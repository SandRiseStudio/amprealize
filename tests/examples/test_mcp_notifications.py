#!/usr/bin/env python3
"""Test script for MCP progress notifications."""
import json
import subprocess
import sys
import time
import threading
from typing import List, Dict, Any

def test_progress_notifications():
    """Test progress notifications during long-running pattern detection."""

    # Pattern detection requires run_ids, not trace_text
    # We'll use dummy run IDs for the test (real use would need actual runs)
    run_ids = [
        "run_001_test_notification",
        "run_002_test_notification",
        "run_003_test_notification"
    ]

    # Send pattern detection request
    request = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "patterns.detectPatterns",
            "arguments": {
                "run_ids": run_ids,
                "min_frequency": 1,
                "min_similarity": 0.5,
                "max_patterns": 10
            }
        }
    })

    print("=== Testing MCP Progress Notifications ===\n")
    print(f"Sending request: patterns.detectPatterns")
    print(f"Run IDs: {len(run_ids)} runs")

    proc = subprocess.Popen(
        [sys.executable, "-m", "amprealize.mcp_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1  # Line buffered
    )

    notifications: List[Dict[str, Any]] = []
    response = None

    def read_output():
        """Read stdout and collect notifications and response."""
        nonlocal response, notifications
        stdout = proc.stdout
        if not stdout:
            return
        for line in stdout:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                # Check if it's a notification (no 'id' field) or response
                if "id" in data:
                    response = data
                    print(f"\n✅ Received response: id={data.get('id')}")
                elif "method" in data:
                    notifications.append(data)
                    method = data.get("method")
                    params = data.get("params", {})
                    status = params.get("status", "unknown")
                    message = params.get("message", "")
                    print(f"📢 Notification: {method} - {status}: {message}")
            except json.JSONDecodeError:
                pass

    # Start output reader thread
    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()

    # Send request
    stdin = proc.stdin
    if stdin:
        stdin.write(request + "\n")
        stdin.flush()

    # Wait for completion (with timeout)
    start_time = time.time()
    while response is None and (time.time() - start_time) < 5:
        time.sleep(0.1)

    # Terminate process
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()

    # Give reader thread time to finish
    time.sleep(0.3)

    # Validate results
    print("\n=== Results ===")
    print(f"Notifications received: {len(notifications)}")

    if notifications:
        print("\nNotification details:")
        for i, notif in enumerate(notifications, 1):
            params = notif.get("params", {})
            print(f"  {i}. {params.get('status')}: {params.get('message')}")

    if response and "result" in response:
        print(f"\n✅ Pattern detection completed successfully")
        return True
    else:
        print(f"\n❌ No valid response received")
        if response:
            print(f"Response: {json.dumps(response, indent=2)}")
        return False

if __name__ == "__main__":
    success = test_progress_notifications()
    sys.exit(0 if success else 1)
