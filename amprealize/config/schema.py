"""Pydantic models for ~/.amprealize/config.yaml local configuration.

This schema defines the hierarchical config file that all Amprealize tools read from.
It is separate from the cloud-focused settings.py — this schema targets local
developer experience: storage backend selection, auth mode, MCP transport, etc.

Config Resolution Order (highest priority wins):
1. CLI flags (--port 8080)
2. Environment variables (AMPREALIZE_STORAGE_BACKEND=sqlite)
3. Project config (.amprealize/config.yaml in project root)
4. User config (~/.amprealize/config.yaml)
5. Built-in defaults (defined here)

Config Versions:
- v1: Flat config with single context (legacy)
- v2: Named contexts with kubectl-style switching
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field, PrivateAttr, field_validator, model_validator


# ==============================================================================
# Environment Variable Expansion
# ==============================================================================

ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def expand_env_vars(value: str) -> str:
    """Expand environment variable references in a string.

    Supports two syntaxes:
    - ${VAR_NAME} - standard syntax with braces
    - $VAR_NAME - shell-style syntax

    Missing variables are replaced with empty string.

    Examples:
        postgresql://${PGUSER}:${PGPASSWORD}@${PGHOST}:${PGPORT}/db
        postgresql://$PGUSER:$PGPASSWORD@localhost:5432/db
    """
    def replace_match(match: re.Match) -> str:
        # Group 1 is ${VAR}, Group 2 is $VAR
        var_name = match.group(1) or match.group(2)
        return os.environ.get(var_name, "")

    return ENV_VAR_PATTERN.sub(replace_match, value)


class ServerConfig(BaseModel):
    """Local API/MCP server settings."""

    host: str = "0.0.0.0"
    port: int = 8765


class PostgresStorageConfig(BaseModel):
    """PostgreSQL connection settings.

    DSN values support environment variable expansion:
    - ${VAR_NAME} - braces syntax
    - $VAR_NAME - shell-style syntax

    Examples:
        dsn: postgresql://${PGUSER}:${PGPASSWORD}@localhost:5432/amprealize
        dsn: postgresql://$PGUSER:$PGPASSWORD@${PGHOST}:${PGPORT:-5432}/db
    """
    model_config = {"extra": "allow"}  # Allow temp fields during init

    dsn: str = "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize"
    telemetry_dsn: str = "postgresql://telemetry:telemetry_dev@localhost:5433/telemetry"

    # Raw values before env expansion (for display/serialization)
    _raw_dsn: str = PrivateAttr(default="")
    _raw_telemetry_dsn: str = PrivateAttr(default="")

    @model_validator(mode="before")
    @classmethod
    def store_raw_and_expand(cls, data: Any) -> Any:
        """Store raw DSN values and expand environment variables."""
        if isinstance(data, dict):
            # Store raw values before expansion
            if "dsn" in data and isinstance(data["dsn"], str):
                raw_dsn = data["dsn"]
                data["dsn"] = expand_env_vars(data["dsn"])
                data["_raw_dsn_init"] = raw_dsn
            if "telemetry_dsn" in data and isinstance(data["telemetry_dsn"], str):
                raw_tel = data["telemetry_dsn"]
                data["telemetry_dsn"] = expand_env_vars(data["telemetry_dsn"])
                data["_raw_telemetry_dsn_init"] = raw_tel
        return data

    def model_post_init(self, __context: Any) -> None:
        """Set private attributes from extra fields after init."""
        # Get from extra and set as private attrs
        if hasattr(self, "_raw_dsn_init"):
            object.__setattr__(self, "_raw_dsn", getattr(self, "_raw_dsn_init"))
        if hasattr(self, "_raw_telemetry_dsn_init"):
            object.__setattr__(self, "_raw_telemetry_dsn", getattr(self, "_raw_telemetry_dsn_init"))

    def get_raw_dsn(self) -> str:
        """Get the DSN with env vars unexpanded (for config display)."""
        return self._raw_dsn if self._raw_dsn else self.dsn

    def get_raw_telemetry_dsn(self) -> str:
        """Get the telemetry DSN with env vars unexpanded."""
        return self._raw_telemetry_dsn if self._raw_telemetry_dsn else self.telemetry_dsn

    def has_env_vars(self) -> bool:
        """Check if DSN contains environment variable references."""
        raw = self._raw_dsn if self._raw_dsn else self.dsn
        return bool(ENV_VAR_PATTERN.search(raw))


class SqliteStorageConfig(BaseModel):
    """SQLite storage settings."""

    path: str = "~/.amprealize/data/amprealize.db"


class StorageConfig(BaseModel):
    """Storage backend configuration."""

    backend: Literal["postgres", "sqlite", "memory"] = "sqlite"
    postgres: PostgresStorageConfig = Field(default_factory=PostgresStorageConfig)
    sqlite: SqliteStorageConfig = Field(default_factory=SqliteStorageConfig)

    @field_validator("backend")
    @classmethod
    def validate_backend(cls, v: str) -> str:
        allowed = ("postgres", "sqlite", "memory")
        if v not in allowed:
            raise ValueError(f"storage.backend must be one of {allowed}, got '{v}'")
        return v


class CloudAuthConfig(BaseModel):
    """Cloud authentication settings."""

    server_url: str = "https://api.breakeramp.dev"
    token_store: Literal["keyring", "file"] = "keyring"


class AuthConfig(BaseModel):
    """Authentication configuration."""

    mode: Literal["local", "cloud"] = "local"
    cloud: CloudAuthConfig = Field(default_factory=CloudAuthConfig)


class McpConfig(BaseModel):
    """MCP server transport configuration."""

    transport: Literal["stdio", "sse"] = "stdio"


class ComposeConfig(BaseModel):
    """Docker-compose specific settings."""

    file: Optional[str] = None
    project_name: str = "amprealize"
    profiles: list[str] = Field(default_factory=list)


class InfraConfig(BaseModel):
    """Infrastructure management configuration.

    managed_by controls which provider ``amprealize infra`` delegates to:
    - ``auto``           – detect best available (breakeramp → compose → none)
    - ``breakeramp``     – delegate to the breakeramp CLI
    - ``docker-compose`` – use docker/podman compose directly
    - ``external``       – user manages infra; amprealize skips lifecycle commands
    - ``none``           – no infrastructure management
    """

    managed_by: Literal[
        "auto", "breakeramp", "docker-compose", "external", "none"
    ] = "auto"
    blueprint: Optional[str] = None
    plan_id: Optional[str] = None
    compose: ComposeConfig = Field(default_factory=ComposeConfig)


class LoggingConfig(BaseModel):
    """Logging configuration."""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    format: Literal["json", "text"] = "json"


# ==============================================================================
# Module & Deployment Configuration
# ==============================================================================


class ModulesConfig(BaseModel):
    """Module selection — which feature sets are active.

    Modules are independently toggleable feature groups. Goals is always
    enabled as the base module. Agents and behaviors can be enabled/disabled
    at any time without data loss.
    """

    goals: Literal[True] = True  # Always on — base module
    agents: bool = False
    behaviors: bool = False
    collaboration: bool = False  # Enterprise-only (Starter+)

    @field_validator("goals", mode="before")
    @classmethod
    def goals_always_true(cls, v: Any) -> bool:
        if v is not True and v is not None:
            raise ValueError("goals module cannot be disabled")
        return True


class DeploymentServicesConfig(BaseModel):
    """Per-service overrides for hybrid deployment mode.

    Only meaningful when deployment.mode is 'hybrid'. Each service can
    independently run locally or be delegated to the cloud.
    """

    storage: Literal["local", "cloud"] = "local"
    compute: Literal["local", "cloud"] = "local"


class DeploymentConfig(BaseModel):
    """Deployment mode — where the system runs.

    - local: Everything on this machine (SQLite/Postgres, local auth)
    - cloud: Thin client, everything on Amprealize.io (enterprise only)
    - hybrid: Per-service choice between local and cloud (enterprise only)
    """

    mode: Literal["local", "cloud", "hybrid"] = "local"
    services: DeploymentServicesConfig = Field(
        default_factory=DeploymentServicesConfig
    )
    cloud_url: str = "https://api.amprealize.io"


class AmprealizeConfig(BaseModel):
    """Root configuration model for ~/.amprealize/config.yaml (v1 format).

    This represents the full local config file. Defaults are chosen for
    the simplest local developer experience (sqlite, local auth, stdio MCP).

    Note: For v2 configs with named contexts, use AmprealizeConfigV2.
    """

    version: int = 1
    modules: ModulesConfig = Field(default_factory=ModulesConfig)
    deployment: DeploymentConfig = Field(default_factory=DeploymentConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    mcp: McpConfig = Field(default_factory=McpConfig)
    infra: InfraConfig = Field(default_factory=InfraConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    @field_validator("version")
    @classmethod
    def validate_version(cls, v: int) -> int:
        if v != 1:
            raise ValueError(
                f"Unsupported config version {v}. Only version 1 is supported."
            )
        return v


# ==============================================================================
# V2 Config Models (Named Contexts)
# ==============================================================================


class ContextConfig(BaseModel):
    """Configuration for a single named context.

    Similar to AmprealizeConfig but without version field.
    Each context defines its own storage, auth, and server settings.

    Example:
        contexts:
          local:
            storage:
              backend: sqlite
          cloud:
            storage:
              backend: postgres
              postgres:
                dsn: ${DATABASE_URL}
    """

    modules: ModulesConfig = Field(default_factory=ModulesConfig)
    deployment: DeploymentConfig = Field(default_factory=DeploymentConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    mcp: McpConfig = Field(default_factory=McpConfig)
    infra: InfraConfig = Field(default_factory=InfraConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    # Optional context metadata
    description: Optional[str] = None

    def to_amprealize_config(self) -> AmprealizeConfig:
        """Convert to AmprealizeConfig (v1 format) for compatibility."""
        return AmprealizeConfig(
            version=1,
            modules=self.modules,
            deployment=self.deployment,
            server=self.server,
            storage=self.storage,
            auth=self.auth,
            mcp=self.mcp,
            infra=self.infra,
            logging=self.logging,
        )


class AmprealizeConfigV2(BaseModel):
    """Root configuration model for v2 config format with named contexts.

    Enables kubectl-style context switching between different environments.

    Example:
        version: 2
        current_context: local
        contexts:
          local:
            storage:
              backend: sqlite
          staging:
            storage:
              backend: postgres
              postgres:
                dsn: ${STAGING_DATABASE_URL}
    """

    version: Literal[2] = 2
    current_context: str = "default"
    contexts: Dict[str, ContextConfig] = Field(default_factory=dict)

    @field_validator("version")
    @classmethod
    def validate_version(cls, v: int) -> int:
        if v != 2:
            raise ValueError(
                f"AmprealizeConfigV2 requires version=2, got {v}"
            )
        return v

    @model_validator(mode="after")
    def validate_current_context_exists(self) -> "AmprealizeConfigV2":
        """Ensure current_context references an existing context."""
        if self.contexts and self.current_context not in self.contexts:
            available = list(self.contexts.keys())
            raise ValueError(
                f"current_context '{self.current_context}' not found. "
                f"Available contexts: {available}"
            )
        return self

    def get_current_config(self) -> ContextConfig:
        """Get the ContextConfig for the current context."""
        if not self.contexts:
            return ContextConfig()
        return self.contexts.get(self.current_context, ContextConfig())

    def switch_context(self, name: str) -> None:
        """Switch to a different context.

        Raises ValueError if context doesn't exist.
        """
        if name not in self.contexts:
            available = list(self.contexts.keys())
            raise ValueError(
                f"Context '{name}' not found. Available: {available}"
            )
        self.current_context = name

    def add_context(self, name: str, config: ContextConfig) -> None:
        """Add a new named context."""
        if name in self.contexts:
            raise ValueError(f"Context '{name}' already exists")
        self.contexts[name] = config

    def remove_context(self, name: str) -> None:
        """Remove a named context.

        Raises ValueError if trying to remove current context.
        """
        if name == self.current_context:
            raise ValueError("Cannot remove current context")
        if name not in self.contexts:
            raise ValueError(f"Context '{name}' not found")
        del self.contexts[name]

    @classmethod
    def from_v1(cls, v1_config: AmprealizeConfig) -> "AmprealizeConfigV2":
        """Migrate from v1 config to v2 format.

        Creates a 'default' context from the v1 settings.
        """
        default_context = ContextConfig(
            modules=v1_config.modules,
            deployment=v1_config.deployment,
            server=v1_config.server,
            storage=v1_config.storage,
            auth=v1_config.auth,
            mcp=v1_config.mcp,
            infra=v1_config.infra,
            logging=v1_config.logging,
        )
        return cls(
            version=2,
            current_context="default",
            contexts={"default": default_context},
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for YAML output."""
        return {
            "version": self.version,
            "current_context": self.current_context,
            "contexts": {
                name: ctx.model_dump(exclude_none=True, exclude_defaults=True)
                for name, ctx in self.contexts.items()
            },
        }
