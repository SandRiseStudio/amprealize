"""Smoke tests for PostgresTraceAnalysisService - validate storage layer operations.

Quick validation tests (non-comprehensive):
- Pattern storage and retrieval
- Occurrence storage and retrieval
- Extraction job lifecycle
- Cache behavior

Run: pytest tests/test_trace_analysis_postgres_smoke.py -v
"""

import json
import os
import uuid
from datetime import datetime

import pytest

from amprealize.trace_analysis_contracts import (
    ExtractionJob,
    ExtractionJobStatus,
    PatternOccurrence,
    TracePattern,
)
from amprealize.trace_analysis_service_postgres import PostgresTraceAnalysisService


@pytest.fixture
def postgres_dsn():
    """Return PostgreSQL DSN for postgres-behavior database."""
    # Prefer explicit trace analysis DSN, then fall back to behavior service DSN
    explicit_dsn = os.getenv("AMPREALIZE_TRACE_ANALYSIS_PG_DSN")
    if explicit_dsn:
        return explicit_dsn

    behavior_dsn = os.getenv("AMPREALIZE_BEHAVIOR_PG_DSN")
    if behavior_dsn:
        return behavior_dsn

    return "postgresql://amprealize_behavior:behavior_test_pass@localhost:6433/amprealize_behavior"


@pytest.fixture
def service(postgres_dsn):
    """Create PostgresTraceAnalysisService instance."""
    return PostgresTraceAnalysisService(
        dsn=postgres_dsn,
        pattern_cache_ttl_seconds=600,
        occurrence_cache_ttl_seconds=300,
    )


@pytest.fixture
def sample_pattern():
    """Create a sample TracePattern for testing."""
    return TracePattern(
        pattern_id=str(uuid.uuid4()),
        sequence=["step 1: analyze input", "step 2: compute result", "step 3: format output"],
        frequency=5,
        first_seen=datetime.utcnow().isoformat() + "Z",
        last_seen=datetime.utcnow().isoformat() + "Z",
        extracted_from_runs=["run_001", "run_002", "run_003"],
        metadata={"task_type": "calculation", "domain": "math"},
    )


@pytest.fixture
def sample_occurrence(sample_pattern):
    """Create a sample PatternOccurrence for testing."""
    return PatternOccurrence(
        occurrence_id=str(uuid.uuid4()),
        pattern_id=sample_pattern.pattern_id,
        run_id=str(uuid.uuid4()),  # Must be UUID string
        occurrence_time=datetime.utcnow().isoformat() + "Z",
        start_step_index=2,
        end_step_index=4,
        context_before=["step 0: initialize", "step 1: load data"],
        context_after=["step 5: validate", "step 6: cleanup"],
        token_count=120,
    )


@pytest.fixture
def sample_job():
    """Create a sample ExtractionJob for testing."""
    return ExtractionJob(
        job_id=str(uuid.uuid4()),
        status=ExtractionJobStatus.PENDING,
        start_time=datetime.utcnow().isoformat() + "Z",
        end_time=None,
        runs_analyzed=0,
        patterns_found=0,
        candidates_generated=0,
        metadata={"batch_date": "2025-10-28", "filter": "completed_runs"},
    )


def test_store_and_get_pattern(service, sample_pattern):
    """Test pattern storage and retrieval."""
    # Store pattern
    pattern_id = service.store_pattern(sample_pattern)
    assert pattern_id == sample_pattern.pattern_id

    # Retrieve pattern (should hit cache on second call)
    retrieved = service.get_pattern(pattern_id)
    assert retrieved is not None
    assert retrieved.pattern_id == sample_pattern.pattern_id
    assert retrieved.sequence == sample_pattern.sequence
    assert retrieved.frequency == sample_pattern.frequency
    assert retrieved.extracted_from_runs == sample_pattern.extracted_from_runs


    # Note: Scores are stored in separate table, not returned by get_pattern


def test_store_and_get_occurrences(service, sample_pattern, sample_occurrence):
    """Test occurrence storage and retrieval."""
    # Store pattern and occurrence
    service.store_pattern(sample_pattern)
    occurrence_id = service.store_occurrence(sample_occurrence)
    assert occurrence_id == sample_occurrence.occurrence_id

    # Retrieve occurrences by pattern
    occurrences_by_pattern = service.get_occurrences_by_pattern(
        sample_pattern.pattern_id, limit=100
    )
    assert len(occurrences_by_pattern) >= 1
    assert any(occ.occurrence_id == occurrence_id for occ in occurrences_by_pattern)

    # Retrieve occurrences by run
    occurrences_by_run = service.get_occurrences_by_run(sample_occurrence.run_id, limit=100)
    assert len(occurrences_by_run) >= 1
    assert any(occ.occurrence_id == occurrence_id for occ in occurrences_by_run)


def test_extraction_job_lifecycle(service, sample_job):
    """Test extraction job creation and status updates."""
    # Store job
    job_id = service.store_extraction_job(sample_job)
    assert job_id == sample_job.job_id

    # Retrieve job (PENDING status)
    retrieved = service.get_extraction_job(job_id)
    assert retrieved is not None
    assert retrieved.status == ExtractionJobStatus.PENDING
    assert retrieved.runs_analyzed == 0

    # Update to RUNNING
    service.update_extraction_job_status(job_id, ExtractionJobStatus.RUNNING)
    retrieved = service.get_extraction_job(job_id)
    assert retrieved.status == ExtractionJobStatus.RUNNING

    # Update to COMPLETE with counters
    end_time = datetime.utcnow().isoformat() + "Z"
    service.update_extraction_job_status(
        job_id=job_id,
        status=ExtractionJobStatus.COMPLETE,
        end_time=end_time,
        runs_analyzed=100,
        patterns_found=42,
        candidates_generated=5,
    )
    retrieved = service.get_extraction_job(job_id)
    assert retrieved.status == ExtractionJobStatus.COMPLETE
    assert retrieved.runs_analyzed == 100
    assert retrieved.patterns_found == 42
    assert retrieved.candidates_generated == 5
    assert retrieved.extraction_rate == 0.05  # 5 / 100 = 0.05


def test_pattern_not_found(service):
    """Test get_pattern with non-existent ID."""
    nonexistent_id = str(uuid.uuid4())
    result = service.get_pattern(nonexistent_id)
    assert result is None


def test_job_not_found(service):
    """Test get_extraction_job with non-existent ID."""
    nonexistent_id = str(uuid.uuid4())
    result = service.get_extraction_job(nonexistent_id)
    assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
