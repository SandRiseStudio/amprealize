#!/usr/bin/env python3
"""Populate embeddings for Phase 2 dual-write validation.

This script:
1. Initializes BehaviorRetriever with semantic model (sentence-transformers)
2. Builds FAISS index from approved behaviors
3. Writes embeddings to both filesystem and PostgreSQL (dual-write mode)
4. Validates embedding storage in both backends

Usage:
    python scripts/populate_embeddings.py
"""

import os
import sys
import logging
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from amprealize.behavior_service import BehaviorService
from amprealize.behavior_retriever import BehaviorRetriever

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    """Build embeddings for approved behaviors and write to FAISS + PostgreSQL."""

    print("\n" + "="*70)
    print("PHASE 2: POPULATE EMBEDDINGS (DUAL-WRITE MODE)")
    print("="*70 + "\n")

    # Step 1: Initialize BehaviorService with PostgreSQL
    behavior_dsn = os.environ.get(
        "AMPREALIZE_BEHAVIOR_PG_DSN",
        "postgresql://amprealize_behavior:dev_behavior_pass@localhost:6433/behaviors"
    )

    print(f"📊 Step 1: Initialize BehaviorService")
    print(f"   DSN: {behavior_dsn}")

    try:
        behavior_service = BehaviorService(dsn=behavior_dsn)
        print("   ✅ BehaviorService connected\n")
    except Exception as exc:
        print(f"   ❌ Failed to initialize BehaviorService: {exc}")
        return 1

    # Step 2: Initialize BehaviorRetriever with use_database=True
    print(f"🔍 Step 2: Initialize BehaviorRetriever (dual-write mode)")
    print(f"   Model: BAAI/bge-m3")
    print(f"   Database mode: ENABLED")

    try:
        retriever = BehaviorRetriever(
            behavior_service=behavior_service,
            model_name="BAAI/bge-m3",
            use_database=True,
            db_dsn=behavior_dsn,
        )
        print(f"   ✅ BehaviorRetriever initialized")
        print(f"   Mode: {retriever.mode}\n")
    except Exception as exc:
        print(f"   ❌ Failed to initialize BehaviorRetriever: {exc}")
        return 1

    # Step 3: Check semantic dependencies
    if retriever.mode != "semantic":
        print(f"   ⚠️  Semantic mode unavailable (mode={retriever.mode})")
        print("   Install: pip install sentence-transformers faiss-cpu")
        return 1

    # Step 4: Build index (generates embeddings and writes to both backends)
    print(f"🏗️  Step 3: Build index and populate embeddings")

    try:
        result = retriever.build_index()

        if result.get("status") != "ready":
            print(f"   ⚠️  Index build returned non-ready status: {result}")
            return 1

        behavior_count = result.get("behavior_count", 0)
        model_name = result.get("model", "unknown")

        print(f"   ✅ Index built successfully")
        print(f"   Behavior count: {behavior_count}")
        print(f"   Model: {model_name}")
        print(f"   Status: {result.get('status')}\n")

        if behavior_count == 0:
            print("   ⚠️  No approved behaviors found to index")
            print("   Run: python scripts/seed_test_behaviors.py")
            return 1

    except Exception as exc:
        print(f"   ❌ Failed to build index: {exc}")
        import traceback
        traceback.print_exc()
        return 1

    # Step 5: Validate dual-write by checking database
    print(f"✅ Step 4: Validate embeddings in PostgreSQL")

    try:
        # Query behavior_embeddings table
        with behavior_service._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        behavior_id,
                        version,
                        name,
                        embedding_checksum,
                        model_name,
                        pg_typeof(embedding) as embedding_type
                    FROM behavior_embeddings
                    ORDER BY created_at DESC
                """)
                rows = cur.fetchall()

        if not rows:
            print(f"   ⚠️  No embeddings found in behavior_embeddings table")
            return 1

        print(f"   ✅ Found {len(rows)} embeddings in database:")
        for row in rows:
            behavior_id, version, name, checksum, model, emb_type = row
            print(f"      - {behavior_id} v{version}: {name}")
            print(f"        Checksum: {checksum[:16]}...")
            print(f"        Model: {model}")
            print(f"        Type: {emb_type}")

        print("\n" + "="*70)
        print("✅ PHASE 2 EMBEDDING POPULATION COMPLETE")
        print("="*70)
        print(f"\nEmbeddings written to:")
        print(f"  1. Filesystem (FAISS): {retriever._index_path}")
        print(f"  2. PostgreSQL (pgvector): behavior_embeddings table")
        print(f"\nNext: Run Phase 2 validation script")
        print(f"  python scripts/test_phase2_validation.py\n")

        return 0

    except Exception as exc:
        print(f"   ❌ Failed to validate database embeddings: {exc}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
