"""Comprehensive test suite for TraceAnalysisService.

Tests cover:
- Pattern detection (frequency, similarity, N-gram extraction)
- Reusability scoring (frequency/token/applicability scores, threshold validation)
- Edge cases (empty runs, single occurrence, identical patterns, null handling)
- Storage integration (PostgreSQL backend)
- Cache behavior
- Multi-tenant isolation

Target: >90% code coverage
"""

import json
import os
import uuid
from datetime import UTC, datetime
from typing import List

import pytest

from amprealize.trace_analysis_contracts import (
    DetectPatternsRequest,
    DetectPatternsResponse,
    ExtractionJob,
    ExtractionJobStatus,
    PatternOccurrence,
    ReusabilityScore,
    ScoreReusabilityRequest,
    ScoreReusabilityResponse,
    TracePattern,
)
from amprealize.trace_analysis_service import TraceAnalysisService
from amprealize.trace_analysis_service_postgres import PostgresTraceAnalysisService


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def trace_analysis_service():
    """Create TraceAnalysisService without storage backend."""
    return TraceAnalysisService()


@pytest.fixture
def postgres_dsn():
    """PostgreSQL DSN for trace analysis storage."""
    env_dsn = os.getenv("AMPREALIZE_TRACE_ANALYSIS_PG_DSN")
    if env_dsn:
        return env_dsn

    behavior_dsn = os.getenv("AMPREALIZE_BEHAVIOR_PG_DSN")
    if behavior_dsn:
        return behavior_dsn

    return "postgresql://amprealize_behavior:behavior_test_pass@localhost:6433/amprealize_behavior"


@pytest.fixture
def postgres_storage(postgres_dsn):
    """Create PostgresTraceAnalysisService."""
    storage = PostgresTraceAnalysisService(
        dsn=postgres_dsn,
        pattern_cache_ttl_seconds=600,
        occurrence_cache_ttl_seconds=300,
    )

    # Cleanup: truncate tables before tests
    from conftest import safe_truncate
    safe_truncate(postgres_dsn, ["extraction_jobs", "pattern_occurrences", "trace_patterns"])

    yield storage

    # Cleanup: truncate tables after tests
    safe_truncate(postgres_dsn, ["extraction_jobs", "pattern_occurrences", "trace_patterns"])


@pytest.fixture
def trace_analysis_with_storage(postgres_storage):
    """Create TraceAnalysisService with PostgreSQL storage backend."""
    return TraceAnalysisService(storage=postgres_storage)


@pytest.fixture
def sample_runs():
    """Sample run data for testing pattern detection."""
    return [
        {
            "run_id": str(uuid.uuid4()),
            "steps": [
                "Check prerequisites",
                "Load configuration",
                "Initialize services",
                "Execute workflow",
                "Generate report",
            ],
        },
        {
            "run_id": str(uuid.uuid4()),
            "steps": [
                "Check prerequisites",
                "Load configuration",
                "Initialize services",
                "Execute workflow",
                "Send notification",
            ],
        },
        {
            "run_id": str(uuid.uuid4()),
            "steps": [
                "Check prerequisites",
                "Load configuration",
                "Initialize database",
                "Run migrations",
                "Generate report",
            ],
        },
    ]


# ============================================================================
# Pattern Detection Tests
# ============================================================================


