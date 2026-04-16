"""Edition resolver — detect OSS vs Enterprise and surface capabilities.

In the OSS build, ``detect_edition()`` always returns ``Edition.OSS``.
The Enterprise fork overrides this file to wire tier resolution.

The Edition enum and capability definitions are kept here so that
UI/docs/migration tooling can reference all tiers without importing
enterprise code.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import wraps
from typing import TYPE_CHECKING, Any, Callable, TypeVar

if TYPE_CHECKING:
    from amprealize.config.schema import ModulesConfig

F = TypeVar("F", bound=Callable[..., Any])


# ---------------------------------------------------------------------------
# Edition enum
# ---------------------------------------------------------------------------


class Edition(str, Enum):
    """Which edition is running — determined by installed packages."""

    OSS = "oss"
    ENTERPRISE_STARTER = "enterprise_starter"
    ENTERPRISE_PREMIUM = "enterprise_premium"


# ---------------------------------------------------------------------------
# Capabilities dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EditionCapabilities:
    """What features are available at the current edition."""

    edition: Edition
    orgs: bool = False
    billing: bool = False
    sso: bool = False
    analytics: bool = False
    audit_logs: bool = False
    audit_signing: bool = False
    custom_branding: bool = False
    priority_support: bool = False
    conversations: bool = False
    collaboration: bool = False
    self_improving: bool = False

    # Caps (OSS = uncapped, Enterprise Starter = capped)
    max_projects: int = -1  # -1 = unlimited
    max_boards_per_project: int = -1
    max_work_items: int = -1
    max_agents: int = -1
    max_behaviors: int = -1
    monthly_api_calls: int = -1
    max_storage_bytes: int = -1
    max_members: int = -1


# ---------------------------------------------------------------------------
# Pre-built capability sets
# ---------------------------------------------------------------------------

_OSS_CAPS = EditionCapabilities(edition=Edition.OSS)

_ENTERPRISE_STARTER_CAPS = EditionCapabilities(
    edition=Edition.ENTERPRISE_STARTER,
    orgs=True,
    billing=True,
    audit_logs=True,
    analytics=True,
    conversations=True,
    collaboration=True,
    # Starter caps
    max_projects=10,
    max_boards_per_project=5,
    max_work_items=2_000,
    max_agents=3,
    max_behaviors=100,
    monthly_api_calls=50_000,
    max_storage_bytes=10 * 1024 * 1024 * 1024,  # 10 GB
    max_members=15,
)

_ENTERPRISE_PREMIUM_CAPS = EditionCapabilities(
    edition=Edition.ENTERPRISE_PREMIUM,
    orgs=True,
    billing=True,
    sso=True,
    analytics=True,
    audit_logs=True,
    audit_signing=True,
    custom_branding=True,
    priority_support=True,
    conversations=True,
    collaboration=True,
    self_improving=True,
    # Premium = uncapped
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_edition() -> Edition:
    """Detect which edition is running.

    Always returns :attr:`Edition.OSS` in the open-source build.
    The enterprise fork overrides this module to resolve Starter/Premium.
    """
    return Edition.OSS


def get_caps(edition: Edition | None = None) -> EditionCapabilities:
    """Return capability set for the given (or detected) edition."""
    if edition is None:
        edition = detect_edition()

    if edition == Edition.ENTERPRISE_PREMIUM:
        return _ENTERPRISE_PREMIUM_CAPS
    if edition == Edition.ENTERPRISE_STARTER:
        return _ENTERPRISE_STARTER_CAPS
    return _OSS_CAPS


# ---------------------------------------------------------------------------
# Edition comparison helpers
# ---------------------------------------------------------------------------

_EDITION_RANK: dict[Edition, int] = {
    Edition.OSS: 0,
    Edition.ENTERPRISE_STARTER: 1,
    Edition.ENTERPRISE_PREMIUM: 2,
}


def edition_rank(edition: Edition) -> int:
    """Return numeric rank for edition comparison."""
    return _EDITION_RANK.get(edition, 0)


def edition_at_least(minimum: Edition, *, current: Edition | None = None) -> bool:
    """Check if *current* (or detected) edition meets or exceeds *minimum*."""
    if current is None:
        current = detect_edition()
    return edition_rank(current) >= edition_rank(minimum)


# ---------------------------------------------------------------------------
# Edition gating exceptions & decorators
# ---------------------------------------------------------------------------


class EditionGateError(Exception):
    """Raised when a feature requires a higher edition tier."""

    def __init__(
        self, required: Edition, current: Edition, feature: str = ""
    ) -> None:
        self.required = required
        self.current = current
        self.feature = feature
        super().__init__(
            f"Feature {feature!r} requires {required.value}, "
            f"current edition is {current.value}"
        )


def requires_edition(minimum: Edition, feature: str = "") -> Callable[[F], F]:
    """Decorator that gates a function behind a minimum edition tier."""

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            current = detect_edition()
            if edition_rank(current) < edition_rank(minimum):
                raise EditionGateError(minimum, current, feature or func.__name__)
            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def requires_capability(cap_name: str) -> Callable[[F], F]:
    """Decorator that gates a function behind a capability flag on the current edition."""

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            caps = get_caps()
            if not getattr(caps, cap_name, False):
                current = detect_edition()
                raise EditionGateError(
                    Edition.ENTERPRISE_STARTER, current, cap_name
                )
            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


# ---------------------------------------------------------------------------
# Tier transitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TierTransition:
    """Describes a tier change and its implications."""

    from_edition: Edition
    to_edition: Edition
    data_preserved: bool = True
    features_lost: tuple[str, ...] = ()
    features_gained: tuple[str, ...] = ()


_VALID_TRANSITIONS: dict[tuple[Edition, Edition], TierTransition] = {
    (Edition.OSS, Edition.ENTERPRISE_STARTER): TierTransition(
        from_edition=Edition.OSS,
        to_edition=Edition.ENTERPRISE_STARTER,
        features_gained=(
            "orgs", "billing", "audit_logs", "analytics",
            "conversations", "collaboration",
        ),
    ),
    (Edition.OSS, Edition.ENTERPRISE_PREMIUM): TierTransition(
        from_edition=Edition.OSS,
        to_edition=Edition.ENTERPRISE_PREMIUM,
        features_gained=(
            "orgs", "billing", "sso", "analytics", "audit_logs",
            "audit_signing", "custom_branding", "priority_support",
            "conversations", "collaboration", "self_improving",
        ),
    ),
    (Edition.ENTERPRISE_STARTER, Edition.ENTERPRISE_PREMIUM): TierTransition(
        from_edition=Edition.ENTERPRISE_STARTER,
        to_edition=Edition.ENTERPRISE_PREMIUM,
        features_gained=(
            "sso", "audit_signing", "custom_branding",
            "priority_support", "self_improving",
        ),
    ),
    (Edition.ENTERPRISE_PREMIUM, Edition.ENTERPRISE_STARTER): TierTransition(
        from_edition=Edition.ENTERPRISE_PREMIUM,
        to_edition=Edition.ENTERPRISE_STARTER,
        features_lost=(
            "sso", "audit_signing", "custom_branding",
            "priority_support", "self_improving",
        ),
    ),
    (Edition.ENTERPRISE_STARTER, Edition.OSS): TierTransition(
        from_edition=Edition.ENTERPRISE_STARTER,
        to_edition=Edition.OSS,
        features_lost=(
            "orgs", "billing", "audit_logs", "analytics",
            "conversations", "collaboration",
        ),
    ),
    (Edition.ENTERPRISE_PREMIUM, Edition.OSS): TierTransition(
        from_edition=Edition.ENTERPRISE_PREMIUM,
        to_edition=Edition.OSS,
        features_lost=(
            "orgs", "billing", "sso", "analytics", "audit_logs",
            "audit_signing", "custom_branding", "priority_support",
            "conversations", "collaboration", "self_improving",
        ),
    ),
}


def get_transition(
    from_edition: Edition, to_edition: Edition
) -> TierTransition | None:
    """Return the ``TierTransition`` for a tier change, or ``None`` if same."""
    if from_edition == to_edition:
        return None
    return _VALID_TRANSITIONS.get((from_edition, to_edition))


def validate_transition(
    from_edition: Edition, to_edition: Edition
) -> list[str]:
    """Return warnings for a tier transition (empty list if upgrade or same)."""
    if from_edition == to_edition:
        return []
    transition = get_transition(from_edition, to_edition)
    if transition is None:
        return [f"Unknown transition: {from_edition.value} → {to_edition.value}"]
    warnings: list[str] = []
    if transition.features_lost:
        warnings.append(
            f"Downgrade will disable: {', '.join(transition.features_lost)}"
        )
    return warnings
