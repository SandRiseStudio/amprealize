"""BreakerAmp data models.

This module contains all Pydantic models for BreakerAmp, including:
- Blueprint and service specifications
- Environment and runtime configuration
- Request/response models for plan, apply, status, and destroy operations
- Environment manifest validation
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# =============================================================================
# Infrastructure Models
# =============================================================================


class ServiceSpec(BaseModel):
    """Specification for a single service within a blueprint.

    Attributes:
        image: Container image name (e.g., "postgres:16-alpine")
        ports: Port mappings in "host:container" format
        environment: Environment variables
        volumes: Volume/bind mount specifications
        command: Optional command override
        cpu_cores: CPU cores required
        memory_mb: Memory required in MB
        bandwidth_mbps: Estimated network bandwidth in Mbps
        module: Module grouping (e.g., "datastores", "observability")
    """
class BuildSpec(BaseModel):
    """Optional image build specification for a service.

    This enables blueprints to declare local-build images (e.g. `:dev` tags)
    so `apply` can build them when missing instead of trying to pull from a
    remote registry.
    """

    context: str = Field(".", description="Build context directory")
    dockerfile: Optional[str] = Field(None, description="Path to Dockerfile relative to context")
    rebuild: bool = Field(False, description="Force rebuild even if image exists")
    pull: bool = Field(False, description="Pull base images during build")
    build_args: Dict[str, Any] = Field(default_factory=dict, description="Build-time args")


class PostStartCommand(BaseModel):
    """A command to execute inside a container after it starts and passes healthchecks."""

    command: List[str] = Field(description="Command and arguments to exec in the container")
    description: str = Field("", description="Human-readable description of the command")
    timeout_s: int = Field(300, description="Timeout in seconds for command execution")


class HealthcheckSpec(BaseModel):
    """Container healthcheck specification (matches Docker/Podman healthcheck format)."""

    test: List[str] = Field(description="Healthcheck command (e.g., ['CMD-SHELL', 'curl -f ...'])")
    interval: str = Field("10s", description="Time between checks")
    timeout: str = Field("5s", description="Timeout per check")
    retries: int = Field(3, description="Consecutive failures before unhealthy")
    start_period: Optional[str] = Field(None, description="Grace period before checks count")


class ServiceSpec(BaseModel):
    """Specification for a single service within a blueprint.

    Attributes:
        image: Container image name (e.g., "postgres:16-alpine")
        ports: Port mappings in "host:container" format
        environment: Environment variables
        volumes: Volume/bind mount specifications
        command: Optional command override
        cpu_cores: CPU cores required
        memory_mb: Memory required in MB
        bandwidth_mbps: Estimated network bandwidth in Mbps
        module: Module grouping (e.g., "datastores", "observability")
        build: Optional local build spec (context/dockerfile/rebuild)
        depends_on: Optional dependency list (best-effort ordering)
        healthcheck: Container healthcheck configuration
        healthcheck_timeout_s: Overall timeout waiting for healthcheck to pass
        post_start_commands: Commands to exec after container is healthy
        extra_hosts: Extra /etc/hosts entries (e.g., "host.containers.internal:host-gateway")
        privileged: Run container in privileged mode
    """

    image: str
    ports: List[str] = Field(default_factory=list)
    environment: Dict[str, str] = Field(default_factory=dict)
    volumes: List[str] = Field(default_factory=list)
    command: Optional[List[str]] = None
    workdir: Optional[str] = Field(None, description="Working directory for container")
    cpu_cores: Optional[float] = Field(None, description="Number of CPU cores required")
    memory_mb: Optional[int] = Field(None, description="Memory required in MB")
    bandwidth_mbps: Optional[int] = Field(None, description="Estimated network bandwidth in Mbps")
    module: Optional[str] = Field(
        None, description="Module name this service belongs to (e.g. 'datastores', 'observability')"
    )
    build: Optional[BuildSpec] = None
    depends_on: List[str] = Field(default_factory=list)
    healthcheck: Optional[HealthcheckSpec] = Field(None, description="Container healthcheck config")
    healthcheck_timeout_s: Optional[int] = Field(None, description="Overall healthcheck wait timeout in seconds")
    post_start_commands: List[PostStartCommand] = Field(
        default_factory=list, description="Commands to exec after container is healthy"
    )
    extra_hosts: List[str] = Field(default_factory=list, description="Extra /etc/hosts entries")
    privileged: bool = Field(False, description="Run container in privileged mode")


class ModuleSpec(BaseModel):
    """Specification for a blueprint module (group of services)."""

    description: str = Field("", description="Human-readable module description")
    enabled: bool = Field(True, description="Whether this module's services should be provisioned")


class Blueprint(BaseModel):
    """Blueprint defining a multi-service environment.

    Blueprints are the core configuration unit for BreakerAmp, defining
    the services that make up an environment.

    Attributes:
        name: Blueprint identifier
        version: Blueprint version
        services: Map of service name to specification
        modules: Map of module name to module spec (controls enabled/disabled)

    Example:
        blueprint = Blueprint(
            name="postgres-dev",
            version="1.0",
            services={
                "postgres": ServiceSpec(
                    image="postgres:16-alpine",
                    ports=["5432:5432"],
                    environment={"POSTGRES_PASSWORD": "dev"}
                )
            }
        )
    """
    name: str
    version: str
    services: Dict[str, ServiceSpec]
    modules: Dict[str, ModuleSpec] = Field(default_factory=dict)

    def validate_topology(self) -> List[str]:
        """Validate the blueprint topology.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors: List[str] = []
        if not self.services:
            errors.append("Blueprint must contain at least one service")

        for name, service in self.services.items():
            if not name.isidentifier() and not name.replace("-", "_").isidentifier():
                # Allow hyphens in service names (e.g. redis-cache) but otherwise must be identifier-like
                errors.append(f"Service name '{name}' contains invalid characters")

            if not service.image:
                errors.append(f"Service '{name}' is missing image definition")

            for port in service.ports:
                if ":" not in port:
                    errors.append(
                        f"Service '{name}' has invalid port mapping '{port}' (expected host:container)"
                    )

        return errors


