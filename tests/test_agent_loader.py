"""
Tests for AgentPlaybookLoader - Dynamic agent loading from markdown playbooks.

Tests cover:
- Playbook discovery
- Markdown parsing
- Behavior extraction
- Capability extraction
- Role alignment inference
- Integration with AgentOrchestratorService

These are unit tests that don't require database infrastructure.
"""

import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pytest

# Mark all tests in this module as unit tests (skip infrastructure check)
pytestmark = pytest.mark.unit

from amprealize.services.agent_loader import (
    AgentPlaybookLoader,
    ParsedPlaybook,
    load_agent_personas,
)


# Sample playbook content for testing
SAMPLE_PLAYBOOK = """
# Test Agent Playbook

## Mission
This is a test agent for validating the playbook loader.
It should apply `behavior_test_one` and `behavior_test_two`.

## Required Inputs Before Review
- Document A
- Document B

## Review Checklist
1. **Code Quality** – Ensure tests pass and coverage meets threshold.
2. **Documentation** – Verify README is updated per `behavior_update_docs_after_changes`.
3. **Security** – Check for secrets using `behavior_prevent_secret_leaks`.

## Decision Rubric
| Dimension | Guiding Questions |
| --- | --- |
| Feasibility | Is this achievable with current resources? |
| Quality | Does it meet our standards? |

## Output Template
```
### Test Agent Review
**Summary:** ...
```

## Escalation Rules
- Escalate to lead if blocked for 24 hours.

## Behavior Contributions
When patterns emerge, propose new behaviors like `behavior_test_pattern`.
"""

MINIMAL_PLAYBOOK = """
# Minimal Agent

## Mission
A minimal test agent.
"""

STRATEGIST_PLAYBOOK = """
# Strategic Agent Playbook

## Mission
Plan, design, and architect solutions for complex problems.
Research patterns and create strategic roadmaps.

## Required Inputs
- Architecture documents
- Strategic plans
"""


