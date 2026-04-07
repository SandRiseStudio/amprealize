#!/usr/bin/env python3
"""Focused test: device_init → approve in PG → device_poll. Measures timing."""

import json
import subprocess
import sys
import threading
import time
import os


def frame(msg: dict) -> bytes:
    body = json.dumps(msg).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n".encode("ascii")
    return header + b"\r\n" + body


def read_response(buf, timeout=10):
    """Read one Content-Length framed response."""
    start = time.time()
    headers = {}
    while True:
        if time.time() - start > timeout:
            return None
        line = buf.readline()
        if line in (b"", b"\r\n", b"\n"):
            if headers:
                break
            continue
        try:
            k, v = line.decode().split(":", 1)
            headers[k.strip().lower()] = v.strip()
        except ValueError:
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                pass

    cl = headers.get("content-length")
    if cl:
        body = buf.read(int(cl))
        if body:
            return json.loads(body)
    return None


def approve_in_pg(user_code: str):
    """Approve the device session directly in PostgreSQL."""
    sql = f"""
    UPDATE auth.device_sessions SET
      status = 'APPROVED',
      approver = 'test@test.com',
      approved_at = NOW(),
      access_token = md5(random()::text) || md5(random()::text),
      refresh_token = md5(random()::text) || md5(random()::text),
      access_token_expires_at = NOW() + interval '1 hour',
      refresh_token_expires_at = NOW() + interval '30 days',
      oauth_user_id = 'nick.sanders.a@gmail.com',
      oauth_email = 'nick.sanders.a@gmail.com'
    WHERE user_code = '{user_code}' AND status = 'PENDING'
    RETURNING user_code, status;
    """
    dsn = "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize"
    result = subprocess.run(
        ["psql", dsn, "-c", sql],
        capture_output=True, text=True, timeout=5,
    )
    print(f"  PG approve: {result.stdout.strip()}", flush=True)
    if result.returncode != 0:
        print(f"  PG error: {result.stderr.strip()}", flush=True)


def main():
    # MCP server env — match .vscode/mcp.json
    env = {
        **os.environ,
        "PYTHONUNBUFFERED": "1",
        "AMPREALIZE_ORG_PG_DSN": "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize?options=-csearch_path%3Dauth",
    }

    proc = subprocess.Popen(
        [sys.executable, "-m", "amprealize.mcp_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=open("/tmp/mcp_stderr_poll.log", "w"),
        env=env,
    )

    def watchdog():
        time.sleep(20)
        print("WATCHDOG: killing after 20s", flush=True)
        proc.kill()

    t = threading.Thread(target=watchdog, daemon=True)
    t.start()

    # Step 1: Initialize
    print("Step 1: Sending initialize...", flush=True)
    t0 = time.time()
    proc.stdin.write(frame({
        "jsonrpc": "2.0", "id": "1", "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "poll-test", "version": "0.1"},
        },
    }))
    proc.stdin.flush()
    resp = read_response(proc.stdout)
    print(f"  [{time.time()-t0:.2f}s] init: {json.dumps(resp)[:200] if resp else 'TIMEOUT'}", flush=True)

    if not resp:
        proc.kill(); return 1

    # Step 2: device_init
    print("\nStep 2: Sending auth_deviceinit...", flush=True)
    t1 = time.time()
    proc.stdin.write(frame({
        "jsonrpc": "2.0", "id": "2", "method": "tools/call",
        "params": {"name": "auth_deviceinit", "arguments": {"client_id": "amprealize-vscode"}},
    }))
    proc.stdin.flush()
    resp2 = read_response(proc.stdout)
    print(f"  [{time.time()-t1:.2f}s] deviceinit: {json.dumps(resp2)[:300] if resp2 else 'TIMEOUT'}", flush=True)

    if not resp2:
        proc.kill(); return 1

    # Extract device_code and user_code
    try:
        content_text = resp2["result"]["content"][0]["text"]
        init_result = json.loads(content_text)
        device_code = init_result["device_code"]
        user_code = init_result["user_code"]
        print(f"  device_code={device_code[:20]}... user_code={user_code}", flush=True)
    except Exception as e:
        print(f"  Failed to parse: {e}", flush=True)
        proc.kill(); return 1

    # Step 3: Approve in PostgreSQL
    print("\nStep 3: Approving in PostgreSQL...", flush=True)
    approve_in_pg(user_code)

    # Step 4: device_poll (THE CRITICAL TEST)
    print("\nStep 4: Sending auth_devicepoll (store_tokens=false)...", flush=True)
    t2 = time.time()
    proc.stdin.write(frame({
        "jsonrpc": "2.0", "id": "3", "method": "tools/call",
        "params": {
            "name": "auth_devicepoll",
            "arguments": {
                "device_code": device_code,
                "store_tokens": False,
            },
        },
    }))
    proc.stdin.flush()
    resp3 = read_response(proc.stdout, timeout=15)
    elapsed = time.time() - t2
    print(f"  [{elapsed:.2f}s] devicepoll: {json.dumps(resp3)[:400] if resp3 else 'TIMEOUT/HANG'}", flush=True)

    if not resp3:
        print("\n*** HANG DETECTED — checking stderr ***", flush=True)
        proc.kill()
        proc.wait()
        with open("/tmp/mcp_stderr_poll.log") as f:
            stderr = f.read()
        print(f"STDERR (last 2000 chars):\n{stderr[-2000:]}", flush=True)
        return 1

    total = time.time() - t0
    print(f"\nSUCCESS: All steps completed in {total:.2f}s", flush=True)

    proc.kill()
    proc.wait()
    return 0


if __name__ == "__main__":
    sys.exit(main())
