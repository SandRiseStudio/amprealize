"""BreakerAmp Service - Infrastructure orchestration with blueprints.

This module contains the core BreakerAmpService class that provides
plan/apply/destroy workflow for containerized environments.
"""

import json
import os
import re
import shutil
import socket
import sys
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Set, Tuple

import yaml

from .executors.base import ContainerRunConfig, ExecutorError, MachineCapableExecutor, MachineInfo, ResourceCapableExecutor, ResourceHealthResult
from .executors.podman import PodmanExecutor
from .hooks import BreakerAmpHooks
from .models import (
    ApplyRequest,
    ApplyResponse,
    AuditEntry,
    Blueprint,
    DestroyRequest,
    DestroyResponse,
    EnvironmentDefinition,
    EnvironmentEstimates,
    EnvironmentManifest,
    HealthCheck,
    InfrastructureConfig,
    MigrationConfig,
    MigrationSpec,
    NoOpProgress,
    PlanForTestsRequest,
    PlanForTestsResponse,
    PlanRequest,
    PlanResponse,
    ProgressCallback,
    RunTestsRequest,
    RunTestsResponse,
    RuntimeConfig,
    ServiceSpec,
    ServiceStatus,
    StatusEvent,
    StatusResponse,
    TelemetryData,
    TestSuiteDefinition,
)


class BandwidthEnforcer:
    """Enforces network bandwidth limits during apply operations."""

    def __init__(self, limit_mbps: Optional[int] = None):
        self.limit_mbps = limit_mbps
        self._last_rx_bytes: Dict[str, int] = {}
        self._last_tx_bytes: Dict[str, int] = {}
        self._last_check_time = time.time()

    def check_usage(self, stats: Dict[str, Dict[str, Any]]) -> bool:
        """Returns True if bandwidth is within limits, False otherwise."""
        if not self.limit_mbps:
            return True

        current_time = time.time()
        elapsed = current_time - self._last_check_time
        if elapsed < 1:
            return True

        total_bytes = 0
        for cid, info in stats.items():
            rx = info.get("net_input_bytes", 0)
            tx = info.get("net_output_bytes", 0)

            if cid in self._last_rx_bytes:
                total_bytes += (rx - self._last_rx_bytes[cid])
                total_bytes += (tx - self._last_tx_bytes.get(cid, 0))

            self._last_rx_bytes[cid] = rx
            self._last_tx_bytes[cid] = tx

        self._last_check_time = current_time
        mbps = (total_bytes * 8) / (elapsed * 1_000_000)
        return mbps <= self.limit_mbps

    def get_current_usage_mbps(self, stats: Dict[str, Dict[str, Any]]) -> float:
        """Get current usage in Mbps."""
        # Simplified - actual implementation would track deltas
        return 0.0


