"""Pytest plugin for BreakerAmp test infrastructure.

This module provides pytest integration for automatic environment provisioning
during test execution. It supports:

1. @pytest.mark.requires_services("postgres", "redis") - declarative service requirements
2. breakeramp fixture - automatic provision/teardown with configurable scope
3. Service output injection via environment variables

Installation:
    # In pyproject.toml
    [project.optional-dependencies]
    pytest = ["pytest>=7.0"]

    [project.entry-points.pytest11]
    breakeramp = "breakeramp.pytest_plugin"

Usage:
    # Test file
    import pytest

    @pytest.mark.requires_services("postgres", "redis")
    def test_with_infrastructure(breakeramp):
        # Environment is automatically provisioned
        postgres_url = breakeramp.get_url("postgres")
        assert postgres_url is not None

    # Or use fixtures directly
    @pytest.fixture(scope="module")
    def database_url(breakeramp):
        return breakeramp.get_url("postgres")

Configuration (pytest.ini or pyproject.toml):
    [tool.pytest.ini_options]
    breakeramp_blueprint = "full-stack"
    breakeramp_environment = "development"
    breakeramp_auto_provision = true
"""

import os
import warnings
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, List, Optional, Set

import pytest


@dataclass
class BreakerAmpContext:
    """Context object provided to tests via the breakeramp fixture.

    Attributes:
        services: Dict mapping service names to their outputs
        amp_run_id: The breakeramp run identifier
        plan_id: The plan identifier
        startup_order: Order in which services were started
    """
    services: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    amp_run_id: Optional[str] = None
    plan_id: Optional[str] = None
    startup_order: List[str] = field(default_factory=list)
    _environment_vars_set: List[str] = field(default_factory=list)

    def get_url(self, service: str) -> Optional[str]:
        """Get the URL for a service.

        Args:
            service: Service name (e.g., "postgres", "redis")

        Returns:
            URL string or None if not available
        """
        if service not in self.services:
            return None
        return self.services[service].get("url")

    def get_host(self, service: str) -> Optional[str]:
        """Get the host for a service."""
        if service not in self.services:
            return None
        return self.services[service].get("host", "localhost")

    def get_port(self, service: str) -> Optional[int]:
        """Get the port for a service."""
        if service not in self.services:
            return None
        port = self.services[service].get("port")
        return int(port) if port else None

    def get_output(self, service: str, key: str) -> Optional[Any]:
        """Get a specific output value for a service."""
        if service not in self.services:
            return None
        return self.services[service].get(key)

    def is_provisioned(self) -> bool:
        """Check if the environment is provisioned."""
        return bool(self.amp_run_id and self.services)

    def inject_env_vars(self) -> None:
        """Inject service outputs as environment variables.

        Sets variables like POSTGRES_HOST, POSTGRES_PORT, POSTGRES_URL
        for each service.
        """
        for name, outputs in self.services.items():
            upper_name = name.upper().replace("-", "_")
            for key, value in outputs.items():
                if value is not None:
                    env_key = f"{upper_name}_{key.upper()}"
                    os.environ[env_key] = str(value)
                    self._environment_vars_set.append(env_key)

    def cleanup_env_vars(self) -> None:
        """Remove injected environment variables."""
        for key in self._environment_vars_set:
            os.environ.pop(key, None)
        self._environment_vars_set.clear()


# Global state for session-scoped provisioning
_session_context: Optional[BreakerAmpContext] = None
_session_services_required: Set[str] = set()


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers and configure plugin."""
    config.addinivalue_line(
        "markers",
        "requires_services(*services): mark test as requiring specific infrastructure services"
    )
    config.addinivalue_line(
        "markers",
        "breakeramp_scope(scope): set the provisioning scope for this test (function, class, module, session)"
    )


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add command line options for breakeramp."""
    group = parser.getgroup("breakeramp", "BreakerAmp infrastructure provisioning")
    group.addoption(
        "--breakeramp-blueprint",
        action="store",
        dest="breakeramp_blueprint",
        default=None,
        help="Blueprint ID to use for test infrastructure",
    )
    group.addoption(
        "--breakeramp-environment",
        action="store",
        dest="breakeramp_environment",
        default="development",
        help="Environment to use (default: development)",
    )
    group.addoption(
        "--breakeramp-auto-provision",
        action="store_true",
        dest="breakeramp_auto_provision",
        default=False,
        help="Automatically provision infrastructure for marked tests",
    )
    group.addoption(
        "--breakeramp-skip",
        action="store_true",
        dest="breakeramp_skip",
        default=False,
        help="Skip breakeramp provisioning (use existing infrastructure)",
    )
    group.addoption(
        "--breakeramp-keep",
        action="store_true",
        dest="breakeramp_keep",
        default=False,
        help="Keep infrastructure after tests complete (don't teardown)",
    )

    # Also read from ini file
    parser.addini(
        "breakeramp_blueprint",
        "Blueprint ID to use for test infrastructure",
        default=None,
    )
    parser.addini(
        "breakeramp_environment",
        "Environment to use",
        default="development",
    )
    parser.addini(
        "breakeramp_auto_provision",
        "Automatically provision infrastructure for marked tests",
        type="bool",
        default=False,
    )


