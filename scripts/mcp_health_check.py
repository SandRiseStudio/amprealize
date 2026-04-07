#!/usr/bin/env python3
"""
MCP Server Health Check Script

Sends a JSON-RPC health check request to the MCP server via stdin/stdout
and returns exit code 0 for healthy, 1 for unhealthy.

Used by Docker HEALTHCHECK for container health monitoring.

Usage:
    # Check health via stdin/stdout (for stdio transport)
    echo '{"jsonrpc":"2.0","id":"health","method":"health"}' | python -m amprealize.mcp_server | python scripts/mcp_health_check.py

    # Or run standalone for HTTP transport (future)
    python scripts/mcp_health_check.py --http http://localhost:3000/health

Epic 6 - MCP Server Deployment
"""

import argparse
import json
import sys
import subprocess
from typing import Any, Dict, Optional


def check_health_stdio(timeout: int = 10) -> Dict[str, Any]:
    """
    Send health check request via stdio to MCP server.

    Args:
        timeout: Timeout in seconds for health check

    Returns:
        Health status dict from MCP server

    Raises:
        RuntimeError: If health check fails
    """
    # Construct JSON-RPC health request
    request = {
        "jsonrpc": "2.0",
        "id": "health-check",
        "method": "health",
    }

    # Read from stdin if piped
    if not sys.stdin.isatty():
        # Parse response from piped input
        try:
            line = sys.stdin.readline().strip()
            if line:
                response = json.loads(line)
                if "result" in response:
                    return response["result"]
                elif "error" in response:
                    raise RuntimeError(f"Health check error: {response['error']}")
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Failed to parse health response: {e}")

    raise RuntimeError("No input received - ensure MCP server output is piped")


def check_health_http(url: str, timeout: int = 10) -> Dict[str, Any]:
    """
    Send health check request via HTTP (for future HTTP transport).

    Args:
        url: Health check endpoint URL
        timeout: Timeout in seconds

    Returns:
        Health status dict
    """
    import urllib.request
    import urllib.error

    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode())
    except urllib.error.URLError as e:
        raise RuntimeError(f"HTTP health check failed: {e}")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid JSON response: {e}")


def main() -> int:
    """
    Run health check and return exit code.

    Returns:
        0 for healthy/degraded, 1 for unhealthy
    """
    parser = argparse.ArgumentParser(
        description="MCP Server Health Check",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--http",
        metavar="URL",
        help="HTTP health endpoint URL (for HTTP transport)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="Health check timeout in seconds (default: 10)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print detailed health status",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return exit code 1 for degraded status (default: only unhealthy)",
    )

    args = parser.parse_args()

    try:
        if args.http:
            health = check_health_http(args.http, args.timeout)
        else:
            health = check_health_stdio(args.timeout)

        status = health.get("status", "unknown")

        if args.verbose:
            print(json.dumps(health, indent=2))
        else:
            print(f"Status: {status}")

        # Exit code based on status
        if status == "unhealthy":
            return 1
        elif status == "degraded" and args.strict:
            return 1
        elif status in ("healthy", "degraded"):
            return 0
        else:
            # Unknown status
            print(f"Warning: Unknown health status: {status}", file=sys.stderr)
            return 1

    except Exception as e:
        print(f"Health check failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
