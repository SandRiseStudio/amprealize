"""Conftest for billing unit tests - no infrastructure required.

Billing tests use MockBillingProvider which is fully in-memory.
No PostgreSQL or Redis required.
"""

import pytest

try:
    from tests.conftest import safe_truncate  # noqa: F401
except ImportError:
    pass


def pytest_configure(config):
    """Skip all infrastructure setup for billing tests.

    Billing tests use MockBillingProvider which is fully in-memory.
    """
    # Mark this subdirectory as requiring no infrastructure
    config._billing_tests = True


@pytest.fixture(scope="session", autouse=True)
def check_test_environment(request):
    """No infrastructure required for billing tests - override parent conftest.

    This fixture name matches the parent conftest's infrastructure check fixture,
    which ensures we override it for billing tests.
    """
    yield  # No infrastructure checks needed


# Override any other infrastructure-dependent fixtures from parent conftest
@pytest.fixture(scope="session")
def postgres_dsn_behavior():
    """Mock PostgreSQL DSN - not needed for billing tests."""
    pytest.skip("Billing tests don't require PostgreSQL")


@pytest.fixture(scope="session")
def postgres_dsn_workflow():
    """Mock PostgreSQL DSN - not needed for billing tests."""
    pytest.skip("Billing tests don't require PostgreSQL")


@pytest.fixture(scope="session")
def postgres_dsn_action():
    """Mock PostgreSQL DSN - not needed for billing tests."""
    pytest.skip("Billing tests don't require PostgreSQL")