def _get_config_value(config: pytest.Config, name: str, default: Any = None) -> Any:
    """Get configuration value from command line or ini file."""
    # Command line takes precedence
    cli_value = getattr(config.option, name, None)
    if cli_value is not None:
        return cli_value

    # Fall back to ini file
    ini_value = config.getini(name)
    if ini_value:
        return ini_value

    return default


def _collect_required_services(item: pytest.Item) -> Set[str]:
    """Collect required services from test markers."""
    services: Set[str] = set()

    for marker in item.iter_markers("requires_services"):
        services.update(marker.args)

    return services


def _provision_environment(
    config: pytest.Config,
    services: Set[str],
    test_paths: Optional[List[str]] = None,
) -> BreakerAmpContext:
    """Provision the environment with required services.

    Args:
        config: Pytest config object
        services: Set of required service names
        test_paths: Optional list of test file paths for analysis

    Returns:
        BreakerAmpContext with provisioned services
    """
    # Import here to avoid circular imports and allow standalone pytest usage
    try:
        from .models import PlanForTestsRequest
        from .service import BreakerAmpService
    except ImportError:
        warnings.warn(
            "BreakerAmp not fully installed. Install with: pip install breakeramp[pytest]"
        )
        return BreakerAmpContext()

    blueprint_id = _get_config_value(config, "breakeramp_blueprint")
    environment = _get_config_value(config, "breakeramp_environment", "development")

    if not blueprint_id:
        warnings.warn(
            "No breakeramp_blueprint configured. Set via --breakeramp-blueprint "
            "or in pytest.ini/pyproject.toml"
        )
        return BreakerAmpContext()

    # Create service and plan for tests
    service = BreakerAmpService()

    try:
        # Plan with explicit markers (services requested via @requires_services)
        plan_response = service.plan_for_tests(PlanForTestsRequest(
            test_paths=test_paths or [],
            blueprint_id=blueprint_id,
            environment=environment,
            markers=list(services),  # Use service names as markers
        ))

        # Apply the plan
        from .models import ApplyRequest
        apply_response = service.apply(ApplyRequest(
            plan_id=plan_response.plan_id,
        ))

        # Build context
        context = BreakerAmpContext(
            services=apply_response.environment_outputs,
            amp_run_id=plan_response.amp_run_id,
            plan_id=plan_response.plan_id,
            startup_order=plan_response.startup_order,
        )

        # Inject environment variables
        context.inject_env_vars()

        return context

    except Exception as e:
        warnings.warn(f"Failed to provision breakeramp environment: {e}")
        return BreakerAmpContext()


def _teardown_environment(context: BreakerAmpContext) -> None:
    """Teardown the provisioned environment."""
    if not context.amp_run_id:
        return

    try:
        from .models import DestroyRequest
        from .service import BreakerAmpService

        service = BreakerAmpService()
        service.destroy(DestroyRequest(
            amp_run_id=context.amp_run_id,
            reason="Pytest session completed",
            cleanup_after_destroy=True,
        ))
    except Exception as e:
        warnings.warn(f"Failed to teardown breakeramp environment: {e}")
    finally:
        context.cleanup_env_vars()


@pytest.fixture(scope="session")
def breakeramp_session(request: pytest.FixtureRequest) -> Generator[BreakerAmpContext, None, None]:
    """Session-scoped breakeramp fixture.

    Provisions infrastructure once for the entire test session.
    """
    global _session_context, _session_services_required

    config = request.config

    if config.option.breakeramp_skip:
        yield BreakerAmpContext()
        return

    # Collect all required services from all tests
    if hasattr(request.session, "items"):
        for item in request.session.items:
            _session_services_required.update(_collect_required_services(item))

    if not _session_services_required and not config.option.breakeramp_auto_provision:
        yield BreakerAmpContext()
        return

    # Provision
    _session_context = _provision_environment(
        config=config,
        services=_session_services_required,
    )

    yield _session_context

    # Teardown
    if not config.option.breakeramp_keep:
        _teardown_environment(_session_context)
        _session_context = None


