"""Tests for the wizard CLI command and supporting modules."""

import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from pytest import CaptureFixture, MonkeyPatch

from amprealize import cli
from amprealize.wizard.analyzer import AnalysisResult, ProjectAnalyzer
from amprealize.wizard.generator import ConfigGenerator
from amprealize.wizard.prompts import SYSTEM_PROMPT, build_user_prompt
from amprealize.wizard.runner import WizardRunner

pytestmark = pytest.mark.unit


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_cli_state() -> None:
    cli._reset_action_state_for_testing()


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """Scaffold a minimal fake project directory."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\n\n[project.optional-dependencies]\ndev = ["pytest"]\n'
    )
    (tmp_path / "README.md").write_text("# Demo\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text("def test_ok(): pass\n")
    return tmp_path


@pytest.fixture()
def sample_analysis() -> AnalysisResult:
    """Return a canned AnalysisResult for testing downstream components."""
    return AnalysisResult(
        tech_stack={
            "languages": ["python"],
            "frameworks": ["pytest"],
            "build_tools": ["setuptools"],
            "package_managers": ["pip"],
        },
        architecture={"pattern": "monolith", "description": "Simple Python project"},
        team_signals={"ci": False, "docker": False},
        suggested_profile="solo-dev",
        profile_rationale="Single-dev Python project with no CI.",
        suggested_modules={"goals": True, "agents": True, "behaviors": False},
        module_rationale="Small scope — skip behaviors.",
        suggested_behaviors=[],
        deployment_recommendation="local",
        storage_recommendation="sqlite",
        notes="",
        raw_response={"suggested_profile": "solo-dev"},
        model_used="claude-sonnet-4-20250514",
        input_tokens=500,
        output_tokens=200,
        cost_usd=0.0045,
        latency_ms=1200.0,
    )


def _run_cli(args: list[str], capsys: CaptureFixture[str]) -> tuple[int, str, str]:
    exit_code = cli.main(args)
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


# ── prompts.py ────────────────────────────────────────────────────────────────


class TestPrompts:
    def test_system_prompt_is_string(self) -> None:
        assert isinstance(SYSTEM_PROMPT, str)
        assert "JSON" in SYSTEM_PROMPT

    def test_build_user_prompt_includes_listing(self) -> None:
        result = build_user_prompt(
            directory_listing="src/\n  main.py",
            key_files_content="### pyproject.toml\n```\n[project]\n```",
            signals_summary="- python: DETECTED",
            heuristic_profile="solo-dev",
            heuristic_confidence=0.85,
        )
        assert "src/" in result
        assert "solo-dev" in result
        assert "85%" in result


# ── analyzer.py ───────────────────────────────────────────────────────────────


class TestProjectAnalyzer:
    def test_gather_directory_listing(self, workspace: Path) -> None:
        analyzer = ProjectAnalyzer()
        listing = analyzer.gather_directory_listing(workspace)
        assert "src/" in listing
        assert "main.py" in listing
        assert "tests/" in listing

    def test_gather_directory_listing_excludes_hidden(self, workspace: Path) -> None:
        (workspace / ".git").mkdir()
        (workspace / ".git" / "config").write_text("")
        analyzer = ProjectAnalyzer()
        listing = analyzer.gather_directory_listing(workspace)
        assert ".git" not in listing

    def test_gather_key_files(self, workspace: Path) -> None:
        analyzer = ProjectAnalyzer()
        content = analyzer.gather_key_files(workspace)
        assert "pyproject.toml" in content
        assert "README.md" in content

    def test_parse_response_clean_json(self) -> None:
        data = {"suggested_profile": "solo-dev", "notes": "ok"}
        result = ProjectAnalyzer._parse_response(json.dumps(data))
        assert result["suggested_profile"] == "solo-dev"

    def test_parse_response_fenced_json(self) -> None:
        data = {"suggested_profile": "team-collab"}
        raw = f"```json\n{json.dumps(data)}\n```"
        result = ProjectAnalyzer._parse_response(raw)
        assert result["suggested_profile"] == "team-collab"

    def test_parse_response_invalid_json(self) -> None:
        result = ProjectAnalyzer._parse_response("this is not json")
        assert result.get("_parse_error") is True

    def test_detect_signals(self, workspace: Path) -> None:
        analyzer = ProjectAnalyzer()
        detection = analyzer.detect_signals(workspace)
        assert detection.profile is not None
        assert isinstance(detection.confidence, float)

    @patch("amprealize.wizard.analyzer.LLMClient")
    def test_analyse_calls_llm(self, mock_client_cls: MagicMock, workspace: Path) -> None:
        mock_response = MagicMock()
        mock_response.content = json.dumps({"suggested_profile": "solo-dev"})
        mock_response.model = "claude-sonnet-4-20250514"
        mock_response.input_tokens = 100
        mock_response.output_tokens = 50
        mock_response.cost_usd = 0.001
        mock_response.latency_ms = 500.0

        mock_client = MagicMock()
        mock_client.call.return_value = mock_response

        analyzer = ProjectAnalyzer(llm_client=mock_client)
        result = analyzer.analyse(workspace, api_key="test-key")

        mock_client.call.assert_called_once()
        assert result.suggested_profile == "solo-dev"
        assert result.model_used == "claude-sonnet-4-20250514"


# ── generator.py ──────────────────────────────────────────────────────────────


class TestConfigGenerator:
    def test_dry_run_does_not_write(
        self, workspace: Path, sample_analysis: AnalysisResult
    ) -> None:
        gen = ConfigGenerator()
        files = gen.generate(workspace, sample_analysis, dry_run=True)
        assert ".amprealize/config.yaml" in files
        assert "AGENTS.md" in files
        assert ".vscode/mcp.json" in files
        # Verify nothing was written
        assert not (workspace / ".amprealize" / "config.yaml").exists()

    def test_generate_writes_files(
        self, workspace: Path, sample_analysis: AnalysisResult
    ) -> None:
        gen = ConfigGenerator()
        files = gen.generate(workspace, sample_analysis)
        assert (workspace / ".amprealize" / "config.yaml").exists()
        assert (workspace / "AGENTS.md").exists()
        assert (workspace / ".vscode" / "mcp.json").exists()

    def test_config_yaml_content(
        self, workspace: Path, sample_analysis: AnalysisResult
    ) -> None:
        import yaml

        gen = ConfigGenerator()
        files = gen.generate(workspace, sample_analysis, dry_run=True)
        config = yaml.safe_load(files[".amprealize/config.yaml"])
        assert config["version"] == 1
        assert config["project"]["workspace_profile"] == "solo-dev"
        assert config["storage"]["backend"] == "sqlite"
        assert config["modules"]["goals"] is True
        assert config["modules"]["behaviors"] is False

    def test_mcp_json_content(
        self, workspace: Path, sample_analysis: AnalysisResult
    ) -> None:
        gen = ConfigGenerator()
        files = gen.generate(workspace, sample_analysis, dry_run=True)
        parsed = json.loads(files[".vscode/mcp.json"])
        assert "amprealize" in parsed["servers"]
        assert parsed["servers"]["amprealize"]["type"] == "stdio"

    def test_wizard_report_included(
        self, workspace: Path, sample_analysis: AnalysisResult
    ) -> None:
        gen = ConfigGenerator()
        files = gen.generate(workspace, sample_analysis, dry_run=True)
        assert ".amprealize/wizard-report.md" in files
        assert "Wizard Analysis Report" in files[".amprealize/wizard-report.md"]

    def test_project_name_override(
        self, workspace: Path, sample_analysis: AnalysisResult
    ) -> None:
        import yaml

        gen = ConfigGenerator()
        files = gen.generate(
            workspace, sample_analysis, project_name="my-project", dry_run=True
        )
        config = yaml.safe_load(files[".amprealize/config.yaml"])
        assert config["project"]["name"] == "my-project"


# ── runner.py ─────────────────────────────────────────────────────────────────


class TestWizardRunner:
    def test_dry_run_no_files_written(
        self, workspace: Path, monkeypatch: MonkeyPatch
    ) -> None:
        """Dry run should produce exit 0 without writing files."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        mock_response = MagicMock()
        mock_response.content = json.dumps({"suggested_profile": "solo-dev"})
        mock_response.model = "claude-sonnet-4-20250514"
        mock_response.input_tokens = 100
        mock_response.output_tokens = 50
        mock_response.cost_usd = 0.001
        mock_response.latency_ms = 500.0

        with patch("amprealize.wizard.analyzer.LLMClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.call.return_value = mock_response
            mock_cls.return_value = mock_client

            runner = WizardRunner(dry_run=True, non_interactive=True)
            result = runner.run(workspace)

        assert result == 0
        assert not (workspace / ".amprealize" / "config.yaml").exists()

    def test_no_api_key_returns_1(
        self, workspace: Path, monkeypatch: MonkeyPatch
    ) -> None:
        """Without an API key and non-interactive, wizard should fail."""
        # Clear all known key env vars
        for var in [
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "OPENROUTER_API_KEY",
            "TOGETHER_API_KEY",
            "GROQ_API_KEY",
            "FIREWORKS_API_KEY",
            "AMPREALIZE_LLM_API_KEY",
        ]:
            monkeypatch.delenv(var, raising=False)

        runner = WizardRunner(non_interactive=True)
        result = runner.run(workspace)
        assert result == 1

    def test_skip_login_bypasses_key_check(
        self, workspace: Path, monkeypatch: MonkeyPatch
    ) -> None:
        # Clear keys
        for var in [
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "AMPREALIZE_LLM_API_KEY",
        ]:
            monkeypatch.delenv(var, raising=False)

        mock_response = MagicMock()
        mock_response.content = json.dumps({"suggested_profile": "solo-dev"})
        mock_response.model = "claude-sonnet-4-20250514"
        mock_response.input_tokens = 100
        mock_response.output_tokens = 50
        mock_response.cost_usd = 0.001
        mock_response.latency_ms = 500.0

        with patch("amprealize.wizard.analyzer.LLMClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.call.return_value = mock_response
            mock_cls.return_value = mock_client

            runner = WizardRunner(
                skip_login=True, dry_run=True, non_interactive=True
            )
            result = runner.run(workspace)

        assert result == 0

    def test_invalid_workspace_returns_1(self, tmp_path: Path) -> None:
        """Non-existent workspace path should return 1."""
        runner = WizardRunner()
        result = runner.run(tmp_path / "nonexistent")
        assert result == 1


# ── CLI integration ───────────────────────────────────────────────────────────


class TestCLIWizard:
    def test_wizard_help(self, capsys: CaptureFixture[str]) -> None:
        """wizard --help should exit cleanly and mention 'wizard'."""
        with pytest.raises(SystemExit) as exc_info:
            cli.main(["wizard", "--help"])
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "wizard" in out.lower()

    def test_wizard_dry_run_via_cli(
        self, workspace: Path, capsys: CaptureFixture[str], monkeypatch: MonkeyPatch
    ) -> None:
        """Full CLI invocation with --dry-run."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        mock_response = MagicMock()
        mock_response.content = json.dumps({"suggested_profile": "solo-dev"})
        mock_response.model = "claude-sonnet-4-20250514"
        mock_response.input_tokens = 100
        mock_response.output_tokens = 50
        mock_response.cost_usd = 0.001
        mock_response.latency_ms = 500.0

        with patch("amprealize.wizard.analyzer.LLMClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.call.return_value = mock_response
            mock_cls.return_value = mock_client

            exit_code, out, err = _run_cli(
                ["wizard", "--path", str(workspace), "--dry-run", "--non-interactive"],
                capsys,
            )

        assert exit_code == 0
