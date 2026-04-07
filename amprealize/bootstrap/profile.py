"""Workspace profile enum and detection result models.

Defines the set of recognised workspace profiles and the data structures
returned by the workspace detector (architecture doc §6.3, §8.2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class WorkspaceProfile(str, Enum):
    """Recognised workspace profiles for knowledge pack selection.

    Each profile maps to a default pack configuration and determines
    which operational playbooks are enabled (architecture doc §6.3).
    """

    SOLO_DEV = "solo-dev"
    AMPREALIZE_PLATFORM = "amprealize-platform"
    TEAM_COLLAB = "team-collab"
    EXTENSION_DEV = "extension-dev"
    API_BACKEND = "api-backend"
    COMPLIANCE_SENSITIVE = "compliance-sensitive"


@dataclass
class WorkspaceSignal:
    """A single workspace detection signal.

    Attributes:
        signal_name: Machine-readable identifier (e.g. ``agents_md``).
        detected: Whether the signal was found.
        confidence: Strength of the signal (0.0–1.0).
        evidence: Human-readable description of what was found.
    """

    signal_name: str
    detected: bool
    confidence: float = 0.0
    evidence: str = ""


@dataclass
class ProfileDetectionResult:
    """Outcome of workspace profile detection.

    Attributes:
        profile: Best-guess workspace profile.
        confidence: Overall confidence (0.0–1.0).
        signals: Individual detection signals.
        is_ambiguous: True when two or more profiles scored similarly.
        runner_up: Second-best profile, if close in score.
    """

    profile: WorkspaceProfile
    confidence: float
    signals: List[WorkspaceSignal] = field(default_factory=list)
    is_ambiguous: bool = False
    runner_up: Optional[WorkspaceProfile] = None

    def to_dict(self) -> dict:
        """Serialise to JSON-safe dict."""
        return {
            "profile": self.profile.value,
            "confidence": round(self.confidence, 3),
            "signals": [
                {
                    "signal_name": s.signal_name,
                    "detected": s.detected,
                    "confidence": round(s.confidence, 3),
                    "evidence": s.evidence,
                }
                for s in self.signals
            ],
            "is_ambiguous": self.is_ambiguous,
            "runner_up": self.runner_up.value if self.runner_up else None,
        }