class RuntimeConfig(BaseModel):
    """Runtime configuration for container execution.

    Attributes:
        provider: Container runtime ("native", "podman", "docker")
        podman_machine: Podman machine name (macOS/Windows)
        podman_connection: Podman connection name
        auto_start: Auto-start machine if stopped
        auto_init: Auto-initialize machine if not exists
        memory_limit_mb: Memory limit in MB
        cpu_limit: CPU limit (cores)
        network_mbps: Network bandwidth limit in Mbps
        auto_scaling_strategy: How to handle resource constraints
    """
    provider: Literal["native", "podman", "docker"] = "native"
    podman_machine: Optional[str] = None
    podman_connection: Optional[str] = None
    auto_start: bool = False
    auto_init: bool = False
    memory_limit_mb: Optional[int] = None
    cpu_limit: Optional[int] = None
    network_mbps: Optional[int] = None
    auto_scaling_strategy: Literal["fail", "serialize", "scale_out"] = "fail"


class InfrastructureConfig(BaseModel):
    """Infrastructure configuration for an environment.

    Attributes:
        blueprint_id: Default blueprint to use
        teardown_on_exit: Whether to teardown on destroy
    """
    blueprint_id: Optional[str] = None
    teardown_on_exit: bool = True


class MigrationSpec(BaseModel):
    """Specification for a database migration to run after environment apply.

    Attributes:
        name: Human-readable migration name
        alembic_config: Path to Alembic config file (e.g., "alembic.ini")
        database_url_env: Environment variable name for the database URL
        target_revision: Target revision (default: "head")
        enabled: Whether this migration is enabled
    """
    name: str
    alembic_config: str = "alembic.ini"
    database_url_env: str = "DATABASE_URL"
    target_revision: str = "head"
    enabled: bool = True


class MigrationConfig(BaseModel):
    """Configuration for database migrations to run after apply.

    Migrations run from the host machine after containers are healthy.
    This ensures database schemas are created before the API container
    starts handling requests.

    Attributes:
        auto_run: Whether to automatically run migrations on apply
        migrations: List of migration specifications
    """
    auto_run: bool = True
    migrations: List[MigrationSpec] = Field(default_factory=list)


