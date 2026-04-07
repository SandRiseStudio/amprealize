#!/usr/bin/env python3
"""Benchmark embedding models for memory usage, disk size, and retrieval quality.

Purpose:
    Measure resource impact and quality trade-offs of quantized embedding models
    (all-MiniLM-L6-v2, bge-small-en-v1.5) vs full model (BAAI/bge-m3).

    Supports Phase 1 optimization decision-making (behavior_curate_behavior_handbook)
    and validates quality retention thresholds from 3-phase plan (~85% of BGE-M3).

Usage:
    # Benchmark all models
    python scripts/benchmark_embedding_models.py --output data/embedding_benchmark.json

    # Benchmark specific models
    python scripts/benchmark_embedding_models.py \
        --models all-MiniLM-L6-v2,bge-m3 \
        --output data/benchmark.json

    # Quick test with fewer queries
    python scripts/benchmark_embedding_models.py \
        --models all-MiniLM-L6-v2 \
        --num-queries 5 \
        --output data/quick_benchmark.json

Output:
    JSON file with comparison data:
    - memory_mb: Peak memory usage in megabytes
    - disk_mb: Model size on disk in megabytes
    - inference_latency_ms: P50/P95/P99 query encoding latency
    - retrieval_quality_ndcg5: nDCG@5 against ground truth (if available)
    - model_info: Dimensions, max sequence length, pooling type
"""

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# Optional dependencies (graceful degradation)
try:
    import psutil  # type: ignore
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

try:
    from sentence_transformers import SentenceTransformer  # type: ignore
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False

try:
    from sklearn.metrics import ndcg_score  # type: ignore
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Default models to benchmark
DEFAULT_MODELS = [
    "sentence-transformers/all-MiniLM-L6-v2",  # 80MB, 384 dims - recommended Phase 1
    "BAAI/bge-small-en-v1.5",  # 133MB, 384 dims - alternative
    "BAAI/bge-m3",  # 2.3GB, 1024 dims - baseline for comparison
]

# Ground truth behavior queries for quality validation
# Format: (query, [relevant_behavior_ids])
GROUND_TRUTH_QUERIES = [
    ("execution record tracking", ["behavior_unify_execution_records"]),
    ("storage adapter alignment", ["behavior_align_storage_layers"]),
    ("hardcoded config paths", ["behavior_externalize_configuration"]),
    ("service boundary calls", ["behavior_harden_service_boundaries"]),
    ("behavior handbook updates", ["behavior_curate_behavior_handbook"]),
    ("action registry schemas", ["behavior_sanitize_action_registry"]),
    ("telemetry events", ["behavior_instrument_metrics_pipeline"]),
    ("CLI orchestration", ["behavior_wire_cli_to_orchestrator"]),
    ("CORS security", ["behavior_lock_down_security_surface"]),
    ("documentation sync", ["behavior_update_docs_after_changes"]),
    ("consent experience", ["behavior_prototype_consent_ux"]),
    ("credential rotation", ["behavior_rotate_leaked_credentials"]),
    ("handbook compliance", ["behavior_handbook_compliance_prompt"]),
    ("secret scanning", ["behavior_prevent_secret_leaks"]),
    ("git branching", ["behavior_git_governance"]),
]


def get_model_disk_size(model_name: str, cache_dir: Path) -> float:
    """Get model size on disk in MB.

    Args:
        model_name: HuggingFace model identifier
        cache_dir: Directory where model is cached

    Returns:
        Size in megabytes
    """
    # Find model directory in cache
    model_dirs = list(cache_dir.glob(f"*{model_name.split('/')[-1]}*"))
    if not model_dirs:
        logger.warning("Model directory not found for %s", model_name)
        return 0.0

    total_size = 0
    for model_dir in model_dirs:
        if model_dir.is_dir():
            for file in model_dir.rglob("*"):
                if file.is_file():
                    total_size += file.stat().st_size

    return total_size / (1024 * 1024)  # Convert bytes to MB


def measure_memory_usage(model: Any, queries: List[str]) -> Tuple[float, float]:
    """Measure peak memory usage during model encoding.

    Args:
        model: SentenceTransformer model instance
        queries: List of queries to encode

    Returns:
        Tuple of (peak_memory_mb, baseline_memory_mb)
    """
    if not PSUTIL_AVAILABLE:
        logger.warning("psutil not available; skipping memory measurement")
        return (0.0, 0.0)

    process = psutil.Process(os.getpid())
    baseline_memory = process.memory_info().rss / (1024 * 1024)  # MB

    # Encode queries and measure peak
    _ = model.encode(queries, convert_to_numpy=True, show_progress_bar=False)

    peak_memory = process.memory_info().rss / (1024 * 1024)  # MB

    return (peak_memory, baseline_memory)


