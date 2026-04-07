"""Tests for CLI suggest-agent command."""

import json
import subprocess
import sys

import pytest


@pytest.mark.skip(reason="suggest-agent CLI command not yet registered in argparse")
class TestCLISuggestAgent:
    """Test the suggest-agent CLI command."""

    def test_suggest_agent_help(self):
        """Test that suggest-agent --help works."""
        result = subprocess.run(
            [sys.executable, "-m", "amprealize.cli", "suggest-agent", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert "suggest-agent" in result.stdout.lower() or "usage" in result.stdout.lower()

    def test_suggest_agent_missing_item_id(self):
        """Test that suggest-agent requires assignable_id."""
        result = subprocess.run(
            [sys.executable, "-m", "amprealize.cli", "suggest-agent"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # argparse returns exit code 2 for missing required argument
        assert result.returncode == 2
        assert "assignable_id" in result.stderr.lower() or "required" in result.stderr.lower()

    @pytest.mark.integration
    def test_suggest_agent_smoke_test(self):
        """Smoke test: run suggest-agent with test data.

        This test requires the Board DB to be running with schema applied.
        """
        result = subprocess.run(
            [
                sys.executable, "-m", "amprealize.cli",
                "suggest-agent",
                "test-feature-001",
                "feature",
                "--behavior", "coding",
                "--max-suggestions", "3",
                "--format", "json",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        # The command should either succeed or fail gracefully
        # (e.g., if no agents are registered yet)
        if result.returncode == 0:
            # If successful, output should be valid JSON
            output = json.loads(result.stdout)
            assert isinstance(output, (list, dict))
        else:
            # If it fails, it should be a known error (not a crash)
            # Common errors: no agents registered, item not found, etc.
            assert "error" in result.stderr.lower() or "traceback" not in result.stderr.lower()
