"""Tests for amprealize.knowledge_pack.overlay_rules — classification rules.

Covers:
- TaskClassificationRule matching
- SurfaceClassificationRule matching
- RoleClassificationRule matching
- OverlayClassifier integration
- Filter helper functions
"""

import pytest

from amprealize.knowledge_pack.overlay_rules import (
    DEFAULT_ROLE_RULES,
    DEFAULT_SURFACE_RULES,
    DEFAULT_TASK_RULES,
    OverlayClassifier,
    Role,
    RoleClassificationRule,
    Surface,
    SurfaceClassificationRule,
    TaskClassificationRule,
    TaskFamily,
    default_classifier,
    filter_overlays_by_role,
    filter_overlays_by_surface,
    filter_overlays_by_task,
)

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# TaskClassificationRule tests
# ---------------------------------------------------------------------------


class TestTaskClassificationRule:
    def test_keyword_match(self):
        rule = TaskClassificationRule(
            family=TaskFamily.TESTING,
            keywords={"pytest", "unittest"},
        )
        assert rule.matches("Run pytest on this file")
        assert rule.matches("Add UNITTEST for the module")  # case-insensitive
        assert not rule.matches("Add a new feature")

    def test_pattern_match(self):
        rule = TaskClassificationRule(
            family=TaskFamily.TESTING,
            patterns=[r"test_\w+\.py"],
        )
        assert rule.matches("Edit test_schema.py")
        assert not rule.matches("Edit schema.py")

    def test_empty_rule_matches_nothing(self):
        rule = TaskClassificationRule(family=TaskFamily.GENERAL)
        assert not rule.matches("anything at all")

    def test_priority_preserved(self):
        rule = TaskClassificationRule(
            family=TaskFamily.INCIDENT,
            keywords={"incident"},
            priority=5,
        )
        assert rule.priority == 5


# ---------------------------------------------------------------------------
# SurfaceClassificationRule tests
# ---------------------------------------------------------------------------


class TestSurfaceClassificationRule:
    def test_keyword_match(self):
        rule = SurfaceClassificationRule(
            surface=Surface.CLI,
            keywords={"cli", "terminal"},
        )
        assert rule.matches("Add a CLI command")
        assert not rule.matches("Add a web page")

    def test_pattern_match(self):
        rule = SurfaceClassificationRule(
            surface=Surface.MCP,
            patterns=[r"mcp_server"],
        )
        assert rule.matches("Update mcp_server.py")
        assert not rule.matches("Update server.py")

    def test_file_extension_match(self):
        rule = SurfaceClassificationRule(
            surface=Surface.VSCODE,
            file_extensions={"vsix"},
        )
        assert rule.matches("install", file_path="extension.vsix")
        assert not rule.matches("install", file_path="extension.zip")

    def test_file_path_without_extension(self):
        rule = SurfaceClassificationRule(
            surface=Surface.VSCODE,
            file_extensions={"vsix"},
        )
        # No extension in path, no match
        assert not rule.matches("build", file_path="Makefile")


# ---------------------------------------------------------------------------
# RoleClassificationRule tests
# ---------------------------------------------------------------------------


class TestRoleClassificationRule:
    def test_keyword_match(self):
        rule = RoleClassificationRule(
            role=Role.STUDENT,
            keywords={"student", "routine"},
        )
        assert rule.matches("Acting as student role")
        assert rule.matches("This is a routine task")
        assert not rule.matches("Create architecture document")

    def test_pattern_match(self):
        rule = RoleClassificationRule(
            role=Role.STRATEGIST,
            patterns=[r"root\s+cause\s+analysis"],
        )
        assert rule.matches("Perform root cause analysis")
        assert not rule.matches("Analyze the code")


# ---------------------------------------------------------------------------
# Default rule sets existence
# ---------------------------------------------------------------------------


class TestDefaultRules:
    def test_task_rules_populated(self):
        assert len(DEFAULT_TASK_RULES) >= 7  # At least 7 families defined

    def test_surface_rules_populated(self):
        assert len(DEFAULT_SURFACE_RULES) >= 5

    def test_role_rules_populated(self):
        assert len(DEFAULT_ROLE_RULES) >= 3


# ---------------------------------------------------------------------------
# OverlayClassifier tests
# ---------------------------------------------------------------------------


