#!/usr/bin/env python3
"""Copy canonical MCP tool JSON from mcp/tools into amprealize/mcp_tool_manifests for wheels."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    src = repo_root / "mcp" / "tools"
    dst = repo_root / "amprealize" / "mcp_tool_manifests"

    if not src.is_dir():
        print(f"error: missing source directory {src}", file=sys.stderr)
        return 1

    dst.mkdir(parents=True, exist_ok=True)
    copied = 0
    for path in sorted(src.glob("*.json")):
        shutil.copy2(path, dst / path.name)
        copied += 1

    print(f"synced {copied} manifests -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
