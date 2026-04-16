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

    # Apply active context (e.g. "neon") to the env dict *before* os.execve
    # so the child process inherits correct DSNs instead of .env localhost
    # defaults.  The child's mcp_server.py also applies context at import
    # time as a belt-and-suspenders measure.
    try:
        from amprealize.context import apply_context_to_environment as _apply_ctx
        _apply_ctx(force=True)
        # Propagate the now-overwritten env vars into the dict we'll pass
        for key in list(env):
            if "DSN" in key or key == "DATABASE_URL" or key == "TELEMETRY_DATABASE_URL":
                current = os.environ.get(key)
                if current:
                    env[key] = current
    except Exception as exc:
        print(f"[start_amprealize_mcp] context bridge warning: {exc}", file=sys.stderr)

    os.chdir(repo_root)
    os.execve(
        sys.executable,
        [sys.executable, "-m", "amprealize.mcp_server", *sys.argv[1:]],
        env,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
