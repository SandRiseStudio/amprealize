from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from amprealize.reflection_contracts import (
    ReflectionCandidate,
    ReflectionQualityScores,
    ReflectResponse,
)
from amprealize.trace_analysis_contracts import ExtractionJob, ExtractionJobStatus, PatternOccurrence, TracePattern
from scripts.nightly_reflection import NightlyReflectionJob, ReflectionJobConfig


pytestmark = pytest.mark.unit


def test_generate_candidate_persists_batch_provenance() -> None:
    config = ReflectionJobConfig()
    run_service = MagicMock()
    behavior_service = MagicMock()
    reflection_service = MagicMock()
    trace_analysis = MagicMock()
    storage = MagicMock()
    telemetry = MagicMock()

    candidate = ReflectionCandidate(
        slug="behavior_batch_reflection",
        display_name="Batch Reflection",
        instruction="Persist mined candidates through the shared queue.",
        summary="Batch-generated reflection candidate",
        supporting_steps=["Mine patterns", "Persist candidate"],
        examples=[],
        quality_scores=ReflectionQualityScores(
            clarity=0.9,
            generality=0.8,
            reusability=0.85,
            correctness=0.95,
        ),
        confidence=0.88,
        tags=["reflection", "batch"],
    )
    reflection_service.reflect.return_value = ReflectResponse(
        run_id="run-1",
        trace_step_count=2,
        candidates=[candidate],
        metadata={"elapsed_ms": 12.5},
    )
    storage.get_occurrences_by_pattern.return_value = [
        PatternOccurrence(
            occurrence_id="occ-1",
            pattern_id="pat-1",
            run_id="trace-1",
            occurrence_time="2026-04-28T00:00:00Z",
            start_step_index=0,
            end_step_index=1,
        ),
        PatternOccurrence(
            occurrence_id="occ-2",
            pattern_id="pat-1",
            run_id="trace-2",
            occurrence_time="2026-04-28T00:05:00Z",
            start_step_index=2,
            end_step_index=3,
        ),
    ]

    job = NightlyReflectionJob(
        config=config,
        run_service=run_service,
        behavior_service=behavior_service,
        reflection_service=reflection_service,
        trace_analysis=trace_analysis,
        storage=storage,
        telemetry=telemetry,
    )
    job.job = ExtractionJob(
        job_id="job-1",
        status=ExtractionJobStatus.RUNNING,
        start_time="2026-04-28T00:00:00Z",
    )

    pattern = TracePattern(
        pattern_id="pat-1",
        sequence=["Inspect traces", "Create candidate"],
        frequency=4,
        first_seen="2026-04-27T00:00:00Z",
        last_seen="2026-04-28T00:00:00Z",
        extracted_from_runs=["trace-2", "trace-3"],
    )

    job._generate_candidate(pattern, runs=[])

    reflect_request = reflection_service.reflect.call_args.args[0]
    assert reflect_request.run_id == "trace-1"
    assert reflect_request.trace_format.value == "chain_of_thought"
    assert "Step 1: Inspect traces" in reflect_request.trace_text

    reflection_service.create_candidate.assert_called_once()
    create_kwargs = reflection_service.create_candidate.call_args.kwargs
    assert create_kwargs["pattern_id"] == "pat-1"
    assert create_kwargs["historical_validation"]["source_run_ids"] == ["trace-1", "trace-2", "trace-3"]
    assert create_kwargs["metadata"]["source_run_id"] == "trace-1"
    assert create_kwargs["metadata"]["source_trace_ids"] == ["trace-1", "trace-2", "trace-3"]
    assert create_kwargs["metadata"]["extraction_job_id"] == "job-1"
    assert create_kwargs["metadata"]["pattern_frequency"] == 4