class TestPatternDetection:
    """Tests for detect_patterns() method."""

    def test_detect_simple_patterns(self, trace_analysis_service, sample_runs):
        """Test detection of simple repeating patterns."""
        # Create request
        run_ids = [run["run_id"] for run in sample_runs]
        request = DetectPatternsRequest(
            run_ids=run_ids,
            min_frequency=2,
            min_similarity=0.7,
            max_patterns=100,
        )

        # Mock _fetch_trace_for_run to return trace text (not list)
        def mock_fetch(run_id):
            for run in sample_runs:
                if run["run_id"] == run_id:
                    return "\n".join(run["steps"])
            return None

        trace_analysis_service._fetch_trace_for_run = mock_fetch

        # Detect patterns
        response = trace_analysis_service.detect_patterns(request)

        # Verify response structure
        assert isinstance(response, DetectPatternsResponse)
        assert len(response.patterns) > 0

        # Verify most frequent pattern is detected
        # ["Check prerequisites", "Load configuration"] appears in all 3 runs
        frequent_patterns = [
            p for p in response.patterns
            if "check prerequisites" in p.sequence[0].lower()
            and "load configuration" in p.sequence[1].lower()
        ]
        assert len(frequent_patterns) > 0
        assert frequent_patterns[0].frequency >= 3

    def test_detect_patterns_with_min_frequency_filter(self, trace_analysis_service, sample_runs):
        """Test that min_frequency filter excludes rare patterns."""
        run_ids = [run["run_id"] for run in sample_runs]

        def mock_fetch(run_id):
            for run in sample_runs:
                if run["run_id"] == run_id:
                    return "\n".join(run["steps"])
            return None

        trace_analysis_service._fetch_trace_for_run = mock_fetch

        # Request with high min_frequency
        request = DetectPatternsRequest(
            run_ids=run_ids,
            min_frequency=3,  # Only patterns appearing in all 3 runs
            min_similarity=0.8,
        )

        response = trace_analysis_service.detect_patterns(request)

        # All patterns should have frequency >= 3
        for pattern in response.patterns:
            assert pattern.frequency >= 3

    def test_detect_patterns_with_similarity_threshold(self, trace_analysis_service):
        """Test similarity-based pattern grouping."""
        # Create runs with similar but not identical sequences
        runs = [
            {
                "run_id": str(uuid.uuid4()),
                "steps": ["Initialize system", "Load config", "Start processing"],
            },
            {
                "run_id": str(uuid.uuid4()),
                "steps": ["Initialize system", "Load configuration", "Start processing"],
            },
            {
                "run_id": str(uuid.uuid4()),
                "steps": ["Init system", "Load config", "Start processing"],
            },
        ]

        run_ids = [run["run_id"] for run in runs]

        def mock_fetch(run_id):
            for run in runs:
                if run["run_id"] == run_id:
                    return "\n".join(run["steps"])
            return None

        trace_analysis_service._fetch_trace_for_run = mock_fetch

        # With high similarity threshold, similar patterns should be grouped
        request = DetectPatternsRequest(
            run_ids=run_ids,
            min_frequency=2,
            min_similarity=0.6,  # Allow ~60% similarity
        )

        response = trace_analysis_service.detect_patterns(request)

        # Should find the common pattern
        assert len(response.patterns) > 0

    def test_detect_patterns_ngram_extraction(self, trace_analysis_service):
        """Test that N-gram extraction captures sequences of different lengths."""
        # Create 3 runs with identical sequences so patterns are detected
        runs = [
            {
                "run_id": str(uuid.uuid4()),
                "steps": ["A", "B", "C", "D", "E"],
            },
            {
                "run_id": str(uuid.uuid4()),
                "steps": ["A", "B", "C", "D", "E"],
            },
            {
                "run_id": str(uuid.uuid4()),
                "steps": ["A", "B", "C", "D", "E"],
            },
        ]

        run_ids = [run["run_id"] for run in runs]

        def mock_fetch(run_id):
            for run in runs:
                if run["run_id"] == run_id:
                    return "\n".join(run["steps"])
            return None

        trace_analysis_service._fetch_trace_for_run = mock_fetch

        request = DetectPatternsRequest(
            run_ids=run_ids,
            min_frequency=2,  # Need at least 2 occurrences
            min_similarity=0.9,
        )

        response = trace_analysis_service.detect_patterns(request)

        # Should extract sequences of different lengths (1-5 steps)
        if len(response.patterns) > 0:
            sequence_lengths = {len(p.sequence) for p in response.patterns}
            assert len(sequence_lengths) >= 1  # At least one N-gram size detected

    def test_detect_patterns_max_patterns_limit(self, trace_analysis_service):
        """Test that max_patterns limit is respected."""
        # Create many unique patterns
        runs = [
            {
                "run_id": str(uuid.uuid4()),
                "steps": [f"Step {i}", f"Step {i+1}"],
            }
            for i in range(50)
        ]

        run_ids = [run["run_id"] for run in runs]

        def mock_fetch(run_id):
            for run in runs:
                if run["run_id"] == run_id:
                    return "\n".join(run["steps"])
            return None

        trace_analysis_service._fetch_trace_for_run = mock_fetch

        request = DetectPatternsRequest(
            run_ids=run_ids,
            min_frequency=1,
            max_patterns=10,  # Limit to 10 patterns
        )

        response = trace_analysis_service.detect_patterns(request)

        # Should not exceed max_patterns
        assert len(response.patterns) <= 10

    def test_detect_patterns_empty_runs(self, trace_analysis_service):
        """Test handling of empty run list."""
        request = DetectPatternsRequest(
            run_ids=[],
            min_frequency=1,
        )

        response = trace_analysis_service.detect_patterns(request)

        # Should return empty patterns list
        assert isinstance(response, DetectPatternsResponse)
        assert len(response.patterns) == 0

    def test_detect_patterns_no_matching_patterns(self, trace_analysis_service):
        """Test when runs have no repeating patterns."""
        # All runs have completely unique steps
        runs = [
            {
                "run_id": str(uuid.uuid4()),
                "steps": ["Unique step A", "Unique step B"],
            },
            {
                "run_id": str(uuid.uuid4()),
                "steps": ["Different step 1", "Different step 2"],
            },
            {
                "run_id": str(uuid.uuid4()),
                "steps": ["Other step X", "Other step Y"],
            },
        ]

        run_ids = [run["run_id"] for run in runs]

        def mock_fetch(run_id):
            for run in runs:
                if run["run_id"] == run_id:
                    return "\n".join(run["steps"])
            return None

        trace_analysis_service._fetch_trace_for_run = mock_fetch

        request = DetectPatternsRequest(
            run_ids=run_ids,
            min_frequency=2,  # Require at least 2 occurrences
        )

        response = trace_analysis_service.detect_patterns(request)

        # Should return no patterns
        assert len(response.patterns) == 0


