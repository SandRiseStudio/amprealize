#!/usr/bin/env python3
"""Portable launcher for the workspace-local Amprealize MCP server."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _venv_python(repo_root: Path) -> Path | None:
    """Return the preferred repo-local Python interpreter if it exists."""

    if os.name == "nt":
        candidate = repo_root / ".venv" / "Scripts" / "python.exe"
    else:
        candidate = repo_root / ".venv" / "bin" / "python"
    return candidate if candidate.exists() else None


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    preferred_python = _venv_python(repo_root)
    current_python = Path(sys.executable).resolve()

    reexec_done = (
        os.environ.get("AMPREALIZE_MCP_REEXEC") == "1"
        or os.environ.get("AMPREALIZE_MCP_REEXEC") == "1"
    )
    if (
        preferred_python is not None
        and current_python != preferred_python.resolve()
        and not reexec_done
    ):
        env = dict(os.environ)
        env["AMPREALIZE_MCP_REEXEC"] = "1"
        env["AMPREALIZE_MCP_REEXEC"] = "1"
        os.execve(
            str(preferred_python),
            [
                str(preferred_python),
                str(Path(__file__).resolve()),
                *sys.argv[1:],
            ],
            env,
        )

    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from amprealize.mcp_env import merge_mcp_runtime_env

    env = merge_mcp_runtime_env(repo_root, os.environ)
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{repo_root}{os.pathsep}{existing_pythonpath}"
        if existing_pythonpath
        else str(repo_root)
    )
    os.chdir(repo_root)
    os.execve(
        sys.executable,
        [sys.executable, "-m", "amprealize.mcp_server", *sys.argv[1:]],
        env,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
