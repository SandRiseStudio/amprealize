#!/usr/bin/env python3
"""Seed test behaviors for dual-write testing.

Creates a few approved behaviors with embeddings for testing Phase 1 pgvector migration.
"""

import os
import sys
import numpy as np
from pathlib import Path

# Add amprealize to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from amprealize.behavior_service import BehaviorService, CreateBehaviorDraftRequest, ApproveBehaviorRequest, Actor
from amprealize.action_contracts import utc_now_iso

def generate_mock_embedding(dim: int = 1024) -> list[float]:
    """Generate a normalized mock embedding."""
    vec = np.random.randn(dim).astype(np.float32)
    vec = vec / np.linalg.norm(vec)  # L2 normalize
    return vec.tolist()

def main():
    """Seed test behaviors."""
    print("=" * 80)
    print("Seeding Test Behaviors for Dual-Write Testing")
    print("=" * 80)

    behavior_dsn = os.getenv(
        "AMPREALIZE_BEHAVIOR_PG_DSN",
        "postgresql://amprealize_behavior:dev_behavior_pass@localhost:6433/behaviors"
    )

    print(f"\nInitializing BehaviorService")
    print(f"DSN: {behavior_dsn}")
    service = BehaviorService(dsn=behavior_dsn)

    # System actor for automated seeding
    actor = Actor(
        id="system",
        role="system",
        surface="cli",
    )

    test_behaviors = [
        {
            "name": "behavior_test_retrieval_1",
            "description": "Test behavior for pgvector retrieval validation",
            "instruction": "Validate semantic search works correctly with PostgreSQL backend",
            "role_focus": ["strategist", "teacher"],
            "tags": ["test", "retrieval", "pgvector"],
            "trigger_keywords": ["test", "pgvector", "retrieval"],
            "citation_label": "TEST-001",
        },
        {
            "name": "behavior_test_retrieval_2",
            "description": "Second test behavior for dual-write mode",
            "instruction": "Ensure embeddings persist to both filesystem and PostgreSQL",
            "role_focus": ["teacher", "student"],
            "tags": ["test", "dual-write", "migration"],
            "trigger_keywords": ["dual-write", "migration", "consistency"],
            "citation_label": "TEST-002",
        },
        {
            "name": "behavior_test_retrieval_3",
            "description": "Third test behavior for IVFFlat index validation",
            "instruction": "Verify cosine similarity search returns correct neighbors",
            "role_focus": ["student"],
            "tags": ["test", "ivfflat", "similarity"],
            "trigger_keywords": ["ivfflat", "cosine", "neighbors"],
            "citation_label": "TEST-003",
        },
    ]

    created_count = 0

    for i, beh_data in enumerate(test_behaviors, 1):
        print(f"\n{i}. Creating behavior: {beh_data['name']}")

        # Generate mock embedding (1024-dim, L2-normalized)
        embedding = generate_mock_embedding(1024)

        # Create draft
        draft_request = CreateBehaviorDraftRequest(
            name=beh_data["name"],
            description=beh_data["description"],
            instruction=beh_data["instruction"],
            role_focus=beh_data["role_focus"],
            tags=beh_data["tags"],
            trigger_keywords=beh_data["trigger_keywords"],
            embedding=embedding,
        )

        try:
            draft = service.create_behavior_draft(draft_request, actor)
            print(f"   ✅ Draft created: {draft.behavior_id} v{draft.version}")

            # Approve immediately
            approve_request = ApproveBehaviorRequest(
                behavior_id=draft.behavior_id,
                version=draft.version,
                effective_from=utc_now_iso(),
            )
            approved = service.approve_behavior(approve_request, actor)
            print(f"   ✅ Approved: {approved.behavior_id} v{approved.version}")
            created_count += 1

        except Exception as e:
            print(f"   ⚠️  Draft creation failed (may already exist): {e}")
            # Try to find and approve existing draft
            try:
                # Query for existing behavior with this name
                with service._pool.connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            SELECT bv.behavior_id, bv.version
                            FROM behaviors b
                            JOIN behavior_versions bv ON b.behavior_id = bv.behavior_id
                            WHERE b.name = %s AND bv.status = 'DRAFT'
                            LIMIT 1
                            """,
                            (beh_data["name"],)
                        )
                        result = cur.fetchone()

                if result:
                    behavior_id, version = result
                    print(f"   Found existing draft: {behavior_id} v{version}")
                    approve_request = ApproveBehaviorRequest(
                        behavior_id=behavior_id,
                        version=version,
                        effective_from=utc_now_iso(),
                    )
                    approved = service.approve_behavior(approve_request, actor)
                    print(f"   ✅ Approved: {approved.behavior_id} v{approved.version}")
                    created_count += 1
                else:
                    print(f"   ❌ No draft found to approve")
            except Exception as e2:
                print(f"   ❌ Approval failed: {e2}")

    print(f"\n" + "=" * 80)
    print(f"✅ Seeded {created_count} / {len(test_behaviors)} test behaviors")
    print("=" * 80)
    print(f"\nNext: Run test_dual_write.py to validate Phase 1 dual-write mode")
    return 0

if __name__ == "__main__":
    sys.exit(main())
