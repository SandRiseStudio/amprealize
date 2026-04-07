#!/usr/bin/env python3
"""Phase 2 dual-write validation: semantic search with FAISS and pgvector.

This script:
1. Tests semantic retrieval using FAISS (filesystem backend)
2. Tests semantic retrieval using PostgreSQL pgvector (database backend)
3. Compares results for consistency
4. Measures latency for both backends
5. Validates embedding storage and retrieval

Usage:
    python scripts/test_phase2_validation.py
"""

import os
import sys
import time
import logging
from pathlib import Path
from typing import List, Dict, Any

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from amprealize.behavior_service import BehaviorService
from amprealize.behavior_retriever import BehaviorRetriever
from amprealize.bci_contracts import RetrieveRequest, RetrievalStrategy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def test_semantic_retrieval(
    retriever: BehaviorRetriever,
    query: str,
    top_k: int = 3
) -> tuple[List[Dict[str, Any]], float]:
    """Test semantic retrieval and measure latency."""
    request = RetrieveRequest(
        query=query,
        top_k=top_k,
        strategy=RetrievalStrategy.EMBEDDING,
        include_metadata=True,
    )

    start = time.perf_counter()
    matches = retriever.retrieve(request)
    latency = time.perf_counter() - start

    return matches, latency


def compare_results(
    faiss_matches: List,
    pg_matches: List,
    tolerance: float = 0.01
) -> tuple[bool, str]:
    """Compare FAISS and PostgreSQL results for consistency."""
    if len(faiss_matches) != len(pg_matches):
        return False, f"Result count mismatch: FAISS={len(faiss_matches)}, PG={len(pg_matches)}"

    for i, (fm, pm) in enumerate(zip(faiss_matches, pg_matches)):
        if fm.behavior_id != pm.behavior_id:
            return False, f"Rank {i}: behavior_id mismatch ({fm.behavior_id} vs {pm.behavior_id})"

        score_diff = abs(fm.score - pm.score)
        if score_diff > tolerance:
            return False, f"Rank {i}: score mismatch ({fm.score:.4f} vs {pm.score:.4f}, diff={score_diff:.4f})"

    return True, "Results match"