@pytest.fixture(scope="module")
def breakeramp_module(request: pytest.FixtureRequest) -> Generator[BreakerAmpContext, None, None]:
    """Module-scoped breakeramp fixture.

    Provisions infrastructure for each test module.
    """
    config = request.config

    if config.option.breakeramp_skip:
        yield BreakerAmpContext()
        return

    # Collect services required by tests in this module
    services: Set[str] = set()
    module = request.module
    for name in dir(module):
        obj = getattr(module, name)
        if hasattr(obj, "pytestmark"):
            for marker in obj.pytestmark:
                if marker.name == "requires_services":
                    services.update(marker.args)

    if not services:
        yield BreakerAmpContext()
        return

    # Provision
    context = _provision_environment(
        config=config,
        services=services,
        test_paths=[str(request.fspath)],
    )

    yield context

    # Teardown
    if not config.option.breakeramp_keep:
        _teardown_environment(context)


@pytest.fixture
def breakeramp(request: pytest.FixtureRequest) -> Generator[BreakerAmpContext, None, None]:
    """Function-scoped breakeramp fixture (default).

    Provisions infrastructure for each test function. This is the recommended
    fixture for most use cases as it ensures clean state.

    For better performance with multiple tests, use breakeramp_module or
    breakeramp_session instead.

    Example:
        @pytest.mark.requires_services("postgres")
        def test_database(breakeramp):
            url = breakeramp.get_url("postgres")
            # test with database
    """
    config = request.config

    if config.option.breakeramp_skip:
        yield BreakerAmpContext()
        return

    # Collect services from this test's markers
    services = _collect_required_services(request.node)

    if not services:
        # No services required, yield empty context
        yield BreakerAmpContext()
        return

    # Check if we should use session context (if session fixture is active)
    global _session_context
    if _session_context and _session_context.is_provisioned():
        # Verify all required services are in session context
        if services.issubset(set(_session_context.services.keys())):
            yield _session_context
            return

    # Provision fresh for this test
    context = _provision_environment(
        config=config,
        services=services,
        test_paths=[str(request.fspath)],
    )

    yield context

    # Teardown
    if not config.option.breakeramp_keep:
        _teardown_environment(context)


# =========================================================================
# Skip Decorators
# =========================================================================

def skip_without_services(*services: str):
    """Skip test if required services cannot be provisioned.

    Example:
        @skip_without_services("postgres", "redis")
        def test_full_stack():
            ...
    """
    return pytest.mark.skipif(
        os.environ.get("BREAKERAMP_SKIP", "").lower() in ("1", "true", "yes"),
        reason=f"BreakerAmp services not available: {', '.join(services)}"
    )


def requires_services(*services: str):
    """Mark test as requiring specific services.

    This is a convenience wrapper around pytest.mark.requires_services.

    Example:
        @requires_services("postgres", "redis")
        def test_with_db_and_cache(breakeramp):
            ...
    """
    return pytest.mark.requires_services(*services)


# =========================================================================
# Hooks for Custom Behavior
# =========================================================================

def pytest_collection_modifyitems(
    session: pytest.Session,
    config: pytest.Config,
    items: List[pytest.Item],
) -> None:
    """Modify test collection to handle breakeramp markers."""
    global _session_services_required

    # Pre-collect all required services for session planning
    for item in items:
        _session_services_required.update(_collect_required_services(item))


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Setup hook to check service availability before test."""
    services = _collect_required_services(item)

    if not services:
        return

    # Check if breakeramp fixture is being used
    if "breakeramp" not in item.fixturenames and \
       "breakeramp_module" not in item.fixturenames and \
       "breakeramp_session" not in item.fixturenames:
        # Add warning that services are required but fixture not used
        warnings.warn(
            f"Test {item.name} has @requires_services marker but doesn't use "
            f"breakeramp fixture. Services may not be provisioned."
        )


# =========================================================================
# Entrypoint for direct pytest plugin registration
# =========================================================================

def get_plugin_modules() -> List[str]:
    """Return list of plugin modules for external registration.

    Note: Do NOT name this 'pytest_plugins' as that conflicts with pytest's
    internal variable-based plugin registration mechanism.
    """
    return []