class TestAgentPlaybookLoader:
    """Tests for AgentPlaybookLoader class."""

    def test_discover_playbooks_real_directory(self) -> None:
        """Test discovering playbooks in the actual agents/ directory."""
        loader = AgentPlaybookLoader()
        playbooks = loader.discover_playbooks()

        # Should find playbooks in the project's agents/ directory
        assert len(playbooks) >= 1
        assert all(p.name.startswith("AGENT_") for p in playbooks)
        assert all(p.suffix == ".md" for p in playbooks)

    def test_discover_playbooks_empty_directory(self, tmp_path: Path) -> None:
        """Test discovering playbooks in an empty directory."""
        loader = AgentPlaybookLoader(agents_dir=tmp_path)
        playbooks = loader.discover_playbooks()
        assert playbooks == []

    def test_discover_playbooks_nonexistent_directory(self) -> None:
        """Test discovering playbooks in a nonexistent directory."""
        loader = AgentPlaybookLoader(agents_dir=Path("/nonexistent/path"))
        playbooks = loader.discover_playbooks()
        assert playbooks == []

    def test_parse_playbook_full(self, tmp_path: Path) -> None:
        """Test parsing a full playbook with all sections."""
        playbook_path = tmp_path / "AGENT_TEST.md"
        playbook_path.write_text(SAMPLE_PLAYBOOK)

        loader = AgentPlaybookLoader(agents_dir=tmp_path)
        parsed = loader.parse_playbook(playbook_path)

        assert parsed is not None
        assert parsed.agent_id == "test"
        assert parsed.display_name == "Test Agent"
        assert "test agent for validating" in parsed.mission

        # Behaviors should be extracted
        assert "behavior_test_one" in parsed.default_behaviors
        assert "behavior_test_two" in parsed.default_behaviors
        assert "behavior_update_docs_after_changes" in parsed.default_behaviors
        assert "behavior_prevent_secret_leaks" in parsed.default_behaviors

        # Capabilities from checklist
        assert "code_quality" in parsed.capabilities
        assert "documentation" in parsed.capabilities
        assert "security" in parsed.capabilities

    def test_parse_playbook_minimal(self, tmp_path: Path) -> None:
        """Test parsing a minimal playbook."""
        playbook_path = tmp_path / "AGENT_MINIMAL.md"
        playbook_path.write_text(MINIMAL_PLAYBOOK)

        loader = AgentPlaybookLoader(agents_dir=tmp_path)
        parsed = loader.parse_playbook(playbook_path)

        assert parsed is not None
        assert parsed.agent_id == "minimal"
        assert parsed.display_name == "Minimal Agent"
        assert parsed.mission == "A minimal test agent."
        assert parsed.default_behaviors == []
        assert parsed.capabilities == []

    def test_parse_playbook_agent_id_from_filename(self, tmp_path: Path) -> None:
        """Test that agent_id is correctly derived from filename."""
        test_cases = [
            ("AGENT_DATA_SCIENCE.md", "data_science"),
            ("AGENT_DX.md", "dx"),
            ("AGENT_AI_RESEARCH.md", "ai_research"),
        ]

        loader = AgentPlaybookLoader(agents_dir=tmp_path)

        for filename, expected_id in test_cases:
            playbook_path = tmp_path / filename
            playbook_path.write_text(MINIMAL_PLAYBOOK)

            parsed = loader.parse_playbook(playbook_path)
            assert parsed is not None
            assert parsed.agent_id == expected_id

            playbook_path.unlink()  # Clean up for next iteration

    def test_extract_behaviors(self, tmp_path: Path) -> None:
        """Test behavior extraction from content."""
        loader = AgentPlaybookLoader(agents_dir=tmp_path)

        content = """
        Use `behavior_test` and behavior_another.
        Also apply `behavior_third` multiple times.
        `behavior_test` should only appear once.
        """

        behaviors = loader._extract_behaviors(content)

        assert "behavior_test" in behaviors
        assert "behavior_another" in behaviors
        assert "behavior_third" in behaviors
        # Should be deduplicated
        assert len([b for b in behaviors if b == "behavior_test"]) == 1

    def test_infer_role_alignment_strategist(self, tmp_path: Path) -> None:
        """Test that strategic content infers STRATEGIST role."""
        playbook_path = tmp_path / "AGENT_STRATEGIC.md"
        playbook_path.write_text(STRATEGIST_PLAYBOOK)

        loader = AgentPlaybookLoader(agents_dir=tmp_path)
        parsed = loader.parse_playbook(playbook_path)

        assert parsed is not None
        assert parsed.role_alignment == "STRATEGIST"

    def test_infer_role_alignment_teacher(self, tmp_path: Path) -> None:
        """Test that review/validate content infers TEACHER role."""
        content = """
        # Review Agent Playbook

        ## Mission
        Review, validate, and ensure compliance with standards.
        Audit all submissions for quality.
        """

        playbook_path = tmp_path / "AGENT_REVIEW.md"
        playbook_path.write_text(content)

        loader = AgentPlaybookLoader(agents_dir=tmp_path)
        parsed = loader.parse_playbook(playbook_path)

        assert parsed is not None
        assert parsed.role_alignment == "TEACHER"

    def test_load_all(self, tmp_path: Path) -> None:
        """Test loading all playbooks from a directory."""
        # Create multiple playbooks
        (tmp_path / "AGENT_ONE.md").write_text(MINIMAL_PLAYBOOK)
        (tmp_path / "AGENT_TWO.md").write_text(SAMPLE_PLAYBOOK)
        (tmp_path / "README.md").write_text("# Not an agent")  # Should be ignored

        loader = AgentPlaybookLoader(agents_dir=tmp_path)
        playbooks = loader.load_all()

        assert len(playbooks) == 2
        agent_ids = [p.agent_id for p in playbooks]
        assert "one" in agent_ids
        assert "two" in agent_ids

    def test_to_persona_defs_format(self, tmp_path: Path) -> None:
        """Test that to_persona_defs returns correct format."""
        (tmp_path / "AGENT_FORMAT_TEST.md").write_text(SAMPLE_PLAYBOOK)

        loader = AgentPlaybookLoader(agents_dir=tmp_path)
        defs = loader.to_persona_defs()

        assert len(defs) == 1
        persona = defs[0]

        # Check all required keys
        assert "agent_id" in persona
        assert "display_name" in persona
        assert "role_alignment" in persona
        assert "default_behaviors" in persona
        assert "playbook_refs" in persona
        assert "capabilities" in persona

        # Check types
        assert isinstance(persona["agent_id"], str)
        assert isinstance(persona["display_name"], str)
        assert isinstance(persona["role_alignment"], str)
        assert isinstance(persona["default_behaviors"], list)
        assert isinstance(persona["playbook_refs"], list)
        assert isinstance(persona["capabilities"], list)


