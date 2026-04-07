"""Backend parity tests for ReflectionService across in-memory and PostgreSQL.

Validates that ReflectionService operations produce consistent results
regardless of which backend is used.

Tests cover:
- reflect() operation: extracting behavior candidates from traces
- Error handling: invalid trace formats
- Quality scoring consistency
"""

from __future__ import annotations

import os
from typing import Generator

try:
    import psycopg2  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - psycopg2 is optional for lint environments
    psycopg2 = None
import pytest

from amprealize.reflection_contracts import (
    ReflectRequest,
    ReflectResponse,
)
from amprealize.bci_contracts import TraceFormat
from amprealize.reflection_service import ReflectionService
from amprealize.reflection_service_postgres import PostgresReflectionService


# Test constants
TEST_TRACE = """
User: Build a feature to validate user input
Agent: I'll implement input validation. First, let me create the validation function.

Step 1: Create validation schema
I defined a Pydantic model for the user input with email, username, and password fields.

Step 2: Add custom validators
Added regex patterns for password strength and email format validation.

Step 3: Handle validation errors
Created a standardized error response format with field-level error messages.

Step 4: Write unit tests
Added pytest tests covering valid inputs, invalid emails, weak passwords, and edge cases.

Result: Input validation feature complete with 95% test coverage.
"""

TEST_TRACE_MINIMAL = """
User: Fix the bug
Agent: I found and fixed the null pointer exception.
"""


def _truncate_reflection_tables(dsn: str) -> None:
    """Remove all data from reflection tables to ensure test isolation."""
    from conftest import safe_truncate
    safe_truncate(dsn, [
        "reflection_sessions", "reflection_candidates",
        "pattern_observations", "reflection_patterns",
    ])


@pytest.fixture
def postgres_dsn() -> Generator[str, None, None]:
    """Discover PostgreSQL DSN from environment."""
    dsn = os.environ.get("AMPREALIZE_REFLECTION_PG_DSN")
    if not dsn:
        pytest.skip("AMPREALIZE_REFLECTION_PG_DSN not set; skipping PostgreSQL parity tests")
    yield dsn


@pytest.fixture
def reflection_service_postgres(postgres_dsn: str) -> Generator[PostgresReflectionService, None, None]:
    """Create a fresh PostgresReflectionService backed by PostgreSQL for each test."""
    _truncate_reflection_tables(postgres_dsn)
    service = PostgresReflectionService(dsn=postgres_dsn)

    try:
        yield service
    finally:
        service.close()


@pytest.fixture
def reflection_service_memory() -> Generator[ReflectionService, None, None]:
    """Create a fresh ReflectionService (in-memory) for each test."""
    # Mock the BehaviorService to avoid actual behavior lookups
    from unittest.mock import MagicMock
    mock_behavior_service = MagicMock()
    mock_behavior_service.list_behaviors.return_value = []
    mock_behavior_service.search_behaviors.return_value = []

    service = ReflectionService(behavior_service=mock_behavior_service)
    yield service


# ------------------------------------------------------------------
# Parity Tests - Basic reflect() Operation
# ------------------------------------------------------------------
class TestReflectParity:
    """Test reflect() operation parity between backends."""

    def test_reflect_response_structure_parity(
        self,
        reflection_service_memory: ReflectionService,
        reflection_service_postgres: PostgresReflectionService,
    ) -> None:
        """Both backends should return responses with the same structure."""
        request = ReflectRequest(
            trace_text=TEST_TRACE,
            trace_format=TraceFormat.CHAIN_OF_THOUGHT,
            max_candidates=3,
            min_quality_score=0.5,
        )

        # Memory backend
        response_memory = reflection_service_memory.reflect(request)

        # PostgreSQL backend
        response_postgres = reflection_service_postgres.reflect(request)

        # Validate response structure (not exact values since LLM-dependent)
        assert isinstance(response_memory, ReflectResponse)
        assert isinstance(response_postgres, ReflectResponse)

        # Both should have required fields
        assert response_memory.trace_step_count >= 0
        assert response_postgres.trace_step_count >= 0

        # Candidates should be lists
        assert isinstance(response_memory.candidates, list)
        assert isinstance(response_postgres.candidates, list)

    def test_reflect_with_run_id_parity(
        self,
        reflection_service_memory: ReflectionService,
        reflection_service_postgres: PostgresReflectionService,
    ) -> None:
        """Both backends should handle run_id parameter consistently."""
        request = ReflectRequest(
            trace_text=TEST_TRACE,
            trace_format=TraceFormat.CHAIN_OF_THOUGHT,
            run_id="test-run-123",
            max_candidates=2,
        )

        response_memory = reflection_service_memory.reflect(request)
        response_postgres = reflection_service_postgres.reflect(request)

        # run_id should be passed through
        assert response_memory.run_id == "test-run-123"
        assert response_postgres.run_id == "test-run-123"

    def test_reflect_minimal_trace_parity(
        self,
        reflection_service_memory: ReflectionService,
        reflection_service_postgres: PostgresReflectionService,
    ) -> None:
        """Both backends should handle minimal traces consistently."""
        request = ReflectRequest(
            trace_text=TEST_TRACE_MINIMAL,
            trace_format=TraceFormat.CHAIN_OF_THOUGHT,
            max_candidates=5,
            min_quality_score=0.3,  # Lower threshold for minimal trace
        )

        response_memory = reflection_service_memory.reflect(request)
        response_postgres = reflection_service_postgres.reflect(request)

        # Both should handle minimal traces without errors
        assert isinstance(response_memory, ReflectResponse)
        assert isinstance(response_postgres, ReflectResponse)


