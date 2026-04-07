#!/usr/bin/env python3
"""Test script for MCP metrics endpoint."""
import json
import subprocess
import sys

def test_metrics_endpoint():
    """Test the MCP metrics endpoint via stdio."""
    # Send initialize request
    init_request = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "clientInfo": {"name": "test-client", "version": "0.1.0"}
        }
    })

    # Send metrics request
    metrics_request = json.dumps({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "metrics",
        "params": {}
    })

    # Send both requests
    input_data = f"{init_request}\n{metrics_request}\n"

    proc = None
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "amprealize.mcp_server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        stdout, stderr = proc.communicate(input=input_data, timeout=5)

        print("=== STDOUT ===")
        print(stdout)

        print("\n=== STDERR ===")
        print(stderr)

        # Parse responses
        responses = []
        for line in stdout.strip().split("\n"):
            if line:
                try:
                    responses.append(json.loads(line))
                except json.JSONDecodeError:
                    print(f"Warning: Could not parse line: {line}")

        # Validate metrics response
        if len(responses) >= 2:
            metrics_response = responses[1]
            if "result" in metrics_response:
                metrics = metrics_response["result"]
                print("\n=== METRICS SUMMARY ===")
                print(json.dumps(metrics, indent=2))

                # Validate expected fields
                expected_fields = [
                    "requests_total",
                    "tool_calls_total",
                    "errors_total",
                    "batch_requests_total",
                    "tool_calls_by_name",
                    "tool_latency_summary",
                ]

                for field in expected_fields:
                    if field not in metrics:
                        print(f"❌ Missing field: {field}")
                        return False

                print("\n✅ Metrics endpoint validated successfully")
                return True
            else:
                print(f"❌ Metrics response missing 'result': {metrics_response}")
                return False
        else:
            print(f"❌ Expected 2 responses, got {len(responses)}")
            return False

    except subprocess.TimeoutExpired:
        print("❌ MCP server timeout")
        if proc is not None:
            proc.kill()
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    success = test_metrics_endpoint()
    sys.exit(0 if success else 1)
