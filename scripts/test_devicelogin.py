#!/usr/bin/env python3
"""Test auth_devicelogin in isolation to detect hangs."""
import subprocess, json, time, os, signal

proc = subprocess.Popen(
    [".venv/bin/python", "-m", "amprealize.mcp_server"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=open("/tmp/mcp_devicelogin_err.log", "w"),
    env={**os.environ},
    cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)

def send(obj):
    data = json.dumps(obj)
    msg = f"Content-Length: {len(data)}\r\n\r\n{data}"
    proc.stdin.write(msg.encode())
    proc.stdin.flush()

def recv(label="", timeout_s=20):
    import select
    start = time.time()
    hdr = b""
    while b"\r\n\r\n" not in hdr:
        elapsed = time.time() - start
        if elapsed > timeout_s:
            print(f"  TIMEOUT after {elapsed:.1f}s waiting for {label}")
            return None
        ch = proc.stdout.read(1)
        if not ch:
            print(f"  EOF after {elapsed:.1f}s waiting for {label}")
            return None
        hdr += ch
    length = int(hdr.split(b"Content-Length: ")[1].split(b"\r\n")[0])
    body = proc.stdout.read(length)
    return json.loads(body)

t0 = time.time()

# Initialize
send({
    "jsonrpc": "2.0", "id": "1", "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "clientInfo": {"name": "test", "version": "0.1"},
        "capabilities": {},
    },
})
r = recv("initialize")
print(f"[{time.time()-t0:.2f}s] initialize: ok")

# deviceLogin
send({
    "jsonrpc": "2.0", "id": "2", "method": "tools/call",
    "params": {"name": "auth_devicelogin", "arguments": {}},
})
r = recv("auth_devicelogin", timeout_s=25)
elapsed = time.time() - t0
if r and "result" in r:
    text = json.loads(r["result"]["content"][0]["text"])
    print(f"[{elapsed:.2f}s] deviceLogin status: {text.get('status')}")
    if text.get("user_code"):
        print(f"  user_code: {text['user_code']}")
        print(f"  verification_uri: {text.get('verification_uri')}")
elif r and "error" in r:
    print(f"[{elapsed:.2f}s] deviceLogin error: {r['error']}")
else:
    print(f"[{elapsed:.2f}s] deviceLogin: no response or timeout")

proc.terminate()
proc.wait(timeout=5)
print(f"\nServer stderr log: /tmp/mcp_devicelogin_err.log")
