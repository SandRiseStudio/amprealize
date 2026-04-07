"""Caps enforcer — resource limit checking for OSS and Enterprise editions.

In the OSS edition, all capability checks pass unconditionally via the no-op
``CapsEnforcer``.  For Enterprise Starter, ``EditionCapsEnforcer`` checks
resource counts against the limits defined in ``EditionCapabilities``.
Enterprise Premium and OSS are both uncapped.

Usage::

    from amprealize.caps_enforcer import get_caps_enforcer

    enforcer = get_caps_enforcer()
    enforcer.check("projects", current_count=42)  # True in OSS
    enforcer.enforce("projects", current_count=42)  # raises if over cap

Part of Phases 1 & 4 of GUIDEAI-748 (Modular Installation System).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from amprealize.edition import EditionCapabilities


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class CapsExceededError(Exception):
    """Raised when a resource cap would be exceeded."""

    def __init__(self, resource: str, limit: int, current: int) -> None:
        self.resource = resource
        self.limit = limit
        self.current = current
        super().__init__(
            f"Cap exceeded for {resource!r}: current {current} >= limit {limit}"
        )


# ---------------------------------------------------------------------------
# Resource → EditionCapabilities field mapping
# ---------------------------------------------------------------------------

_RESOURCE_TO_CAP_FIELD: dict[str, str] = {
    "projects": "max_projects",
    "boards": "max_boards_per_project",
    "work_items": "max_work_items",
    "agents": "max_agents",
    "behaviors": "max_behaviors",
    "api_calls": "monthly_api_calls",
    "storage": "max_storage_bytes",
    "members": "max_members",
}


# ---------------------------------------------------------------------------
# No-op enforcer (OSS / Enterprise Premium — both uncapped)
# ---------------------------------------------------------------------------


class CapsEnforcer:
    """No-op caps enforcer for OSS edition.

    Every ``check()`` call returns ``True`` — OSS is fully uncapped.
    """

    def check(self, resource: str, *, current_count: int = 0) -> bool:
        """Return ``True`` unconditionally (OSS has no caps)."""
        return True

    def enforce(self, resource: str, *, current_count: int = 0) -> None:
        """No-op — never raises in OSS."""

    def get_limit(self, resource: str) -> int:
        """Return ``-1`` (unlimited) for any resource."""
        return -1

    def get_usage_summary(self) -> dict[str, dict[str, int]]:
        """Return empty usage summary (no caps to report)."""
        return {}


# ---------------------------------------------------------------------------
# Edition-aware enforcer (Enterprise Starter — capped resources)
# ---------------------------------------------------------------------------


class EditionCapsEnforcer(CapsEnforcer):
    """Caps enforcer that checks against ``EditionCapabilities`` limits.

    Enterprise Starter has capped resources.  OSS and Enterprise Premium
    are both unlimited (``-1``), so ``check()`` always returns ``True``
    for those editions.
    """

    def __init__(self, caps: EditionCapabilities | None = None) -> None:
        self._caps = caps

    @property
    def caps(self) -> EditionCapabilities:
        if self._caps is None:
            from amprealize.edition import get_caps

            self._caps = get_caps()
        return self._caps

    def check(self, resource: str, *, current_count: int = 0) -> bool:
        """Return ``True`` if *current_count* is below the cap (or uncapped)."""
        limit = self.get_limit(resource)
        if limit == -1:
            return True
        return current_count < limit

    def enforce(self, resource: str, *, current_count: int = 0) -> None:
        """Raise ``CapsExceededError`` if over cap."""
        if not self.check(resource, current_count=current_count):
            raise CapsExceededError(resource, self.get_limit(resource), current_count)

    def get_limit(self, resource: str) -> int:
        """Return the cap for *resource*, or ``-1`` if uncapped."""
        field_name = _RESOURCE_TO_CAP_FIELD.get(resource)
        if field_name is None:
            return -1
        return getattr(self.caps, field_name, -1)

    def get_usage_summary(self) -> dict[str, dict[str, int]]:
        """Return cap limits for all capped resources."""
        summary: dict[str, dict[str, int]] = {}
        for resource, field_name in _RESOURCE_TO_CAP_FIELD.items():
            limit = getattr(self.caps, field_name, -1)
            if limit != -1:
                summary[resource] = {"limit": limit}
        return summary


# ---------------------------------------------------------------------------
# Factory — tries enterprise first, falls back based on edition
# ---------------------------------------------------------------------------

_enforcer: CapsEnforcer | None = None


def get_caps_enforcer() -> CapsEnforcer:
    """Return the caps enforcer singleton.

    Resolution order:
    1. Real enforcer from ``amprealize_enterprise`` (if installed)
    2. ``EditionCapsEnforcer`` for Enterprise Starter (capped)
    3. No-op ``CapsEnforcer`` for OSS / Enterprise Premium (uncapped)
    """
    global _enforcer
    if _enforcer is not None:
        return _enforcer

    try:
        from amprealize_enterprise.caps_enforcer import (  # type: ignore[import-not-found]
            CapsEnforcer as EnterpriseCapsEnforcer,
        )

        _enforcer = EnterpriseCapsEnforcer()
    except ImportError:
        from amprealize.edition import Edition, detect_edition

        edition = detect_edition()
        if edition == Edition.ENTERPRISE_STARTER:
            _enforcer = EditionCapsEnforcer()
        else:
            _enforcer = CapsEnforcer()

    return _enforcer


def reset_caps_enforcer() -> None:
    """Reset the singleton — for testing only."""
    global _enforcer
    _enforcer = None
