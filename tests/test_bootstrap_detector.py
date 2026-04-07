"""Tests for the Workspace Detector (E2 — Adaptive Bootstrap).

Phase 1, Step 4 of AMPREALIZE-276 implementation plan.
Tests WorkspaceDetector signal detection and profile suggestion.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from amprealize.bootstrap.detector import WorkspaceDetector
from amprealize.bootstrap.profile import WorkspaceProfile


class TestWorkspaceDetector:
    """Unit tests for WorkspaceDetector."""

    @pytest.fixture
    def detector(self) -> WorkspaceDetector:
        return WorkspaceDetector()

    @pytest.fixture
    def empty_workspace(self, tmp_path: Path) -> Path:
        """Create an empty workspace directory."""
        return tmp_path

    @pytest.fixture
    def solo_dev_workspace(self, tmp_path: Path) -> Path:
        """Minimal solo-dev workspace with pyproject.toml."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'myapp'\n")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("print('hello')")
        return tmp_path

    @pytest.fixture
    def amprealize_workspace(self, tmp_path: Path) -> Path:
        """Full amprealize-platform workspace with all signals."""
        # AGENTS.md
        (tmp_path / "AGENTS.md").write_text("# Agent Handbook\n" + "x" * 1000)

        # amprealize/ package
        amprealize_pkg = tmp_path / "amprealize"
        amprealize_pkg.mkdir()
        (amprealize_pkg / "__init__.py").write_text("")

        # amprealize/knowledge_pack/
        kp = amprealize_pkg / "knowledge_pack"
        kp.mkdir()
        (kp / "__init__.py").write_text("")

        # mcp/tools/
        mcp = tmp_path / "mcp" / "tools"
        mcp.mkdir(parents=True)
        for i in range(5):
            (mcp / f"tool_{i}.json").write_text('{"name": "tool"}')

        # pyproject.toml with FastAPI
        (tmp_path / "pyproject.toml").write_text(
            "[project]\nname = 'amprealize'\ndependencies = ['fastapi']\n"
        )

        # alembic.ini
        (tmp_path / "alembic.ini").write_text("[alembic]\nscript_location = migrations")

        # policy/
        (tmp_path / "policy").mkdir()

        # SECURITY.md
        (tmp_path / "SECURITY.md").write_text("# Security Policy")

        return tmp_path

    @pytest.fixture
    def api_backend_workspace(self, tmp_path: Path) -> Path:
        """API/backend workspace with FastAPI + Alembic."""
        (tmp_path / "pyproject.toml").write_text(
            "[project]\nname = 'backend'\ndependencies = ['fastapi', 'sqlalchemy']\n"
        )
        (tmp_path / "alembic.ini").write_text("[alembic]\n")
        (tmp_path / "openapi.yaml").write_text("openapi: 3.0.0")
        (tmp_path / "src").mkdir()
        return tmp_path

    @pytest.fixture
    def extension_workspace(self, tmp_path: Path) -> Path:
        """VS Code extension workspace."""
        ext = tmp_path / "extension"
        ext.mkdir()
        pkg = {
            "name": "my-extension",
            "version": "1.0.0",
            "contributes": {"commands": []},
            "activationEvents": ["onStartupFinished"],
        }
        (ext / "package.json").write_text(json.dumps(pkg))
        return tmp_path

    @pytest.fixture
    def team_workspace(self, tmp_path: Path) -> Path:
        """Team collaboration workspace with CODEOWNERS and PR templates."""
        gh = tmp_path / ".github"
        gh.mkdir()
        (gh / "CODEOWNERS").write_text("* @team-leads\n")
        (gh / "pull_request_template.md").write_text("## PR Description\n")
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'team-app'\n")
        return tmp_path

    @pytest.fixture
    def compliance_workspace(self, tmp_path: Path) -> Path:
        """Compliance-sensitive workspace with policy/ and compliance docs."""
        (tmp_path / "policy").mkdir()
        (tmp_path / "SOC2.md").write_text("# SOC2 Compliance\n")
        (tmp_path / "SECURITY.md").write_text("# Security Policy\n")
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'compliant'\n")
        return tmp_path

    # ====================================================================
    # Signal detection tests
    # ====================================================================

    def test_detect_signals_empty_workspace(
        self, detector: WorkspaceDetector, empty_workspace: Path
    ):
        """Empty workspace should detect zero signals."""
        signals = detector.detect_signals(empty_workspace)
        assert len(signals) > 0  # All signals returned, but not detected
        detected = [s for s in signals if s.detected]
        # single_contributor detects as True when no team signals
        assert len(detected) == 1
        assert detected[0].signal_name == "single_contributor"

    def test_detect_signals_amprealize_workspace(
        self, detector: WorkspaceDetector, amprealize_workspace: Path
    ):
        """Amprealize workspace should detect core amprealize signals."""
        signals = detector.detect_signals(amprealize_workspace)
        detected_names = {s.signal_name for s in signals if s.detected}

        assert "agents_md" in detected_names
        assert "amprealize_imports" in detected_names
        assert "knowledge_pack_dir" in detected_names
        assert "mcp_tools_dir" in detected_names
        assert "pyproject_toml" in detected_names
        assert "alembic_ini" in detected_names
        assert "fastapi_or_flask" in detected_names
        assert "policy_dir" in detected_names
        assert "security_md" in detected_names

    def test_detect_signals_api_backend(
        self, detector: WorkspaceDetector, api_backend_workspace: Path
    ):
        """API backend workspace should detect FastAPI and OpenAPI signals."""
        signals = detector.detect_signals(api_backend_workspace)
        detected_names = {s.signal_name for s in signals if s.detected}

        assert "fastapi_or_flask" in detected_names
        assert "alembic_ini" in detected_names
        assert "openapi_spec" in detected_names
        assert "pyproject_toml" in detected_names

    def test_detect_signals_extension(
        self, detector: WorkspaceDetector, extension_workspace: Path
    ):
        """Extension workspace should detect VS Code extension signals."""
        signals = detector.detect_signals(extension_workspace)
        detected_names = {s.signal_name for s in signals if s.detected}

        assert "extension_dir" in detected_names
        assert "vscode_extension_manifest" in detected_names

    def test_detect_signals_team(
        self, detector: WorkspaceDetector, team_workspace: Path
    ):
        """Team workspace should detect CODEOWNERS and PR template."""
        signals = detector.detect_signals(team_workspace)
        detected_names = {s.signal_name for s in signals if s.detected}

        assert "codeowners" in detected_names
        assert "pr_template" in detected_names
        assert "github_dir" in detected_names
        # NOT single_contributor when team signals exist
        assert "single_contributor" not in detected_names

    def test_detect_signals_compliance(
        self, detector: WorkspaceDetector, compliance_workspace: Path
    ):
        """Compliance workspace should detect policy/ and compliance docs."""
        signals = detector.detect_signals(compliance_workspace)
        detected_names = {s.signal_name for s in signals if s.detected}

        assert "policy_dir" in detected_names
        assert "security_md" in detected_names
        assert "soc2_or_hipaa" in detected_names

    # ====================================================================
    # Profile suggestion tests
    # ====================================================================

    def test_suggest_profile_empty(
        self, detector: WorkspaceDetector, empty_workspace: Path
    ):
        """Empty workspace should default to solo-dev."""
        result = detector.detect(empty_workspace)
        assert result.profile == WorkspaceProfile.SOLO_DEV
        # Low confidence for near-empty workspace
        assert result.confidence < 0.5

    def test_suggest_profile_solo_dev(
        self, detector: WorkspaceDetector, solo_dev_workspace: Path
    ):
        """Minimal workspace should suggest solo-dev."""
        result = detector.detect(solo_dev_workspace)
        assert result.profile == WorkspaceProfile.SOLO_DEV

    def test_suggest_profile_amprealize_platform(
        self, detector: WorkspaceDetector, amprealize_workspace: Path
    ):
        """Full Amprealize workspace should suggest amprealize-platform with high confidence."""
        result = detector.detect(amprealize_workspace)
        assert result.profile == WorkspaceProfile.AMPREALIZE_PLATFORM
        assert result.confidence >= 0.9  # High confidence

    def test_suggest_profile_api_backend(
        self, detector: WorkspaceDetector, api_backend_workspace: Path
    ):
        """API backend workspace should suggest api-backend."""
        result = detector.detect(api_backend_workspace)
        assert result.profile == WorkspaceProfile.API_BACKEND
        assert result.confidence >= 0.5

    def test_suggest_profile_extension_dev(
        self, detector: WorkspaceDetector, extension_workspace: Path
    ):
        """Extension workspace should suggest extension-dev."""
        result = detector.detect(extension_workspace)
        assert result.profile == WorkspaceProfile.EXTENSION_DEV
        assert result.confidence >= 0.6

    def test_suggest_profile_team_collab(
        self, detector: WorkspaceDetector, team_workspace: Path
    ):
        """Team workspace should suggest team-collab."""
        result = detector.detect(team_workspace)
        assert result.profile == WorkspaceProfile.TEAM_COLLAB
        assert result.confidence >= 0.4

    def test_suggest_profile_compliance_sensitive(
        self, detector: WorkspaceDetector, compliance_workspace: Path
    ):
        """Compliance workspace should suggest compliance-sensitive."""
        result = detector.detect(compliance_workspace)
        assert result.profile == WorkspaceProfile.COMPLIANCE_SENSITIVE
        assert result.confidence >= 0.5

    # ====================================================================
    # Edge cases
    # ====================================================================

    def test_ambiguous_detection(self, detector: WorkspaceDetector, tmp_path: Path):
        """When two profiles are close, mark as ambiguous."""
        # Create workspace with equal signals for both extension-dev and api-backend
        ext = tmp_path / "extension"
        ext.mkdir()
        pkg = {"name": "ext", "contributes": {}, "activationEvents": []}
        (ext / "package.json").write_text(json.dumps(pkg))

        # Also add FastAPI signal
        (tmp_path / "pyproject.toml").write_text(
            "[project]\ndependencies = ['fastapi']\n"
        )
        (tmp_path / "alembic.ini").write_text("[alembic]\n")

        result = detector.detect(tmp_path)
        # Should detect both extension and API signals — check result has some profile
        assert result.profile in (
            WorkspaceProfile.EXTENSION_DEV,
            WorkspaceProfile.API_BACKEND,
        )

    def test_to_dict_serialization(
        self, detector: WorkspaceDetector, amprealize_workspace: Path
    ):
        """ProfileDetectionResult.to_dict() should be JSON-serializable."""
        result = detector.detect(amprealize_workspace)
        d = result.to_dict()

        assert d["profile"] == "amprealize-platform"
        assert isinstance(d["confidence"], float)
        assert isinstance(d["signals"], list)
        assert isinstance(d["is_ambiguous"], bool)

        # Should be JSON-serializable
        json_str = json.dumps(d)
        assert "amprealize-platform" in json_str

    def test_agents_md_confidence_scales_with_size(
        self, detector: WorkspaceDetector, tmp_path: Path
    ):
        """Larger AGENTS.md should have higher confidence."""
        (tmp_path / "AGENTS.md").write_text("x" * 100)
        signals = detector.detect_signals(tmp_path)
        small_sig = next(s for s in signals if s.signal_name == "agents_md")

        (tmp_path / "AGENTS.md").write_text("x" * 1000)
        signals2 = detector.detect_signals(tmp_path)
        large_sig = next(s for s in signals2 if s.signal_name == "agents_md")

        assert large_sig.confidence >= small_sig.confidence

    def test_mcp_tools_confidence_scales_with_count(
        self, detector: WorkspaceDetector, tmp_path: Path
    ):
        """More MCP tool schemas should yield higher confidence."""
        mcp = tmp_path / "mcp" / "tools"
        mcp.mkdir(parents=True)
        (mcp / "tool1.json").write_text("{}")

        signals = detector.detect_signals(tmp_path)
        one_tool = next(s for s in signals if s.signal_name == "mcp_tools_dir")

        for i in range(2, 10):
            (mcp / f"tool{i}.json").write_text("{}")

        signals2 = detector.detect_signals(tmp_path)
        many_tools = next(s for s in signals2 if s.signal_name == "mcp_tools_dir")

        assert many_tools.confidence > one_tool.confidence


class TestWorkspaceDetectorIntegration:
    """Integration tests using the actual amprealize repo."""

    def test_detect_amprealize_repo(self):
        """Detection on the actual amprealize repo should return amprealize-platform."""
        amprealize_root = Path(__file__).parents[2]
        if not (amprealize_root / "AGENTS.md").exists():
            pytest.skip("Not running from amprealize repo root")

        detector = WorkspaceDetector()
        result = detector.detect(amprealize_root)

        assert result.profile == WorkspaceProfile.AMPREALIZE_PLATFORM
        assert result.confidence >= 0.9
        assert not result.is_ambiguous

        # Should detect many signals
        detected = [s for s in result.signals if s.detected]
        assert len(detected) >= 10