def measure_inference_latency(model: Any, queries: List[str], num_runs: int = 10) -> Dict[str, float]:
    """Measure query encoding latency percentiles.

    Args:
        model: SentenceTransformer model instance
        queries: List of queries to encode
        num_runs: Number of repeated measurements for percentiles

    Returns:
        Dict with p50, p95, p99 latency in milliseconds
    """
    latencies = []

    for _ in range(num_runs):
        for query in queries:
            start = time.perf_counter()
            _ = model.encode([query], convert_to_numpy=True, show_progress_bar=False)
            latency_ms = (time.perf_counter() - start) * 1000
            latencies.append(latency_ms)

    latencies = np.array(latencies)

    return {
        "p50": float(np.percentile(latencies, 50)),
        "p95": float(np.percentile(latencies, 95)),
        "p99": float(np.percentile(latencies, 99)),
        "mean": float(np.mean(latencies)),
        "min": float(np.min(latencies)),
        "max": float(np.max(latencies)),
    }


def compute_retrieval_quality(
    model: Any,
    queries: List[str],
    ground_truth: List[List[str]],
    behavior_corpus: List[str],
) -> Dict[str, float]:
    """Compute retrieval quality metrics (nDCG@5) against ground truth.

    Args:
        model: SentenceTransformer model instance
        queries: List of query strings
        ground_truth: List of lists of relevant behavior IDs per query
        behavior_corpus: List of all behavior IDs in index

    Returns:
        Dict with nDCG@5 and other quality metrics
    """
    if not SKLEARN_AVAILABLE:
        logger.warning("scikit-learn not available; skipping quality measurement")
        return {"ndcg@5": 0.0}

    # Encode queries and behaviors
    query_embeddings = model.encode(queries, convert_to_numpy=True, show_progress_bar=False)
    behavior_embeddings = model.encode(behavior_corpus, convert_to_numpy=True, show_progress_bar=False)

    # Compute cosine similarities (normalized dot product)
    from sklearn.preprocessing import normalize  # type: ignore
    query_embeddings = normalize(query_embeddings)
    behavior_embeddings = normalize(behavior_embeddings)

    # Compute nDCG@5 for each query
    ndcg_scores = []

    for i, (query_emb, relevant_ids) in enumerate(zip(query_embeddings, ground_truth)):
        # Compute scores for all behaviors
        scores = query_emb @ behavior_embeddings.T

        # Create relevance vector (1 for relevant, 0 for irrelevant)
        relevance = np.array([
            1.0 if behavior_id in relevant_ids else 0.0
            for behavior_id in behavior_corpus
        ])

        # Compute nDCG@5
        try:
            ndcg = ndcg_score([relevance], [scores], k=5)
            ndcg_scores.append(ndcg)
        except Exception as exc:
            logger.warning("Failed to compute nDCG for query %d: %s", i, exc)

    if not ndcg_scores:
        return {"ndcg@5": 0.0}

    return {
        "ndcg@5": float(np.mean(ndcg_scores)),
        "ndcg@5_std": float(np.std(ndcg_scores)),
        "ndcg@5_min": float(np.min(ndcg_scores)),
        "ndcg@5_max": float(np.max(ndcg_scores)),
    }


