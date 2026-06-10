#!/usr/bin/env python3
"""Create a GuideAI board goal that tracks pytest not-yet-implemented / parity gaps.

Uses BoardService against the configured Postgres backend (same pattern as
``scripts/create_adr_work_items.py``). Does not call remote GitHub.

Examples:
  python scripts/create_guideai_skip_backlog_goal.py --dry-run
  python scripts/create_guideai_skip_backlog_goal.py --project-id proj-abc123
  GUIDEAI_PROJECT_ID=proj-abc123 python scripts/create_guideai_skip_backlog_goal.py

After MCP ``auth_devicelogin`` (and optional ``auth_devicepoll``), call
``workitems_create`` with ``item_type=goal`` and the same title/description as
this script. See ``docs/testing/NOT_YET_IMPLEMENTED_SKIP_INVENTORY.md`` §
“Create the GuideAI goal via Amprealize MCP”.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from amprealize.boards.contracts import (  # noqa: E402
    CreateWorkItemRequest,
    WorkItemPriority,
    WorkItemType,
)
from amprealize.services.board_service import Actor, BoardService  # noqa: E402

DEFAULT_TITLE = "Close pytest not-yet-implemented gaps across surfaces"
INVENTORY_REL = Path("docs/testing/NOT_YET_IMPLEMENTED_SKIP_INVENTORY.md")
_MAX_DESC = 9_500


def _load_description() -> str:
    path = ROOT / INVENTORY_REL
    if not path.is_file():
        return f"See repository file `{INVENTORY_REL}` (missing on disk)."
    text = path.read_text(encoding="utf-8")
    if len(text) > _MAX_DESC:
        return text[:_MAX_DESC] + "\n\n_(truncated — see full file in repo.)_"
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-id",
        default=os.environ.get("GUIDEAI_PROJECT_ID", "").strip() or None,
        help="GuideAI project id (or set GUIDEAI_PROJECT_ID)",
    )
    parser.add_argument(
        "--board-id",
        default=os.environ.get("GUIDEAI_BOARD_ID", "").strip() or None,
        help="Board id (default: first board for project)",
    )
    parser.add_argument("--title", default=DEFAULT_TITLE, help="Goal title (GWS: imperative phrase)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print title and description only; do not call BoardService",
    )
    args = parser.parse_args()

    description = _load_description()
    if args.dry_run:
        print("--- dry-run: would create goal ---")
        print("title:", args.title)
        print("description bytes:", len(description.encode("utf-8")))
        print("\n--- description preview (first 2k chars) ---\n")
        print(description[:2000])
        if len(description) > 2000:
            print("\n... [truncated in preview only]")
        return 0

    if not args.project_id:
        print(
            "Missing --project-id (or GUIDEAI_PROJECT_ID). "
            "Resolve the GuideAI project in the web console or via projects.list.",
            file=sys.stderr,
        )
        return 2

    board_service = BoardService()
    actor = Actor(id="skip-backlog-script", role="TEACHER", surface="cli")

    board_id = args.board_id
    if not board_id:
        boards = board_service.list_boards(project_id=args.project_id)
        if not boards:
            print(f"No boards for project_id={args.project_id}", file=sys.stderr)
            return 3
        board_id = boards[0].board_id
        print(f"Using board {board_id} ({boards[0].name!r})")

    columns = board_service.list_columns(board_id)
    if not columns:
        print(f"No columns on board {board_id}", file=sys.stderr)
        return 4
    column_id = columns[0].column_id

    request = CreateWorkItemRequest(
        item_type=WorkItemType.GOAL,
        project_id=args.project_id,
        board_id=board_id,
        column_id=column_id,
        title=args.title,
        description=description,
        priority=WorkItemPriority.HIGH,
        labels=["skip-backlog", "parity", "pytest", "guideai"],
        metadata={
            "source": "scripts/create_guideai_skip_backlog_goal.py",
            "inventory_doc": str(INVENTORY_REL).replace("\\", "/"),
        },
    )
    item = board_service.create_work_item(request, actor)
    print(f"Created goal {item.item_id} on board {board_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