class EnvironmentDefinition(BaseModel):
    """Complete environment definition.

    Environments combine runtime and infrastructure configuration
    with default settings for compliance and lifecycle.

    Attributes:
        name: Environment name (e.g., "development", "staging")
        description: Human-readable description
        default_compliance_tier: Default compliance level
        default_lifetime: Default environment lifetime
        active_modules: List of modules to activate
        runtime: Runtime configuration
        infrastructure: Infrastructure configuration
        migrations: Database migration configuration (auto-runs on apply)
        variables: Environment variables for substitution
    """
    name: str
    description: Optional[str] = None
    default_compliance_tier: str = "standard"
    default_lifetime: str = "90m"
    active_modules: Optional[List[str]] = None
    runtime: RuntimeConfig = Field(default_factory=lambda: RuntimeConfig())
    infrastructure: InfrastructureConfig = Field(default_factory=lambda: InfrastructureConfig())
    migrations: Optional[MigrationConfig] = None
    variables: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Plan Operation Models
# =============================================================================


class PlanRequest(BaseModel):
    """Request to plan an environment deployment.

    Attributes:
        blueprint_id: Blueprint to use (or from environment default)
        environment: Target environment name
        lifetime: Environment lifetime (e.g., "2h", "90m")
        compliance_tier: Compliance tier override
        checklist_id: Optional compliance checklist to track
        behaviors: Behavior references for tracking
        variables: Variable overrides
        active_modules: Module filter override
        force_podman: Skip Podman checks/warnings
        machine_disk_size_gb: Override disk size for Podman machine
    """
    blueprint_id: Optional[str] = None
    environment: str
    lifetime: Optional[str] = None
    compliance_tier: Optional[str] = None
    checklist_id: Optional[str] = None
    behaviors: List[str] = Field(default_factory=list)
    variables: Dict[str, Any] = Field(default_factory=dict)
    active_modules: Optional[List[str]] = Field(
        None, description="Override active modules for this plan"
    )
    force_podman: bool = False
    machine_disk_size_gb: Optional[int] = Field(
        None, description="Override disk size for Podman machine initialization"
    )


class EnvironmentEstimates(BaseModel):
    """Resource estimates for a planned environment.

    Attributes:
        cost_estimate: Estimated cost (placeholder for cloud)
        memory_footprint_mb: Total memory requirement in MB
        bandwidth_mbps: Network bandwidth estimate
        region: Target region
        expected_boot_duration_s: Estimated startup time
    """
    cost_estimate: float
    memory_footprint_mb: int
    bandwidth_mbps: int = 0
    region: str
    expected_boot_duration_s: int


class PlanResponse(BaseModel):
    """Response from a plan operation.

    Attributes:
        plan_id: Unique plan identifier
        amp_run_id: Run identifier for tracking
        signed_manifest: Complete manifest for apply
        environment_estimates: Resource estimates
    """
    plan_id: str
    amp_run_id: str
    signed_manifest: Dict[str, Any]
    environment_estimates: EnvironmentEstimates


# =============================================================================
# Apply Operation Models
# =============================================================================


class ApplyRequest(BaseModel):
    """Request to apply a plan and provision infrastructure.

    Attributes:
        plan_id: Plan to apply (from PlanResponse)
        manifest: Direct manifest (alternative to plan_id)
        watch: Whether to watch for completion
        resume: Resume a partial apply
        force_podman: Skip Podman checks/warnings
        skip_resource_check: Skip host/machine resource health check
        auto_cleanup: Automatically cleanup resources when low before provisioning
        auto_cleanup_aggressive: Use aggressive cleanup (includes all cleanup options except volumes)
        auto_cleanup_include_volumes: Include volumes in auto-cleanup (WARNING: may lose data)
        auto_cleanup_max_retries: Max cleanup+recheck cycles before giving up
        allow_host_resource_warning: Allow apply to proceed if only host resources are low
            (VM resources are sufficient). Host cleanup is limited compared to VM cleanup.
        min_disk_gb: Minimum disk space required (default: 5.0 GB)
        min_memory_mb: Minimum memory required (default: 1024 MB)
        proactive_cleanup: Run cleanup BEFORE resource check to maximize available resources
        blueprint_aware_memory_check: Use blueprint memory estimates instead of fixed threshold
        memory_safety_margin_mb: Extra memory to require beyond blueprint estimate (default: 512 MB)
        auto_resolve_stale: Automatically remove stale/exited/dead containers before apply
        auto_resolve_conflicts: Automatically resolve port conflicts (stop conflicting containers/processes)
        stale_max_age_hours: Max age for stale container cleanup (None = any age, 0 = all stale)
    """
    plan_id: Optional[str] = None
    manifest: Optional[Dict[str, Any]] = None
    watch: bool = True
    resume: bool = False
    force_podman: bool = False
    skip_resource_check: bool = False
    auto_cleanup: bool = False
    auto_cleanup_aggressive: bool = False
    auto_cleanup_include_volumes: bool = False
    auto_cleanup_max_retries: int = 3
    allow_host_resource_warning: bool = False
    min_disk_gb: float = 5.0
    min_memory_mb: float = 1024.0
    proactive_cleanup: bool = False
    blueprint_aware_memory_check: bool = True
    memory_safety_margin_mb: float = 512.0
    # Automatic conflict resolution options (default: enabled for zero-friction apply)
    auto_resolve_stale: bool = True
    auto_resolve_conflicts: bool = True
    stale_max_age_hours: Optional[float] = 0.0  # 0 = clean all stale, None = skip age check
    # Force rebuild of local images (useful for fresh starts with code changes)
    rebuild_images: bool = False


