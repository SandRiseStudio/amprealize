"""Process-wide runtime overrides for boolean feature flags (Postgres-backed UI).

Used by :class:`amprealize.feature_flags.FeatureFlagService` so admin API updates
take effect immediately in this worker. Other workers pick up changes on their
next restart unless a shared cache layer is added later.
"""

from __future__ import annotations

import threading
from typing import Dict, Optional

_lock = threading.Lock()
_overrides: Dict[str, bool] = {}


def snapshot_overrides() -> Dict[str, bool]:
    with _lock:
        return dict(_overrides)


def replace_overrides(values: Dict[str, bool]) -> None:
    with _lock:
        _overrides.clear()
        _overrides.update(values)


def set_override(flag_name: str, enabled: bool) -> None:
    with _lock:
        _overrides[flag_name] = enabled


def clear_override(flag_name: str) -> None:
    with _lock:
        _overrides.pop(flag_name, None)


def get_boolean_override(flag_name: str) -> Optional[bool]:
    """Return DB-backed override for *flag_name*, or ``None`` if unset."""
    with _lock:
        if flag_name not in _overrides:
            return None
        return bool(_overrides[flag_name])
