"""Reflection pipeline implementing PRD Component B (automated behavior extraction)."""

from __future__ import annotations

import logging
from difflib import SequenceMatcher
from time import perf_counter
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .bci_contracts import (
    PatternCandidate,
    ScoreReusabilityRequest,
    ScoreReusabilityResponse,
    TraceStep,
)
from .bci_service import BCIService
from .behavior_service import BehaviorSearchResult, BehaviorService, SearchBehaviorsRequest
from .reflection_contracts import (
    ReflectRequest,
    ReflectResponse,
    ReflectionCandidate,
    ReflectionExample,
    ReflectionQualityScores,
)
from .telemetry import TelemetryClient
from .trace_analysis_service import TraceAnalysisService, _Snippet

logger = logging.getLogger(__name__)


def _normalize_sentence(text: str) -> str:
    sentence = text.strip()
    if not sentence:
        return sentence
    if sentence[-1] not in {".", "!", "?"}:
        sentence = f"{sentence}."
    return sentence


def _slugify(display_name: str) -> str:
    import re

    tokens = re.findall(r"[a-zA-Z0-9]+", display_name.lower())
    if not tokens:
        return "behavior_candidate"
    core = "_".join(tokens[:6])
    if not core.startswith("behavior_"):
        core = f"behavior_{core}"
    return core[:80]


def _title_case(snippet: str) -> str:
    return " ".join(part.capitalize() for part in snippet.split())


def _sequence_similarity(lhs: str, rhs: str) -> float:
    return SequenceMatcher(None, lhs.lower(), rhs.lower()).ratio()


