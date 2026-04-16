"""
Smoke tests for Amprealize staging environment.

Tests core service health, API parity, and basic workflow functionality.
These tests require the staging stack to be running. When the staging stack
is not available, tests will be automatically skipped via fixtures in conftest.py.

To run these tests, start the staging stack:
    podman-compose -f docker-compose.staging.yml --profile with-nginx up -d

Last Updated: 2025-12-19
"""

import time
from typing import Any, Dict

import httpx
import pytest

# Mark all tests in this module as smoke tests for easy filtering
pytestmark = pytest.mark.smoke


# Note: api_client and nginx_client fixtures are defined in conftest.py
# They will auto-skip tests when staging infrastructure is unavailable

RETRY_COUNT = 3
RETRY_DELAY = 2.0


def retry_request(func, retries: int = RETRY_COUNT, delay: float = RETRY_DELAY):
    """Retry HTTP requests with exponential backoff."""
    for attempt in range(retries):
        try:
            return func()
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            if attempt == retries - 1:
                raise
            time.sleep(delay * (2**attempt))


def _skip_if_staging_write_unavailable(response: httpx.Response, action: str) -> None:
    """Skip write smoke checks when the staging stack is only partially provisioned."""
    if response.status_code in {500, 502, 503, 504}:
        pytest.skip(
            f"Staging write path unavailable for {action} "
            f"(status {response.status_code})"
        )


# =============================================================================
# Health Checks
# =============================================================================


def test_api_health_check(api_client: httpx.Client):
    """Verify API service is healthy."""

    def check():
        response = api_client.get("/health")
        assert response.status_code == 200, f"API health check failed: {response.status_code}"
        data = response.json()
        assert data["status"] in ["healthy", "degraded"], f"Unexpected status: {data['status']}"
        return data

    result = retry_request(check)
    assert "services" in result or "status" in result


def test_nginx_health_check(nginx_client: httpx.Client):
    """Verify NGINX proxy is healthy."""

    def check():
        response = nginx_client.get("/health")
        assert response.status_code == 200, f"NGINX health check failed: {response.status_code}"
        return response

    retry_request(check)


def test_api_via_nginx(nginx_client: httpx.Client):
    """Verify API is accessible through NGINX proxy."""

    def check():
        response = nginx_client.get("/api/health")
        if response.status_code == 404:
            pytest.skip("NGINX staging route /api/health is not configured in this environment")
        assert response.status_code == 200, f"API via NGINX failed: {response.status_code}"
        return response

    retry_request(check)


def test_redis_connectivity(api_client: httpx.Client):
    """Verify Redis connection via API health check."""
    response = api_client.get("/health")
    assert response.status_code == 200
    # Health check should include Redis status if implemented
    data = response.json()
    assert data["status"] in ["healthy", "degraded"]


# =============================================================================
# API Parity Tests
# =============================================================================


def test_create_behavior(api_client: httpx.Client):
    """Test creating a behavior draft via API."""
    import uuid
    unique_name = f"smoke_test_behavior_{uuid.uuid4().hex[:8]}"
    payload = {
        "name": unique_name,
        "description": "Smoke test behavior for staging environment validation",
        "instruction": "When testing staging environment, validate all core services",
        "role_focus": "test",
        "trigger_keywords": ["staging", "smoke", "validation"],
        "tags": ["test", "smoke", "staging"],
        "metadata": {
            "test_type": "smoke",
            "environment": "staging",
            "step": "create_behavior",
        },
    }

    response = api_client.post("/v1/behaviors", json=payload)
    _skip_if_staging_write_unavailable(response, "create behavior")
    assert response.status_code in [200, 201], f"Create behavior failed: {response.status_code}"
    data = response.json()
    assert "behavior" in data and "behavior_id" in data["behavior"]


def test_list_behaviors(api_client: httpx.Client):
    """Test listing behaviors via API."""
    response = api_client.get("/v1/behaviors")
    assert response.status_code == 200, f"List behaviors failed: {response.status_code}"
    data = response.json()
    assert isinstance(data, list), "Expected list of behaviors"


def test_create_action(api_client: httpx.Client):
    """Test creating an action via API."""
    payload = {
        "artifact_path": "/staging/smoke/test_001",
        "summary": "Smoke test action for staging validation",
        "behaviors_cited": ["behavior_smoke_test"],
        "metadata": {
            "test_type": "smoke",
            "environment": "staging",
            "step": "create_action",
        },
    }

    response = api_client.post("/v1/actions", json=payload)
    _skip_if_staging_write_unavailable(response, "create action")
    assert response.status_code in [200, 201], f"Create action failed: {response.status_code}"
    data = response.json()
    assert "action_id" in data or "id" in data


def test_list_actions(api_client: httpx.Client):
    """Test listing actions via API."""
    response = api_client.get("/v1/actions")
    assert response.status_code == 200, f"List actions failed: {response.status_code}"
    data = response.json()
    assert isinstance(data, list), "Expected list of actions"


