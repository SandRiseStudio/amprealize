"""Amprealize BreakerAmp Service wrapper.

This module provides a thin wrapper around the standalone breakeramp.BreakerAmpService,
wiring hooks to amprealize services for action tracking, compliance, and metrics.

The standalone package handles all orchestration logic; this wrapper only provides
the integration glue to amprealize.s infrastructure.

NOTE: The standalone breakeramp package is REQUIRED. Install with:
    pip install -e ./packages/breakeramp
"""

from typing import Optional, Dict, Any, List, Generator
from pathlib import Path
import os
import sys
import time

# Import from standalone breakeramp package (required)
from breakeramp.service import BreakerAmpService as StandaloneBreakerAmpService
from breakeramp.hooks import BreakerAmpHooks
from breakeramp.models import (
    PlanRequest,
    PlanResponse,
    ApplyRequest,
    ApplyResponse,
    StatusResponse,
    DestroyRequest,
    DestroyResponse,
    StatusEvent,
    EnvironmentDefinition,
)
from breakeramp.executors.base import Executor
from breakeramp.executors.podman import PodmanExecutor

# amprealize services
from amprealize.action_service import ActionService
from amprealize.action_contracts import ActionCreateRequest, Actor, Action
from amprealize.compliance_service import ComplianceService, RecordStepRequest
from amprealize.metrics_service import MetricsService

# Optional Redis for availability checking
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


class RedisNotAvailableError(Exception):
    """Raised when Redis is required by blueprint but not available."""
    pass


