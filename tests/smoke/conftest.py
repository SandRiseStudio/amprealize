"""Pytest configuration for smoke tests.

Provides fixtures that check staging infrastructure availability and skip tests
appropriately when staging services aren't running.

Behaviors: behavior_align_storage_layers, behavior_unify_execution_records
"""

from __future__ import annotations

import os
import socket
import time
from typing import Generator

import pytest
import httpx

try:
    from tests.conftest import safe_truncate  # noqa: F401
except ImportError:
    pass


# Staging configuration from environment or defaults
STAGING_API_BASE = os.getenv("STAGING_API_URL", "http://localhost:8000")
STAGING_NGINX_BASE = os.getenv("STAGING_NGINX_URL", "http://localhost:8080")
CONNECTION_TIMEOUT = 5.0


def _extract_host_port(url: str) -> tuple[str, int]:
    """Extract host and port from a URL."""
    # Remove scheme
    if "://" in url:
        url = url.split("://", 1)[1]
    # Remove path
    if "/" in url:
        url = url.split("/", 1)[0]
    # Split host:port
    if ":" in url:
        host, port_str = url.rsplit(":", 1)
        return host, int(port_str)
    return url, 80


def _check_port_available(host: str, port: int, timeout: float = CONNECTION_TIMEOUT) -> bool:
    """Check if a TCP port is reachable."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _check_http_health(base_url: str, path: str = "/health") -> bool:
    """Check if an HTTP endpoint is responding and healthy."""
    try:
        with httpx.Client(base_url=base_url, timeout=CONNECTION_TIMEOUT) as client:
            response = client.get(path)
            # Only consider it available if truly healthy (not 500 or degraded)
            if response.status_code != 200:
                return False
            # Check if health response indicates actual readiness
            try:
                data = response.json()
                status = data.get("status", "").lower()
                # Only "healthy" means services are ready; "degraded" or missing = not ready
                return status == "healthy"
            except Exception:
                # Non-JSON health response - just check status code
                return response.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException, OSError):
        return False


def _is_staging_api_available() -> bool:
    """Check if staging API is reachable and functioning."""
    host, port = _extract_host_port(STAGING_API_BASE)
    if not _check_port_available(host, port):
        return False
    if not _check_http_health(STAGING_API_BASE, "/health"):
        return False
    # Also verify a core endpoint doesn't return 500
    try:
        with httpx.Client(base_url=STAGING_API_BASE, timeout=CONNECTION_TIMEOUT) as client:
            response = client.get("/v1/behaviors")
            # If we get a 500, staging services aren't ready
            return response.status_code != 500
    except (httpx.ConnectError, httpx.TimeoutException, OSError):
        return False


def _is_staging_nginx_available() -> bool:
    """Check if staging NGINX is reachable."""
    host, port = _extract_host_port(STAGING_NGINX_BASE)
    if not _check_port_available(host, port):
        return False
    return _check_http_health(STAGING_NGINX_BASE, "/health")


@pytest.fixture(scope="session")
def staging_api_available() -> bool:
    """Check if staging API is available (session-scoped for performance)."""
    return _is_staging_api_available()


@pytest.fixture(scope="session")
def staging_nginx_available() -> bool:
    """Check if staging NGINX is available (session-scoped for performance)."""
    return _is_staging_nginx_available()


@pytest.fixture
def require_staging_api(staging_api_available: bool):
    """Skip test if staging API is not available."""
    if not staging_api_available:
        pytest.skip(
            f"Staging API not available at {STAGING_API_BASE}. "
            f"Start staging stack with: podman-compose -f docker-compose.staging.yml up -d"
        )


@pytest.fixture
def require_staging_nginx(staging_nginx_available: bool):
    """Skip test if staging NGINX is not available."""
    if not staging_nginx_available:
        pytest.skip(
            f"Staging NGINX not available at {STAGING_NGINX_BASE}. "
            f"Start staging stack with: podman-compose -f docker-compose.staging.yml --profile with-nginx up -d"
        )


@pytest.fixture
def require_staging_stack(staging_api_available: bool, staging_nginx_available: bool):
    """Skip test if full staging stack is not available."""
    if not staging_api_available:
        pytest.skip(
            f"Staging API not available at {STAGING_API_BASE}. "
            f"Start staging stack with: podman-compose -f docker-compose.staging.yml up -d"
        )
    if not staging_nginx_available:
        pytest.skip(
            f"Staging NGINX not available at {STAGING_NGINX_BASE}. "
            f"Start staging stack with: podman-compose -f docker-compose.staging.yml --profile with-nginx up -d"
        )


# Override the default api_client and nginx_client fixtures to auto-skip when unavailable
@pytest.fixture
def api_client(staging_api_available: bool) -> Generator[httpx.Client, None, None]:
    """Create HTTP client for staging API, skipping if unavailable."""
    if not staging_api_available:
        pytest.skip(
            f"Staging API not available at {STAGING_API_BASE}. "
            f"Start staging stack with: podman-compose -f docker-compose.staging.yml up -d"
        )

    client = httpx.Client(base_url=STAGING_API_BASE, timeout=30.0)
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def nginx_client(staging_nginx_available: bool) -> Generator[httpx.Client, None, None]:
    """Create HTTP client for NGINX proxy, skipping if unavailable."""
    if not staging_nginx_available:
        pytest.skip(
            f"Staging NGINX not available at {STAGING_NGINX_BASE}. "
            f"Start staging stack with: podman-compose -f docker-compose.staging.yml --profile with-nginx up -d"
        )

    client = httpx.Client(base_url=STAGING_NGINX_BASE, timeout=30.0)
    try:
        yield client
    finally:
        client.close()
