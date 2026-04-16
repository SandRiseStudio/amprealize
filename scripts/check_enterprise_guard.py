#!/usr/bin/env python3
"""Guard rail: verify no new amprealize_enterprise references leak into OSS.

Run this in CI or pre-commit to ensure the OSS codebase stays independent.
Only the approved upgrade hook sites should reference amprealize_enterprise.

Exit 0 = clean, Exit 1 = unexpected enterprise references found.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# Known upgrade hook sites — these are the ONLY files allowed to reference
# amprealize_enterprise.  Each entry is (relative path, line pattern).
ALLOWED_REFS: list[tuple[str, str]] = [
    ("amprealize/__init__.py", r"import amprealize_enterprise"),
    ("amprealize/edition.py", r"import amprealize_enterprise"),
    ("amprealize/caps_enforcer.py", r"from amprealize_enterprise"),
    ("amprealize/cli.py", r"amprealize_enterprise"),
]

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    result = subprocess.run(
        ["grep", "-rn", "amprealize_enterprise", "amprealize/",
         "--include=*.py"],
        capture_output=True, text=True, cwd=ROOT,
    )

    if result.returncode == 1:
        # grep found nothing — perfect
        print("✅ No amprealize_enterprise references in OSS codebase.")
        return 0

    violations: list[str] = []
    for line in result.stdout.strip().splitlines():
        # line format: "amprealize/foo.py:42:    import amprealize_enterprise"
        if "__pycache__" in line:
            continue

        path_part = line.split(":")[0]
        allowed = any(
            path_part == allowed_path and re.search(pattern, line)
            for allowed_path, pattern in ALLOWED_REFS
        )
        if not allowed:
            violations.append(line)

    if violations:
        print("❌ Unexpected amprealize_enterprise references found:")
        for v in violations:
            print(f"   {v}")
        print()
        print("If this is an intentional upgrade hook, add it to ALLOWED_REFS")
        print(f"in {__file__}")
        return 1

    n = len(result.stdout.strip().splitlines())
    print(f"✅ All {n} amprealize_enterprise references are approved upgrade hooks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
