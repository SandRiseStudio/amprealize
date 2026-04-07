"""Unit tests for BootstrapService.

Tests the orchestration layer for workspace bootstrap including:
- Profile detection delegation
- Pack selection based on profile
- Profile-scoped primer generation
- Full bootstrap workflow
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from amprealize.bootstrap.service import (
    BootstrapService,
    BootstrapResult,
    _PROFILE_DEFAULT_PACKS,
    _PROFILE_PRIMERS,
)
from amprealize.bootstrap.profile import (
    WorkspaceProfile,
    ProfileDetectionResult,
    WorkspaceSignal,
)


pytestmark = pytest.mark.unit  # Mark all tests in this module as unit tests


class TestBootstrapService:
    """Test suite for BootstrapService."""

    def test_get_pack_for_profile_returns_correct_mapping(self):
        """Each profile should map to its expected pack ID."""
        svc = BootstrapService()

        # Verify all profiles have mappings
        for profile in WorkspaceProfile:
            pack_id = svc.get_pack_for_profile(profile)
            assert pack_id is not None, f"Profile {profile} has no pack mapping"
            assert isinstance(pack_id, str)
            assert len(pack_id) > 0

    def test_get_pack_for_profile_specific_mappings(self):
        """Verify specific profile-to-pack mappings."""
        svc = BootstrapService()

        expected = {
            WorkspaceProfile.SOLO_DEV: "solo-developer",
            WorkspaceProfile.AMPREALIZE_PLATFORM: "amprealize-platform",
            WorkspaceProfile.TEAM_COLLAB: "team-collaboration",
            WorkspaceProfile.EXTENSION_DEV: "extension-developer",
            WorkspaceProfile.API_BACKEND: "api-backend",
            WorkspaceProfile.COMPLIANCE_SENSITIVE: "compliance-sensitive",
        }

        for profile, expected_pack in expected.items():
            actual = svc.get_pack_for_profile(profile)
            assert actual == expected_pack, f"Profile {profile}: expected {expected_pack}, got {actual}"

    def test_get_primer_template_returns_content_for_all_profiles(self):
        """All profiles should have primer templates."""
        svc = BootstrapService()

        for profile in WorkspaceProfile:
            template = svc.get_primer_template(profile)
            assert template is not None, f"Profile {profile} has no primer template"
            assert len(template) > 100, f"Profile {profile} template too short: {len(template)} chars"

    def test_get_primer_template_contains_profile_keywords(self):
        """Primer templates should contain profile-specific keywords."""
        svc = BootstrapService()

        keywords = {
            WorkspaceProfile.SOLO_DEV: ["solo", "single"],
            WorkspaceProfile.AMPREALIZE_PLATFORM: ["amprealize", "mcp"],
            WorkspaceProfile.TEAM_COLLAB: ["team", "review"],
            WorkspaceProfile.EXTENSION_DEV: ["extension", "vscode"],
            WorkspaceProfile.API_BACKEND: ["api", "openapi"],
            WorkspaceProfile.COMPLIANCE_SENSITIVE: ["compliance", "audit"],
        }

        for profile, expected_keywords in keywords.items():
            template = svc.get_primer_template(profile)
            assert template is not None, f"Profile {profile} has no template"
            template_lower = template.lower()
            found = [kw for kw in expected_keywords if kw in template_lower]
            assert found, f"Profile {profile} missing keywords: {expected_keywords}"

    def test_detect_delegates_to_workspace_detector(self, tmp_path: Path):
        """detect() should delegate to WorkspaceDetector."""
        svc = BootstrapService()

        # Create minimal workspace
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'")

        result = svc.detect(tmp_path)

        assert isinstance(result, ProfileDetectionResult)
        assert isinstance(result.profile, WorkspaceProfile)
        assert 0 <= result.confidence <= 1.0

    def test_detect_with_amprealize_workspace(self, tmp_path: Path):
        """Workspace with Amprealize markers should detect as amprealize-platform."""
        svc = BootstrapService()

        # Setup amprealize-platform signals
        (tmp_path / "AGENTS.md").write_text("# Agent Handbook\n" * 100)
        amprealize_dir = tmp_path / "amprealize"
        amprealize_dir.mkdir()
        (amprealize_dir / "__init__.py").write_text("")
        mcp_dir = tmp_path / "mcp" / "tools"
        mcp_dir.mkdir(parents=True)
        for i in range(10):
            (mcp_dir / f"tool_{i}.json").write_text("{}")
        (tmp_path / "pyproject.toml").write_text('[project]\nname="test"\ndependencies=["fastapi"]')

        result = svc.detect(tmp_path)

        assert result.profile == WorkspaceProfile.AMPREALIZE_PLATFORM
        assert result.confidence >= 0.8

    def test_generate_primer_creates_agents_md(self, tmp_path: Path):
        """generate_primer() should create AGENTS.md with profile content."""
        svc = BootstrapService()

        path = svc.generate_primer(tmp_path, WorkspaceProfile.API_BACKEND)

        assert path is not None, "generate_primer should return a path"
        assert path.exists()
        assert path.name == "AGENTS.md"
        content = path.read_text()
        assert "api" in content.lower() or "openapi" in content.lower()

    def test_generate_primer_does_not_overwrite_existing(self, tmp_path: Path):
        """generate_primer() should not overwrite existing AGENTS.md."""
        svc = BootstrapService()

        # Create existing AGENTS.md
        existing = tmp_path / "AGENTS.md"
        existing.write_text("# My Custom AGENTS.md\n\nDo not overwrite.")

        path = svc.generate_primer(tmp_path, WorkspaceProfile.SOLO_DEV)

        assert path is None  # Returns None when skipped
        assert existing.read_text().startswith("# My Custom AGENTS.md")

    def test_bootstrap_full_workflow(self, tmp_path: Path):
        """bootstrap() should run detection, select pack, and generate primer."""
        svc = BootstrapService()

        # Setup api-backend signals
        (tmp_path / "pyproject.toml").write_text('[project]\nname="api"\ndependencies=["fastapi"]')
        (tmp_path / "openapi.yaml").write_text("openapi: 3.0.0")

        result = svc.bootstrap(tmp_path)

        assert isinstance(result, BootstrapResult)
        assert result.profile == WorkspaceProfile.API_BACKEND
        assert result.pack_id == "api-backend"
        # files_written contains strings, not Paths
        assert str(tmp_path / "AGENTS.md") in result.files_written

    def test_bootstrap_with_profile_override(self, tmp_path: Path):
        """bootstrap() should use override_profile when provided."""
        svc = BootstrapService()

        # Setup signals that would normally detect as solo-dev
        (tmp_path / "pyproject.toml").write_text('[project]\nname="test"')

        result = svc.bootstrap(tmp_path, profile=WorkspaceProfile.COMPLIANCE_SENSITIVE)

        assert result.profile == WorkspaceProfile.COMPLIANCE_SENSITIVE
        assert result.pack_id == "compliance-sensitive"

    def test_bootstrap_skip_primer(self, tmp_path: Path):
        """bootstrap() with skip_primer=True should not create AGENTS.md."""
        svc = BootstrapService()

        result = svc.bootstrap(tmp_path, skip_primer=True)

        assert not (tmp_path / "AGENTS.md").exists()
        assert result.files_written == []

    def test_bootstrap_result_to_dict(self, tmp_path: Path):
        """BootstrapResult.to_dict() should serialize properly."""
        svc = BootstrapService()

        result = svc.bootstrap(tmp_path)
        serialized = result.to_dict()

        assert "profile" in serialized
        assert "pack_id" in serialized
        # Key is 'detection' not 'detection_result'
        assert "detection" in serialized
        assert isinstance(serialized["detection"], dict)


class TestProfilePackMapping:
    """Test the profile-to-pack mapping constants."""

    def test_all_profiles_have_pack_mapping(self):
        """Every WorkspaceProfile should have a pack ID mapping."""
        for profile in WorkspaceProfile:
            assert profile in _PROFILE_DEFAULT_PACKS, f"Missing pack mapping for {profile}"

    def test_all_profiles_have_primer_template(self):
        """Every WorkspaceProfile should have a primer template."""
        for profile in WorkspaceProfile:
            assert profile in _PROFILE_PRIMERS, f"Missing primer template for {profile}"
            assert len(_PROFILE_PRIMERS[profile]) > 0


class TestBootstrapResult:
    """Test the BootstrapResult dataclass."""

    def test_bootstrap_result_creation(self):
        """BootstrapResult should be creatable with all fields."""
        detection = ProfileDetectionResult(
            profile=WorkspaceProfile.SOLO_DEV,
            confidence=0.85,
            signals=[],
            is_ambiguous=False,
            runner_up=None,
        )

        result = BootstrapResult(
            profile=WorkspaceProfile.SOLO_DEV,
            detection_result=detection,
            pack_id="solo-developer",
            pack_version="1.0.0",
            files_written=["/tmp/AGENTS.md"],
            notes=["Test note"],
        )

        assert result.profile == WorkspaceProfile.SOLO_DEV
        assert result.pack_id == "solo-developer"
        assert len(result.files_written) == 1
        assert len(result.notes) == 1

    def test_bootstrap_result_to_dict_serializes_paths(self):
        """to_dict() should convert Path objects to strings."""
        detection = ProfileDetectionResult(
            profile=WorkspaceProfile.API_BACKEND,
            confidence=0.9,
            signals=[],
            is_ambiguous=False,
        )

        result = BootstrapResult(
            profile=WorkspaceProfile.API_BACKEND,
            detection_result=detection,
            pack_id="api-backend",
            pack_version="1.0.0",
            files_written=["/tmp/AGENTS.md", "/tmp/config.yaml"],
            notes=[],
        )

        serialized = result.to_dict()

        assert all(isinstance(f, str) for f in serialized["files_written"])
        assert "/tmp/AGENTS.md" in serialized["files_written"]