class AmprealizeBreakerAmpService:
    """BreakerAmp service integrated with Amprealize infrastructure.

    This wrapper wires the standalone breakeramp package to amprealize services:
    - ActionService: Track actions for audit and replay
    - ComplianceService: Record compliance gates and steps
    - MetricsService: Emit telemetry events

    Usage:
        from amprealize.breakeramp import BreakerAmpService
        from amprealize.action_service import ActionService
        from amprealize.compliance_service import ComplianceService

        service = BreakerAmpService(
            action_service=action_service,
            compliance_service=compliance_service,
            metrics_service=metrics_service,
        )

        plan = service.plan(PlanRequest(...))
        result = service.apply(ApplyRequest(plan_id=plan.plan_id))
    """

    def __init__(
        self,
        action_service: ActionService,
        compliance_service: ComplianceService,
        metrics_service: Optional[MetricsService] = None,
        executor: Optional["Executor"] = None,
    ):
        self.action_service = action_service
        self.compliance_service = compliance_service
        self.metrics_service = metrics_service

        # Default actor for service-initiated actions
        self._default_actor = Actor(
            id="breakeramp-service",
            role="system",
            surface="api",
        )
        # Current actor for tracking (can be overridden per-call)
        self._current_actor: Optional[Actor] = None

        # Create hooks that wire to amprealize services
        hooks = BreakerAmpHooks(
            on_action=self._on_action,
            on_compliance_step=self._on_compliance_step,
            on_metric=self._on_metric,
        )

        # Use provided executor or default to Podman
        if executor is None:
            executor = PodmanExecutor()

        # Create the standalone service with hooks
        self._service = StandaloneBreakerAmpService(
            executor=executor,
            hooks=hooks,
        )

    # =========================================================================
    # Redis availability checking
    # =========================================================================

    def _blueprint_requires_redis(self, request: "PlanRequest") -> bool:
        """Check if the blueprint contains any Redis services.

        Scans service names and images for 'redis' to determine if Redis
        is a required dependency.

        Args:
            request: Plan request with blueprint reference

        Returns:
            True if any service appears to be Redis
        """
        # Get blueprint_id from request, may be None if using environment default
        blueprint_id = request.blueprint_id
        if not blueprint_id:
            # Try to get from environment definition
            env_name = request.environment
            if env_name in self._service.environments:
                env_def = self._service.environments[env_name]
                blueprint_id = env_def.default_blueprint
            if not blueprint_id:
                return False

        # Resolve the blueprint
        try:
            blueprint = self._service._resolve_blueprint(blueprint_id)
        except Exception:
            # If we can't resolve the blueprint, don't block on Redis check
            return False

        if blueprint is None or not hasattr(blueprint, 'services'):
            return False

        for name, spec in blueprint.services.items():
            name_lower = name.lower()
            image_lower = (spec.image or '').lower() if hasattr(spec, 'image') else ''

            # Check common Redis patterns
            if 'redis' in name_lower or 'redis' in image_lower:
                return True

        return False

    def _check_redis_available(self) -> bool:
        """Check if Redis is reachable.

        Uses environment variables for Redis connection:
        - REDIS_HOST (default: localhost)
        - REDIS_PORT (default: 6379)
        - REDIS_PASSWORD (optional)

        Returns:
            True if Redis responds to ping, False otherwise
        """
        if not REDIS_AVAILABLE:
            return False

        host = os.getenv('REDIS_HOST', 'localhost')
        port = int(os.getenv('REDIS_PORT', '6379'))
        password = os.getenv('REDIS_PASSWORD')

        try:
            client = redis.Redis(
                host=host,
                port=port,
                password=password,
                socket_connect_timeout=2.0,  # Fast fail
            )
            return client.ping()
        except (redis.ConnectionError, redis.TimeoutError, Exception):
            return False

    def _bootstrap_redis(self) -> bool:
        """Bootstrap a Redis container if needed for planner state storage.

        This solves the chicken-and-egg problem where the planner needs Redis
        to store state, but Redis is part of the blueprint being planned.

        Returns:
            True if Redis was bootstrapped or already available, False on failure
        """
        from breakeramp.executors.base import ContainerRunConfig

        host = os.getenv('REDIS_HOST', 'localhost')
        port = int(os.getenv('REDIS_PORT', '6379'))
        container_name = "amprealize-redis-bootstrap"

        try:
            executor = self._service.executor

            # Check if bootstrap container already exists and start it
            try:
                info = executor.inspect_container(container_name)
                print(f"  Found existing Redis container: {container_name} (status: {info.status})", file=sys.stderr)
                if info.status != "running":
                    # Container exists but not running - start it
                    # Use ensure_container_ready which handles start/recreate
                    config = ContainerRunConfig(
                        name=container_name,
                        image="docker.io/redis:7-alpine",
                        ports=[f"{port}:6379"],
                        detach=True,
                    )
                    executor.ensure_container_ready(container_name, config, reuse_if_running=True)

                # Wait briefly for Redis to be ready
                for _ in range(10):
                    if self._check_redis_available():
                        print(f"  Redis is ready on port {port}", file=sys.stderr)
                        return True
                    time.sleep(0.5)
                return self._check_redis_available()
            except Exception:
                print(f"  Container {container_name} not found, creating new one...", file=sys.stderr)

            # Create and start new Redis container
            print(f"  Starting Redis container on port {port}...", file=sys.stderr)
            config = ContainerRunConfig(
                name=container_name,
                image="docker.io/redis:7-alpine",
                ports=[f"{port}:6379"],
                detach=True,
            )
            container_id = executor.run_container(config)
            print(f"  Redis container started: {container_id}", file=sys.stderr)

            # Wait for Redis to be ready
            for _ in range(20):
                if self._check_redis_available():
                    print(f"  Redis is ready on port {port}", file=sys.stderr)
                    return True
                time.sleep(0.5)

            print(f"  Warning: Redis container started but not responding on port {port}", file=sys.stderr)
            return False

        except Exception as e:
            import traceback
            print(f"Warning: Redis bootstrap failed: {e}", file=sys.stderr)
            print(f"  Details: {traceback.format_exc()}", file=sys.stderr)
            return False

    def _ensure_redis_available(self, request: "PlanRequest") -> None:
        """Ensure Redis is available if required by the blueprint.

        If the blueprint requires Redis but it's not running, this method
        will attempt to bootstrap a Redis container automatically.

        Args:
            request: Plan request to check

        Raises:
            RedisNotAvailableError: If Redis is required but cannot be started
        """
        if self._blueprint_requires_redis(request):
            if not self._check_redis_available():
                # Attempt to bootstrap Redis before planning
                print("Redis not available - bootstrapping Redis container...", file=sys.stderr)
                if not self._bootstrap_redis():
                    raise RedisNotAvailableError(
                        "Blueprint requires Redis but Redis could not be started. "
                        "Check that the container runtime (Podman/Docker) is available "
                        "and the Redis image can be pulled."
                    )

    # =========================================================================
    # Hook implementations - wire to amprealize services
    # =========================================================================

    def _get_actor(self) -> Actor:
        """Get the current actor, falling back to default."""
        return self._current_actor if self._current_actor is not None else self._default_actor

    def _on_action(
        self,
        action_type: str,
        payload: Dict[str, Any],
        run_id: Optional[str] = None,
        behaviors: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Record an action via ActionService."""
        request = ActionCreateRequest(
            artifact_path=f"breakeramp/{action_type}",
            summary=f"BreakerAmp {action_type}: {payload.get('description', '')}",
            behaviors_cited=behaviors or [],
            metadata=payload,
            related_run_id=run_id,
        )

        try:
            result: Action = self.action_service.create_action(request, self._get_actor())
            return result.action_id
        except Exception as e:
            # Log but don't fail the operation
            print(f"Warning: Failed to record action: {e}")
            return None

    def _on_compliance_step(
        self,
        checklist_id: str,
        step_id: str,
        status: str,
        evidence: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a compliance step via ComplianceService."""
        request = RecordStepRequest(
            checklist_id=checklist_id,
            title=step_id,  # Use step_id as title
            status=status,
            evidence=evidence,
            behaviors_cited=[],
        )

        try:
            self.compliance_service.record_step(request, self._get_actor())
        except Exception as e:
            # Log but don't fail the operation
            print(f"Warning: Failed to record compliance step: {e}")

    def _on_metric(
        self,
        event_name: str,
        payload: Dict[str, Any],
        actor: Optional[Dict[str, str]] = None,
    ) -> None:
        """Emit a metrics event via MetricsService."""
        if self.metrics_service is None:
            return

        try:
            self.metrics_service.emit_event(event_name, payload, actor=actor)
        except Exception as e:
            # Log but don't fail the operation
            print(f"Warning: Failed to emit metric: {e}")

    def _on_audit(
        self,
        event_type: str,
        details: Dict[str, Any],
        run_id: Optional[str] = None,
    ) -> None:
        """Record an audit event (delegates to action recording)."""
        self._on_action(
            action_type=f"audit.{event_type}",
            payload=details,
            run_id=run_id,
        )

    # =========================================================================
    # Delegate to standalone service
    # =========================================================================

    def plan(self, request: "PlanRequest", actor: Optional[Actor] = None) -> "PlanResponse":
        """Create an execution plan for an environment.

        Args:
            request: Plan request with blueprint, environment, and options
            actor: Optional actor override for action tracking

        Returns:
            PlanResponse with plan_id, manifest, and estimates

        Raises:
            RedisNotAvailableError: If blueprint requires Redis but it's not reachable
        """
        # Track who initiated this plan
        if actor is not None:
            self._current_actor = actor

        # Check Redis availability if blueprint requires it
        self._ensure_redis_available(request)

        return self._service.plan(request)

    def apply(self, request: "ApplyRequest", actor: Optional[Actor] = None) -> "ApplyResponse":
        """Apply a plan to create/update infrastructure.

        Args:
            request: Apply request with plan_id or manifest
            actor: Optional actor override for action tracking

        Returns:
            ApplyResponse with environment outputs and status
        """
        if actor is not None:
            self._current_actor = actor
        return self._service.apply(request)

    def status(self, amp_run_id: str) -> "StatusResponse":
        """Get status of a running or completed operation.

        Args:
            amp_run_id: The run ID to check

        Returns:
            StatusResponse with phase, progress, and checks
        """
        return self._service.status(amp_run_id)

    def destroy(self, request: "DestroyRequest") -> "DestroyResponse":
        """Destroy an environment and clean up resources.

        Args:
            request: Destroy request with run_id and options

        Returns:
            DestroyResponse with teardown report
        """
        return self._service.destroy(request)

    def watch(self, amp_run_id: str) -> Generator["StatusEvent", None, None]:
        """Watch status updates for a running operation.

        Args:
            amp_run_id: The run ID to watch

        Yields:
            StatusEvent updates as they occur
        """
        return self._service.watch(amp_run_id)

    def list_blueprints(self) -> List[Dict[str, Any]]:
        """List available blueprints.

        Returns:
            List of blueprint metadata dicts
        """
        return self._service.list_blueprints()

    def list_environments(self) -> List[Dict[str, Any]]:
        """List registered environments.

        Returns:
            List of environment metadata dicts
        """
        return self._service.list_environments()

    def list_runs(self, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """List tracked runs.

        Args:
            status_filter: Optional filter by status

        Returns:
            List of run metadata dicts
        """
        return self._service.list_runs(status_filter=status_filter)

    def configure(
        self,
        config_dir: Optional[str] = None,
        include_blueprints: bool = False,
        blueprints: Optional[List[str]] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Configure breakeramp in a directory.

        Sets up configuration files and optionally copies blueprint definitions.

        Args:
            config_dir: Directory to configure (defaults to ./config/breakeramp)
            include_blueprints: Whether to copy packaged blueprints
            blueprints: Specific blueprints to copy (or all if None)
            force: Overwrite existing files

        Returns:
            Configuration result with status and file paths
        """
        path = Path(config_dir) if config_dir else None
        return self._service.configure(path, include_blueprints, blueprints, force)

    def bootstrap(
        self,
        target_directory: Optional[Path] = None,
        include_blueprints: bool = False,
        blueprints: Optional[List[str]] = None,
        force: bool = False,
        env_template: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Bootstrap breakeramp configuration in a directory.

        This is a CLI-friendly wrapper around configure() that:
        - Uses target_directory parameter name (vs config_dir)
        - Accepts optional env_template parameter (for future custom templates)
        - Returns output formatted for CLI consumption with environment_file key

        Args:
            target_directory: Target directory (defaults to ./config/breakeramp)
            include_blueprints: Whether to copy packaged blueprints
            blueprints: Specific blueprints to copy (or all if None)
            force: Overwrite existing files
            env_template: Optional custom environment template file (currently unused)

        Returns:
            Configuration result with status, file paths, and environment_file
        """
        # Convert to config_dir parameter
        config_dir = str(target_directory) if target_directory else None

        result = self.configure(
            config_dir=config_dir,
            include_blueprints=include_blueprints,
            blueprints=blueprints,
            force=force,
        )

        # Ensure result has environment_file key for CLI compatibility
        if "environment_file" not in result and "config_dir" in result:
            result["environment_file"] = str(Path(result["config_dir"]) / "environments.yaml")

        return result

    # =========================================================================
    # Properties that delegate to standalone service
    # =========================================================================

    @property
    def environments(self) -> Dict[str, "EnvironmentDefinition"]:
        """Get registered environments."""
        return self._service.environments

    @property
    def base_dir(self) -> Path:
        """Get base storage directory."""
        return self._service.base_dir

    @property
    def pkg_blueprints_dir(self) -> Path:
        """Get packaged blueprints directory."""
        return self._service.pkg_blueprints_dir

    def register_environment(self, env_def: "EnvironmentDefinition") -> None:
        """Register an environment definition."""
        self._service.register_environment(env_def)

    def load_environments(self) -> None:
        """Load environments from configuration file."""
        self._service.load_environments()
