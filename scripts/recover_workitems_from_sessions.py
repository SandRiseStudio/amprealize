#!/usr/bin/env python3
"""Recover work items from VS Code GitHub Copilot Chat session files.

Scans JSONL session files in VS Code workspace storage for MCP workitem create
tool calls, extracts their parameters, deduplicates, and produces a JSON plan
ready for WorkItemPlanner to create.

Usage:
    # Scan all workspaces, last 7 days
    python scripts/recover_workitems_from_sessions.py

    # Scan specific date range
    python scripts/recover_workitems_from_sessions.py --since 2026-03-31 --until 2026-04-06

    # Filter to specific workspace folder name
    python scripts/recover_workitems_from_sessions.py --workspace amprealize

    # Compare against live DB and output only missing items
    python scripts/recover_workitems_from_sessions.py --db-check --db-container amp-461bcc36-...-amprealize-db

    # Output as JSON plan for WorkItemPlanner
    python scripts/recover_workitems_from_sessions.py --output /tmp/recovery_plan.json

    # Dry run: just show what would be found
    python scripts/recover_workitems_from_sessions.py --dry-run
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VSCODE_STORAGE_ROOT = Path.home() / "Library" / "Application Support" / "Code" / "User" / "workspaceStorage"
TOOL_PATTERNS = ("workitems_create", "workitems.create", "workItems.create")


# ---------------------------------------------------------------------------
# Session discovery
# ---------------------------------------------------------------------------

def discover_workspaces(
    storage_root: Path,
    workspace_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Find all VS Code workspace storage dirs that contain chatSessions."""
    results = []
    if not storage_root.exists():
        return results

    for entry in sorted(storage_root.iterdir()):
        if not entry.is_dir():
            continue
        sessions_dir = entry / "chatSessions"
        if not sessions_dir.exists():
            continue

        # Read workspace.json to identify the workspace
        ws_json_path = entry / "workspace.json"
        ws_info = {"id": entry.name, "path": str(entry), "sessions_dir": str(sessions_dir)}
        if ws_json_path.exists():
            try:
                with open(ws_json_path) as f:
                    ws_data = json.load(f)
                ws_info["workspace"] = ws_data.get("workspace", ws_data.get("folder", ""))
            except (json.JSONDecodeError, OSError):
                ws_info["workspace"] = ""
        else:
            ws_info["workspace"] = ""

        # Apply workspace filter
        if workspace_filter:
            ws_str = ws_info.get("workspace", "").lower()
            if workspace_filter.lower() not in ws_str:
                continue

        session_files = list(sessions_dir.glob("*.jsonl"))
        if session_files:
            ws_info["session_count"] = len(session_files)
            results.append(ws_info)

    return results


def find_session_files(
    workspaces: list[dict[str, Any]],
    since: datetime.datetime | None = None,
    until: datetime.datetime | None = None,
) -> list[dict[str, Any]]:
    """Find session JSONL files within the date range."""
    results = []
    for ws in workspaces:
        sessions_dir = Path(ws["sessions_dir"])
        for jsonl_file in sorted(sessions_dir.glob("*.jsonl")):
            mod_time = datetime.datetime.fromtimestamp(os.path.getmtime(jsonl_file))
            if since and mod_time < since:
                continue
            if until and mod_time > until + datetime.timedelta(days=1):
                continue
            results.append({
                "path": str(jsonl_file),
                "session_id": jsonl_file.stem,
                "modified": mod_time.isoformat(),
                "workspace_id": ws["id"],
                "workspace": ws.get("workspace", ""),
                "size_kb": jsonl_file.stat().st_size // 1024,
            })
    return results


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def _extract_creates_recursive(obj: Any) -> list[dict[str, Any]]:
    """Recursively search a JSON object for workitem create tool calls."""
    results = []
    if isinstance(obj, dict):
        name = str(obj.get("name", "") or obj.get("tool_name", "") or "")
        if any(p in name for p in TOOL_PATTERNS):
            args = obj.get("arguments", obj.get("input", obj.get("parameters", {})))
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except (json.JSONDecodeError, ValueError):
                    args = {}
            if isinstance(args, dict) and args.get("title"):
                results.append({
                    "title": args["title"],
                    "item_type": args.get("item_type", args.get("type", "task")),
                    "description": (args.get("description") or "")[:500],
                    "parent_id": args.get("parent_id", ""),
                    "points": args.get("points"),
                    "labels": args.get("labels", []),
                    "priority": args.get("priority", "medium"),
                    "board_id": args.get("board_id", ""),
                    "project_id": args.get("project_id", ""),
                    "org_id": args.get("org_id", ""),
                })
        for v in obj.values():
            results.extend(_extract_creates_recursive(v))
    elif isinstance(obj, list):
        for v in obj:
            results.extend(_extract_creates_recursive(v))
    elif isinstance(obj, str):
        if any(p in obj for p in TOOL_PATTERNS) and "title" in obj:
            try:
                inner = json.loads(obj)
                results.extend(_extract_creates_recursive(inner))
            except (json.JSONDecodeError, ValueError):
                pass
    return results