class TestOverlayClassifier:
    def test_classify_task_docs(self):
        classifier = OverlayClassifier()
        result = classifier.classify_task("Update the README documentation")
        assert result == TaskFamily.DOCS

    def test_classify_task_testing(self):
        classifier = OverlayClassifier()
        result = classifier.classify_task("Add pytest coverage")
        assert result == TaskFamily.TESTING

    def test_classify_task_incident_high_priority(self):
        classifier = OverlayClassifier()
        # Incident has higher priority than other matches
        result = classifier.classify_task("Document the incident postmortem")
        assert result == TaskFamily.INCIDENT

    def test_classify_task_fallback_to_general(self):
        classifier = OverlayClassifier()
        result = classifier.classify_task("Do something completely random xyz")
        assert result == TaskFamily.GENERAL

    def test_classify_surfaces_single(self):
        classifier = OverlayClassifier()
        surfaces = classifier.classify_surfaces("Add a cli command for build")
        assert Surface.CLI in surfaces

    def test_classify_surfaces_multiple(self):
        classifier = OverlayClassifier()
        # Text mentions both CLI and MCP
        surfaces = classifier.classify_surfaces(
            "Add MCP tool and CLI command for the feature"
        )
        assert Surface.CLI in surfaces
        assert Surface.MCP in surfaces

    def test_classify_surfaces_none(self):
        classifier = OverlayClassifier()
        surfaces = classifier.classify_surfaces("something completely unrelated xyz")
        assert surfaces == []

    def test_classify_role_student(self):
        classifier = OverlayClassifier()
        result = classifier.classify_role("As a student, follow the established behavior")
        assert result == Role.STUDENT

    def test_classify_role_teacher(self):
        classifier = OverlayClassifier()
        result = classifier.classify_role("Create example documentation")
        assert result == Role.TEACHER

    def test_classify_role_strategist(self):
        classifier = OverlayClassifier()
        result = classifier.classify_role("Perform root cause analysis on the bug")
        assert result == Role.STRATEGIST

    def test_classify_role_fallback_to_engineer(self):
        classifier = OverlayClassifier()
        result = classifier.classify_role("Just build a feature")
        assert result == Role.ENGINEER

    def test_classify_all_returns_dict(self):
        classifier = OverlayClassifier()
        result = classifier.classify_all(
            "Add CLI command for testing",
            file_path="test_main.py",
        )
        assert "task_family" in result
        assert "surfaces" in result
        assert "role" in result
        assert result["task_family"] == TaskFamily.TESTING
        assert Surface.CLI in result["surfaces"]

    def test_custom_rules(self):
        # Custom rule set with only one task rule
        custom_rules = [
            TaskClassificationRule(
                family=TaskFamily.DEPLOYMENT,
                keywords={"ship"},
                priority=10,
            )
        ]
        classifier = OverlayClassifier(task_rules=custom_rules)
        result = classifier.classify_task("ship this code")
        assert result == TaskFamily.DEPLOYMENT


# ---------------------------------------------------------------------------
# Filter helpers
# ---------------------------------------------------------------------------


class TestFilterHelpers:
    def test_filter_overlays_by_task(self):
        overlays = [
            {"overlay_id": "o1", "applies_to": {"task_family": "testing"}},
            {"overlay_id": "o2", "applies_to": {"task_family": "docs"}},
            {"overlay_id": "o3", "applies_to": {"surface": "cli"}},
        ]
        result = filter_overlays_by_task(overlays, TaskFamily.TESTING)
        assert len(result) == 1
        assert result[0]["overlay_id"] == "o1"

    def test_filter_overlays_by_surface(self):
        overlays = [
            {"overlay_id": "o1", "applies_to": {"surface": "cli"}},
            {"overlay_id": "o2", "applies_to": {"surface": "mcp"}},
            {"overlay_id": "o3", "applies_to": {"role": "student"}},
        ]
        result = filter_overlays_by_surface(overlays, Surface.CLI)
        assert len(result) == 1
        assert result[0]["overlay_id"] == "o1"

    def test_filter_overlays_by_role(self):
        overlays = [
            {"overlay_id": "o1", "applies_to": {"role": "student"}},
            {"overlay_id": "o2", "applies_to": {"role": "teacher"}},
            {"overlay_id": "o3", "applies_to": {"task_family": "testing"}},
        ]
        result = filter_overlays_by_role(overlays, Role.STUDENT)
        assert len(result) == 1
        assert result[0]["overlay_id"] == "o1"

    def test_filter_empty_list(self):
        assert filter_overlays_by_task([], TaskFamily.DOCS) == []
        assert filter_overlays_by_surface([], Surface.CLI) == []
        assert filter_overlays_by_role([], Role.STUDENT) == []


# ---------------------------------------------------------------------------
# Default classifier singleton
# ---------------------------------------------------------------------------


class TestDefaultClassifier:
    def test_default_classifier_exists(self):
        assert default_classifier is not None
        assert isinstance(default_classifier, OverlayClassifier)

    def test_default_classifier_works(self):
        # Quick sanity check
        result = default_classifier.classify_task("run pytest")
        assert result == TaskFamily.TESTING


# ---------------------------------------------------------------------------
# Regression: case insensitivity
# ---------------------------------------------------------------------------


class TestCaseInsensitivity:
    def test_keywords_case_insensitive(self):
        classifier = OverlayClassifier()
        # All caps
        assert classifier.classify_task("PYTEST coverage") == TaskFamily.TESTING
        # Mixed case
        assert classifier.classify_task("PyTest coverage") == TaskFamily.TESTING

    def test_patterns_case_insensitive(self):
        classifier = OverlayClassifier()
        # Pattern r"\bdocs?\b" should match "DOCS"
        assert classifier.classify_task("Update the DOCS") == TaskFamily.DOCS


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_text(self):
        classifier = OverlayClassifier()
        assert classifier.classify_task("") == TaskFamily.GENERAL
        assert classifier.classify_surfaces("") == []
        assert classifier.classify_role("") == Role.ENGINEER

    def test_whitespace_only(self):
        classifier = OverlayClassifier()
        assert classifier.classify_task("   \n\t  ") == TaskFamily.GENERAL

    def test_special_characters(self):
        classifier = OverlayClassifier()
        # Should not crash
        result = classifier.classify_task("@#$%^&*()[]{}|\\")
        assert result == TaskFamily.GENERAL