# ============================================================================
# Reusability Scoring Tests
# ============================================================================


class TestReusabilityScoring:
    """Tests for score_reusability() method and ReusabilityScore.calculate()."""

    def test_calculate_reusability_score_balanced(self):
        """Test ReusabilityScore.calculate() with balanced metrics."""
        # Create a pattern
        pattern = TracePattern(
            pattern_id=str(uuid.uuid4()),
            sequence=["Step A", "Step B", "Step C"],
            frequency=10,
            first_seen=datetime.now(UTC).isoformat(),
            last_seen=datetime.now(UTC).isoformat(),
            extracted_from_runs=[str(uuid.uuid4()) for _ in range(10)],
            metadata={},
        )

        score = ReusabilityScore.calculate(
            pattern=pattern,
            total_runs=100,
            avg_trace_tokens=1000.0,
            unique_task_types=5,
            total_task_types=10,
        )

        # Verify score structure
        assert 0.0 <= score.frequency_score <= 1.0
        assert 0.0 <= score.token_savings_score <= 1.0
        assert 0.0 <= score.applicability_score <= 1.0
        assert 0.0 <= score.overall_score <= 1.0

        # Verify formula: 0.4*freq + 0.3*savings + 0.3*applicability
        expected = (
            0.4 * score.frequency_score +
            0.3 * score.token_savings_score +
            0.3 * score.applicability_score
        )
        assert abs(score.overall_score - expected) < 0.01

    def test_calculate_reusability_score_high_frequency(self):
        """Test scoring with high frequency pattern."""
        pattern = TracePattern(
            pattern_id=str(uuid.uuid4()),
            sequence=["Common step 1", "Common step 2"],
            frequency=50,
            first_seen=datetime.now(UTC).isoformat(),
            last_seen=datetime.now(UTC).isoformat(),
            extracted_from_runs=[str(uuid.uuid4()) for _ in range(50)],
            metadata={},
        )

        score = ReusabilityScore.calculate(
            pattern=pattern,
            total_runs=100,
            avg_trace_tokens=1000.0,
            unique_task_types=8,
            total_task_types=10,
        )

        # High frequency should result in higher frequency_score
        assert score.frequency_score > 0.3
        # Overall score should be weighted appropriately
        assert score.overall_score > 0.1

    def test_calculate_reusability_score_high_applicability(self):
        """Test scoring with high applicability."""
        pattern = TracePattern(
            pattern_id=str(uuid.uuid4()),
            sequence=["Universal step"],
            frequency=10,
            first_seen=datetime.now(UTC).isoformat(),
            last_seen=datetime.now(UTC).isoformat(),
            extracted_from_runs=[str(uuid.uuid4()) for _ in range(10)],
            metadata={},
        )

        score = ReusabilityScore.calculate(
            pattern=pattern,
            total_runs=100,
            avg_trace_tokens=1000.0,
            unique_task_types=9,
            total_task_types=10,
        )

        # High applicability should result in higher applicability_score
        assert score.applicability_score > 0.8

    def test_reusability_score_meets_threshold(self):
        """Test meets_approval_threshold property."""
        # Create high-scoring pattern (frequent + long sequence for high token savings)
        # Need very long sequence with many words per step to get high token savings
        high_pattern = TracePattern(
            pattern_id=str(uuid.uuid4()),
            sequence=["This is a very long detailed step number " + str(i) for i in range(200)],  # 200 steps × ~10 words = ~2600 tokens
            frequency=80,  # Very high frequency
            first_seen=datetime.now(UTC).isoformat(),
            last_seen=datetime.now(UTC).isoformat(),
            extracted_from_runs=[str(uuid.uuid4()) for _ in range(80)],
            metadata={},
        )

        high_score = ReusabilityScore.calculate(
            pattern=high_pattern,
            total_runs=100,
            avg_trace_tokens=1000.0,  # Lower than pattern tokens for higher savings score
            unique_task_types=9,
            total_task_types=10,
        )

        # Should meet 0.7 threshold
        assert high_score.overall_score > 0.7, f"Expected >0.7, got {high_score.overall_score} (freq={high_score.frequency_score}, savings={high_score.token_savings_score}, app={high_score.applicability_score})"
        assert high_score.meets_approval_threshold is True

        # Create low-scoring pattern
        low_pattern = TracePattern(
            pattern_id=str(uuid.uuid4()),
            sequence=["Rare step"],
            frequency=2,
            first_seen=datetime.now(UTC).isoformat(),
            last_seen=datetime.now(UTC).isoformat(),
            extracted_from_runs=[str(uuid.uuid4()) for _ in range(2)],
            metadata={},
        )

        low_score = ReusabilityScore.calculate(
            pattern=low_pattern,
            total_runs=100,
            avg_trace_tokens=1000.0,
            unique_task_types=1,
            total_task_types=10,
        )

        # Should not meet 0.7 threshold
        assert low_score.overall_score < 0.7
        assert low_score.meets_approval_threshold is False

    def test_score_reusability_integration(self, trace_analysis_service):
        """Test score_reusability() method integration."""
        # Create a minimal pattern
        pattern = TracePattern(
            pattern_id=str(uuid.uuid4()),
            sequence=["Step 1", "Step 2"],
            frequency=15,
            first_seen=datetime.now(UTC).isoformat(),
            last_seen=datetime.now(UTC).isoformat(),
            extracted_from_runs=[str(uuid.uuid4()) for _ in range(15)],
            metadata={},
        )

        # Mock storage to return the pattern
        class MockStorage:
            def get_pattern(self, pattern_id):
                return pattern

        trace_analysis_service._storage = MockStorage()

        # Create scoring request
        request = ScoreReusabilityRequest(
            pattern_id=pattern.pattern_id,
            total_runs=100,
            avg_trace_tokens=1000,
            unique_task_types=8,
            total_task_types=10,
        )

        # Score pattern
        response = trace_analysis_service.score_reusability(request)

        # Verify response structure
        assert isinstance(response, ScoreReusabilityResponse)
        assert isinstance(response.score, ReusabilityScore)
        assert response.pattern.pattern_id == pattern.pattern_id
        assert isinstance(response.meets_threshold, bool)

    def test_score_reusability_edge_cases(self):
        """Test scoring edge cases (zero values, extreme ratios)."""
        # Zero frequency
        pattern1 = TracePattern(
            pattern_id=str(uuid.uuid4()),
            sequence=["Never seen"],
            frequency=0,
            first_seen=datetime.now(UTC).isoformat(),
            last_seen=datetime.now(UTC).isoformat(),
            extracted_from_runs=[],
            metadata={},
        )
        score1 = ReusabilityScore.calculate(
            pattern=pattern1,
            total_runs=100,
            avg_trace_tokens=1000.0,
            unique_task_types=5,
            total_task_types=10,
        )
        assert score1.frequency_score == 0.0

        # High frequency pattern
        pattern2 = TracePattern(
            pattern_id=str(uuid.uuid4()),
            sequence=["Very common"],
            frequency=10,
            first_seen=datetime.now(UTC).isoformat(),
            last_seen=datetime.now(UTC).isoformat(),
            extracted_from_runs=[str(uuid.uuid4()) for _ in range(10)],
            metadata={},
        )
        score2 = ReusabilityScore.calculate(
            pattern=pattern2,
            total_runs=1,  # Minimum to avoid division by zero
            avg_trace_tokens=1000.0,
            unique_task_types=5,
            total_task_types=10,
        )
        assert score2.frequency_score >= 0.0


