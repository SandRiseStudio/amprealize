#!/usr/bin/env python3
"""Sync agent instruction artifacts after handbook or MCP tool changes.

- Copies docs/agent-handbook/ from OSS to Enterprise (canonical source: amprealize/)
- Runs sync_mcp_tool_manifests.py in each product repo
- Refreshes workspace .cursor/rules/Agent-rules.mdc from root AGENTS.md

Does not run `brief update` — AGENTS.md, CLAUDE.md, and copilot-instructions.md are
intentionally layered (contract vs adapters). Use `brief list` / `brief validate` for
optional drift checks only.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def _workspace_root(oss_root: Path) -> Path:
    parent = oss_root.parent
    if (parent / "amprealize-enterprise").is_dir():
        return parent
    return oss_root


def _copy_handbook(oss_root: Path, enterprise_root: Path, dry_run: bool) -> int:
    src = oss_root / "docs" / "agent-handbook"
    dst = enterprise_root / "docs" / "agent-handbook"
    if not src.is_dir():
        print(f"error: missing handbook {src}", file=sys.stderr)
        return 1
    if dry_run:
        print(f"would copy {src} -> {dst}")
        return 0
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    print(f"copied agent-handbook -> {dst}")
    return 0


def _run_manifest_sync(repo_root: Path, dry_run: bool) -> int:
    script = repo_root / "scripts" / "sync_mcp_tool_manifests.py"
    if not script.is_file():
        print(f"skip manifest sync (no script): {script}")
        return 0
    cmd = [sys.executable, str(script)]
    if dry_run:
        print(f"would run: {' '.join(cmd)} (cwd={repo_root})")
        return 0
    proc = subprocess.run(cmd, cwd=repo_root, check=False)
    if proc.returncode != 0:
        print(f"error: manifest sync failed in {repo_root}", file=sys.stderr)
    return proc.returncode


def _sync_cursor_rule(workspace: Path, dry_run: bool) -> int:
    agents_md = workspace / "AGENTS.md"
    rule_path = workspace / ".cursor" / "rules" / "Agent-rules.mdc"
    if not agents_md.is_file():
        print(f"skip cursor rule (no {agents_md})")
        return 0
    body = agents_md.read_text(encoding="utf-8")
    content = (
        "---\n"
        "description: Workspace agent operating contract — retrieve behaviors, "
        "use repo-local AGENTS.md, follow Amprealize handbooks.\n"
        "alwaysApply: true\n"
        "---\n\n"
        f"{body.strip()}\n"
    )
    if dry_run:
        print(f"would write {rule_path} ({len(content)} bytes)")
        return 0
    rule_path.parent.mkdir(parents=True, exist_ok=True)
    rule_path.write_text(content, encoding="utf-8")
    print(f"updated {rule_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--oss-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Amprealize OSS repo root (default: parent of this script)",
    )
    parser.add_argument(
        "--enterprise-root",
        type=Path,
        default=None,
        help="Enterprise repo root (default: sibling amprealize-enterprise)",
    )
    parser.add_argument(
        "--skip-handbook",
        action="store_true",
        help="Do not copy agent-handbook to enterprise",
    )
    parser.add_argument(
        "--skip-manifests",
        action="store_true",
        help="Do not run sync_mcp_tool_manifests.py",
    )
    parser.add_argument(
        "--skip-cursor-rule",
        action="store_true",
        help="Do not refresh .cursor/rules/Agent-rules.mdc",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    oss_root = args.oss_root.resolve()
    workspace = _workspace_root(oss_root)
    enterprise_root = (
        args.enterprise_root.resolve()
        if args.enterprise_root
        else workspace / "amprealize-enterprise"
    )

    rc = 0
    if not args.skip_handbook:
        if enterprise_root.is_dir():
            rc = max(rc, _copy_handbook(oss_root, enterprise_root, args.dry_run))
        else:
            print(f"skip handbook copy (no enterprise repo at {enterprise_root})")

    if not args.skip_manifests:
        rc = max(rc, _run_manifest_sync(oss_root, args.dry_run))
        if enterprise_root.is_dir():
            rc = max(rc, _run_manifest_sync(enterprise_root, args.dry_run))

    if not args.skip_cursor_rule:
        rc = max(rc, _sync_cursor_rule(workspace, args.dry_run))

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
