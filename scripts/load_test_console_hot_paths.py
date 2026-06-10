#!/usr/bin/env python3
"""Repeatable load test for web console hot API paths (guideai-1159).

Measures latency percentiles (p50, p75, p95) and error rate for:

- ``GET /api/v1/capabilities`` (no auth)
- ``GET /api/v1/console/dashboard-bootstrap`` (requires Bearer JWT)
- ``GET /api/v1/conversations/global-chat-bootstrap`` (requires Bearer JWT)
- ``GET /api/v1/boards/{board_id}/bootstrap`` (optional; requires ``--board-id``)

DB timing, worker queue depth, and Redis cache hit rates are server-side metrics —
correlate runs with ``/metrics``, Raze, or your observability stack.

Environment (optional):
  AMPREALIZE_LOAD_TEST_BASE_URL   default http://localhost:8080
  AMPREALIZE_LOAD_TEST_BEARER_TOKEN
  AMPREALIZE_LOAD_TEST_ORG_ID     query param for dashboard-bootstrap
  AMPREALIZE_LOAD_TEST_BOARD_ID

For token resolution from ``amprealize auth login`` (repo .venv), prefer::

  ./scripts/run_load_test_console_hot_paths.sh [--iterations N ...]

Following behavior_use_raze_for_logging (Student): this script prints to stdout only;
wire Raze separately if you need structured load-test telemetry.

Examples::

  python scripts/load_test_console_hot_paths.py --token "$JWT"
  python scripts/load_test_console_hot_paths.py --token "$JWT" --board-id <uuid> --iterations 50 --concurrency 5
  python scripts/load_test_console_hot_paths.py --json --max-p95-ms 800
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple


def percentile(sorted_vals: List[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def request_once(url: str, headers: Dict[str, str], timeout: float) -> Tuple[int, float]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
        ms = (time.perf_counter() - t0) * 1000.0
        return resp.status, ms
    except urllib.error.HTTPError as e:
        ms = (time.perf_counter() - t0) * 1000.0
        try:
            e.read()
        except Exception:
            pass
        return e.code, ms
    except Exception:
        ms = (time.perf_counter() - t0) * 1000.0
        return -1, ms


def build_headers(token: Optional[str]) -> Dict[str, str]:
    h: Dict[str, str] = {"Accept": "application/json", "User-Agent": "amprealize-load-test/1.0"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def run_scenario(
    name: str,
    url: str,
    headers: Dict[str, str],
    *,
    need_auth: bool,
    token: Optional[str],
    iterations: int,
    concurrency: int,
    timeout: float,
) -> Dict[str, Any]:
    if need_auth and not token:
        return {"scenario": name, "skipped": True, "reason": "missing bearer token"}

    latencies: List[float] = []
    errors = 0

    def one_call() -> Tuple[int, float]:
        return request_once(url, headers, timeout)

    if concurrency <= 1:
        for _ in range(iterations):
            status, ms = one_call()
            if status == 200:
                latencies.append(ms)
            else:
                errors += 1
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = [pool.submit(one_call) for _ in range(iterations)]
            for fut in as_completed(futures):
                status, ms = fut.result()
                if status == 200:
                    latencies.append(ms)
                else:
                    errors += 1

    latencies.sort()
    total = iterations
    ok = len(latencies)
    err_rate = errors / total if total else 0.0
    return {
        "scenario": name,
        "url": url,
        "iterations": total,
        "success": ok,
        "errors": errors,
        "error_rate": round(err_rate, 4),
        "p50_ms": round(percentile(latencies, 50), 2) if latencies else None,
        "p75_ms": round(percentile(latencies, 75), 2) if latencies else None,
        "p95_ms": round(percentile(latencies, 95), 2) if latencies else None,
        "max_ms": round(max(latencies), 2) if latencies else None,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--base-url",
        default=os.getenv("AMPREALIZE_LOAD_TEST_BASE_URL", "http://localhost:8080"),
        help="Gateway origin (no trailing slash)",
    )
    p.add_argument(
        "--token",
        default=os.getenv("AMPREALIZE_LOAD_TEST_BEARER_TOKEN"),
        help="Bearer JWT (or AMPREALIZE_LOAD_TEST_BEARER_TOKEN)",
    )
    p.add_argument("--iterations", type=int, default=20)
    p.add_argument("--concurrency", type=int, default=1)
    p.add_argument("--timeout", type=float, default=60.0)
    p.add_argument("--org-id", default=os.getenv("AMPREALIZE_LOAD_TEST_ORG_ID"))
    p.add_argument("--board-id", default=os.getenv("AMPREALIZE_LOAD_TEST_BOARD_ID"))
    p.add_argument("--board-limit", type=int, default=50)
    p.add_argument("--json", action="store_true")
    p.add_argument("--max-p95-ms", type=float, default=None)
    p.add_argument("--max-error-rate", type=float, default=0.05)
    args = p.parse_args()

    base = args.base_url.rstrip("/")
    headers = build_headers(args.token)

    scenarios: List[Tuple[str, str, bool]] = [
        ("capabilities", f"{base}/api/v1/capabilities", False),
        (
            "dashboard_bootstrap",
            f"{base}/api/v1/console/dashboard-bootstrap"
            + (f"?org_id={args.org_id}" if args.org_id else ""),
            True,
        ),
        (
            "global_chat_bootstrap",
            f"{base}/api/v1/conversations/global-chat-bootstrap?"
            "limit=50&offset=0&include_thread_replies=true",
            True,
        ),
    ]
    if args.board_id:
        scenarios.append(
            (
                "board_bootstrap",
                f"{base}/api/v1/boards/{args.board_id}/bootstrap?"
                f"limit={args.board_limit}&offset=0",
                True,
            )
        )

    results = []
    for name, url, need_auth in scenarios:
        results.append(
            run_scenario(
                name,
                url,
                headers,
                need_auth=need_auth,
                token=args.token,
                iterations=args.iterations,
                concurrency=args.concurrency,
                timeout=args.timeout,
            )
        )

    fail = False
    if args.json:
        print(json.dumps({"base_url": base, "results": results}, indent=2))
    else:
        print(
            f"load_test_console_hot_paths: base={base} iterations={args.iterations} "
            f"concurrency={args.concurrency}"
        )
        for r in results:
            if r.get("skipped"):
                print(f"  [{r['scenario']}] SKIPPED: {r['reason']}")
                continue
            print(
                f"  [{r['scenario']}] ok={r['success']}/{r['iterations']} err_rate={r['error_rate']} "
                f"p50={r['p50_ms']} p75={r['p75_ms']} p95={r['p95_ms']} ms (max={r['max_ms']})"
            )
            if args.max_p95_ms is not None and r.get("p95_ms") is not None:
                if r["p95_ms"] > args.max_p95_ms:
                    print(f"    FAIL p95 {r['p95_ms']} > {args.max_p95_ms}")
                    fail = True
            if r["error_rate"] > args.max_error_rate:
                print(f"    FAIL error_rate {r['error_rate']} > {args.max_error_rate}")
                fail = True

    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
