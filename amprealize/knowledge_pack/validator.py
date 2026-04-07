"""Manifest validation and linting for Knowledge Packs.

Provides programmatic validation (validate_manifest) and a CLI-friendly
lint entrypoint (lint_manifest) that reads a JSON file from disk.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List, Optional

from pydantic import ValidationError

from amprealize.knowledge_pack.schema import (
    KnowledgePackManifest,
    LintIssue,
    ValidationResult,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core validation
# ---------------------------------------------------------------------------


def validate_manifest(
    manifest: KnowledgePackManifest,
    *,
    known_behavior_names: Optional[List[str]] = None,
) -> ValidationResult:
    """Run semantic checks that go beyond Pydantic field validation.

    Parameters
    ----------
    manifest:
        Already-parsed manifest.
    known_behavior_names:
        If provided, behaviour_refs are checked against this list and
        unrecognised names produce warnings (not errors).
    """
    errors: List[LintIssue] = []
    warnings: List[LintIssue] = []

    # 1. Duplicate overlay IDs across task + surface lists
    all_overlay_ids = manifest.task_overlays + manifest.surface_overlays
    seen: set[str] = set()
    for oid in all_overlay_ids:
        if oid in seen:
            errors.append(
                LintIssue(
                    level="error",
                    path="task_overlays / surface_overlays",
                    message=f"Duplicate overlay id: '{oid}'",
                )
            )
        seen.add(oid)

    # 2. Sources: at least one required
    if not manifest.sources:
        errors.append(
            LintIssue(
                level="error",
                path="sources",
                message="Pack must declare at least one source",
            )
        )

    # 3. Duplicate source refs
    source_refs = [s.ref for s in manifest.sources]
    seen_refs: set[str] = set()
    for ref in source_refs:
        if ref in seen_refs:
            errors.append(
                LintIssue(
                    level="error",
                    path="sources",
                    message=f"Duplicate source ref: '{ref}'",
                )
            )
        seen_refs.add(ref)

    # 4. Constraints consistency
    if manifest.constraints.mandatory_overlays:
        for mo in manifest.constraints.mandatory_overlays:
            if mo not in all_overlay_ids:
                errors.append(
                    LintIssue(
                        level="error",
                        path="constraints.mandatory_overlays",
                        message=f"Mandatory overlay '{mo}' not listed in task_overlays or surface_overlays",
                    )
                )

    # 5. Behaviour ref warnings
    if known_behavior_names is not None:
        for bref in manifest.behavior_refs:
            if bref not in known_behavior_names:
                warnings.append(
                    LintIssue(
                        level="warning",
                        path="behavior_refs",
                        message=f"Behavior '{bref}' not found in known behaviors",
                    )
                )

    # 6. Empty workspace_profiles
    if not manifest.workspace_profiles:
        warnings.append(
            LintIssue(
                level="warning",
                path="workspace_profiles",
                message="No workspace profiles specified; pack will be profile-agnostic",
            )
        )

    valid = len(errors) == 0
    return ValidationResult(valid=valid, errors=errors, warnings=warnings)


# ---------------------------------------------------------------------------
# File-based linting (for CLI)
# ---------------------------------------------------------------------------


def lint_manifest(path: Path) -> List[LintIssue]:
    """Load a manifest JSON file, parse it, validate, and return all issues.

    Returns a flat list of errors + warnings suitable for CLI display.
    """
    issues: List[LintIssue] = []

    # Read file
    if not path.exists():
        issues.append(
            LintIssue(level="error", path=str(path), message="File not found")
        )
        return issues

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        issues.append(
            LintIssue(level="error", path=str(path), message=f"Cannot read file: {exc}")
        )
        return issues

    # Parse JSON
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        issues.append(
            LintIssue(level="error", path=str(path), message=f"Invalid JSON: {exc}")
        )
        return issues

    # Parse into Pydantic model
    try:
        manifest = KnowledgePackManifest.model_validate(data)
    except ValidationError as exc:
        for err in exc.errors():
            loc = " → ".join(str(part) for part in err.get("loc", []))
            issues.append(
                LintIssue(
                    level="error",
                    path=loc,
                    message=err.get("msg", str(err)),
                )
            )
        return issues

    # Semantic validation
    result = validate_manifest(manifest)
    issues.extend(result.errors)
    issues.extend(result.warnings)
    return issues
