"""BCI SDK dataclasses derived from schema/bci/v1 artifacts.

These dataclasses mirror the JSON schema definitions for Behavior-Conditioned
Inference retrieval, prompting, citation, and trace analysis APIs. They provide
lightweight serialization helpers used across REST, CLI, and MCP adapters.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Type,
    TypeVar,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

T = TypeVar("T", bound="SerializableDataclass")


class SerializableDataclass:
    """Mixin providing dataclass <-> dict conversion with Enum support."""

    def to_dict(self) -> Dict[str, Any]:
        return _serialize_dataclass(self)

    @classmethod
    def from_dict(cls: Type[T], payload: Dict[str, Any]) -> T:
        return _deserialize_dataclass(cls, payload)


def _serialize_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _serialize_dataclass(value)
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize_value(val) for key, val in value.items() if val is not None}
    return value


def _serialize_dataclass(instance: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for field_info in fields(instance):
        value = getattr(instance, field_info.name)
        if value is None:
            continue
        result[field_info.name] = _serialize_value(value)
    return result


def _is_optional(annotation: Any) -> bool:
    origin = get_origin(annotation)
    if origin is Union:
        args = get_args(annotation)
        return len(args) == 2 and type(None) in args
    return False


def _unwrap_optional(annotation: Any) -> Any:
    if get_origin(annotation) is Union:
        return next(arg for arg in get_args(annotation) if arg is not type(None))
    return annotation


def _deserialize_value(annotation: Any, value: Any) -> Any:
    if value is None:
        return None

    if _is_optional(annotation):
        annotation = _unwrap_optional(annotation)

    origin = get_origin(annotation)
    if origin in (list, List):
        (item_type,) = get_args(annotation) or (Any,)
        return [_deserialize_value(item_type, item) for item in value]
    if origin in (dict, Dict):
        key_type, value_type = get_args(annotation) or (str, Any)
        return {
            _deserialize_value(key_type, key): _deserialize_value(value_type, val)
            for key, val in value.items()
        }
    if origin is Union:
        for option in get_args(annotation):
            if option is type(None):
                continue
            try:
                return _deserialize_value(option, value)
            except Exception:  # pragma: no cover - fallback attempts
                continue
        return value

    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return annotation(value)
    if isinstance(annotation, type) and issubclass(annotation, SerializableDataclass):
        return annotation.from_dict(value)
    return value


def _deserialize_dataclass(cls: Type[T], payload: Dict[str, Any]) -> T:
    if not is_dataclass(cls):  # pragma: no cover - defensive guard
        raise TypeError(f"{cls!r} is not a dataclass")
    kwargs: Dict[str, Any] = {}
    type_hints = get_type_hints(cast(Any, cls))
    for field_info in fields(cast(Any, cls)):
        if field_info.name not in payload:
            continue
        field_value = payload[field_info.name]
        annotation = type_hints.get(field_info.name, field_info.type)
        kwargs[field_info.name] = _deserialize_value(annotation, field_value)
    return cls(**kwargs)  # type: ignore[arg-type]


class RetrievalStrategy(str, Enum):
    EMBEDDING = "embedding"
    KEYWORD = "keyword"
    HYBRID = "hybrid"


class RoleFocus(str, Enum):
    STRATEGIST = "STRATEGIST"
    TEACHER = "TEACHER"
    STUDENT = "STUDENT"
    MULTI_ROLE = "MULTI_ROLE"


@dataclass
class BehaviorMatch(SerializableDataclass):
    behavior_id: str
    name: str
    version: str
    instruction: str
    score: float
    description: Optional[str] = None
    role_focus: Optional[RoleFocus] = None
    tags: List[str] = field(default_factory=list)
    strategy_breakdown: Optional[Dict[str, float]] = None
    citation_label: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class RetrieveRequest(SerializableDataclass):
    query: str
    top_k: int = 5
    strategy: RetrievalStrategy = RetrievalStrategy.HYBRID
    role_focus: Optional[RoleFocus] = None
    tags: Optional[List[str]] = None
    include_metadata: bool = False
    embedding_weight: float = 0.7
    keyword_weight: float = 0.3
    trace_context: Optional[Dict[str, Any]] = None
    user_id: Optional[str] = None  # Phase 2: For gradual rollout A/B cohort routing
    namespace: Optional[str] = "core"
    # E3 Runtime Injection — context-aware retrieval signals
    workspace_profile: Optional[str] = None
    active_pack_id: Optional[str] = None
    surface: Optional[str] = None
    task_type: Optional[str] = None
    pack_behavior_refs: Optional[List[str]] = None
    runtime_constraints: Optional[List[str]] = None
    # E3 S3.9 — phase-aware retrieval
    phase: Optional[str] = None


@dataclass
class RetrieveResponse(SerializableDataclass):
    query: str
    results: List[BehaviorMatch]
    strategy_used: RetrievalStrategy = RetrievalStrategy.HYBRID
    latency_ms: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None


class CitationMode(str, Enum):
    EXPLICIT = "explicit"
    IMPLICIT = "implicit"
    INLINE = "inline"


class PromptFormat(str, Enum):
    LIST = "list"
    PROSE = "prose"
    STRUCTURED = "structured"


@dataclass
class BehaviorSnippet(SerializableDataclass):
    behavior_id: str
    name: str
    instruction: str
    version: Optional[str] = None
    role_focus: Optional[RoleFocus] = None
    citation_label: Optional[str] = None
    summary: Optional[str] = None


@dataclass
class ComposePromptRequest(SerializableDataclass):
    query: str
    behaviors: List[BehaviorSnippet]
    citation_mode: CitationMode = CitationMode.EXPLICIT
    format: PromptFormat = PromptFormat.LIST
    citation_instruction: Optional[str] = None
    max_behaviors: Optional[int] = None
    # E3 Runtime Injection — overlay/primer enrichment
    runtime_context: Optional[Dict[str, Any]] = None
    overlay_instructions: Optional[List[str]] = None
    primer_text: Optional[str] = None
    runtime_constraints: Optional[List[str]] = None


@dataclass
class ComposePromptResponse(SerializableDataclass):
    prompt: str
    behaviors: List[BehaviorSnippet]
    metadata: Optional[Dict[str, Any]] = None
    overlays_included: List[str] = field(default_factory=list)


@dataclass
class BatchComposeItem(SerializableDataclass):
    query: str
    behaviors: List[BehaviorSnippet]
    citation_mode: Optional[CitationMode] = None
    format: Optional[PromptFormat] = None


@dataclass
class BatchComposePromptRequest(SerializableDataclass):
    items: List[BatchComposeItem]


@dataclass
class BatchComposeResult(SerializableDataclass):
    query: str
    prompt: str
    behaviors: List[BehaviorSnippet]


@dataclass
class BatchComposePromptResponse(SerializableDataclass):
    items: List[BatchComposeResult]


class CitationType(str, Enum):
    EXPLICIT = "explicit"
    IMPLICIT = "implicit"
    INLINE = "inline"


@dataclass
class Citation(SerializableDataclass):
    text: str
    type: CitationType
    start_index: int
    end_index: int
    behavior_name: Optional[str] = None
    behavior_id: Optional[str] = None
    confidence: Optional[float] = None


@dataclass
class ParseCitationsRequest(SerializableDataclass):
    output_text: str
    patterns: Optional[List[str]] = None


@dataclass
class ParseCitationsResponse(SerializableDataclass):
    citations: List[Citation]
    # E3 Runtime Injection — overlay/role adherence
    overlays_cited: List[str] = field(default_factory=list)
    role_declared: Optional[str] = None


@dataclass
class PrependedBehavior(SerializableDataclass):
    behavior_name: str
    behavior_id: Optional[str] = None
    version: Optional[str] = None


@dataclass
class ValidateCitationsRequest(SerializableDataclass):
    output_text: str
    prepended_behaviors: List[PrependedBehavior]
    minimum_citations: int = 1
    allow_unlisted_behaviors: bool = False


@dataclass
class ValidateCitationsResponse(SerializableDataclass):
    total_citations: int
    valid_citations: List[Citation]
    invalid_citations: List[Citation]
    compliance_rate: float
    is_compliant: bool
    missing_behaviors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    # E3 Runtime Injection — overlay compliance
    overlay_compliance_rate: float = 0.0
    missing_overlays: List[str] = field(default_factory=list)
    role_declared: bool = False


@dataclass
class ComputeTokenSavingsRequest(SerializableDataclass):
    baseline_tokens: int
    bci_tokens: int


@dataclass
class ComputeTokenSavingsResponse(SerializableDataclass):
    token_savings: int
    token_savings_pct: float


class TraceFormat(str, Enum):
    CHAIN_OF_THOUGHT = "chain_of_thought"
    JSON_STEPS = "json_steps"
    PLAN_MARKDOWN = "plan_markdown"

    # Backward-compatible aliases used by older tests/adapters.
    JSON = "json_steps"
    STRUCTURED_JSON = "json_steps"
    STRUCTURED_LOG = "json_steps"
    MARKDOWN = "plan_markdown"

    @classmethod
    def _missing_(cls, value: object) -> "TraceFormat | None":
        if not isinstance(value, str):
            return None
        normalized = value.strip().lower()
        alias_map = {
            "text": cls.CHAIN_OF_THOUGHT,
            "chain_of_thought": cls.CHAIN_OF_THOUGHT,
            "json": cls.JSON_STEPS,
            "json_steps": cls.JSON_STEPS,
            "structured_json": cls.JSON_STEPS,
            "structured_log": cls.JSON_STEPS,
            "markdown": cls.PLAN_MARKDOWN,
            "plan": cls.PLAN_MARKDOWN,
            "plan_markdown": cls.PLAN_MARKDOWN,
        }
        return alias_map.get(normalized)


@dataclass
class TraceStep(SerializableDataclass):
    index: int
    text: str
    role: Optional[str] = None
    timestamp: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class SegmentTraceRequest(SerializableDataclass):
    trace_text: str
    format: TraceFormat = TraceFormat.CHAIN_OF_THOUGHT
    language: Optional[str] = None


@dataclass
class SegmentTraceResponse(SerializableDataclass):
    steps: List[TraceStep]


@dataclass
class TraceInput(SerializableDataclass):
    trace_text: str
    format: Optional[TraceFormat] = None


@dataclass
class DetectPatternsRequest(SerializableDataclass):
    traces: List[TraceInput]
    min_occurrences: int = 2
    window_size: Optional[int] = None


@dataclass
class PatternCandidate(SerializableDataclass):
    name: Optional[str] = None
    instruction: Optional[str] = None
    supporting_traces: List[str] = field(default_factory=list)


@dataclass
class Pattern(SerializableDataclass):
    pattern_id: str
    description: str
    occurrence_count: int
    name: Optional[str] = None
    candidate_behavior: Optional[PatternCandidate] = None


@dataclass
class DetectPatternsResponse(SerializableDataclass):
    patterns: List[Pattern]
    total_traces: int
    latency_ms: Optional[float] = None


class ScoreDimensionName(str, Enum):
    CLARITY = "clarity"
    GENERALITY = "generality"
    REUSABILITY = "reusability"
    CORRECTNESS = "correctness"
    CUSTOM = "custom"


@dataclass
class ScoreDimension(SerializableDataclass):
    name: ScoreDimensionName
    weight: float
    score: float
    rationale: Optional[str] = None


@dataclass
class ScoreReusabilityRequest(SerializableDataclass):
    candidate_behavior: PatternCandidate
    override_weights: Optional[List[ScoreDimension]] = None


@dataclass
class ScoreReusabilityResponse(SerializableDataclass):
    score: float
    dimensions: List[ScoreDimension]


# ===========================================================================
# E3 S3.9 — Phase-Specific Behavior Boosts & Adherence Tracking
# ===========================================================================


# Phase boost configuration: maps GEP phases to tag boosts and query hints.
# Tags matching a phase's boost_tags receive the specified multiplier.
# The query_hint is prepended to the embedding query for better retrieval.
PHASE_BOOST_CONFIG: Dict[str, Dict[str, Any]] = {
    "planning": {
        "boost_tags": ["architecture", "planning", "design", "requirements", "estimation"],
        "boost_factor": 1.5,
        "query_hint": "planning and architecture decisions",
    },
    "clarifying": {
        "boost_tags": ["requirements", "clarification", "scope", "stakeholder", "acceptance"],
        "boost_factor": 1.4,
        "query_hint": "requirements clarification and scope definition",
    },
    "architecting": {
        "boost_tags": ["architecture", "design", "patterns", "contracts", "api"],
        "boost_factor": 1.5,
        "query_hint": "software architecture and design patterns",
    },
    "executing": {
        "boost_tags": ["implementation", "coding", "refactoring", "logging", "security"],
        "boost_factor": 1.3,
        "query_hint": "code implementation best practices",
    },
    "testing": {
        "boost_tags": ["testing", "test", "coverage", "quality", "validation"],
        "boost_factor": 1.5,
        "query_hint": "testing strategy and test patterns",
    },
    "fixing": {
        "boost_tags": ["debugging", "fix", "error", "incident", "root-cause"],
        "boost_factor": 1.4,
        "query_hint": "debugging and fixing issues",
    },
    "verifying": {
        "boost_tags": ["verification", "review", "compliance", "audit", "quality"],
        "boost_factor": 1.4,
        "query_hint": "verification and quality review",
    },
    "completing": {
        "boost_tags": ["documentation", "deployment", "release", "changelog"],
        "boost_factor": 1.3,
        "query_hint": "documentation and release completion",
    },
}


@dataclass
class PhaseAdherenceRecord(SerializableDataclass):
    """Records adherence for a single GEP phase execution."""

    phase: str
    behaviors_injected: List[str] = field(default_factory=list)
    behaviors_cited: List[str] = field(default_factory=list)
    behaviors_missed: List[str] = field(default_factory=list)
    overlays_injected: List[str] = field(default_factory=list)
    overlays_cited: List[str] = field(default_factory=list)
    overlays_missed: List[str] = field(default_factory=list)
    role_declared: bool = False
    adherence_score: float = 0.0
    violation_count: int = 0
    timestamp: Optional[str] = None


@dataclass
class AdherenceResult(SerializableDataclass):
    """Aggregate adherence result across all phases of a run."""

    run_id: str
    phase_records: List[PhaseAdherenceRecord] = field(default_factory=list)
    overall_adherence_score: float = 0.0
    total_behaviors_injected: int = 0
    total_behaviors_cited: int = 0
    total_violations: int = 0
    is_compliant: bool = True


__all__ = [
    "RetrievalStrategy",
    "RoleFocus",
    "BehaviorMatch",
    "RetrieveRequest",
    "RetrieveResponse",
    "CitationMode",
    "PromptFormat",
    "BehaviorSnippet",
    "ComposePromptRequest",
    "ComposePromptResponse",
    "BatchComposeItem",
    "BatchComposePromptRequest",
    "BatchComposeResult",
    "BatchComposePromptResponse",
    "CitationType",
    "Citation",
    "ParseCitationsRequest",
    "ParseCitationsResponse",
    "PrependedBehavior",
    "ValidateCitationsRequest",
    "ValidateCitationsResponse",
    "ComputeTokenSavingsRequest",
    "ComputeTokenSavingsResponse",
    "TraceFormat",
    "TraceStep",
    "SegmentTraceRequest",
    "SegmentTraceResponse",
    "TraceInput",
    "DetectPatternsRequest",
    "PatternCandidate",
    "Pattern",
    "DetectPatternsResponse",
    "ScoreDimensionName",
    "ScoreDimension",
    "ScoreReusabilityRequest",
    "ScoreReusabilityResponse",
    "PHASE_BOOST_CONFIG",
    "PhaseAdherenceRecord",
    "AdherenceResult",
]
