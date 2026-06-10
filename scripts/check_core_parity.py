#!/usr/bin/env python3
"""Core parity gate: enforce that the Enterprise repo is a superset of OSS core.

Model (see CORE_DRIFT_INVENTORY.md):

    Enterprise core  =  OSS core (identical)  +  enterprise-only differentiation

For every file in the OSS core package that is NOT part of a documented
"seam" (the OSS-stub-vs-enterprise-real boundary), this script asserts:

  * presence  — the file also exists in the Enterprise core, and
  * content   — the two copies are byte-identical.

A committed baseline (``core_parity_baseline.txt``) lists the files that
already drift today; they are tolerated so the gate passes immediately and
fails only on *new* drift. The baseline is a ratchet: as files are
reconciled, remove them from it. The gate also flags baseline entries that
are now clean ("stale") so the ratchet keeps tightening.

Usage:
    check_core_parity.py [--oss PATH] [--enterprise PATH] [--update-baseline]

Defaults assume the two repos are siblings:
    <root>/amprealize  and  <root>/amprealize-enterprise

Exit codes: 0 = parity holds (modulo baseline); 1 = new drift; 2 = bad args.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Package-relative path of the core within each repo.
CORE_SUBPATH = "amprealize"

# Seam: paths (relative to the core package) that are EXPECTED to differ or be
# enterprise-only. These are the documented OSS/enterprise differentiation
# boundaries — orgs/multi-tenancy, billing, research, analytics, crypto, the
# enterprise subpackage itself, and the surface files that mount enterprise
# routes/commands. Matched as prefixes (a trailing "/" matches a directory).
SEAM_PREFIXES = (
    "enterprise/",          # enterprise-only subpackage (never in OSS)
    "multi_tenant/",        # OSS stub vs enterprise real (orgs)
    "billing/",             # enterprise differentiation
    "analytics/",           # enterprise differentiation
    "research/",            # enterprise differentiation
    "crypto/",              # enterprise differentiation
    "tenant/",              # OSS-only single-tenant shim
    "wizard/",              # OSS-only CLI setup wizard
    "auth/invite_policy.py",  # invitations are part of orgs (enterprise)
    "api.py",               # mounts enterprise routes
    "cli.py",               # mounts enterprise commands
    "mcp_server.py",        # mounts enterprise tools
)

BASELINE_NAME = "core_parity_baseline.txt"


def is_seam(rel: str) -> bool:
    return any(rel == p or rel.startswith(p) for p in SEAM_PREFIXES)


def py_files(core: Path) -> set[str]:
    out: set[str] = set()
    for p in core.rglob("*.py"):
        s = str(p.relative_to(core))
        if "__pycache__" in s or "_archive" in s:
            continue
        if "/.!" in "/" + s:  # stray editor/AFP temp artifacts
            continue
        out.add(s)
    return out


def load_baseline(path: Path) -> set[str]:
    if not path.exists():
        return set()
    entries = set()
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            entries.add(line)
    return entries


def compute_drift(oss_core: Path, ent_core: Path) -> tuple[set[str], set[str]]:
    """Return (missing_in_enterprise, content_diff) for non-seam OSS files."""
    oss = {f for f in py_files(oss_core) if not is_seam(f)}
    ent = py_files(ent_core)
    missing, diff = set(), set()
    for rel in oss:
        ent_file = ent_core / rel
        if rel not in ent:
            missing.add(rel)
        elif (oss_core / rel).read_bytes() != ent_file.read_bytes():
            diff.add(rel)
    return missing, diff


def main() -> int:
    here = Path(__file__).resolve()
    default_oss = here.parents[2] / "amprealize"
    default_ent = here.parents[2] / "amprealize-enterprise"

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--oss", type=Path, default=default_oss)
    ap.add_argument("--enterprise", type=Path, default=default_ent)
    ap.add_argument(
        "--update-baseline",
        action="store_true",
        help="Rewrite the baseline to current drift (run after intentional changes).",
    )
    args = ap.parse_args()

    oss_core = args.oss / CORE_SUBPATH
    ent_core = args.enterprise / CORE_SUBPATH
    for label, core in (("OSS", oss_core), ("Enterprise", ent_core)):
        if not core.is_dir():
            print(f"error: {label} core not found at {core}", file=sys.stderr)
            return 2

    baseline_path = here.parent / BASELINE_NAME
    missing, diff = compute_drift(oss_core, ent_core)
    current = missing | diff

    if args.update_baseline:
        lines = [
            "# Core parity baseline — known OSS↔Enterprise drift, tolerated by the gate.",
            "# Ratchet: shrink this as files are reconciled. Regenerate with --update-baseline.",
            "# See CORE_DRIFT_INVENTORY.md.",
            "",
        ]
        lines += [f"MISSING  {f}" if f in missing else f"DIFFER   {f}" for f in sorted(current)]
        baseline_path.write_text("\n".join(lines) + "\n")
        print(f"Wrote baseline with {len(current)} entries -> {baseline_path}")
        return 0

    baseline_raw = load_baseline(baseline_path)
    # Baseline lines may be "MISSING <path>" / "DIFFER <path>" or bare "<path>".
    baseline = {ln.split()[-1] for ln in baseline_raw}

    new_drift = sorted(current - baseline)
    stale = sorted(baseline - current)

    print("=== Core parity gate ===")
    print(f"OSS core:        {oss_core}")
    print(f"Enterprise core: {ent_core}")
    print(f"Non-seam OSS files checked: {len(py_files(oss_core)) }")
    print(f"Currently drifting (missing+differ): {len(current)}  "
          f"(missing={len(missing)}, differ={len(diff)})")
    print(f"Baselined (tolerated): {len(baseline)}")
    print()

    if stale:
        print(f"✓ {len(stale)} baselined file(s) are now in parity — "
              f"remove from {BASELINE_NAME} to tighten the ratchet:")
        for f in stale:
            print(f"    {f}")
        print()

    if new_drift:
        print(f"✗ NEW drift not in baseline ({len(new_drift)} file(s)):")
        for f in new_drift:
            kind = "missing from Enterprise" if f in missing else "content differs"
            print(f"    {f}  ({kind})")
        print()
        print("Fix: mirror the change to both repos, or — if intentional — add it to")
        print(f"{BASELINE_NAME} (and explain why), or extend SEAM_PREFIXES if it's a")
        print("genuine OSS/enterprise differentiation boundary.")
        return 1

    print("✓ No new drift. Enterprise core is a superset of OSS core (modulo baseline).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
