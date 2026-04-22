"""Feature Flag Service — T4.4.1: Phased rollout feature flags.

Provides a formal FeatureFlagService replacing ad-hoc env-var checks with
a central registry supporting boolean, percentage (consistent-hashing),
and user-list flag types.

Flags can be evaluated with optional context (user_id, org_id) for percentage
rollout and user-list targeting.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Flag type enum
# ---------------------------------------------------------------------------

class FlagType(str, Enum):
    """Supported feature flag types."""

    BOOLEAN = "boolean"
    PERCENTAGE = "percentage"
    USER_LIST = "user_list"


# ---------------------------------------------------------------------------
# Flag definition
# ---------------------------------------------------------------------------

@dataclass
class FeatureFlag:
    """A single feature flag definition.

    Attributes:
        name: Dotted flag name (e.g. ``feature.auto_reflection``).
        flag_type: How the flag is evaluated.
        enabled: Master on/off for boolean flags.
        percentage: Rollout percentage (0-100) for percentage flags.
        user_list: Allowlisted user IDs for user_list flags.
        description: Human-readable description.
        metadata: Arbitrary key-value metadata.
    """

    name: str
    flag_type: FlagType = FlagType.BOOLEAN
    enabled: bool = False
    percentage: int = 0
    user_list: List[str] = field(default_factory=list)
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    # -- serialisation helpers -----------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "flag_type": self.flag_type.value,
            "enabled": self.enabled,
            "percentage": self.percentage,
            "user_list": list(self.user_list),
            "description": self.description,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FeatureFlag":
        return cls(
            name=data["name"],
            flag_type=FlagType(data.get("flag_type", "boolean")),
            enabled=data.get("enabled", False),
            percentage=data.get("percentage", 0),
            user_list=data.get("user_list", []),
            description=data.get("description", ""),
            metadata=data.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# Consistent-hashing helper (percentage rollout)
# ---------------------------------------------------------------------------

def _hash_bucket(flag_name: str, user_id: str) -> int:
    """Return a deterministic bucket 0-99 for a (flag, user) pair."""
    digest = hashlib.sha256(f"{flag_name}:{user_id}".encode()).hexdigest()
    return int(digest[:8], 16) % 100


# ---------------------------------------------------------------------------
# Default flag catalogue
# ---------------------------------------------------------------------------

# Existing env-var flags migrated to formal definitions.
_MIGRATED_FLAGS: List[FeatureFlag] = [
    FeatureFlag(
        name="feature.early_knowledge_alignment",
        flag_type=FlagType.BOOLEAN,
        enabled=os.getenv("AMPREALIZE_ENABLE_EARLY_RETRIEVAL", "true").lower() == "true",
        description="Enable Early Knowledge Alignment (EKA) retrieval before planning phase",
        metadata={"legacy_env": "AMPREALIZE_ENABLE_EARLY_RETRIEVAL"},
    ),
    FeatureFlag(
        name="feature.embedding_v2_rollout",
        flag_type=FlagType.PERCENTAGE,
        enabled=True,
        percentage=int(os.getenv("EMBEDDING_ROLLOUT_PERCENTAGE", "100")),
        description="Percentage rollout of v2 embedding model",
        metadata={"legacy_env": "EMBEDDING_ROLLOUT_PERCENTAGE"},
    ),
    FeatureFlag(
        name="feature.device_flow_auth",
        flag_type=FlagType.BOOLEAN,
        enabled=os.getenv("FEATURE_DEVICE_FLOW_AUTH", "true").lower() == "true",
        description="Enable device-flow authentication",
        metadata={"legacy_env": "FEATURE_DEVICE_FLOW_AUTH"},
    ),
]

# New E4 flags.
_E4_FLAGS: List[FeatureFlag] = [
    FeatureFlag(
        name="feature.auto_reflection",
        flag_type=FlagType.BOOLEAN,
        enabled=os.getenv("AMPREALIZE_ENABLE_AUTO_REFLECTION", "false").lower() == "true",
        description="Post-run auto-reflection to extract candidate behaviors",
        metadata={"epic": "E4", "story": "S4.2"},
    ),
    FeatureFlag(
        name="feature.wiki_reflection",
        flag_type=FlagType.BOOLEAN,
        enabled=os.getenv("AMPREALIZE_ENABLE_WIKI_REFLECTION", "false").lower() == "true",
        description="Post-run wiki reflection nudge to update AI Learning Wiki",
        metadata={"epic": "E4", "story": "S4.2"},
    ),
    FeatureFlag(
        name="feature.pack_generation",
        flag_type=FlagType.BOOLEAN,
        enabled=False,
        description="Enable knowledge-pack generation pipeline",
        metadata={"epic": "E4", "story": "S4.3"},
    ),
    FeatureFlag(
        name="feature.adaptive_bootstrap",
        flag_type=FlagType.BOOLEAN,
        enabled=False,
        description="Enable runtime adaptive bootstrap with knowledge packs",
        metadata={"epic": "E4", "story": "S4.3"},
    ),
    FeatureFlag(
        name="feature.quality_gates",
        flag_type=FlagType.BOOLEAN,
        enabled=False,
        description="Enable CI quality-gate regression blocking",
        metadata={"epic": "E4", "story": "S4.3"},
    ),
]

# Whiteboard flags.
_WHITEBOARD_FLAGS: List[FeatureFlag] = [
    FeatureFlag(
        name="feature.whiteboard",
        flag_type=FlagType.BOOLEAN,
        enabled=os.getenv("AMPREALIZE_ENABLE_WHITEBOARD", "false").lower() == "true",
        description="Enable collaborative brainstorm whiteboard canvas",
        metadata={"work_item": "GUIDEAI-971"},
    ),
]

DEFAULT_FLAGS: List[FeatureFlag] = _MIGRATED_FLAGS + _E4_FLAGS + _WHITEBOARD_FLAGS


# ---------------------------------------------------------------------------
# FeatureFlagService
# ---------------------------------------------------------------------------

class FeatureFlagService:
    """Central feature-flag registry with evaluation logic.

    Supports boolean, percentage (consistent-hash), and user-list
    flag types.  Flag state is held in-memory with optional persistence
    hooks (Postgres / settings service).
    """

    def __init__(
        self,
        flags: Optional[List[FeatureFlag]] = None,
        settings_service: Optional[Any] = None,
    ) -> None:
        self._flags: Dict[str, FeatureFlag] = {}
        self._settings_service = settings_service

        for f in (flags if flags is not None else DEFAULT_FLAGS):
            self._flags[f.name] = f

    # -- query API -----------------------------------------------------------

    def is_enabled(
        self,
        flag_name: str,
        context: Optional[Dict[str, str]] = None,
    ) -> bool:
        """Evaluate whether *flag_name* is active for the given context.

        For ``BOOLEAN`` flags, returns ``flag.enabled``.
        For ``PERCENTAGE`` flags, hashes ``flag_name + user_id`` into a 0-99
        bucket and compares against the rollout percentage.
        For ``USER_LIST`` flags, checks if ``user_id`` is in the allowlist.

        Returns ``False`` for unknown flags (fail-closed).
        """
        flag = self._flags.get(flag_name)
        if flag is None:
            return False

        ctx = context or {}

        if flag.flag_type == FlagType.BOOLEAN:
            from amprealize.feature_flag_runtime import get_boolean_override

            ov = get_boolean_override(flag_name)
            if ov is not None:
                return ov
            return flag.enabled

        if flag.flag_type == FlagType.PERCENTAGE:
            if not flag.enabled:
                return False
            user_id = ctx.get("user_id", "")
            if not user_id:
                # No user context → fall back to enabled check at 100%
                return flag.percentage >= 100
            return _hash_bucket(flag_name, user_id) < flag.percentage

        if flag.flag_type == FlagType.USER_LIST:
            if not flag.enabled:
                return False
            return ctx.get("user_id", "") in flag.user_list

        return False  # pragma: no cover — defensive

    def list_flags(self) -> List[FeatureFlag]:
        """Return all registered flags sorted by name."""
        return sorted(self._flags.values(), key=lambda f: f.name)

    def get_flag(self, flag_name: str) -> Optional[FeatureFlag]:
        """Return a single flag or ``None``."""
        return self._flags.get(flag_name)

    def set_flag(
        self,
        flag_name: str,
        *,
        enabled: Optional[bool] = None,
        percentage: Optional[int] = None,
        user_list: Optional[List[str]] = None,
    ) -> FeatureFlag:
        """Update a flag's state.  Creates the flag if it does not exist.

        Only the provided keyword arguments are mutated; others are
        left unchanged.

        Returns the updated flag.
        """
        flag = self._flags.get(flag_name)
        if flag is None:
            flag = FeatureFlag(name=flag_name)
            self._flags[flag_name] = flag

        if enabled is not None:
            flag.enabled = enabled
        if percentage is not None:
            flag.percentage = max(0, min(100, percentage))
            if flag.flag_type == FlagType.BOOLEAN:
                flag.flag_type = FlagType.PERCENTAGE
        if user_list is not None:
            flag.user_list = list(user_list)
            if flag.flag_type == FlagType.BOOLEAN:
                flag.flag_type = FlagType.USER_LIST

        return flag

    def register_flag(self, flag: FeatureFlag) -> None:
        """Register (or replace) a flag definition."""
        self._flags[flag.name] = flag
