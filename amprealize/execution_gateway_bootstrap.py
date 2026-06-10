"""Bootstrap policy for gateway-backed execution start paths."""

from __future__ import annotations


_FALSE_VALUES = {"0", "false", "no", "off"}
_TRUE_VALUES = {"1", "true", "yes", "on"}


def is_execution_gateway_enabled(raw_value: str | None) -> bool:
    """Return whether execution starts should route through ExecutionGateway.

    The gateway is now the canonical start boundary. The environment flag remains
    as an explicit escape hatch for legacy fallback during incident response.
    """
    if raw_value is None:
        return True

    normalized = raw_value.strip().lower()
    if normalized in _FALSE_VALUES:
        return False
    if normalized in _TRUE_VALUES:
        return True
    return True
