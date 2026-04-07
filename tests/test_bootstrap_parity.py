"""Parity tests for bootstrap CLI/MCP surfaces.

Verifies that CLI commands (amprealize bootstrap detect/status/init) produce
output consistent with MCP tools (bootstrap.detect/status/init).
"""

import json
import pytest
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

from amprealize.bootstrap.detector import WorkspaceDetector
from amprealize.bootstrap.service import BootstrapService
from amprealize.bootstrap.profile import WorkspaceProfile, ProfileDetectionResult, WorkspaceSignal


pytestmark = pytest.mark.unit  # Mark all tests in this module as unit tests


class TestBootstrapDetectParity:
    """Test that CLI and MCP bootstrap.detect produce equivalent output."""

    def test_cli_detect_json_matches_mcp_schema(self, tmp_path: Path) -> None:
        """CLI --format json output matches MCP bootstrap.detect response schema."""
        # Create a minimal workspace
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")

        # Run CLI
        result = subprocess.run(
            [sys.executable, "-m", "amprealize.cli", "bootstrap", "detect",
             "--path", str(tmp_path), "--format", "json"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        cli_output = json.loads(result.stdout)

        # Verify MCP schema fields are present
        assert "profile" in cli_output
        assert "confidence" in cli_output
        assert "is_ambiguous" in cli_output
        assert "runner_up" in cli_output  # nullable
        assert "signals" in cli_output

        # Verify signals structure
        for signal in cli_output["signals"]:
            assert "signal_name" in signal
            assert "detected" in signal
            assert "evidence" in signal

    def test_cli_and_mcp_handler_produce_same_result(self, tmp_path: Path) -> None:
        """CLI detect and MCP handler return identical detection results."""
        # Create a workspace with identifiable signals
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        (tmp_path / ".github").mkdir()
        (tmp_path / "SECURITY.md").write_text("# Security\n")

        # Get CLI result
        result = subprocess.run(
            [sys.executable, "-m", "amprealize.cli", "bootstrap", "detect",
             "--path", str(tmp_path), "--format", "json"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        cli_result = json.loads(result.stdout)

        # Get MCP handler result
        from amprealize.mcp.handlers.bootstrap_handlers import handle_bootstrap_detect
        mcp_result = handle_bootstrap_detect({"workspace_path": str(tmp_path)})

        # Compare key fields
        assert cli_result["profile"] == mcp_result["profile"]
        assert cli_result["confidence"] == mcp_result["confidence"]
        assert cli_result["is_ambiguous"] == mcp_result["is_ambiguous"]
        assert cli_result["runner_up"] == mcp_result["runner_up"]

        # Compare signals (order may differ but content should match)
        cli_signals = {s["signal_name"]: s for s in cli_result["signals"]}
        mcp_signals = {s["signal_name"]: s for s in mcp_result["signals"]}
        assert cli_signals.keys() == mcp_signals.keys()
        for name, cli_sig in cli_signals.items():
            mcp_sig = mcp_signals[name]
            assert cli_sig["detected"] == mcp_sig["detected"], f"Signal {name} mismatch"


class TestBootstrapStatusParity:
    """Test that CLI and MCP bootstrap.status produce equivalent output."""

    def test_cli_status_json_matches_mcp_schema(self, tmp_path: Path) -> None:
        """CLI --format json output matches MCP bootstrap.status response schema."""
        result = subprocess.run(
            [sys.executable, "-m", "amprealize.cli", "bootstrap", "status",
             "--path", str(tmp_path), "--format", "json"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        cli_output = json.loads(result.stdout)

        # Verify MCP schema fields are present
        assert "is_bootstrapped" in cli_output
        assert "profile" in cli_output  # nullable
        assert "pack_id" in cli_output  # nullable
        assert "pack_version" in cli_output  # nullable
        assert "agents_md_exists" in cli_output
        assert "amprealize_dir_exists" in cli_output
        assert "last_updated" in cli_output  # nullable

    def test_cli_status_not_bootstrapped(self, tmp_path: Path) -> None:
        """Empty workspace reports not bootstrapped."""
        result = subprocess.run(
            [sys.executable, "-m", "amprealize.cli", "bootstrap", "status",
             "--path", str(tmp_path), "--format", "json"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

        cli_output = json.loads(result.stdout)
        assert cli_output["is_bootstrapped"] is False
        assert cli_output["agents_md_exists"] is False
        assert cli_output["amprealize_dir_exists"] is False

    def test_cli_status_with_agents_md(self, tmp_path: Path) -> None:
        """Workspace with AGENTS.md shows bootstrapped."""
        (tmp_path / "AGENTS.md").write_text("# Agent Handbook\n")

        result = subprocess.run(
            [sys.executable, "-m", "amprealize.cli", "bootstrap", "status",
             "--path", str(tmp_path), "--format", "json"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

        cli_output = json.loads(result.stdout)
        assert cli_output["is_bootstrapped"] is True
        assert cli_output["agents_md_exists"] is True

    def test_cli_status_with_amprealize_dir(self, tmp_path: Path) -> None:
        """Workspace with .amprealize/ shows bootstrapped."""
        (tmp_path / ".amprealize").mkdir()

        result = subprocess.run(
            [sys.executable, "-m", "amprealize.cli", "bootstrap", "status",
             "--path", str(tmp_path), "--format", "json"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

        cli_output = json.loads(result.stdout)
        assert cli_output["is_bootstrapped"] is True
        assert cli_output["amprealize_dir_exists"] is True

    def test_cli_and_mcp_handler_produce_same_result(self, tmp_path: Path) -> None:
        """CLI status and MCP handler return identical results."""
        # Create partial bootstrap state
        (tmp_path / "AGENTS.md").write_text("# Agent Handbook\n")

        # Get CLI result
        result = subprocess.run(
            [sys.executable, "-m", "amprealize.cli", "bootstrap", "status",
             "--path", str(tmp_path), "--format", "json"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        cli_result = json.loads(result.stdout)

        # Get MCP handler result
        from amprealize.mcp.handlers.bootstrap_handlers import handle_bootstrap_status
        mcp_result = handle_bootstrap_status({"workspace_path": str(tmp_path)})

        # Compare all fields
        assert cli_result["is_bootstrapped"] == mcp_result["is_bootstrapped"]
        assert cli_result["profile"] == mcp_result["profile"]
        assert cli_result["pack_id"] == mcp_result["pack_id"]
        assert cli_result["agents_md_exists"] == mcp_result["agents_md_exists"]
        assert cli_result["amprealize_dir_exists"] == mcp_result["amprealize_dir_exists"]


class TestBootstrapInitParity:
    """Test that CLI and MCP bootstrap.init produce equivalent output."""

    def test_cli_init_json_matches_mcp_schema(self, tmp_path: Path) -> None:
        """CLI --format json output matches MCP bootstrap.init response schema."""
        result = subprocess.run(
            [sys.executable, "-m", "amprealize.cli", "bootstrap", "init",
             "--path", str(tmp_path), "--skip-pack", "--format", "json"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        cli_output = json.loads(result.stdout)

        # Verify MCP schema fields are present
        assert "success" in cli_output
        assert "profile" in cli_output
        assert "detection" in cli_output
        assert "pack_id" in cli_output  # nullable
        assert "files_written" in cli_output
        assert "notes" in cli_output

    def test_cli_init_creates_agents_md(self, tmp_path: Path) -> None:
        """CLI init creates AGENTS.md file."""
        result = subprocess.run(
            [sys.executable, "-m", "amprealize.cli", "bootstrap", "init",
             "--path", str(tmp_path), "--skip-pack", "--format", "json"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        cli_output = json.loads(result.stdout)
        assert cli_output["success"] is True
        assert (tmp_path / "AGENTS.md").exists()

        # Verify file in files_written
        files = cli_output["files_written"]
        agents_written = any("AGENTS.md" in f for f in files)
        assert agents_written, f"AGENTS.md not in files_written: {files}"

    def test_cli_init_with_profile_override(self, tmp_path: Path) -> None:
        """CLI init respects --profile override."""
        result = subprocess.run(
            [sys.executable, "-m", "amprealize.cli", "bootstrap", "init",
             "--path", str(tmp_path), "--profile", "api-backend",
             "--skip-pack", "--format", "json"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        cli_output = json.loads(result.stdout)
        assert cli_output["profile"] == "api-backend"

    def test_cli_init_skip_primer(self, tmp_path: Path) -> None:
        """CLI init --skip-primer skips AGENTS.md creation."""
        result = subprocess.run(
            [sys.executable, "-m", "amprealize.cli", "bootstrap", "init",
             "--path", str(tmp_path), "--skip-primer", "--skip-pack", "--format", "json"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        cli_output = json.loads(result.stdout)
        assert cli_output["success"] is True
        assert not (tmp_path / "AGENTS.md").exists()

    def test_cli_and_mcp_handler_produce_equivalent_result(self, tmp_path: Path) -> None:
        """CLI init and MCP handler produce structurally equivalent results."""
        # Create two workspaces for independent tests
        cli_workspace = tmp_path / "cli_ws"
        mcp_workspace = tmp_path / "mcp_ws"
        cli_workspace.mkdir()
        mcp_workspace.mkdir()

        # Run CLI
        result = subprocess.run(
            [sys.executable, "-m", "amprealize.cli", "bootstrap", "init",
             "--path", str(cli_workspace), "--skip-pack", "--format", "json"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        cli_result = json.loads(result.stdout)

        # Run MCP handler
        from amprealize.mcp.handlers.bootstrap_handlers import handle_bootstrap_init
        mcp_result = handle_bootstrap_init({
            "workspace_path": str(mcp_workspace),
            "skip_pack": True,
        })

        # Compare key fields (paths will differ)
        assert cli_result["success"] == mcp_result["success"]
        assert cli_result["profile"] == mcp_result["profile"]
        assert cli_result["pack_id"] == mcp_result["pack_id"]

        # Both should have created AGENTS.md
        assert (cli_workspace / "AGENTS.md").exists()
        assert (mcp_workspace / "AGENTS.md").exists()


class TestBootstrapErrorHandling:
    """Test error handling consistency across CLI and MCP."""

    def test_cli_detect_invalid_path(self) -> None:
        """CLI detect reports error for non-existent path."""
        result = subprocess.run(
            [sys.executable, "-m", "amprealize.cli", "bootstrap", "detect",
             "--path", "/nonexistent/path/12345"],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "Error" in result.stderr or "not exist" in result.stderr.lower()

    def test_cli_status_invalid_path(self) -> None:
        """CLI status reports error for non-existent path."""
        result = subprocess.run(
            [sys.executable, "-m", "amprealize.cli", "bootstrap", "status",
             "--path", "/nonexistent/path/12345"],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0

    def test_cli_init_invalid_profile(self, tmp_path: Path) -> None:
        """CLI init reports error for invalid profile."""
        result = subprocess.run(
            [sys.executable, "-m", "amprealize.cli", "bootstrap", "init",
             "--path", str(tmp_path), "--profile", "not-a-real-profile"],
            capture_output=True,
            text=True,
        )
        # argparse should catch this and show valid choices
        assert result.returncode != 0


class TestBootstrapTableOutput:
    """Test table format output (human-readable)."""

    def test_cli_detect_table_has_profile(self, tmp_path: Path) -> None:
        """CLI detect table output shows profile."""
        result = subprocess.run(
            [sys.executable, "-m", "amprealize.cli", "bootstrap", "detect",
             "--path", str(tmp_path), "--format", "table"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "Profile:" in result.stdout or "profile" in result.stdout.lower()

    def test_cli_status_table_has_status(self, tmp_path: Path) -> None:
        """CLI status table output shows bootstrap status."""
        result = subprocess.run(
            [sys.executable, "-m", "amprealize.cli", "bootstrap", "status",
             "--path", str(tmp_path), "--format", "table"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "Status:" in result.stdout or "bootstrapped" in result.stdout.lower()

    def test_cli_init_table_shows_completion(self, tmp_path: Path) -> None:
        """CLI init table output shows completion message."""
        result = subprocess.run(
            [sys.executable, "-m", "amprealize.cli", "bootstrap", "init",
             "--path", str(tmp_path), "--skip-pack", "--format", "table"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "Complete" in result.stdout or "✅" in result.stdout
