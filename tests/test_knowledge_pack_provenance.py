"""Provenance tests for Knowledge Pack extraction.

Verifies:
- Fragment-to-source mapping correctness
- Hash drift detection
- Deterministic extraction (same input → same fragments)

Implements T1.2.3 (AMPREALIZE-300) of the Knowledge Pack Foundations epic.
"""

import hashlib
import tempfile
from pathlib import Path

import pytest

from amprealize.knowledge_pack.extractor import (
    BehaviorFragment,
    DoctrineFragment,
    ExtractionResult,
    PlaybookFragment,
    SourceExtractor,
)
from amprealize.knowledge_pack.source_registry import (
    DriftResult,
    RegisterSourceRequest,
    SourceRecord,
)

pytestmark = [pytest.mark.unit]

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def agents_md_content() -> str:
    """Minimal AGENTS.md with one behavior and two sections."""
    return """\
# Agent Handbook

> TL;DR summary line.

## 🚨 Critical Rules

| Rule | Behavior |
|------|----------|
| Log everything | `behavior_use_raze_for_logging` |

## 📖 Behaviors

### `behavior_use_raze_for_logging`
- **When**: Adding logging to any service.
- **Steps**:
  1. Import RazeLogger.
  2. Configure sink.
  3. Use structured fields.

## 🛠️ Agent Etiquette

- Never hardcode secrets.
- Run pre-commit before pushing.
"""


@pytest.fixture
def playbook_content() -> str:
    """Operational playbook sample."""
    return """\
# Work Management Guide

## Creating Work Items

Steps to create a work item.

## Tracking Progress

Use the dashboard to track.
"""


@pytest.fixture
def extractor() -> SourceExtractor:
    return SourceExtractor()


# ---------------------------------------------------------------------------
# Tests: Doctrine fragment extraction
# ---------------------------------------------------------------------------


class TestDoctrineExtraction:
    def test_extracts_sections_from_agents_md(
        self, extractor: SourceExtractor, agents_md_content: str
    ):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write(agents_md_content)
            path = Path(f.name)

        fragments = extractor.extract_from_agents_md(path)
        path.unlink()

        # Should extract 3 ## sections
        assert len(fragments) == 3
        headings = [frag.section_heading for frag in fragments]
        assert "🚨 Critical Rules" in headings
        assert "📖 Behaviors" in headings
        assert "🛠️ Agent Etiquette" in headings

    def test_fragments_have_source_ref(
        self, extractor: SourceExtractor, agents_md_content: str
    ):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write(agents_md_content)
            path = Path(f.name)

        fragments = extractor.extract_from_agents_md(path)
        path.unlink()

        for frag in fragments:
            assert frag.source_ref == str(path)
            assert frag.scope == "canonical"

    def test_fragment_ids_are_deterministic(
        self, extractor: SourceExtractor, agents_md_content: str
    ):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write(agents_md_content)
            path = Path(f.name)

        run1 = extractor.extract_from_agents_md(path)
        run2 = extractor.extract_from_agents_md(path)
        path.unlink()

        ids1 = [frag.fragment_id for frag in run1]
        ids2 = [frag.fragment_id for frag in run2]
        assert ids1 == ids2, "Fragment IDs must be deterministic"


# ---------------------------------------------------------------------------
# Tests: Behavior fragment extraction
# ---------------------------------------------------------------------------


class TestBehaviorExtraction:
    def test_extracts_behaviors_from_agents_md(
        self, extractor: SourceExtractor, agents_md_content: str
    ):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write(agents_md_content)
            path = Path(f.name)

        fragments = extractor.extract_behaviors_from_agents_md(path)
        path.unlink()

        assert len(fragments) == 1
        frag = fragments[0]
        assert frag.behavior_name == "behavior_use_raze_for_logging"
        assert "RazeLogger" in frag.instruction
        assert "logging" in frag.trigger_keywords

    def test_behavior_fragment_has_role_focus(
        self, extractor: SourceExtractor, agents_md_content: str
    ):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write(agents_md_content)
            path = Path(f.name)

        fragments = extractor.extract_behaviors_from_agents_md(path)
        path.unlink()

        # Logging behavior should infer ENGINEER role
        assert fragments[0].role_focus == "ENGINEER"

    def test_behavior_fragment_ids_deterministic(
        self, extractor: SourceExtractor, agents_md_content: str
    ):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write(agents_md_content)
            path = Path(f.name)

        run1 = extractor.extract_behaviors_from_agents_md(path)
        run2 = extractor.extract_behaviors_from_agents_md(path)
        path.unlink()

        assert run1[0].fragment_id == run2[0].fragment_id


# ---------------------------------------------------------------------------
# Tests: Playbook fragment extraction
# ---------------------------------------------------------------------------


