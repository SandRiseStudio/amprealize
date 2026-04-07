"""PostgreSQL-backed Reflection Service for persistent pattern and candidate storage.

This service extends the in-memory ReflectionService with PostgreSQL persistence
for reflection patterns, behavior candidates, and pattern observation tracking.

Behaviors referenced:
- behavior_migrate_postgres_schema: PostgreSQL migration pattern
- behavior_use_raze_for_logging: Structured logging via Raze
- behavior_align_storage_layers: Consistent storage interface

Usage:
    from amprealize.reflection_service_postgres import PostgresReflectionService

    service = PostgresReflectionService(
        dsn="postgresql://user:pass@host:5432/amprealize_reflection"
    )

    # Reflect on a trace (also persists patterns)
    response = service.reflect(ReflectRequest(
        trace_text="...",
        run_id="run-123"
    ))

    # Get candidate by ID
    candidate = service.get_candidate("candidate-abc")

    # Approve a candidate
    service.approve_candidate("candidate-abc", reviewed_by="user-1")

    # Track pattern observation for escalation
    service.observe_pattern(
        pattern_hash="abc123",
        pattern_type="procedural",
        description="Add logging to endpoints",
        run_id="run-456"
    )

    # Check if pattern needs escalation (3+ occurrences)
    if service.should_escalate_pattern("abc123"):
        # Escalate to Metacognitive Strategist
        ...
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import uuid4

from psycopg2 import extras

from .reflection_service import ReflectionService, _slugify
from .reflection_contracts import (
    ReflectRequest,
    ReflectResponse,
    ReflectionCandidate,
)
from .storage.postgres_pool import PostgresPool
from .storage.redis_cache import get_cache
from .telemetry import TelemetryClient

try:
    from .bci_service import BCIService
    from .behavior_service import BehaviorService
except ImportError:
    BCIService = None  # type: ignore
    BehaviorService = None  # type: ignore


logger = logging.getLogger(__name__)


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class StoredPattern:
    """Pattern stored in PostgreSQL."""
    pattern_id: str
    run_id: Optional[str]
    trace_id: Optional[str]
    pattern_type: str
    description: str
    frequency: int
    confidence: float
    context: Optional[Dict[str, Any]]
    metadata: Optional[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime


@dataclass
class StoredCandidate:
    """Behavior candidate stored in PostgreSQL."""
    candidate_id: str
    pattern_id: Optional[str]
    name: str
    summary: str
    triggers: List[str]
    steps: List[str]
    confidence: float
    status: str  # proposed, approved, rejected, merged
    role: str  # student, teacher, strategist
    keywords: List[str]
    historical_validation: Optional[Dict[str, Any]]
    reviewed_by: Optional[str]
    reviewed_at: Optional[datetime]
    merged_behavior_id: Optional[str]
    metadata: Optional[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime


@dataclass
class PatternObservation:
    """Individual pattern observation for tracking."""
    observation_id: str
    pattern_hash: str
    pattern_type: str
    description: str
    run_id: str
    trace_id: Optional[str]
    file_path: Optional[str]
    line_range: Optional[str]
    observed_at: datetime
    metadata: Optional[Dict[str, Any]]


@dataclass
class ReflectionSession:
    """Reflection session record."""
    session_id: str
    run_id: Optional[str]
    trace_id: Optional[str]
    session_type: str
    patterns_extracted: int
    candidates_generated: int
    status: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    error_message: Optional[str]
    metadata: Optional[Dict[str, Any]]
    created_at: datetime


# ============================================================================
# PostgreSQL Reflection Service
# ============================================================================

class PostgresReflectionService(ReflectionService):
    """PostgreSQL-backed ReflectionService with persistent storage.

    Extends the base ReflectionService to persist:
    - Extracted patterns from trace analysis
    - Behavior candidates with lifecycle tracking
    - Pattern observations for 3+ threshold escalation
    - Reflection sessions for audit/analytics

    The service maintains API compatibility with ReflectionService while
    adding persistence and additional query methods.
    """

    CACHE_SERVICE = "reflection"
    CACHE_TTL = 300  # 5 minutes
    ESCALATION_THRESHOLD = 3  # Per AGENTS.md: "Pattern observed 3+ times"

    def __init__(
        self,
        dsn: str,
        *,
        behavior_service: Optional[BehaviorService] = None,
        bci_service: Optional[BCIService] = None,
        telemetry: Optional[TelemetryClient] = None,
        window_sizes: Sequence[int] = (1, 2),
        auto_persist: bool = True,
    ) -> None:
        """Initialize PostgreSQL-backed ReflectionService.

        Args:
            dsn: PostgreSQL connection string
            behavior_service: Optional BehaviorService for duplicate detection
            bci_service: Optional BCIService for scoring
            telemetry: Optional TelemetryClient
            window_sizes: Window sizes for trace segmentation
            auto_persist: If True, automatically persist patterns and candidates
        """
        super().__init__(
            behavior_service=behavior_service,
            bci_service=bci_service,
            telemetry=telemetry,
            window_sizes=window_sizes,
        )
        self._pool = PostgresPool(dsn=dsn)
        self._auto_persist = auto_persist
        self._logger = logging.getLogger("amprealize.reflection_service_postgres")
        self._ensure_schema()
        self._logger.info("PostgresReflectionService initialized")

    def _ensure_schema(self) -> None:
        """Ensure database schema exists."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                # Check if tables exist
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = 'reflection_patterns'
                    )
                """)
                if not cur.fetchone()[0]:
                    self._logger.warning(
                        "Reflection tables not found. Run migration 020_create_reflection_service.sql"
                    )

    # ========================================================================
    # Override reflect() to persist results
    # ========================================================================

    def reflect(self, request: ReflectRequest) -> ReflectResponse:
        """Analyze trace and return candidates, optionally persisting results.

        Overrides base reflect() to:
        1. Create a reflection session
        2. Call parent reflect()
        3. Persist patterns and candidates if auto_persist is True
        4. Update session with results
        """
        session_id = str(uuid4())

        # Record session start
        if self._auto_persist:
            self._create_session(
                session_id=session_id,
                run_id=request.run_id,
                session_type="automatic",
            )

        try:
            # Call parent implementation
            response = super().reflect(request)

            # Persist results
            if self._auto_persist and response.candidates:
                for candidate in response.candidates:
                    self._persist_candidate(candidate, request.run_id)

            # Update session
            if self._auto_persist:
                self._complete_session(
                    session_id=session_id,
                    patterns_extracted=response.trace_step_count,
                    candidates_generated=len(response.candidates),
                )

            return response

        except Exception as e:
            if self._auto_persist:
                self._fail_session(session_id, str(e))
            raise

    # ========================================================================
    # Pattern Persistence
    # ========================================================================

    def create_pattern(
        self,
        pattern_type: str,
        description: str,
        *,
        run_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        confidence: float = 0.5,
        context: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> StoredPattern:
        """Create a new reflection pattern.

        Args:
            pattern_type: Type of pattern (procedural, structural, error_recovery)
            description: Human-readable pattern description
            run_id: Optional associated run ID
            trace_id: Optional associated trace ID
            confidence: Initial confidence score (0.0-1.0)
            context: Optional source context
            metadata: Optional additional metadata

        Returns:
            Created StoredPattern
        """
        pattern_id = f"pat_{uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        def _execute(conn):
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO reflection_patterns (
                        pattern_id, run_id, trace_id, pattern_type, description,
                        frequency, confidence, context, metadata, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                """, (
                    pattern_id, run_id, trace_id, pattern_type, description,
                    1, confidence,
                    json.dumps(context) if context else None,
                    json.dumps(metadata) if metadata else None,
                    now, now
                ))
                return cur.fetchone()

        row = self._pool.run_transaction("create_pattern", executor=_execute)
        get_cache().invalidate_service(self.CACHE_SERVICE)
        self._logger.info(f"Created pattern {pattern_id}")
        return self._row_to_pattern(row)

    def get_pattern(self, pattern_id: str) -> Optional[StoredPattern]:
        """Get a pattern by ID."""
        cache = get_cache()
        cache_key = f"pattern:{pattern_id}"

        cached = cache.get(cache_key)
        if cached:
            return StoredPattern(**cached)

        with self._pool.connection() as conn:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM reflection_patterns WHERE pattern_id = %s",
                    (pattern_id,)
                )
                row = cur.fetchone()

        if not row:
            return None

        pattern = self._row_to_pattern(row)
        cache.set(cache_key, asdict(pattern), ttl=self.CACHE_TTL)
        return pattern

    def list_patterns(
        self,
        *,
        pattern_type: Optional[str] = None,
        run_id: Optional[str] = None,
        min_confidence: float = 0.0,
        limit: int = 50,
        offset: int = 0,
    ) -> List[StoredPattern]:
        """List patterns with optional filtering."""
        conditions = ["confidence >= %s"]
        params: List[Any] = [min_confidence]

        if pattern_type:
            conditions.append("pattern_type = %s")
            params.append(pattern_type)

        if run_id:
            conditions.append("run_id = %s")
            params.append(run_id)

        where_clause = " AND ".join(conditions)
        params.extend([limit, offset])

        with self._pool.connection() as conn:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(f"""
                    SELECT * FROM reflection_patterns
                    WHERE {where_clause}
                    ORDER BY confidence DESC, created_at DESC
                    LIMIT %s OFFSET %s
                """, params)
                rows = cur.fetchall()

        return [self._row_to_pattern(row) for row in rows]

    # ========================================================================
    # Candidate Persistence
    # ========================================================================

    def create_candidate(
        self,
        name: str,
        summary: str,
        triggers: List[str],
        steps: List[str],
        *,
        pattern_id: Optional[str] = None,
        confidence: float = 0.5,
        role: str = "student",
        keywords: Optional[List[str]] = None,
        historical_validation: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> StoredCandidate:
        """Create a new behavior candidate.

        Args:
            name: Behavior name (behavior_<verb>_<noun> format)
            summary: One-line summary
            triggers: List of "when" conditions
            steps: List of procedure steps
            pattern_id: Optional associated pattern ID
            confidence: Confidence score (0.0-1.0)
            role: Proposed role (student, teacher, strategist)
            keywords: Keywords for retrieval
            historical_validation: Cases where this would have helped
            metadata: Additional metadata

        Returns:
            Created StoredCandidate
        """
        candidate_id = f"cand_{uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        # Ensure name follows convention
        if not name.startswith("behavior_"):
            name = f"behavior_{name}"

        def _execute(conn):
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO behavior_candidates (
                        candidate_id, pattern_id, name, summary, triggers, steps,
                        confidence, status, role, keywords, historical_validation,
                        metadata, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                """, (
                    candidate_id, pattern_id, name, summary,
                    triggers, steps, confidence, "proposed", role,
                    keywords or [],
                    json.dumps(historical_validation) if historical_validation else None,
                    json.dumps(metadata) if metadata else None,
                    now, now
                ))
                return cur.fetchone()

        row = self._pool.run_transaction("create_candidate", executor=_execute)
        get_cache().invalidate_service(self.CACHE_SERVICE)
        self._logger.info(f"Created candidate {candidate_id}: {name}")
        return self._row_to_candidate(row)

    def get_candidate(self, candidate_id: str) -> Optional[StoredCandidate]:
        """Get a candidate by ID."""
        cache = get_cache()
        cache_key = f"candidate:{candidate_id}"

        cached = cache.get(cache_key)
        if cached:
            return StoredCandidate(**cached)

        with self._pool.connection() as conn:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM behavior_candidates WHERE candidate_id = %s",
                    (candidate_id,)
                )
                row = cur.fetchone()

        if not row:
            return None

        candidate = self._row_to_candidate(row)
        cache.set(cache_key, asdict(candidate), ttl=self.CACHE_TTL)
        return candidate

    def list_candidates(
        self,
        *,
        status: Optional[str] = None,
        role: Optional[str] = None,
        min_confidence: float = 0.0,
        limit: int = 50,
        offset: int = 0,
    ) -> List[StoredCandidate]:
        """List candidates with optional filtering."""
        conditions = ["confidence >= %s"]
        params: List[Any] = [min_confidence]

        if status:
            conditions.append("status = %s")
            params.append(status)

        if role:
            conditions.append("role = %s")
            params.append(role)

        where_clause = " AND ".join(conditions)
        params.extend([limit, offset])

        with self._pool.connection() as conn:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(f"""
                    SELECT * FROM behavior_candidates
                    WHERE {where_clause}
                    ORDER BY confidence DESC, created_at DESC
                    LIMIT %s OFFSET %s
                """, params)
                rows = cur.fetchall()

        return [self._row_to_candidate(row) for row in rows]

    def approve_candidate(
        self,
        candidate_id: str,
        reviewed_by: str,
        merged_behavior_id: Optional[str] = None,
    ) -> StoredCandidate:
        """Approve a behavior candidate.

        Args:
            candidate_id: Candidate to approve
            reviewed_by: User/agent ID of reviewer
            merged_behavior_id: Optional ID if merged into handbook

        Returns:
            Updated StoredCandidate
        """
        now = datetime.now(timezone.utc)
        status = "merged" if merged_behavior_id else "approved"

        def _execute(conn):
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute("""
                    UPDATE behavior_candidates
                    SET status = %s, reviewed_by = %s, reviewed_at = %s,
                        merged_behavior_id = %s, updated_at = %s
                    WHERE candidate_id = %s
                    RETURNING *
                """, (status, reviewed_by, now, merged_behavior_id, now, candidate_id))
                return cur.fetchone()

        row = self._pool.run_transaction("approve_candidate", executor=_execute)
        if not row:
            raise ValueError(f"Candidate not found: {candidate_id}")

        get_cache().invalidate_service(self.CACHE_SERVICE)
        self._logger.info(f"Approved candidate {candidate_id} by {reviewed_by}")
        return self._row_to_candidate(row)

    def reject_candidate(
        self,
        candidate_id: str,
        reviewed_by: str,
        reason: Optional[str] = None,
    ) -> StoredCandidate:
        """Reject a behavior candidate.

        Args:
            candidate_id: Candidate to reject
            reviewed_by: User/agent ID of reviewer
            reason: Optional rejection reason

        Returns:
            Updated StoredCandidate
        """
        now = datetime.now(timezone.utc)

        def _execute(conn):
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                # Get existing metadata to append rejection reason
                cur.execute(
                    "SELECT metadata FROM behavior_candidates WHERE candidate_id = %s",
                    (candidate_id,)
                )
                existing = cur.fetchone()
                metadata = json.loads(existing["metadata"]) if existing and existing["metadata"] else {}
                if reason:
                    metadata["rejection_reason"] = reason

                cur.execute("""
                    UPDATE behavior_candidates
                    SET status = 'rejected', reviewed_by = %s, reviewed_at = %s,
                        metadata = %s, updated_at = %s
                    WHERE candidate_id = %s
                    RETURNING *
                """, (reviewed_by, now, json.dumps(metadata), now, candidate_id))
                return cur.fetchone()

        row = self._pool.run_transaction("reject_candidate", executor=_execute)
        if not row:
            raise ValueError(f"Candidate not found: {candidate_id}")

        get_cache().invalidate_service(self.CACHE_SERVICE)
        self._logger.info(f"Rejected candidate {candidate_id} by {reviewed_by}")
        return self._row_to_candidate(row)

    # ========================================================================
    # Pattern Observation Tracking
    # ========================================================================

    def observe_pattern(
        self,
        pattern_hash: str,
        pattern_type: str,
        description: str,
        run_id: str,
        *,
        trace_id: Optional[str] = None,
        file_path: Optional[str] = None,
        line_range: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PatternObservation:
        """Record a pattern observation for escalation tracking.

        Per AGENTS.md: "Pattern observed 3+ times" triggers escalation
        to Metacognitive Strategist for behavior extraction.

        Args:
            pattern_hash: Hash of pattern signature for deduplication
            pattern_type: Type of pattern
            description: Human-readable description
            run_id: Run where pattern was observed
            trace_id: Optional trace ID
            file_path: Optional file where pattern occurred
            line_range: Optional line range (e.g., "10-25")
            metadata: Additional metadata

        Returns:
            Created PatternObservation
        """
        observation_id = f"obs_{uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        def _execute(conn):
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                # Use INSERT ... ON CONFLICT DO NOTHING for idempotency
                cur.execute("""
                    INSERT INTO pattern_observations (
                        observation_id, pattern_hash, pattern_type, description,
                        run_id, trace_id, file_path, line_range, observed_at, metadata
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (pattern_hash, run_id) DO NOTHING
                    RETURNING *
                """, (
                    observation_id, pattern_hash, pattern_type, description,
                    run_id, trace_id, file_path, line_range, now,
                    json.dumps(metadata) if metadata else None
                ))
                return cur.fetchone()

        row = self._pool.run_transaction("observe_pattern", executor=_execute)
        if row:
            self._logger.debug(f"Recorded observation for pattern {pattern_hash[:8]}...")
            return self._row_to_observation(row)
        else:
            # Conflict - already observed in this run, return existing
            with self._pool.connection() as conn:
                with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                    cur.execute(
                        "SELECT * FROM pattern_observations WHERE pattern_hash = %s AND run_id = %s",
                        (pattern_hash, run_id)
                    )
                    row = cur.fetchone()
            return self._row_to_observation(row) if row else None

    def get_pattern_observation_count(self, pattern_hash: str) -> int:
        """Get the number of observations for a pattern."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM pattern_observations WHERE pattern_hash = %s",
                    (pattern_hash,)
                )
                return cur.fetchone()[0]

    def should_escalate_pattern(self, pattern_hash: str) -> bool:
        """Check if a pattern should be escalated (3+ observations).

        Per AGENTS.md: "Pattern observed 3+ times" triggers escalation.
        """
        return self.get_pattern_observation_count(pattern_hash) >= self.ESCALATION_THRESHOLD

    def list_escalatable_patterns(self, limit: int = 20) -> List[Tuple[str, str, int]]:
        """List patterns that meet the escalation threshold.

        Returns:
            List of (pattern_hash, description, count) tuples
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT pattern_hash, description, COUNT(*) as count
                    FROM pattern_observations
                    GROUP BY pattern_hash, description
                    HAVING COUNT(*) >= %s
                    ORDER BY count DESC
                    LIMIT %s
                """, (self.ESCALATION_THRESHOLD, limit))
                return [(row[0], row[1], row[2]) for row in cur.fetchall()]

    @staticmethod
    def compute_pattern_hash(description: str, pattern_type: str) -> str:
        """Compute a hash for pattern deduplication."""
        content = f"{pattern_type}:{description.lower().strip()}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    # ========================================================================
    # Session Management
    # ========================================================================

    def _create_session(
        self,
        session_id: str,
        run_id: Optional[str],
        session_type: str,
    ) -> None:
        """Create a reflection session record."""
        now = datetime.now(timezone.utc)

        def _execute(conn):
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO reflection_sessions (
                        session_id, run_id, session_type, status, started_at, created_at
                    ) VALUES (%s, %s, %s, 'running', %s, %s)
                """, (session_id, run_id, session_type, now, now))

        self._pool.run_transaction("create_session", executor=_execute)

    def _complete_session(
        self,
        session_id: str,
        patterns_extracted: int,
        candidates_generated: int,
    ) -> None:
        """Mark a session as completed."""
        now = datetime.now(timezone.utc)

        def _execute(conn):
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE reflection_sessions
                    SET status = 'completed', patterns_extracted = %s,
                        candidates_generated = %s, completed_at = %s
                    WHERE session_id = %s
                """, (patterns_extracted, candidates_generated, now, session_id))

        self._pool.run_transaction("complete_session", executor=_execute)

    def _fail_session(self, session_id: str, error_message: str) -> None:
        """Mark a session as failed."""
        now = datetime.now(timezone.utc)

        def _execute(conn):
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE reflection_sessions
                    SET status = 'failed', error_message = %s, completed_at = %s
                    WHERE session_id = %s
                """, (error_message, now, session_id))

        self._pool.run_transaction("fail_session", executor=_execute)

    def _persist_candidate(
        self,
        candidate: ReflectionCandidate,
        run_id: Optional[str],
    ) -> None:
        """Persist a ReflectionCandidate from reflect() output."""
        self.create_candidate(
            name=candidate.slug,
            summary=candidate.summary,
            triggers=[candidate.instruction] if candidate.instruction else [],
            steps=candidate.supporting_steps,
            confidence=candidate.confidence,
            role="student",  # Default; can be updated during review
            keywords=candidate.tags,
            metadata={
                "run_id": run_id,
                "display_name": candidate.display_name,
                "duplicate_behavior_id": candidate.duplicate_behavior_id,
                "quality_scores": (
                    candidate.quality_scores.to_dict()
                    if candidate.quality_scores else None
                ),
            },
        )

    # ========================================================================
    # Row Converters
    # ========================================================================

    def _row_to_pattern(self, row: Dict[str, Any]) -> StoredPattern:
        """Convert database row to StoredPattern."""
        return StoredPattern(
            pattern_id=row["pattern_id"],
            run_id=row.get("run_id"),
            trace_id=row.get("trace_id"),
            pattern_type=row["pattern_type"],
            description=row["description"],
            frequency=row.get("frequency", 1),
            confidence=float(row.get("confidence", 0.5)),
            context=json.loads(row["context"]) if row.get("context") else None,
            metadata=json.loads(row["metadata"]) if row.get("metadata") else None,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_candidate(self, row: Dict[str, Any]) -> StoredCandidate:
        """Convert database row to StoredCandidate."""
        return StoredCandidate(
            candidate_id=row["candidate_id"],
            pattern_id=row.get("pattern_id"),
            name=row["name"],
            summary=row["summary"],
            triggers=row.get("triggers") or [],
            steps=row.get("steps") or [],
            confidence=float(row.get("confidence", 0.5)),
            status=row.get("status", "proposed"),
            role=row.get("role", "student"),
            keywords=row.get("keywords") or [],
            historical_validation=(
                json.loads(row["historical_validation"])
                if row.get("historical_validation") else None
            ),
            reviewed_by=row.get("reviewed_by"),
            reviewed_at=row.get("reviewed_at"),
            merged_behavior_id=row.get("merged_behavior_id"),
            metadata=json.loads(row["metadata"]) if row.get("metadata") else None,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_observation(self, row: Dict[str, Any]) -> PatternObservation:
        """Convert database row to PatternObservation."""
        return PatternObservation(
            observation_id=row["observation_id"],
            pattern_hash=row["pattern_hash"],
            pattern_type=row["pattern_type"],
            description=row["description"],
            run_id=row["run_id"],
            trace_id=row.get("trace_id"),
            file_path=row.get("file_path"),
            line_range=row.get("line_range"),
            observed_at=row["observed_at"],
            metadata=json.loads(row["metadata"]) if row.get("metadata") else None,
        )


__all__ = [
    "PostgresReflectionService",
    "StoredPattern",
    "StoredCandidate",
    "PatternObservation",
    "ReflectionSession",
]
