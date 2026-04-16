"""Structured perf timing logger.

Single point of control for the "how slow is this endpoint" question. Every
`perf_span(...)` emits one INFO line on the `amprealize.perf` logger shaped
as `key=value` pairs so we can grep/parse later from container logs.

Gated by env var `AMPREALIZE_PERF_LOG` (default: enabled). Set to `0` to
A/B test whether the logging itself is a cost.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from typing import Any, Iterator

_PERF_LOG_ENABLED = os.environ.get("AMPREALIZE_PERF_LOG", "1") not in (
    "0",
    "",
    "false",
    "False",
    "no",
    "No",
)

perf_logger = logging.getLogger("amprealize.perf")


def perf_enabled() -> bool:
    return _PERF_LOG_ENABLED


def _format_tags(tags: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, value in tags.items():
        if value is None:
            rendered = "null"
        elif isinstance(value, float):
            rendered = f"{value:.1f}"
        else:
            rendered = str(value)
            if " " in rendered or "=" in rendered:
                rendered = rendered.replace(" ", "_").replace("=", "_")
        parts.append(f"{key}={rendered}")
    return " ".join(parts)


def perf_log(endpoint: str, t_total_ms: float, **tags: Any) -> None:
    if not _PERF_LOG_ENABLED:
        return
    payload = {"endpoint": endpoint, "t_total_ms": round(t_total_ms, 1), **tags}
    perf_logger.info("perf %s", _format_tags(payload))


@contextmanager
def perf_span(endpoint: str, **tags: Any) -> Iterator[dict[str, Any]]:
    """Time a block; extra tags can be added by mutating the yielded dict."""
    extra: dict[str, Any] = dict(tags)
    start = time.perf_counter()
    try:
        yield extra
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        perf_log(endpoint, elapsed_ms, **extra)
