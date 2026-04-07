"""Data contracts for TraceAnalysisService - automated behavior extraction from execution traces.

Implements PRD Component B (TraceAnalysisService) requirements:
- parse_cot_trace: Segment reasoning into discrete steps
- detect_patterns: Identify repeated sub-procedures across multiple traces
- score_reusability: Calculate frequency, token savings potential, cross-task applicability

Per PRD success metrics:
- Extract ≥5 high-quality behaviors per 100 runs (0.05 extraction rate)
- 80% approval rate for auto-extracted candidates
- Reduce duplicate manual submissions by 50%
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from .bci_contracts import SerializableDataclass


class ExtractionJobStatus(str, Enum):
    """Status of an extraction job lifecycle."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


@dataclass
class TracePattern(SerializableDataclass):
    """Recurring reasoning pattern detected across multiple traces.

    Attributes:
        pattern_id: Unique identifier (UUID)
        sequence: Ordered list of reasoning steps (normalized text)
        frequency: Number of times this pattern occurred across runs
        first_seen: ISO timestamp of first occurrence
        last_seen: ISO timestamp of most recent occurrence
        extracted_from_runs: List of run_ids where this pattern was detected
        metadata: Additional context (task types, domains, avg tokens)
    """

    pattern_id: str
    sequence: List[str]
    frequency: int
    first_seen: str
    last_seen: str
    extracted_from_runs: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def sequence_length(self) -> int:
        """Number of steps in the pattern sequence."""
        return len(self.sequence)

    @property
    def avg_tokens_per_step(self) -> float:
        """Average token count per step in the pattern."""
        if not self.sequence:
            return 0.0
        total_tokens = sum(len(step.split()) * 1.3 for step in self.sequence)  # ~1.3 tokens per word
        return round(total_tokens / len(self.sequence), 2)


@dataclass
class PatternOccurrence(SerializableDataclass):
    """Single occurrence of a pattern in a specific run.

    Attributes:
        occurrence_id: Unique identifier (UUID)
        pattern_id: Reference to parent TracePattern
        run_id: Run where this occurrence was found
        occurrence_time: ISO timestamp when run was executed
        start_step_index: Starting position in the trace (0-indexed)
        end_step_index: Ending position in the trace (inclusive)
        context_before: Steps immediately before the pattern (for disambiguation)
        context_after: Steps immediately after the pattern
        token_count: Estimated tokens in this occurrence
    """

    occurrence_id: str
    pattern_id: str
    run_id: str
    occurrence_time: str
    start_step_index: int
    end_step_index: int
    context_before: List[str] = field(default_factory=list)
    context_after: List[str] = field(default_factory=list)
    token_count: int = 0

    @property
    def step_span(self) -> int:
        """Number of steps covered by this occurrence."""
        return self.end_step_index - self.start_step_index + 1


@dataclass
class ReusabilityScore(SerializableDataclass):
    """Quality scores for a detected pattern's reusability potential.

    Implements PRD score_reusability() requirements:
    - frequency_score: How often pattern recurs (0-1)
    - token_savings_score: Potential reduction in reasoning tokens (0-1)
    - applicability_score: Cross-task/domain applicability (0-1)
    - overall_score: Weighted average for approval threshold (> 0.7)

    Attributes:
        pattern_id: Reference to scored pattern
        frequency_score: pattern.frequency / total_runs (0-1)
        token_savings_score: estimated_tokens_saved / avg_trace_tokens (0-1)
        applicability_score: unique_task_types / total_task_types (0-1)
        overall_score: Weighted average (0.4*freq + 0.3*savings + 0.3*applicability)
        calculated_at: ISO timestamp when scores were computed
        metadata: Breakdown details (total_runs, unique_tasks, avg_trace_tokens)
    """

    pattern_id: str
    frequency_score: float
    token_savings_score: float
    applicability_score: float
    overall_score: float
    calculated_at: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def calculate(
        pattern: TracePattern,
        total_runs: int,
        avg_trace_tokens: float,
        unique_task_types: int,
        total_task_types: int,
    ) -> "ReusabilityScore":
        """Calculate reusability score from pattern metrics.

        Args:
            pattern: Pattern to score
            total_runs: Total number of runs analyzed in the period
            avg_trace_tokens: Average tokens per trace in corpus
            unique_task_types: Number of distinct task types where pattern occurred
            total_task_types: Total number of task types in corpus

        Returns:
            ReusabilityScore with weighted overall_score
        """
        frequency_score = min(pattern.frequency / max(total_runs, 1), 1.0)

        # Token savings = tokens saved per reuse * frequency
        pattern_tokens = pattern.avg_tokens_per_step * pattern.sequence_length
        potential_savings = pattern_tokens * pattern.frequency
        token_savings_score = min(potential_savings / max(avg_trace_tokens * total_runs, 1), 1.0)

        applicability_score = min(unique_task_types / max(total_task_types, 1), 1.0)

        # Weighted average: frequency 40%, savings 30%, applicability 30%
        overall_score = (
            0.4 * frequency_score + 0.3 * token_savings_score + 0.3 * applicability_score
        )

        return ReusabilityScore(
            pattern_id=pattern.pattern_id,
            frequency_score=round(frequency_score, 3),
            token_savings_score=round(token_savings_score, 3),
            applicability_score=round(applicability_score, 3),
            overall_score=round(overall_score, 3),
            calculated_at=datetime.utcnow().isoformat() + "Z",
            metadata={
                "total_runs": total_runs,
                "pattern_frequency": pattern.frequency,
                "pattern_tokens": pattern_tokens,
                "potential_savings": potential_savings,
                "unique_task_types": unique_task_types,
                "total_task_types": total_task_types,
            },
        )

    @property
    def meets_approval_threshold(self) -> bool:
        """Whether overall_score exceeds PRD threshold (0.7) for candidate generation."""
        return self.overall_score > 0.7


