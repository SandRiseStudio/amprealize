#!/usr/bin/env python3
"""
Lightweight load test for MacBook Air - Phase 2 Task 7 validation
Sends 20 sequential requests (not concurrent) to avoid memory pressure
Measures P95 latency and validates SLO targets

Behaviors: behavior_instrument_metrics_pipeline
"""

import requests
import time
import sys
import statistics

def run_lightweight_load_test(base_url="http://localhost:8080", num_requests=20):
    """Run lightweight sequential load test"""

    print("=" * 60)
    print("Lightweight Load Test - MacBook Air Friendly")
    print("=" * 60)
    print(f"Target: {base_url}")
    print(f"Requests: {num_requests} (sequential, not concurrent)")
    print(f"SLO Target: P95 <250ms")
    print()

    endpoint = f"{base_url}/v1/bci/retrieve"
    latencies = []
    errors = 0

    # Test queries covering different behavior types
    test_queries = [
        "OAuth2 device flow authentication",
        "PostgreSQL connection pooling",
        "Prometheus metrics instrumentation",
        "Behavior handbook compliance",
        "Storage layer alignment",
        "Security surface hardening",
        "Git governance workflow",
        "CI/CD pipeline orchestration",
        "Documentation synchronization",
        "Action registry sanitization",
    ]

    print("Running requests...")
    for i in range(num_requests):
        query = test_queries[i % len(test_queries)]
        payload = {
            "query": query,
            "top_k": 5,
            "user_id": f"loadtest_user_{i}"
        }

        try:
            start = time.time()
            response = requests.post(endpoint, json=payload, timeout=5)
            latency_ms = (time.time() - start) * 1000

            if response.status_code == 200:
                latencies.append(latency_ms)
                status = "✓" if latency_ms < 250 else "⚠"
                print(f"  [{i+1:2d}/{num_requests}] {status} {latency_ms:6.1f}ms - {query[:40]}")
            else:
                errors += 1
                print(f"  [{i+1:2d}/{num_requests}] ✗ HTTP {response.status_code}")

        except Exception as e:
            errors += 1
            print(f"  [{i+1:2d}/{num_requests}] ✗ Error: {e}")

        # Small delay to avoid overwhelming the system
        time.sleep(0.1)

    print()
    print("=" * 60)
    print("Results")
    print("=" * 60)

    if not latencies:
        print("✗ All requests failed - cannot validate SLOs")
        return False

    # Calculate percentiles
    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    p95_idx = int(len(latencies) * 0.95)
    p95 = latencies[p95_idx] if p95_idx < len(latencies) else latencies[-1]
    p99_idx = int(len(latencies) * 0.99)
    p99 = latencies[p99_idx] if p99_idx < len(latencies) else latencies[-1]
    avg = statistics.mean(latencies)

    print(f"Successful requests: {len(latencies)}/{num_requests} ({len(latencies)/num_requests*100:.1f}%)")
    print(f"Failed requests:     {errors}")
    print()
    print(f"Latency (ms):")
    print(f"  Average: {avg:6.1f}ms")
    print(f"  P50:     {p50:6.1f}ms")
    print(f"  P95:     {p95:6.1f}ms {'✓ PASS' if p95 < 250 else '✗ FAIL'} (SLO: <250ms)")
    print(f"  P99:     {p99:6.1f}ms")
    print(f"  Min:     {min(latencies):6.1f}ms")
    print(f"  Max:     {max(latencies):6.1f}ms")
    print()

    # SLO validation
    slo_passed = True
    print("SLO Validation:")

    if p95 < 250:
        print(f"  ✓ P95 latency: {p95:.1f}ms < 250ms")
    else:
        print(f"  ✗ P95 latency: {p95:.1f}ms >= 250ms (VIOLATION)")
        slo_passed = False

    error_rate = (errors / num_requests) * 100
    if error_rate < 1:
        print(f"  ✓ Error rate: {error_rate:.1f}% < 1%")
    else:
        print(f"  ✗ Error rate: {error_rate:.1f}% >= 1% (VIOLATION)")
        slo_passed = False

    print()
    print("=" * 60)

    if slo_passed:
        print("✓ VALIDATION PASSED - Ready for production deployment")
    else:
        print("✗ VALIDATION FAILED - Review issues before production")

    print()
    return slo_passed


if __name__ == "__main__":
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"
    num_requests = int(sys.argv[2]) if len(sys.argv) > 2 else 20

    passed = run_lightweight_load_test(base_url, num_requests)
    sys.exit(0 if passed else 1)
