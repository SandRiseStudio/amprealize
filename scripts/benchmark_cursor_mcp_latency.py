#!/usr/bin/env python3
"""Benchmark Cursor-visible Amprealize MCP latency.

This uses MCP Content-Length framing, starts the same launcher Cursor uses by
default, and measures the client-visible path: process startup, initialize,
tools/list, and tools/call.
"""

from __future__ import annotations

import argparse
import math
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_COMMAND = [
    sys.executable,
    str(ROOT / "scripts" / "start_amprealize_mcp.py"),
]


def _encode_message(message: Dict[str, Any]) -> bytes:
    body = json.dumps(message, separators=(",", ":")).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


def _read_message(proc: subprocess.Popen[bytes], *, timeout_seconds: float) -> Dict[str, Any]:
    deadline = time.perf_counter() + timeout_seconds
    headers: Dict[str, str] = {}

    while time.perf_counter() < deadline:
        line = proc.stdout.readline() if proc.stdout else b""
        if not line:
            if proc.poll() is not None:
                stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
                raise RuntimeError(f"MCP server exited early with {proc.returncode}: {stderr}")
            continue
        if line in (b"\r\n", b"\n"):
            break
        decoded = line.decode("ascii", errors="replace").strip()
        if ":" in decoded:
            key, value = decoded.split(":", 1)
            headers[key.lower()] = value.strip()

    length = int(headers.get("content-length", "0"))
    if length <= 0:
        raise RuntimeError(f"Missing Content-Length header: {headers}")

    body = proc.stdout.read(length) if proc.stdout else b""
    if len(body) != length:
        raise RuntimeError(f"Short MCP response: expected {length}, received {len(body)}")
    return json.loads(body.decode("utf-8"))


def _send_message(proc: subprocess.Popen[bytes], message: Dict[str, Any]) -> None:
    if not proc.stdin:
        raise RuntimeError("MCP server stdin is closed")
    proc.stdin.write(_encode_message(message))
    proc.stdin.flush()


def _request(
    proc: subprocess.Popen[bytes],
    request_id: int,
    method: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    timeout_seconds: float,
) -> tuple[Dict[str, Any], float]:
    message: Dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params

    start = time.perf_counter()
    _send_message(proc, message)
    response = _read_message(proc, timeout_seconds=timeout_seconds)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return response, elapsed_ms


def _notify(proc: subprocess.Popen[bytes], method: str, params: Optional[Dict[str, Any]] = None) -> None:
    message: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        message["params"] = params
    _send_message(proc, message)


def _spawn_server(command: Iterable[str], env: Dict[str, str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        list(command),
        cwd=str(ROOT),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _terminate(proc: subprocess.Popen[bytes]) -> None:
    try:
        if proc.stdin:
            proc.stdin.close()
    except Exception:
        pass
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        proc.kill()


def run_benchmark(iterations: int, timeout_seconds: float, command: list[str]) -> Dict[str, Any]:
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("MCP_REQUIRE_AUTH", "false")
    env.setdefault("MCP_RATE_LIMIT_ENABLED", "false")
    env.setdefault("AMPREALIZE_MCP_HOT_PATH_LOGS", "false")

    cold_starts = []
    initialize_times = []
    tools_list_times = []
    active_groups_times = []
    tools_list_bytes = []
    active_tool_counts = []

    for _ in range(iterations):
        proc = _spawn_server(command, env)
        process_start = time.perf_counter()
        try:
            init_response, init_ms = _request(
                proc,
                1,
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "cursor-mcp-latency-benchmark", "version": "1.0.0"},
                },
                timeout_seconds=timeout_seconds,
            )
            if "error" in init_response:
                raise RuntimeError(f"initialize failed: {init_response}")
            _notify(proc, "notifications/initialized")

            tools_response, tools_ms = _request(
                proc,
                2,
                "tools/list",
                timeout_seconds=timeout_seconds,
            )
            tool_call_response, tool_call_ms = _request(
                proc,
                3,
                "tools/call",
                {"name": "tools_activegroups", "arguments": {}},
                timeout_seconds=timeout_seconds,
            )
            if "error" in tool_call_response:
                raise RuntimeError(f"tools_activegroups failed: {tool_call_response}")

            tools_result = tools_response.get("result", {})
            tools = tools_result.get("tools", [])
            initialize_times.append(init_ms)
            tools_list_times.append(tools_ms)
            active_groups_times.append(tool_call_ms)
            tools_list_bytes.append(len(json.dumps(tools_response, separators=(",", ":")).encode("utf-8")))
            active_tool_counts.append(len(tools))
            cold_starts.append((time.perf_counter() - process_start) * 1000)
        finally:
            _terminate(proc)

    def summary(values: list[float]) -> Dict[str, float]:
        ordered = sorted(values)
        p95_index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * 0.95) - 1))
        return {
            "avg": round(statistics.mean(values), 3),
            "p50": round(statistics.median(values), 3),
            "p95": round(ordered[p95_index], 3),
            "max": round(max(values), 3),
        }

    return {
        "iterations": iterations,
        "command": command,
        "initialize_ms": summary(initialize_times),
        "tools_list_ms": summary(tools_list_times),
        "tools_activegroups_ms": summary(active_groups_times),
        "cold_start_to_activegroups_ms": summary(cold_starts),
        "tools_list_bytes_avg": round(statistics.mean(tools_list_bytes), 1),
        "active_tools_avg": round(statistics.mean(active_tool_counts), 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--direct",
        action="store_true",
        help="Run python -m amprealize.mcp_server directly instead of the Cursor launcher.",
    )
    args = parser.parse_args()

    command = [sys.executable, "-m", "amprealize.mcp_server"] if args.direct else DEFAULT_COMMAND
    result = run_benchmark(args.iterations, args.timeout, command)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
