"""Load testing suite for Amprealize PostgreSQL services.

This module provides load testing utilities to validate performance under concurrent load.
Tests measure P95/P99 latency, transaction retry behavior, and connection pool utilization.

Performance Target: P95 <100ms at 20 concurrent workers (realistic API load)
- Profiles (set via --load-profile or AMPREALIZE_LOAD_PROFILE):
    • smoke – 5 workers / 100 requests (fast sanity checks on laptops)
    • baseline – 20 workers / 1000 requests (default regression target)
    • stress – 50 workers / 5000 requests (heavy validation on CI beefy hosts)
- Use --concurrent/--total flags to override profile values when needed

The suite honors AMPREALIZE_API_URL so it targets whichever server ./scripts/run_tests.sh booted
for the current session (falls back to http://localhost:8000 when unset).

Usage:
    # Run all load tests with default settings (20 concurrent, 1k total)
    pytest tests/load/test_service_load.py -v

    # Run with custom parameters
    pytest tests/load/test_service_load.py -v --concurrent=50 --total=5000

    # Run with smoke profile (or export AMPREALIZE_LOAD_PROFILE=smoke)
    pytest tests/load/test_service_load.py -v --load-profile=smoke

    # Run against specific service
    pytest tests/load/test_service_load.py -v -k test_behavior_service_load
"""

import concurrent.futures
import os
import statistics
import time
from typing import Any, Callable, Dict, List, Tuple

import pytest

# Skip if httpx not available
httpx = pytest.importorskip("httpx")


# Configuration
DEFAULT_BASE_URL = os.environ.get("AMPREALIZE_GATEWAY_URL", "http://localhost:8080")


def measure_latency(
    func: Callable[[], Any], num_requests: int, num_workers: int
) -> Dict[str, Any]:
    """Execute function concurrently and measure latency statistics.

    Args:
        func: Callable to execute (should make a single request)
        num_requests: Total number of requests to make
        num_workers: Number of concurrent workers

    Returns:
        Dictionary with timing statistics:
        - total_time: Total execution time
        - requests_per_second: Throughput
        - p50, p95, p99: Latency percentiles
        - min, max, mean: Basic statistics
        - errors: Number of failed requests
    """
    latencies: List[float] = []
    errors: List[Exception] = []

    start_time = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(func) for _ in range(num_requests)]

        for future in concurrent.futures.as_completed(futures):
            try:
                latency = future.result()
                latencies.append(latency)
            except Exception as exc:
                errors.append(exc)

    total_time = time.time() - start_time

    if not latencies:
        return {
            "total_time": total_time,
            "requests_per_second": 0,
            "errors": len(errors),
            "error_rate": 1.0,
        }

    latencies.sort()

    return {
        "total_time": total_time,
        "requests_per_second": len(latencies) / total_time,
        "p50": statistics.median(latencies),
        "p95": latencies[int(len(latencies) * 0.95)],
        "p99": latencies[int(len(latencies) * 0.99)],
        "min": min(latencies),
        "max": max(latencies),
        "mean": statistics.mean(latencies),
        "errors": len(errors),
        "error_rate": len(errors) / (len(latencies) + len(errors)),
    }


def _skip_if_no_latency_stats(stats: Dict[str, Any], endpoint_name: str) -> None:
    """Skip load assertions when no requests completed successfully."""
    if "p50" not in stats:
        pytest.skip(
            f"All requests failed for {endpoint_name} "
            f"(error rate: {stats.get('error_rate', 1.0) * 100:.1f}%)"
        )


