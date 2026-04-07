"""TraceAnalysisService - automated behavior extraction from execution traces.

Implements PRD Component B requirements:
- parse_cot_trace: Segment reasoning into discrete steps (via segment())
- detect_patterns: Identify repeated sub-procedures across multiple traces
- score_reusability: Calculate frequency, token savings, cross-task applicability

Success targets (PRD lines 350-353):
- Extract ≥5 high-quality behaviors per 100 runs (0.05 extraction rate)
- 80% approval rate for auto-extracted candidates
- Reduce duplicate manual submissions by 50%
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .bci_contracts import SegmentTraceRequest, TraceFormat, TraceStep
from .bci_service import BCIService
from .telemetry import TelemetryClient
from .trace_analysis_contracts import (
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

logger = logging.getLogger(__name__)


@dataclass
class _Snippet:
    """Internal helper for snippet extraction (backward compatibility with ReflectionService)."""

    text: str
    steps: Sequence[TraceStep]


@dataclass
class _PatternMatch:
    """Internal helper for pattern detection algorithm."""

    sequence: List[str]
    run_ids: Set[str]
    occurrences: List[Tuple[str, int, int]]  # (run_id, start_idx, end_idx)
    first_seen: datetime
    last_seen: datetime


class TraceAnalysisService:
    """Automated behavior extraction from execution traces.

    Core responsibilities:
    - Segment traces into discrete reasoning steps
    - Detect recurring patterns across multiple runs
    - Score pattern reusability for candidate generation
    - Track extraction job metrics
    """

    def __init__(
        self,
        *,
        bci_service: Optional[BCIService] = None,
        storage: Optional[Any] = None,  # PostgresTraceAnalysisService or compatible
        telemetry: Optional[TelemetryClient] = None,
    ) -> None:
        """Initialize TraceAnalysisService.

        Args:
            bci_service: BCIService for trace segmentation (default: BCIService())
            storage: Storage backend for pattern persistence (optional for in-memory mode)
            telemetry: TelemetryClient for observability (default: TelemetryClient.noop())
        """
        self._bci_service = bci_service or BCIService()
        self._storage = storage
        self._telemetry = telemetry or TelemetryClient.noop()

    # ------------------------------------------------------------------
    # Public API - Trace Segmentation (existing functionality)
    # ------------------------------------------------------------------

    def segment(self, *, trace_text: str, trace_format: TraceFormat) -> List[TraceStep]:
        """Segment a trace into discrete reasoning steps.

        Implements PRD parse_cot_trace() requirement.

        Args:
            trace_text: Raw trace output from execution
            trace_format: Format of the trace (CHAIN_OF_THOUGHT, STRUCTURED, etc.)

        Returns:
            List of TraceStep objects with indexed positions
        """
        request = SegmentTraceRequest(trace_text=trace_text, format=trace_format)
        response = self._bci_service.segment_trace(request)
        return response.steps

    def iter_snippets(
        self, steps: Sequence[TraceStep], window_sizes: Sequence[int]
    ) -> Iterable[_Snippet]:
        """Generate sliding window snippets from trace steps.

        Used by ReflectionService for single-trace candidate extraction.

        Args:
            steps: Segmented trace steps
            window_sizes: Window sizes to extract (e.g., [1, 2] for 1-step and 2-step sequences)

        Yields:
            _Snippet objects with text and step sequences
        """
        normalized = [step for step in steps if step.text.strip()]
        for window in window_sizes:
            if window <= 0:
                continue
            for start in range(0, len(normalized)):
                end = start + window
                if end > len(normalized):
                    break
                chunk = normalized[start:end]
                text = " ".join(step.text.strip() for step in chunk).strip()
                if not text:
                    continue
                if len(text.split()) < 4:  # Minimum 4 words for meaningful pattern
                    continue
                yield _Snippet(text=text, steps=chunk)

    # ------------------------------------------------------------------
    # Public API - Pattern Detection (new Phase 4 Item 4 functionality)
    # ------------------------------------------------------------------

    def detect_patterns(self, request: DetectPatternsRequest) -> DetectPatternsResponse:
        """Detect recurring patterns across multiple runs.

        Implements PRD detect_patterns() requirement.

        Algorithm:
        1. Segment each run's trace
        2. Extract all possible sequences (sliding window)
        3. Normalize sequences for comparison
        4. Group similar sequences using similarity threshold
        5. Count frequency and track occurrences
        6. Filter by min_frequency
        7. Store patterns if storage backend available

        Args:
            request: DetectPatternsRequest with run_ids and detection parameters

        Returns:
            DetectPatternsResponse with detected patterns sorted by frequency
        """
        start_time = datetime.utcnow()

        # Step 1-2: Segment traces and extract sequences
        all_sequences: Dict[str, List[Tuple[List[str], int, int]]] = {}  # run_id -> [(sequence, start, end)]
        runs_analyzed = 0

        for run_id in request.run_ids:
            try:
                # TODO: Fetch trace from RunService instead of placeholder
                trace_text = self._fetch_trace_for_run(run_id)
                if not trace_text:
                    logger.warning(f"No trace found for run {run_id}")
                    continue

                steps = self.segment(trace_text=trace_text, trace_format=TraceFormat.CHAIN_OF_THOUGHT)
                sequences = self._extract_sequences_from_steps(steps)
                all_sequences[run_id] = sequences
                runs_analyzed += 1
            except Exception as exc:
                logger.warning(f"Failed to process run {run_id}: {exc}")
                continue

        # Step 3-5: Group similar sequences and count frequency
        pattern_matches = self._group_similar_sequences(
            all_sequences,
            min_similarity=request.min_similarity,
            include_context=request.include_context,
        )

        # Step 6: Filter by frequency threshold
        filtered_matches = [
            match for match in pattern_matches if len(match.run_ids) >= request.min_frequency
        ]

        # Sort by frequency (descending)
        filtered_matches.sort(key=lambda m: len(m.run_ids), reverse=True)

        # Limit results
        limited_matches = filtered_matches[: request.max_patterns]

        # Step 7: Convert to TracePattern contracts
        patterns: List[TracePattern] = []
        total_occurrences = 0

        for match in limited_matches:
            pattern_id = str(uuid.uuid4())
            pattern = TracePattern(
                pattern_id=pattern_id,
                sequence=match.sequence,
                frequency=len(match.run_ids),
                first_seen=match.first_seen.isoformat() + "Z",
                last_seen=match.last_seen.isoformat() + "Z",
                extracted_from_runs=list(match.run_ids),
                metadata={
                    "occurrence_count": len(match.occurrences),
                    "avg_sequence_length": len(match.sequence),
                },
            )
            patterns.append(pattern)
            total_occurrences += len(match.occurrences)

            # Store pattern if storage backend available
            if self._storage:
                try:
                    self._storage.store_pattern(pattern)

                    # Store occurrences
                    if request.include_context:
                        for run_id, start_idx, end_idx in match.occurrences:
                            occurrence = PatternOccurrence(
                                occurrence_id=str(uuid.uuid4()),
                                pattern_id=pattern_id,
                                run_id=run_id,
                                occurrence_time=datetime.utcnow().isoformat() + "Z",
                                start_step_index=start_idx,
                                end_step_index=end_idx,
                                context_before=[],  # TODO: Capture context from trace
                                context_after=[],
                                token_count=int(pattern.avg_tokens_per_step * len(match.sequence)),
                            )
                            self._storage.store_occurrence(occurrence)
                except Exception as exc:
                    logger.warning(f"Failed to store pattern {pattern_id}: {exc}")

        end_time = datetime.utcnow()
        execution_time_seconds = (end_time - start_time).total_seconds()

        response = DetectPatternsResponse(
            patterns=patterns,
            runs_analyzed=runs_analyzed,
            total_occurrences=total_occurrences,
            execution_time_seconds=round(execution_time_seconds, 3),
            metadata={
                "min_frequency": request.min_frequency,
                "min_similarity": request.min_similarity,
                "max_patterns": request.max_patterns,
                "filtered_count": len(filtered_matches),
            },
        )

        # Emit telemetry event
        self._emit_pattern_detection_telemetry(
            request=request,
            response=response,
            success=True,
            error=None,
        )

        return response

    def score_reusability(self, request: ScoreReusabilityRequest) -> ScoreReusabilityResponse:
        """Score a pattern's reusability potential.

        Implements PRD score_reusability() requirement.

        Formula:
        - frequency_score = pattern.frequency / total_runs (0-1)
        - token_savings_score = estimated_savings / avg_trace_tokens (0-1)
        - applicability_score = unique_task_types / total_task_types (0-1)
        - overall_score = 0.4*freq + 0.3*savings + 0.3*applicability

        Args:
            request: ScoreReusabilityRequest with pattern and corpus metrics

        Returns:
            ScoreReusabilityResponse with calculated scores and threshold check
        """
        # Fetch pattern from storage or use provided pattern
        pattern: Optional[TracePattern] = None
        if self._storage:
            try:
                pattern = self._storage.get_pattern(request.pattern_id)
            except Exception as exc:
                logger.warning(f"Failed to fetch pattern {request.pattern_id}: {exc}")

        if not pattern:
            # Fallback: Create minimal pattern from request (for testing)
            pattern = TracePattern(
                pattern_id=request.pattern_id,
                sequence=["placeholder"],
                frequency=1,
                first_seen=datetime.utcnow().isoformat() + "Z",
                last_seen=datetime.utcnow().isoformat() + "Z",
            )

        # Calculate reusability score using static method
        score = ReusabilityScore.calculate(
            pattern=pattern,
            total_runs=request.total_runs,
            avg_trace_tokens=request.avg_trace_tokens,
            unique_task_types=request.unique_task_types,
            total_task_types=request.total_task_types,
        )

        # TODO: Store score if storage backend available (requires pattern_reusability_scores table)
        # if self._storage:
        #     try:
        #         self._storage.update_pattern_scores(...)
        #     except Exception as exc:
        #         logger.warning(f"Failed to store scores for pattern {pattern.pattern_id}: {exc}")

        response = ScoreReusabilityResponse(
            score=score,
            pattern=pattern,
            meets_threshold=score.meets_approval_threshold,
        )

        # Emit telemetry event
        self._emit_reusability_scoring_telemetry(
            request=request,
            response=response,
            success=True,
            error=None,
        )

        return response

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _fetch_trace_for_run(self, run_id: str) -> Optional[str]:
        """Fetch trace text for a run ID.

        TODO: Replace placeholder with actual RunService integration.

        Args:
            run_id: Run identifier

        Returns:
            Trace text or None if not found
        """
        # Placeholder - will be replaced with RunService.get_run(run_id).trace_text
        logger.debug(f"Fetching trace for run {run_id} (placeholder implementation)")
        return None

    def _extract_sequences_from_steps(
        self, steps: List[TraceStep]
    ) -> List[Tuple[List[str], int, int]]:
        """Extract all possible sequences from trace steps using sliding windows.

        Args:
            steps: Segmented trace steps

        Returns:
            List of (sequence, start_index, end_index) tuples
        """
        sequences: List[Tuple[List[str], int, int]] = []
        normalized_steps = [self._normalize_step(step.text) for step in steps if step.text.strip()]

        # Extract sequences of varying lengths (1-5 steps)
        for window_size in range(1, min(6, len(normalized_steps) + 1)):
            for start_idx in range(len(normalized_steps) - window_size + 1):
                end_idx = start_idx + window_size - 1
                sequence = normalized_steps[start_idx : end_idx + 1]

                # Filter trivial sequences
                if window_size == 1 and len(sequence[0].split()) < 4:
                    continue

                sequences.append((sequence, start_idx, end_idx))

        return sequences

    def _normalize_step(self, text: str) -> str:
        """Normalize a step text for comparison.

        Removes punctuation, lowercases, strips whitespace.

        Args:
            text: Raw step text

        Returns:
            Normalized text
        """
        import re

        # Remove punctuation and extra whitespace
        normalized = re.sub(r"[^\w\s]", "", text.lower())
        normalized = " ".join(normalized.split())
        return normalized.strip()

    def _group_similar_sequences(
        self,
        all_sequences: Dict[str, List[Tuple[List[str], int, int]]],
        min_similarity: float,
        include_context: bool,
    ) -> List[_PatternMatch]:
        """Group similar sequences across runs to detect patterns.

        Args:
            all_sequences: Map of run_id -> sequences
            min_similarity: Minimum similarity threshold (0-1)
            include_context: Whether to track occurrence positions

        Returns:
            List of _PatternMatch objects representing detected patterns
        """
        # Flatten all sequences with run context
        all_with_context: List[Tuple[str, List[str], int, int]] = []  # (run_id, sequence, start, end)
        for run_id, sequences in all_sequences.items():
            for sequence, start_idx, end_idx in sequences:
                all_with_context.append((run_id, sequence, start_idx, end_idx))

        # Group similar sequences
        pattern_groups: List[_PatternMatch] = []
        processed: Set[int] = set()

        for i, (run_id_i, seq_i, start_i, end_i) in enumerate(all_with_context):
            if i in processed:
                continue

            # Start new pattern group
            match = _PatternMatch(
                sequence=seq_i,
                run_ids={run_id_i},
                occurrences=[(run_id_i, start_i, end_i)] if include_context else [],
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
            )
            processed.add(i)

            # Find similar sequences
            for j, (run_id_j, seq_j, start_j, end_j) in enumerate(all_with_context):
                if j in processed or j <= i:
                    continue

                similarity = self._calculate_sequence_similarity(seq_i, seq_j)
                if similarity >= min_similarity:
                    match.run_ids.add(run_id_j)
                    if include_context:
                        match.occurrences.append((run_id_j, start_j, end_j))
                    processed.add(j)

            # Only keep patterns that appear in multiple runs
            if len(match.run_ids) >= 2:
                pattern_groups.append(match)

        return pattern_groups

    def _calculate_sequence_similarity(self, seq1: List[str], seq2: List[str]) -> float:
        """Calculate similarity between two sequences using SequenceMatcher.

        Args:
            seq1: First sequence
            seq2: Second sequence

        Returns:
            Similarity score 0-1 (1 = identical)
        """
        if len(seq1) != len(seq2):
            return 0.0

        # Calculate average similarity across all steps
        total_similarity = 0.0
        for step1, step2 in zip(seq1, seq2):
            step_similarity = SequenceMatcher(None, step1, step2).ratio()
            total_similarity += step_similarity

        return total_similarity / len(seq1) if seq1 else 0.0

    # ------------------------------------------------------------------
    # Telemetry Helpers
    # ------------------------------------------------------------------

    def _emit_pattern_detection_telemetry(
        self,
        *,
        request: DetectPatternsRequest,
        response: Optional[DetectPatternsResponse],
        success: bool,
        error: Optional[str],
    ) -> None:
        """Emit telemetry event for pattern detection.

        Args:
            request: Original detection request
            response: Detection response (if successful)
            success: Whether detection succeeded
            error: Error message (if failed)
        """
        try:
            payload = {
                "run_ids": request.run_ids,
                "run_count": len(request.run_ids),
                "min_frequency": request.min_frequency,
                "min_similarity": request.min_similarity,
                "max_patterns": request.max_patterns,
                "include_context": request.include_context,
                "success": success,
            }

            if response:
                payload.update(
                    {
                        "pattern_count": len(response.patterns),
                        "runs_analyzed": response.runs_analyzed,
                        "total_occurrences": response.total_occurrences,
                        "execution_time_seconds": response.execution_time_seconds,
                        "filtered_count": response.metadata.get("filtered_count", 0),
                    }
                )

            if error:
                payload["error"] = error

            self._telemetry.emit_event(
                event_type="trace_analysis.pattern_detected",
                payload=payload,
            )
        except Exception:  # pragma: no cover - telemetry should not block detection
            logger.debug("Pattern detection telemetry emission failed", exc_info=True)

    def _emit_reusability_scoring_telemetry(
        self,
        *,
        request: ScoreReusabilityRequest,
        response: Optional[ScoreReusabilityResponse],
        success: bool,
        error: Optional[str],
    ) -> None:
        """Emit telemetry event for reusability scoring.

        Args:
            request: Original scoring request
            response: Scoring response (if successful)
            success: Whether scoring succeeded
            error: Error message (if failed)
        """
        try:
            payload = {
                "pattern_id": request.pattern_id,
                "total_runs": request.total_runs,
                "avg_trace_tokens": request.avg_trace_tokens,
                "unique_task_types": request.unique_task_types,
                "total_task_types": request.total_task_types,
                "success": success,
            }

            if response:
                payload.update(
                    {
                        "frequency_score": response.score.frequency_score,
                        "token_savings_score": response.score.token_savings_score,
                        "applicability_score": response.score.applicability_score,
                        "overall_score": response.score.overall_score,
                        "meets_threshold": response.meets_threshold,
                        "pattern_frequency": response.pattern.frequency,
                    }
                )

            if error:
                payload["error"] = error

            self._telemetry.emit_event(
                event_type="trace_analysis.pattern_scored",
                payload=payload,
            )
        except Exception:  # pragma: no cover - telemetry should not block scoring
            logger.debug("Reusability scoring telemetry emission failed", exc_info=True)


__all__ = ["TraceAnalysisService", "_Snippet"]
