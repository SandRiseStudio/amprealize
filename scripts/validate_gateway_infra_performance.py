#!/usr/bin/env python3
"""Validate gateway / nginx / pool settings for avoidable web-console hot-path latency.

Static checks (no network): ``config/nginx/nginx.conf`` rate limits, keepalive, gzip,
proxy timeouts and HTTP/1.1 upgrade paths for API, SSE, and WebSockets.

Optional live probe: pass ``--base-url`` (e.g. ``http://localhost:8080``) to GET ``/health``.
If the API was started with ``AMPREALIZE_SERVER_TIMING=1``, the response includes
``Server-Timing`` for end-to-end timing through nginx + upstream.

Exit codes: 0 = pass, 1 = failures, 2 = warnings only (no hard failures).

Related: guideai-1144 (infra/gateway performance validation).
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path


def _failures_and_warnings(nginx_text: str) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    warnings: list[str] = []

    def require(pattern: str, msg: str, flags: int = re.MULTILINE) -> None:
        if not re.search(pattern, nginx_text, flags):
            failures.append(msg)

    def warn_if_missing(pattern: str, msg: str) -> None:
        if not re.search(pattern, nginx_text, re.MULTILINE):
            warnings.append(msg)

    require(r"tcp_nodelay\s+on", "tcp_nodelay should be enabled for low latency")
    require(r"keepalive_timeout\s+\d+", "keepalive_timeout should be set on http{}")
    require(r"gzip\s+on", "gzip should be enabled for text/json responses")
    require(r"sendfile\s+on", "sendfile should be enabled")
    require(r"limit_req_zone.*zone=api:", "API rate limit zone (api) should be defined")
    require(r"location\s+/api/", "location /api/ block should exist for console API")
    require(
        r"location\s+/api/[\s\S]*?proxy_http_version\s+1\.1",
        "/api/ should use proxy_http_version 1.1 (keep-alive to upstream)",
    )
    require(
        r"location\s+/sse/[\s\S]*?proxy_buffering\s+off",
        "/sse/ should disable proxy_buffering for streaming",
    )
    require(
        r"location\s+/ws/[\s\S]*?proxy_read_timeout\s+\d+[sm]",
        "/ws/ should set proxy_read_timeout for long-lived connections",
    )

    # Legacy /v1/ passthrough — shorter read timeout than /api/ is intentional for REST;
    # warn if missing entirely.
    warn_if_missing(
        r"location\s+/v1/",
        "no location /v1/ block — legacy clients may hit different timeouts than /api/",
    )

    return failures, warnings


def _probe_health(base_url: str) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    warnings: list[str] = []
    url = base_url.rstrip("/") + "/health"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read()
            if resp.status != 200:
                failures.append(f"GET {url} returned HTTP {resp.status}")
            elif len(body) > 64 * 1024:
                warnings.append(f"GET /health body unusually large ({len(body)} bytes)")
    except urllib.error.HTTPError as e:
        failures.append(f"GET {url} failed: HTTP {e.code}")
    except urllib.error.URLError as e:
        failures.append(f"GET {url} failed: {e.reason}")
    except Exception as e:
        failures.append(f"GET {url} failed: {e}")
    return failures, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        help="Optional gateway base URL (e.g. http://localhost:8080) to GET /health",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    nginx_path = repo_root / "config/nginx/nginx.conf"
    if not nginx_path.is_file():
        print(f"FAIL: missing {nginx_path}", file=sys.stderr)
        return 1

    nginx_text = nginx_path.read_text(encoding="utf-8")
    failures, warnings = _failures_and_warnings(nginx_text)

    if args.base_url:
        f2, w2 = _probe_health(args.base_url)
        failures.extend(f2)
        warnings.extend(w2)

    for w in warnings:
        print(f"WARN: {w}", file=sys.stderr)
    for f in failures:
        print(f"FAIL: {f}", file=sys.stderr)

    if failures:
        print(f"validate_gateway_infra_performance: {len(failures)} failure(s), {len(warnings)} warning(s)")
        return 1
    if warnings:
        print(f"validate_gateway_infra_performance: 0 failures, {len(warnings)} warning(s)")
        return 2
    print("validate_gateway_infra_performance: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