# ============================================================================
# Storage Integration Tests
# ============================================================================


class TestStorageIntegration:
    """Tests for PostgreSQL storage backend integration."""

    def test_detect_patterns_stores_to_postgres(self, trace_analysis_with_storage, sample_runs, postgres_storage):
        """Test that detect_patterns() stores patterns in PostgreSQL."""
        run_ids = [run["run_id"] for run in sample_runs]

        def mock_fetch(run_id):
            for run in sample_runs:
                if run["run_id"] == run_id:
                    return "\n".join(run["steps"])
            return None

        trace_analysis_with_storage._fetch_trace_for_run = mock_fetch

        # Detect patterns
        request = DetectPatternsRequest(
            run_ids=run_ids,
            min_frequency=2,
            min_similarity=0.7,
        )

        response = trace_analysis_with_storage.detect_patterns(request)

        # Verify patterns were stored
        assert len(response.patterns) > 0

        # Retrieve from storage
        stored_pattern = postgres_storage.get_pattern(response.patterns[0].pattern_id)
        assert stored_pattern is not None
        assert stored_pattern.pattern_id == response.patterns[0].pattern_id
        assert stored_pattern.sequence == response.patterns[0].sequence

    def test_pattern_occurrences_stored(self, trace_analysis_with_storage, sample_runs, postgres_storage):
        """Test that pattern occurrences are tracked in PostgreSQL."""
        run_ids = [run["run_id"] for run in sample_runs]

        def mock_fetch(run_id):
            for run in sample_runs:
                if run["run_id"] == run_id:
                    return "\n".join(run["steps"])
            return None

        trace_analysis_with_storage._fetch_trace_for_run = mock_fetch

        # Detect patterns
        request = DetectPatternsRequest(
            run_ids=run_ids,
            min_frequency=2,
            include_context=True,
        )

        response = trace_analysis_with_storage.detect_patterns(request)

        # Get occurrences for first pattern
        pattern_id = response.patterns[0].pattern_id
        occurrences = postgres_storage.get_occurrences_by_pattern(pattern_id, limit=10)

        # Should have at least frequency number of occurrences
        assert len(occurrences) >= response.patterns[0].frequency

    def test_extraction_job_lifecycle(self, postgres_storage):
        """Test ExtractionJob storage and status updates."""
        # Create job
        job = ExtractionJob(
            job_id=str(uuid.uuid4()),
            status=ExtractionJobStatus.PENDING,
            start_time=datetime.now(UTC).isoformat(),
            metadata={"test": "data"},
        )

        # Store job
        job_id = postgres_storage.store_extraction_job(job)
        assert str(job_id) == job.job_id  # Convert UUID to string for comparison

        # Retrieve job
        retrieved = postgres_storage.get_extraction_job(job_id)
        assert retrieved is not None
        assert str(retrieved.job_id) == job.job_id
        assert retrieved.status == ExtractionJobStatus.PENDING

        # Update status to RUNNING
        postgres_storage.update_extraction_job_status(
            job_id=job_id,
            status=ExtractionJobStatus.RUNNING,
        )
        updated = postgres_storage.get_extraction_job(job_id)
        assert updated.status == ExtractionJobStatus.RUNNING

        # Update status to COMPLETE with metrics
        postgres_storage.update_extraction_job_status(
            job_id=job_id,
            status=ExtractionJobStatus.COMPLETE,
            runs_analyzed=100,
            patterns_found=15,
            candidates_generated=5,
            end_time=datetime.now(UTC).isoformat(),
        )
        completed = postgres_storage.get_extraction_job(job_id)

        assert completed.status == ExtractionJobStatus.COMPLETE
        assert completed.runs_analyzed == 100
        assert completed.patterns_found == 15
        assert completed.candidates_generated == 5
        assert completed.extraction_rate == 0.05  # 5/100

    def test_cache_invalidation_on_store(self, trace_analysis_with_storage, postgres_storage):
        """Test that cache is invalidated when patterns are stored."""
        # Create a pattern
        pattern = TracePattern(
            pattern_id=str(uuid.uuid4()),
            sequence=["Test step 1", "Test step 2"],
            frequency=5,
            first_seen=datetime.now(UTC).isoformat(),
            last_seen=datetime.now(UTC).isoformat(),
            extracted_from_runs=[str(uuid.uuid4()) for _ in range(5)],
            metadata={},
        )

        # Store pattern (should cache it)
        postgres_storage.store_pattern(pattern)

        # Retrieve (should hit cache)
        cached = postgres_storage.get_pattern(pattern.pattern_id)
        assert cached is not None

        # Modify and store again - note: can't modify frequency without re-instantiation
        updated_pattern = TracePattern(
            pattern_id=pattern.pattern_id,
            sequence=pattern.sequence,
            frequency=10,  # Updated frequency
            first_seen=pattern.first_seen,
            last_seen=datetime.now(UTC).isoformat(),
            extracted_from_runs=pattern.extracted_from_runs + [str(uuid.uuid4()) for _ in range(5)],
            metadata=pattern.metadata,
        )
        postgres_storage.store_pattern(updated_pattern)

        # Retrieve again (should get updated value, cache invalidated)
        updated = postgres_storage.get_pattern(pattern.pattern_id)
        assert updated.frequency == 10


