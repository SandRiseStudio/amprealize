"""Integration tests for TraceAnalysisService CLI, API, and MCP surfaces.

Validates parity across:
- CLI: amprealize patterns detect/score
- MCP: patterns.detectPatterns / patterns.scoreReusability

Per docs/contracts/ACTION_SERVICE_CONTRACT.md parity requirements and behavior_wire_cli_to_orchestrator.
"""

import json
import pytest
from uuid import uuid4

from amprealize.trace_analysis_service import TraceAnalysisService
from amprealize.trace_analysis_contracts import (
    DetectPatternsRequest,
    DetectPatternsResponse,
    ScoreReusabilityRequest,
    ScoreReusabilityResponse,
    TracePattern,
)
from amprealize.adapters import (
    CLITraceAnalysisServiceAdapter,
    MCPTraceAnalysisServiceAdapter,
)


@pytest.fixture
def trace_analysis_service():
    """Create in-memory TraceAnalysisService for testing."""
    return TraceAnalysisService()


@pytest.fixture
def cli_adapter(trace_analysis_service):
    """Create CLI adapter."""
    return CLITraceAnalysisServiceAdapter(trace_analysis_service)


@pytest.fixture
def mcp_adapter(trace_analysis_service):
    """Create MCP adapter."""
    return MCPTraceAnalysisServiceAdapter(trace_analysis_service)


@pytest.fixture
def sample_runs():
    """Generate sample run data for pattern detection."""
    return [
        {
            "run_id": str(uuid4()),
            "steps": [
                "Check prerequisites",
                "Load configuration",
                "Initialize services",
                "Execute workflow",
                "Generate report",
            ],
        },
        {
            "run_id": str(uuid4()),
            "steps": [
                "Check prerequisites",
                "Load configuration",
                "Initialize services",
                "Execute workflow",
                "Send notification",
            ],
        },
        {
            "run_id": str(uuid4()),
            "steps": [
                "Check prerequisites",
                "Load configuration",
                "Initialize database",
                "Run migrations",
                "Generate report",
            ],
        },
    ]


class TestCLIAdapterIntegration:
    """Test CLI adapter detect_patterns and score_reusability methods."""

    def test_detect_patterns_cli(self, cli_adapter, sample_runs, monkeypatch):
        """Test CLI adapter detect_patterns with mock trace fetching."""

        def mock_fetch(run_id):
            for run in sample_runs:
                if run["run_id"] == run_id:
                    return "\n".join(run["steps"])
            return None

        # Mock _fetch_trace_for_run on the service
        monkeypatch.setattr(
            cli_adapter._service, "_fetch_trace_for_run", mock_fetch
        )

        run_ids = [run["run_id"] for run in sample_runs]
        result = cli_adapter.detect_patterns(
            run_ids=run_ids,
            min_frequency=2,
            min_similarity=0.7,
            max_patterns=10,
            include_context=True,
        )

        # Validate response structure
        assert "patterns" in result
        assert "runs_analyzed" in result
        assert "total_occurrences" in result
        assert "execution_time_seconds" in result

        assert result["runs_analyzed"] == 3
        assert isinstance(result["patterns"], list)

        # Validate pattern structure
        if result["patterns"]:
            pattern = result["patterns"][0]
            assert "pattern_id" in pattern
            assert "sequence" in pattern
            assert "frequency" in pattern
            assert isinstance(pattern["sequence"], list)
            assert pattern["frequency"] >= 2

    def test_score_reusability_cli(self, cli_adapter, monkeypatch):
        """Test CLI adapter score_reusability method."""

        # Create a mock pattern to score
        pattern = TracePattern(
            pattern_id=str(uuid4()),
            sequence=["Check prerequisites", "Load configuration", "Initialize services"],
            frequency=10,
            first_seen="2025-10-29T10:00:00Z",
            last_seen="2025-10-29T12:00:00Z",
            extracted_from_runs=[str(uuid4()) for _ in range(10)],
            metadata={},
        )

        # Mock storage.get_pattern
        def mock_get_pattern(pattern_id):
            if pattern_id == pattern.pattern_id:
                return pattern
            return None

        # If service has storage, mock it; otherwise skip
        if hasattr(cli_adapter._service, "storage") and cli_adapter._service.storage:
            monkeypatch.setattr(
                cli_adapter._service.storage, "get_pattern", mock_get_pattern
            )
        else:
            # In-memory service: inject pattern directly
            cli_adapter._service._patterns = {pattern.pattern_id: pattern}

        result = cli_adapter.score_reusability(
            pattern_id=pattern.pattern_id,
            total_runs=100,
            avg_trace_tokens=500,
            unique_task_types=5,
            total_task_types=10,
        )

        # Validate response structure
        assert "score" in result
        assert "pattern" in result
        assert "meets_threshold" in result

        score = result["score"]
        assert "frequency_score" in score
        assert "token_savings_score" in score
        assert "applicability_score" in score
        assert "overall_score" in score
        assert 0 <= score["overall_score"] <= 1


