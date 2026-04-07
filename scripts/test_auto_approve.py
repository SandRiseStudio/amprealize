#!/usr/bin/env python3
"""End-to-end test: device_init (auto-approves) → device_poll → verify tokens."""

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


def main():
    env = {
        **os.environ,
        "PYTHONUNBUFFERED": "1",
        "AMPREALIZE_ORG_PG_DSN": "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize?options=-csearch_path%3Dauth",
        "AMPREALIZE_DEFAULT_APPROVER": "nick.sanders.a@gmail.com",
        "MCP_AUTO_APPROVE_DEVICE_FLOW": "true",
    }

    proc = subprocess.Popen(
        [sys.executable, "-m", "amprealize.mcp_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=open("/tmp/mcp_stderr_e2e.log", "w"),
        env=env,
    )

    def watchdog():
        time.sleep(20)
        print("WATCHDOG: killing after 20s", flush=True)
        proc.kill()

    t = threading.Thread(target=watchdog, daemon=True)
    t.start()

    # Step 1: Initialize MCP
    print("1. Initialize MCP...", flush=True)
    t0 = time.time()
    proc.stdin.write(frame({
        "jsonrpc": "2.0", "id": "1", "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "e2e-test", "version": "0.1"},
        },
    }))
    proc.stdin.flush()
    resp = read_response(proc.stdout)
    print(f"   [{time.time()-t0:.2f}s] OK", flush=True)
    if not resp:
        print("   FAIL: no init response"); proc.kill(); return 1

    # Step 2: device_init (should auto-approve)
    print("2. device_init (should auto-approve)...", flush=True)
    t1 = time.time()
    proc.stdin.write(frame({
        "jsonrpc": "2.0", "id": "2", "method": "tools/call",
        "params": {"name": "auth_deviceinit", "arguments": {"client_id": "amprealize-vscode"}},
    }))
    proc.stdin.flush()
    resp2 = read_response(proc.stdout)
    print(f"   [{time.time()-t1:.2f}s]", flush=True)
    if not resp2:
        print("   FAIL: no deviceinit response"); proc.kill(); return 1

    try:
        init_result = json.loads(resp2["result"]["content"][0]["text"])
        device_code = init_result["device_code"]
        user_code = init_result["user_code"]
        print(f"   device_code={device_code[:20]}... user_code={user_code}", flush=True)
    except Exception as e:
        print(f"   FAIL: parse error: {e}"); proc.kill(); return 1

    # Step 3: device_poll (NO manual approval needed!)
    print("3. device_poll (no manual approval)...", flush=True)
    t2 = time.time()
    proc.stdin.write(frame({
        "jsonrpc": "2.0", "id": "3", "method": "tools/call",
        "params": {
            "name": "auth_devicepoll",
            "arguments": {"device_code": device_code, "store_tokens": False},
        },
    }))
    proc.stdin.flush()
    resp3 = read_response(proc.stdout, timeout=10)
    elapsed = time.time() - t2
    if not resp3:
        print(f"   [{elapsed:.2f}s] FAIL: HANG/TIMEOUT")
        proc.kill()
        with open("/tmp/mcp_stderr_e2e.log") as f:
            print(f"STDERR:\n{f.read()[-2000:]}")
        return 1

    try:
        poll_result = json.loads(resp3["result"]["content"][0]["text"])
        status = poll_result.get("status")
        has_token = bool(poll_result.get("access_token"))
        print(f"   [{elapsed:.2f}s] status={status} has_token={has_token}", flush=True)
        if status == "authorized" and has_token:
            print(f"   access_token={poll_result['access_token'][:20]}...", flush=True)
        else:
            print(f"   UNEXPECTED: {json.dumps(poll_result)[:300]}", flush=True)
    except Exception as e:
        print(f"   [{elapsed:.2f}s] Parse error: {e}", flush=True)

    total = time.time() - t0
    print(f"\nTotal: {total:.2f}s", flush=True)

    if status == "authorized" and has_token:
        print("SUCCESS: Full auth flow works with auto-approve!", flush=True)
    else:
        print("FAIL: Auth flow did not complete", flush=True)

    proc.kill()
    proc.wait()
    return 0 if (status == "authorized" and has_token) else 1


if __name__ == "__main__":
    sys.exit(main())