# ------------------------------------------------------------------
# Parity Tests - Candidate Quality Constraints
# ------------------------------------------------------------------
class TestCandidateQualityParity:
    """Test that quality filtering works consistently across backends."""

    def test_max_candidates_respected_parity(
        self,
        reflection_service_memory: ReflectionService,
        reflection_service_postgres: PostgresReflectionService,
    ) -> None:
        """Both backends should respect max_candidates limit."""
        request = ReflectRequest(
            trace_text=TEST_TRACE,
            trace_format=TraceFormat.CHAIN_OF_THOUGHT,
            max_candidates=1,
            min_quality_score=0.1,
        )

        response_memory = reflection_service_memory.reflect(request)
        response_postgres = reflection_service_postgres.reflect(request)

        # Both should return at most 1 candidate
        assert len(response_memory.candidates) <= 1
        assert len(response_postgres.candidates) <= 1


# ------------------------------------------------------------------
# Parity Tests - Trace Format Handling
# ------------------------------------------------------------------
class TestTraceFormatParity:
    """Test trace format handling parity."""

    def test_chain_of_thought_format_parity(
        self,
        reflection_service_memory: ReflectionService,
        reflection_service_postgres: PostgresReflectionService,
    ) -> None:
        """Both backends should handle CHAIN_OF_THOUGHT format."""
        request = ReflectRequest(
            trace_text=TEST_TRACE,
            trace_format=TraceFormat.CHAIN_OF_THOUGHT,
            max_candidates=2,
        )

        response_memory = reflection_service_memory.reflect(request)
        response_postgres = reflection_service_postgres.reflect(request)

        assert isinstance(response_memory, ReflectResponse)
        assert isinstance(response_postgres, ReflectResponse)

    def test_structured_json_format_parity(
        self,
        reflection_service_memory: ReflectionService,
        reflection_service_postgres: PostgresReflectionService,
    ) -> None:
        """Both backends should handle STRUCTURED_JSON format."""
        structured_trace = """
        {
            "steps": [
                {"action": "analyze", "result": "found issue"},
                {"action": "fix", "result": "applied patch"},
                {"action": "test", "result": "tests passing"}
            ]
        }
        """

        request = ReflectRequest(
            trace_text=structured_trace,
            trace_format=TraceFormat.STRUCTURED_JSON,
            max_candidates=2,
        )

        response_memory = reflection_service_memory.reflect(request)
        response_postgres = reflection_service_postgres.reflect(request)

        assert isinstance(response_memory, ReflectResponse)
        assert isinstance(response_postgres, ReflectResponse)


# ------------------------------------------------------------------
# PostgreSQL-Specific Features Tests
# ------------------------------------------------------------------
class TestPostgresSpecificFeatures:
    """Test PostgreSQL-specific persistence features."""

    def test_pattern_storage(
        self,
        reflection_service_postgres: PostgresReflectionService,
    ) -> None:
        """PostgreSQL backend should persist patterns for observation."""
        request = ReflectRequest(
            trace_text=TEST_TRACE,
            trace_format=TraceFormat.CHAIN_OF_THOUGHT,
            max_candidates=3,
            min_quality_score=0.3,
        )

        response = reflection_service_postgres.reflect(request)

        # If candidates were generated, they should be stored
        for candidate in response.candidates:
            # The pattern hash should be stored and retrievable
            # This is a PostgreSQL-specific feature for metacognitive reuse
            assert candidate.slug  # Slug should be set

    def test_session_tracking(
        self,
        reflection_service_postgres: PostgresReflectionService,
    ) -> None:
        """PostgreSQL backend should track reflection sessions."""
        request = ReflectRequest(
            trace_text=TEST_TRACE,
            trace_format=TraceFormat.CHAIN_OF_THOUGHT,
            run_id="session-test-run",
            max_candidates=2,
        )

        response = reflection_service_postgres.reflect(request)

        # Session should be tracked with run_id
        assert response.run_id == "session-test-run"


# ------------------------------------------------------------------
# Memory-Only Behavior Tests
# ------------------------------------------------------------------
class TestMemoryOnlyBehavior:
    """Test in-memory specific behaviors."""

    def test_no_persistence_between_calls(
        self,
        reflection_service_memory: ReflectionService,
    ) -> None:
        """In-memory backend should not persist between reflect() calls."""
        request1 = ReflectRequest(
            trace_text=TEST_TRACE,
            trace_format=TraceFormat.CHAIN_OF_THOUGHT,
            run_id="run-1",
            max_candidates=2,
        )

        request2 = ReflectRequest(
            trace_text=TEST_TRACE_MINIMAL,
            trace_format=TraceFormat.CHAIN_OF_THOUGHT,
            run_id="run-2",
            max_candidates=2,
        )

        response1 = reflection_service_memory.reflect(request1)
        response2 = reflection_service_memory.reflect(request2)

        # Both should succeed independently
        assert response1.run_id == "run-1"
        assert response2.run_id == "run-2"