class ApplyResponse(BaseModel):
    """Response from an apply operation.

    Attributes:
        environment_outputs: Service outputs (container IDs, etc.)
        status_stream_url: URL for status streaming
        action_id: Action tracking ID
        amp_run_id: Run identifier
    """
    environment_outputs: Dict[str, Any]
    status_stream_url: Optional[str] = None
    action_id: str
    amp_run_id: str


# =============================================================================
# Status Operation Models
# =============================================================================


class HealthCheck(BaseModel):
    """Health check result for a service.

    Attributes:
        name: Service name
        status: Health status
        last_probe: Last check timestamp
    """
    name: str
    status: str
    last_probe: datetime


class TelemetryData(BaseModel):
    """Telemetry data for an environment.

    Attributes:
        token_savings_pct: Token savings percentage
        behavior_reuse_pct: Behavior reuse percentage
    """
    token_savings_pct: float
    behavior_reuse_pct: float


class AuditEntry(BaseModel):
    """Audit trail entry.

    Attributes:
        timestamp: Entry timestamp
        type: Entry type (ACTION, COMPLIANCE, etc.)
        summary: Brief summary
        details: Additional details
    """
    timestamp: str
    type: str
    summary: str
    details: Dict[str, Any] = Field(default_factory=dict)


class StatusResponse(BaseModel):
    """Response from a status query.

    Attributes:
        amp_run_id: Run identifier
        phase: Current phase (PLANNED, PROVISIONING, APPLIED, etc.)
        progress_pct: Progress percentage
        checks: Health check results
        environment_outputs_path: Path to outputs file
        next_maintenance: Next scheduled maintenance
        telemetry: Telemetry data
        audit_trail: Audit entries
    """
    amp_run_id: str
    phase: str
    progress_pct: int
    checks: List[HealthCheck]
    environment_outputs_path: Optional[str] = None
    next_maintenance: Optional[datetime] = None
    telemetry: Optional[TelemetryData] = None
    audit_trail: List[AuditEntry] = Field(default_factory=list)


class StatusEvent(BaseModel):
    """Status event for streaming updates.

    Attributes:
        timestamp: Event timestamp
        status: Status string
        message: Human-readable message
        details: Additional details
    """
    timestamp: str
    status: str
    message: str
    details: Optional[Dict[str, Any]] = None


# =============================================================================
# Destroy Operation Models
# =============================================================================


class DestroyRequest(BaseModel):
    """Request to destroy an environment.

    Attributes:
        amp_run_id: Run to destroy
        cascade: Cascade to dependent resources
        reason: Reason for destruction
        force_podman: Skip Podman checks/warnings
        cleanup_after_destroy: Run resource cleanup after destroying containers (default: True)
        cleanup_aggressive: Use aggressive cleanup including dangling images/cache (default: True)
        cleanup_include_volumes: Include volumes in cleanup (WARNING: may lose data)
    """
    amp_run_id: str
    cascade: bool = True
    reason: str
    force_podman: bool = False
    cleanup_after_destroy: bool = True
    cleanup_aggressive: bool = True
    cleanup_include_volumes: bool = False


class DestroyResponse(BaseModel):
    """Response from a destroy operation.

    Attributes:
        teardown_report: List of torn down services
        action_id: Action tracking ID
    """
    teardown_report: List[str]
    action_id: str


# =============================================================================
# Strict Validation Models (for environments.yaml)
# =============================================================================