def benchmark_model(
    model_name: str,
    cache_dir: Path,
    queries: List[str],
    ground_truth: Optional[List[List[str]]] = None,
    behavior_corpus: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Benchmark a single embedding model.

    Args:
        model_name: HuggingFace model identifier
        cache_dir: Directory to cache models
        queries: List of queries for latency/quality testing
        ground_truth: Optional list of relevant behavior IDs per query
        behavior_corpus: Optional list of all behavior IDs

    Returns:
        Dict with benchmark results
    """
    logger.info("Benchmarking model: %s", model_name)

    if not SENTENCE_TRANSFORMERS_AVAILABLE:
        logger.error("sentence-transformers not available; cannot benchmark")
        return {
            "model_name": model_name,
            "error": "sentence-transformers dependency missing",
        }

    try:
        # Load model
        load_start = time.perf_counter()
        model = SentenceTransformer(model_name, cache_folder=str(cache_dir))
        load_duration = time.perf_counter() - load_start

        # Get model info
        model_info = {
            "max_seq_length": model.max_seq_length,
            "embedding_dim": model.get_sentence_embedding_dimension(),
            "load_duration_seconds": load_duration,
        }

        # Measure disk size
        disk_mb = get_model_disk_size(model_name, cache_dir)

        # Measure memory usage
        peak_memory_mb, baseline_memory_mb = measure_memory_usage(model, queries)
        memory_delta_mb = peak_memory_mb - baseline_memory_mb

        # Measure inference latency
        latency = measure_inference_latency(model, queries)

        # Measure retrieval quality (if ground truth provided)
        quality = {}
        if ground_truth and behavior_corpus:
            quality = compute_retrieval_quality(model, queries, ground_truth, behavior_corpus)

        return {
            "model_name": model_name,
            "disk_mb": disk_mb,
            "memory_mb": peak_memory_mb,
            "memory_delta_mb": memory_delta_mb,
            "baseline_memory_mb": baseline_memory_mb,
            "latency_ms": latency,
            "quality": quality,
            "model_info": model_info,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    except Exception as exc:
        logger.error("Failed to benchmark model %s: %s", model_name, exc, exc_info=True)
        return {
            "model_name": model_name,
            "error": str(exc),
        }


def main() -> int:
    """Main benchmark entrypoint."""
    parser = argparse.ArgumentParser(
        description="Benchmark embedding models for memory, disk, and quality",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--models",
        type=str,
        default=",".join(DEFAULT_MODELS),
        help=f"Comma-separated list of models to benchmark (default: {','.join(DEFAULT_MODELS)})",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/embedding_benchmark.json",
        help="Output JSON file path (default: data/embedding_benchmark.json)",
    )
    parser.add_argument(
        "--cache-dir",
        type=str,
        default=str(Path.home() / ".cache" / "huggingface" / "hub"),
        help="Model cache directory (default: ~/.cache/huggingface/hub)",
    )
    parser.add_argument(
        "--num-queries",
        type=int,
        default=len(GROUND_TRUTH_QUERIES),
        help=f"Number of queries to test (default: {len(GROUND_TRUTH_QUERIES)})",
    )
    parser.add_argument(
        "--skip-quality",
        action="store_true",
        help="Skip retrieval quality measurement (faster, no ground truth needed)",
    )

    args = parser.parse_args()

    # Parse models
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if not models:
        logger.error("No models specified")
        return 1

    # Prepare cache dir
    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Prepare output dir
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Prepare queries
    queries = [q for q, _ in GROUND_TRUTH_QUERIES[:args.num_queries]]
    ground_truth = [ids for _, ids in GROUND_TRUTH_QUERIES[:args.num_queries]] if not args.skip_quality else None

    # Extract behavior corpus from ground truth
    behavior_corpus = None
    if ground_truth:
        unique_behaviors = set()
        for ids in ground_truth:
            unique_behaviors.update(ids)
        behavior_corpus = sorted(unique_behaviors)

    # Benchmark each model
    results = []
    for model_name in models:
        result = benchmark_model(
            model_name,
            cache_dir,
            queries,
            ground_truth=ground_truth,
            behavior_corpus=behavior_corpus,
        )
        results.append(result)

        # Log summary
        if "error" in result:
            logger.error("❌ %s: %s", model_name, result["error"])
        else:
            logger.info(
                "✅ %s: disk=%.1fMB, memory=%.1fMB, p95_latency=%.1fms, ndcg@5=%.3f",
                model_name,
                result.get("disk_mb", 0),
                result.get("memory_mb", 0),
                result.get("latency_ms", {}).get("p95", 0),
                result.get("quality", {}).get("ndcg@5", 0),
            )

    # Write results
    output_data = {
        "benchmark_metadata": {
            "timestamp": datetime.now(UTC).isoformat(),
            "models": models,
            "num_queries": len(queries),
            "skip_quality": args.skip_quality,
            "cache_dir": str(cache_dir),
        },
        "results": results,
    }

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2)

    logger.info("Benchmark results written to %s", output_path)

    # Print comparison table
    print("\n" + "=" * 100)
    print("EMBEDDING MODEL BENCHMARK COMPARISON")
    print("=" * 100)
    print(f"{'Model':<50} {'Disk (MB)':<12} {'Memory (MB)':<12} {'P95 Latency (ms)':<18} {'nDCG@5':<10}")
    print("-" * 100)

    for result in results:
        if "error" in result:
            print(f"{result['model_name']:<50} {'ERROR':<12} {'ERROR':<12} {'ERROR':<18} {'ERROR':<10}")
        else:
            print(
                f"{result['model_name']:<50} "
                f"{result.get('disk_mb', 0):<12.1f} "
                f"{result.get('memory_mb', 0):<12.1f} "
                f"{result.get('latency_ms', {}).get('p95', 0):<18.1f} "
                f"{result.get('quality', {}).get('ndcg@5', 0):<10.3f}"
            )

    print("=" * 100 + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
