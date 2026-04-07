#!/usr/bin/env python
"""Seed the behavior store with behaviors parsed from AGENTS.md.

This script extracts behavior definitions from the AGENTS.md handbook and
populates the BehaviorService database for BCI (Behavior-Conditioned Inference).

Usage:
    python scripts/seed_behaviors_from_agents_md.py
    python scripts/seed_behaviors_from_agents_md.py --dry-run  # Preview without writing

Behaviors: behavior_curate_behavior_handbook
"""

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any

# Add repo root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from amprealize.behavior_service import (
    BehaviorService,
    CreateBehaviorDraftRequest,
    ApproveBehaviorRequest,
    Actor,
)


def parse_behaviors_from_agents_md(agents_md_path: Path) -> List[Dict[str, Any]]:
    """Parse behavior definitions from AGENTS.md.

    Behaviors are defined in the format:
    ### `behavior_name`
    - **When**: <trigger conditions>
    - **Steps**:
      1. Step one
      2. Step two
      ...
    """
    content = agents_md_path.read_text()

    # Pattern to match behavior blocks
    # Matches: ### `behavior_name` followed by content until next ### or ---
    behavior_pattern = re.compile(
        r'### `(behavior_\w+)`\s*\n'
        r'- \*\*When\*\*:\s*(.+?)\n'
        r'- \*\*Steps\*\*:\s*\n'
        r'((?:\s+\d+\.\s+.+?\n)+)',
        re.MULTILINE
    )

    behaviors = []

    for match in behavior_pattern.finditer(content):
        name = match.group(1)
        when_clause = match.group(2).strip()
        steps_raw = match.group(3)

        # Parse steps
        steps = []
        for step_match in re.finditer(r'\d+\.\s+(.+?)(?=\n\s+\d+\.|\n\n|\Z)', steps_raw, re.DOTALL):
            step_text = step_match.group(1).strip()
            # Clean up multi-line steps
            step_text = re.sub(r'\s+', ' ', step_text)
            steps.append(step_text)

        # Extract keywords from name and when clause
        keywords = extract_keywords(name, when_clause)

        # Determine role focus based on behavior name
        role_focus = determine_role_focus(name)

        # Build instruction from steps
        instruction = "Steps:\n" + "\n".join(f"{i+1}. {step}" for i, step in enumerate(steps))

        behaviors.append({
            'name': name,
            'description': f"Trigger: {when_clause}",
            'instruction': instruction,
            'trigger_keywords': keywords,
            'role_focus': role_focus,
            'tags': extract_tags(name),
            'metadata': {
                'source': 'AGENTS.md',
                'when_clause': when_clause,
                'step_count': len(steps),
            }
        })

    return behaviors


def extract_keywords(name: str, when_clause: str) -> List[str]:
    """Extract trigger keywords from behavior name and when clause."""
    keywords = set()

    # Extract from behavior name (e.g., behavior_use_raze_for_logging -> raze, logging)
    name_parts = name.replace('behavior_', '').split('_')
    keywords.update(p for p in name_parts if len(p) > 2)

    # Extract significant words from when clause
    stopwords = {'when', 'the', 'a', 'an', 'or', 'and', 'for', 'to', 'in', 'on', 'with', 'is', 'are', 'any'}
    when_words = re.findall(r'\b\w+\b', when_clause.lower())
    keywords.update(w for w in when_words if len(w) > 3 and w not in stopwords)

    return list(keywords)[:15]  # Limit to 15 keywords


def extract_tags(name: str) -> List[str]:
    """Extract category tags from behavior name."""
    tags = ['handbook', 'agents-md']

    # Category mapping based on behavior name patterns
    if any(x in name for x in ['logging', 'raze', 'telemetry', 'metrics']):
        tags.append('observability')
    if any(x in name for x in ['secret', 'credential', 'security', 'auth', 'cors']):
        tags.append('security')
    if any(x in name for x in ['storage', 'database', 'postgres', 'migration']):
        tags.append('storage')
    if any(x in name for x in ['cli', 'api', 'mcp', 'service']):
        tags.append('integration')
    if any(x in name for x in ['doc', 'update', 'readme']):
        tags.append('documentation')
    if any(x in name for x in ['test', 'validate', 'compliance']):
        tags.append('quality')
    if any(x in name for x in ['environment', 'breakeramp', 'container', 'docker']):
        tags.append('infrastructure')
    if any(x in name for x in ['git', 'branch', 'merge', 'cicd']):
        tags.append('devops')
    if any(x in name for x in ['config', 'externalize', 'setting']):
        tags.append('configuration')

    return tags


