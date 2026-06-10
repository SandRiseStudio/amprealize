"""In-process hub for user-scoped local execution connector (pairing + run leases).

Industry pattern: a trusted local daemon opens an **outbound** WebSocket to the
platform ("client calls home"). The gateway registers pending runs; the hub
notifies connected daemons for that user.

This module is intentionally in-memory for the MVP slice (single-process dev /
tests). Replace with Redis + durable device store before multi-instance prod.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import string
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from starlette.websockets import WebSocket

logger = logging.getLogger(__name__)

# Sentinel ``run_id`` for connectivity checks: ``tool.invoke`` without ``run_lease`` (daemon handles inline).
CONNECTOR_PROBE_RUN_ID = "__amprealize_connector_probe__"

_PAIRING_TTL_SEC = 600
_DEVICE_TOKEN_PREFIX_LEN = 8


def _random_pairing_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    alphabet = alphabet.replace("0", "").replace("O", "").replace("I", "").replace("1", "")
    part = lambda n: "".join(secrets.choice(alphabet) for _ in range(n))
    return f"{part(4)}-{part(4)}"


@dataclass
class PendingLocalRun:
    run_id: str
    cycle_id: str
    user_id: str
    org_id: Optional[str]
    project_id: str
    work_item_id: str
    created_at: float = field(default_factory=time.time)


@dataclass
class RegisteredDevice:
    device_id: str
    user_id: str
    label: str
    device_token: str
    created_at: float = field(default_factory=time.time)


class LocalExecutionConnectorHub:
    """Pairing codes, device tokens, pending runs, and WebSocket fan-out per user."""

    def __init__(self) -> None:
        self._pairing: Dict[str, Tuple[str, float]] = {}  # code_upper -> (user_id, expires_at)
        self._devices_by_token: Dict[str, RegisteredDevice] = {}
        self._sockets_by_user: Dict[str, Set[WebSocket]] = {}
        self._pending_by_user: Dict[str, List[PendingLocalRun]] = {}
        # Outbound signals (e.g. cancel) when no WebSocket is connected yet, or from sync code paths.
        self._outbound_buffer: Dict[str, List[Dict[str, Any]]] = {}
        # Hybrid delegation: lease ack + tool.invoke / tool.result RPC (protocol v1).
        self._lease_events: Dict[str, asyncio.Event] = {}
        self._tool_futures: Dict[str, asyncio.Future] = {}

    def create_pairing_code(self, *, user_id: str) -> Tuple[str, float]:
        if not user_id:
            raise ValueError("user_id is required for pairing")
        for _ in range(20):
            code = _random_pairing_code()
            key = code.upper().replace("-", "")
            if key not in self._pairing:
                expires = time.time() + _PAIRING_TTL_SEC
                self._pairing[key] = (user_id, expires)
                return code, expires
        raise RuntimeError("Could not allocate pairing code")

    def claim_pairing_code(
        self,
        *,
        code: str,
        label: str,
    ) -> RegisteredDevice:
        raw = (code or "").strip().upper().replace("-", "")
        if raw not in self._pairing:
            raise KeyError("invalid_or_expired_pairing_code")
        user_id, expires = self._pairing.pop(raw)
        if time.time() > expires:
            raise KeyError("invalid_or_expired_pairing_code")
        device_id = f"dev-{uuid.uuid4().hex[:16]}"
        token = f"lec_{secrets.token_urlsafe(32)}"
        dev = RegisteredDevice(
            device_id=device_id,
            user_id=user_id,
            label=(label or "device").strip()[:120] or "device",
            device_token=token,
        )
        self._devices_by_token[token] = dev
        return dev

    def resolve_device_token(self, token: str) -> Optional[RegisteredDevice]:
        return self._devices_by_token.get(token)

    def revoke_device_token(self, token: str) -> bool:
        return self._devices_by_token.pop(token, None) is not None

    def register_websocket(self, *, user_id: str, websocket: WebSocket) -> None:
        self._sockets_by_user.setdefault(user_id, set()).add(websocket)

    def unregister_websocket(self, *, user_id: str, websocket: WebSocket) -> None:
        subs = self._sockets_by_user.get(user_id)
        if not subs:
            return
        subs.discard(websocket)
        if not subs:
            self._sockets_by_user.pop(user_id, None)

    def user_has_live_connector_socket(self, user_id: str) -> bool:
        """True if at least one outbound daemon WebSocket is registered for ``user_id``."""
        if not user_id:
            return False
        subs = self._sockets_by_user.get(user_id)
        return bool(subs)

    def enqueue_pending_run(self, pending: PendingLocalRun) -> None:
        self.ensure_lease_event(pending.run_id)
        self._pending_by_user.setdefault(pending.user_id, []).append(pending)

    def ensure_lease_event(self, run_id: str) -> asyncio.Event:
        if run_id not in self._lease_events:
            self._lease_events[run_id] = asyncio.Event()
        return self._lease_events[run_id]

    def signal_lease_ack(self, run_id: str) -> None:
        self.ensure_lease_event(run_id).set()

    async def wait_for_lease_ack(self, run_id: str, *, timeout_sec: float) -> bool:
        ev = self.ensure_lease_event(run_id)
        try:
            await asyncio.wait_for(ev.wait(), timeout=timeout_sec)
            return True
        except asyncio.TimeoutError:
            return False

    def resolve_tool_result(self, invoke_id: str, payload: Dict[str, Any]) -> bool:
        fut = self._tool_futures.get(invoke_id)
        if fut is None or fut.done():
            return False
        fut.set_result(payload)
        self._tool_futures.pop(invoke_id, None)
        return True

    async def invoke_tool(
        self,
        *,
        user_id: str,
        run_id: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        timeout_sec: float = 120.0,
    ) -> Dict[str, Any]:
        invoke_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._tool_futures[invoke_id] = fut
        msg: Dict[str, Any] = {
            "type": "tool.invoke",
            "protocol_version": 1,
            "invoke_id": invoke_id,
            "run_id": run_id,
            "tool_name": tool_name,
            "tool_args": tool_args or {},
        }
        await self.broadcast_or_buffer(user_id, msg)
        try:
            return await asyncio.wait_for(fut, timeout=timeout_sec)
        except asyncio.TimeoutError:
            self._tool_futures.pop(invoke_id, None)
            raise

    def pop_pending_runs_for_user(self, user_id: str) -> List[PendingLocalRun]:
        return self._pending_by_user.pop(user_id, [])

    async def notify_pending_run_async(self, pending: PendingLocalRun) -> None:
        """Push ``run_lease`` to all WebSockets registered for the run's user."""
        message = {
            "type": "run_lease",
            "run_id": pending.run_id,
            "cycle_id": pending.cycle_id,
            "work_item_id": pending.work_item_id,
            "project_id": pending.project_id,
            "org_id": pending.org_id,
            "user_id": pending.user_id,
        }
        for ws in list(self._sockets_by_user.get(pending.user_id, set())):
            try:
                await ws.send_json(message)
            except Exception:
                self.unregister_websocket(user_id=pending.user_id, websocket=ws)

    def buffer_outbound(self, user_id: str, message: Dict[str, Any]) -> None:
        self._outbound_buffer.setdefault(user_id, []).append(message)

    async def broadcast_or_buffer(self, user_id: str, message: Dict[str, Any]) -> None:
        """Deliver JSON to all live sockets for ``user_id``, or queue until a socket connects."""
        socks = list(self._sockets_by_user.get(user_id, set()))
        if not socks:
            self.buffer_outbound(user_id, message)
            return
        for ws in socks:
            try:
                await ws.send_json(message)
            except Exception:
                self.unregister_websocket(user_id=user_id, websocket=ws)

    async def flush_outbound_buffer(self, user_id: str) -> None:
        """Send any buffered outbound messages to all sockets for this user (then clear buffer)."""
        pending = self._outbound_buffer.pop(user_id, [])
        if not pending:
            return
        socks = list(self._sockets_by_user.get(user_id, set()))
        for msg in pending:
            for ws in socks:
                try:
                    await ws.send_json(msg)
                except Exception:
                    self.unregister_websocket(user_id=user_id, websocket=ws)

    def summarize_device_token(self, token: str) -> Dict[str, Any]:
        dev = self._devices_by_token.get(token)
        if not dev:
            return {"valid": False}
        return {
            "valid": True,
            "device_id": dev.device_id,
            "user_id": dev.user_id,
            "label": dev.label,
            "token_prefix": token[:_DEVICE_TOKEN_PREFIX_LEN],
        }


