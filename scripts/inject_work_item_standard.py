#!/usr/bin/env python3
"""Inject / remove / preview / check the GWS snippet in target files.

Usage:
    python scripts/inject_work_item_standard.py inject  <file>
    python scripts/inject_work_item_standard.py remove  <file>
    python scripts/inject_work_item_standard.py preview
    python scripts/inject_work_item_standard.py check   <file>

Exit codes: 0 = success, 1 = check failed (snippet missing), 2 = usage error
"""

from __future__ import annotations

import sys
from pathlib import Path

SENTINEL_START = "<!-- GWS:START -->"
SENTINEL_END = "<!-- GWS:END -->"

SNIPPET_PATH = Path(__file__).resolve().parent.parent / "amprealize" / "agents" / "work_item_planner" / "GWS_INJECT.md"


def _load_snippet() -> str:
    """Load the GWS injectable snippet from the canonical file."""
    if not SNIPPET_PATH.exists():
        print(f"Error: Snippet not found at {SNIPPET_PATH}", file=sys.stderr)
        sys.exit(2)
    return SNIPPET_PATH.read_text(encoding="utf-8")


def _has_snippet(content: str) -> bool:
    return SENTINEL_START in content and SENTINEL_END in content


def _remove_snippet(content: str) -> str:
    """Remove everything between (and including) the sentinel markers."""
    start = content.find(SENTINEL_START)
    end = content.find(SENTINEL_END)
    if start == -1 or end == -1:
        return content
    end += len(SENTINEL_END)
    # Also remove a trailing newline if present
    if end < len(content) and content[end] == "\n":
        end += 1
    return content[:start] + content[end:]


def cmd_inject(filepath: str) -> None:
    path = Path(filepath)
    if not path.exists():
        print(f"Error: File not found: {filepath}", file=sys.stderr)
        sys.exit(2)

    content = path.read_text(encoding="utf-8")
    snippet = _load_snippet()

    # Idempotent: remove old snippet first
    if _has_snippet(content):
        content = _remove_snippet(content)

    # Find injection point — after </rules> or <rules> closing, or append at end
    inject_after = "</rules>"
    idx = content.find(inject_after)
    if idx != -1:
        insert_pos = idx + len(inject_after)
        before = content[:insert_pos].rstrip("\n") + "\n"
        after = content[insert_pos:].lstrip("\n")
        if after:
            after = "\n" + after
        content = before + "\n" + snippet + after
    else:
        # Append at end with blank line separator
        content = content.rstrip("\n") + "\n\n" + snippet

    path.write_text(content, encoding="utf-8")
    print(f"Injected GWS snippet into {filepath}")


def cmd_remove(filepath: str) -> None:
    path = Path(filepath)
    if not path.exists():
        print(f"Error: File not found: {filepath}", file=sys.stderr)
        sys.exit(2)

    content = path.read_text(encoding="utf-8")
    if not _has_snippet(content):
        print(f"No GWS snippet found in {filepath}")
        return

    content = _remove_snippet(content)
    path.write_text(content, encoding="utf-8")
    print(f"Removed GWS snippet from {filepath}")


def cmd_preview() -> None:
    snippet = _load_snippet()
    print(snippet)


def cmd_check(filepath: str) -> None:
    path = Path(filepath)
    if not path.exists():
        print(f"Error: File not found: {filepath}", file=sys.stderr)
        sys.exit(2)

    content = path.read_text(encoding="utf-8")
    if _has_snippet(content):
        print(f"GWS snippet is present in {filepath}")
        sys.exit(0)
    else:
        print(f"GWS snippet is MISSING from {filepath}")
        sys.exit(1)


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)

    command = sys.argv[1].lower()

    if command == "inject":
        if len(sys.argv) < 3:
            print("Usage: inject <file>", file=sys.stderr)
            sys.exit(2)
        cmd_inject(sys.argv[2])
    elif command == "remove":
        if len(sys.argv) < 3:
            print("Usage: remove <file>", file=sys.stderr)
            sys.exit(2)
        cmd_remove(sys.argv[2])
    elif command == "preview":
        cmd_preview()
    elif command == "check":
        if len(sys.argv) < 3:
            print("Usage: check <file>", file=sys.stderr)
            sys.exit(2)
        cmd_check(sys.argv[2])
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print(__doc__, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