class StrictRuntimeConfig(BaseModel):
    """Runtime configuration with strict validation (forbids extra fields).

    Used for validating user-provided environments.yaml files.
    """
    model_config = ConfigDict(extra="forbid")

    provider: Literal["native", "podman", "docker"] = "native"
    podman_machine: Optional[str] = None
    podman_connection: Optional[str] = None
    auto_start: bool = False
    auto_init: bool = False
    memory_limit_mb: Optional[int] = None
    cpu_limit: Optional[int] = None
    network_mbps: Optional[int] = None
    auto_scaling_strategy: Literal["fail", "serialize", "scale_out"] = "fail"


class StrictInfrastructureConfig(BaseModel):
    """Infrastructure configuration with strict validation."""
    model_config = ConfigDict(extra="forbid")

    blueprint_id: Optional[str] = None
    teardown_on_exit: bool = True


class StrictEmbeddingConfig(BaseModel):
    """Embedding configuration with strict validation."""
    model_config = ConfigDict(extra="forbid")

    model_name: Optional[str] = None
    lazy_load: bool = True
    cache_size: int = 1000
    rollout_percentage: int = 100


class StrictEnvironmentDefinition(BaseModel):
    """Environment definition with strict validation (forbids extra fields).

    Used for validating user-provided environments.yaml files.
    All unknown fields will cause validation errors.
    """
    model_config = ConfigDict(extra="forbid")

    name: str
    description: Optional[str] = None
    default_compliance_tier: str = "standard"
    default_lifetime: str = "90m"
    active_modules: Optional[List[str]] = None
    runtime: StrictRuntimeConfig = Field(default_factory=StrictRuntimeConfig)
    infrastructure: StrictInfrastructureConfig = Field(default_factory=StrictInfrastructureConfig)
    embedding: Optional[StrictEmbeddingConfig] = None
    variables: Dict[str, Any] = Field(default_factory=dict)