_hub: Optional[LocalExecutionConnectorHub] = None


def get_local_execution_connector_hub() -> LocalExecutionConnectorHub:
    global _hub
    if _hub is None:
        _hub = LocalExecutionConnectorHub()
    return _hub


def reset_local_execution_connector_hub_for_tests() -> None:
    """Clear singleton state (pytest isolation)."""
    global _hub
    if _hub is not None:
        for fut in list(_hub._tool_futures.values()):
            if not fut.done():
                fut.cancel()
        _hub._tool_futures.clear()
        _hub._lease_events.clear()
    _hub = None


def schedule_local_connector_outbound(user_id: str, message: Dict[str, Any]) -> None:
    """Schedule async delivery of a JSON message to connector WebSockets, or buffer if no event loop."""
    hub = get_local_execution_connector_hub()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        hub.buffer_outbound(user_id, message)
        return
    loop.create_task(hub.broadcast_or_buffer(user_id, message))


def emit_local_connector_cancel_from_terminal_completion(prior_run: Any, completion: Any) -> None:
    """When a run is completed as CANCELLED, notify paired connector daemons (WebSocket)."""
    from amprealize.run_contracts import RunStatus

    if getattr(completion, "status", None) != RunStatus.CANCELLED:
        return
    md = getattr(prior_run, "metadata", None) or {}
    if md.get("execution_workspace_kind") != "local_connector":
        return
    actor = getattr(prior_run, "actor", None)
    user_id = getattr(actor, "id", None) if actor else None
    run_id = getattr(prior_run, "run_id", None)
    if not user_id or not run_id:
        return
    reason = getattr(completion, "message", None) or "cancelled"
    msg = {"type": "run.cancel_requested", "run_id": run_id, "reason": reason}
    try:
        schedule_local_connector_outbound(user_id, msg)
    except Exception:
        logger.debug("local connector cancel notify failed", exc_info=True)
