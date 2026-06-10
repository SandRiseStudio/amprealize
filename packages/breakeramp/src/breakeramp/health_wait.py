"""Poll gateway and API /health until the dev stack is ready to use."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional, Tuple
from urllib.parse import urljoin


@dataclass
class HealthWaitResult:
    """Outcome of waiting for stack health checks."""

    ok: bool
    gateway_ok: bool
    direct_api_ok: bool
    attempts: int
    elapsed_s: float
    last_error: Optional[str] = None


def _fetch_json(url: str, *, timeout_s: float) -> Tuple[int, Optional[dict]]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = resp.read().decode()
            status = getattr(resp, "status", 200)
            try:
                return status, json.loads(body)
            except json.JSONDecodeError:
                return status, None
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()
        except Exception:
            pass
        try:
            return e.code, json.loads(body) if body else None
        except json.JSONDecodeError:
            return e.code, None
    except urllib.error.URLError as e:
        raise ConnectionError(str(e.reason)) from e


def endpoint_ready(url: str, *, strict: bool, request_timeout_s: float = 5.0) -> Tuple[bool, Optional[str]]:
    """Return True when URL responds with readiness criteria.

    Non-strict: HTTP 200 on GET.
    Strict: HTTP 200 and JSON body ``status`` equals ``healthy`` (case-insensitive).
    """
    try:
        status, data = _fetch_json(url, timeout_s=request_timeout_s)
    except Exception as exc:
        return False, str(exc)

    if status != 200:
        return False, f"HTTP {status}"

    if not strict:
        return True, None

    if not isinstance(data, dict):
        return False, "strict mode requires JSON body with status"

    st = data.get("status")
    if isinstance(st, str) and st.lower() == "healthy":
        return True, None

    return False, f"status is {data.get('status')!r}, expected healthy"


def wait_for_stack_health(
    *,
    gateway_health_url: str,
    direct_api_health_url: Optional[str] = None,
    strict: bool = False,
    max_wait_s: float = 300.0,
    interval_s: float = 2.0,
    request_timeout_s: float = 5.0,
) -> HealthWaitResult:
    """Poll gateway /health until ready; optionally verify direct API /health."""

    deadline = time.monotonic() + max_wait_s
    attempts = 0
    overall_ok = False
    last_err: Optional[str] = None
    gw_ok = False
    api_ok = False
    start = time.monotonic()

    while time.monotonic() < deadline:
        attempts += 1
        gw_ok, err_gw = endpoint_ready(
            gateway_health_url,
            strict=strict,
            request_timeout_s=request_timeout_s,
        )
        if not gw_ok:
            last_err = f"gateway: {err_gw}"
            if time.monotonic() + interval_s <= deadline:
                time.sleep(interval_s)
            continue

        if direct_api_health_url:
            api_ok, err_api = endpoint_ready(
                direct_api_health_url,
                strict=strict,
                request_timeout_s=request_timeout_s,
            )
            if not api_ok:
                last_err = f"direct API: {err_api}"
                if time.monotonic() + interval_s <= deadline:
                    time.sleep(interval_s)
                continue
        else:
            api_ok = True

        overall_ok = True
        break

    elapsed = time.monotonic() - start
    if not overall_ok and last_err is None:
        last_err = "timeout"

    return HealthWaitResult(
        ok=overall_ok,
        gateway_ok=gw_ok,
        direct_api_ok=api_ok,
        attempts=attempts,
        elapsed_s=elapsed,
        last_error=None if overall_ok else last_err,
    )


def default_gateway_health_url() -> str:
    base = __import__("os").environ.get("AMPREALIZE_GATEWAY_URL", "http://localhost:8080").rstrip("/")
    return urljoin(base + "/", "health")


def default_direct_api_health_url() -> str:
    base = __import__("os").environ.get("AMPREALIZE_API_HEALTH_URL", "http://localhost:8000").rstrip("/")
    return urljoin(base + "/", "health")