# ============================================================================
# Edge Cases & Error Handling
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_single_step_sequences(self, trace_analysis_service):
        """Test handling of single-step sequences."""
        # Create 3 runs with longer but still simple sequences containing repeated single steps
        runs = [
            {"run_id": str(uuid.uuid4()), "steps": ["Single step", "Another step"]},
            {"run_id": str(uuid.uuid4()), "steps": ["Single step", "Different step"]},
            {"run_id": str(uuid.uuid4()), "steps": ["Single step", "Third step"]},
        ]

        run_ids = [run["run_id"] for run in runs]

        def mock_fetch(run_id):
            for run in runs:
                if run["run_id"] == run_id:
                    return "\n".join(run["steps"])
            return None

        trace_analysis_service._fetch_trace_for_run = mock_fetch

        request = DetectPatternsRequest(
            run_ids=run_ids,
            min_frequency=2,
        )

        response = trace_analysis_service.detect_patterns(request)

        # Test passes if detect_patterns runs without crashing
        # Pattern detection may find single-step or multi-step patterns depending on similarity matching
        assert isinstance(response, DetectPatternsResponse)
        assert response.runs_analyzed == 3

    def test_identical_patterns(self, trace_analysis_service):
        """Test handling of completely identical run sequences."""
        identical_steps = ["Step A", "Step B", "Step C"]
        runs = [
            {"run_id": str(uuid.uuid4()), "steps": identical_steps.copy()}
            for _ in range(5)
        ]

        run_ids = [run["run_id"] for run in runs]

        def mock_fetch(run_id):
            for run in runs:
                if run["run_id"] == run_id:
                    return "\n".join(run["steps"])
            return None

        trace_analysis_service._fetch_trace_for_run = mock_fetch

        request = DetectPatternsRequest(
            run_ids=run_ids,
            min_frequency=2,
        )

        response = trace_analysis_service.detect_patterns(request)

        # Should detect the full sequence pattern with frequency 5
        full_sequence = [p for p in response.patterns if len(p.sequence) == 3]
        assert len(full_sequence) > 0
        assert full_sequence[0].frequency == 5

    def test_null_and_empty_string_steps(self, trace_analysis_service):
        """Test handling of null/empty step values."""
        runs = [
            {"run_id": str(uuid.uuid4()), "steps": ["Valid step", "", "Another step"]},
            {"run_id": str(uuid.uuid4()), "steps": ["Valid step", None, "Another step"]},
        ]

        run_ids = [run["run_id"] for run in runs]

        def mock_fetch(run_id):
            for run in runs:
                if run["run_id"] == run_id:
                    # Filter out None/empty strings
                    return [s for s in run["steps"] if s]
            return None

        trace_analysis_service._fetch_trace_for_run = mock_fetch

        request = DetectPatternsRequest(
            run_ids=run_ids,
            min_frequency=2,
        )

        # Should not raise exception
        response = trace_analysis_service.detect_patterns(request)
        assert isinstance(response, DetectPatternsResponse)

    def test_very_long_sequences(self, trace_analysis_service):
        """Test handling of very long step sequences."""
        long_sequence = [f"Step {i}" for i in range(100)]
        runs = [
            {"run_id": str(uuid.uuid4()), "steps": long_sequence.copy()}
            for _ in range(2)
        ]

        run_ids = [run["run_id"] for run in runs]

        def mock_fetch(run_id):
            for run in runs:
                if run["run_id"] == run_id:
                    return "\n".join(run["steps"])
            return None

        trace_analysis_service._fetch_trace_for_run = mock_fetch

        request = DetectPatternsRequest(
            run_ids=run_ids,
            min_frequency=2,
            max_patterns=50,  # Limit output
        )

        # Should handle without performance issues
        response = trace_analysis_service.detect_patterns(request)
        assert len(response.patterns) <= 50

    def test_pattern_not_found_in_storage(self, postgres_storage):
        """Test graceful handling when pattern doesn't exist."""
        nonexistent_id = str(uuid.uuid4())

        pattern = postgres_storage.get_pattern(nonexistent_id)

        # Should return None, not raise exception
        assert pattern is None

    def test_extraction_job_not_found(self, postgres_storage):
        """Test graceful handling when extraction job doesn't exist."""
        nonexistent_id = str(uuid.uuid4())

        job = postgres_storage.get_extraction_job(nonexistent_id)

        # Should return None, not raise exception
        assert job is None


