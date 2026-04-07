#!/usr/bin/env python3
"""Quick validation of metrics endpoint code."""
import sys
import json
from amprealize.mcp_server import MCPServer

def test_metrics_method():
    """Test that get_metrics_summary returns expected structure."""
    server = MCPServer()

    # Initialize metrics by calling some internal methods
    # (in real usage, metrics accumulate during request handling)
    server._metrics["requests_total"] = 10
    server._metrics["tool_calls_total"] = 15
    server._metrics["tool_calls_by_name"]["behaviors.list"] = 5
    server._metrics["tool_calls_by_name"]["runs.create"] = 10
    server._metrics["tool_latency_seconds"]["behaviors.list"] = [0.1, 0.2, 0.15, 0.3, 0.12]
    server._metrics["tool_latency_seconds"]["runs.create"] = [0.5, 0.6, 0.55, 0.7, 0.52, 0.48, 0.65, 0.58, 0.62, 0.59]

    # Call get_metrics_summary
    try:
        metrics = server.get_metrics_summary()

        print("=== METRICS SUMMARY ===")
        print(json.dumps(metrics, indent=2))

        # Validate structure
        required_fields = [
            "requests_total",
            "requests_by_method",
            "tool_calls_total",
            "tool_calls_by_name",
            "tool_latency_summary",
            "errors_total",
            "batch_requests_total",
        ]

        missing = [f for f in required_fields if f not in metrics]
        if missing:
            print(f"\n❌ Missing fields: {missing}")
            return False

        # Check latency summary structure
        if "behaviors.list" in metrics["tool_latency_summary"]:
            lat = metrics["tool_latency_summary"]["behaviors.list"]
            required_lat_fields = ["count", "mean", "median", "min", "max", "p95"]
            missing_lat = [f for f in required_lat_fields if f not in lat]
            if missing_lat:
                print(f"\n❌ Missing latency fields: {missing_lat}")
                return False

            print(f"\n✅ Latency metrics validated:")
            print(f"  - behaviors.list: {lat['count']} calls, p95={lat['p95']:.3f}s")

        print("\n✅ Metrics endpoint code validated successfully")
        return True

    except Exception as e:
        print(f"\n❌ Error calling get_metrics_summary: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_metrics_method()
    sys.exit(0 if success else 1)
