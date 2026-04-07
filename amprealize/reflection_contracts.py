"""Reflection service dataclasses aligned with PRD Component B."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .bci_contracts import SerializableDataclass, TraceFormat


@dataclass
class ReflectionExample(SerializableDataclass):
    """Example snippet supporting a candidate behavior."""

    title: str
    body: str


@dataclass
class ReflectionQualityScores(SerializableDataclass):
    """Quality dimensions extracted during reflection."""

    clarity: float
    generality: float
    reusability: float
    correctness: float

    @staticmethod
    def from_dimension_map(dimensions: Dict[str, float]) -> "ReflectionQualityScores":
        return ReflectionQualityScores(
            clarity=_clamp(dimensions.get("clarity", 0.0)),
            generality=_clamp(dimensions.get("generality", 0.0)),
            reusability=_clamp(dimensions.get("reusability", 0.0)),
            correctness=_clamp(dimensions.get("correctness", 0.0)),
        )


@dataclass
class ReflectionCandidate(SerializableDataclass):
    """Candidate behavior synthesized from a trace."""

    slug: str
    display_name: str
    instruction: str
    summary: Optional[str]
    supporting_steps: List[str]
    examples: List[ReflectionExample]
    quality_scores: ReflectionQualityScores
    confidence: float
    duplicate_behavior_id: Optional[str] = None
    duplicate_behavior_name: Optional[str] = None
    tags: List[str] = field(default_factory=list)


@dataclass
class ReflectRequest(SerializableDataclass):
    """Request payload for the reflection service."""

    trace_text: str
    trace_format: TraceFormat = TraceFormat.CHAIN_OF_THOUGHT
    run_id: Optional[str] = None
    max_candidates: int = 5
    min_quality_score: float = 0.6
    include_examples: bool = True
    preferred_tags: Optional[List[str]] = None


@dataclass
class ReflectResponse(SerializableDataclass):
    """Response payload describing extracted behavior candidates."""

    run_id: Optional[str]
    trace_step_count: int
    candidates: List[ReflectionCandidate]
    summary: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


def _clamp(value: float) -> float:
    if math.isnan(value):
        return 0.0
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return round(value, 3)