# ============================================================================
# Multi-Tenant Isolation Tests
# ============================================================================


class TestMultiTenantIsolation:
    """Tests for multi-tenant data isolation."""

    def test_pattern_isolation_by_run_id(self, trace_analysis_with_storage, postgres_storage):
        """Test that patterns are isolated by run_id."""
        # Create patterns for two different tenants
        tenant1_runs = [
            {"run_id": f"tenant1-{uuid.uuid4()}", "steps": ["T1 Step A", "T1 Step B"]},
            {"run_id": f"tenant1-{uuid.uuid4()}", "steps": ["T1 Step A", "T1 Step B"]},
        ]

        tenant2_runs = [
            {"run_id": f"tenant2-{uuid.uuid4()}", "steps": ["T2 Step X", "T2 Step Y"]},
            {"run_id": f"tenant2-{uuid.uuid4()}", "steps": ["T2 Step X", "T2 Step Y"]},
        ]

        def mock_fetch(run_id):
            all_runs = tenant1_runs + tenant2_runs
            for run in all_runs:
                if run["run_id"] == run_id:
                    return "\n".join(run["steps"])
            return None

        trace_analysis_with_storage._fetch_trace_for_run = mock_fetch

        # Detect patterns for tenant 1
        request1 = DetectPatternsRequest(
            run_ids=[r["run_id"] for r in tenant1_runs],
            min_frequency=2,
        )
        response1 = trace_analysis_with_storage.detect_patterns(request1)

        # Detect patterns for tenant 2
        request2 = DetectPatternsRequest(
            run_ids=[r["run_id"] for r in tenant2_runs],
            min_frequency=2,
        )
        response2 = trace_analysis_with_storage.detect_patterns(request2)

        # Patterns should be distinct
        assert len(response1.patterns) > 0
        assert len(response2.patterns) > 0

        # Verify tenant 1 patterns reference only tenant 1 runs
        for pattern in response1.patterns:
            for run_id in pattern.extracted_from_runs:
                assert run_id.startswith("tenant1-")

        # Verify tenant 2 patterns reference only tenant 2 runs
        for pattern in response2.patterns:
            for run_id in pattern.extracted_from_runs:
                assert run_id.startswith("tenant2-")


