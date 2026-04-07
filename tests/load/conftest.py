"""Pytest configuration for load tests."""

import os
import socket
from typing import Dict, Optional

import pytest

try:
    from tests.conftest import safe_truncate  # noqa: F401
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Kafka Availability Check
# ---------------------------------------------------------------------------

def _check_kafka_available(bootstrap_servers: str = None, timeout: float = 2.0) -> bool:
    """
    Check if Kafka is reachable by attempting a socket connection.

    Args:
        bootstrap_servers: Kafka bootstrap servers (default: env var or localhost:10092)
        timeout: Connection timeout in seconds

    Returns:
        True if Kafka is reachable, False otherwise
    """
    servers = bootstrap_servers or os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:10092")
    # Parse first broker from comma-separated list
    first_broker = servers.split(",")[0].strip()
    try:
        host, port = first_broker.rsplit(":", 1)
        port = int(port)
    except ValueError:
        return False

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except (socket.error, OSError):
        return False


# Cache the result to avoid repeated checks
_kafka_available_cache: Optional[bool] = None


def is_kafka_available() -> bool:
    """Check Kafka availability with caching for performance."""
    global _kafka_available_cache
    if _kafka_available_cache is None:
        _kafka_available_cache = _check_kafka_available()
    return _kafka_available_cache


# Pytest skip marker for Kafka-dependent tests
requires_kafka = pytest.mark.skipif(
    not is_kafka_available(),
    reason="Kafka not available - set KAFKA_BOOTSTRAP_SERVERS or start Kafka to enable"
)


@pytest.fixture(scope="session")
def kafka_available() -> bool:
    """
    Session-scoped fixture indicating if Kafka is available.

    Use this fixture to conditionally skip tests or adjust behavior
    when Kafka is not running.
    """
    return is_kafka_available()


# ---------------------------------------------------------------------------
# Load Profile Presets
# ---------------------------------------------------------------------------

PROFILE_PRESETS: Dict[str, Dict[str, int]] = {
    # Lightweight mode for constrained laptops (≈15s runtime)
    "smoke": {"concurrent": 5, "total": 100},
    # Default regression profile aligned with PRD targets
    "baseline": {"concurrent": 20, "total": 1000},
    # High-pressure mode for CI or beefy machines
    "stress": {"concurrent": 50, "total": 5000},
}

DEFAULT_PROFILE = "baseline"
ENV_PROFILE_VAR = "AMPREALIZE_LOAD_PROFILE"


def pytest_addoption(parser):
    """Add custom command line options for load testing presets."""
    parser.addoption(
        "--load-profile",
        action="store",
        choices=sorted(PROFILE_PRESETS.keys()),
        default=None,
        help=(
            "Load profile preset (overrides defaults). Also configurable via "
            f"{ENV_PROFILE_VAR} environment variable."
        ),
    )
    parser.addoption(
        "--concurrent",
        action="store",
        type=int,
        default=None,
        help="Number of concurrent workers (overrides load profile)",
    )
    parser.addoption(
        "--total",
        action="store",
        type=int,
        default=None,
        help="Total number of requests (overrides load profile)",
    )


def _resolve_profile(cli_profile: Optional[str]) -> str:
    profile = cli_profile or os.environ.get(ENV_PROFILE_VAR) or DEFAULT_PROFILE
    profile = profile.lower()
    if profile not in PROFILE_PRESETS:
        valid = ", ".join(sorted(PROFILE_PRESETS.keys()))
        raise pytest.UsageError(
            f"Unknown load profile '{profile}'. Valid profiles: {valid}."
        )
    return profile


@pytest.fixture
def load_profile(request) -> str:
    """Determine the active load profile (CLI > env > default)."""
    cli_value = request.config.getoption("--load-profile")
    return _resolve_profile(cli_value)


@pytest.fixture
def concurrent_workers(request, load_profile: str):
    """Get concurrent workers count derived from profile or CLI override."""
    cli_value = request.config.getoption("--concurrent")
    if cli_value is not None:
        return int(cli_value)
    return PROFILE_PRESETS[load_profile]["concurrent"]


@pytest.fixture
def total_requests(request, load_profile: str):
    """Get total request count derived from profile or CLI override."""
    cli_value = request.config.getoption("--total")
    if cli_value is not None:
        return int(cli_value)
    return PROFILE_PRESETS[load_profile]["total"]


@pytest.fixture
def load_params(concurrent_workers: int, total_requests: int, load_profile: str):
    """Bundle resolved load parameters for reuse in test modules."""
    return {
        "concurrent": int(concurrent_workers),
        "total": int(total_requests),
        "profile": load_profile,
    }
