#!/usr/bin/env python3
"""Fail if mcp/tools/*.json and amprealize/mcp_tool_manifests/*.json diverge."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    src = root / "mcp" / "tools"
    dst = root / "amprealize" / "mcp_tool_manifests"

    if not src.is_dir():
        print(f"error: missing {src}", file=sys.stderr)
        return 1
    if not dst.is_dir():
        print(f"error: missing {dst} — run python scripts/sync_mcp_tool_manifests.py", file=sys.stderr)
        return 1

    src_files = {p.name: p for p in src.glob("*.json")}
    dst_files = {p.name: p for p in dst.glob("*.json")}

    only_src = sorted(set(src_files) - set(dst_files))
    only_dst = sorted(set(dst_files) - set(src_files))
    if only_src or only_dst:
        if only_src:
            print(f"error: bundled manifests missing files: {only_src[:10]!r}...", file=sys.stderr)
        if only_dst:
            print(f"error: bundled manifests have extra files: {only_dst[:10]!r}...", file=sys.stderr)
        print("hint: python scripts/sync_mcp_tool_manifests.py", file=sys.stderr)
        return 1

    mismatches = []
    for name in sorted(src_files):
        if _sha256(src_files[name]) != _sha256(dst_files[name]):
            mismatches.append(name)

    if mismatches:
        print(
            "error: content drift between mcp/tools and amprealize/mcp_tool_manifests for:",
            ", ".join(mismatches[:20]),
            file=sys.stderr,
        )
        if len(mismatches) > 20:
            print(f"... and {len(mismatches) - 20} more", file=sys.stderr)
        print("hint: python scripts/sync_mcp_tool_manifests.py", file=sys.stderr)
        return 1

    print(f"ok: {len(src_files)} MCP tool manifests in sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
