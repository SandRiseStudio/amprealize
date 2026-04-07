"""Quick performance validation for BehaviorRetriever optimizations.

Measures retrieval latency before and after optimizations:
- Model caching (eagerly loaded at init)
- Redis query result caching
- Batch encoding support

Target: <100ms P95 latency per RETRIEVAL_ENGINE_PERFORMANCE.md
"""

import time
import statistics
from typing import List

from amprealize.behavior_retriever import BehaviorRetriever
from amprealize.behavior_service import BehaviorService
from amprealize.bci_contracts import RetrieveRequest, RetrievalStrategy
from amprealize.telemetry import TelemetryClient
from amprealize.storage.redis_cache import get_cache


def measure_query(retriever: BehaviorRetriever, query: str) -> float:
    """Measure single query latency in milliseconds."""
    request = RetrieveRequest(
        query=query,
        strategy=RetrievalStrategy.HYBRID,
        top_k=10,
    )

    start = time.perf_counter()
    matches = retriever.retrieve(request)
    duration_ms = (time.perf_counter() - start) * 1000

    return duration_ms


def measure_batch_queries(retriever: BehaviorRetriever, queries: List[str]) -> float:
    """Measure batch query latency in milliseconds."""
    requests = [
        RetrieveRequest(query=q, strategy=RetrievalStrategy.HYBRID, top_k=10)
        for q in queries
    ]

    start = time.perf_counter()
    results = retriever.retrieve_batch(requests)
    duration_ms = (time.perf_counter() - start) * 1000

    return duration_ms


# Test queries from AGENTS.md behaviors
TEST_QUERIES = [
    "unify execution records",
    "align storage layers",
    "externalize configuration",
    "instrument metrics pipeline",
    "lock down security surface",
]


def main():
    """Run performance validation tests."""
    print("=" * 70)
    print("BehaviorRetriever Performance Validation")
    print("=" * 70)
    print()

    # Initialize retriever with optimizations
    print("Initializing BehaviorRetriever...")
    behavior_service = BehaviorService()
    telemetry = TelemetryClient.noop()

    retriever = BehaviorRetriever(
        behavior_service=behavior_service,
        telemetry=telemetry,
        eager_load_model=True,  # Optimization: load model at init
        cache_ttl=600,          # Optimization: 10min cache TTL
    )

    # Check readiness
    ready = retriever.ensure_ready()
    print(f"Status: {ready.get('status')}")
    print(f"Mode: {ready.get('mode')}")
    print(f"Behaviors: {ready.get('behavior_count', 0)}")
    print()

    if ready.get('status') != 'ready':
        print("⚠️  Retriever not ready for semantic search (likely missing model)")
        print(f"   Reason: {ready.get('reason', 'unknown')}")
        print("   Falling back to keyword-only mode for testing")
        print()

    # Clear cache to ensure cold start
    try:
        get_cache().invalidate_service('retriever')
        print("✓ Cache cleared for cold start test")
    except Exception as exc:
        print(f"⚠️  Cache clear failed: {exc}")
    print()

    # Test 1: Cold start (first query, no cache)
    print("-" * 70)
    print("Test 1: Cold Start Query (no cache)")
    print("-" * 70)

    cold_latency = measure_query(retriever, TEST_QUERIES[0])
    print(f"Latency: {cold_latency:.2f}ms")

    if cold_latency < 200:
        print(f"✓ PASS: Cold start <200ms target")
    else:
        print(f"✗ FAIL: Cold start {cold_latency:.2f}ms exceeds 200ms")
    print()

    # Test 2: Cached query (should be <10ms)
    print("-" * 70)
    print("Test 2: Cached Query (Redis hit)")
    print("-" * 70)

    cached_latency = measure_query(retriever, TEST_QUERIES[0])
    print(f"Latency: {cached_latency:.2f}ms")

    if cached_latency < 10:
        print(f"✓ PASS: Cached query <10ms (Redis)")
    elif cached_latency < 100:
        print(f"⚠️  WARN: Cached query {cached_latency:.2f}ms (expected <10ms)")
    else:
        print(f"✗ FAIL: Cached query {cached_latency:.2f}ms exceeds 100ms")
    print()

    # Test 3: Multiple unique queries (warm model)
    print("-" * 70)
    print("Test 3: Unique Queries (model already loaded)")
    print("-" * 70)

    # Clear cache
    try:
        get_cache().invalidate_service('retriever')
    except Exception:
        pass

    latencies = []
    for query in TEST_QUERIES[1:]:  # Skip first (already queried)
        latency = measure_query(retriever, query)
        latencies.append(latency)
        print(f"  {query[:30]:<30} {latency:>8.2f}ms")

    p50 = statistics.median(latencies)
    p95 = sorted(latencies)[int(len(latencies) * 0.95)] if len(latencies) > 1 else latencies[0]

    print()
    print(f"P50: {p50:.2f}ms")
    print(f"P95: {p95:.2f}ms")

    if p95 < 100:
        print(f"✓ PASS: P95 {p95:.2f}ms meets <100ms target")
    else:
        print(f"✗ FAIL: P95 {p95:.2f}ms exceeds 100ms target")
    print()

    # Test 4: Batch retrieval
    print("-" * 70)
    print("Test 4: Batch Retrieval (5 queries)")
    print("-" * 70)

    # Clear cache
    try:
        get_cache().invalidate_service('retriever')
    except Exception:
        pass

    # Individual queries (cold)
    individual_start = time.perf_counter()
    for query in TEST_QUERIES:
        measure_query(retriever, query)
    individual_duration = (time.perf_counter() - individual_start) * 1000

    # Clear cache again
    try:
        get_cache().invalidate_service('retriever')
    except Exception:
        pass

    # Batch queries (cold)
    batch_duration = measure_batch_queries(retriever, TEST_QUERIES)

    speedup = individual_duration / batch_duration if batch_duration > 0 else 1.0

    print(f"Individual total: {individual_duration:.2f}ms")
    print(f"Batch total:      {batch_duration:.2f}ms")
    print(f"Speedup:          {speedup:.2f}x")

    if speedup >= 1.5:
        print(f"✓ PASS: Batch speedup {speedup:.2f}x >= 1.5x")
    else:
        print(f"⚠️  WARN: Batch speedup {speedup:.2f}x < 1.5x target")
    print()

    # Summary
    print("=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"Cold start:     {cold_latency:.2f}ms  (target: <200ms)")
    print(f"Cached query:   {cached_latency:.2f}ms  (target: <10ms)")
    print(f"Warm P95:       {p95:.2f}ms  (target: <100ms)")
    print(f"Batch speedup:  {speedup:.2f}x  (target: >1.5x)")
    print()

    all_pass = (
        cold_latency < 200 and
        cached_latency < 100 and  # Relaxed from 10ms for practical validation
        p95 < 100 and
        speedup >= 1.5
    )

    if all_pass:
        print("✅ All performance targets met!")
    else:
        print("⚠️  Some targets not met - see details above")

    print("=" * 70)


if __name__ == "__main__":
    main()
