"""Pytest configuration for Midnighter tests."""

import os
from pathlib import Path

import pytest

# Load .env file early so environment variables are available at collection time
# This is needed for skipif markers that check for OPENAI_API_KEY
try:
    from dotenv import load_dotenv
    amprealize_root = Path(__file__).resolve().parents[3]
    env_path = amprealize_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register custom CLI flags."""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Execute integration tests that require live OpenAI API.",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Configure custom markers."""
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests (require --run-integration)"
    )
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (may incur API costs)"
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list) -> None:
    """Skip integration tests unless --run-integration is passed."""
    if config.getoption("--run-integration"):
        # .env already loaded at module level
        return

    skip_integration = pytest.mark.skip(reason="need --run-integration option to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)


@pytest.fixture(autouse=True)
def reset_environment(monkeypatch, request):
    """Reset environment for each test.

    Integration tests bypass this to use real backends.
    """
    # Don't force simulation backend for integration tests
    if "integration" in request.keywords:
        return

    # Ensure we use simulation backend in unit tests
    monkeypatch.setenv("MDNT_BACKEND", "simulation")
    monkeypatch.setenv("MDNT_USE_LLM_EXAMPLES", "false")
