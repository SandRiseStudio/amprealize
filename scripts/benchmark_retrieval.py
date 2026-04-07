#!/usr/bin/env python3
"""
Behavior Retrieval Benchmark Script

Benchmarks behavior retrieval performance with the full behavior corpus.
Supports both embedding-based (FAISS) and keyword-based retrieval.

Usage:
    # Run with defaults
    python scripts/benchmark_retrieval.py

    # Run with custom settings
    python scripts/benchmark_retrieval.py --sample-size 200 --top-k 5

    # Output JSON for CI
    python scripts/benchmark_retrieval.py --output json --out-file results.json

Environment:
    BEHAVIOR_PG_DSN: PostgreSQL connection string for behavior service
    EMBEDDING_MODEL_NAME: Sentence-transformers model (default: all-MiniLM-L6-v2)
"""

import argparse
import json
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import mean, stdev
from typing import Any, Dict, List, Optional

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    from sentence_transformers import SentenceTransformer
    HAS_SENTENCE_TRANSFORMERS = True
except ImportError:
    HAS_SENTENCE_TRANSFORMERS = False


@dataclass
class BenchmarkQuery:
    """A query for benchmarking with expected behavior matches."""
    query: str
    expected_behavior_ids: List[str] = field(default_factory=list)
    expected_keywords: List[str] = field(default_factory=list)
    category: str = "general"


@dataclass
class RetrievalResult:
    """Result from a single retrieval query."""
    query: str
    latency_ms: float
    retrieved_ids: List[str]
    top_k: int
    hit_at_k: Dict[int, bool] = field(default_factory=dict)
    recall_at_k: Dict[int, float] = field(default_factory=dict)


