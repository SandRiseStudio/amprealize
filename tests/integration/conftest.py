"""
Conftest for integration tests - overrides global fixtures.

Integration tests connect to staging environment and should NOT
start local test infrastructure (PostgreSQL, Redis, etc.).
"""

import pytest

try:
    from tests.conftest import safe_truncate  # noqa: F401
except ImportError:
    pass


# Override the check_test_environment fixture from tests/conftest.py
# to prevent infrastructure validation for integration tests
@pytest.fixture(scope="session", autouse=True)
def check_test_environment(request):
    """
    Override global conftest fixture that checks test infrastructure.

    Integration tests use staging environment (running Podman containers),
    not local test containers. This prevents pytest.exit() when test DBs
    are not available.
    """
    # Skip all infrastructure checks for integration tests
    return