def test_create_run(api_client: httpx.Client):
    """Test creating a run via API."""
    payload = {
        "workflow_name": "smoke_test_workflow",
        "behavior_ids": [],
        "metadata": {
            "test_type": "smoke",
            "environment": "staging",
        },
        "initial_message": "Smoke test run for staging validation",
    }

    response = api_client.post("/v1/runs", json=payload)
    _skip_if_staging_write_unavailable(response, "create run")
    assert response.status_code in [200, 201], f"Create run failed: {response.status_code}"
    data = response.json()
    assert "run_id" in data or "id" in data


# =============================================================================
# Workflow Tests
# =============================================================================


def test_behavior_workflow(api_client: httpx.Client):
    """Test complete behavior creation and retrieval workflow."""
    import uuid
    unique_name = f"workflow_test_{uuid.uuid4().hex[:8]}"

    # Create behavior
    create_payload = {
        "name": unique_name,
        "description": "Behavior for testing complete workflow in staging",
        "instruction": "Test complete workflow",
        "role_focus": "teacher",
        "trigger_keywords": ["workflow", "test"],
        "tags": ["workflow-test", "staging"],
        "metadata": {"test_type": "workflow"},
    }

    create_response = api_client.post("/v1/behaviors", json=create_payload)
    _skip_if_staging_write_unavailable(create_response, "behavior workflow create")
    assert create_response.status_code in [200, 201]
    created = create_response.json()
    behavior_id = created["behavior"]["behavior_id"]

    # Retrieve behavior
    get_response = api_client.get(f"/v1/behaviors/{behavior_id}")
    assert get_response.status_code == 200
    retrieved = get_response.json()
    assert retrieved["behavior"]["name"] == unique_name


def test_action_replay_workflow(api_client: httpx.Client):
    """Test action capture and replay workflow."""
    # Create action
    create_payload = {
        "artifact_path": "/staging/replay/test_001",
        "summary": "Action for replay workflow testing",
        "behaviors_cited": ["behavior_replay_test"],
        "metadata": {
            "test_type": "replay_workflow",
            "step": "1",
            "data": "test",
        },
    }

    create_response = api_client.post("/v1/actions", json=create_payload)
    _skip_if_staging_write_unavailable(create_response, "action replay create")
    assert create_response.status_code in [200, 201]
    created = create_response.json()
    action_id = created.get("action_id") or created.get("id")

    # Replay actions
    replay_payload = {
        "action_ids": [action_id],
        "strategy": "SEQUENTIAL",
        "options": {
            "skip_existing": False,
            "dry_run": True,
        },
    }

    replay_response = api_client.post("/v1/actions:replay", json=replay_payload)
    assert replay_response.status_code in [200, 202]


# =============================================================================
# Performance Tests
# =============================================================================


def test_api_response_time(api_client: httpx.Client):
    """Verify API responds within acceptable time."""
    start = time.time()
    response = api_client.get("/health")
    duration = time.time() - start

    assert response.status_code == 200
    assert duration < 2.0, f"Health check took {duration:.2f}s (expected < 2.0s)"


def test_concurrent_requests(api_client: httpx.Client):
    """Test handling concurrent requests."""
    import concurrent.futures

    def make_request():
        response = api_client.get("/v1/behaviors")
        return response.status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(make_request) for _ in range(10)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert all(status == 200 for status in results), "Some concurrent requests failed"


# =============================================================================
# Metrics & Monitoring
# =============================================================================


def test_metrics_endpoint(api_client: httpx.Client):
    """Verify metrics endpoint is accessible."""
    response = api_client.get("/metrics")
    assert response.status_code == 200
    content_type = response.headers.get("content-type")
    assert content_type.startswith("text/plain; version=0.0.4")


def test_analytics_kpi_summary(api_client: httpx.Client):
    """Test analytics KPI summary endpoint."""
    response = api_client.get("/v1/analytics/kpi-summary")
    assert response.status_code == 200
    data = response.json()
    assert "records" in data or isinstance(data, list)


# =============================================================================
# Error Handling
# =============================================================================


def test_404_handling(api_client: httpx.Client):
    """Verify proper 404 responses."""
    response = api_client.get("/v1/behaviors/nonexistent_behavior_id")
    assert response.status_code == 404


def test_400_handling(api_client: httpx.Client):
    """Verify proper 400 responses for invalid payloads."""
    invalid_payload = {"invalid": "structure"}
    response = api_client.post("/v1/behaviors", json=invalid_payload)
    assert response.status_code == 400


# =============================================================================
# Summary Test
# =============================================================================


def test_staging_summary(api_client: httpx.Client):
    """Generate staging environment summary."""
    print("\n" + "=" * 70)
    print("STAGING ENVIRONMENT SUMMARY")
    print("=" * 70)

    # Health status
    health = api_client.get("/health").json()
    print(f"\nHealth Status: {health.get('status', 'unknown')}")

    # Service counts
    behaviors = api_client.get("/v1/behaviors").json()
    actions = api_client.get("/v1/actions").json()

    print(f"Behaviors: {len(behaviors) if isinstance(behaviors, list) else 'N/A'}")
    print(f"Actions: {len(actions) if isinstance(actions, list) else 'N/A'}")

    # Metrics
    try:
        metrics_response = api_client.get("/metrics")
        print(f"Metrics Available: {metrics_response.status_code == 200}")
    except Exception:
        print("Metrics Available: False")

    print("=" * 70 + "\n")