class EnvironmentManifest(BaseModel):
    """Complete environment manifest with strict validation.

    This model validates the structure of environments.yaml files,
    ensuring all fields are known and properly typed.

    Example:
        manifest = EnvironmentManifest.validate_file("environments.yaml")
        for env_name, env_def in manifest.environments.items():
            print(f"{env_name}: {env_def.description}")

    Raises:
        ValidationError: If the file contains unknown fields or invalid types
    """
    model_config = ConfigDict(extra="forbid")

    environments: Dict[str, StrictEnvironmentDefinition]

    @classmethod
    def validate_file(cls, path: str | Path) -> "EnvironmentManifest":
        """Load and validate an environments.yaml file.

        Args:
            path: Path to the environments.yaml file

        Returns:
            Validated EnvironmentManifest instance

        Raises:
            FileNotFoundError: If the file does not exist
            yaml.YAMLError: If the file is not valid YAML
            ValidationError: If the file structure is invalid
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Environment file not found: {path}")

        with open(path, "r") as f:
            data = yaml.safe_load(f)

        if data is None:
            raise ValueError(f"Environment file is empty: {path}")

        # Ensure each environment has a 'name' field if not provided
        if "environments" in data:
            for env_name, env_data in data["environments"].items():
                if isinstance(env_data, dict):
                    env_data.setdefault("name", env_name)

        return cls.model_validate(data)

    @classmethod
    def validate_dict(cls, data: Dict[str, Any]) -> "EnvironmentManifest":
        """Validate a dictionary as an environment manifest.

        Args:
            data: Dictionary to validate

        Returns:
            Validated EnvironmentManifest instance

        Raises:
            ValidationError: If the structure is invalid
        """
        # Ensure each environment has a 'name' field if not provided
        if "environments" in data:
            for env_name, env_data in data["environments"].items():
                if isinstance(env_data, dict):
                    env_data.setdefault("name", env_name)

        return cls.model_validate(data)

    def get_environment(self, name: str) -> Optional[StrictEnvironmentDefinition]:
        """Get an environment definition by name.

        Args:
            name: Environment name

        Returns:
            Environment definition or None if not found
        """
        return self.environments.get(name)

    def list_environments(self) -> List[str]:
        """List all environment names.

        Returns:
            List of environment names
        """
        return list(self.environments.keys())


# =============================================================================
# Test Planning Models
# =============================================================================


class TestSuiteDefinition(BaseModel):
    """Definition of a test suite with marker-to-service mappings."""

    name: str = Field(default="default", description="Name of the test suite")
    description: str = Field(default="", description="Description of the test suite")
    marker_mappings: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Mapping of pytest markers to required service names"
    )
    default_services: List[str] = Field(
        default_factory=list,
        description="Services always required for this suite"
    )
    timeout_minutes: int = Field(
        default=30,
        description="Default timeout for test runs in minutes"
    )


class PlanForTestsRequest(BaseModel):
    """Request to plan infrastructure for running tests."""

    test_paths: List[str] = Field(
        description="Paths to test files or directories to analyze"
    )
    blueprint_id: Optional[str] = Field(
        default=None,
        description="Blueprint ID to use (uses environment default if not specified)"
    )
    environment: Optional[str] = Field(
        default=None,
        description="Environment name to use for configuration"
    )
    markers: Optional[List[str]] = Field(
        default=None,
        description="Specific pytest markers to filter for"
    )
    marker_mappings: Optional[Dict[str, List[str]]] = Field(
        default=None,
        description="Override marker-to-service mappings"
    )
    suite_config_path: Optional[str] = Field(
        default=None,
        description="Path to test suite YAML configuration file"
    )
    compliance_tier: Optional[str] = Field(
        default=None,
        description="Compliance tier to use"
    )
    lifetime: Optional[str] = Field(
        default="30m",
        description="How long the test environment should live"
    )


class PlanForTestsResponse(BaseModel):
    """Response from test infrastructure planning."""

    plan_id: str = Field(description="Unique ID for this test plan")
    amp_run_id: str = Field(description="BreakerAmp run ID")
    required_services: List[str] = Field(
        description="Services required to run the tests"
    )
    startup_order: List[str] = Field(
        description="Order in which services should start"
    )
    discovered_markers: List[str] = Field(
        default_factory=list,
        description="Pytest markers discovered in test files"
    )
    service_sources: Dict[str, str] = Field(
        default_factory=dict,
        description="Why each service is required (marker, import, etc.)"
    )
    test_files_analyzed: int = Field(
        default=0,
        description="Number of test files analyzed"
    )
    analysis_errors: List[str] = Field(
        default_factory=list,
        description="Any errors encountered during analysis"
    )
    minimal_blueprint: Dict[str, Any] = Field(
        description="The minimal blueprint with only required services"
    )
    environment_estimates: Optional[EnvironmentEstimates] = Field(
        default=None,
        description="Resource estimates for the minimal environment"
    )


class RunTestsRequest(BaseModel):
    """Request to run tests with automatic infrastructure management."""

    test_paths: List[str] = Field(
        description="Paths to test files or directories to run"
    )
    blueprint_id: Optional[str] = Field(
        default=None,
        description="Blueprint ID to use"
    )
    environment: Optional[str] = Field(
        default=None,
        description="Environment name to use"
    )
    markers: Optional[List[str]] = Field(
        default=None,
        description="Pytest markers to filter tests"
    )
    marker_mappings: Optional[Dict[str, List[str]]] = Field(
        default=None,
        description="Override marker-to-service mappings"
    )
    suite_config_path: Optional[str] = Field(
        default=None,
        description="Path to test suite YAML configuration"
    )
    pytest_args: Optional[List[str]] = Field(
        default=None,
        description="Additional arguments to pass to pytest"
    )
    timeout_minutes: int = Field(
        default=30,
        description="Timeout for test run in minutes"
    )
    keep_infrastructure: bool = Field(
        default=False,
        description="Keep infrastructure running after tests complete"
    )
    verbose: bool = Field(
        default=False,
        description="Enable verbose output"
    )


class RunTestsResponse(BaseModel):
    """Response from running tests."""

    success: bool = Field(description="Whether all tests passed")
    plan_id: str = Field(description="ID of the test plan used")
    amp_run_id: str = Field(description="BreakerAmp run ID")
    exit_code: int = Field(description="Pytest exit code")
    tests_run: int = Field(default=0, description="Number of tests executed")
    tests_passed: int = Field(default=0, description="Number of tests passed")
    tests_failed: int = Field(default=0, description="Number of tests failed")
    tests_skipped: int = Field(default=0, description="Number of tests skipped")
    tests_error: int = Field(default=0, description="Number of tests with errors")
    duration_seconds: float = Field(
        default=0.0,
        description="Total duration of test run in seconds"
    )
    infrastructure_time_seconds: float = Field(
        default=0.0,
        description="Time spent setting up/tearing down infrastructure"
    )
    output: str = Field(default="", description="Pytest output")
    services_started: List[str] = Field(
        default_factory=list,
        description="Services that were started for this run"
    )
    errors: List[str] = Field(
        default_factory=list,
        description="Any errors encountered"
    )