class TestLoadAgentPersonasFunction:
    """Tests for the convenience function."""

    def test_load_agent_personas_real(self) -> None:
        """Test loading from the real agents directory."""
        personas = load_agent_personas()

        # Should load at least some agents
        assert len(personas) >= 1

        # Each persona should have required keys
        for persona in personas:
            assert "agent_id" in persona
            assert "display_name" in persona
            assert "role_alignment" in persona

    def test_load_agent_personas_custom_dir(self, tmp_path: Path) -> None:
        """Test loading from a custom directory."""
        (tmp_path / "AGENT_CUSTOM.md").write_text(MINIMAL_PLAYBOOK)

        personas = load_agent_personas(agents_dir=tmp_path)

        assert len(personas) == 1
        assert personas[0]["agent_id"] == "custom"


class TestIntegrationWithOrchestratorService:
    """Integration tests with AgentOrchestratorService."""

    def test_orchestrator_loads_dynamically(self) -> None:
        """Test that AgentOrchestratorService loads agents from playbooks."""
        from amprealize.agent_orchestrator_service import AgentOrchestratorService

        service = AgentOrchestratorService()
        personas = service.list_personas()

        # Should have loaded agents from playbooks
        assert len(personas) >= 1

        # Should include standard agents
        agent_ids = [p.agent_id for p in personas]
        # At least engineering should be present
        assert "engineering" in agent_ids

    def test_orchestrator_reload(self, tmp_path: Path) -> None:
        """Test reloading personas at runtime."""
        from amprealize.agent_orchestrator_service import AgentOrchestratorService

        service = AgentOrchestratorService()
        initial_count = len(service.list_personas())

        # Re-listing should work without error
        reloaded_count = len(service.list_personas())
        assert reloaded_count == initial_count

    def test_orchestrator_assign_agent_with_dynamic_personas(self) -> None:
        """Test assigning agents with dynamically loaded personas."""
        from amprealize.agent_orchestrator_service import AgentOrchestratorService

        service = AgentOrchestratorService()

        # Assign an agent
        assignment = service.assign_agent(
            run_id="test-run-123",
            requested_agent_id="engineering",
            stage="review",
            context={"task_type": "code_review"},
            requested_by={"user": "test"},
        )

        assert assignment is not None
        assert assignment.active_agent.agent_id == "engineering"
        assert assignment.run_id == "test-run-123"


class TestEdgeCases:
    """Edge case tests."""

    def test_malformed_playbook(self, tmp_path: Path) -> None:
        """Test handling of malformed playbook files."""
        # No title
        (tmp_path / "AGENT_NOTITLE.md").write_text("Just some text without headers")

        loader = AgentPlaybookLoader(agents_dir=tmp_path)
        parsed = loader.parse_playbook(tmp_path / "AGENT_NOTITLE.md")

        # Should still parse with defaults
        assert parsed is not None
        assert parsed.agent_id == "notitle"
        assert "Notitle Agent" in parsed.display_name

    def test_unicode_content(self, tmp_path: Path) -> None:
        """Test handling of unicode content in playbooks."""
        content = """# Unicode Agent Playbook 🚀

## Mission
Handle internationalization: 日本語, 中文, العربية
"""

        playbook_path = tmp_path / "AGENT_UNICODE.md"
        playbook_path.write_text(content, encoding="utf-8")

        loader = AgentPlaybookLoader(agents_dir=tmp_path)
        parsed = loader.parse_playbook(playbook_path)

        assert parsed is not None
        assert "internationalization" in parsed.mission

    def test_empty_file(self, tmp_path: Path) -> None:
        """Test handling of empty playbook files."""
        (tmp_path / "AGENT_EMPTY.md").write_text("")

        loader = AgentPlaybookLoader(agents_dir=tmp_path)
        parsed = loader.parse_playbook(tmp_path / "AGENT_EMPTY.md")

        assert parsed is not None
        assert parsed.agent_id == "empty"
        assert parsed.mission == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