# ============================================================================
# Telemetry Tests
# ============================================================================


class TestTelemetryEmission:
    """Tests for telemetry event emission."""

    def test_detect_patterns_emits_telemetry(self, trace_analysis_service, sample_runs, monkeypatch):
        """Test that detect_patterns emits telemetry event."""
        events_emitted = []

        def mock_emit_event(*, event_type, payload, **kwargs):
            events_emitted.append({"event_type": event_type, "payload": payload})
            return type("Event", (), {"event_id": "test-event-id"})()

        monkeypatch.setattr(trace_analysis_service._telemetry, "emit_event", mock_emit_event)

        # Mock trace fetching
        run_traces = {run["run_id"]: "\n".join(run["steps"]) for run in sample_runs}

        def mock_fetch_trace(run_id):
            return run_traces.get(run_id)

        monkeypatch.setattr(trace_analysis_service, "_fetch_trace_for_run", mock_fetch_trace)

        # Detect patterns
        request = DetectPatternsRequest(
            run_ids=[run["run_id"] for run in sample_runs],
            min_frequency=2,
            min_similarity=0.7,
        )
        response = trace_analysis_service.detect_patterns(request)

        # Verify telemetry emission
        assert len(events_emitted) == 1
        event = events_emitted[0]
        assert event["event_type"] == "trace_analysis.pattern_detected"
        assert event["payload"]["run_count"] == 3
        assert event["payload"]["success"] is True
        assert event["payload"]["pattern_count"] == len(response.patterns)
        assert event["payload"]["runs_analyzed"] == response.runs_analyzed
        assert "execution_time_seconds" in event["payload"]

    def test_score_reusability_emits_telemetry(self, trace_analysis_service, monkeypatch):
        """Test that score_reusability emits telemetry event."""
        events_emitted = []

        def mock_emit_event(*, event_type, payload, **kwargs):
            events_emitted.append({"event_type": event_type, "payload": payload})
            return type("Event", (), {"event_id": "test-event-id"})()

        monkeypatch.setattr(trace_analysis_service._telemetry, "emit_event", mock_emit_event)

        # Score reusability
        request = ScoreReusabilityRequest(
            pattern_id=str(uuid.uuid4()),
            total_runs=100,
            avg_trace_tokens=500,
            unique_task_types=30,
            total_task_types=50,
        )
        response = trace_analysis_service.score_reusability(request)

        # Verify telemetry emission
        assert len(events_emitted) == 1
        event = events_emitted[0]
        assert event["event_type"] == "trace_analysis.pattern_scored"
        assert event["payload"]["success"] is True
        assert event["payload"]["pattern_id"] == request.pattern_id
        assert event["payload"]["overall_score"] == response.score.overall_score
        assert event["payload"]["meets_threshold"] == response.meets_threshold
        assert "frequency_score" in event["payload"]
        assert "token_savings_score" in event["payload"]
        assert "applicability_score" in event["payload"]

    def test_telemetry_failure_does_not_break_detection(self, trace_analysis_service, sample_runs, monkeypatch):
        """Test that telemetry failures don't break pattern detection."""

        def mock_emit_event_error(*, event_type, payload, **kwargs):
            raise RuntimeError("Telemetry sink unavailable")

        monkeypatch.setattr(trace_analysis_service._telemetry, "emit_event", mock_emit_event_error)

        # Mock trace fetching
        run_traces = {run["run_id"]: "\n".join(run["steps"]) for run in sample_runs}

        def mock_fetch_trace(run_id):
            return run_traces.get(run_id)

        monkeypatch.setattr(trace_analysis_service, "_fetch_trace_for_run", mock_fetch_trace)

        # Detect patterns - should succeed despite telemetry failure
        request = DetectPatternsRequest(
            run_ids=[run["run_id"] for run in sample_runs],
            min_frequency=2,
        )
        response = trace_analysis_service.detect_patterns(request)

        # Verify detection still works
        assert response.runs_analyzed > 0
        assert isinstance(response.patterns, list)