def determine_role_focus(name: str) -> str:
    """Determine the primary role focus for a behavior."""
    # Map behavior patterns to roles
    if any(x in name for x in ['security', 'secret', 'credential', 'auth', 'cors']):
        return 'SECURITY'
    if any(x in name for x in ['doc', 'readme', 'update_docs']):
        return 'COPYWRITING'
    if any(x in name for x in ['financial', 'budget', 'roi']):
        return 'FINANCE'
    if any(x in name for x in ['gtm', 'go_to_market', 'launch']):
        return 'GTM'
    if any(x in name for x in ['accessibility', 'wcag']):
        return 'ACCESSIBILITY'
    if any(x in name for x in ['compliance', 'audit']):
        return 'COMPLIANCE'
    if any(x in name for x in ['cicd', 'deploy', 'pipeline']):
        return 'DEVOPS'
    # Default to ENGINEER for most technical behaviors
    return 'ENGINEER'


def seed_behaviors(behaviors: List[Dict[str, Any]], dry_run: bool = False) -> None:
    """Seed behaviors into the BehaviorService database."""
    if dry_run:
        print("\n🔍 DRY RUN - No changes will be made\n")
        for b in behaviors:
            print(f"  Would create: {b['name']}")
            print(f"    Description: {b['description'][:80]}...")
            print(f"    Keywords: {', '.join(b['trigger_keywords'][:5])}...")
            print(f"    Role: {b['role_focus']}")
            print(f"    Tags: {', '.join(b['tags'])}")
            print()
        print(f"Total: {len(behaviors)} behaviors")
        return

    service = BehaviorService()
    actor = Actor(id='seed-script', role='ENGINEER', surface='CLI')

    created = 0
    skipped = 0
    errors = 0

    print(f"\n📝 Seeding {len(behaviors)} behaviors from AGENTS.md...\n")

    for b in behaviors:
        try:
            # Check if behavior already exists
            existing = service.list_behaviors(status='APPROVED')
            if any(eb['behavior'].get('name') == b['name'] for eb in existing):
                print(f"  ⏭️  Skipped (exists): {b['name']}")
                skipped += 1
                continue

            # Create draft
            req = CreateBehaviorDraftRequest(
                name=b['name'],
                description=b['description'],
                instruction=b['instruction'],
                trigger_keywords=b['trigger_keywords'],
                tags=b['tags'],
                role_focus=b['role_focus'],
                metadata=b['metadata'],
                examples=[],
            )

            result = service.create_behavior_draft(req, actor)
            behavior_id = result.behavior_id
            version = result.version

            # Auto-approve (these are from the canonical handbook)
            approve_req = ApproveBehaviorRequest(
                behavior_id=behavior_id,
                version=version,
                effective_from=datetime.now(timezone.utc).isoformat(),
            )
            service.approve_behavior(approve_req, actor)

            print(f"  ✓ Created: {b['name']} ({behavior_id})")
            created += 1

        except Exception as e:
            print(f"  ✗ Error creating {b['name']}: {e}")
            errors += 1

    print(f"\n{'='*60}")
    print(f"✅ Seeding complete!")
    print(f"   Created: {created}")
    print(f"   Skipped: {skipped}")
    print(f"   Errors:  {errors}")

    # Verify
    all_behaviors = service.list_behaviors(status='APPROVED')
    print(f"\n📊 Total APPROVED behaviors in database: {len(all_behaviors)}")


def main():
    parser = argparse.ArgumentParser(
        description='Seed behavior store from AGENTS.md'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview behaviors without writing to database'
    )
    parser.add_argument(
        '--agents-md',
        type=Path,
        default=Path(__file__).parent.parent / 'AGENTS.md',
        help='Path to AGENTS.md file'
    )
    args = parser.parse_args()

    if not args.agents_md.exists():
        print(f"❌ AGENTS.md not found at {args.agents_md}")
        sys.exit(1)

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("     Seed Behaviors from AGENTS.md")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    print(f"\n📖 Parsing behaviors from: {args.agents_md}")
    behaviors = parse_behaviors_from_agents_md(args.agents_md)
    print(f"   Found {len(behaviors)} behavior definitions")

    seed_behaviors(behaviors, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