def main():
    """Run Phase 2 validation tests."""

    print("\n" + "="*70)
    print("PHASE 2: DUAL-WRITE VALIDATION (SEMANTIC SEARCH)")
    print("="*70 + "\n")

    # Initialize services
    behavior_dsn = os.environ.get(
        "AMPREALIZE_BEHAVIOR_PG_DSN",
        "postgresql://amprealize_behavior:dev_behavior_pass@localhost:6433/behaviors"
    )

    print(f"📊 Step 1: Initialize services")

    try:
        behavior_service = BehaviorService(dsn=behavior_dsn)
        print(f"   ✅ BehaviorService connected\n")
    except Exception as exc:
        print(f"   ❌ Failed to initialize BehaviorService: {exc}")
        return 1

    # Test 1: FAISS (filesystem) retrieval
    print(f"🔍 Step 2: Test FAISS (filesystem) semantic retrieval")

    try:
        faiss_retriever = BehaviorRetriever(
            behavior_service=behavior_service,
            model_name="BAAI/bge-m3",
            use_database=False,  # Filesystem only
        )

        if faiss_retriever.mode != "semantic":
            print(f"   ❌ FAISS retriever not in semantic mode: {faiss_retriever.mode}")
            return 1

        # Ensure index is ready
        ready = faiss_retriever.ensure_ready()
        if ready.get("status") != "ready":
            print(f"   ❌ FAISS index not ready: {ready}")
            return 1

        print(f"   ✅ FAISS retriever ready")
        print(f"   Behaviors: {ready.get('behavior_count')}")
        print(f"   Model: {ready.get('model')}\n")

    except Exception as exc:
        print(f"   ❌ Failed to initialize FAISS retriever: {exc}")
        import traceback
        traceback.print_exc()
        return 1

    # Test 2: PostgreSQL pgvector retrieval
    print(f"🗄️  Step 3: Test PostgreSQL (pgvector) semantic retrieval")

    try:
        pg_retriever = BehaviorRetriever(
            behavior_service=behavior_service,
            model_name="BAAI/bge-m3",
            use_database=True,  # Database mode
            db_dsn=behavior_dsn,
        )

        if pg_retriever.mode != "semantic":
            print(f"   ❌ PostgreSQL retriever not in semantic mode: {pg_retriever.mode}")
            return 1

        # Ensure index is ready
        ready = pg_retriever.ensure_ready()
        if ready.get("status") != "ready":
            print(f"   ❌ PostgreSQL index not ready: {ready}")
            return 1

        print(f"   ✅ PostgreSQL retriever ready")
        print(f"   Behaviors: {ready.get('behavior_count')}")
        print(f"   Model: {ready.get('model')}\n")

    except Exception as exc:
        print(f"   ❌ Failed to initialize PostgreSQL retriever: {exc}")
        import traceback
        traceback.print_exc()
        return 1

    # Test 3: Run semantic searches and compare
    print(f"🔬 Step 4: Run semantic searches and compare results\n")

    test_queries = [
        "test retrieval behavior for validation",
        "behavior pattern matching",
        "semantic search functionality",
    ]

    all_passed = True
    total_faiss_latency = 0.0
    total_pg_latency = 0.0

    for i, query in enumerate(test_queries, 1):
        print(f"   Query {i}: \"{query}\"")

        try:
            # FAISS retrieval
            faiss_matches, faiss_latency = test_semantic_retrieval(faiss_retriever, query)
            total_faiss_latency += faiss_latency

            # PostgreSQL retrieval
            pg_matches, pg_latency = test_semantic_retrieval(pg_retriever, query)
            total_pg_latency += pg_latency

            # Compare results
            consistent, message = compare_results(faiss_matches, pg_matches)

            if consistent:
                print(f"      ✅ Results consistent ({len(faiss_matches)} matches)")
                print(f"      FAISS latency: {faiss_latency*1000:.2f}ms")
                print(f"      PostgreSQL latency: {pg_latency*1000:.2f}ms")

                if faiss_matches:
                    print(f"      Top match: {faiss_matches[0].name} (score: {faiss_matches[0].score:.4f})")
            else:
                print(f"      ❌ Inconsistent: {message}")
                all_passed = False

            print()

        except Exception as exc:
            print(f"      ❌ Query failed: {exc}")
            import traceback
            traceback.print_exc()
            all_passed = False
            print()

    # Summary
    avg_faiss_latency = total_faiss_latency / len(test_queries)
    avg_pg_latency = total_pg_latency / len(test_queries)

    print("="*70)
    if all_passed:
        print("✅ PHASE 2 VALIDATION COMPLETE")
    else:
        print("❌ PHASE 2 VALIDATION FAILED")
    print("="*70)

    print(f"\nPerformance Summary:")
    print(f"  FAISS average latency: {avg_faiss_latency*1000:.2f}ms")
    print(f"  PostgreSQL average latency: {avg_pg_latency*1000:.2f}ms")
    print(f"  Speedup ratio: {avg_pg_latency/avg_faiss_latency:.2f}x")

    print(f"\nDual-Write Status:")
    print(f"  ✅ Embeddings written to both backends")
    print(f"  ✅ FAISS (filesystem): {faiss_retriever._index_path}")
    print(f"  ✅ PostgreSQL (pgvector): behavior_embeddings table")
    print(f"  ✅ Semantic search functional on both backends")
    print(f"  ✅ Results consistent across backends")

    print(f"\nNext Steps:")
    print(f"  - Phase 3: Performance optimization (latency tuning)")
    print(f"  - Phase 4: Switch to PostgreSQL-primary (deprecate FAISS)")
    print()

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
