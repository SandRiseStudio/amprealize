#!/usr/bin/env python3
"""Smoke test: send initialize + 3 tool calls to the MCP server and check responses."""

import json
import subprocess
import sys
import threading
import time
import os


def frame(msg: dict) -> bytes:
    body = json.dumps(msg).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


def main():
    messages = [
        frame({
            "jsonrpc": "2.0", "id": "1", "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "smoketest", "version": "0.1"},
            },
        }),
        frame({
            "jsonrpc": "2.0", "id": "2", "method": "tools/call",
            "params": {"name": "auth_authstatus", "arguments": {"validate_remote": False}},
        }),
        frame({
            "jsonrpc": "2.0", "id": "3", "method": "tools/call",
            "params": {"name": "auth_deviceinit", "arguments": {"client_id": "amprealize-vscode", "scopes": ["actions:read"]}},
        }),
        frame({
            "jsonrpc": "2.0", "id": "4", "method": "tools/call",
            "params": {"name": "context_getcontext", "arguments": {}},
        }),
    ]

    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "amprealize.mcp_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=open("/tmp/mcp_stderr_smoke.log", "w"),
        env=env,
    )

    # Safety kill after 30s
    def watchdog():
        time.sleep(30)
        print("WATCHDOG: killing after 30s", flush=True)
        proc.kill()

    t = threading.Thread(target=watchdog, daemon=True)
    t.start()

    # Send all messages at once
    payload = b"".join(messages)
    proc.stdin.write(payload)
    proc.stdin.flush()
    proc.stdin.close()

    # Read and parse Content-Length framed responses
    responses = []
    start = time.time()
    buf = proc.stdout

    while len(responses) < 4:
        if time.time() - start > 25:
            print(f"TIMEOUT after 25s — only got {len(responses)}/4 responses")
            break

        # Read headers
        headers = {}
        while True:
            line = buf.readline()
            if line in (b"", b"\r\n", b"\n"):
                break
            try:
                k, v = line.decode().split(":", 1)
                headers[k.strip().lower()] = v.strip()
            except ValueError:
                # Could be newline-delimited JSON
                try:
                    obj = json.loads(line)
                    elapsed = time.time() - start
                    responses.append(obj)
                    rid = obj.get("id", "?")
                    print(f"  [{elapsed:.2f}s] Response id={rid}: {json.dumps(obj)[:200]}")
                    continue
                except json.JSONDecodeError:
                    pass

        cl = headers.get("content-length")
        if cl:
            body = buf.read(int(cl))
            if not body:
                break
            obj = json.loads(body)
            elapsed = time.time() - start
            responses.append(obj)
            rid = obj.get("id", "?")
            print(f"  [{elapsed:.2f}s] Response id={rid}: {json.dumps(obj)[:200]}")

    total = time.time() - start
    print(f"\nGot {len(responses)}/4 responses in {total:.2f}s")

    if len(responses) == 4:
        print("SUCCESS: All 4 responses received")
    else:
        print("FAIL: Not all responses received")

    proc.kill()
    proc.wait()
    return 0 if len(responses) == 4 else 1


if __name__ == "__main__":
    sys.exit(main())