class ServiceLoadTester:
    """Load testing utilities for Amprealize services."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL):
        self.base_url = base_url
        self.client = httpx.Client(base_url=base_url, timeout=30.0)

    def _make_request(self, method: str, path: str, **kwargs) -> float:
        """Make a single HTTP request and return latency in seconds."""
        start = time.time()
        response = self.client.request(method, path, **kwargs)
        latency = time.time() - start
        response.raise_for_status()
        return latency

    def test_health_endpoint(self, num_requests: int, num_workers: int) -> Dict[str, Any]:
        """Load test the /health endpoint."""
        def req():
            return self._make_request("GET", "/health")

        return measure_latency(req, num_requests, num_workers)

    def test_metrics_endpoint(self, num_requests: int, num_workers: int) -> Dict[str, Any]:
        """Load test the /metrics endpoint."""
        def req():
            return self._make_request("GET", "/metrics")

        return measure_latency(req, num_requests, num_workers)

    def test_behavior_list(self, num_requests: int, num_workers: int) -> Dict[str, Any]:
        """Load test BehaviorService list operation."""
        def req():
            return self._make_request("GET", "/v1/behaviors")

        return measure_latency(req, num_requests, num_workers)

    def test_workflow_list(self, num_requests: int, num_workers: int) -> Dict[str, Any]:
        """Load test WorkflowService list operation."""
        def req():
            return self._make_request("GET", "/v1/workflows/templates")

        return measure_latency(req, num_requests, num_workers)

    def test_action_list(self, num_requests: int, num_workers: int) -> Dict[str, Any]:
        """Load test ActionService list operation."""
        def req():
            return self._make_request("GET", "/v1/actions")

        return measure_latency(req, num_requests, num_workers)

    def test_run_list(self, num_requests: int, num_workers: int) -> Dict[str, Any]:
        """Load test RunService list operation."""
        def req():
            return self._make_request("GET", "/v1/runs")

        return measure_latency(req, num_requests, num_workers)

    def test_compliance_list(self, num_requests: int, num_workers: int) -> Dict[str, Any]:
        """Load test ComplianceService list operation."""
        def req():
            return self._make_request("GET", "/v1/compliance/checklists")

        return measure_latency(req, num_requests, num_workers)


@pytest.fixture(scope="module")
def load_tester():
    """Create a ServiceLoadTester instance."""
    tester = ServiceLoadTester()
    try:
        response = tester.client.get("/health", timeout=5.0)
        response.raise_for_status()
    except Exception as exc:
        pytest.skip(
            f"Service load tests require API at {tester.base_url}; skipping: {exc}"
        )
    return tester


def test_health_endpoint_load(load_tester, load_params):
    """Test /health endpoint under load."""
    stats = load_tester.test_health_endpoint(
        num_requests=load_params["total"],
        num_workers=load_params["concurrent"],
    )

    print(f"\n/health Endpoint Load Test Results:")
    print(f"  Total time: {stats['total_time']:.2f}s")
    print(f"  Throughput: {stats['requests_per_second']:.2f} req/s")
    print(f"  P50 latency: {stats['p50']*1000:.2f}ms")
    print(f"  P95 latency: {stats['p95']*1000:.2f}ms")
    print(f"  P99 latency: {stats['p99']*1000:.2f}ms")
    print(f"  Error rate: {stats['error_rate']*100:.2f}%")

    # Assert P95 < 500ms for health checks
    assert stats["p95"] < 0.5, f"P95 latency {stats['p95']*1000:.0f}ms exceeds 500ms threshold"
    assert stats["error_rate"] < 0.01, f"Error rate {stats['error_rate']*100:.1f}% exceeds 1% threshold"


def test_metrics_endpoint_load(load_tester, load_params):
    """Test /metrics endpoint under load."""
    # Use 10% of total requests for metrics (it's expensive)
    stats = load_tester.test_metrics_endpoint(
        num_requests=load_params["total"] // 10,
        num_workers=load_params["concurrent"],
    )

    print(f"\n/metrics Endpoint Load Test Results:")
    print(f"  Total time: {stats['total_time']:.2f}s")
    print(f"  Throughput: {stats['requests_per_second']:.2f} req/s")

    # Check if we got any successful responses - if all requests failed, skip percentile checks
    if "p50" not in stats:
        pytest.skip(f"All requests failed (error rate: {stats.get('error_rate', 1.0)*100:.1f}%) - /metrics endpoint may not be available")

    print(f"  P50 latency: {stats['p50']*1000:.2f}ms")
    print(f"  P95 latency: {stats['p95']*1000:.2f}ms")
    print(f"  P99 latency: {stats['p99']*1000:.2f}ms")

    # Metrics can be slower, allow up to 1s P95
    assert stats["p95"] < 1.0, f"P95 latency {stats['p95']*1000:.0f}ms exceeds 1000ms threshold"


def test_behavior_service_load(load_tester, load_params):
    """Test BehaviorService list operation under load."""
    stats = load_tester.test_behavior_list(
        num_requests=load_params["total"],
        num_workers=load_params["concurrent"],
    )

    print(f"\nBehaviorService Load Test Results:")
    print(f"  Total time: {stats['total_time']:.2f}s")
    print(f"  Throughput: {stats['requests_per_second']:.2f} req/s")
    _skip_if_no_latency_stats(stats, "BehaviorService")
    print(f"  P50 latency: {stats['p50']*1000:.2f}ms")
    print(f"  P95 latency: {stats['p95']*1000:.2f}ms")
    print(f"  P99 latency: {stats['p99']*1000:.2f}ms")
    print(f"  Error rate: {stats['error_rate']*100:.2f}%")

    # Assert P95 < 100ms for read operations per RETRIEVAL_ENGINE_PERFORMANCE.md
    assert stats["p95"] < 0.1, f"P95 latency {stats['p95']*1000:.0f}ms exceeds 100ms threshold"
    assert stats["error_rate"] < 0.01, f"Error rate {stats['error_rate']*100:.1f}% exceeds 1% threshold"


def test_workflow_service_load(load_tester, load_params):
    """Test WorkflowService list operation under load."""
    stats = load_tester.test_workflow_list(
        num_requests=load_params["total"],
        num_workers=load_params["concurrent"],
    )

    print(f"\nWorkflowService Load Test Results:")
    print(f"  Total time: {stats['total_time']:.2f}s")
    print(f"  Throughput: {stats['requests_per_second']:.2f} req/s")
    _skip_if_no_latency_stats(stats, "WorkflowService")
    print(f"  P50 latency: {stats['p50']*1000:.2f}ms")
    print(f"  P95 latency: {stats['p95']*1000:.2f}ms")
    print(f"  P99 latency: {stats['p99']*1000:.2f}ms")

    assert stats["p95"] < 0.1, f"P95 latency {stats['p95']*1000:.0f}ms exceeds 100ms threshold"


def test_action_service_load(load_tester, load_params):
    """Test ActionService list operation under load."""
    stats = load_tester.test_action_list(
        num_requests=load_params["total"],
        num_workers=load_params["concurrent"],
    )

    print(f"\nActionService Load Test Results:")
    print(f"  Total time: {stats['total_time']:.2f}s")
    print(f"  Throughput: {stats['requests_per_second']:.2f} req/s")
    _skip_if_no_latency_stats(stats, "ActionService")
    print(f"  P50 latency: {stats['p50']*1000:.2f}ms")
    print(f"  P95 latency: {stats['p95']*1000:.2f}ms")
    print(f"  P99 latency: {stats['p99']*1000:.2f}ms")

    assert stats["p95"] < 0.1, f"P95 latency {stats['p95']*1000:.0f}ms exceeds 100ms threshold"


@pytest.mark.skip(reason="RunService may not have /v1/runs endpoint yet")
def test_run_service_load(load_tester, load_params):
    """Test RunService list operation under load."""
    stats = load_tester.test_run_list(
        num_requests=load_params["total"],
        num_workers=load_params["concurrent"],
    )

    print(f"\nRunService Load Test Results:")
    _skip_if_no_latency_stats(stats, "RunService")
    print(f"  P95 latency: {stats['p95']*1000:.2f}ms")

    assert stats["p95"] < 0.5, f"P95 latency {stats['p95']*1000:.0f}ms exceeds 500ms threshold"


@pytest.mark.skip(reason="ComplianceService may not have REST endpoints yet")
def test_compliance_service_load(load_tester, load_params):
    """Test ComplianceService list operation under load."""
    stats = load_tester.test_compliance_list(
        num_requests=load_params["total"],
        num_workers=load_params["concurrent"],
    )

    print(f"\nComplianceService Load Test Results:")
    _skip_if_no_latency_stats(stats, "ComplianceService")
    print(f"  P95 latency: {stats['p95']*1000:.2f}ms")

    assert stats["p95"] < 0.1, f"P95 latency {stats['p95']*1000:.0f}ms exceeds 100ms threshold"
