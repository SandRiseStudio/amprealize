#!/usr/bin/env python3
"""Nightly batch reflection job for automated behavior extraction.

This script orchestrates the trace analysis pipeline:
1. Fetch recent runs from RunService
2. Detect patterns across runs using TraceAnalysisService
3. Score patterns for reusability
4. Generate behavior candidates for high-value patterns
5. Submit candidates to ReflectionService for approval

Configured via environment variables:
- AMPREALIZE_RUN_DB_PATH: Path to runs database
- AMPREALIZE_BEHAVIOR_DB_PATH: Path to behaviors database
- AMPREALIZE_REFLECTION_LOOKBACK_DAYS: Days to look back (default: 7)
- AMPREALIZE_REFLECTION_MIN_RUNS: Minimum runs to process (default: 10)
- AMPREALIZE_REFLECTION_MIN_FREQUENCY: Minimum pattern frequency (default: 3)
- AMPREALIZE_REFLECTION_MIN_SCORE: Minimum reusability score (default: 0.7)

Usage:
    python scripts/nightly_reflection.py [--dry-run] [--lookback-days N]
"""

import argparse
import logging
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import List, Optional

# Add amprealize to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from amprealize.action_contracts import Actor
from amprealize.behavior_service import BehaviorService
from amprealize.reflection_contracts import ReflectRequest
from amprealize.reflection_service import ReflectionService
from amprealize.run_contracts import Run, RunStatus
from amprealize.run_service import RunService
from amprealize.telemetry import TelemetryClient
from amprealize.trace_analysis_contracts import (
    DetectPatternsRequest,
    ExtractionJob,
    ExtractionJobStatus,
    ScoreReusabilityRequest,
)
from amprealize.trace_analysis_service import TraceAnalysisService
from amprealize.trace_analysis_service_postgres import PostgresTraceAnalysisService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("nightly_reflection")


class ReflectionJobConfig:
    """Configuration for nightly reflection job."""

    def __init__(self) -> None:
        self.lookback_days = int(os.getenv("AMPREALIZE_REFLECTION_LOOKBACK_DAYS", "7"))
        self.min_runs = int(os.getenv("AMPREALIZE_REFLECTION_MIN_RUNS", "10"))
        self.min_frequency = int(os.getenv("AMPREALIZE_REFLECTION_MIN_FREQUENCY", "3"))
        self.min_score = float(os.getenv("AMPREALIZE_REFLECTION_MIN_SCORE", "0.7"))
        self.pg_dsn = os.getenv("AMPREALIZE_TRACE_ANALYSIS_PG_DSN")
        self.dry_run = False

    def __str__(self) -> str:
        return (
            f"ReflectionJobConfig(lookback_days={self.lookback_days}, "
            f"min_runs={self.min_runs}, min_frequency={self.min_frequency}, "
            f"min_score={self.min_score}, pg_dsn={'***' if self.pg_dsn else None}, "
            f"dry_run={self.dry_run})"
        )


