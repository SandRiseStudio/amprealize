#!/usr/bin/env python3
"""Validate that the installed amprealize version matches .amprealize-version.

Usage:
    python scripts/check_oss_version.py              # check amprealize
    python scripts/check_oss_version.py --package amprealize-enterprise  # check enterprise

Exit codes:
    0 — version matches
    1 — mismatch or .amprealize-version missing
    2 — package not installed

Enterprise CI example:
    pip install amprealize==$(cat .amprealize-version)
    python scripts/check_oss_version.py
"""
from __future__ import annotations

import argparse
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _read_pinned_version() -> str:
    pin_file = Path(__file__).resolve().parent.parent / ".amprealize-version"
    if not pin_file.exists():
        print(f"ERROR: {pin_file} not found", file=sys.stderr)
        sys.exit(1)
    return pin_file.read_text().strip()


def _installed_version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        print(f"ERROR: {package} is not installed", file=sys.stderr)
        sys.exit(2)


def _compatible(installed: str, pinned: str) -> bool:
    """Check major.minor compatibility (PEP 440 ~= semantics).

    Given pinned=0.1.0 the installed version must satisfy >=0.1.0, <0.2.0.
    """
    from packaging.version import Version

    inst = Version(installed)
    pin = Version(pinned)
    return inst >= pin and inst.release[:2] == pin.release[:2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--package",
        default="amprealize",
        help="Package name to check (default: amprealize)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Require exact version match instead of compatible range",
    )
    args = parser.parse_args()

    pinned = _read_pinned_version()
    installed = _installed_version(args.package)

    if args.strict:
        ok = installed == pinned
    else:
        ok = _compatible(installed, pinned)

    if ok:
        print(f"OK: {args.package}=={installed} (pinned {pinned})")
    else:
        print(
            f"MISMATCH: {args.package}=={installed} vs pinned {pinned}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