class BreakerAmpService:
    """Infrastructure-as-Code orchestration service.

    Provides Terraform-like plan/apply/destroy workflow for containerized
    development environments using blueprints.

    Example:
        from breakeramp import BreakerAmpService
        from breakeramp.executors import PodmanExecutor

        service = BreakerAmpService(executor=PodmanExecutor())

        # Plan an environment
        plan = service.plan(PlanRequest(
            blueprint_id="postgres-dev",
            environment="development"
        ))

        # Apply the plan
        result = service.apply(ApplyRequest(plan_id=plan.plan_id))

        # Clean up
        service.destroy(DestroyRequest(amp_run_id=result.amp_run_id, reason="Done"))

    Args:
        executor: Container executor (defaults to PodmanExecutor)
        hooks: Optional hooks for external integrations
        base_dir: Base directory for storage (defaults to ~/.amprealize/breakeramp)
    """

    def __init__(
        self,
        executor: Optional[MachineCapableExecutor] = None,
        hooks: Optional[BreakerAmpHooks] = None,
        base_dir: Optional[Path] = None,
    ):
        self.executor = executor or PodmanExecutor()
        self.hooks = hooks or BreakerAmpHooks()

        # Initialize storage paths
        self.base_dir = base_dir or Path.home() / ".amprealize" / "breakeramp"
        self.manifests_dir = self.base_dir / "manifests"
        self.environments_dir = self.base_dir / "environments"
        self.user_blueprints_dir = self.base_dir / "blueprints"

        # Package blueprints directory
        self.pkg_blueprints_dir = Path(__file__).parent / "blueprints"

        self.manifests_dir.mkdir(parents=True, exist_ok=True)
        self.environments_dir.mkdir(parents=True, exist_ok=True)
        self.user_blueprints_dir.mkdir(parents=True, exist_ok=True)

        self.environments: Dict[str, EnvironmentDefinition] = {}
        self.environment_manifest_path: Optional[Path] = None

        # Auto-load .env file if present (for OAuth, secrets, etc.)
        self._load_dotenv_if_present()

        # Load environments from file if available
        self.load_environments()

        # Register default environments if none loaded
        if not self.environments:
            self.register_environment(
                EnvironmentDefinition(name="development", description="Local development environment")
            )
            self.register_environment(
                EnvironmentDefinition(name="staging", description="Staging environment")
            )
            self.register_environment(
                EnvironmentDefinition(
                    name="production",
                    description="Production environment",
                    default_compliance_tier="strict",
                )
            )

    # =========================================================================
    # Environment Management
    # =========================================================================

    def _load_dotenv_if_present(self) -> None:
        """Auto-load .env file from cwd or the workspace repo root.

        This ensures that environment variables like GOOGLE_CLIENT_ID,
        GITHUB_CLIENT_SECRET, etc. are available for blueprint expansion
        without requiring manual `source .env` before running breakeramp.

        Search order:
          1. BREAKERAMP_DOTENV_PATH env var (explicit override)
          2. Current working directory (.env)
          3. Workspace repo root (for example ~/amprealize/.env during transition, or detected via environments.yaml location)
        """
        candidates: List[Path] = []

        # 1. Explicit override
        override = os.environ.get("BREAKERAMP_DOTENV_PATH")
        if override:
            candidates.append(Path(override).expanduser())

        # 2. Current working directory
        candidates.append(Path.cwd() / ".env")

        # 3. Common amprealize locations
        home = Path.home()
        candidates.extend([
            home / "amprealize" / ".env",
            home / "src" / "amprealize" / ".env",
            home / "projects" / "amprealize" / ".env",
        ])

        # 4. If we found an environments.yaml, check its parent
        if self.environment_manifest_path:
            candidates.append(self.environment_manifest_path.parent / ".env")

        for dotenv_path in candidates:
            if dotenv_path.exists():
                self._parse_dotenv_file(dotenv_path)
                return

    def _parse_dotenv_file(self, path: Path) -> None:
        """Parse a .env file and set environment variables (if not already set).

        This is a minimal parser that handles:
          - KEY=value
          - KEY="value with spaces"
          - KEY='value with spaces'
          - # comments
          - Empty lines

        Variables already set in the environment are NOT overwritten.
        """
        try:
            with open(path, "r") as f:
                for line in f:
                    line = line.strip()
                    # Skip empty lines and comments
                    if not line or line.startswith("#"):
                        continue
                    # Skip lines without =
                    if "=" not in line:
                        continue

                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip()

                    # Remove surrounding quotes
                    if (value.startswith('"') and value.endswith('"')) or \
                       (value.startswith("'") and value.endswith("'")):
                        value = value[1:-1]

                    # Only set if not already in environment (don't override)
                    if key and key not in os.environ:
                        os.environ[key] = value
        except Exception:
            # Silently ignore parse errors - .env loading is best-effort
            pass

    def load_environments(self) -> None:
        """Load environment definitions from a YAML file."""
        path = self._resolve_environment_file()
        if not path or not path.exists():
            return

        self.environment_manifest_path = path

        try:
            with open(path, "r") as f:
                data = yaml.safe_load(f)

            if data and "environments" in data:
                for env_name, env_data in data["environments"].items():
                    if not isinstance(env_data, dict):
                        print(f"Warning: Environment '{env_name}' must be a mapping")
                        continue

                    env_payload = env_data.copy()
                    env_payload.setdefault("name", env_name)

                    if "compliance_tier" in env_payload and "default_compliance_tier" not in env_payload:
                        env_payload["default_compliance_tier"] = env_payload.pop("compliance_tier")
                    if "lifetime" in env_payload and "default_lifetime" not in env_payload:
                        env_payload["default_lifetime"] = env_payload.pop("lifetime")
                    if "blueprint_id" in env_payload and "infrastructure" not in env_payload:
                        env_payload["infrastructure"] = {"blueprint_id": env_payload.pop("blueprint_id")}
                    if (
                        "active_modules" not in env_payload
                        and isinstance(env_payload.get("infrastructure"), dict)
                        and "active_modules" in env_payload["infrastructure"]
                    ):
                        env_payload["active_modules"] = env_payload["infrastructure"].get("active_modules")

                    # Convert migrations dict to MigrationConfig model
                    if "migrations" in env_payload and isinstance(env_payload["migrations"], dict):
                        mig_data = env_payload["migrations"]
                        migration_specs = [
                            MigrationSpec(**m) for m in mig_data.get("migrations", [])
                        ]
                        env_payload["migrations"] = MigrationConfig(
                            auto_run=mig_data.get("auto_run", True),
                            migrations=migration_specs,
                        )

                    try:
                        env_def = EnvironmentDefinition(**env_payload)
                        self.register_environment(env_def)
                    except Exception as e:
                        print(f"Warning: Failed to parse environment '{env_name}': {e}")
        except Exception as e:
            print(f"Warning: Failed to load environments from {path}: {e}")

    def register_environment(self, env_def: EnvironmentDefinition) -> None:
        """Register an environment definition."""
        self.environments[env_def.name] = env_def

    def _infer_repo_root(self) -> Path:
        """Infer the repository root directory.

        Uses AMPREALIZE_REPO_ROOT env var if set, otherwise infers from
        the environment manifest path. When the manifest lives inside a
        ``config/breakeramp/`` subdirectory, walks up to the true repo root
        rather than returning the manifest's immediate parent.
        """
        env_val = os.environ.get("AMPREALIZE_REPO_ROOT")
        if env_val:
            return Path(env_val)

        if self.environment_manifest_path:
            manifest_dir = self.environment_manifest_path.parent
            # config/breakeramp/environments.yaml → repo root is 2 levels up
            if manifest_dir.name == "breakeramp" and manifest_dir.parent.name == "config":
                return manifest_dir.parent.parent
            return manifest_dir

        return Path.cwd()

    def _resolve_environment_file(self) -> Optional[Path]:
        """Resolve the environment configuration file path."""
        override = os.environ.get("AMPREALIZE_ENV_FILE") or os.environ.get("BREAKERAMP_ENV_FILE")
        candidates = []
        if override:
            candidates.append(Path(override).expanduser())

        cwd = Path.cwd()
        candidates.append(cwd / "config" / "breakeramp" / "environments.yaml")
        candidates.append(cwd / "environments.yaml")

        package_root = Path(__file__).resolve().parents[2]
        candidates.append(package_root / "config" / "breakeramp" / "environments.yaml")
        candidates.append(package_root / "environments.yaml")

        # Common developer layouts (best-effort; helps when invoking CLI from outside repo)
        home = Path.home()
        candidates.append(home / "amprealize" / "environments.yaml")
        candidates.append(home / "src" / "amprealize" / "environments.yaml")
        candidates.append(home / "projects" / "amprealize" / "environments.yaml")

        for candidate in candidates:
            if candidate.exists():
                return candidate

        if override:
            return Path(override).expanduser()
        return None

    def validate_environment_file(
        self, path: Optional[str | Path] = None, strict: bool = True
    ) -> Dict[str, Any]:
        """Validate an environment configuration file.

        Args:
            path: Path to environments.yaml (uses resolved path if not provided)
            strict: If True, raises errors on unknown fields (default: True)

        Returns:
            Validation result dict with:
                - valid: bool
                - path: str (resolved path)
                - environments: list of environment names
                - errors: list of error messages (if invalid)
                - warnings: list of warning messages

        Raises:
            FileNotFoundError: If the file does not exist
            ValueError: If strict=True and validation fails
        """
        from pydantic import ValidationError

        # Resolve path
        if path:
            file_path = Path(path)
        else:
            file_path = self._resolve_environment_file()

        if not file_path or not file_path.exists():
            raise FileNotFoundError(
                f"Environment file not found: {path or 'no file resolved'}"
            )

        result: Dict[str, Any] = {
            "valid": False,
            "path": str(file_path),
            "environments": [],
            "errors": [],
            "warnings": [],
        }

        try:
            # Use strict validation model
            manifest = EnvironmentManifest.validate_file(file_path)
            result["valid"] = True
            result["environments"] = manifest.list_environments()

            # Add warnings for common issues
            for env_name, env_def in manifest.environments.items():
                if env_def.runtime.provider == "podman" and not env_def.runtime.podman_machine:
                    result["warnings"].append(
                        f"Environment '{env_name}': podman provider without podman_machine set"
                    )
                if env_def.default_compliance_tier == "strict" and env_def.runtime.auto_start:
                    result["warnings"].append(
                        f"Environment '{env_name}': strict compliance with auto_start=true (consider false)"
                    )

        except ValidationError as e:
            result["errors"] = [str(err) for err in e.errors()]
            if strict:
                raise ValueError(
                    f"Environment file validation failed: {file_path}\n"
                    + "\n".join(result["errors"])
                ) from e
        except yaml.YAMLError as e:
            result["errors"] = [f"YAML parse error: {e}"]
            if strict:
                raise ValueError(f"Invalid YAML in {file_path}: {e}") from e
        except Exception as e:
            result["errors"] = [str(e)]
            if strict:
                raise

        return result

    # =========================================================================
    # Blueprint Management
    # =========================================================================

    def _resolve_blueprint(
        self, blueprint_id: str, *, variables: Optional[Dict[str, Any]] = None
    ) -> Blueprint:
        """Resolve a blueprint by ID or path."""
        # 1. Try as absolute path
        path = Path(blueprint_id)
        if path.exists() and path.is_file():
            return self._load_blueprint_from_file(path, variables=variables)

        # 2. Try in user blueprints dir
        for ext in [".yaml", ".yml", ".json"]:
            path = self.user_blueprints_dir / f"{blueprint_id}{ext}"
            if path.exists():
                return self._load_blueprint_from_file(path, variables=variables)

        # 3. Try in package blueprints dir
        for ext in [".yaml", ".yml", ".json"]:
            path = self.pkg_blueprints_dir / f"{blueprint_id}{ext}"
            if path.exists():
                return self._load_blueprint_from_file(path, variables=variables)

        raise ValueError(f"Blueprint '{blueprint_id}' not found")

    def _expand_env_vars(
        self, data: Any, variables: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Recursively expand environment variables in data structures.

        Handles ${VAR} and ${VAR:-default} syntax in strings.

        Priority:
        1. os.environ (always takes precedence for actual secret values)
        2. variables dict (for template values like AMPREALIZE_REPO_ROOT)
        3. default value from ${VAR:-default} syntax
        """
        if isinstance(data, str):
            # Pattern to match ${VAR} or ${VAR:-default}
            pattern = re.compile(r'\$\{([^}:]+)(?::-([^}]*))?\}')

            def replace_var(match):
                var_name = match.group(1)
                default_value = match.group(2) if match.group(2) is not None else ""
                # ALWAYS check os.environ first for actual secret values
                if var_name in os.environ:
                    return os.environ[var_name]
                # Then check variables dict for template values
                if variables and var_name in variables:
                    value = variables.get(var_name)
                    if value is None:
                        return ""
                    # If the variable value is itself a template, skip it and use default
                    str_value = str(value)
                    if str_value.startswith("${"):
                        return default_value
                    return str_value
                return default_value

            return pattern.sub(replace_var, data)
        elif isinstance(data, dict):
            return {k: self._expand_env_vars(v, variables) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._expand_env_vars(item, variables) for item in data]
        else:
            return data

    def _load_blueprint_from_file(
        self, path: Path, *, variables: Optional[Dict[str, Any]] = None
    ) -> Blueprint:
        """Load a blueprint from a file, expanding environment variables."""
        with open(path, "r") as f:
            if path.suffix == ".json":
                data = json.load(f)
            else:
                data = yaml.safe_load(f)
        # Expand environment variables in the loaded data
        data = self._expand_env_vars(data, variables)
        return Blueprint(**data)

    def _discover_packaged_blueprints(self) -> Dict[str, Path]:
        """Discover all packaged blueprints."""
        blueprints: Dict[str, Path] = {}

        if self.pkg_blueprints_dir.exists():
            for ext in ["*.yaml", "*.yml", "*.json"]:
                for path in self.pkg_blueprints_dir.glob(ext):
                    # Use stem as key (e.g., "postgres-dev" from "postgres-dev.yaml")
                    blueprints[path.stem] = path

        return blueprints

    def list_blueprints(self) -> List[Dict[str, Any]]:
        """List all available blueprints."""
        result = []

        # Packaged blueprints
        packaged = self._discover_packaged_blueprints()
        for name, path in packaged.items():
            result.append({
                "id": name,
                "path": str(path),
                "source": "package",
            })

        # User blueprints
        if self.user_blueprints_dir.exists():
            for ext in ["*.yaml", "*.yml", "*.json"]:
                for path in self.user_blueprints_dir.glob(ext):
                    result.append({
                        "id": path.stem,
                        "path": str(path),
                        "source": "user",
                    })

        return result

    def _calculate_blueprint_resources(self, blueprint: Blueprint) -> tuple[int, float, int]:
        """Calculate total resources required by a blueprint."""
        total_memory = 0
        total_cpus = 0.0
        total_bandwidth = 0
        for service in blueprint.services.values():
            if service.memory_mb:
                total_memory += service.memory_mb
            if service.cpu_cores:
                total_cpus += service.cpu_cores
            if service.bandwidth_mbps:
                total_bandwidth += service.bandwidth_mbps
        return total_memory, total_cpus, total_bandwidth

    # =========================================================================
    # Runtime Management
    # =========================================================================

    def _ensure_runtime_ready_from_run_manifest(
        self, run: Dict[str, Any], *, force: bool = True
    ) -> None:
        """Ensure runtime is ready using the stored run manifest.

        This is needed for `destroy`/`status` when the user's default Podman
        connection points at a different machine than the one used for apply.
        """
        runtime_payload = run.get("runtime") or {}
        if not isinstance(runtime_payload, dict):
            return

        provider = runtime_payload.get("provider")
        if provider not in ("podman", "docker"):
            return

        if not isinstance(self.executor, MachineCapableExecutor):
            return

        runtime = RuntimeConfig(**runtime_payload)
        env_def = EnvironmentDefinition(
            name=run.get("environment", "unknown"),
            runtime=runtime,
            infrastructure=InfrastructureConfig(),
            variables=(run.get("variables") or {}) if isinstance(run.get("variables"), dict) else {},
        )
        self._ensure_runtime_ready(env_def, force=force)

        # Persist any resolved runtime fields back onto the run manifest.
        # This makes plan/apply/status/destroy deterministic across process boundaries
        # (e.g. when the user's default Podman connection points elsewhere).
        try:
            if isinstance(run.get("runtime"), dict):
                if env_def.runtime.podman_machine:
                    run["runtime"]["podman_machine"] = env_def.runtime.podman_machine
                if env_def.runtime.podman_connection:
                    run["runtime"]["podman_connection"] = env_def.runtime.podman_connection
        except Exception:
            # Best-effort; runtime readiness is the primary goal.
            pass

    def _ensure_runtime_ready(
        self, env_def: EnvironmentDefinition, *, force: bool = False
    ) -> None:
        """Ensure the container runtime is ready and configure executor connection."""
        runtime = env_def.runtime
        if runtime.provider not in ("podman", "docker"):
            return

        if not isinstance(self.executor, MachineCapableExecutor):
            return

        machine_name = runtime.podman_machine or "podman-machine-default"

        try:
            machine = self.executor.get_machine(machine_name)
        except ExecutorError:
            if force:
                print(f"Warning: Could not check machine status", file=sys.stderr)
                return
            raise

        if not machine:
            if runtime.auto_init:
                disk_gb = runtime.machine_disk_size_gb or 20  # Default to 20GB if not specified
                print(
                    f"Auto-initializing Podman machine '{machine_name}' "
                    f"(CPUs: {runtime.cpu_limit or 'default'}, "
                    f"Memory: {runtime.memory_limit_mb or 'default'}MB, "
                    f"Disk: {disk_gb}GB)",
                    file=sys.stderr
                )
                self.executor.init_machine(
                    machine_name,
                    cpus=runtime.cpu_limit,
                    memory_mb=runtime.memory_limit_mb,
                    disk_gb=disk_gb,
                )
                machine = self.executor.get_machine(machine_name)
            elif force:
                print(f"Warning: Machine '{machine_name}' not found", file=sys.stderr)
                return
            else:
                raise RuntimeError(
                    f"Podman machine '{machine_name}' not found. "
                    f"Enable auto_init or run 'podman machine init {machine_name}'."
                )

        if machine and not machine.running:
            if runtime.auto_start:
                try:
                    self.executor.start_machine(machine_name)
                except ExecutorError as exc:
                    stderr = (exc.stderr or "").lower()
                    if "only one vm can be active at a time" not in stderr:
                        raise

                    # Podman on macOS currently allows only one VM active at a time.
                    # When another machine is already running, proactively stop it and retry.
                    try:
                        self.executor.stop_unused_machines(preserve_machines=[machine_name])
                        self.executor.start_machine(machine_name)
                    except Exception:
                        raise exc
            elif force:
                print(f"Warning: Machine '{machine_name}' is stopped", file=sys.stderr)
                return
            else:
                raise RuntimeError(
                    f"Podman machine '{machine_name}' is stopped. "
                    f"Start it or enable auto_start."
                )

        # Set the executor connection to use the correct Podman connection.
        # Deterministic rules (prevents "containers exist but on the other connection" confusion):
        # 1) Respect explicit runtime.podman_connection if set
        # 2) Prefer the host's default Podman connection for this machine
        # 3) Fall back to <machine> then <machine>-root if needed
        from .executors.podman import PodmanExecutor
        if isinstance(self.executor, PodmanExecutor):
            connection_name: Optional[str] = None

            if runtime.podman_connection:
                connection_name = runtime.podman_connection
            else:
                try:
                    connection_name = self.executor.resolve_connection_for_machine(machine_name)
                except Exception:
                    connection_name = None

            if not connection_name:
                connection_name = machine_name
                try:
                    inspect = self.executor.inspect_machine(machine_name)
                    if inspect.get("Rootful", False) and self.executor.connection_exists(f"{machine_name}-root"):
                        connection_name = f"{machine_name}-root"
                except Exception:
                    pass

            self.executor.connection = connection_name
            runtime.podman_connection = connection_name

        self._verify_podman_resources(machine_name, runtime, env_def.name, force=force)

    def _verify_podman_resources(
        self,
        machine_name: str,
        runtime: RuntimeConfig,
        environment: str,
        *,
        force: bool,
    ) -> None:
        """Verify the Podman machine has sufficient resources."""
        if not isinstance(self.executor, MachineCapableExecutor):
            return

        warnings = []
        try:
            inspect = self.executor.inspect_machine(machine_name)
            config = inspect.get("Config", {})
        except Exception as exc:
            if force:
                print(f"Warning: Unable to inspect machine '{machine_name}': {exc}", file=sys.stderr)
                return
            raise

        memory_bytes = config.get("Memory")
        cpus = config.get("CPUs")

        if runtime.memory_limit_mb and isinstance(memory_bytes, int):
            allocated_mb = memory_bytes // (1024 * 1024)
            if allocated_mb < runtime.memory_limit_mb:
                warnings.append(
                    f"configured memory {allocated_mb}MB < requested {runtime.memory_limit_mb}MB"
                )

        if runtime.cpu_limit and isinstance(cpus, int) and cpus < runtime.cpu_limit:
            warnings.append(f"configured CPUs {cpus} < requested {runtime.cpu_limit}")

        if warnings:
            message = (
                f"Machine '{machine_name}' does not meet requirements for '{environment}': "
                + "; ".join(warnings)
            )
            self.hooks.emit_metric(
                "breakeramp.runtime.resource_warning",
                machine=machine_name,
                environment=environment,
                warnings=warnings,
            )
            if force:
                print(f"Warning: {message}", file=sys.stderr)
            else:
                raise RuntimeError(message)
        else:
            self.hooks.emit_metric(
                "breakeramp.runtime.resource_ok",
                machine=machine_name,
                environment=environment,
                memory_mb=(memory_bytes // (1024 * 1024)) if isinstance(memory_bytes, int) else None,
                cpus=cpus,
            )

    def _perform_tiered_cleanup(
        self,
        request: "ApplyRequest",
        initial_warnings: List[str],
    ) -> Tuple[bool, List[str]]:
        """Perform tiered auto-cleanup with escalating aggressiveness.

        This method now performs SEPARATE cleanup for host vs VM resources:
        - If only HOST is low: attempt host cleanup first (cache, tmp files)
        - If only VM is low: perform standard VM cleanup (podman system prune)
        - If BOTH are low: attempt both cleanups

        Cleanup tiers (for VM):
        1. Standard: containers, images, cache (no volumes)
        2. Aggressive: all options except volumes (+ networks, pods, logs)
        3. Full: include volumes (only if auto_cleanup_include_volumes=True)

        Args:
            request: The apply request with cleanup configuration
            initial_warnings: Initial resource warnings

        Returns:
            Tuple of (healthy: bool, warnings: List[str]) after cleanup attempts
        """
        from .executors.base import ResourceCapableExecutor

        if not isinstance(self.executor, ResourceCapableExecutor):
            return False, initial_warnings

        max_retries = request.auto_cleanup_max_retries
        total_space_freed_mb = 0.0
        total_host_space_freed_mb = 0.0
        current_warnings = initial_warnings

        # Get detailed health info to distinguish host vs VM issues
        detailed_health: Optional[ResourceHealthResult] = None
        if hasattr(self.executor, 'check_resource_health_detailed'):
            detailed_health = self.executor.check_resource_health_detailed(
                min_disk_gb=request.min_disk_gb,
                min_memory_mb=request.min_memory_mb,
            )
            self.hooks.emit_metric(
                "breakeramp.apply.detailed_health_check",
                host_healthy=detailed_health.host_healthy,
                vm_healthy=detailed_health.vm_healthy,
                only_host_unhealthy=detailed_health.only_host_unhealthy,
                only_vm_unhealthy=detailed_health.only_vm_unhealthy,
                host_warnings=detailed_health.host_warnings,
                vm_warnings=detailed_health.vm_warnings,
            )

        # Step 1: If only HOST is unhealthy, try host cleanup first
        if detailed_health and detailed_health.only_host_unhealthy:
            self.hooks.emit_metric(
                "breakeramp.apply.host_only_cleanup_triggered",
                host_warnings=detailed_health.host_warnings,
            )

            # Attempt host cleanup
            if hasattr(self.executor, 'mitigate_host_resources'):
                try:
                    host_cleanup = self.executor.mitigate_host_resources(
                        dry_run=False,
                        clean_container_cache=True,
                        clean_tmp_files=True,
                        aggressive=request.auto_cleanup_aggressive,
                    )

                    total_host_space_freed_mb += host_cleanup.host_space_reclaimed_mb

                    self.hooks.emit_metric(
                        "breakeramp.apply.host_cleanup_completed",
                        space_reclaimed_mb=host_cleanup.host_space_reclaimed_mb,
                        cache_cleared=host_cleanup.cache_cleared,
                        errors=host_cleanup.errors,
                    )
                except Exception as e:
                    self.hooks.emit_metric(
                        "breakeramp.apply.host_cleanup_error",
                        error=str(e),
                    )

            # Re-check detailed health
            detailed_health = self.executor.check_resource_health_detailed(
                min_disk_gb=request.min_disk_gb,
                min_memory_mb=request.min_memory_mb,
            )

            if detailed_health.host_healthy and detailed_health.vm_healthy:
                self.hooks.emit_metric(
                    "breakeramp.apply.host_cleanup_success",
                    total_host_space_freed_mb=total_host_space_freed_mb,
                )
                return True, []

            # If host is STILL unhealthy after cleanup, check if we should allow override
            if not detailed_health.host_healthy:
                # If enabled, try machine scale-down/removal to reclaim host disk.
                # This is useful on macOS where Podman machine disk images consume host space.
                if request.auto_cleanup_scale_down:
                    from .executors.podman import PodmanExecutor

                    if isinstance(self.executor, PodmanExecutor):
                        try:
                            stopped_machines = self.executor.stop_unused_machines(
                                preserve_current=True,
                            )
                            if stopped_machines:
                                self.hooks.emit_metric(
                                    "breakeramp.apply.host_only_machines_stopped",
                                    machines=stopped_machines,
                                    count=len(stopped_machines),
                                )

                            if request.auto_cleanup_remove_machines:
                                scale_result = self.executor.scale_down_machines(
                                    keep_count=1,
                                    remove_stopped=True,
                                )
                                if scale_result.get("removed"):
                                    total_host_space_freed_mb += scale_result.get("disk_freed_gb", 0) * 1024
                                    self.hooks.emit_metric(
                                        "breakeramp.apply.host_only_machines_removed",
                                        machines=scale_result.get("removed", []),
                                        disk_freed_gb=scale_result.get("disk_freed_gb", 0),
                                    )

                            detailed_health = self.executor.check_resource_health_detailed(
                                min_disk_gb=request.min_disk_gb,
                                min_memory_mb=request.min_memory_mb,
                            )
                            if detailed_health.host_healthy and detailed_health.vm_healthy:
                                return True, detailed_health.host_warnings
                        except Exception as e:
                            self.hooks.emit_metric(
                                "breakeramp.apply.host_only_machine_cleanup_error",
                                error=str(e),
                            )

                if request.allow_host_resource_warning:
                    self.hooks.emit_metric(
                        "breakeramp.apply.host_warning_override",
                        host_warnings=detailed_health.host_warnings,
                    )
                    # Warn but continue if VM is healthy
                    if detailed_health.vm_healthy:
                        print(
                            f"Warning: Host disk space is low but proceeding with "
                            f"allow_host_resource_warning=True. Warnings:\n"
                            + "\n".join(f"  - {w}" for w in detailed_health.host_warnings),
                            file=sys.stderr,
                        )
                        return True, detailed_health.host_warnings
                else:
                    # Return failure with specific host warning
                    return False, [
                        "Host disk space is low. VM cleanup cannot help. Options:\n"
                        "  1. Free up space on your host disk manually\n"
                        "  2. Use allow_host_resource_warning=True to proceed anyway\n"
                        "  3. Use skip_resource_check=True to skip all checks"
                    ] + detailed_health.host_warnings

        # Step 2: If VM is unhealthy (either only VM or both), perform VM cleanup
        # Define cleanup tiers with escalating aggressiveness
        cleanup_tiers = [
            {
                "name": "standard",
                "prune_containers": True,
                "prune_images": True,
                "prune_volumes": False,
                "prune_cache": True,
                "prune_networks": False,
                "prune_pods": False,
                "prune_logs": False,
                "aggressive": False,
            },
            {
                "name": "aggressive",
                "prune_containers": True,
                "prune_images": True,
                "prune_volumes": False,
                "prune_cache": True,
                "prune_networks": True,
                "prune_pods": True,
                "prune_logs": True,
                "aggressive": True,
            },
        ]

        # Add full cleanup tier if volumes are allowed
        if request.auto_cleanup_include_volumes:
            cleanup_tiers.append({
                "name": "full_with_volumes",
                "prune_containers": True,
                "prune_images": True,
                "prune_volumes": True,  # ⚠️ May lose data
                "prune_cache": True,
                "prune_networks": True,
                "prune_pods": True,
                "prune_logs": True,
                "aggressive": True,
            })

        # Skip to aggressive tier if requested
        start_tier = 1 if request.auto_cleanup_aggressive else 0

        for tier_idx in range(start_tier, len(cleanup_tiers)):
            tier = cleanup_tiers[tier_idx].copy()  # Copy to avoid mutation
            tier_name = tier.pop("name")

            for attempt in range(max_retries):
                self.hooks.emit_metric(
                    "breakeramp.apply.auto_cleanup_triggered",
                    tier=tier_name,
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    warnings=current_warnings,
                )

                try:
                    cleanup_result = self.executor.mitigate_resources(
                        dry_run=False,
                        **tier,
                    )

                    total_space_freed_mb += cleanup_result.space_reclaimed_mb

                    self.hooks.emit_metric(
                        "breakeramp.apply.auto_cleanup_completed",
                        tier=tier_name,
                        attempt=attempt + 1,
                        containers_removed=cleanup_result.containers_removed,
                        images_removed=cleanup_result.images_removed,
                        volumes_removed=cleanup_result.volumes_removed,
                        space_reclaimed_mb=cleanup_result.space_reclaimed_mb,
                        total_space_freed_mb=total_space_freed_mb,
                        success=cleanup_result.success,
                    )

                    # Re-check resources after cleanup
                    healthy, current_warnings = self.executor.check_resource_health(
                        min_disk_gb=request.min_disk_gb,
                        min_memory_mb=request.min_memory_mb,
                    )

                    if healthy:
                        self.hooks.emit_metric(
                            "breakeramp.apply.auto_cleanup_success",
                            tier=tier_name,
                            attempt=attempt + 1,
                            total_space_freed_mb=total_space_freed_mb,
                        )
                        return True, current_warnings

                    # If cleanup freed less than 100MB, don't retry at this tier
                    if cleanup_result.space_reclaimed_mb < 100:
                        self.hooks.emit_metric(
                            "breakeramp.apply.auto_cleanup_tier_exhausted",
                            tier=tier_name,
                            reason="insufficient_space_freed",
                            space_freed_mb=cleanup_result.space_reclaimed_mb,
                        )
                        break  # Move to next tier

                except Exception as e:
                    self.hooks.emit_metric(
                        "breakeramp.apply.auto_cleanup_error",
                        tier=tier_name,
                        attempt=attempt + 1,
                        error=str(e),
                    )
                    # Continue to next attempt/tier

        # All container cleanup tiers exhausted - try machine scale-down if enabled
        if request.auto_cleanup_scale_down:
            from .executors.podman import PodmanExecutor

            if isinstance(self.executor, PodmanExecutor):
                self.hooks.emit_metric(
                    "breakeramp.apply.machine_scale_down_triggered",
                    current_warnings=current_warnings,
                    remove_machines=request.auto_cleanup_remove_machines,
                )

                try:
                    # Stop unused machines first
                    stopped_machines = self.executor.stop_unused_machines(
                        preserve_current=True,  # Keep the machine we need
                    )

                    if stopped_machines:
                        self.hooks.emit_metric(
                            "breakeramp.apply.machines_stopped",
                            machines=stopped_machines,
                            count=len(stopped_machines),
                        )

                    # If still not healthy and remove_machines is enabled, remove stopped machines
                    if request.auto_cleanup_remove_machines:
                        scale_result = self.executor.scale_down_machines(
                            keep_count=1,
                            remove_stopped=True,
                        )

                        if scale_result.get("removed"):
                            total_space_freed_mb += scale_result.get("disk_freed_gb", 0) * 1024
                            self.hooks.emit_metric(
                                "breakeramp.apply.machines_removed",
                                machines=scale_result.get("removed", []),
                                disk_freed_gb=scale_result.get("disk_freed_gb", 0),
                            )

                    # Re-check resources after machine cleanup
                    healthy, current_warnings = self.executor.check_resource_health(
                        min_disk_gb=request.min_disk_gb,
                        min_memory_mb=request.min_memory_mb,
                    )

                    if healthy:
                        self.hooks.emit_metric(
                            "breakeramp.apply.machine_scale_down_success",
                            total_space_freed_mb=total_space_freed_mb,
                        )
                        return True, current_warnings

                except Exception as e:
                    self.hooks.emit_metric(
                        "breakeramp.apply.machine_scale_down_error",
                        error=str(e),
                    )

        # All tiers exhausted
        self.hooks.emit_metric(
            "breakeramp.apply.auto_cleanup_exhausted",
            total_space_freed_mb=total_space_freed_mb,
            final_warnings=current_warnings,
        )

        return False, current_warnings

    def _run_migrations(
        self,
        env_def: EnvironmentDefinition,
        manifest: Dict[str, Any],
        plan_id: str,
        amp_run_id: str,
    ) -> List[Dict[str, Any]]:
        """Run database migrations after containers are healthy.

        Migrations run from the host machine (where Alembic configs and migration
        files reside) against the database container (accessible via port mapping).

        Args:
            env_def: Environment definition with migration config
            manifest: Apply manifest with variables
            plan_id: Plan identifier for logging
            amp_run_id: Run identifier for logging

        Returns:
            List of migration results with status and output
        """
        import subprocess

        results: List[Dict[str, Any]] = []

        if not env_def.migrations or not env_def.migrations.auto_run:
            return results

        migrations = env_def.migrations.migrations
        if not migrations:
            return results

        # Get working directory from environment manifest or current directory
        working_dir = Path(manifest.get("environment_manifest", ".")).parent
        if not working_dir.exists():
            working_dir = Path.cwd()

        # Merge environment variables
        env_vars = os.environ.copy()
        env_vars.update(manifest.get("variables", {}))

        for migration_spec in migrations:
            if not migration_spec.enabled:
                results.append({
                    "name": migration_spec.name,
                    "status": "skipped",
                    "reason": "disabled",
                })
                continue

            self.hooks.emit_metric(
                "breakeramp.apply.migration.started",
                plan_id=plan_id,
                amp_run_id=amp_run_id,
                migration_name=migration_spec.name,
                alembic_config=migration_spec.alembic_config,
                target_revision=migration_spec.target_revision,
            )

            # Check if Alembic config exists
            alembic_config_path = working_dir / migration_spec.alembic_config
            if not alembic_config_path.exists():
                error_msg = f"Alembic config not found: {alembic_config_path}"
                self.hooks.emit_metric(
                    "breakeramp.apply.migration.failed",
                    plan_id=plan_id,
                    amp_run_id=amp_run_id,
                    migration_name=migration_spec.name,
                    error=error_msg,
                )
                results.append({
                    "name": migration_spec.name,
                    "status": "failed",
                    "error": error_msg,
                })
                continue

            # Resolve database URL from environment variable
            db_url = env_vars.get(migration_spec.database_url_env)
            if not db_url:
                error_msg = f"Database URL not found in {migration_spec.database_url_env}"
                self.hooks.emit_metric(
                    "breakeramp.apply.migration.failed",
                    plan_id=plan_id,
                    amp_run_id=amp_run_id,
                    migration_name=migration_spec.name,
                    error=error_msg,
                )
                results.append({
                    "name": migration_spec.name,
                    "status": "failed",
                    "error": error_msg,
                })
                continue

            # Build Alembic command
            cmd = [
                "alembic",
                "-c", str(alembic_config_path),
                "upgrade",
                migration_spec.target_revision,
            ]

            # Set DATABASE_URL in subprocess environment
            run_env = env_vars.copy()
            run_env["DATABASE_URL"] = db_url

            try:
                result = subprocess.run(
                    cmd,
                    cwd=str(working_dir),
                    env=run_env,
                    capture_output=True,
                    text=True,
                    timeout=300,  # 5 minute timeout
                )

                if result.returncode == 0:
                    self.hooks.emit_metric(
                        "breakeramp.apply.migration.completed",
                        plan_id=plan_id,
                        amp_run_id=amp_run_id,
                        migration_name=migration_spec.name,
                        output_preview=result.stdout[:500] if result.stdout else "",
                    )
                    results.append({
                        "name": migration_spec.name,
                        "status": "completed",
                        "output": result.stdout,
                    })
                else:
                    error_output = result.stderr or result.stdout
                    self.hooks.emit_metric(
                        "breakeramp.apply.migration.failed",
                        plan_id=plan_id,
                        amp_run_id=amp_run_id,
                        migration_name=migration_spec.name,
                        error=error_output[:500] if error_output else "Unknown error",
                        return_code=result.returncode,
                    )
                    results.append({
                        "name": migration_spec.name,
                        "status": "failed",
                        "error": error_output,
                        "return_code": result.returncode,
                    })

            except subprocess.TimeoutExpired as e:
                error_msg = f"Migration timed out after 300s"
                self.hooks.emit_metric(
                    "breakeramp.apply.migration.timeout",
                    plan_id=plan_id,
                    amp_run_id=amp_run_id,
                    migration_name=migration_spec.name,
                    error=error_msg,
                )
                results.append({
                    "name": migration_spec.name,
                    "status": "timeout",
                    "error": error_msg,
                })

            except Exception as e:
                error_msg = str(e)
                self.hooks.emit_metric(
                    "breakeramp.apply.migration.error",
                    plan_id=plan_id,
                    amp_run_id=amp_run_id,
                    migration_name=migration_spec.name,
                    error=error_msg,
                )
                results.append({
                    "name": migration_spec.name,
                    "status": "error",
                    "error": error_msg,
                })

        return results

    # =========================================================================
    # Core Operations
    # =========================================================================

    def plan(self, request: PlanRequest) -> PlanResponse:
        """Create a plan for an environment deployment.

        Args:
            request: Plan request with blueprint and environment info

        Returns:
            Plan response with estimates and manifest

        Raises:
            ValueError: If environment or blueprint not found
        """
        if request.environment not in self.environments:
            raise ValueError(
                f"Environment '{request.environment}' not defined. "
                f"Available: {list(self.environments.keys())}"
            )

        env_def = self.environments[request.environment]

        # Apply CLI override for disk size if provided
        if request.machine_disk_size_gb is not None:
            env_def.runtime.machine_disk_size_gb = request.machine_disk_size_gb

        self._ensure_runtime_ready(env_def, force=request.force_podman)

        # Merge variables: request overrides environment
        merged_variables = env_def.variables.copy()
        merged_variables.update(request.variables)
        if "AMPREALIZE_REPO_ROOT" not in merged_variables:
            merged_variables["AMPREALIZE_REPO_ROOT"] = str(self._infer_repo_root())

        # Apply defaults
        lifetime = request.lifetime or env_def.default_lifetime
        compliance_tier = request.compliance_tier or env_def.default_compliance_tier

        blueprint_id = request.blueprint_id or env_def.infrastructure.blueprint_id
        if not blueprint_id:
            raise ValueError(
                f"Environment '{env_def.name}' does not define a blueprint. "
                f"Provide blueprint_id or update the manifest."
            )

        blueprint = self._resolve_blueprint(blueprint_id, variables=merged_variables)

        # Auto-derive active_modules from blueprint module definitions
        # when the caller didn't explicitly specify them.
        if request.active_modules is None and blueprint.modules:
            request.active_modules = [
                mod_name for mod_name, mod_spec in blueprint.modules.items()
                if mod_spec.enabled
            ]

        # Filter services by module when active_modules is set
        # (either explicitly by the caller or auto-derived from blueprint).
        if request.active_modules is not None:
            active_modules = request.active_modules
            filtered_services = {}
            for name, svc in blueprint.services.items():
                if svc.module and svc.module in active_modules:
                    filtered_services[name] = svc
                elif not svc.module and "core" in active_modules:
                    filtered_services[name] = svc
            blueprint.services = filtered_services
            if not blueprint.services:
                raise ValueError(
                    "Module filtering selected zero services. "
                    "Either adjust active_modules or omit it to include all services."
                )

        # Calculate resources
        req_mem, req_cpu, req_bandwidth = self._calculate_blueprint_resources(blueprint)

        plan_id = f"plan-{uuid.uuid4()}"
        amp_run_id = f"amp-{uuid.uuid4()}"

        # Generate manifest
        runtime_payload = (
            env_def.runtime.model_dump()
            if hasattr(env_def.runtime, "model_dump")
            else env_def.runtime.dict()
        )
        infra_payload = (
            env_def.infrastructure.model_dump()
            if hasattr(env_def.infrastructure, "model_dump")
            else env_def.infrastructure.dict()
        )

        manifest = {
            "blueprint": blueprint.model_dump() if hasattr(blueprint, "model_dump") else blueprint.dict(),
            "blueprint_id": blueprint_id,
            "tier": compliance_tier,
            "created_at": datetime.utcnow().isoformat(),
            "variables": merged_variables,
            "plan_id": plan_id,
            "amp_run_id": amp_run_id,
            "phase": "PLANNED",
            "environment": request.environment,
            "lifetime": lifetime,
            "checklist_id": request.checklist_id,
            "runtime": runtime_payload,
            "infrastructure": infra_payload,
            "environment_manifest": str(self.environment_manifest_path) if self.environment_manifest_path else None,
            "teardown_on_exit": env_def.infrastructure.teardown_on_exit,
        }

        # Save manifest
        manifest_path = self.manifests_dir / f"{plan_id}.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

        # Record action via hooks
        self.hooks.record_action(
            "breakeramp.plan",
            blueprint_id=blueprint_id,
            environment=request.environment,
            plan_id=plan_id,
            amp_run_id=amp_run_id,
        )

        # Record compliance step via hooks
        if request.checklist_id:
            self.hooks.record_compliance_step(
                "plan_created",
                checklist_id=request.checklist_id,
                plan_id=plan_id,
                blueprint_id=blueprint_id,
                manifest_path=str(manifest_path),
            )

        # Emit metric
        self.hooks.emit_metric(
            "breakeramp.plan.created",
            plan_id=plan_id,
            blueprint_id=blueprint_id,
        )

        return PlanResponse(
            plan_id=plan_id,
            amp_run_id=amp_run_id,
            signed_manifest=manifest,
            environment_estimates=EnvironmentEstimates(
                cost_estimate=0.50,
                memory_footprint_mb=req_mem or env_def.runtime.memory_limit_mb or 1024,
                bandwidth_mbps=req_bandwidth,
                region="local",
                expected_boot_duration_s=60,
            ),
        )

    # =========================================================================
    # Test-Aware Provisioning
    # =========================================================================

    def plan_for_tests(self, request: PlanForTestsRequest) -> PlanForTestsResponse:
        """Analyze test files and plan minimal infrastructure for them.

        This method examines test files to discover which services they need,
        then creates a minimal blueprint containing only those services with
        their dependencies resolved.

        Args:
            request: Plan request with test paths and optional blueprint override

        Returns:
            Response with analysis details and minimal plan

        Example:
            response = service.plan_for_tests(PlanForTestsRequest(
                test_paths=["tests/integration/test_api.py"],
                blueprint_id="full-stack",
                environment="development",
            ))
            print(f"Required services: {response.required_services}")
            # Apply the minimal plan
            apply_response = service.apply(ApplyRequest(plan_id=response.plan_id))
        """
        from .test_analyzer import TestDependencyAnalyzer

        # Resolve the full blueprint
        blueprint_id = request.blueprint_id
        merged_variables: Dict[str, Any] = {}
        if request.environment and request.environment in self.environments:
            env_def = self.environments[request.environment]
            blueprint_id = blueprint_id or env_def.infrastructure.blueprint_id
            merged_variables = env_def.variables.copy()
            merged_variables.setdefault("AMPREALIZE_REPO_ROOT", str(self._infer_repo_root()))

        if not blueprint_id:
            raise ValueError(
                "No blueprint_id provided and no default found for environment"
            )

        full_blueprint = self._resolve_blueprint(blueprint_id, variables=merged_variables or None)

        # Load test suite definition if provided
        suite_definition: Optional[TestSuiteDefinition] = None
        if request.suite_config_path:
            suite_path = Path(request.suite_config_path)
            if suite_path.exists():
                with open(suite_path, "r") as f:
                    suite_data = yaml.safe_load(f)
                suite_definition = TestSuiteDefinition(**suite_data)

        # Create analyzer and analyze test files
        analyzer = TestDependencyAnalyzer(
            default_marker_mappings=request.marker_mappings,
        )

        analysis = analyzer.analyze_tests(
            test_paths=request.test_paths,
            blueprint=full_blueprint,
            suite_definition=suite_definition,
            markers=request.markers,
        )

        # Get minimal blueprint with only required services
        minimal_blueprint = analyzer.get_minimal_blueprint(
            analysis=analysis,
            full_blueprint=full_blueprint,
            suite_definition=suite_definition,
        )

        # Get startup order for the minimal blueprint
        startup_order = minimal_blueprint.get_startup_order()

        # Calculate resources for minimal blueprint
        req_mem, req_cpu, req_bandwidth = self._calculate_blueprint_resources(minimal_blueprint)

        # Generate plan IDs
        plan_id = f"plan-test-{uuid.uuid4()}"
        amp_run_id = f"amp-test-{uuid.uuid4()}"

        # Get environment definition (use default if not specified)
        environment = request.environment or "development"
        if environment not in self.environments:
            environment = list(self.environments.keys())[0] if self.environments else "development"

        env_def = self.environments.get(environment, EnvironmentDefinition(name=environment))

        # Build manifest (similar to plan() but for tests)
        runtime_payload = (
            env_def.runtime.model_dump()
            if hasattr(env_def.runtime, "model_dump")
            else env_def.runtime.dict()
        )

        manifest = {
            "blueprint": minimal_blueprint.model_dump() if hasattr(minimal_blueprint, "model_dump") else minimal_blueprint.dict(),
            "blueprint_id": f"{blueprint_id}-minimal",
            "original_blueprint_id": blueprint_id,
            "tier": request.compliance_tier or env_def.default_compliance_tier or "standard",
            "created_at": datetime.utcnow().isoformat(),
            "variables": {},
            "plan_id": plan_id,
            "amp_run_id": amp_run_id,
            "phase": "PLANNED",
            "environment": environment,
            "lifetime": request.lifetime or "30m",
            "runtime": runtime_payload,
            "test_context": {
                "test_paths": request.test_paths,
                "markers": list(analysis.discovered_markers),
                "required_services": list(analysis.required_services),
                "startup_order": startup_order,
                "service_sources": analysis.service_sources,
                "test_files_analyzed": analysis.test_files_analyzed,
            },
            "teardown_on_exit": True,  # Always teardown after tests
        }

        # Save manifest
        manifest_path = self.manifests_dir / f"{plan_id}.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

        # Record action via hooks
        self.hooks.record_action(
            "breakeramp.plan_for_tests",
            blueprint_id=blueprint_id,
            test_paths=request.test_paths,
            required_services=list(analysis.required_services),
            plan_id=plan_id,
            amp_run_id=amp_run_id,
        )

        # Emit metric
        self.hooks.emit_metric(
            "breakeramp.plan_for_tests.created",
            plan_id=plan_id,
            original_blueprint_id=blueprint_id,
            services_in_full=len(full_blueprint.services),
            services_in_minimal=len(minimal_blueprint.services),
            test_files_analyzed=analysis.test_files_analyzed,
            markers_discovered=len(analysis.discovered_markers),
        )

        return PlanForTestsResponse(
            plan_id=plan_id,
            amp_run_id=amp_run_id,
            required_services=list(analysis.required_services),
            startup_order=startup_order,
            discovered_markers=list(analysis.discovered_markers),
            service_sources=analysis.service_sources,
            test_files_analyzed=analysis.test_files_analyzed,
            analysis_errors=analysis.analysis_errors,
            minimal_blueprint=minimal_blueprint.model_dump() if hasattr(minimal_blueprint, "model_dump") else minimal_blueprint.dict(),
            environment_estimates=EnvironmentEstimates(
                cost_estimate=0.25,  # Minimal setup should cost less
                memory_footprint_mb=req_mem or 512,
                bandwidth_mbps=req_bandwidth,
                region="local",
                expected_boot_duration_s=30,  # Faster with fewer services
            ),
        )

    def run_tests(self, request: RunTestsRequest) -> RunTestsResponse:
        """Plan, provision, run tests, and teardown in one operation.

        This is a convenience method that:
        1. Analyzes test files to determine required services
        2. Plans a minimal environment
        3. Provisions the environment
        4. (Optionally) runs pytest
        5. Tears down the environment

        Args:
            request: Run tests request with test paths and options

        Returns:
            Response with test results and timing information

        Example:
            result = service.run_tests(RunTestsRequest(
                test_paths=["tests/integration/"],
                blueprint_id="full-stack",
                pytest_args=["-v", "--tb=short"],
            ))
            print(f"Exit code: {result.pytest_exit_code}")
            print(f"Total duration: {result.total_duration_s}s")
        """
        import subprocess

        start_time = time.time()
        plan_response: Optional[PlanForTestsResponse] = None
        apply_response: Optional[ApplyResponse] = None
        pytest_exit_code: Optional[int] = None
        pytest_output: Optional[str] = None
        teardown_report: List[str] = []
        errors: List[str] = []

        try:
            # Step 1: Plan for tests
            plan_start = time.time()
            plan_response = self.plan_for_tests(PlanForTestsRequest(
                test_paths=request.test_paths,
                blueprint_id=request.blueprint_id,
                environment=request.environment,
                markers=request.markers,
                marker_mappings=request.marker_mappings,
                suite_config_path=request.suite_config_path,
                lifetime=request.lifetime,
            ))
            plan_duration_s = time.time() - plan_start

            self.hooks.emit_metric(
                "breakeramp.run_tests.planned",
                plan_id=plan_response.plan_id,
                required_services=plan_response.required_services,
                plan_duration_s=plan_duration_s,
            )

            # Step 2: Apply the plan (provision environment)
            apply_start = time.time()
            apply_response = self.apply(ApplyRequest(
                plan_id=plan_response.plan_id,
                skip_resource_check=request.skip_resource_check,
            ))
            apply_duration_s = time.time() - apply_start

            self.hooks.emit_metric(
                "breakeramp.run_tests.applied",
                amp_run_id=plan_response.amp_run_id,
                services_started=len(apply_response.environment_outputs),
                apply_duration_s=apply_duration_s,
            )

            # Step 3: Run pytest if requested
            if request.run_pytest:
                test_start = time.time()

                # Build environment variables from service outputs
                env = os.environ.copy()
                for name, output in apply_response.environment_outputs.items():
                    upper_name = name.upper().replace("-", "_")
                    if "port" in output:
                        env[f"{upper_name}_PORT"] = str(output["port"])
                    if "host" in output:
                        env[f"{upper_name}_HOST"] = str(output["host"])
                    if "url" in output:
                        env[f"{upper_name}_URL"] = str(output["url"])

                # Build pytest command
                pytest_cmd = ["pytest"] + request.test_paths
                if request.pytest_args:
                    pytest_cmd.extend(request.pytest_args)
                if request.markers:
                    marker_expr = " or ".join(request.markers)
                    pytest_cmd.extend(["-m", marker_expr])

                # Run pytest
                try:
                    result = subprocess.run(
                        pytest_cmd,
                        capture_output=True,
                        text=True,
                        env=env,
                        timeout=request.timeout_s or 600,
                    )
                    pytest_exit_code = result.returncode
                    pytest_output = result.stdout + result.stderr
                except subprocess.TimeoutExpired:
                    pytest_exit_code = -1
                    pytest_output = "Test execution timed out"
                    errors.append(f"Pytest timed out after {request.timeout_s}s")
                except Exception as e:
                    pytest_exit_code = -1
                    pytest_output = str(e)
                    errors.append(f"Failed to run pytest: {e}")

                test_duration_s = time.time() - test_start

                self.hooks.emit_metric(
                    "breakeramp.run_tests.pytest_completed",
                    amp_run_id=plan_response.amp_run_id,
                    exit_code=pytest_exit_code,
                    test_duration_s=test_duration_s,
                )

        except Exception as e:
            errors.append(str(e))
            self.hooks.emit_metric(
                "breakeramp.run_tests.failed",
                error=str(e),
            )

        finally:
            # Step 4: Always teardown (unless skip_teardown is True)
            if plan_response and not request.skip_teardown:
                try:
                    destroy_response = self.destroy(DestroyRequest(
                        amp_run_id=plan_response.amp_run_id,
                        reason="Test run completed",
                        cleanup_after_destroy=True,
                        cleanup_aggressive=False,
                    ))
                    teardown_report = destroy_response.teardown_report
                except Exception as e:
                    errors.append(f"Teardown failed: {e}")

        total_duration_s = time.time() - start_time

        self.hooks.emit_metric(
            "breakeramp.run_tests.completed",
            plan_id=plan_response.plan_id if plan_response else None,
            total_duration_s=total_duration_s,
            pytest_exit_code=pytest_exit_code,
            errors=errors,
        )

        return RunTestsResponse(
            plan_id=plan_response.plan_id if plan_response else None,
            amp_run_id=plan_response.amp_run_id if plan_response else None,
            required_services=plan_response.required_services if plan_response else [],
            environment_outputs=apply_response.environment_outputs if apply_response else {},
            pytest_exit_code=pytest_exit_code,
            pytest_output=pytest_output,
            teardown_report=teardown_report,
            total_duration_s=total_duration_s,
            errors=errors,
        )

    def apply(self, request: ApplyRequest, progress: Optional[ProgressCallback] = None) -> ApplyResponse:
        """Apply a plan and provision the environment.

        Args:
            request: Apply request with plan_id or manifest
            progress: Optional callback for progress reporting

        Returns:
            Apply response with environment outputs

        Raises:
            ValueError: If plan not found
            RuntimeError: If provisioning fails
        """
        prog = progress or NoOpProgress()
        plan_id = request.plan_id
        manifest = request.manifest

        if not plan_id and not manifest:
            raise ValueError("Either plan_id or manifest must be provided")

        if plan_id:
            manifest_path = self.manifests_dir / f"{plan_id}.json"
            if manifest_path.exists():
                with open(manifest_path, "r") as f:
                    manifest = json.load(f)
            elif not manifest:
                raise ValueError(f"Plan {plan_id} not found")

        assert manifest is not None  # Type narrowing

        # Configure executor for the environment's runtime
        runtime_config = manifest.get("runtime", {})
        if isinstance(runtime_config, dict) and runtime_config.get("provider") in ("podman", "docker"):
            # Reuse the canonical runtime readiness + Podman connection resolution logic.
            # This prevents "containers exist but on a different connection" confusion.
            self._ensure_runtime_ready_from_run_manifest(manifest, force=False)

            from .executors.podman import PodmanExecutor
            if isinstance(self.executor, PodmanExecutor):
                # Prefer the resolved executor connection when present; otherwise keep
                # whatever was resolved onto the manifest by _ensure_runtime_ready_from_run_manifest.
                if self.executor.connection:
                    runtime_config["podman_connection"] = self.executor.connection

        # Calculate blueprint memory requirements for smart resource checking
        blueprint_data = manifest.get("blueprint", manifest)
        services = blueprint_data.get("services", {})
        blueprint_memory_mb = 0
        for svc_spec in services.values():
            svc_mem = svc_spec.get("memory_mb")
            if svc_mem:
                blueprint_memory_mb += svc_mem

        # Use blueprint-aware memory threshold if enabled and blueprint has memory info
        min_memory_for_check = request.min_memory_mb
        if request.blueprint_aware_memory_check and blueprint_memory_mb > 0:
            # Add safety margin to blueprint estimate
            min_memory_for_check = blueprint_memory_mb + request.memory_safety_margin_mb
            self.hooks.emit_metric(
                "breakeramp.apply.blueprint_memory_estimate",
                blueprint_memory_mb=blueprint_memory_mb,
                safety_margin_mb=request.memory_safety_margin_mb,
                total_required_mb=min_memory_for_check,
            )

        # Proactive cleanup: clean BEFORE checking resources (maximizes available resources)
        if request.proactive_cleanup and isinstance(self.executor, ResourceCapableExecutor):
            prog.on_phase("cleanup", "Cleaning up resources")
            prog.on_step("proactive_cleanup", "Proactive cleanup")
            self.hooks.emit_metric(
                "breakeramp.apply.proactive_cleanup_started",
            )
            try:
                # Run standard cleanup to free resources before we even check
                cleanup_result = self.executor.mitigate_resources(
                    dry_run=False,
                    prune_containers=True,
                    prune_images=True,
                    prune_volumes=False,  # Never proactively delete volumes
                    prune_cache=True,
                    prune_networks=True,
                    prune_pods=True,
                    prune_logs=request.auto_cleanup_aggressive,
                )
                self.hooks.emit_metric(
                    "breakeramp.apply.proactive_cleanup_completed",
                    space_reclaimed_mb=cleanup_result.space_reclaimed_mb,
                    containers_removed=cleanup_result.containers_removed,
                    images_removed=cleanup_result.images_removed,
                )
                prog.on_step_done("proactive_cleanup")
            except Exception as e:
                prog.on_warning(f"Proactive cleanup error: {e}")
                self.hooks.emit_metric(
                    "breakeramp.apply.proactive_cleanup_error",
                    error=str(e),
                )

        # Pre-flight resource health check with tiered auto-remediation
        if not request.skip_resource_check:
            prog.on_step("resource_check", "Checking resources")
            if isinstance(self.executor, ResourceCapableExecutor):
                try:
                    healthy, warnings = self.executor.check_resource_health(
                        min_disk_gb=request.min_disk_gb,
                        min_memory_mb=min_memory_for_check,
                    )
                    if warnings:
                        for warning in warnings:
                            self.hooks.emit_metric(
                                "breakeramp.apply.resource_warning",
                                warning=warning,
                            )
                    if not healthy:
                        # Resource shortage detected - attempt auto-remediation if enabled
                        if request.auto_cleanup:
                            healthy, warnings = self._perform_tiered_cleanup(
                                request=request,
                                initial_warnings=warnings,
                            )

                        if not healthy:
                            # Still not healthy after cleanup attempts (or auto_cleanup not enabled)
                            raise RuntimeError(
                                f"Resource shortage detected. Use skip_resource_check=True to override, "
                                f"or auto_cleanup=True to automatically free up space.\n"
                                f"Warnings:\n" + "\n".join(f"  - {w}" for w in warnings)
                            )
                except Exception as e:
                    if "Resource shortage" in str(e) or "Critical resource" in str(e):
                        raise
                    # Non-blocking: log but continue if resource check fails
                    self.hooks.emit_metric(
                        "breakeramp.apply.resource_check_error",
                        error=str(e),
                    )
            prog.on_step_done("resource_check")

        amp_run_id = manifest.get("amp_run_id") or f"amp-{uuid.uuid4()}"
        checklist_id = manifest.get("checklist_id")

        # Update manifest state
        manifest["phase"] = "PROVISIONING"
        manifest["updated_at"] = datetime.utcnow().isoformat()

        # Record action
        self.hooks.record_action(
            "breakeramp.apply.started",
            plan_id=plan_id,
            amp_run_id=amp_run_id,
        )

        # Emit metric
        self.hooks.emit_metric(
            "breakeramp.apply.started",
            plan_id=plan_id,
            amp_run_id=amp_run_id,
        )

        # Record compliance step
        if checklist_id:
            self.hooks.record_compliance_step(
                "apply_started",
                checklist_id=checklist_id,
                plan_id=plan_id,
                amp_run_id=amp_run_id,
            )

        # Execute plan
        blueprint_data = manifest.get("blueprint", manifest)
        services = blueprint_data.get("services", {})

        outputs: Dict[str, Any] = {}

        # Collect all ports that will be used
        all_ports: List[int] = []
        for name, spec in services.items():
            for port_mapping in spec.get("ports", []):
                if isinstance(port_mapping, str) and ":" in port_mapping:
                    host_port = int(port_mapping.split(":")[0])
                    all_ports.append(host_port)
                elif isinstance(port_mapping, dict) and "host" in port_mapping:
                    all_ports.append(int(port_mapping["host"]))

        # Pre-apply cleanup: remove stale/orphaned containers and resolve port conflicts
        # Uses request options for auto-resolve behavior (enabled by default for zero-friction apply)
        should_cleanup = request.auto_resolve_stale or request.auto_resolve_conflicts
        if should_cleanup:
            try:
                cleanup_result = self.executor.prepare_for_apply(
                    ports=all_ports if request.auto_resolve_conflicts else [],
                    preserve_run_id=amp_run_id,
                    cleanup_stale=request.auto_resolve_stale,
                    stale_max_age_hours=request.stale_max_age_hours,  # None = any age, 0 = all stale
                )
                stale_removed = cleanup_result.get("stale_removed", 0)
                orphans_removed = cleanup_result.get("orphans_removed", 0)
                conflicts_resolved = cleanup_result.get("conflicts_resolved", 0)
                conflicts_found = cleanup_result.get("conflicts_found", [])

                if stale_removed > 0 or orphans_removed > 0 or conflicts_resolved > 0:
                    self.hooks.emit_metric(
                        "breakeramp.apply.cleanup",
                        plan_id=plan_id,
                        amp_run_id=amp_run_id,
                        stale_removed=stale_removed,
                        orphans_removed=orphans_removed,
                        conflicts_resolved=conflicts_resolved,
                    )

                # Log any unresolved conflicts (ports still blocked)
                if conflicts_found:
                    self.hooks.emit_metric(
                        "breakeramp.apply.conflicts_remaining",
                        plan_id=plan_id,
                        amp_run_id=amp_run_id,
                        conflicts=conflicts_found,
                    )
            except Exception as e:
                # Log but don't fail - the main apply might still succeed
                self.hooks.emit_metric(
                    "breakeramp.apply.cleanup_warning",
                    plan_id=plan_id,
                    amp_run_id=amp_run_id,
                    warning=str(e),
                )

        def _parse_host_port(port_mapping: str) -> Optional[int]:
            parts = port_mapping.split(":")
            if len(parts) < 2:
                return None
            try:
                return int(parts[-2] if len(parts) > 2 else parts[0])
            except ValueError:
                return None

        def _wait_for_port(host_port: int, timeout_s: int) -> None:
            deadline = time.time() + max(timeout_s, 1)
            last_err: Optional[Exception] = None
            while time.time() < deadline:
                try:
                    with socket.create_connection(("127.0.0.1", host_port), timeout=1.0):
                        return
                except OSError as exc:
                    last_err = exc
                    time.sleep(0.25)
            raise RuntimeError(f"Timed out waiting for port {host_port} to become ready: {last_err}")

        def _wait_for_healthcheck(
            container_name: str,
            healthcheck_spec: Optional[Dict[str, Any]],
            timeout_s: int,
            executor: Any,
        ) -> None:
            """Wait for a container's healthcheck to pass with adaptive polling.

            Starts polling at 0.5s intervals and geometrically backs off to the
            spec-defined interval, reducing startup latency for fast services.
            """
            if not healthcheck_spec:
                return

            test_cmd = healthcheck_spec.get("test")
            if not test_cmd:
                return

            if isinstance(test_cmd, str):
                shell_cmd = test_cmd
            elif isinstance(test_cmd, list) and len(test_cmd) >= 2:
                if test_cmd[0] == "CMD-SHELL":
                    shell_cmd = test_cmd[1]
                elif test_cmd[0] == "CMD":
                    shell_cmd = " ".join(test_cmd[1:])
                else:
                    shell_cmd = " ".join(test_cmd)
            else:
                return

            interval_str = healthcheck_spec.get("interval", "2s")
            try:
                max_interval = int(interval_str.rstrip("smh"))
            except ValueError:
                max_interval = 2

            # Adaptive polling: start fast, back off to spec interval
            poll_interval = 0.5
            retries = healthcheck_spec.get("retries", 5)
            deadline = time.time() + max(timeout_s, 1)
            attempts = 0
            last_err: Optional[str] = None

            while time.time() < deadline:
                attempts += 1
                try:
                    if hasattr(executor, "exec_in_container"):
                        executor.exec_in_container(
                            container_name,
                            ["sh", "-c", shell_cmd],
                        )
                        return  # Healthcheck passed!
                except Exception as exc:
                    last_err = str(exc)
                    if attempts >= retries:
                        pass
                time.sleep(poll_interval)
                # Geometric backoff: 0.5 → 1.0 → 2.0 → ... → max_interval
                poll_interval = min(poll_interval * 2, max_interval)

            raise RuntimeError(
                f"Healthcheck failed for {container_name} after {timeout_s}s "
                f"(command: {shell_cmd}): {last_err}"
            )

        try:
            # Create a dedicated network for this run (enables inter-container DNS)
            network_name = f"amp-net-{amp_run_id}"
            from .executors.podman import PodmanExecutor
            should_wait_for_ports = isinstance(self.executor, PodmanExecutor)
            if isinstance(self.executor, PodmanExecutor):
                self.executor.create_network(network_name, ignore_exists=True)
                manifest["network_name"] = network_name
            else:
                network_name = None  # Non-Podman executors don't need this

            # ── DAG-based parallel service startup ──────────────────────
            # Build dependency graph from `depends_on` so independent services
            # start concurrently while respecting ordering constraints.
            dep_graph: Dict[str, List[str]] = {}
            for svc_name, svc_spec in services.items():
                deps = svc_spec.get("depends_on", [])
                # Filter out deps that aren't in the service list
                dep_graph[svc_name] = [d for d in deps if d in services]

            # Pre-register services for progress display
            service_ports: Dict[str, Optional[int]] = {}
            for svc_name, svc_spec in services.items():
                ports = svc_spec.get("ports", []) or []
                host_port = _parse_host_port(str(ports[0])) if ports else None
                service_ports[svc_name] = host_port
                prog.on_service_status(svc_name, ServiceStatus.WAITING)

            prog.on_phase("services", "Starting services", total_steps=len(services))

            # Shared state for DAG scheduling (protected by GIL for simple flags)
            healthy_services: Set[str] = set()
            failed_services: Dict[str, str] = {}  # name -> error message
            service_lock = __import__("threading").Lock()

            def _start_service(name: str, spec: Dict[str, Any]) -> None:
                """Start a single service: build → run → port wait → healthcheck → post-start."""
                container_name = f"{amp_run_id}-{name}"
                try:
                    # Stop existing if any (simple reconciliation)
                    self.executor.stop_container(container_name)
                    self.executor.remove_container(container_name)

                    # Build image if needed
                    build_spec = spec.get("build")
                    if build_spec:
                        image = spec.get("image")
                        if not image:
                            raise ValueError(f"Service '{name}' is missing required image tag for build")

                        rebuild = request.rebuild_images or bool(build_spec.get("rebuild", False))
                        should_build = rebuild
                        if not should_build and hasattr(self.executor, "image_exists"):
                            try:
                                should_build = not bool(self.executor.image_exists(image))
                            except Exception:
                                should_build = True

                        if should_build:
                            prog.on_service_status(name, ServiceStatus.BUILDING, detail=image)
                            if not hasattr(self.executor, "build_image"):
                                raise RuntimeError(
                                    "Executor does not support image builds; "
                                    f"cannot build image for service '{name}'"
                                )
                            self.hooks.emit_metric(
                                "breakeramp.apply.build.started",
                                plan_id=plan_id, amp_run_id=amp_run_id,
                                service=name, image=image,
                            )
                            self.executor.build_image(
                                image=image,
                                context=str(build_spec.get("context", ".")),
                                dockerfile=build_spec.get("dockerfile"),
                                build_args=build_spec.get("build_args") or {},
                                pull=bool(build_spec.get("pull", False)),
                            )
                            self.hooks.emit_metric(
                                "breakeramp.apply.build.completed",
                                plan_id=plan_id, amp_run_id=amp_run_id,
                                service=name, image=image,
                            )

                    # Run container
                    prog.on_service_status(name, ServiceStatus.STARTING)
                    run_config = ContainerRunConfig(
                        image=spec.get("image"),
                        name=container_name,
                        ports=spec.get("ports", []),
                        environment=spec.get("environment", {}),
                        volumes=spec.get("volumes", []),
                        command=spec.get("command"),
                        workdir=spec.get("workdir"),
                        detach=True,
                        network=network_name,
                        network_aliases=[name] if network_name else [],
                        privileged=bool(spec.get("privileged", False)),
                        extra_hosts=spec.get("extra_hosts", []),
                    )
                    container_id = self.executor.run_container(run_config)
                    outputs[name] = {"container_id": container_id, "status": "running"}

                    # Wait for port
                    timeout_s = int(spec.get("healthcheck_timeout_s") or 0)
                    ports = spec.get("ports", []) or []
                    if should_wait_for_ports and timeout_s > 0 and ports:
                        host_port = _parse_host_port(str(ports[0]))
                        if host_port is not None:
                            _wait_for_port(host_port, timeout_s)

                    # Healthcheck with adaptive polling
                    healthcheck_spec = spec.get("healthcheck")
                    if healthcheck_spec:
                        prog.on_service_status(name, ServiceStatus.HEALTH_CHECKING)
                        healthcheck_timeout = timeout_s if timeout_s > 0 else 60
                        self.hooks.emit_metric(
                            "breakeramp.apply.healthcheck.waiting",
                            plan_id=plan_id, amp_run_id=amp_run_id,
                            service=name, timeout_s=healthcheck_timeout,
                        )
                        _wait_for_healthcheck(
                            container_name, healthcheck_spec,
                            healthcheck_timeout, self.executor,
                        )
                        self.hooks.emit_metric(
                            "breakeramp.apply.healthcheck.passed",
                            plan_id=plan_id, amp_run_id=amp_run_id, service=name,
                        )

                    # Post-start commands (e.g., Alembic migrations)
                    post_start_commands = spec.get("post_start_commands", [])
                    if post_start_commands:
                        prog.on_service_status(name, ServiceStatus.RUNNING_POST_START)
                    for cmd_spec in post_start_commands:
                        cmd_description = cmd_spec.get("description", "post-start command")
                        cmd = cmd_spec.get("command", [])
                        if not cmd:
                            continue
                        prog.on_service_status(name, ServiceStatus.RUNNING_POST_START, detail=cmd_description)
                        self.hooks.emit_metric(
                            "breakeramp.apply.post_start_command.started",
                            plan_id=plan_id, amp_run_id=amp_run_id,
                            service=name, description=cmd_description,
                        )
                        if hasattr(self.executor, "exec_in_container"):
                            output = self.executor.exec_in_container(container_name, cmd)
                            self.hooks.emit_metric(
                                "breakeramp.apply.post_start_command.completed",
                                plan_id=plan_id, amp_run_id=amp_run_id,
                                service=name, description=cmd_description,
                                output_preview=output[:500] if output else "",
                            )
                        else:
                            self.hooks.emit_metric(
                                "breakeramp.apply.post_start_command.skipped",
                                plan_id=plan_id, amp_run_id=amp_run_id,
                                service=name, reason="executor does not support exec_in_container",
                            )

                    # Mark healthy
                    prog.on_service_status(name, ServiceStatus.HEALTHY)
                    with service_lock:
                        healthy_services.add(name)

                except Exception as svc_err:
                    prog.on_service_status(name, ServiceStatus.FAILED, detail=str(svc_err))
                    prog.on_error(str(svc_err), service=name)
                    with service_lock:
                        failed_services[name] = str(svc_err)
                    raise

            # ── DAG scheduler: launch services as their deps become healthy ──
            remaining: Set[str] = set(services.keys())
            max_workers = min(4, len(services))  # Cap thread count

            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures: Dict[Any, str] = {}  # future -> service name

                def _submit_ready() -> None:
                    """Submit any services whose deps are all healthy."""
                    to_submit = []
                    with service_lock:
                        for svc in list(remaining):
                            deps = dep_graph.get(svc, [])
                            if all(d in healthy_services for d in deps) and svc not in futures.values():
                                to_submit.append(svc)
                    for svc in to_submit:
                        remaining.discard(svc)
                        fut = pool.submit(_start_service, svc, services[svc])
                        futures[fut] = svc

                _submit_ready()  # Seed with zero-dep services

                while futures:
                    # Wait for any service to complete
                    done_iter = as_completed(futures, timeout=600)
                    for done_future in done_iter:
                        svc_name = futures.pop(done_future)
                        try:
                            done_future.result()  # Re-raises exceptions
                            prog.on_step_done(svc_name, service=svc_name)
                        except Exception:
                            # Service failed — propagated below
                            pass
                        # Submit newly-unblocked services
                        _submit_ready()
                        break  # Re-check after each completion

                # Check for failures
                if failed_services:
                    first_name, first_err = next(iter(failed_services.items()))
                    raise RuntimeError(
                        f"Service startup failed for {first_name}: {first_err}"
                    )

                # Any services never submitted? (broken dep graph)
                if remaining:
                    raise RuntimeError(
                        f"Circular dependency or missing services: {remaining}"
                    )

        except Exception as e:
            self.hooks.emit_metric(
                "breakeramp.apply.failed",
                plan_id=plan_id,
                amp_run_id=amp_run_id,
                error=str(e),
            )
            prog.on_error(str(e))
            if checklist_id:
                self.hooks.record_compliance_step(
                    "apply_failed",
                    checklist_id=checklist_id,
                    error=str(e),
                )
            raise

        prog.on_phase("finalizing", "Finalizing environment")

        # Run database migrations after all containers are healthy
        # Migrations run from host using Alembic against the database container
        environment_name = manifest.get("environment", "")
        env_def = self.environments.get(environment_name)
        migration_results: List[Dict[str, Any]] = []
        if env_def and env_def.migrations:
            prog.on_step("migrations", "Running database migrations")
            migration_results = self._run_migrations(
                env_def=env_def,
                manifest=manifest,
                plan_id=plan_id,
                amp_run_id=amp_run_id,
            )
            # Check for any failed migrations
            if migration_results:
                failed_migrations = [m for m in migration_results if m.get("status") in ("failed", "error", "timeout")]
                if failed_migrations:
                    error_msg = f"Migration(s) failed: {[m['name'] for m in failed_migrations]}"
                    self.hooks.emit_metric(
                        "breakeramp.apply.migrations_failed",
                        plan_id=plan_id,
                        amp_run_id=amp_run_id,
                        failed_count=len(failed_migrations),
                        failed_names=[m["name"] for m in failed_migrations],
                    )
                    # Don't raise - migrations failure is non-fatal but logged
                    prog.on_warning(error_msg)
                    print(f"Warning: {error_msg}", file=sys.stderr)
            prog.on_step_done("migrations")

        manifest["phase"] = "APPLIED"
        manifest["environment_outputs"] = outputs
        # Store migration results separately (not in environment_outputs to avoid CLI parsing issues)
        if migration_results:
            manifest["migration_results"] = migration_results

        # Save environment state
        env_path = self.environments_dir / f"{amp_run_id}.json"
        with open(env_path, "w") as f:
            json.dump(manifest, f, indent=2)

        # Record action
        action_id = self.hooks.record_action(
            "breakeramp.apply.completed",
            plan_id=plan_id,
            amp_run_id=amp_run_id,
        )

        # Record compliance step
        if checklist_id:
            self.hooks.record_compliance_step(
                "apply_completed",
                checklist_id=checklist_id,
                plan_id=plan_id,
                environment_outputs=outputs,
                env_path=str(env_path),
            )

        # Emit metric
        self.hooks.emit_metric(
            "breakeramp.apply.completed",
            plan_id=plan_id,
            amp_run_id=amp_run_id,
            services_count=len(outputs),
        )

        return ApplyResponse(
            environment_outputs=outputs,
            status_stream_url=f"/v1/breakeramp/status/{amp_run_id}/stream",
            action_id=action_id,
            amp_run_id=amp_run_id,
        )

    def resolve_run_id(self, amp_run_id: str) -> Tuple[str, Path]:
        """Resolve a full or prefix run ID to its state file path.

        Supports exact matches and unambiguous prefix matches. This allows
        users to pass truncated IDs (e.g. from ``breakeramp list`` output).

        Args:
            amp_run_id: Full run ID or unique prefix

        Returns:
            Tuple of (resolved_full_id, state_file_path)

        Raises:
            FileNotFoundError: No matching run found
            ValueError: Prefix matches multiple runs (ambiguous)
        """
        # Try exact match first
        exact_path = self.environments_dir / f"{amp_run_id}.json"
        if exact_path.exists():
            return amp_run_id, exact_path

        # Try prefix match
        matches = list(self.environments_dir.glob(f"{amp_run_id}*.json"))
        if len(matches) == 1:
            full_id = matches[0].stem
            return full_id, matches[0]
        elif len(matches) > 1:
            ids = [m.stem for m in matches]
            raise ValueError(
                f"Ambiguous run ID prefix '{amp_run_id}' matches {len(matches)} runs: "
                + ", ".join(ids[:5])
            )
        else:
            raise FileNotFoundError(f"No environment found for run ID '{amp_run_id}'")

    def status(self, amp_run_id: str) -> StatusResponse:
        """Get the status of an environment.

        Args:
            amp_run_id: Full run ID or unique prefix

        Returns:
            Status response with health checks and telemetry

        Raises:
            FileNotFoundError: No matching run found
            ValueError: Ambiguous prefix
        """
        amp_run_id, env_path = self.resolve_run_id(amp_run_id)

        with open(env_path, "r") as f:
            run = json.load(f)

        # Ensure we are connected to the machine used for this run before querying containers.
        prev_connection = None
        runtime_payload = run.get("runtime")
        if isinstance(runtime_payload, dict):
            prev_connection = runtime_payload.get("podman_connection")
        self._ensure_runtime_ready_from_run_manifest(run, force=True)

        # If we resolved a previously-missing Podman connection, persist it so future
        # commands (and manual inspection) remain consistent.
        runtime_payload = run.get("runtime")
        if (
            isinstance(runtime_payload, dict)
            and not prev_connection
            and runtime_payload.get("podman_connection")
        ):
            try:
                with open(env_path, "w") as f:
                    json.dump(run, f, indent=2)
            except Exception:
                pass

        phase = run.get("phase", "UNKNOWN")
        outputs = run.get("environment_outputs", {})
        checks = []
        all_running = True

        for name, info in outputs.items():
            container_id = info.get("container_id")
            if not container_id:
                continue

            status = self.executor.get_container_status(container_id)
            # "unknown" from the executor means podman can't find the container
            # at all — it was removed, not just stopped.
            if status == "unknown":
                status = "removed"
            if status != "running":
                all_running = False

            checks.append(
                HealthCheck(
                    name=name,
                    status=status,
                    last_probe=datetime.utcnow(),
                )
            )

        if phase == "APPLIED" and not all_running:
            phase = "DEGRADED"

        return StatusResponse(
            amp_run_id=amp_run_id,
            phase=phase,
            progress_pct=100 if phase in ["APPLIED", "DEGRADED"] else 50,
            checks=checks,
            environment_outputs_path=str(env_path),
            audit_trail=[],
        )

    def destroy(self, request: DestroyRequest) -> DestroyResponse:
        """Destroy an environment.

        Args:
            request: Destroy request with run ID and reason

        Returns:
            Destroy response with teardown report
        """
        env_path = self.environments_dir / f"{request.amp_run_id}.json"
        teardown_report: List[str] = []
        checklist_id = None

        if env_path.exists():
            with open(env_path, "r") as f:
                run = json.load(f)
            checklist_id = run.get("checklist_id")
        else:
            run = {}

        # Ensure we are connected to the machine used for this run before stopping containers.
        self._ensure_runtime_ready_from_run_manifest(run, force=True)

        # Emit start metric
        self.hooks.emit_metric(
            "breakeramp.destroy.started",
            amp_run_id=request.amp_run_id,
        )

        # Record compliance step
        if checklist_id:
            self.hooks.record_compliance_step(
                "destroy_started",
                checklist_id=checklist_id,
                amp_run_id=request.amp_run_id,
                reason=request.reason,
            )

        try:
            if env_path.exists():
                outputs = run.get("environment_outputs", {})
                for name, info in outputs.items():
                    container_id = info.get("container_id")
                    if container_id:
                        self.executor.stop_container(container_id)
                        self.executor.remove_container(container_id)
                        teardown_report.append(name)

                # Clean up the network if one was created
                network_name = run.get("network_name")
                if network_name:
                    from .executors.podman import PodmanExecutor
                    if isinstance(self.executor, PodmanExecutor):
                        try:
                            self.executor.remove_network(network_name, force=True)
                            teardown_report.append(f"network:{network_name}")
                        except Exception:
                            pass  # Network cleanup is best-effort

                run["phase"] = "DESTROYED"
                run["destroyed_at"] = datetime.utcnow().isoformat()

                with open(env_path, "w") as f:
                    json.dump(run, f, indent=2)

        except Exception as e:
            self.hooks.emit_metric(
                "breakeramp.destroy.failed",
                amp_run_id=request.amp_run_id,
                error=str(e),
            )
            if checklist_id:
                self.hooks.record_compliance_step(
                    "destroy_failed",
                    checklist_id=checklist_id,
                    error=str(e),
                )
            raise

        # Record action
        action_id = self.hooks.record_action(
            "breakeramp.destroy",
            amp_run_id=request.amp_run_id,
            reason=request.reason,
        )

        # Record compliance step
        if checklist_id:
            self.hooks.record_compliance_step(
                "destroy_completed",
                checklist_id=checklist_id,
                teardown_report=teardown_report,
                destroyed_at=run.get("destroyed_at"),
            )

        # Emit metric
        self.hooks.emit_metric(
            "breakeramp.destroy.completed",
            amp_run_id=request.amp_run_id,
            services_removed=len(teardown_report),
        )

        # Post-destroy cleanup: reclaim disk/memory from dangling images, unused caches
        cleanup_space_reclaimed_mb = 0.0
        if request.cleanup_after_destroy and isinstance(self.executor, ResourceCapableExecutor):
            try:
                self.hooks.emit_metric(
                    "breakeramp.destroy.post_cleanup_started",
                    amp_run_id=request.amp_run_id,
                    aggressive=request.cleanup_aggressive,
                )

                cleanup_result = self.executor.mitigate_resources(
                    dry_run=False,
                    prune_containers=True,
                    prune_images=request.cleanup_aggressive,
                    prune_volumes=request.cleanup_include_volumes,
                    prune_cache=request.cleanup_aggressive,
                    prune_networks=True,
                    prune_pods=True,
                    prune_logs=request.cleanup_aggressive,
                )

                cleanup_space_reclaimed_mb = cleanup_result.space_reclaimed_mb
                teardown_report.append(
                    f"cleanup:freed {cleanup_space_reclaimed_mb:.1f}MB "
                    f"(images:{cleanup_result.images_removed}, "
                    f"containers:{cleanup_result.containers_removed})"
                )

                self.hooks.emit_metric(
                    "breakeramp.destroy.post_cleanup_completed",
                    amp_run_id=request.amp_run_id,
                    space_reclaimed_mb=cleanup_space_reclaimed_mb,
                    containers_removed=cleanup_result.containers_removed,
                    images_removed=cleanup_result.images_removed,
                    cache_cleared=cleanup_result.cache_cleared,
                )
            except Exception as e:
                # Post-cleanup is best-effort, don't fail the destroy
                self.hooks.emit_metric(
                    "breakeramp.destroy.post_cleanup_error",
                    amp_run_id=request.amp_run_id,
                    error=str(e),
                )

        return DestroyResponse(
            teardown_report=teardown_report,
            action_id=action_id,
        )

    def watch(self, amp_run_id: str) -> Generator[StatusEvent, None, None]:
        """Watch status events for a run.

        Args:
            amp_run_id: Run identifier

        Yields:
            Status events
        """
        status = self.status(amp_run_id)
        yield StatusEvent(
            timestamp=datetime.utcnow().isoformat(),
            status=status.phase,
            message=f"Run is in phase {status.phase}",
            details={"progress": status.progress_pct},
        )

    def list_environments(
        self,
        reconcile: bool = True,
        auto_cleanup: bool = True,
    ) -> List[Dict[str, Any]]:
        """List all active environments, optionally reconciling with container reality.

        Args:
            reconcile: If True, verify containers actually exist and mark stale ones
            auto_cleanup: If True, remove state files for environments with no containers

        Returns:
            List of environment status dicts with 'actual_status' field when reconciled
        """
        result = []
        stale_paths = []

        # Get actual containers if we need to reconcile
        actual_containers: set[str] = set()
        container_statuses: dict[str, str] = {}  # name -> status ("running", "exited", etc.)
        if reconcile:
            try:
                containers = self.executor.list_containers(all_containers=True)
                actual_containers = {c.name for c in containers}
                container_statuses = {c.name: c.status.lower() for c in containers}
            except Exception:
                # If we can't list containers (machine not running), skip reconciliation
                reconcile = False

        for path in self.environments_dir.glob("*.json"):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, IOError):
                # Corrupted state file - mark for cleanup
                stale_paths.append(path)
                continue

            amp_run_id = data.get("amp_run_id", "")
            phase = data.get("phase", "UNKNOWN")

            # Check if any containers for this run actually exist and their health
            actual_status = "UNKNOWN"
            container_count = 0
            running_count = 0
            if reconcile and amp_run_id:
                # Containers are named: {amp_run_id}-{service_name}
                run_containers = [c for c in actual_containers if c.startswith(f"{amp_run_id}-")]
                container_count = len(run_containers)
                running_count = sum(
                    1 for c in run_containers
                    if container_statuses.get(c, "") == "running"
                )

                if container_count == 0:
                    actual_status = "STALE"
                    if auto_cleanup:
                        stale_paths.append(path)
                elif running_count == container_count:
                    actual_status = "RUNNING"
                elif running_count > 0:
                    actual_status = "DEGRADED"
                else:
                    actual_status = "STOPPED"

            entry = {
                "amp_run_id": amp_run_id,
                "environment": data.get("environment"),
                "phase": phase,
                "blueprint_id": data.get("blueprint_id"),
                "created_at": data.get("created_at"),
            }

            if reconcile:
                entry["actual_status"] = actual_status
                entry["container_count"] = container_count
                entry["running_count"] = running_count

            # Only include non-stale entries (or all if auto_cleanup is False)
            if not auto_cleanup or actual_status != "STALE":
                result.append(entry)

        # Clean up stale state files
        if auto_cleanup:
            for stale_path in stale_paths:
                try:
                    # Also remove corresponding manifest
                    manifest_path = self.manifests_dir / stale_path.name
                    if manifest_path.exists():
                        manifest_path.unlink()
                    stale_path.unlink()
                except OSError:
                    pass  # Best effort cleanup

        return result

    # =========================================================================
    # Configuration
    # =========================================================================

    def configure(
        self,
        config_dir: Optional[Path] = None,
        include_blueprints: bool = False,
        blueprints: Optional[List[str]] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Bootstrap BreakerAmp configuration in a directory.

        Args:
            config_dir: Target directory (defaults to ./config/breakeramp)
            include_blueprints: Whether to copy packaged blueprints
            blueprints: Specific blueprints to copy (or all if None)
            force: Overwrite existing files

        Returns:
            Summary of what was created
        """
        config_dir = config_dir or Path.cwd() / "config" / "breakeramp"
        config_dir.mkdir(parents=True, exist_ok=True)

        # Copy environment template
        template = Path(__file__).parent / "templates" / "environments.yaml"
        if not template.exists():
            # Create a default template
            default_env = """environments:
  development:
    description: Local development environment
    default_compliance_tier: standard
    default_lifetime: 90m
    runtime:
      provider: podman
      auto_start: true
    infrastructure:
            blueprint_id: local-test-suite
      teardown_on_exit: true

  staging:
    description: Staging environment
    default_compliance_tier: strict
    default_lifetime: 4h
    runtime:
      provider: podman
      memory_limit_mb: 4096
"""
            destination_env = config_dir / "environments.yaml"
            env_status = "created"
            if destination_env.exists() and not force:
                env_status = "skipped"
            else:
                if destination_env.exists():
                    env_status = "overwritten"
                destination_env.write_text(default_env)
        else:
            destination_env = config_dir / "environments.yaml"
            env_status = "created"
            if destination_env.exists() and not force:
                env_status = "skipped"
            else:
                if destination_env.exists():
                    env_status = "overwritten"
                shutil.copyfile(template, destination_env)

        blueprint_records: List[Dict[str, Any]] = []
        blueprints_dir: Optional[Path] = None

        if include_blueprints:
            blueprints_dir = config_dir / "blueprints"
            blueprints_dir.mkdir(parents=True, exist_ok=True)

            packaged = self._discover_packaged_blueprints()
            selected = blueprints or sorted(packaged.keys())

            for bp in selected:
                source = packaged.get(bp)
                if not source:
                    blueprint_records.append({
                        "blueprint": bp,
                        "status": "missing",
                        "reason": "Blueprint not found",
                    })
                    continue

                target_path = blueprints_dir / source.name
                existed_before = target_path.exists()

                if existed_before and not force:
                    blueprint_records.append({
                        "blueprint": bp,
                        "status": "skipped",
                        "path": str(target_path),
                        "reason": "File exists",
                    })
                    continue

                shutil.copyfile(source, target_path)
                blueprint_records.append({
                    "blueprint": bp,
                    "status": "overwritten" if existed_before else "copied",
                    "path": str(target_path),
                })

        return {
            "environment_file": str(destination_env),
            "environment_status": env_status,
            "blueprints_dir": str(blueprints_dir) if blueprints_dir else None,
            "blueprints": blueprint_records,
        }
