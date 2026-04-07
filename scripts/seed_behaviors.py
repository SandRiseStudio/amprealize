#!/usr/bin/env python
"""Seed database with test behaviors for load testing."""

import sys
sys.path.insert(0, '.')

from amprealize.behavior_service import (
    BehaviorService,
    CreateBehaviorDraftRequest,
    ApproveBehaviorRequest,
    Actor,
)

def seed_behaviors(count: int = 10):
    """Seed database with test behaviors."""
    service = BehaviorService()
    actor = Actor(id='test-user', role='ENGINEER', surface='API')

    print(f"Seeding {count} test behaviors...")

    for i in range(count):
        # Create draft
        req = CreateBehaviorDraftRequest(
            name=f'test_behavior_{i:03d}',
            description=f'Test behavior {i} for load testing performance benchmarks',
            instruction=f'Execute test procedure {i} with detailed steps and validation',
            trigger_keywords=[f'test{i}', 'load', 'performance', 'benchmark'],
            tags=['test', 'performance', f'batch{i//3}', f'priority{i%3}'],
            examples=[
                {'input': f'test case {i}', 'output': f'expected result {i}'},
                {'input': f'edge case {i}', 'output': f'fallback {i}'},
            ],
            role_focus='ENGINEER',
            metadata={
                'test_id': i,
                'batch': i//3,
                'priority': i % 3,
                'complexity': 'medium',
            },
        )

        result = service.create_draft(req, actor)
        behavior_id = result['behavior']['behavior_id']
        version = result['version']['version']

        # Approve it to make it active
        approve_req = ApproveBehaviorRequest(
            behavior_id=behavior_id,
            version=version,
        )
        service.approve_draft(approve_req, actor)

        print(f"  ✓ Created and approved test_behavior_{i:03d} ({behavior_id})")

    print(f"\n✅ Successfully seeded {count} behaviors")

    # Verify
    behaviors = service.list_behaviors(status='APPROVED')
    print(f"📊 Total APPROVED behaviors in database: {len(behaviors)}")

if __name__ == '__main__':
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    seed_behaviors(count)
