#!/usr/bin/env python
"""
Semantic mode performance validation without aggressive cache clearing.

This script validates BehaviorRetriever performance in semantic mode
under realistic conditions where the model stays warm and Redis cache
accumulates hits over time.
"""
import time
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from amprealize.behavior_retriever import BehaviorRetriever, RetrieveRequest, RetrievalStrategy


def measure_latency(retriever: BehaviorRetriever, query: str, strategy: RetrievalStrategy = RetrievalStrategy.HYBRID) -> float:
    """Measure retrieval latency in milliseconds."""
    start = time.perf_counter()
    request = RetrieveRequest(query=query, strategy=strategy, top_k=5)
    retriever.retrieve(request)
    return (time.perf_counter() - start) * 1000


def main():
    print("=" * 70)
    print("BehaviorRetriever Semantic Mode Performance Validation")
    print("=" * 70)
    print()

    # Initialize retriever with semantic mode
    dsn = "postgresql://amprealize_behavior:dev_behavior_pass@localhost:6433/behaviors"
    retriever = BehaviorRetriever(use_database=True, db_dsn=dsn, eager_load_model=True)

    print(f"Initializing BehaviorRetriever...")
    print(f"Status: {'ready' if retriever._semantic_available else 'degraded'}")
    print(f"Mode: {'semantic' if retriever._semantic_available else 'keyword'}")
    print(f"Behaviors: {len(retriever._behavior_ids)}")
    print()

    # Test queries from AGENTS.md
    test_queries = [
        "unify execution records",
        "align storage layers",
        "externalize configuration",
        "instrument metrics pipeline",
        "lock down security surface",
        "curate behavior handbook",
        "sanitize action registry",
        "wire CLI to orchestrator",
        "update docs after changes",
        "prevent secret leaks",
    ]

    print("-" * 70)
    print("Test 1: First Query (MPS warm-up + model inference)")
    print("-" * 70)
    first_latency = measure_latency(retriever, test_queries[0])
    print(f"Latency: {first_latency:.2f}ms")
    if first_latency < 200:
        print("✓ PASS: First query <200ms target")
    else:
        print(f"⚠️  INFO: First query includes MPS initialization ({first_latency:.2f}ms)")
    print()

    print("-" * 70)
    print("Test 2: Second Query (same query, Redis cache hit)")
    print("-" * 70)
    cached_latency = measure_latency(retriever, test_queries[0])
    print(f"Latency: {cached_latency:.2f}ms")
    if cached_latency < 10:
        print("✓ PASS: Cached query <10ms (Redis)")
    else:
        print(f"✗ FAIL: Cached query {cached_latency:.2f}ms exceeds 10ms")
    print()

    print("-" * 70)
    print("Test 3: Unique Queries (warm model, no cache)")
    print("-" * 70)
    latencies = []
    for query in test_queries[1:6]:  # 5 different queries
        lat = measure_latency(retriever, query)
        latencies.append(lat)
        print(f"  {query:35} {lat:8.2f}ms")

    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[int(len(latencies) * 0.95)]

    print()
    print(f"P50: {p50:.2f}ms")
    print(f"P95: {p95:.2f}ms")

    if p95 < 100:
        print("✓ PASS: P95 meets <100ms target")
    else:
        print(f"✗ FAIL: P95 {p95:.2f}ms exceeds 100ms target")
    print()

    print("-" * 70)
    print("Test 4: Repeated Queries (cache accumulation)")
    print("-" * 70)
    cache_latencies = []
    for query in test_queries[:5]:  # Repeat first 5 queries
        lat = measure_latency(retriever, query)
        cache_latencies.append(lat)

    cache_avg = sum(cache_latencies) / len(cache_latencies)
    cache_max = max(cache_latencies)
    print(f"Average: {cache_avg:.2f}ms")
    print(f"Max: {cache_max:.2f}ms")

    if cache_avg < 10:
        print("✓ PASS: Average cached latency <10ms")
    else:
        print(f"✗ FAIL: Average {cache_avg:.2f}ms exceeds 10ms")
    print()

    print("-" * 70)
    print("Test 5: Batch Retrieval (5 queries)")
    print("-" * 70)
    # Individual
    individual_queries = test_queries[5:10]
    start = time.perf_counter()
    for query in individual_queries:
        request = RetrieveRequest(query=query, strategy=RetrievalStrategy.HYBRID, top_k=5)
        retriever.retrieve(request)
    individual_ms = (time.perf_counter() - start) * 1000

    # Batch
    start = time.perf_counter()
    requests = [RetrieveRequest(query=q, strategy=RetrievalStrategy.HYBRID, top_k=5) for q in individual_queries]
    retriever.retrieve_batch(requests)
    batch_ms = (time.perf_counter() - start) * 1000

    speedup = individual_ms / batch_ms if batch_ms > 0 else 0

    print(f"Individual total: {individual_ms:.2f}ms")
    print(f"Batch total:      {batch_ms:.2f}ms")
    print(f"Speedup:          {speedup:.2f}x")

    if speedup >= 1.5:
        print("✓ PASS: Batch speedup ≥1.5x target")
    else:
        print(f"⚠️  WARN: Batch speedup {speedup:.2f}x < 1.5x target")
    print()

    print("=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"First query:    {first_latency:.2f}ms  (includes MPS init)")
    print(f"Cached query:   {cached_latency:.2f}ms  (target: <10ms)")
    print(f"Warm P95:       {p95:.2f}ms  (target: <100ms)")
    print(f"Cache average:  {cache_avg:.2f}ms  (target: <10ms)")
    print(f"Batch speedup:  {speedup:.2f}x  (target: >1.5x)")
    print()

    # Overall assessment
    targets_met = 0
    total_targets = 4

    if cached_latency < 10:
        targets_met += 1
    if p95 < 100:
        targets_met += 1
    if cache_avg < 10:
        targets_met += 1
    if speedup >= 1.5:
        targets_met += 1

    if targets_met == total_targets:
        print("✓ All targets met!")
    else:
        print(f"⚠️  {targets_met}/{total_targets} targets met")
    print("=" * 70)


if __name__ == "__main__":
    main()
