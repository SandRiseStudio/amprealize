"""Tests for GWS title validation (amprealize-487)."""

import pytest

from amprealize.agents.work_item_planner.prompts import (
    GWS_VERSION,
    GWS_TITLE_PATTERNS,
    GWS_COMPACT_SUMMARY,
    GWS_CONVENTION_TEXT,
    validate_title,
)


class TestValidateTitle:
    """Test GWS title validation rules."""

    # ── Valid titles ──────────────────────────────────────────────────────

    @pytest.mark.unit
    @pytest.mark.parametrize("item_type,title", [
        ("goal", "Standardize Work Item Creation Across Agents"),
        ("goal", "Implement User Authentication with OAuth2"),
        ("feature", "Add GWS Title Validation to MCP Handler"),
        ("feature", "Create Login and Signup Pages"),
        ("task", "Write unit tests for title regex"),
        ("task", "Update README with new API docs"),
        ("bug", "Fix race condition in board column reorder"),
        ("bug", "Resolve null pointer in pagination logic"),
    ])
    def test_valid_titles_accepted(self, item_type: str, title: str) -> None:
        assert validate_title(item_type, title) is None

    # ── Anti-pattern: Phase/Sprint/Track numbering ────────────────────────

    @pytest.mark.unit
    @pytest.mark.parametrize("title", [
        "Phase 1: Work Items",
        "Sprint 3 - Implement auth",
        "Track 2: Backend work",
        "Milestone 4 Deploy",
    ])
    def test_phase_sprint_track_rejected(self, title: str) -> None:
        error = validate_title("goal", title)
        assert error is not None
        assert "Phase/Track/Sprint/Milestone" in error

    # ── Anti-pattern: Type-number prefixes ────────────────────────────────

    @pytest.mark.unit
    @pytest.mark.parametrize("title", [
        "EPIC-001 Standardize naming",
        "STORY-42 Add validation",
        "TASK-99 Write tests",
        "BUG-12 Fix crash",
        "FEAT-5 New feature",
        "ISSUE-100 Track bug",
    ])
    def test_type_number_prefix_rejected(self, title: str) -> None:
        error = validate_title("feature", title)
        assert error is not None
        assert "type-number codes" in error

    # ── Anti-pattern: Manual numbering ────────────────────────────────────

    @pytest.mark.unit
    @pytest.mark.parametrize("title", [
        "1. Do the first thing",
        "42. Implement feature",
        "3) Write tests",
        "7 - Deploy service",
    ])
    def test_manual_numbering_rejected(self, title: str) -> None:
        error = validate_title("task", title)
        assert error is not None
        assert "manual numbering" in error

    # ── Anti-pattern: Status prefixes ─────────────────────────────────────

    @pytest.mark.unit
    @pytest.mark.parametrize("title", [
        "TODO fix the tests",
        "WIP adding auth",
        "DRAFT new feature spec",
        "TBD figure out approach",
        "FIXME broken endpoint",
    ])
    def test_status_prefix_rejected(self, title: str) -> None:
        error = validate_title("task", title)
        assert error is not None
        assert "TODO/WIP/DRAFT/TBD/FIXME" in error

    # ── Pattern: must start with uppercase ────────────────────────────────

    @pytest.mark.unit
    def test_lowercase_start_rejected(self) -> None:
        error = validate_title("goal", "implement something new")
        assert error is not None
        assert "uppercase" in error

    # ── Pattern: length constraints ───────────────────────────────────────

    @pytest.mark.unit
    def test_too_short_rejected(self) -> None:
        error = validate_title("goal", "Fix")
        assert error is not None

    @pytest.mark.unit
    def test_too_long_rejected(self) -> None:
        title = "A" + "a" * 121
        error = validate_title("goal", title)
        assert error is not None

    # ── Includes GWS version in error messages ────────────────────────────

    @pytest.mark.unit
    def test_error_includes_version(self) -> None:
        error = validate_title("goal", "Phase 1: Bad title")
        assert error is not None
        assert f"GWS v{GWS_VERSION}" in error

    # ── Constants exist and are non-empty ─────────────────────────────────

    @pytest.mark.unit
    def test_constants_exist(self) -> None:
        assert GWS_VERSION == "1.0"
        assert len(GWS_TITLE_PATTERNS) == 4
        assert "goal" in GWS_TITLE_PATTERNS
        assert "feature" in GWS_TITLE_PATTERNS
        assert "task" in GWS_TITLE_PATTERNS
        assert "bug" in GWS_TITLE_PATTERNS
        assert len(GWS_COMPACT_SUMMARY) > 50
        assert len(GWS_CONVENTION_TEXT) > 100

    # ── Unknown item_type passes through ──────────────────────────────────

    @pytest.mark.unit
    def test_unknown_type_no_pattern_check(self) -> None:
        # Still checks anti-patterns but no type-specific pattern
        result = validate_title("unknown_type", "Valid Title Here")
        assert result is None

    @pytest.mark.unit
    def test_unknown_type_still_catches_anti_patterns(self) -> None:
        error = validate_title("unknown_type", "Phase 1: Bad title")
        assert error is not None

    # ── Valid titles with technical characters ────────────────────────────

    @pytest.mark.unit
    @pytest.mark.parametrize("item_type,title", [
        ("task", "Update settings.py configuration"),
        ("task", "Fix snake_case naming in module"),
        ("feature", "Add `backtick` support to parser"),
        ("task", "Migrate data → new schema format"),
        ("feature", "Implement <T> generic type support"),
        ("task", 'Handle "quoted" strings in parser'),
        ("task", "Add [optional] parameter support"),
        ("task", "Install pytest + coverage tools"),
        ("feature", "Add #tag search to dashboard"),
        ("feature", "Support @mention notifications"),
        ("task", "Add wildcard *.py glob matching"),
        ("task", "Fix parser? Handle edge cases!"),
        ("task", "Set timeout=30; retry=3 defaults"),
        ("task", "Update ~home path resolution"),
    ])
    def test_technical_characters_accepted(self, item_type: str, title: str) -> None:
        assert validate_title(item_type, title) is None

    # ── Anti-pattern: Coded-section prefixes ──────────────────────────────

    @pytest.mark.unit
    @pytest.mark.parametrize("title", [
        "A1: Credential Rotation",
        "S1.1 — Define Knowledge Pack",
        "T1.1.1 — Draft manifest schema",
        "A1-T1: Delete leaked credential",
        "E1 — Knowledge Pack Foundations",
        "B2: Cloud SaaS Setup",
    ])
    def test_coded_section_prefix_rejected(self, title: str) -> None:
        error = validate_title("task", title)
        assert error is not None
        assert "coded-section" in error

    # ── Anti-pattern: Bracket-type prefixes ───────────────────────────────

    @pytest.mark.unit
    @pytest.mark.parametrize("title", [
        "[Bug] Device flow verification fails",
        "[Feature] Add new dashboard widget",
        "[WIP] Refactor auth module",
    ])
    def test_bracket_prefix_rejected(self, title: str) -> None:
        error = validate_title("task", title)
        assert error is not None
        assert "brackets" in error
