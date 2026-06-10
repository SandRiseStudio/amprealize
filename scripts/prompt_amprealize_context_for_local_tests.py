#!/usr/bin/env python3
"""Interactive prompt: switch off remote Postgres context before BreakerAmp test runs.

Invoked from ``run_tests.sh`` when ``--breakeramp --env test`` and stdin is a TTY.
Environment:
  AMPREALIZE_SKIP_LOCAL_TEST_CONTEXT_PROMPT=1 — skip entirely (CI / automation).
  AMPREALIZE_REPO_ROOT — repo root for ``python -m amprealize context use``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    env = os.environ.get("AMPREALIZE_REPO_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parents[1]


def main() -> int:
    if os.environ.get("AMPREALIZE_SKIP_LOCAL_TEST_CONTEXT_PROMPT", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return 0

    from amprealize.context import (
        active_amprealize_context_targets_remote_postgres,
        suggest_local_postgres_context_names,
    )

    remote, ctx_name, reason = active_amprealize_context_targets_remote_postgres()
    if not remote:
        return 0

    suggestions = suggest_local_postgres_context_names()
    banner = (
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "  Amprealize context vs BreakerAmp local test stack\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  Current context: {ctx_name}\n"
        f"  {reason}\n"
        "\n"
        "  BreakerAmp ``--env test`` uses local Postgres in Podman. A cloud context\n"
        "  (e.g. neon after ``cloud-dev``) can confuse CLI tools and ``.env``.\n"
    )
    sys.stderr.write(banner)

    if not sys.stdin.isatty():
        sys.stderr.write(
            "  (Skipping interactive prompt: stdin is not a TTY.)\n"
            "  To switch manually:  amprealize context use <local-context-name>\n"
            "  Seed standard local contexts once:  amprealize context init-standard-local\n"
            "  Silence this message:  export AMPREALIZE_SKIP_LOCAL_TEST_CONTEXT_PROMPT=1\n"
            "\n"
        )
        return 0

    if not suggestions:
        sys.stderr.write(
            "  No local Postgres context found in ~/.amprealize/config.yaml.\n"
            "  Create the standard BreakerAmp contexts:\n"
            "    amprealize context init-standard-local\n"
            "  Or add one manually, for example:\n"
            "    amprealize context add local-postgres --backend postgres \\\n"
            '      --dsn "postgresql://USER:PASS@localhost:5432/DBNAME"\n'  # pragma: allowlist secret
            "\n"
            "  Continue without switching? [Y/n]: "
        )
        sys.stderr.flush()
        line = sys.stdin.readline()
        if line.strip().lower() in ("n", "no"):
            sys.stderr.write("  Aborted.\n")
            return 2
        sys.stderr.write("\n")
        return 0

    pick = suggestions[0]
    extra = ""
    if len(suggestions) > 1:
        extra = f" (also available: {', '.join(suggestions[1:])})"

    sys.stderr.write(
        f"  Switch active context to '{pick}'?{extra}\n"
        f"  [Y/n]: "
    )
    sys.stderr.flush()
    line = sys.stdin.readline()
    if line.strip().lower() in ("n", "no"):
        sys.stderr.write(
            f"  Kept context '{ctx_name}'. If tests fail on DSN guards, run:\n"
            f"    amprealize context use {' | '.join(suggestions)}\n\n"
        )
        return 0

    repo = _repo_root()
    cmd = [sys.executable, "-m", "amprealize", "context", "use", pick]
    proc = subprocess.run(
        cmd,
        cwd=str(repo),
        env={**os.environ, "PYTHONPATH": str(repo)},
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.stdout:
        sys.stderr.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        sys.stderr.write(
            f"  Failed to run: {' '.join(cmd)} (exit {proc.returncode})\n\n"
        )
        return 1

    sys.stderr.write(f"  Switched to context '{pick}'.\n\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
