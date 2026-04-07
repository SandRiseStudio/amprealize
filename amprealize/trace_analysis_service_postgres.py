"""PostgresTraceAnalysisService - PostgreSQL-backed pattern storage for TraceAnalysisService.

Production-ready pattern storage with:
- High-throughput pattern/occurrence ingestion
- JSONB sequence storage with GIN indexing
- Pattern similarity search via trigram indexes
- Redis caching for hot patterns (600s TTL)
- Connection pooling via PostgresPool
- Automatic data retention (1-year for occurrences)

Database: postgres-behavior (port 6433)
Schema: migration 013_create_trace_analysis.sql (4 tables, 13 indexes, 3 views)
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from amprealize.storage.postgres_pool import PostgresPool
from amprealize.storage.redis_cache import get_cache
from amprealize.trace_analysis_contracts import (
    ExtractionJob,
    ExtractionJobStatus,
    PatternOccurrence,
    TracePattern,
)


def _utc_now_iso() -> str:
    """Return current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat()


class PostgresTraceAnalysisService:
    """PostgreSQL-backed trace pattern storage with Redis caching.

    Features:
    - Pattern storage with JSONB sequence fields and GIN indexes
    - Occurrence tracking with composite PK (occurrence_id, occurrence_time)
    - Extraction job lifecycle management (PENDING → RUNNING → COMPLETE/FAILED)
    - Redis caching: patterns 600s TTL, occurrences 300s TTL, no job caching
    - Connection pooling via PostgresPool
    - Automatic retention policies (1-year for occurrences)

    Cache Strategy:
    - Pattern cache: 600s TTL, cache-first on get_pattern/get_occurrences
    - Occurrence cache: 300s TTL, cache-first on get_occurrences_by_*
    - Job cache: None (status updates need fresh data)
    - Cache invalidation on all writes

    Tables:
    - trace_patterns: Pattern definitions with JSONB sequences
    - pattern_occurrences: Individual occurrences with run_id FK
    - pattern_reusability_scores: Quality metrics (updated separately)
    - extraction_jobs: Batch job tracking
    """

    def __init__(
        self,
        dsn: str,
        pattern_cache_ttl_seconds: int = 600,
        occurrence_cache_ttl_seconds: int = 300,
    ):
        """Initialize PostgresTraceAnalysisService.

        Args:
            dsn: PostgreSQL connection string (postgres-behavior database)
            pattern_cache_ttl_seconds: TTL for pattern cache (default 600s = 10 minutes)
            occurrence_cache_ttl_seconds: TTL for occurrence cache (default 300s = 5 minutes)
        """
        self.pattern_cache_ttl_seconds = pattern_cache_ttl_seconds
        self.occurrence_cache_ttl_seconds = occurrence_cache_ttl_seconds
        self._pool = PostgresPool(dsn=dsn, service_name="trace_analysis")

    def store_pattern(self, pattern: TracePattern) -> str:
        """Store a new pattern to trace_patterns table.

        Args:
            pattern: TracePattern to persist

        Returns:
            pattern_id (UUID string)

        Side Effects:
            - Invalidates pattern cache for this pattern_id
            - Commits transaction automatically
        """
        pattern_id = pattern.pattern_id or str(uuid.uuid4())

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO trace_patterns (
                        pattern_id, sequence, frequency,
                        first_seen, last_seen,
                        extracted_from_runs, metadata
                    ) VALUES (
                        %(pattern_id)s, %(sequence)s, %(frequency)s,
                        %(first_seen)s, %(last_seen)s,
                        %(extracted_from_runs)s, %(metadata)s
                    )
                    ON CONFLICT (pattern_id) DO UPDATE SET
                        sequence = EXCLUDED.sequence,
                        frequency = EXCLUDED.frequency,
                        first_seen = EXCLUDED.first_seen,
                        last_seen = EXCLUDED.last_seen,
                        extracted_from_runs = EXCLUDED.extracted_from_runs,
                        metadata = EXCLUDED.metadata
                    """,
                    {
                        "pattern_id": pattern_id,
                        "sequence": json.dumps(pattern.sequence),
                        "frequency": pattern.frequency,
                        "first_seen": pattern.first_seen,
                        "last_seen": pattern.last_seen,
                        "extracted_from_runs": json.dumps(pattern.extracted_from_runs),
                        "metadata": json.dumps(pattern.metadata),
                    },
                )
            conn.commit()

        # Invalidate cache after write
        get_cache().delete(f"trace_analysis:pattern:{pattern_id}")

        return pattern_id

    def get_pattern(self, pattern_id: str) -> Optional[TracePattern]:
        """Retrieve a pattern by ID with Redis caching.

        Args:
            pattern_id: Pattern UUID to fetch

        Returns:
            TracePattern or None if not found

        Cache Strategy:
            - Cache-first: Check Redis before hitting database
            - 600s TTL (pattern_cache_ttl_seconds)
            - Cache key: trace_analysis:pattern:{pattern_id}
        """
        cache_key = f"trace_analysis:pattern:{pattern_id}"

        # Check cache first
        cached = get_cache().get(cache_key)
        if cached is not None:
            data = json.loads(cached)
            return TracePattern(
                pattern_id=data["pattern_id"],
                sequence=data["sequence"],
                frequency=data["frequency"],
                first_seen=data["first_seen"],
                last_seen=data["last_seen"],
                extracted_from_runs=data.get("extracted_from_runs", []),
                metadata=data.get("metadata", {}),
            )

        # Cache miss - query database
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        pattern_id,
                        sequence,
                        frequency,
                        first_seen,
                        last_seen,
                        extracted_from_runs,
                        metadata
                    FROM trace_patterns
                    WHERE pattern_id = %(pattern_id)s
                    """,
                    {"pattern_id": pattern_id},
                )
                row = cur.fetchone()

        if row is None:
            return None

        # Deserialize JSONB fields
        pattern = TracePattern(
            pattern_id=str(row[0]),  # Convert UUID to string
            sequence=json.loads(row[1]) if isinstance(row[1], str) else row[1],
            frequency=row[2],
            first_seen=row[3],
            last_seen=row[4],
            extracted_from_runs=(
                json.loads(row[5]) if isinstance(row[5], str) else row[5]
            ),
            metadata=json.loads(row[6]) if isinstance(row[6], str) else row[6],
        )

        # Populate cache
        cache_data = {
            "pattern_id": pattern.pattern_id,
            "sequence": pattern.sequence,
            "frequency": pattern.frequency,
            "first_seen": pattern.first_seen if isinstance(pattern.first_seen, str) else pattern.first_seen.isoformat(),
            "last_seen": pattern.last_seen if isinstance(pattern.last_seen, str) else pattern.last_seen.isoformat(),
            "extracted_from_runs": pattern.extracted_from_runs,
            "metadata": pattern.metadata,
        }
        get_cache().set(
            cache_key, json.dumps(cache_data), ttl=self.pattern_cache_ttl_seconds
        )

        return pattern

    def store_occurrence(self, occurrence: PatternOccurrence) -> str:
        """Store a pattern occurrence to pattern_occurrences table.

        Args:
            occurrence: PatternOccurrence to persist

        Returns:
            occurrence_id (UUID string)

        Side Effects:
            - Invalidates occurrence cache for pattern_id and run_id
            - Commits transaction automatically

        Note:
            - Composite PK (occurrence_id, occurrence_time) for time-series partitioning
            - occurrence_time defaults to NOW() if not provided
        """
        occurrence_id = occurrence.occurrence_id or str(uuid.uuid4())

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO pattern_occurrences (
                        occurrence_id,
                        pattern_id,
                        run_id,
                        occurrence_time,
                        start_step_index,
                        end_step_index,
                        context_before,
                        context_after,
                        token_count
                    ) VALUES (
                        %(occurrence_id)s,
                        %(pattern_id)s,
                        %(run_id)s,
                        %(occurrence_time)s,
                        %(start_step_index)s,
                        %(end_step_index)s,
                        %(context_before)s,
                        %(context_after)s,
                        %(token_count)s
                    )
                    """,
                    {
                        "occurrence_id": occurrence_id,
                        "pattern_id": occurrence.pattern_id,
                        "run_id": occurrence.run_id,
                        "occurrence_time": occurrence.occurrence_time or _utc_now_iso(),
                        "start_step_index": occurrence.start_step_index,
                        "end_step_index": occurrence.end_step_index,
                        "context_before": json.dumps(occurrence.context_before),
                        "context_after": json.dumps(occurrence.context_after),
                        "token_count": occurrence.token_count,
                    },
                )
            conn.commit()

        # Invalidate occurrence caches
        get_cache().delete(f"trace_analysis:occurrences:pattern:{occurrence.pattern_id}")
        get_cache().delete(f"trace_analysis:occurrences:run:{occurrence.run_id}")

        return occurrence_id

    def get_occurrences_by_pattern(
        self, pattern_id: str, limit: int = 100
    ) -> List[PatternOccurrence]:
        """Retrieve all occurrences of a pattern with Redis caching.

        Args:
            pattern_id: Pattern UUID to fetch occurrences for
            limit: Maximum number of occurrences to return (default 100)

        Returns:
            List of PatternOccurrence ordered by occurrence_time DESC

        Cache Strategy:
            - Cache-first: Check Redis before hitting database
            - 300s TTL (occurrence_cache_ttl_seconds)
            - Cache key: trace_analysis:occurrences:pattern:{pattern_id}
            - Cache stores JSON array of occurrences
        """
        cache_key = f"trace_analysis:occurrences:pattern:{pattern_id}"

        # Check cache first
        cached = get_cache().get(cache_key)
        if cached is not None:
            data_list = json.loads(cached)
            return [
                PatternOccurrence(
                    occurrence_id=item["occurrence_id"],
                    pattern_id=item["pattern_id"],
                    run_id=item["run_id"],
                    occurrence_time=item["occurrence_time"],
                    start_step_index=item["start_step_index"],
                    end_step_index=item["end_step_index"],
                    context_before=item.get("context_before", []),
                    context_after=item.get("context_after", []),
                    token_count=item.get("token_count", 0),
                )
                for item in data_list[:limit]
            ]

        # Cache miss - query database
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        occurrence_id,
                        pattern_id,
                        run_id,
                        occurrence_time,
                        start_step_index,
                        end_step_index,
                        context_before,
                        context_after,
                        token_count
                    FROM pattern_occurrences
                    WHERE pattern_id = %(pattern_id)s
                    ORDER BY occurrence_time DESC
                    LIMIT %(limit)s
                    """,
                    {"pattern_id": pattern_id, "limit": limit},
                )
                rows = cur.fetchall()

        if not rows:
            return []

        # Deserialize occurrences
        occurrences = []
        for row in rows:
            occurrences.append(
                PatternOccurrence(
                    occurrence_id=str(row[0]),
                    pattern_id=str(row[1]),
                    run_id=str(row[2]),
                    occurrence_time=row[3],
                    start_step_index=row[4],
                    end_step_index=row[5],
                    context_before=(
                        json.loads(row[6]) if isinstance(row[6], str) else row[6]
                    ),
                    context_after=(
                        json.loads(row[7]) if isinstance(row[7], str) else row[7]
                    ),
                    token_count=row[8] or 0,
                )
            )

        # Populate cache
        cache_data = [
            {
                "occurrence_id": occ.occurrence_id,
                "pattern_id": occ.pattern_id,
                "run_id": occ.run_id,
                "occurrence_time": occ.occurrence_time if isinstance(occ.occurrence_time, str) else occ.occurrence_time.isoformat(),
                "start_step_index": occ.start_step_index,
                "end_step_index": occ.end_step_index,
                "context_before": occ.context_before,
                "context_after": occ.context_after,
                "token_count": occ.token_count,
            }
            for occ in occurrences
        ]
        get_cache().set(
            cache_key,
            json.dumps(cache_data),
            ttl=self.occurrence_cache_ttl_seconds,
        )

        return occurrences

    def get_occurrences_by_run(
        self, run_id: str, limit: int = 100
    ) -> List[PatternOccurrence]:
        """Retrieve all pattern occurrences in a specific run with Redis caching.

        Args:
            run_id: Run UUID to fetch occurrences for
            limit: Maximum number of occurrences to return (default 100)

        Returns:
            List of PatternOccurrence ordered by start_step_index ASC

        Cache Strategy:
            - Cache-first: Check Redis before hitting database
            - 300s TTL (occurrence_cache_ttl_seconds)
            - Cache key: trace_analysis:occurrences:run:{run_id}
            - Cache stores JSON array of occurrences
        """
        cache_key = f"trace_analysis:occurrences:run:{run_id}"

        # Check cache first
        cached = get_cache().get(cache_key)
        if cached is not None:
            data_list = json.loads(cached)
            return [
                PatternOccurrence(
                    occurrence_id=item["occurrence_id"],
                    pattern_id=item["pattern_id"],
                    run_id=item["run_id"],
                    occurrence_time=item["occurrence_time"],
                    start_step_index=item["start_step_index"],
                    end_step_index=item["end_step_index"],
                    context_before=item.get("context_before", []),
                    context_after=item.get("context_after", []),
                    token_count=item.get("token_count", 0),
                )
                for item in data_list[:limit]
            ]

        # Cache miss - query database
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        occurrence_id,
                        pattern_id,
                        run_id,
                        occurrence_time,
                        start_step_index,
                        end_step_index,
                        context_before,
                        context_after,
                        token_count
                    FROM pattern_occurrences
                    WHERE run_id = %(run_id)s
                    ORDER BY start_step_index ASC
                    LIMIT %(limit)s
                    """,
                    {"run_id": run_id, "limit": limit},
                )
                rows = cur.fetchall()

        if not rows:
            return []

        # Deserialize occurrences
        occurrences = []
        for row in rows:
            occurrences.append(
                PatternOccurrence(
                    occurrence_id=str(row[0]),
                    pattern_id=str(row[1]),
                    run_id=str(row[2]),
                    occurrence_time=row[3],
                    start_step_index=row[4],
                    end_step_index=row[5],
                    context_before=(
                        json.loads(row[6]) if isinstance(row[6], str) else row[6]
                    ),
                    context_after=(
                        json.loads(row[7]) if isinstance(row[7], str) else row[7]
                    ),
                    token_count=row[8] or 0,
                )
            )

        # Populate cache
        cache_data = [
            {
                "occurrence_id": occ.occurrence_id,
                "pattern_id": occ.pattern_id,
                "run_id": occ.run_id,
                "occurrence_time": occ.occurrence_time if isinstance(occ.occurrence_time, str) else occ.occurrence_time.isoformat(),
                "start_step_index": occ.start_step_index,
                "end_step_index": occ.end_step_index,
                "context_before": occ.context_before,
                "context_after": occ.context_after,
                "token_count": occ.token_count,
            }
            for occ in occurrences
        ]
        get_cache().set(
            cache_key,
            json.dumps(cache_data),
            ttl=self.occurrence_cache_ttl_seconds,
        )

        return occurrences

    def store_extraction_job(self, job: ExtractionJob) -> str:
        """Store a new extraction job to extraction_jobs table.

        Args:
            job: ExtractionJob to persist

        Returns:
            job_id (UUID string)

        Side Effects:
            - No cache invalidation (jobs are not cached)
            - Commits transaction automatically

        Note:
            - duration_seconds computed via GENERATED ALWAYS AS expression
            - extraction_rate computed via GENERATED ALWAYS AS expression
        """
        job_id = job.job_id or str(uuid.uuid4())

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO extraction_jobs (
                        job_id,
                        status,
                        start_time,
                        end_time,
                        runs_analyzed,
                        patterns_found,
                        candidates_generated,
                        error_message,
                        metadata
                    ) VALUES (
                        %(job_id)s,
                        %(status)s,
                        %(start_time)s,
                        %(end_time)s,
                        %(runs_analyzed)s,
                        %(patterns_found)s,
                        %(candidates_generated)s,
                        %(error_message)s,
                        %(metadata)s
                    )
                    """,
                    {
                        "job_id": job_id,
                        "status": job.status.value,
                        "start_time": job.start_time or _utc_now_iso(),
                        "end_time": job.end_time,
                        "runs_analyzed": job.runs_analyzed,
                        "patterns_found": job.patterns_found,
                        "candidates_generated": job.candidates_generated,
                        "error_message": job.error_message,
                        "metadata": json.dumps(job.metadata),
                    },
                )
            conn.commit()

        return job_id

    def get_extraction_job(self, job_id: str) -> Optional[ExtractionJob]:
        """Retrieve an extraction job by ID (no caching - status changes frequently).

        Args:
            job_id: Job UUID to fetch

        Returns:
            ExtractionJob or None if not found

        Note:
            - No Redis caching for jobs (status updates need fresh data)
            - duration_seconds and extraction_rate computed by database
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        job_id,
                        status,
                        start_time,
                        end_time,
                        runs_analyzed,
                        patterns_found,
                        candidates_generated,
                        error_message,
                        metadata,
                        duration_seconds,
                        extraction_rate
                    FROM extraction_jobs
                    WHERE job_id = %(job_id)s
                    """,
                    {"job_id": job_id},
                )
                row = cur.fetchone()

        if row is None:
            return None

        return ExtractionJob(
            job_id=row[0],
            status=ExtractionJobStatus(row[1]),
            start_time=row[2],
            end_time=row[3],
            runs_analyzed=row[4],
            patterns_found=row[5],
            candidates_generated=row[6],
            error_message=row[7],
            metadata=json.loads(row[8]) if isinstance(row[8], str) else row[8],
        )

    def update_extraction_job_status(
        self,
        job_id: str,
        status: ExtractionJobStatus,
        end_time: Optional[str] = None,
        runs_analyzed: Optional[int] = None,
        patterns_found: Optional[int] = None,
        candidates_generated: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Update extraction job status and counters.

        Args:
            job_id: Job UUID to update
            status: New status (PENDING/RUNNING/COMPLETE/FAILED)
            end_time: ISO timestamp when job finished (optional)
            runs_analyzed: Total runs processed (optional)
            patterns_found: Total patterns detected (optional)
            candidates_generated: Total candidates submitted (optional)
            error_message: Error details if status=FAILED (optional)

        Side Effects:
            - No cache invalidation (jobs are not cached)
            - Commits transaction automatically
            - duration_seconds and extraction_rate recomputed automatically

        Usage:
            - PENDING → RUNNING: update_extraction_job_status(job_id, RUNNING)
            - RUNNING → COMPLETE: update_extraction_job_status(job_id, COMPLETE, end_time=now, runs_analyzed=100, patterns_found=42, candidates_generated=5)
            - RUNNING → FAILED: update_extraction_job_status(job_id, FAILED, end_time=now, error_message="Timeout")
        """
        # Build dynamic update clause
        update_fields = ["status = %(status)s"]
        params: Dict[str, Any] = {"job_id": job_id, "status": status.value}

        if end_time is not None:
            update_fields.append("end_time = %(end_time)s")
            params["end_time"] = end_time

        if runs_analyzed is not None:
            update_fields.append("runs_analyzed = %(runs_analyzed)s")
            params["runs_analyzed"] = runs_analyzed

        if patterns_found is not None:
            update_fields.append("patterns_found = %(patterns_found)s")
            params["patterns_found"] = patterns_found

        if candidates_generated is not None:
            update_fields.append("candidates_generated = %(candidates_generated)s")
            params["candidates_generated"] = candidates_generated

        if error_message is not None:
            update_fields.append("error_message = %(error_message)s")
            params["error_message"] = error_message

        update_clause = ", ".join(update_fields)

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE extraction_jobs
                    SET {update_clause}
                    WHERE job_id = %(job_id)s
                    """,
                    params,
                )
            conn.commit()
