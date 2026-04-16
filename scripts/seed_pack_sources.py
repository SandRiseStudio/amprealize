#!/usr/bin/env python3
"""Seed the knowledge-pack source registry with the core project files.

Run once (or idempotently) to populate ``knowledge_pack_sources`` so that
``amprealize knowledge-pack build`` has something to work with.

Usage:
    python scripts/seed_pack_sources.py          # default — register all
    python scripts/seed_pack_sources.py --dry-run # preview only
"""
from __future__ import annotations

import argparse
import os
import sys

# Ensure repo root is on sys.path so imports work from the scripts/ dir.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

from amprealize.knowledge_pack.source_registry import (  # noqa: E402
    RegisterSourceRequest,
    SourceRegistryService,
)


# ---------------------------------------------------------------------------
# Source definitions
# ---------------------------------------------------------------------------
# Each tuple: (source_type, ref, scope, owner)

CORE_SOURCES = [
    # ── Handbook (top-level) ──────────────────────────────────────────────
    ("file", "AGENTS.md", "canonical", "platform"),
    # ── Agent playbooks ───────────────────────────────────────────────────
    ("file", "amprealize/agents/playbooks/AGENT_ACCESSIBILITY.md", "canonical", "platform"),
    ("file", "amprealize/agents/playbooks/AGENT_AI_RESEARCH.md", "canonical", "platform"),
    ("file", "amprealize/agents/playbooks/AGENT_APP_STORE_SCREENSHOTS.md", "canonical", "platform"),
    ("file", "amprealize/agents/playbooks/AGENT_ARCHITECT.md", "canonical", "platform"),
    ("file", "amprealize/agents/playbooks/AGENT_BRAINSTORM.md", "canonical", "platform"),
    ("file", "amprealize/agents/playbooks/AGENT_COMPLIANCE.md", "canonical", "platform"),
    ("file", "amprealize/agents/playbooks/AGENT_COPYWRITING.md", "canonical", "platform"),
    ("file", "amprealize/agents/playbooks/AGENT_DATA_SCIENCE.md", "canonical", "platform"),
    ("file", "amprealize/agents/playbooks/AGENT_DEVOPS.md", "canonical", "platform"),
    ("file", "amprealize/agents/playbooks/AGENT_DX.md", "canonical", "platform"),
    ("file", "amprealize/agents/playbooks/AGENT_ENGINEERING.md", "canonical", "platform"),
    ("file", "amprealize/agents/playbooks/AGENT_FINANCE.md", "canonical", "platform"),
    ("file", "amprealize/agents/playbooks/AGENT_GTM.md", "canonical", "platform"),
    ("file", "amprealize/agents/playbooks/AGENT_NEW_FEATURE.md", "canonical", "platform"),
    ("file", "amprealize/agents/playbooks/AGENT_PRODUCT.md", "canonical", "platform"),
    ("file", "amprealize/agents/playbooks/AGENT_SECURITY.md", "canonical", "platform"),
    ("file", "amprealize/agents/playbooks/AGENT_WORK_ITEM_PLANNER.md", "canonical", "platform"),
    # ── Templates ─────────────────────────────────────────────────────────
    ("file", "amprealize/agents/templates/BRAINSTORM_SESSION_TEMPLATE.md", "canonical", "platform"),
    ("file", "amprealize/agents/templates/FEATURE_DEFINITION_TEMPLATE.md", "canonical", "platform"),
    # ── Work-item planner inject ──────────────────────────────────────────
    ("file", "amprealize/agents/work_item_planner/GWS_INJECT.md", "canonical", "platform"),
    # ── Platform wiki pages ───────────────────────────────────────────────
    ("file", "wiki/platform/reference/context-system.md", "runtime", "platform"),
    ("file", "wiki/platform/reference/surfaces.md", "runtime", "platform"),
    ("file", "wiki/platform/reference/editions.md", "runtime", "platform"),
    ("file", "wiki/platform/reference/mcp-tools.md", "runtime", "platform"),
    ("file", "wiki/platform/reference/agent-handbook.md", "runtime", "platform"),
    ("file", "wiki/platform/howto/getting-started.md", "runtime", "platform"),
    ("file", "wiki/platform/howto/environment-setup.md", "runtime", "platform"),
    ("file", "wiki/platform/howto/run-tests.md", "runtime", "platform"),
    ("file", "wiki/platform/howto/knowledge-packs.md", "runtime", "platform"),
    ("file", "wiki/platform/architecture/service-map.md", "runtime", "platform"),
    ("file", "wiki/platform/architecture/behavior-system.md", "runtime", "platform"),
]


def _already_registered(registry: SourceRegistryService) -> set[str]:
    """Return the set of ``ref`` values already in the registry."""
    return {s.ref for s in registry.list_sources()}


def _resolve_dsn() -> str:
    """Resolve the Postgres DSN from the active amprealize context."""
    from amprealize.context import get_current_context

    name, cfg = get_current_context()
    dsn = cfg.storage.postgres.dsn
    print(f"  Context: {name}  →  {dsn.split('@')[-1] if '@' in dsn else dsn}")
    return dsn


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed knowledge-pack sources")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be registered without persisting",
    )
    args = parser.parse_args()

    dsn = _resolve_dsn()
    registry = SourceRegistryService(dsn=dsn)
    existing = _already_registered(registry)

    registered, skipped = 0, 0
    for source_type, ref, scope, owner in CORE_SOURCES:
        if ref in existing:
            print(f"  SKIP  {ref}  (already registered)")
            skipped += 1
            continue

        if args.dry_run:
            print(f"  [DRY] {ref}")
            registered += 1
            continue

        request = RegisterSourceRequest(
            source_type=source_type,
            ref=ref,
            scope=scope,
            owner=owner,
        )
        record = registry.register_source(request)
        print(f"  ✅ {record.source_id}  {ref}")
        registered += 1

    print(f"\nDone — registered: {registered}, skipped: {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