@dataclass
class ExtractionJob(SerializableDataclass):
    """Batch extraction job tracking pattern detection across multiple runs.

    Attributes:
        job_id: Unique identifier (UUID)
        status: Current job status (PENDING/RUNNING/COMPLETE/FAILED)
        start_time: ISO timestamp when job started
        end_time: ISO timestamp when job finished (None if still running)
        runs_analyzed: Number of runs processed
        patterns_found: Number of unique patterns detected
        candidates_generated: Number of ReflectionCandidates submitted for approval
        error_message: Error details if status=FAILED
        metadata: Additional context (date_range, filters, config)
    """

    job_id: str
    status: ExtractionJobStatus
    start_time: str
    end_time: Optional[str] = None
    runs_analyzed: int = 0
    patterns_found: int = 0
    candidates_generated: int = 0
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> Optional[float]:
        """Job execution duration in seconds (None if not finished)."""
        if not self.end_time:
            return None
        start = datetime.fromisoformat(self.start_time.replace("Z", "+00:00"))
        end = datetime.fromisoformat(self.end_time.replace("Z", "+00:00"))
        return (end - start).total_seconds()

    @property
    def extraction_rate(self) -> float:
        """Candidates per 100 runs (PRD target: 5 per 100 = 0.05)."""
        if self.runs_analyzed == 0:
            return 0.0
        return round(self.candidates_generated / self.runs_analyzed, 4)


@dataclass
class DetectPatternsRequest(SerializableDataclass):
    """Request to detect patterns across multiple runs.

    Attributes:
        run_ids: List of run IDs to analyze
        min_frequency: Minimum occurrences to consider a pattern (default: 3)
        min_similarity: Minimum sequence similarity threshold 0-1 (default: 0.7)
        max_patterns: Maximum number of patterns to return (default: 100)
        include_context: Whether to capture before/after steps for each occurrence
    """

    run_ids: List[str]
    min_frequency: int = 3
    min_similarity: float = 0.7
    max_patterns: int = 100
    include_context: bool = True


@dataclass
class DetectPatternsResponse(SerializableDataclass):
    """Response from pattern detection operation.

    Attributes:
        patterns: List of detected patterns ordered by frequency (descending)
        runs_analyzed: Number of runs successfully processed
        total_occurrences: Total pattern occurrences across all runs
        execution_time_seconds: Time taken to detect patterns
        metadata: Additional stats (avg_pattern_length, unique_sequences)
    """

    patterns: List[TracePattern]
    runs_analyzed: int
    total_occurrences: int
    execution_time_seconds: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ScoreReusabilityRequest(SerializableDataclass):
    """Request to score a pattern's reusability.

    Attributes:
        pattern_id: Pattern to score
        total_runs: Total runs in analysis period (for frequency normalization)
        avg_trace_tokens: Average tokens per trace (for savings calculation)
        unique_task_types: Number of distinct task types where pattern occurred
        total_task_types: Total task types in corpus (for applicability score)
    """

    pattern_id: str
    total_runs: int
    avg_trace_tokens: float
    unique_task_types: int
    total_task_types: int


@dataclass
class ScoreReusabilityResponse(SerializableDataclass):
    """Response from reusability scoring operation.

    Attributes:
        score: Calculated ReusabilityScore
        pattern: Reference pattern (for convenience)
        meets_threshold: Whether score > 0.7 (approval threshold)
    """

    score: ReusabilityScore
    pattern: TracePattern
    meets_threshold: bool
