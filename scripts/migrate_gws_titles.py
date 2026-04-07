#!/usr/bin/env python3
"""Migrate work item titles to GWS v1.0 compliance.

Transforms non-compliant titles by stripping organizational prefixes
(coded-section, phase, track, bracket-type) and extracting them into labels.

Usage:
    # Dry-run from MCP JSON export:
    python scripts/migrate_gws_titles.py --input data/work_items.json

    # Dry-run from PostgreSQL:
    python scripts/migrate_gws_titles.py --dsn postgresql://user:pass@host/db --project-id proj-xxx

    # Apply to PostgreSQL:
    python scripts/migrate_gws_titles.py --dsn postgresql://user:pass@host/db --project-id proj-xxx --apply
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Title transformation patterns
# ---------------------------------------------------------------------------

# Phase prefix: Phase 1:, Phase 2 —
PHASE_RE = re.compile(r"^Phase\s*(\d+)\s*[:\-–—]\s*", re.IGNORECASE)

# Track prefix: Track A —, Track B:
TRACK_RE = re.compile(r"^Track\s*([A-Za-z\d]+)\s*[:\-–—]\s*", re.IGNORECASE)

# Coded-section: A1:, S1.1 —, T1.1.1 —, A1-T1:, E1 —
CODED_SECTION_RE = re.compile(
    r"^([A-Z]\d+(?:[.\-][A-Z]?\d+)*)\s*[:\-–—]\s*"
)

# Bracket prefix: [Bug], [Feature], [WIP]
BRACKET_RE = re.compile(r"^\[([^\]]+)\]\s*")


def compute_transformation(
    item_id: str,
    title: str,
    item_type: str,
    existing_labels: List[str],
) -> Optional[Dict[str, Any]]:
    """Compute title transformation and label extraction.

    Returns None if no transformation needed, or a dict with:
    - new_title: the cleaned title
    - merged_labels: full label list (existing + new)
    - add_labels: only the new labels being added
    - rule: which rule was applied
    """
    new_title: Optional[str] = None
    add_labels: List[str] = []
    rule: Optional[str] = None

    # 1. Phase prefix (most specific word match — check first)
    m = PHASE_RE.match(title)
    if m:
        new_title = title[m.end():]
        add_labels = [f"phase:{m.group(1)}"]
        rule = "phase_prefix"

    # 2. Track prefix
    if not rule:
        m = TRACK_RE.match(title)
        if m:
            new_title = title[m.end():]
            add_labels = [f"track:{m.group(1).lower()}"]
            rule = "track_prefix"

    # 3. Coded-section prefix (A1:, S1.1—, E1—, etc.)
    if not rule:
        m = CODED_SECTION_RE.match(title)
        if m:
            new_title = title[m.end():]
            section_id = m.group(1).lower()
            # E-prefix items are epochs
            if re.match(r"^e\d+$", section_id):
                add_labels = [f"epoch:{section_id}"]
            else:
                add_labels = [f"section:{section_id}"]
            rule = "coded_section"

    # 4. Bracket prefix
    if not rule:
        m = BRACKET_RE.match(title)
        if m:
            new_title = title[m.end():]
            add_labels = []  # bracket type is redundant with item_type
            rule = "bracket_prefix"

    if not rule or not new_title:
        return None

    # Ensure first character is uppercase after stripping
    if new_title and not new_title[0].isupper():
        new_title = new_title[0].upper() + new_title[1:]

    # Check minimum length (5 for goal/feature/bug, 3 for task)
    min_len = 3 if item_type == "task" else 5
    if len(new_title) < min_len:
        return {
            "item_id": item_id,
            "old_title": title,
            "new_title": new_title,
            "add_labels": add_labels,
            "merged_labels": existing_labels + add_labels,
            "rule": rule,
            "status": "MANUAL_REVIEW",
            "reason": f"Title too short after stripping ({len(new_title)} < {min_len})",
        }

    # Merge labels (avoid duplicates)
    merged = list(existing_labels)
    for lbl in add_labels:
        if lbl not in merged:
            merged.append(lbl)

    return {
        "item_id": item_id,
        "old_title": title,
        "new_title": new_title,
        "add_labels": add_labels,
        "merged_labels": merged,
        "rule": rule,
        "status": "OK",
    }


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_from_json(path: Path) -> List[Dict[str, Any]]:
    """Load work items from an MCP JSON export."""
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("items", data) if isinstance(data, dict) else data
    return [
        {
            "item_id": it["item_id"],
            "title": it["title"],
            "item_type": (it.get("item_type") or "task").lower(),
            "labels": it.get("labels") or [],
            "display_id": it.get("display_id"),
        }
        for it in items
    ]


def load_from_postgres(dsn: str, project_id: str) -> List[Dict[str, Any]]:
    """Load work items directly from PostgreSQL."""
    try:
        import psycopg2
    except ImportError:
        print("❌ psycopg2 not installed. Install with: pip install psycopg2-binary", file=sys.stderr)
        sys.exit(1)

    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, title, item_type, labels, display_number
                FROM board.work_items
                WHERE project_id = %s
                ORDER BY display_number NULLS LAST
                """,
                (project_id,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    items = []
    for row in rows:
        item_id, title, item_type, labels, display_number = row
        # labels column is text[] in postgres
        if labels is None:
            labels = []
        items.append({
            "item_id": str(item_id),
            "title": title,
            "item_type": (item_type or "task").lower(),
            "labels": list(labels),
            "display_id": f"amprealize-{display_number}" if display_number else None,
        })
    return items


# ---------------------------------------------------------------------------
# Apply changes
# ---------------------------------------------------------------------------


def apply_to_postgres(dsn: str, changes: List[Dict[str, Any]]) -> int:
    """Apply title/label changes directly to PostgreSQL."""
    try:
        import psycopg2
    except ImportError:
        print("❌ psycopg2 not installed.", file=sys.stderr)
        sys.exit(1)

    actionable = [c for c in changes if c["status"] == "OK"]
    if not actionable:
        print("No actionable changes to apply.")
        return 0

    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            for change in actionable:
                cur.execute(
                    """
                    UPDATE board.work_items
                    SET title = %s, labels = %s, updated_at = %s
                    WHERE id = %s::uuid
                    """,
                    (
                        change["new_title"],
                        change["merged_labels"],
                        datetime.now(timezone.utc),
                        change["item_id"],
                    ),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return len(actionable)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_report(changes: List[Dict[str, Any]]) -> None:
    """Print a human-readable migration report."""
    if not changes:
        print("\n✅ No GWS title violations found. All items are compliant.")
        return

    ok = [c for c in changes if c["status"] == "OK"]
    manual = [c for c in changes if c["status"] == "MANUAL_REVIEW"]

    print(f"\n{'='*72}")
    print(f"GWS Title Migration Report — {len(changes)} items to transform")
    print(f"{'='*72}")

    # Breakdown by rule
    rules: Dict[str, int] = {}
    for c in changes:
        rules[c["rule"]] = rules.get(c["rule"], 0) + 1
    print("\nBy rule:")
    for rule, count in sorted(rules.items()):
        print(f"  {rule}: {count}")

    print(f"\n{'─'*72}")
    print("Transformations:")
    print(f"{'─'*72}")
    for c in ok:
        did = c.get("display_id", c["item_id"][:12])
        labels_str = f" +labels={c['add_labels']}" if c["add_labels"] else ""
        print(f"  [{c['rule']}] {did}")
        print(f"    OLD: {c['old_title']}")
        print(f"    NEW: {c['new_title']}{labels_str}")

    if manual:
        print(f"\n{'─'*72}")
        print("⚠️  Manual review required:")
        print(f"{'─'*72}")
        for c in manual:
            did = c.get("display_id", c["item_id"][:12])
            print(f"  {did}: {c['old_title']}")
            print(f"    Reason: {c.get('reason', 'unknown')}")

    print(f"\n{'='*72}")
    print(f"Summary: {len(ok)} auto-fixable, {len(manual)} need manual review")
    print(f"{'='*72}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate work item titles to GWS v1.0 compliance"
    )
    parser.add_argument("--input", type=Path, help="Path to MCP JSON export file")
    parser.add_argument("--dsn", help="PostgreSQL connection string")
    parser.add_argument("--project-id", help="Project ID (required with --dsn)")
    parser.add_argument(
        "--apply", action="store_true",
        help="Apply changes to database (default is dry-run)",
    )
    parser.add_argument(
        "--output", type=Path,
        help="Write change manifest to JSON file",
    )
    args = parser.parse_args()

    # Load items
    if args.input:
        items = load_from_json(args.input)
        print(f"Loaded {len(items)} items from {args.input}")
    elif args.dsn:
        if not args.project_id:
            parser.error("--project-id is required when using --dsn")
        items = load_from_postgres(args.dsn, args.project_id)
        print(f"Loaded {len(items)} items from PostgreSQL")
    else:
        parser.error("Either --input or --dsn is required")

    # Compute transformations
    changes: List[Dict[str, Any]] = []
    for item in items:
        result = compute_transformation(
            item_id=item["item_id"],
            title=item["title"],
            item_type=item["item_type"],
            existing_labels=item["labels"],
        )
        if result:
            result["display_id"] = item.get("display_id")
            changes.append(result)

    # Report
    print_report(changes)

    # Write manifest
    if args.output:
        args.output.write_text(json.dumps(changes, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nManifest written to {args.output}")

    # Apply
    if args.apply:
        if not args.dsn:
            print("\n❌ --apply requires --dsn for database connection", file=sys.stderr)
            sys.exit(1)
        ok_count = len([c for c in changes if c["status"] == "OK"])
        print(f"\n🔄 Applying {ok_count} changes...")
        applied = apply_to_postgres(args.dsn, changes)
        print(f"✅ Applied {applied} title migrations successfully.")
    elif changes:
        ok_count = len([c for c in changes if c["status"] == "OK"])
        print(f"\n💡 Dry-run complete. Use --apply --dsn <DSN> to execute {ok_count} changes.")


if __name__ == "__main__":
    main()