def extract_workitems_from_session(session_path: str) -> list[dict[str, Any]]:
    """Parse a single JSONL session file and extract workitem create calls."""
    items = []
    try:
        with open(session_path, "r", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if not any(p in line for p in TOOL_PATTERNS):
                    continue
                try:
                    obj = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                items.extend(_extract_creates_recursive(obj))
    except OSError as e:
        print(f"  Warning: Could not read {session_path}: {e}", file=sys.stderr)
    return items


def extract_all(
    session_files: list[dict[str, Any]],
    verbose: bool = False,
) -> list[dict[str, Any]]:
    """Extract work items from all session files, deduplicate by title."""
    all_items: list[dict[str, Any]] = []

    for sf in session_files:
        items = extract_workitems_from_session(sf["path"])
        for item in items:
            item["session_id"] = sf["session_id"]
            item["session_date"] = sf["modified"][:10]
            item["workspace"] = sf.get("workspace", "")
        if verbose and items:
            print(f"  Found {len(items)} create calls in {sf['session_id'][:12]}...")
        all_items.extend(items)

    # Deduplicate by title (keep first occurrence)
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in all_items:
        if item["title"] not in seen:
            seen.add(item["title"])
            unique.append(item)

    return unique


# ---------------------------------------------------------------------------
# DB comparison
# ---------------------------------------------------------------------------

def check_against_db(
    items: list[dict[str, Any]],
    db_container: str,
    db_name: str = "amprealize",
    db_user: str = "amprealize",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Compare extracted items against DB. Returns (missing, existing)."""
    # Fetch all titles from DB
    cmd = [
        "podman", "exec", "-i", db_container,
        "psql", "-U", db_user, "-d", db_name, "-t", "-A", "-c",
        "SELECT title FROM board.work_items",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        db_titles = {line.strip() for line in result.stdout.strip().split("\n") if line.strip()}
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"Warning: Could not query DB: {e}", file=sys.stderr)
        return items, []

    missing = [i for i in items if i["title"] not in db_titles]
    existing = [i for i in items if i["title"] in db_titles]
    return missing, existing


# ---------------------------------------------------------------------------
# Hierarchy reconstruction
# ---------------------------------------------------------------------------

def build_hierarchy(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Reconstruct goal → feature → task hierarchy from flat items.

    Groups items by type, then uses label overlap to infer parent relationships
    where original parent_ids reference items not in the current set.
    """
    goals = [i for i in items if i.get("item_type") == "goal"]
    features = [i for i in items if i.get("item_type") == "feature"]
    tasks = [i for i in items if i.get("item_type") in ("task", "bug")]

    # Build parent_id -> item mapping for items present in the set
    id_to_item: dict[str, dict] = {}
    # We don't have original IDs, but parent_id fields reference old UUIDs
    # Use label overlap to match features to goals and tasks to features

    def _label_overlap_score(a_labels: list, b_labels: list) -> int:
        return len(set(a_labels or []) & set(b_labels or []))

    # Map features to goals by label overlap
    feature_to_goal: dict[str, str] = {}
    for f in features:
        pid = f.get("parent_id", "")
        best_goal = None
        best_score = 0
        for g in goals:
            score = _label_overlap_score(f.get("labels", []), g.get("labels", []))
            if score > best_score:
                best_score = score
                best_goal = g["title"]
        if best_goal:
            feature_to_goal[f["title"]] = best_goal

    # Map tasks to features by label overlap (aggregate across shared parent_ids)
    parent_feature_scores: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for t in tasks:
        pid = t.get("parent_id", "")
        if not pid:
            continue
        for f in features:
            score = _label_overlap_score(t.get("labels", []), f.get("labels", []))
            if score > 0:
                parent_feature_scores[pid][f["title"]] += score

    task_parent_to_feature: dict[str, str] = {}
    for pid, scores in parent_feature_scores.items():
        if scores:
            best = max(scores.items(), key=lambda x: x[1])
            task_parent_to_feature[pid] = best[0]

    # Build tree structure
    tree = []
    for g in goals:
        goal_node = {**g, "children": []}
        child_features = [f for f in features if feature_to_goal.get(f["title"]) == g["title"]]
        for f in child_features:
            feature_node = {**f, "children": []}
            child_tasks = [
                t for t in tasks
                if task_parent_to_feature.get(t.get("parent_id", "")) == f["title"]
            ]
            feature_node["children"] = child_tasks
            goal_node["children"].append(feature_node)
        tree.append(goal_node)

    # Find orphans (features/tasks not mapped)
    mapped_features = set()
    for g_node in tree:
        for f_node in g_node["children"]:
            mapped_features.add(f_node["title"])
    orphan_features = [f for f in features if f["title"] not in mapped_features]

    mapped_tasks = set()
    for g_node in tree:
        for f_node in g_node["children"]:
            for t_node in f_node["children"]:
                mapped_tasks.add(t_node["title"])
    orphan_tasks = [t for t in tasks if t["title"] not in mapped_tasks]

    return {
        "tree": tree,
        "orphan_features": orphan_features,
        "orphan_tasks": orphan_tasks,
        "stats": {
            "goals": len(goals),
            "features": len(features),
            "tasks": len(tasks),
            "mapped_features": len(mapped_features),
            "mapped_tasks": len(mapped_tasks),
            "orphan_features": len(orphan_features),
            "orphan_tasks": len(orphan_tasks),
        },
    }


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def format_plan_for_planner(
    items: list[dict[str, Any]],
    hierarchy: dict[str, Any],
) -> dict[str, Any]:
    """Format extracted items into a plan compatible with WorkItemPlanner.

    Returns a structured JSON document that can be handed to the
    WorkItemPlanner agent for review and creation.
    """
    plan = {
        "recovery_metadata": {
            "source": "vscode_copilot_chat_sessions",
            "extracted_at": datetime.datetime.now().isoformat(),
            "total_items": len(items),
            "stats": hierarchy["stats"],
        },
        "goals": [],
    }

    for g_node in hierarchy["tree"]:
        goal_entry = {
            "item_type": "goal",
            "title": g_node["title"],
            "description": g_node.get("description", ""),
            "priority": g_node.get("priority", "medium"),
            "labels": g_node.get("labels", []),
            "features": [],
        }
        for f_node in g_node["children"]:
            feature_entry = {
                "item_type": "feature",
                "title": f_node["title"],
                "description": f_node.get("description", ""),
                "priority": f_node.get("priority", "medium"),
                "labels": f_node.get("labels", []),
                "points": f_node.get("points"),
                "tasks": [],
            }
            for t_node in f_node["children"]:
                task_entry = {
                    "item_type": t_node.get("item_type", "task"),
                    "title": t_node["title"],
                    "description": t_node.get("description", ""),
                    "priority": t_node.get("priority", "medium"),
                    "labels": t_node.get("labels", []),
                    "points": t_node.get("points"),
                }
                feature_entry["tasks"].append(task_entry)
            goal_entry["features"].append(feature_entry)
        plan["goals"].append(goal_entry)

    # Add orphans section if any
    if hierarchy["orphan_features"] or hierarchy["orphan_tasks"]:
        plan["orphans"] = {
            "features": [
                {
                    "item_type": "feature",
                    "title": f["title"],
                    "description": f.get("description", ""),
                    "labels": f.get("labels", []),
                    "points": f.get("points"),
                    "original_parent_id": f.get("parent_id", ""),
                }
                for f in hierarchy["orphan_features"]
            ],
            "tasks": [
                {
                    "item_type": t.get("item_type", "task"),
                    "title": t["title"],
                    "description": t.get("description", ""),
                    "labels": t.get("labels", []),
                    "points": t.get("points"),
                    "original_parent_id": t.get("parent_id", ""),
                }
                for t in hierarchy["orphan_tasks"]
            ],
        }

    return plan


def print_summary(
    items: list[dict[str, Any]],
    hierarchy: dict[str, Any],
    missing: list[dict[str, Any]] | None = None,
    existing: list[dict[str, Any]] | None = None,
) -> None:
    """Print a human-readable summary."""
    stats = hierarchy["stats"]
    print("\n" + "=" * 70)
    print("WORK ITEM RECOVERY SUMMARY")
    print("=" * 70)
    print(f"Total unique items extracted:  {len(items)}")
    print(f"  Goals:    {stats['goals']}")
    print(f"  Features: {stats['features']} ({stats['mapped_features']} mapped, {stats['orphan_features']} orphans)")
    print(f"  Tasks:    {stats['tasks']} ({stats['mapped_tasks']} mapped, {stats['orphan_tasks']} orphans)")

    if missing is not None:
        print(f"\nDB comparison:")
        print(f"  Missing from DB: {len(missing)}")
        print(f"  Already in DB:   {len(existing or [])}")

    print("\nHierarchy:")
    for g_node in hierarchy["tree"]:
        feature_count = len(g_node["children"])
        task_count = sum(len(f["children"]) for f in g_node["children"])
        print(f"  [{g_node.get('priority', 'medium')}] {g_node['title']}")
        print(f"    {feature_count} features, {task_count} tasks")
        for f_node in g_node["children"]:
            t_count = len(f_node["children"])
            pts = f" ({f_node['points']}pts)" if f_node.get("points") else ""
            print(f"      - {f_node['title']}{pts} [{t_count} tasks]")

    if hierarchy["orphan_features"]:
        print(f"\nOrphan features ({len(hierarchy['orphan_features'])}):")
        for f in hierarchy["orphan_features"]:
            print(f"  - {f['title']}")
    if hierarchy["orphan_tasks"]:
        print(f"\nOrphan tasks ({len(hierarchy['orphan_tasks'])}):")
        for t in hierarchy["orphan_tasks"][:10]:
            print(f"  - {t['title']}")
        if len(hierarchy["orphan_tasks"]) > 10:
            print(f"  ... and {len(hierarchy['orphan_tasks']) - 10} more")

    print("=" * 70)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recover work items from VS Code Copilot Chat session files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--since", type=str, default=None,
        help="Start date (YYYY-MM-DD). Default: 7 days ago",
    )
    parser.add_argument(
        "--until", type=str, default=None,
        help="End date (YYYY-MM-DD). Default: today",
    )
    parser.add_argument(
        "--workspace", type=str, default=None,
        help="Filter to workspaces matching this name (e.g., 'amprealize', 'guideai')",
    )
    parser.add_argument(
        "--storage-root", type=str, default=str(VSCODE_STORAGE_ROOT),
        help="VS Code workspace storage root path",
    )
    parser.add_argument(
        "--db-check", action="store_true",
        help="Compare against live DB to find only missing items",
    )
    parser.add_argument(
        "--db-container", type=str, default=None,
        help="Podman DB container name for --db-check",
    )
    parser.add_argument(
        "--db-name", type=str, default="amprealize",
        help="Database name (default: amprealize)",
    )
    parser.add_argument(
        "--db-user", type=str, default="amprealize",
        help="Database user (default: amprealize)",
    )
    parser.add_argument(
        "--output", "-o", type=str, default=None,
        help="Output JSON file path. If not set, prints to stdout.",
    )
    parser.add_argument(
        "--raw", action="store_true",
        help="Output raw extracted items instead of hierarchical plan",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Just show what sessions would be scanned",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Verbose output",
    )
    args = parser.parse_args()

    # Parse dates
    now = datetime.datetime.now()
    since = datetime.datetime.strptime(args.since, "%Y-%m-%d") if args.since else now - datetime.timedelta(days=7)
    until = datetime.datetime.strptime(args.until, "%Y-%m-%d") if args.until else now

    storage_root = Path(args.storage_root)
    print(f"Scanning VS Code sessions from {since.date()} to {until.date()}")
    if args.workspace:
        print(f"  Workspace filter: {args.workspace}")

    # Step 1: Discover workspaces
    workspaces = discover_workspaces(storage_root, args.workspace)
    if not workspaces:
        print("No workspaces found with chat sessions.", file=sys.stderr)
        sys.exit(1)
    print(f"Found {len(workspaces)} workspace(s) with chat sessions")

    # Step 2: Find session files
    session_files = find_session_files(workspaces, since, until)
    if not session_files:
        print("No session files found in date range.", file=sys.stderr)
        sys.exit(1)
    print(f"Found {len(session_files)} session file(s) in date range")

    if args.dry_run:
        print("\nSession files that would be scanned:")
        for sf in session_files:
            print(f"  {sf['session_id'][:12]}... ({sf['size_kb']}KB) {sf['modified'][:10]} [{sf['workspace'][-30:]}]")
        sys.exit(0)

    # Step 3: Extract work items
    print("\nExtracting work item create calls...")
    items = extract_all(session_files, verbose=args.verbose)
    if not items:
        print("No work item create calls found.", file=sys.stderr)
        sys.exit(0)
    print(f"Extracted {len(items)} unique work items")

    # Step 4: Optional DB check
    missing = None
    existing = None
    if args.db_check:
        if not args.db_container:
            # Auto-detect running amprealize-db container
            try:
                result = subprocess.run(
                    ["podman", "ps", "--format", "{{.Names}}"],
                    capture_output=True, text=True, timeout=10,
                )
                containers = result.stdout.strip().split("\n")
                db_containers = [c for c in containers if "amprealize-db" in c]
                if db_containers:
                    args.db_container = db_containers[0]
                    print(f"Auto-detected DB container: {args.db_container}")
                else:
                    print("Warning: No amprealize-db container found. Skipping DB check.", file=sys.stderr)
                    args.db_check = False
            except (subprocess.TimeoutExpired, FileNotFoundError):
                print("Warning: podman not available. Skipping DB check.", file=sys.stderr)
                args.db_check = False

        if args.db_check:
            print("Comparing against database...")
            missing, existing = check_against_db(items, args.db_container, args.db_name, args.db_user)
            print(f"  Missing: {len(missing)}, Already present: {len(existing)}")
            items = missing  # Only process missing items going forward

    # Step 5: Build hierarchy
    hierarchy = build_hierarchy(items)

    # Step 6: Output
    if args.raw:
        output_data = items
    else:
        output_data = format_plan_for_planner(items, hierarchy)

    print_summary(items, hierarchy, missing, existing)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(output_data, f, indent=2, default=str)
        print(f"\nPlan written to {args.output}")
    else:
        # Print JSON to stdout only if not verbose (avoid mixing)
        if not args.verbose:
            print("\n--- JSON Plan ---")
            print(json.dumps(output_data, indent=2, default=str))


if __name__ == "__main__":
    main()
