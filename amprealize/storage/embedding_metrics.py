"""Prometheus metrics for embedding model performance and retrieval.

This module provides instrumentation for Phase 1 Embedding Optimization SLO monitoring:
- Model loading performance (lazy loading overhead, memory footprint)
- Retrieval latency (P50, P95, P99 against <250ms SLO target)
- Cache efficiency (hit rates, cost savings)
- Quality proxy metrics (fallback rates, degraded mode usage)

Phase 1 SLO Targets (RETRIEVAL_ENGINE_PERFORMANCE.md):
- P95 retrieval latency <250ms
- Memory footprint <750MB
- Quality nDCG@5 >0.85 (validated via offline benchmarks)
- Disk storage <100MB

Usage:
    from amprealize.storage.embedding_metrics import (
        record_model_load,
        record_retrieval_latency,
        increment_cache_hit,
        increment_cache_miss,
    )

    # In BehaviorRetriever._load_model() for lazy loading tracking
    start = time.time()
    model = SentenceTransformer(model_name, device=device)
    load_time = time.time() - start
    record_model_load(model_name, load_time, memory_bytes)

    # In BehaviorRetriever.retrieve() for latency tracking
    start = time.time()
    matches = ... # retrieval logic
    record_retrieval_latency(strategy, time.time() - start)

    # Cache instrumentation (already exists, extending for embedding context)
    if cache_hit:
        increment_cache_hit(strategy="embedding")
    else:
        increment_cache_miss(strategy="embedding")
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Optional

try:
    from prometheus_client import Counter, Gauge, Histogram, Info
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    # Stub implementations for when prometheus_client is not installed
    class Counter:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs): pass
        def labels(self, *args, **kwargs): return self
        def inc(self, *args, **kwargs): pass

    class Gauge:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs): pass
        def labels(self, *args, **kwargs): return self
        def set(self, *args, **kwargs): pass
        def inc(self, *args, **kwargs): pass
        def dec(self, *args, **kwargs): pass

    class Histogram:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs): pass
        def labels(self, *args, **kwargs): return self
        def observe(self, *args, **kwargs): pass
        def time(self): return self
        def __enter__(self): return self
        def __exit__(self, *args): pass

    class Info:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs): pass
        def info(self, *args, **kwargs): pass


# Model loading metrics (lazy loading optimization tracking)
embedding_model_load_count = Counter(
    "amprealize_embedding_model_load_count_total",
    "Total number of embedding model loads (should be 1 for lazy loading)",
    ["model_name"],
)

embedding_model_load_time_seconds = Histogram(
    "amprealize_embedding_model_load_time_seconds",
    "Embedding model initialization duration (lazy loading overhead)",
    ["model_name"],
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0],  # Model loading can be slow
)

embedding_model_memory_bytes = Gauge(
    "amprealize_embedding_model_memory_bytes",
    "Current embedding model memory footprint (Phase 1 SLO <750MB)",
    ["model_name"],
)

embedding_model_info = Info(
    "amprealize_embedding_model",
    "Embedding model metadata (name, dimensions, device)",
)

# Retrieval performance metrics (Phase 1 SLO <250ms P95)
retrieval_latency_seconds = Histogram(
    "amprealize_retrieval_latency_seconds",
    "Behavior retrieval latency by strategy and model (Phase 1 SLO P95 <250ms, Phase 2 A/B testing)",
    ["strategy", "model_name"],  # embedding/keyword/hybrid, all-MiniLM-L6-v2/bge-m3
    buckets=[0.01, 0.025, 0.05, 0.1, 0.15, 0.2, 0.25, 0.5, 1.0, 2.5],  # Fine-grained <250ms
)

retrieval_requests_total = Counter(
    "amprealize_retrieval_requests_total",
    "Total number of retrieval requests by strategy and model (Phase 2 A/B cohort tracking)",
    ["strategy", "model_name"],
)

retrieval_matches_total = Counter(
    "amprealize_retrieval_matches_total",
    "Total number of behaviors matched across all retrievals",
    ["strategy", "model_name"],
)

# Cache efficiency metrics (Redis cache + FAISS index performance)
retrieval_cache_hits_total = Counter(
    "amprealize_retrieval_cache_hits_total",
    "Total number of retrieval cache hits (token savings)",
    ["strategy"],
)

retrieval_cache_misses_total = Counter(
    "amprealize_retrieval_cache_misses_total",
    "Total number of retrieval cache misses (triggers embedding inference)",
    ["strategy"],
)

# Quality proxy metrics (degraded mode, fallbacks, errors)
retrieval_degraded_mode_total = Counter(
    "amprealize_retrieval_degraded_mode_total",
    "Total retrievals in degraded mode (semantic unavailable, fallback to keyword)",
    ["reason"],  # dependencies-missing, index-not-ready, model-load-failed
)

retrieval_failures_total = Counter(
    "amprealize_retrieval_failures_total",
    "Total retrieval failures by error type",
    ["error_type"],
)

# FAISS index metrics
faiss_index_behaviors_total = Gauge(
    "amprealize_faiss_index_behaviors_total",
    "Total number of behaviors in FAISS index",
)

faiss_index_rebuild_total = Counter(
    "amprealize_faiss_index_rebuild_total",
    "Total number of FAISS index rebuilds",
)

faiss_index_rebuild_duration_seconds = Histogram(
    "amprealize_faiss_index_rebuild_duration_seconds",
    "FAISS index rebuild duration",
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 60.0],
)


def record_model_load(
    model_name: str,
    load_time_seconds: float,
    memory_bytes: Optional[int] = None,
    dimensions: Optional[int] = None,
    device: Optional[str] = None,
) -> None:
    """Record embedding model load event (lazy loading optimization tracking).

    Args:
        model_name: Model identifier (e.g., "sentence-transformers/all-MiniLM-L6-v2")
        load_time_seconds: Model initialization duration
        memory_bytes: Model memory footprint (if available)
        dimensions: Embedding vector dimensions (if available)
        device: Device (cpu, cuda, mps) if available
    """
    if not PROMETHEUS_AVAILABLE:
        return

    embedding_model_load_count.labels(model_name=model_name).inc()
    embedding_model_load_time_seconds.labels(model_name=model_name).observe(load_time_seconds)

    if memory_bytes is not None:
        embedding_model_memory_bytes.labels(model_name=model_name).set(memory_bytes)

    # Update model metadata
    info_dict = {"model_name": model_name}
    if dimensions is not None:
        info_dict["dimensions"] = str(dimensions)
    if device is not None:
        info_dict["device"] = device
    embedding_model_info.info(info_dict)


def record_retrieval_latency(strategy: str, duration_seconds: float, model_name: str = "unknown") -> None:
    """Record retrieval latency for Phase 1 SLO monitoring (P95 <250ms) and Phase 2 A/B testing.

    Args:
        strategy: Retrieval strategy (embedding, keyword, hybrid, keyword-degraded)
        duration_seconds: Retrieval duration
        model_name: Model used for retrieval (Phase 2: for A/B cohort comparison)
    """
    if not PROMETHEUS_AVAILABLE:
        return

    retrieval_latency_seconds.labels(strategy=strategy, model_name=model_name).observe(duration_seconds)
    retrieval_requests_total.labels(strategy=strategy, model_name=model_name).inc()


def record_retrieval_matches(strategy: str, match_count: int, model_name: str = "unknown") -> None:
    """Record number of behaviors matched in retrieval.

    Args:
        strategy: Retrieval strategy
        match_count: Number of behaviors returned
        model_name: Model used for retrieval (Phase 2: for A/B cohort comparison)
    """
    if not PROMETHEUS_AVAILABLE:
        return

    retrieval_matches_total.labels(strategy=strategy, model_name=model_name).inc(match_count)


def increment_cache_hit(strategy: str) -> None:
    """Record retrieval cache hit (token savings, no embedding inference needed).

    Args:
        strategy: Retrieval strategy
    """
    if not PROMETHEUS_AVAILABLE:
        return

    retrieval_cache_hits_total.labels(strategy=strategy).inc()


def increment_cache_miss(strategy: str) -> None:
    """Record retrieval cache miss (triggers embedding inference).

    Args:
        strategy: Retrieval strategy
    """
    if not PROMETHEUS_AVAILABLE:
        return

    retrieval_cache_misses_total.labels(strategy=strategy).inc()


def record_degraded_mode(reason: str) -> None:
    """Record retrieval in degraded mode (semantic unavailable, fallback to keyword).

    Args:
        reason: Degradation reason (dependencies-missing, index-not-ready, model-load-failed)
    """
    if not PROMETHEUS_AVAILABLE:
        return

    retrieval_degraded_mode_total.labels(reason=reason).inc()


def record_retrieval_failure(error_type: str) -> None:
    """Record retrieval failure for alerting.

    Args:
        error_type: Error classification (timeout, model-error, index-error, unknown)
    """
    if not PROMETHEUS_AVAILABLE:
        return

    retrieval_failures_total.labels(error_type=error_type).inc()


def record_faiss_index_rebuild(
    behavior_count: int,
    duration_seconds: float,
) -> None:
    """Record FAISS index rebuild event.

    Args:
        behavior_count: Number of behaviors indexed
        duration_seconds: Index rebuild duration
    """
    if not PROMETHEUS_AVAILABLE:
        return

    faiss_index_behaviors_total.set(behavior_count)
    faiss_index_rebuild_total.inc()
    faiss_index_rebuild_duration_seconds.observe(duration_seconds)


@contextmanager
def track_retrieval(strategy: str):
    """Context manager for automatic retrieval latency tracking.

    Usage:
        with track_retrieval("embedding"):
            matches = retriever.retrieve(request)

    Args:
        strategy: Retrieval strategy
    """
    start = time.time()
    try:
        yield
    finally:
        duration = time.time() - start
        record_retrieval_latency(strategy, duration)