class NightlyReflectionJob:
    """Orchestrates batch pattern extraction and candidate generation."""

    def __init__(
        self,
        *,
        config: ReflectionJobConfig,
        run_service: RunService,
        behavior_service: BehaviorService,
        reflection_service: ReflectionService,
        trace_analysis: TraceAnalysisService,
        storage: Optional[PostgresTraceAnalysisService] = None,
        telemetry: Optional[TelemetryClient] = None,
    ) -> None:
        self.config = config
        self.run_service = run_service
        self.behavior_service = behavior_service
        self.reflection_service = reflection_service
        self.trace_analysis = trace_analysis
        self.storage = storage
        self.telemetry = telemetry or TelemetryClient.noop()
        self.job: Optional[ExtractionJob] = None

    def execute(self) -> ExtractionJob:
        """Run the batch extraction pipeline."""
        job_id = str(uuid.uuid4())
        start_time = datetime.now(UTC).isoformat()

        logger.info(f"Starting nightly reflection job {job_id}")
        logger.info(f"Config: {self.config}")

        # Create extraction job
        self.job = ExtractionJob(
            job_id=job_id,
            status=ExtractionJobStatus.PENDING,
            start_time=start_time,
            metadata={
                "lookback_days": self.config.lookback_days,
                "min_frequency": self.config.min_frequency,
                "min_score": self.config.min_score,
                "dry_run": self.config.dry_run,
            },
        )

        if self.storage:
            try:
                self.storage.store_extraction_job(self.job)
                logger.info(f"Extraction job {job_id} stored in PostgreSQL")
            except Exception as e:
                logger.warning(f"Failed to store extraction job: {e}")

        try:
            # Step 1: Fetch recent runs
            self._update_job_status(ExtractionJobStatus.RUNNING, "Fetching runs")
            runs = self._fetch_recent_runs()

            if len(runs) < self.config.min_runs:
                error_msg = f"Insufficient runs: {len(runs)} < {self.config.min_runs}"
                self._update_job_status(ExtractionJobStatus.FAILED, error_msg)
                logger.warning(error_msg)
                return self.job

            logger.info(f"Fetched {len(runs)} runs for analysis")
            self.job.runs_analyzed = len(runs)

            # Step 2: Detect patterns across runs
            self._update_job_status(ExtractionJobStatus.RUNNING, "Detecting patterns")
            patterns = self._detect_patterns(runs)
            logger.info(f"Detected {len(patterns)} patterns")
            self.job.patterns_found = len(patterns)

            # Step 3: Score patterns and generate candidates
            self._update_job_status(ExtractionJobStatus.RUNNING, "Scoring patterns")
            candidates_generated = 0

            for pattern in patterns:
                try:
                    # Score reusability
                    score_request = ScoreReusabilityRequest(
                        pattern_id=pattern.pattern_id,
                        total_runs=len(runs),
                        avg_trace_tokens=self._estimate_avg_tokens(runs),
                        unique_task_types=self._count_unique_tasks(runs),
                        total_task_types=len(runs),
                    )
                    score_response = self.trace_analysis.score_reusability(score_request)

                    if not score_response.meets_threshold:
                        logger.debug(
                            f"Pattern {pattern.pattern_id} scored {score_response.score.overall_score:.2f} "
                            f"< {self.config.min_score} threshold, skipping"
                        )
                        continue

                    # Generate behavior candidate
                    if self.config.dry_run:
                        logger.info(
                            f"[DRY RUN] Would generate candidate for pattern {pattern.pattern_id} "
                            f"(score: {score_response.score.overall_score:.2f})"
                        )
                        candidates_generated += 1
                    else:
                        self._generate_candidate(pattern, runs)
                        candidates_generated += 1

                except Exception as e:
                    logger.error(f"Error processing pattern {pattern.pattern_id}: {e}")
                    continue

            self.job.candidates_generated = candidates_generated
            logger.info(f"Generated {candidates_generated} behavior candidates")

            # Step 4: Mark job complete
            end_time = datetime.now(UTC).isoformat()
            self.job.end_time = end_time
            self.job.status = ExtractionJobStatus.COMPLETE
            self._update_job_status(ExtractionJobStatus.COMPLETE, "Job complete")

            # Emit telemetry
            self._emit_job_telemetry()

            return self.job

        except Exception as e:
            logger.exception(f"Job {job_id} failed: {e}")
            self.job.error_message = str(e)
            self.job.end_time = datetime.now(UTC).isoformat()
            self._update_job_status(ExtractionJobStatus.FAILED, str(e))
            return self.job

    def _fetch_recent_runs(self) -> List[Run]:
        """Fetch runs from the last N days."""
        cutoff_date = datetime.now(UTC) - timedelta(days=self.config.lookback_days)
        cutoff_iso = cutoff_date.isoformat()

        # List runs with completed status after cutoff date
        runs = self.run_service.list_runs(
            status=RunStatus.COMPLETED,
            limit=1000,  # Reasonable upper bound
        )

        # Filter by date (RunService.list_runs doesn't support date filtering)
        filtered_runs = [
            run
            for run in runs
            if run.completed_at and run.completed_at >= cutoff_iso
        ]

        logger.info(
            f"Found {len(filtered_runs)} completed runs since {cutoff_date.date()}"
        )
        return filtered_runs

    def _detect_patterns(self, runs: List[Run]) -> List:
        """Detect patterns across runs using TraceAnalysisService."""
        run_ids = [run.run_id for run in runs]

        request = DetectPatternsRequest(
            run_ids=run_ids,
            min_frequency=self.config.min_frequency,
            min_similarity=0.7,  # Standard threshold
            max_patterns=100,  # PRD default
            include_context=True,
        )

        response = self.trace_analysis.detect_patterns(request)
        return response.patterns

    def _estimate_avg_tokens(self, runs: List[Run]) -> int:
        """Estimate average trace tokens from run metadata."""
        token_counts = []
        for run in runs:
            tokens = run.metadata.get("tokens", {})
            baseline = tokens.get("baseline", 0)
            generated = tokens.get("generated", 0)
            if baseline or generated:
                token_counts.append(baseline + generated)

        if not token_counts:
            return 1000  # Default estimate

        return sum(token_counts) // len(token_counts)

    def _count_unique_tasks(self, runs: List[Run]) -> int:
        """Count unique task types from run workflow names."""
        task_types = {run.workflow_name for run in runs if run.workflow_name}
        return len(task_types)

    def _generate_candidate(self, pattern, runs: List[Run]) -> None:
        """Generate behavior candidate from pattern using ReflectionService."""
        # Build a synthetic trace from pattern occurrences
        # For now, use pattern sequence as the trace text
        trace_text = "\n".join(
            f"Step {i+1}: {step}" for i, step in enumerate(pattern.sequence)
        )

        # Create reflection request
        actor = Actor(
            id="system",
            role="automation",
            surface="batch",
        )

        reflect_request = ReflectRequest(
            trace_text=trace_text,
            trace_format="text",
            actor=actor,
            metadata={
                "pattern_id": pattern.pattern_id,
                "frequency": pattern.frequency,
                "extraction_job_id": self.job.job_id,
            },
        )

        # Call ReflectionService to generate candidates
        try:
            response = self.reflection_service.reflect(reflect_request)
            if response.candidates:
                logger.info(
                    f"Generated {len(response.candidates)} candidates from pattern {pattern.pattern_id}"
                )
        except Exception as e:
            logger.error(f"Failed to generate candidate for pattern {pattern.pattern_id}: {e}")
            raise

    def _update_job_status(self, status: ExtractionJobStatus, message: str) -> None:
        """Update extraction job status in storage."""
        if not self.job:
            return

        self.job.status = status
        if status in {ExtractionJobStatus.COMPLETE, ExtractionJobStatus.FAILED}:
            self.job.end_time = datetime.now(UTC).isoformat()

        logger.info(f"Job {self.job.job_id} status: {status} - {message}")

        if self.storage:
            try:
                self.storage.update_extraction_job_status(
                    job_id=self.job.job_id,
                    status=status,
                    runs_analyzed=self.job.runs_analyzed,
                    patterns_found=self.job.patterns_found,
                    candidates_generated=self.job.candidates_generated,
                    error_message=self.job.error_message,
                    end_time=self.job.end_time,
                )
            except Exception as e:
                logger.warning(f"Failed to update job status: {e}")

    def _emit_job_telemetry(self) -> None:
        """Emit telemetry event for completed job."""
        if not self.job:
            return

        # Emit job completion event
        self.telemetry.emit_event(
            event_type="trace_analysis.extraction_job_complete",
            payload={
                "job_id": self.job.job_id,
                "status": self.job.status.value if hasattr(self.job.status, "value") else str(self.job.status),
                "runs_analyzed": self.job.runs_analyzed,
                "patterns_found": self.job.patterns_found,
                "candidates_generated": self.job.candidates_generated,
                "duration_seconds": self.job.duration_seconds,
                "extraction_rate": self.job.extraction_rate,
                "lookback_days": self.config.lookback_days,
                "dry_run": self.config.dry_run,
            },
        )

        # Emit extraction rate metrics event for PRD tracking
        if self.job.status == ExtractionJobStatus.COMPLETE:
            self.telemetry.emit_event(
                event_type="trace_analysis.extraction_rate",
                payload={
                    "job_id": self.job.job_id,
                    "extraction_rate": self.job.extraction_rate,
                    "candidates_generated": self.job.candidates_generated,
                    "runs_analyzed": self.job.runs_analyzed,
                    "patterns_found": self.job.patterns_found,
                    "meets_target": self.job.extraction_rate >= 0.05,  # PRD target: 5 behaviors per 100 runs
                    "lookback_days": self.config.lookback_days,
                },
            )


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Nightly batch reflection job for automated behavior extraction"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without actually creating behavior candidates",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        help=f"Days to look back for runs (default: from env or 7)",
    )
    parser.add_argument(
        "--min-runs",
        type=int,
        help="Minimum runs required to proceed (default: from env or 10)",
    )
    parser.add_argument(
        "--min-frequency",
        type=int,
        help="Minimum pattern frequency (default: from env or 3)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Build configuration
    config = ReflectionJobConfig()
    if args.dry_run:
        config.dry_run = True
    if args.lookback_days:
        config.lookback_days = args.lookback_days
    if args.min_runs:
        config.min_runs = args.min_runs
    if args.min_frequency:
        config.min_frequency = args.min_frequency

    # Initialize services
    from amprealize.utils.dsn import apply_host_overrides
    run_dsn = apply_host_overrides(os.environ.get("AMPREALIZE_RUN_PG_DSN"), "RUN")
    if run_dsn:
        from amprealize.run_service_postgres import PostgresRunService
        run_service = PostgresRunService(dsn=run_dsn)
        logger.info("Using PostgresRunService for nightly reflection")
    else:
        run_service = RunService()
        logger.warning("AMPREALIZE_RUN_PG_DSN not set - using SQLite RunService")
    behavior_service = BehaviorService()
    reflection_service = ReflectionService(behavior_service=behavior_service)
    trace_analysis = TraceAnalysisService()

    # Initialize PostgreSQL storage if configured
    storage = None
    if config.pg_dsn:
        try:
            storage = PostgresTraceAnalysisService(
                dsn=config.pg_dsn,
                pattern_cache_ttl_seconds=600,
                occurrence_cache_ttl_seconds=300,
            )
            trace_analysis._storage = storage
            logger.info("PostgreSQL storage layer initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize PostgreSQL storage: {e}")

    # Create and execute job
    job_runner = NightlyReflectionJob(
        config=config,
        run_service=run_service,
        behavior_service=behavior_service,
        reflection_service=reflection_service,
        trace_analysis=trace_analysis,
        storage=storage,
    )

    job = job_runner.execute()

    # Print summary
    print("\n" + "=" * 60)
    print(f"Extraction Job Summary (ID: {job.job_id})")
    print("=" * 60)
    print(f"Status:              {job.status}")
    print(f"Runs Analyzed:       {job.runs_analyzed}")
    print(f"Patterns Found:      {job.patterns_found}")
    print(f"Candidates Generated: {job.candidates_generated}")
    if job.duration_seconds:
        print(f"Duration:            {job.duration_seconds:.1f}s")
        print(f"Extraction Rate:     {job.extraction_rate:.4f} (target: 0.05)")
    if job.error_message:
        print(f"Error:               {job.error_message}")
    print("=" * 60)

    return 0 if job.status == ExtractionJobStatus.COMPLETE else 1


if __name__ == "__main__":
    sys.exit(main())
