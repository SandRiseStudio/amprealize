"""REST routes for local execution connector (pairing + device lifecycle).

Auth model matches other dev-oriented execution routes: callers pass
``user_id`` as a query parameter until a unified session middleware is wired.
Production must bind these routes to authenticated identity.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from amprealize.connector_connection_status import build_connector_connection_status
from amprealize.feature_flags import FeatureFlagService
from amprealize.local_execution_connector_hub import get_local_execution_connector_hub
from amprealize.run_contracts import RunStatus

logger = logging.getLogger(__name__)


class PairingCodeResponse(BaseModel):
    code: str
    expires_at: float = Field(description="Unix timestamp when the code expires")


class ClaimDeviceRequest(BaseModel):
    code: str = Field(..., min_length=1)
    label: str = Field("device", max_length=120)


class ClaimDeviceResponse(BaseModel):
    device_id: str
    device_token: str
    user_id: str
    label: str


class RevokeDeviceRequest(BaseModel):
    device_token: str = Field(..., min_length=10)


class ConnectorConnectionStatusResponse(BaseModel):
    connected: bool = Field(description="True when this API instance has an outbound daemon WebSocket for the user")
    depth: str = Field(default="socket", description="Echo of requested depth: socket or invoke")
    tool_invoke_ok: Optional[bool] = Field(
        default=None,
        description="When depth=invoke: True if list_dir probe succeeded on the daemon",
    )
    tool_invoke_error: Optional[str] = Field(
        default=None,
        description="When depth=invoke and probe failed or was skipped: machine-readable reason",
    )


def create_local_execution_connector_routes(*, tags: Optional[list] = None) -> APIRouter:
    router = APIRouter(prefix="/v1/execution-connector", tags=tags or ["execution-connector"])
    flags = FeatureFlagService()

    @router.post("/pairing-codes", response_model=PairingCodeResponse)
    async def create_pairing_code(user_id: str = Query(..., description="User issuing the code")):
        if not flags.is_enabled("feature.local_execution_connector", {"user_id": user_id}):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail="feature.local_execution_connector is disabled",
            )
        hub = get_local_execution_connector_hub()
        try:
            code, expires = hub.create_pairing_code(user_id=user_id)
        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
        return PairingCodeResponse(code=code, expires_at=expires)

    @router.get("/connection-status", response_model=ConnectorConnectionStatusResponse)
    async def connection_status(
        user_id: str = Query(..., description="User whose connector presence is checked"),
        depth: str = Query(
            "socket",
            description="socket: WebSocket registered only; invoke: additionally run list_dir probe via tool.invoke",
        ),
    ):
        uid = user_id.strip()
        if not uid:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="user_id is required")
        if not flags.is_enabled("feature.local_execution_connector", {"user_id": uid}):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail="feature.local_execution_connector is disabled",
            )
        hub = get_local_execution_connector_hub()
        try:
            data = await build_connector_connection_status(user_id=uid, depth=depth, hub=hub)
        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
        depth_norm = (depth or "socket").strip().lower()
        return ConnectorConnectionStatusResponse(
            connected=data.connected,
            depth=depth_norm,
            tool_invoke_ok=data.tool_invoke_ok,
            tool_invoke_error=data.tool_invoke_error,
        )

    @router.post("/devices", response_model=ClaimDeviceResponse)
    async def claim_device(body: ClaimDeviceRequest):
        if not flags.is_enabled("feature.local_execution_connector", context=None):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail="feature.local_execution_connector is disabled",
            )
        hub = get_local_execution_connector_hub()
        try:
            dev = hub.claim_pairing_code(code=body.code, label=body.label)
        except KeyError:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="invalid_or_expired_pairing_code",
            ) from None
        return ClaimDeviceResponse(
            device_id=dev.device_id,
            device_token=dev.device_token,
            user_id=dev.user_id,
            label=dev.label,
        )

    @router.post("/devices:revoke", status_code=status.HTTP_204_NO_CONTENT)
    async def revoke_device(body: RevokeDeviceRequest):
        if not flags.is_enabled("feature.local_execution_connector", context=None):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail="feature.local_execution_connector is disabled",
            )
        hub = get_local_execution_connector_hub()
        if not hub.revoke_device_token(body.device_token):
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="unknown_device_token")
        return None

    return router


def register_execution_connector_websocket(app: Any) -> None:
    """Outbound-daemon WebSocket: ``/api/v1/execution-connector/ws?device_token=...``."""

    from starlette.websockets import WebSocket, WebSocketDisconnect

    @app.websocket("/api/v1/execution-connector/ws")
    async def execution_connector_ws(websocket: WebSocket) -> None:
        token = (websocket.query_params.get("device_token") or "").strip()
        hub = get_local_execution_connector_hub()
        dev = hub.resolve_device_token(token) if token else None
        if not dev:
            await websocket.accept()
            await websocket.send_json(
                {
                    "type": "error",
                    "code": "UNAUTHORIZED",
                    "message": "valid device_token query parameter required",
                }
            )
            await websocket.close(code=1008)
            return

        if not FeatureFlagService().is_enabled("feature.local_execution_connector", context=None):
            await websocket.accept()
            await websocket.send_json(
                {
                    "type": "error",
                    "code": "FORBIDDEN",
                    "message": "feature.local_execution_connector is disabled",
                }
            )
            await websocket.close(code=1008)
            return

        await websocket.accept()
        user_id = dev.user_id
        hub.register_websocket(user_id=user_id, websocket=websocket)
        pending = hub.pop_pending_runs_for_user(user_id)
        try:
            for run in pending:
                await websocket.send_json(
                    {
                        "type": "run_lease",
                        "run_id": run.run_id,
                        "cycle_id": run.cycle_id,
                        "work_item_id": run.work_item_id,
                        "project_id": run.project_id,
                        "org_id": run.org_id,
                        "user_id": run.user_id,
                    }
                )
            await hub.flush_outbound_buffer(user_id)
            await websocket.send_json(
                {
                    "type": "connector.ready",
                    "user_id": user_id,
                    "device_id": dev.device_id,
                    "replayed_pending": len(pending),
                }
            )
            while True:
                try:
                    raw = await websocket.receive()
                except WebSocketDisconnect:
                    break
                if raw.get("type") == "websocket.disconnect":
                    break
                if raw.get("type") != "websocket.receive":
                    continue
                try:
                    text = raw.get("text")
                    if not text:
                        continue
                    msg = json.loads(text)
                except Exception:
                    continue
                if msg.get("type") == "ping":
                    await websocket.send_json({"type": "pong", "ts": time.time()})
                    continue

                if msg.get("type") == "connector.heartbeat":
                    ack: Dict[str, Any] = {"type": "connector.heartbeat_ack", "ts": time.time()}
                    active = msg.get("active_run_id")
                    if isinstance(active, str) and active.strip():
                        ack["active_run_id"] = active.strip()
                        container = getattr(websocket.app.state, "container", None)
                        run_service = getattr(container, "run_service", None) if container else None
                        if run_service is not None:
                            try:
                                r = run_service.get_run(active.strip())
                                st = str(getattr(r, "status", "") or "").upper()
                                ack["run_cancel_requested"] = st == RunStatus.CANCELLED
                            except Exception:
                                ack["run_cancel_requested"] = False
                    await websocket.send_json(ack)
                    continue

                if msg.get("type") == "tool.result":
                    invoke_id = msg.get("invoke_id")
                    if isinstance(invoke_id, str) and invoke_id.strip():
                        hub.resolve_tool_result(invoke_id.strip(), msg)
                    await websocket.send_json(
                        {"type": "daemon.ack", "ok": True, "invoke_id": invoke_id}
                    )
                    continue

                if msg.get("type") in ("run.progress", "run.complete", "run.fail", "run.lease_ack"):
                    container = getattr(websocket.app.state, "container", None)
                    run_service = getattr(container, "run_service", None) if container else None
                    if run_service is None:
                        await websocket.send_json(
                            {
                                "type": "daemon.ack",
                                "ok": False,
                                "error": "run_service_unavailable",
                                "run_id": msg.get("run_id"),
                            }
                        )
                        continue
                    from amprealize.local_execution_connector_ws_handler import (
                        apply_connector_daemon_message,
                    )

                    result = apply_connector_daemon_message(
                        device_user_id=user_id,
                        message=msg,
                        run_service=run_service,
                    )
                    await websocket.send_json(
                        {
                            "type": "daemon.ack",
                            "run_id": msg.get("run_id"),
                            **result,
                        }
                    )
        finally:
            hub.unregister_websocket(user_id=user_id, websocket=websocket)
