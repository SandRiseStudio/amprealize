"""``python -m amprealize.connector_daemon`` entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys


def _cmd_pair(args: argparse.Namespace) -> int:
    from amprealize.connector_daemon.client import http_json

    status, data = http_json(
        "POST",
        "/v1/execution-connector/devices",
        {"code": args.code, "label": args.label or "daemon"},
    )
    if status >= 400:
        print(json.dumps({"ok": False, "status": status, "detail": data}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(data, indent=2))
    if args.emit_env:
        print(
            f"\n# Paste into your shell:\nexport AMPREALIZE_DEVICE_TOKEN={data.get('device_token', '')!r}",
            file=sys.stderr,
        )
    return 0


def _cmd_pairing_code(args: argparse.Namespace) -> int:
    from amprealize.connector_daemon.client import http_json
    from urllib.parse import quote

    uid = quote(args.user_id, safe="")
    status, data = http_json("POST", f"/v1/execution-connector/pairing-codes?user_id={uid}", None)
    if status >= 400:
        print(json.dumps({"ok": False, "status": status, "detail": data}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(data, indent=2))
    return 0


def _cmd_revoke(args: argparse.Namespace) -> int:
    from amprealize.connector_daemon.client import http_json

    token = args.device_token or os.environ.get("AMPREALIZE_DEVICE_TOKEN", "")
    if not token:
        print("device_token required (--device-token or AMPREALIZE_DEVICE_TOKEN)", file=sys.stderr)
        return 1
    status, data = http_json("POST", "/v1/execution-connector/devices:revoke", {"device_token": token})
    if status >= 400:
        print(json.dumps({"ok": False, "status": status, "detail": data}, indent=2), file=sys.stderr)
        return 1
    return 0


async def _cmd_listen_async(args: argparse.Namespace) -> int:
    try:
        import websockets  # noqa: F401
    except ImportError:
        print(
            "Install optional dependency: pip install 'amprealize[connector]'",
            file=sys.stderr,
        )
        return 1

    from amprealize.connector_daemon.runner import listen_forever, ws_url_with_token

    token = args.device_token or os.environ.get("AMPREALIZE_DEVICE_TOKEN", "")
    if not token:
        print("device_token required (--device-token or AMPREALIZE_DEVICE_TOKEN)", file=sys.stderr)
        return 1
    url = ws_url_with_token(token)
    await listen_forever(url)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Amprealize local execution connector daemon")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_code = sub.add_parser("pairing-code", help="Create a one-time pairing code (requires API auth)")
    p_code.add_argument("--user-id", required=True, help="User ID for whom the code is issued")
    p_code.set_defaults(_fn=_cmd_pairing_code)

    p_pair = sub.add_parser("pair", help="Claim a pairing code and print device credentials")
    p_pair.add_argument("--code", required=True, help="Pairing code from the server")
    p_pair.add_argument("--label", default="daemon", help="Device label")
    p_pair.add_argument(
        "--emit-env",
        action="store_true",
        help="Print suggested export AMPREALIZE_DEVICE_TOKEN to stderr",
    )
    p_pair.set_defaults(_fn=_cmd_pair)

    p_rev = sub.add_parser("revoke", help="Revoke a device token")
    p_rev.add_argument("--device-token", default=None, help="Device token (else AMPREALIZE_DEVICE_TOKEN)")
    p_rev.set_defaults(_fn=_cmd_revoke)

    p_listen = sub.add_parser("listen", help="Connect WebSocket and process run leases (requires websockets)")
    p_listen.add_argument("--device-token", default=None, help="Device token (else AMPREALIZE_DEVICE_TOKEN)")
    p_listen.set_defaults(_fn=None)

    args = parser.parse_args()
    if args.cmd == "listen":
        return asyncio.run(_cmd_listen_async(args))
    return int(args._fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