class TestMCPAdapterIntegration:
    """Test MCP adapter detectPatterns and scoreReusability methods."""

    def test_detect_patterns_mcp(self, mcp_adapter, sample_runs, monkeypatch):
        """Test MCP adapter detectPatterns with mock trace fetching."""

        def mock_fetch(run_id):
            for run in sample_runs:
                if run["run_id"] == run_id:
                    return "\n".join(run["steps"])
            return None

        monkeypatch.setattr(
            mcp_adapter._service, "_fetch_trace_for_run", mock_fetch
        )

        payload = {
            "run_ids": [run["run_id"] for run in sample_runs],
            "min_frequency": 2,
            "min_similarity": 0.7,
            "max_patterns": 10,
            "include_context": True,
        }

        result = mcp_adapter.detectPatterns(payload)

        # Validate response structure (same as CLI)
        assert "patterns" in result
        assert "runs_analyzed" in result
        assert result["runs_analyzed"] == 3

    def test_score_reusability_mcp(self, mcp_adapter, monkeypatch):
        """Test MCP adapter scoreReusability method."""

        pattern = TracePattern(
            pattern_id=str(uuid4()),
            sequence=["Check prerequisites", "Load configuration"],
            frequency=15,
            first_seen="2025-10-29T10:00:00Z",
            last_seen="2025-10-29T12:00:00Z",
            extracted_from_runs=[str(uuid4()) for _ in range(15)],
            metadata={},
        )

        # Mock pattern retrieval
        if hasattr(mcp_adapter._service, "storage") and mcp_adapter._service.storage:
            monkeypatch.setattr(
                mcp_adapter._service.storage,
                "get_pattern",
                lambda pid: pattern if pid == pattern.pattern_id else None,
            )
        else:
            mcp_adapter._service._patterns = {pattern.pattern_id: pattern}

        payload = {
            "pattern_id": pattern.pattern_id,
            "total_runs": 100,
            "avg_trace_tokens": 600,
            "unique_task_types": 6,
            "total_task_types": 10,
        }

        result = mcp_adapter.scoreReusability(payload)

        # Validate response structure
        assert "score" in result
        assert "pattern" in result
        assert "meets_threshold" in result
        assert isinstance(result["meets_threshold"], bool)


class TestCLIMCPParity:
    """Validate parity between CLI and MCP adapter outputs."""

    def test_detect_patterns_parity(self, cli_adapter, mcp_adapter, sample_runs, monkeypatch):
        """Ensure CLI and MCP adapters return structurally identical responses."""

        def mock_fetch(run_id):
            for run in sample_runs:
                if run["run_id"] == run_id:
                    return "\n".join(run["steps"])
            return None

        monkeypatch.setattr(cli_adapter._service, "_fetch_trace_for_run", mock_fetch)
        monkeypatch.setattr(mcp_adapter._service, "_fetch_trace_for_run", mock_fetch)

        run_ids = [run["run_id"] for run in sample_runs]

        cli_result = cli_adapter.detect_patterns(
            run_ids=run_ids,
            min_frequency=2,
            min_similarity=0.7,
            max_patterns=10,
            include_context=True,
        )

        mcp_payload = {
            "run_ids": run_ids,
            "min_frequency": 2,
            "min_similarity": 0.7,
            "max_patterns": 10,
            "include_context": True,
        }
        mcp_result = mcp_adapter.detectPatterns(mcp_payload)

        # Compare top-level keys
        assert set(cli_result.keys()) == set(mcp_result.keys())
        assert cli_result["runs_analyzed"] == mcp_result["runs_analyzed"]
        assert cli_result["total_occurrences"] == mcp_result["total_occurrences"]

        # Compare pattern structures (pattern IDs are UUIDs, so compare content)
        assert len(cli_result["patterns"]) == len(mcp_result["patterns"])
        if cli_result["patterns"]:
            # Sort patterns by sequence for stable comparison
            cli_patterns_sorted = sorted(cli_result["patterns"], key=lambda p: " ".join(p["sequence"]))
            mcp_patterns_sorted = sorted(mcp_result["patterns"], key=lambda p: " ".join(p["sequence"]))

            for cli_pat, mcp_pat in zip(cli_patterns_sorted, mcp_patterns_sorted):
                assert cli_pat["sequence"] == mcp_pat["sequence"]
                assert cli_pat["frequency"] == mcp_pat["frequency"]
                assert set(cli_pat.keys()) == set(mcp_pat.keys())
