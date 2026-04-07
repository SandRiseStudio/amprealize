"""Typed telemetry event payloads for E4 learning-loop, analytics, and governance.

Each payload model maps 1-to-1 to a JSON Schema definition under
``schema/telemetry/v1/`` and a ``TelemetryEventType`` enum member.
Surfaces emit events through :class:`~amprealize.telemetry.TelemetryClient`
with validated payloads:

    client.emit_event(
        event_type=TelemetryEventType.PACK_ACTIVATED,
        payload=PackActivatedPayload(pack_id="pk-1", ...).to_dict(),
    )

Part of E4 — Learning Loop, Analytics, and Governance (AMPREALIZE-278 / T4.1.1).
"""

from __future__ import annotations

import enum
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Event Type Enum
# ---------------------------------------------------------------------------


class TelemetryEventType(str, enum.Enum):
    """Canonical event type identifiers used across all surfaces.

    Legacy events (pre-E4) are included for completeness but not modeled here;
    new code should prefer the typed payloads below.
    """

    # -- Pre-existing domain events --
    BEHAVIOR_RETRIEVED = "behavior_retrieved"
    PLAN_CREATED = "plan_created"
    EXECUTION_UPDATE = "execution_update"
    REFLECTION_SUBMITTED = "reflection_submitted"
    ACTION_RECORDED = "action_recorded"
    COMPLIANCE_STEP_RECORDED = "compliance_step_recorded"

    # -- E4: Knowledge Pack events -------
    PACK_ACTIVATED = "pack.activated"
    PACK_DEACTIVATED = "pack.deactivated"
    PACK_OVERLAY_APPLIED = "pack.overlay_applied"

    # -- E4: BCI events -------
    BCI_RETRIEVAL_COMPLETED = "bci.retrieval_completed"
    BCI_INJECTION_COMPLETED = "bci.injection_completed"
    BCI_CITATION_VALIDATED = "bci.citation_validated"

    # -- E4: Reflection events -------
    REFLECTION_CANDIDATE_EXTRACTED = "reflection.candidate_extracted"
    REFLECTION_CANDIDATE_APPROVED = "reflection.candidate_approved"


# ---------------------------------------------------------------------------
# Pack Event Payloads
# ---------------------------------------------------------------------------


@dataclass
class PackActivatedPayload:
    """Emitted when a knowledge pack is activated for a workspace."""

    pack_id: str
    pack_version: str
    workspace_id: str
    surface: str
    profile: Optional[str] = None
    activated_by: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class PackDeactivatedPayload:
    """Emitted when a knowledge pack is deactivated."""

    pack_id: str
    workspace_id: str
    surface: str
    deactivated_by: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class PackOverlayAppliedPayload:
    """Emitted when an overlay rule matches and is applied during injection."""

    pack_id: str
    overlay_kind: str  # "task", "surface", "role"
    task_family: Optional[str] = None
    surface: Optional[str] = None
    role: Optional[str] = None
    overlay_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


# ---------------------------------------------------------------------------
# BCI Event Payloads
# ---------------------------------------------------------------------------


@dataclass
class BCIRetrievalCompletedPayload:
    """Emitted after behavior retrieval completes in RuntimeInjector."""

    top_k: int
    behaviors_returned: List[str]
    latency_ms: float
    strategy: str
    run_id: Optional[str] = None
    pack_id: Optional[str] = None
    query: Optional[str] = None
    surface: Optional[str] = None
    phase: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class BCIInjectionCompletedPayload:
    """Emitted after full runtime injection completes."""

    behaviors_count: int
    token_estimate: int
    latency_ms: float
    run_id: Optional[str] = None
    pack_id: Optional[str] = None
    phase: Optional[str] = None
    overlays_count: int = 0
    primer_length: Optional[int] = None
    constraint_count: Optional[int] = None
    surface: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class BCICitationValidatedPayload:
    """Emitted after citation validation completes."""

    valid_count: int
    invalid_count: int
    run_id: Optional[str] = None
    cited_behavior_ids: List[str] = field(default_factory=list)
    missing_count: int = 0
    validation_rate: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


# ---------------------------------------------------------------------------
# Reflection Event Payloads
# ---------------------------------------------------------------------------


@dataclass
class ReflectionCandidateExtractedPayload:
    """Emitted when a reflection candidate is extracted from a run trace."""

    candidate_id: str
    confidence: float
    run_id: Optional[str] = None
    candidate_slug: Optional[str] = None
    pattern_type: Optional[str] = None
    quality_scores: Optional[Dict[str, float]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class ReflectionCandidateApprovedPayload:
    """Emitted when a reflection candidate is approved (manually or auto)."""

    candidate_id: str
    behavior_id: Optional[str] = None
    behavior_version: Optional[str] = None
    reviewer_role: Optional[str] = None
    auto_approved: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


# ---------------------------------------------------------------------------
# Convenience mapping for validation
# ---------------------------------------------------------------------------

EVENT_TYPE_PAYLOAD_MAP = {
    TelemetryEventType.PACK_ACTIVATED: PackActivatedPayload,
    TelemetryEventType.PACK_DEACTIVATED: PackDeactivatedPayload,
    TelemetryEventType.PACK_OVERLAY_APPLIED: PackOverlayAppliedPayload,
    TelemetryEventType.BCI_RETRIEVAL_COMPLETED: BCIRetrievalCompletedPayload,
    TelemetryEventType.BCI_INJECTION_COMPLETED: BCIInjectionCompletedPayload,
    TelemetryEventType.BCI_CITATION_VALIDATED: BCICitationValidatedPayload,
    TelemetryEventType.REFLECTION_CANDIDATE_EXTRACTED: ReflectionCandidateExtractedPayload,
    TelemetryEventType.REFLECTION_CANDIDATE_APPROVED: ReflectionCandidateApprovedPayload,
}


__all__ = [
    "TelemetryEventType",
    "PackActivatedPayload",
    "PackDeactivatedPayload",
    "PackOverlayAppliedPayload",
    "BCIRetrievalCompletedPayload",
    "BCIInjectionCompletedPayload",
    "BCICitationValidatedPayload",
    "ReflectionCandidateExtractedPayload",
    "ReflectionCandidateApprovedPayload",
    "EVENT_TYPE_PAYLOAD_MAP",
]