@dataclass
class BenchmarkResults:
    """Aggregated benchmark results."""
    benchmark_id: str
    timestamp: str
    corpus_size: int
    sample_size: int
    top_k: int
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    std_latency_ms: float
    min_latency_ms: float
    max_latency_ms: float
    accuracy_at_k: Dict[str, float] = field(default_factory=dict)
    recall_at_k: Dict[str, float] = field(default_factory=dict)
    queries_per_second: float = 0.0
    embedding_model: str = ""
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class BehaviorBenchmark:
    """Benchmark harness for behavior retrieval."""

    # Default benchmark queries covering common scenarios
    DEFAULT_QUERIES = [
        BenchmarkQuery(
            query="How do I add logging to my service?",
            expected_keywords=["logging", "raze", "telemetry"],
            category="logging",
        ),
        BenchmarkQuery(
            query="Set up a container environment",
            expected_keywords=["environment", "container", "breakeramp", "blueprint"],
            category="infrastructure",
        ),
        BenchmarkQuery(
            query="Prevent secret leaks in code",
            expected_keywords=["secret", "credential", "gitleaks", "pre-commit"],
            category="security",
        ),
        BenchmarkQuery(
            query="Create a standalone package",
            expected_keywords=["package", "standalone", "reusable"],
            category="architecture",
        ),
        BenchmarkQuery(
            query="Use MCP tools in IDE",
            expected_keywords=["mcp", "tool", "ide", "extension"],
            category="tooling",
        ),
        BenchmarkQuery(
            query="Update documentation after changes",
            expected_keywords=["docs", "documentation", "update", "readme"],
            category="documentation",
        ),
        BenchmarkQuery(
            query="Git branching and merge workflow",
            expected_keywords=["git", "branch", "merge", "workflow"],
            category="git",
        ),
        BenchmarkQuery(
            query="CI/CD pipeline setup",
            expected_keywords=["ci", "cd", "pipeline", "deployment"],
            category="devops",
        ),
        BenchmarkQuery(
            query="Handle configuration externalization",
            expected_keywords=["config", "environment", "secrets"],
            category="configuration",
        ),
        BenchmarkQuery(
            query="Add behavior to handbook",
            expected_keywords=["behavior", "handbook", "curate"],
            category="behaviors",
        ),
    ]

    def __init__(
        self,
        dsn: Optional[str] = None,
        embedding_model: Optional[str] = None,
    ):
        self.dsn = dsn or os.environ.get("BEHAVIOR_PG_DSN", "")
        self.embedding_model_name = embedding_model or os.environ.get(
            "EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2"
        )
        self._embedding_model = None
        self._behaviors_cache: List[Dict[str, Any]] = []

    def _get_embedding_model(self) -> Optional[Any]:
        """Lazy load embedding model."""
        if not HAS_SENTENCE_TRANSFORMERS:
            return None
        if self._embedding_model is None:
            self._embedding_model = SentenceTransformer(self.embedding_model_name)
        return self._embedding_model

    def _generate_embedding(self, text: str) -> Optional[List[float]]:
        """Generate embedding for text."""
        model = self._get_embedding_model()
        if model is None:
            return None
        embedding = model.encode(text, convert_to_numpy=True)
        if hasattr(embedding, "tolist"):
            return embedding.tolist()
        return list(embedding)

    def load_behaviors(self) -> List[Dict[str, Any]]:
        """Load all behaviors from database."""
        if self._behaviors_cache:
            return self._behaviors_cache

        try:
            import psycopg2
        except ImportError:
            print("Warning: psycopg2 not installed, using mock data")
            return self._generate_mock_behaviors()

        if not self.dsn:
            print("Warning: No database DSN configured, using mock data")
            return self._generate_mock_behaviors()

        try:
            conn = psycopg2.connect(self.dsn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT b.behavior_id, b.name, b.description, b.tags, b.status,
                           bv.instruction, bv.trigger_keywords, bv.embedding
                    FROM behaviors b
                    JOIN behavior_versions bv ON b.behavior_id = bv.behavior_id
                    WHERE bv.status IN ('APPROVED', 'DRAFT')
                    ORDER BY b.updated_at DESC
                    """
                )
                rows = cur.fetchall()
                columns = [desc[0] for desc in cur.description]

            conn.close()

            behaviors = []
            for row in rows:
                data = dict(zip(columns, row))
                embedding = None
                if data.get("embedding"):
                    try:
                        if isinstance(data["embedding"], memoryview):
                            embedding = json.loads(data["embedding"].tobytes().decode())
                        elif isinstance(data["embedding"], bytes):
                            embedding = json.loads(data["embedding"].decode())
                        elif isinstance(data["embedding"], str):
                            embedding = json.loads(data["embedding"])
                        elif isinstance(data["embedding"], list):
                            embedding = data["embedding"]
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        pass

                behaviors.append({
                    "behavior_id": str(data["behavior_id"]),
                    "name": data["name"],
                    "description": data["description"],
                    "tags": json.loads(data["tags"]) if isinstance(data["tags"], str) else data["tags"],
                    "instruction": data["instruction"],
                    "trigger_keywords": (
                        json.loads(data["trigger_keywords"])
                        if isinstance(data["trigger_keywords"], str)
                        else data["trigger_keywords"]
                    ),
                    "embedding": embedding,
                })

            self._behaviors_cache = behaviors
            return behaviors

        except Exception as e:
            print(f"Warning: Database error ({e}), using mock data")
            return self._generate_mock_behaviors()

    def _generate_mock_behaviors(self) -> List[Dict[str, Any]]:
        """Generate mock behaviors for testing without database."""
        mock_behaviors = [
            {
                "behavior_id": str(uuid.uuid4()),
                "name": "behavior_use_raze_for_logging",
                "description": "Use Raze for structured logging and telemetry",
                "tags": ["logging", "telemetry", "observability"],
                "instruction": "Import RazeLogger, configure sink, use structured fields",
                "trigger_keywords": ["logging", "raze", "telemetry", "structured logs"],
                "embedding": None,
            },
            {
                "behavior_id": str(uuid.uuid4()),
                "name": "behavior_use_breakeramp_for_environments",
                "description": "Use BreakerAmp for container and environment management",
                "tags": ["infrastructure", "containers", "environments"],
                "instruction": "Create blueprint, use plan/apply/destroy workflow",
                "trigger_keywords": ["environment", "container", "breakeramp", "blueprint", "podman"],
                "embedding": None,
            },
            {
                "behavior_id": str(uuid.uuid4()),
                "name": "behavior_prevent_secret_leaks",
                "description": "Prevent secrets from leaking into code or logs",
                "tags": ["security", "secrets", "compliance"],
                "instruction": "Run pre-commit hooks, use gitignore, scan secrets",
                "trigger_keywords": ["secret", "credential", "gitleaks", "leak"],
                "embedding": None,
            },
            {
                "behavior_id": str(uuid.uuid4()),
                "name": "behavior_prefer_mcp_tools",
                "description": "Prefer MCP tools over CLI/API when available",
                "tags": ["tooling", "mcp", "ide"],
                "instruction": "Check available MCP tools, prefer over CLI, fallback gracefully",
                "trigger_keywords": ["mcp", "tool", "ide", "extension"],
                "embedding": None,
            },
            {
                "behavior_id": str(uuid.uuid4()),
                "name": "behavior_git_governance",
                "description": "Follow git workflow and branching conventions",
                "tags": ["git", "workflow", "governance"],
                "instruction": "Create branches as role/short-slug, run pre-commit",
                "trigger_keywords": ["git", "branch", "merge", "workflow"],
                "embedding": None,
            },
        ]

        # Generate embeddings for mock data if possible
        for behavior in mock_behaviors:
            text = f"{behavior['name']} {behavior['description']} {behavior['instruction']}"
            behavior["embedding"] = self._generate_embedding(text)

        self._behaviors_cache = mock_behaviors
        return mock_behaviors

    def _keyword_retrieval(
        self,
        query: str,
        behaviors: List[Dict[str, Any]],
        top_k: int,
    ) -> List[str]:
        """Simple keyword-based retrieval."""
        query_tokens = set(query.lower().split())

        scored = []
        for behavior in behaviors:
            haystack = " ".join([
                behavior["name"],
                behavior["description"],
                " ".join(behavior.get("tags", [])),
                " ".join(behavior.get("trigger_keywords", [])),
            ]).lower()

            haystack_tokens = set(haystack.split())
            overlap = len(query_tokens & haystack_tokens)
            if overlap > 0:
                scored.append((behavior["behavior_id"], overlap))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [bid for bid, _ in scored[:top_k]]

    def _embedding_retrieval(
        self,
        query: str,
        behaviors: List[Dict[str, Any]],
        top_k: int,
    ) -> List[str]:
        """Embedding-based retrieval using cosine similarity."""
        if not HAS_NUMPY:
            return self._keyword_retrieval(query, behaviors, top_k)

        query_embedding = self._generate_embedding(query)
        if query_embedding is None:
            return self._keyword_retrieval(query, behaviors, top_k)

        query_vec = np.array(query_embedding)

        scored = []
        for behavior in behaviors:
            if behavior.get("embedding") is None:
                continue
            behavior_vec = np.array(behavior["embedding"])
            # Cosine similarity
            similarity = np.dot(query_vec, behavior_vec) / (
                np.linalg.norm(query_vec) * np.linalg.norm(behavior_vec) + 1e-8
            )
            scored.append((behavior["behavior_id"], float(similarity)))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [bid for bid, _ in scored[:top_k]]

    def run_single_query(
        self,
        query: BenchmarkQuery,
        behaviors: List[Dict[str, Any]],
        top_k: int,
        use_embeddings: bool = True,
    ) -> RetrievalResult:
        """Run a single benchmark query."""
        start_time = time.perf_counter()

        if use_embeddings:
            retrieved_ids = self._embedding_retrieval(query.query, behaviors, top_k)
        else:
            retrieved_ids = self._keyword_retrieval(query.query, behaviors, top_k)

        latency_ms = (time.perf_counter() - start_time) * 1000

        # Calculate hit@k and recall@k if expected behaviors provided
        hit_at_k = {}
        recall_at_k = {}

        if query.expected_behavior_ids:
            expected_set = set(query.expected_behavior_ids)
            for k in [1, 3, 5, 10]:
                if k <= top_k:
                    top_k_results = set(retrieved_ids[:k])
                    hit_at_k[k] = bool(top_k_results & expected_set)
                    recall_at_k[k] = len(top_k_results & expected_set) / len(expected_set)
        elif query.expected_keywords:
            # Check if retrieved behaviors contain expected keywords
            for k in [1, 3, 5, 10]:
                if k <= top_k:
                    top_k_results = retrieved_ids[:k]
                    matching = 0
                    for bid in top_k_results:
                        behavior = next((b for b in behaviors if b["behavior_id"] == bid), None)
                        if behavior:
                            haystack = " ".join([
                                behavior["name"],
                                behavior["description"],
                                " ".join(behavior.get("trigger_keywords", [])),
                            ]).lower()
                            if any(kw.lower() in haystack for kw in query.expected_keywords):
                                matching += 1
                                break
                    hit_at_k[k] = matching > 0
                    recall_at_k[k] = matching / len(query.expected_keywords) if matching else 0

        return RetrievalResult(
            query=query.query,
            latency_ms=latency_ms,
            retrieved_ids=retrieved_ids,
            top_k=top_k,
            hit_at_k=hit_at_k,
            recall_at_k=recall_at_k,
        )

    def run_benchmark(
        self,
        sample_size: int = 100,
        top_k: int = 5,
        queries: Optional[List[BenchmarkQuery]] = None,
        use_embeddings: bool = True,
    ) -> BenchmarkResults:
        """Run full benchmark suite."""
        benchmark_id = str(uuid.uuid4())
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        behaviors = self.load_behaviors()
        if not behaviors:
            return BenchmarkResults(
                benchmark_id=benchmark_id,
                timestamp=timestamp,
                corpus_size=0,
                sample_size=0,
                top_k=top_k,
                avg_latency_ms=0,
                p50_latency_ms=0,
                p95_latency_ms=0,
                p99_latency_ms=0,
                std_latency_ms=0,
                min_latency_ms=0,
                max_latency_ms=0,
                errors=["No behaviors loaded"],
            )

        # Use provided queries or default
        test_queries = queries or self.DEFAULT_QUERIES

        # Repeat queries to reach sample size
        all_queries = []
        while len(all_queries) < sample_size:
            all_queries.extend(test_queries)
        all_queries = all_queries[:sample_size]

        results: List[RetrievalResult] = []
        errors: List[str] = []

        for query in all_queries:
            try:
                result = self.run_single_query(query, behaviors, top_k, use_embeddings)
                results.append(result)
            except Exception as e:
                errors.append(f"Query '{query.query[:50]}...': {str(e)}")

        if not results:
            return BenchmarkResults(
                benchmark_id=benchmark_id,
                timestamp=timestamp,
                corpus_size=len(behaviors),
                sample_size=sample_size,
                top_k=top_k,
                avg_latency_ms=0,
                p50_latency_ms=0,
                p95_latency_ms=0,
                p99_latency_ms=0,
                std_latency_ms=0,
                min_latency_ms=0,
                max_latency_ms=0,
                errors=errors,
            )

        latencies = [r.latency_ms for r in results]
        sorted_latencies = sorted(latencies)

        def percentile(data: List[float], p: float) -> float:
            idx = int(len(data) * p / 100)
            return data[min(idx, len(data) - 1)]

        # Aggregate accuracy metrics
        accuracy_at_k: Dict[str, float] = {}
        recall_at_k: Dict[str, float] = {}
        for k in [1, 3, 5, 10]:
            if k <= top_k:
                hits = [r.hit_at_k.get(k, False) for r in results if r.hit_at_k]
                recalls = [r.recall_at_k.get(k, 0) for r in results if r.recall_at_k]
                accuracy_at_k[f"k{k}"] = mean(hits) if hits else 0
                recall_at_k[f"k{k}"] = mean(recalls) if recalls else 0

        total_time_sec = sum(latencies) / 1000
        qps = len(results) / total_time_sec if total_time_sec > 0 else 0

        return BenchmarkResults(
            benchmark_id=benchmark_id,
            timestamp=timestamp,
            corpus_size=len(behaviors),
            sample_size=len(results),
            top_k=top_k,
            avg_latency_ms=mean(latencies),
            p50_latency_ms=percentile(sorted_latencies, 50),
            p95_latency_ms=percentile(sorted_latencies, 95),
            p99_latency_ms=percentile(sorted_latencies, 99),
            std_latency_ms=stdev(latencies) if len(latencies) > 1 else 0,
            min_latency_ms=min(latencies),
            max_latency_ms=max(latencies),
            accuracy_at_k=accuracy_at_k,
            recall_at_k=recall_at_k,
            queries_per_second=qps,
            embedding_model=self.embedding_model_name if use_embeddings else "keyword",
            errors=errors,
        )

    def save_results(self, results: BenchmarkResults) -> None:
        """Save benchmark results to database."""
        try:
            import psycopg2
        except ImportError:
            print("Warning: psycopg2 not installed, skipping database save")
            return

        if not self.dsn:
            print("Warning: No database DSN configured, skipping database save")
            return

        try:
            conn = psycopg2.connect(self.dsn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO behavior_benchmarks (
                        benchmark_id, run_date, corpus_size, sample_size,
                        avg_retrieval_latency_ms, p95_retrieval_latency_ms, p99_retrieval_latency_ms,
                        accuracy_at_k, recall_at_k, actor_id, metadata, status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        results.benchmark_id,
                        results.timestamp,
                        results.corpus_size,
                        results.sample_size,
                        results.avg_latency_ms,
                        results.p95_latency_ms,
                        results.p99_latency_ms,
                        json.dumps(results.accuracy_at_k),
                        json.dumps(results.recall_at_k),
                        "benchmark_script",
                        json.dumps({
                            "embedding_model": results.embedding_model,
                            "queries_per_second": results.queries_per_second,
                            "min_latency_ms": results.min_latency_ms,
                            "max_latency_ms": results.max_latency_ms,
                            "errors": results.errors,
                        }),
                        "COMPLETED",
                    ),
                )
            conn.commit()
            conn.close()
            print(f"Results saved to database: {results.benchmark_id}")
        except Exception as e:
            print(f"Warning: Failed to save to database: {e}")


def main():
    parser = argparse.ArgumentParser(description="Benchmark behavior retrieval performance")
    parser.add_argument(
        "--sample-size",
        type=int,
        default=100,
        help="Number of queries to run (default: 100)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of results to retrieve per query (default: 5)",
    )
    parser.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--out-file",
        type=str,
        help="Output file path (optional)",
    )
    parser.add_argument(
        "--no-embeddings",
        action="store_true",
        help="Use keyword-based retrieval instead of embeddings",
    )
    parser.add_argument(
        "--save-to-db",
        action="store_true",
        help="Save results to database",
    )
    parser.add_argument(
        "--dsn",
        type=str,
        help="PostgreSQL DSN (overrides BEHAVIOR_PG_DSN env var)",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("Behavior Retrieval Benchmark")
    print("=" * 60)

    benchmark = BehaviorBenchmark(dsn=args.dsn)

    print(f"\nConfiguration:")
    print(f"  Sample size: {args.sample_size}")
    print(f"  Top-K: {args.top_k}")
    print(f"  Use embeddings: {not args.no_embeddings}")
    print(f"  Embedding model: {benchmark.embedding_model_name}")

    print("\nLoading behaviors...")
    behaviors = benchmark.load_behaviors()
    print(f"  Loaded {len(behaviors)} behaviors")

    print("\nRunning benchmark...")
    results = benchmark.run_benchmark(
        sample_size=args.sample_size,
        top_k=args.top_k,
        use_embeddings=not args.no_embeddings,
    )

    if args.save_to_db:
        benchmark.save_results(results)

    if args.output == "json":
        output = json.dumps(results.to_dict(), indent=2)
        if args.out_file:
            with open(args.out_file, "w") as f:
                f.write(output)
            print(f"\nResults written to: {args.out_file}")
        else:
            print(output)
    else:
        print("\n" + "=" * 60)
        print("RESULTS")
        print("=" * 60)
        print(f"\nBenchmark ID: {results.benchmark_id}")
        print(f"Timestamp: {results.timestamp}")
        print(f"Corpus Size: {results.corpus_size} behaviors")
        print(f"Sample Size: {results.sample_size} queries")
        print(f"\nLatency Metrics:")
        print(f"  Average: {results.avg_latency_ms:.2f} ms")
        print(f"  P50: {results.p50_latency_ms:.2f} ms")
        print(f"  P95: {results.p95_latency_ms:.2f} ms")
        print(f"  P99: {results.p99_latency_ms:.2f} ms")
        print(f"  Std Dev: {results.std_latency_ms:.2f} ms")
        print(f"  Min: {results.min_latency_ms:.2f} ms")
        print(f"  Max: {results.max_latency_ms:.2f} ms")
        print(f"  Queries/sec: {results.queries_per_second:.2f}")
        print(f"\nAccuracy Metrics (Accuracy@K):")
        for k, v in results.accuracy_at_k.items():
            print(f"  {k}: {v:.2%}")
        print(f"\nRecall Metrics (Recall@K):")
        for k, v in results.recall_at_k.items():
            print(f"  {k}: {v:.2%}")

        if results.errors:
            print(f"\nErrors ({len(results.errors)}):")
            for err in results.errors[:5]:
                print(f"  - {err}")
            if len(results.errors) > 5:
                print(f"  ... and {len(results.errors) - 5} more")

        if args.out_file:
            with open(args.out_file, "w") as f:
                json.dump(results.to_dict(), f, indent=2)
            print(f"\nResults also written to: {args.out_file}")

    # Exit with error code if benchmark had issues
    if results.errors and len(results.errors) > results.sample_size * 0.1:
        sys.exit(1)


if __name__ == "__main__":
    main()
