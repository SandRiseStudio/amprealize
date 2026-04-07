"""
Unit tests for Knowledge Pack schema models and validator.

Tests verify:
- Pydantic model parsing for valid and invalid manifests
- Semver validation on version field
- Pack ID / overlay ID format enforcement
- OverlayKind, PackScope, SourceScope enum values
- validate_manifest() semantic checks
- lint_manifest() file-based entrypoint

Following `behavior_design_test_strategy` (Student).

Run with: pytest tests/test_knowledge_pack_schema.py -v -m unit
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any, Dict

import pytest
from pydantic import ValidationError

from amprealize.knowledge_pack.schema import (
    KnowledgePackManifest,
    LintIssue,
    OverlayFragment,
    OverlayKind,
    PackConstraints,
    PackScope,
    PackSource,
    PackSourceType,
    SourceScope,
    ValidationResult,
)
from amprealize.knowledge_pack.validator import lint_manifest, validate_manifest

# All tests in this module are unit tests (no DB required)
pytestmark = [pytest.mark.unit]


# =============================================================================
# Helpers
# =============================================================================

def _minimal_manifest(**overrides: Any) -> Dict[str, Any]:
    """Return the smallest valid manifest dict, with optional overrides."""
    base: Dict[str, Any] = {
        "pack_id": "test-pack",
        "version": "0.1.0",
        "scope": "workspace",
        "sources": [{"type": "file", "ref": "AGENTS.md"}],
    }
    base.update(overrides)
    return base


def _parse(data: Dict[str, Any]) -> KnowledgePackManifest:
    return KnowledgePackManifest.model_validate(data)


# =============================================================================
# Schema: basic parsing
# =============================================================================


class TestManifestParsing:
    """Test basic model creation and serialisation."""

    def test_minimal_valid_manifest(self) -> None:
        m = _parse(_minimal_manifest())
        assert m.pack_id == "test-pack"
        assert m.version == "0.1.0"
        assert m.scope == PackScope.WORKSPACE
        assert len(m.sources) == 1

    def test_full_manifest_round_trip(self) -> None:
        data = _minimal_manifest(
            workspace_profiles=["python-backend"],
            surfaces=["vscode", "cli"],
            doctrine_fragments=["Always cite behaviours"],
            behavior_refs=["behavior_use_raze_for_logging"],
            task_overlays=["overlay-logging"],
            surface_overlays=["overlay-vscode"],
            constraints={
                "strict_role_declaration": True,
                "strict_behavior_citation": True,
                "mandatory_overlays": ["overlay-logging"],
            },
            created_by="agent:student",
        )
        m = _parse(data)
        out = m.to_dict()

        assert out["pack_id"] == "test-pack"
        assert out["constraints"]["strict_role_declaration"] is True
        assert "overlay-logging" in out["task_overlays"]
        assert out["created_by"] == "agent:student"

    def test_defaults_applied(self) -> None:
        m = _parse(_minimal_manifest())
        assert m.workspace_profiles == []
        assert m.surfaces == []
        assert m.doctrine_fragments == []
        assert m.behavior_refs == []
        assert m.task_overlays == []
        assert m.surface_overlays == []
        assert m.constraints.strict_role_declaration is False
        assert m.constraints.mandatory_overlays == []
        assert m.created_at is None


# =============================================================================
# Schema: ID validation
# =============================================================================


class TestPackIdValidation:
    """Pack ID must be lowercase-alphanumeric-with-hyphens."""

    @pytest.mark.parametrize(
        "pack_id",
        ["my-pack", "a", "abc-123", "0-pack"],
    )
    def test_valid_pack_ids(self, pack_id: str) -> None:
        m = _parse(_minimal_manifest(pack_id=pack_id))
        assert m.pack_id == pack_id

    @pytest.mark.parametrize(
        "pack_id",
        [
            "My-Pack",      # uppercase
            "-leading",     # leading hyphen
            "spaces here",  # spaces
            "",             # empty
            "under_score",  # underscore
        ],
    )
    def test_invalid_pack_ids(self, pack_id: str) -> None:
        with pytest.raises(ValidationError):
            _parse(_minimal_manifest(pack_id=pack_id))


# =============================================================================
# Schema: semver validation
# =============================================================================


class TestSemverValidation:
    """Version must be valid semver."""

    @pytest.mark.parametrize(
        "version",
        ["0.1.0", "1.0.0", "1.2.3-alpha.1", "1.2.3+build.42", "10.20.30"],
    )
    def test_valid_semver(self, version: str) -> None:
        m = _parse(_minimal_manifest(version=version))
        assert m.version == version

    @pytest.mark.parametrize(
        "version",
        [
            "1.0",       # missing patch
            "v1.0.0",    # leading v
            "1.0.0.0",   # too many parts
            "abc",       # not numeric
            "",          # empty
        ],
    )
    def test_invalid_semver(self, version: str) -> None:
        with pytest.raises(ValidationError):
            _parse(_minimal_manifest(version=version))


# =============================================================================
# Schema: overlay fragment
# =============================================================================


class TestOverlayFragment:
    """OverlayFragment model validation."""

    def test_valid_overlay(self) -> None:
        o = OverlayFragment(
            overlay_id="task-logging",
            kind=OverlayKind.TASK,
            applies_to={"task_type": "logging"},
            instructions=["Use Raze"],
            retrieval_keywords=["logging", "raze"],
            priority=10,
        )
        assert o.overlay_id == "task-logging"
        assert o.kind == OverlayKind.TASK

    @pytest.mark.parametrize(
        "bad_id",
        ["BadId", "-leading", "has space", "UPPER"],
    )
    def test_invalid_overlay_id(self, bad_id: str) -> None:
        with pytest.raises(ValidationError):
            OverlayFragment(overlay_id=bad_id, kind=OverlayKind.TASK)

    def test_default_priority_zero(self) -> None:
        o = OverlayFragment(overlay_id="basic", kind=OverlayKind.SURFACE)
        assert o.priority == 0

    def test_priority_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            OverlayFragment(overlay_id="basic", kind=OverlayKind.TASK, priority=-1)


# =============================================================================
# Schema: enums
# =============================================================================


class TestEnums:
    """Enum values match architecture doc."""

    def test_pack_source_types(self) -> None:
        assert set(PackSourceType) == {PackSourceType.FILE, PackSourceType.SERVICE}

    def test_source_scopes(self) -> None:
        assert set(SourceScope) == {
            SourceScope.CANONICAL,
            SourceScope.OPERATIONAL,
            SourceScope.SURFACE,
            SourceScope.RUNTIME,
        }

    def test_overlay_kinds(self) -> None:
        assert set(OverlayKind) == {
            OverlayKind.TASK,
            OverlayKind.SURFACE,
            OverlayKind.ROLE,
        }


# =============================================================================
# Validator: validate_manifest
# =============================================================================


class TestValidateManifest:
    """Semantic validation beyond Pydantic field checks."""

    def test_valid_manifest_passes(self) -> None:
        m = _parse(
            _minimal_manifest(
                task_overlays=["overlay-a"],
                workspace_profiles=["python"],
            )
        )
        result = validate_manifest(m)
        assert result.valid is True
        assert result.errors == []

    def test_duplicate_overlay_ids_error(self) -> None:
        m = _parse(
            _minimal_manifest(
                task_overlays=["dup-overlay"],
                surface_overlays=["dup-overlay"],
            )
        )
        result = validate_manifest(m)
        assert result.valid is False
        assert any("Duplicate overlay" in e.message for e in result.errors)

    def test_no_sources_error(self) -> None:
        m = _parse(_minimal_manifest(sources=[]))
        result = validate_manifest(m)
        assert result.valid is False
        assert any("at least one source" in e.message for e in result.errors)

    def test_duplicate_source_refs_error(self) -> None:
        m = _parse(
            _minimal_manifest(
                sources=[
                    {"type": "file", "ref": "AGENTS.md"},
                    {"type": "file", "ref": "AGENTS.md"},
                ]
            )
        )
        result = validate_manifest(m)
        assert result.valid is False
        assert any("Duplicate source ref" in e.message for e in result.errors)

    def test_mandatory_overlay_not_listed(self) -> None:
        m = _parse(
            _minimal_manifest(
                constraints={
                    "mandatory_overlays": ["missing-overlay"],
                },
                task_overlays=[],
                surface_overlays=[],
            )
        )
        result = validate_manifest(m)
        assert result.valid is False
        assert any("Mandatory overlay" in e.message for e in result.errors)

    def test_unknown_behavior_ref_warning(self) -> None:
        m = _parse(
            _minimal_manifest(
                behavior_refs=["behavior_unknown"],
                workspace_profiles=["python"],
            )
        )
        result = validate_manifest(
            m, known_behavior_names=["behavior_use_raze_for_logging"]
        )
        assert result.valid is True  # warnings don't fail
        assert any("not found in known behaviors" in w.message for w in result.warnings)

    def test_known_behavior_ref_no_warning(self) -> None:
        m = _parse(
            _minimal_manifest(
                behavior_refs=["behavior_use_raze_for_logging"],
                workspace_profiles=["python"],
            )
        )
        result = validate_manifest(
            m, known_behavior_names=["behavior_use_raze_for_logging"]
        )
        assert not any("not found" in w.message for w in result.warnings)

    def test_empty_workspace_profiles_warning(self) -> None:
        m = _parse(_minimal_manifest(workspace_profiles=[]))
        result = validate_manifest(m)
        assert any("No workspace profiles" in w.message for w in result.warnings)

    def test_no_behavior_check_when_not_supplied(self) -> None:
        m = _parse(
            _minimal_manifest(
                behavior_refs=["behavior_anything"],
                workspace_profiles=["python"],
            )
        )
        result = validate_manifest(m, known_behavior_names=None)
        assert not any("not found" in w.message for w in result.warnings)


# =============================================================================
# Validator: lint_manifest (file-based)
# =============================================================================


class TestLintManifest:
    """File-based lint entrypoint."""

    def test_valid_file(self, tmp_path: Path) -> None:
        f = tmp_path / "pack.json"
        f.write_text(json.dumps(_minimal_manifest(workspace_profiles=["py"])))
        issues = lint_manifest(f)
        # Should have no errors (might have info-level only)
        assert not any(i.level == "error" for i in issues)

    def test_missing_file(self, tmp_path: Path) -> None:
        issues = lint_manifest(tmp_path / "nonexistent.json")
        assert len(issues) == 1
        assert issues[0].level == "error"
        assert "not found" in issues[0].message.lower()

    def test_invalid_json(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.json"
        f.write_text("{not valid json}")
        issues = lint_manifest(f)
        assert any(i.level == "error" and "JSON" in i.message for i in issues)

    def test_schema_violation(self, tmp_path: Path) -> None:
        f = tmp_path / "bad_schema.json"
        f.write_text(json.dumps({"pack_id": "UPPER", "version": "abc"}))
        issues = lint_manifest(f)
        assert any(i.level == "error" for i in issues)

    def test_semantic_errors_surfaced(self, tmp_path: Path) -> None:
        data = _minimal_manifest(
            sources=[
                {"type": "file", "ref": "AGENTS.md"},
                {"type": "file", "ref": "AGENTS.md"},
            ],
        )
        f = tmp_path / "dup.json"
        f.write_text(json.dumps(data))
        issues = lint_manifest(f)
        assert any("Duplicate source ref" in i.message for i in issues)