class TestPlaybookExtraction:
    def test_extracts_playbook_sections(
        self, extractor: SourceExtractor, playbook_content: str
    ):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write(playbook_content)
            path = Path(f.name)

        fragments = extractor.extract_from_playbook(path, scope="operational")
        path.unlink()

        assert len(fragments) == 2
        assert all(frag.scope == "operational" for frag in fragments)
        headings = [frag.section_heading for frag in fragments]
        assert "Creating Work Items" in headings
        assert "Tracking Progress" in headings

    def test_playbook_fragment_ids_deterministic(
        self, extractor: SourceExtractor, playbook_content: str
    ):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write(playbook_content)
            path = Path(f.name)

        run1 = extractor.extract_from_playbook(path)
        run2 = extractor.extract_from_playbook(path)
        path.unlink()

        ids1 = [frag.fragment_id for frag in run1]
        ids2 = [frag.fragment_id for frag in run2]
        assert ids1 == ids2


# ---------------------------------------------------------------------------
# Tests: Full extraction orchestration
# ---------------------------------------------------------------------------


class TestExtractAll:
    def test_extract_all_aggregates_fragments(
        self, extractor: SourceExtractor, agents_md_content: str
    ):
        # Create a temp directory and place AGENTS.md in it
        with tempfile.TemporaryDirectory() as tmpdir:
            agents_path = Path(tmpdir) / "AGENTS.md"
            agents_path.write_text(agents_md_content)

            sources = [
                {"source_type": "file", "ref": str(agents_path), "scope": "canonical"}
            ]

            result = extractor.extract_all(sources)

            assert isinstance(result, ExtractionResult)
            assert result.total_fragments > 0
            assert len(result.doctrine_fragments) > 0
            assert len(result.errors) == 0

    def test_extract_all_records_errors_for_missing_files(
        self, extractor: SourceExtractor
    ):
        sources = [
            {"source_type": "file", "ref": "/nonexistent/path.md", "scope": "canonical"}
        ]

        result = extractor.extract_all(sources)

        assert result.total_fragments == 0
        assert len(result.errors) == 1
        assert "not found" in result.errors[0].lower()


# ---------------------------------------------------------------------------
# Tests: Hash drift detection (unit-level stubs)
# ---------------------------------------------------------------------------


class TestDriftDetection:
    """Test drift detection logic without requiring actual database."""

    def test_drift_result_construction(self):
        result = DriftResult(
            source_id="src-123",
            ref="/path/to/file.md",
            stored_hash="abc123",
            current_hash="def456",
            has_drift=True,
        )

        assert result.has_drift is True
        d = result.to_dict()
        assert d["stored_hash"] == "abc123"
        assert d["current_hash"] == "def456"

    def test_no_drift_when_hashes_match(self):
        result = DriftResult(
            source_id="src-123",
            ref="/path/to/file.md",
            stored_hash="abc123",
            current_hash="abc123",
            has_drift=False,
        )

        assert result.has_drift is False

    def test_file_hash_changes_on_content_change(self, agents_md_content: str):
        """Verify SHA-256 changes when content changes."""
        original_hash = hashlib.sha256(agents_md_content.encode()).hexdigest()
        modified_content = agents_md_content + "\n## New Section\n\nNew content."
        modified_hash = hashlib.sha256(modified_content.encode()).hexdigest()

        assert original_hash != modified_hash


# ---------------------------------------------------------------------------
# Tests: Fragment keyword extraction
# ---------------------------------------------------------------------------


class TestKeywordExtraction:
    def test_behavior_keywords_include_name_parts(
        self, extractor: SourceExtractor, agents_md_content: str
    ):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write(agents_md_content)
            path = Path(f.name)

        fragments = extractor.extract_behaviors_from_agents_md(path)
        path.unlink()

        kws = fragments[0].trigger_keywords
        # Should include parts from "behavior_use_raze_for_logging"
        assert "raze" in kws
        assert "logging" in kws

    def test_doctrine_keywords_from_content(
        self, extractor: SourceExtractor, agents_md_content: str
    ):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write(agents_md_content)
            path = Path(f.name)

        fragments = extractor.extract_from_agents_md(path)
        path.unlink()

        # Find the etiquette section
        etiquette = next(
            f for f in fragments if "Etiquette" in f.section_heading
        )
        assert "secrets" in etiquette.retrieval_keywords
        assert "hardcode" in etiquette.retrieval_keywords


# ---------------------------------------------------------------------------
# Tests: Role and surface inference
# ---------------------------------------------------------------------------


class TestRoleInference:
    def test_infers_student_role_from_content(
        self, extractor: SourceExtractor
    ):
        content = """\
# Guide

## Student Tasks

The student should execute routine tasks following established patterns.
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write(content)
            path = Path(f.name)

        fragments = extractor.extract_from_playbook(path)
        path.unlink()

        assert "Student" in fragments[0].role_applicability

    def test_infers_vscode_surface_from_content(
        self, extractor: SourceExtractor
    ):
        content = """\
# Guide

## VS Code Integration

The vscode extension provides chat panels.
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write(content)
            path = Path(f.name)

        fragments = extractor.extract_from_playbook(path)
        path.unlink()

        assert "vscode" in fragments[0].surface_applicability