class ReflectionService:
    """Analyzes traces and proposes reusable behavior candidates."""

    def __init__(
        self,
        *,
        behavior_service: Optional[BehaviorService] = None,
        bci_service: Optional[BCIService] = None,
        telemetry: Optional[TelemetryClient] = None,
        window_sizes: Sequence[int] = (1, 2),
    ) -> None:
        self._behavior_service = behavior_service
        self._bci_service = bci_service or BCIService(behavior_service=behavior_service)
        self._analysis = TraceAnalysisService(bci_service=self._bci_service)
        self._telemetry = telemetry or TelemetryClient.noop()
        self._window_sizes = tuple(window_sizes) or (1, 2)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def reflect(self, request: ReflectRequest) -> ReflectResponse:
        start = perf_counter()
        steps = self._analysis.segment(trace_text=request.trace_text, trace_format=request.trace_format)
        snippets = list(self._analysis.iter_snippets(steps, self._window_sizes))

        seen_slugs: Dict[str, ReflectionCandidate] = {}
        candidates: List[ReflectionCandidate] = []

        for snippet in snippets:
            candidate = self._build_candidate(snippet, request)
            if candidate is None:
                continue
            if candidate.slug in seen_slugs:
                # Boost confidence if duplicate snippet surfaces again
                existing = seen_slugs[candidate.slug]
                boosted = min(1.0, existing.confidence + (candidate.confidence * 0.1))
                seen_slugs[candidate.slug] = ReflectionCandidate(
                    slug=existing.slug,
                    display_name=existing.display_name,
                    instruction=existing.instruction,
                    summary=existing.summary,
                    supporting_steps=list({*existing.supporting_steps, *candidate.supporting_steps}),
                    examples=existing.examples or candidate.examples,
                    quality_scores=existing.quality_scores,
                    confidence=boosted,
                    duplicate_behavior_id=existing.duplicate_behavior_id or candidate.duplicate_behavior_id,
                    duplicate_behavior_name=existing.duplicate_behavior_name or candidate.duplicate_behavior_name,
                    tags=list({*existing.tags, *candidate.tags}),
                )
                continue
            seen_slugs[candidate.slug] = candidate
            candidates.append(candidate)

        candidates.sort(key=lambda item: item.confidence, reverse=True)
        limited = candidates[: request.max_candidates]

        elapsed_ms = round((perf_counter() - start) * 1000.0, 3)
        metadata = {
            "elapsed_ms": elapsed_ms,
            "window_sizes": list(self._window_sizes),
            "scanned_snippet_count": len(snippets),
            "total_candidates": len(candidates),
            "min_quality_score": request.min_quality_score,
        }
        summary = self._build_summary(limited, len(steps))

        response = ReflectResponse(
            run_id=request.run_id,
            trace_step_count=len(steps),
            candidates=limited,
            summary=summary,
            metadata=metadata,
        )
        self._emit_telemetry(response, metadata)
        return response

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _build_candidate(self, snippet: _Snippet, request: ReflectRequest) -> Optional[ReflectionCandidate]:
        display_name = _title_case(snippet.text[:80])
        slug = _slugify(display_name)

        pattern = PatternCandidate(
            name=display_name,
            instruction=_normalize_sentence(snippet.text),
            supporting_traces=[step.text for step in snippet.steps],
        )
        try:
            score_response = self._bci_service.score_reusability(
                ScoreReusabilityRequest(candidate_behavior=pattern)
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning("Failed to score candidate '%s': %s", display_name, exc)
            return None

        confidence = self._calculate_confidence(score_response)
        if confidence < request.min_quality_score:
            return None

        quality_scores = ReflectionQualityScores.from_dimension_map(
            {dimension.name.value: dimension.score for dimension in score_response.dimensions}
        )

        duplicate_behavior_id: Optional[str]
        duplicate_behavior_name: Optional[str]
        duplicate_behavior_id, duplicate_behavior_name = self._find_duplicate_behavior(
            display_name, pattern.instruction or ""
        )

        examples: List[ReflectionExample] = []
        if request.include_examples:
            examples = [
                ReflectionExample(title=f"Step {step.index + 1}", body=step.text.strip())
                for step in snippet.steps
            ]

        tags = self._derive_tags(snippet, request)

        return ReflectionCandidate(
            slug=slug,
            display_name=display_name,
            instruction=pattern.instruction or _normalize_sentence(snippet.text),
            summary=self._summarize_steps(snippet.steps),
            supporting_steps=[step.text for step in snippet.steps],
            examples=examples,
            quality_scores=quality_scores,
            confidence=round(confidence, 3),
            duplicate_behavior_id=duplicate_behavior_id,
            duplicate_behavior_name=duplicate_behavior_name,
            tags=tags,
        )

    def _calculate_confidence(self, score: ScoreReusabilityResponse) -> float:
        base = score.score / 100.0
        clarity = next((dim.score for dim in score.dimensions if dim.name.value == "clarity"), base)
        reusability = next((dim.score for dim in score.dimensions if dim.name.value == "reusability"), base)
        blended = (base * 0.6) + (clarity * 0.2) + (reusability * 0.2)
        return max(0.0, min(1.0, blended))

    def _summarize_steps(self, steps: Sequence[TraceStep]) -> str:
        if not steps:
            return ""
        if len(steps) == 1:
            return steps[0].text.strip()
        first = steps[0].text.strip()
        last = steps[-1].text.strip()
        if first == last:
            return first
        return f"{first} … {last}"

    def _derive_tags(self, snippet: _Snippet, request: ReflectRequest) -> List[str]:
        if request.preferred_tags:
            return list(dict.fromkeys(request.preferred_tags))
        words = [word.lower() for word in snippet.text.split() if word.isalpha()]
        unique: List[str] = []
        for word in words:
            if len(word) <= 3:
                continue
            if word in unique:
                continue
            unique.append(word)
            if len(unique) == 4:
                break
        if not unique:
            unique = [snippet.text.split()[0].lower()]
        return unique

    def _find_duplicate_behavior(self, name: str, instruction: str) -> Tuple[Optional[str], Optional[str]]:
        if not self._behavior_service:
            return (None, None)
        try:
            results = self._behavior_service.search_behaviors(
                SearchBehaviorsRequest(query=name, status="APPROVED", limit=5)
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.debug("Behavior search failed during reflection duplicate detection: %s", exc)
            return (None, None)

        for result in results:
            duplicate = self._evaluate_duplicate_match(result, name, instruction)
            if duplicate is not None:
                return duplicate
        return (None, None)

    def _evaluate_duplicate_match(
        self,
        result: BehaviorSearchResult,
        name: str,
        instruction: str,
    ) -> Optional[Tuple[str, str]]:
        similarity = _sequence_similarity(result.behavior.name, name)
        instruction_similarity = _sequence_similarity(result.active_version.instruction, instruction)
        score = max(result.score, 0.0)
        if similarity >= 0.8 or instruction_similarity >= 0.8 or score >= 0.9:
            return (result.behavior.behavior_id, result.behavior.name)
        return None

    def _build_summary(self, candidates: Sequence[ReflectionCandidate], step_count: int) -> str:
        if not candidates:
            return f"Analyzed {step_count} trace steps; no high-quality behavior candidates detected yet."
        top = candidates[0]
        return (
            f"Analyzed {step_count} trace steps and synthesized {len(candidates)} candidate "
            f"behaviors. Highest confidence: {top.display_name} ({top.confidence:.2f})."
        )

    def _emit_telemetry(self, response: ReflectResponse, metadata: Dict[str, Any]) -> None:
        from .telemetry_events import TelemetryEventType

        try:
            self._telemetry.emit_event(
                event_type=TelemetryEventType.BCI_REFLECTION_GENERATED.value
                if hasattr(TelemetryEventType, "BCI_REFLECTION_GENERATED")
                else "bci.reflection.generated",
                payload={
                    "run_id": response.run_id,
                    "candidate_count": len(response.candidates),
                    "elapsed_ms": metadata.get("elapsed_ms"),
                    "trace_step_count": response.trace_step_count,
                    "window_sizes": metadata.get("window_sizes"),
                    "top_confidence": response.candidates[0].confidence if response.candidates else 0.0,
                },
            )
        except Exception:  # pragma: no cover - telemetry should not block reflection
            logger.debug("Reflection telemetry emission failed", exc_info=True)


__all__ = ["ReflectionService"]
