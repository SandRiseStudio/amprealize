"""MCP handlers for local execution connector (pairing + device lifecycle).

Mirrors ``/api/v1/execution-connector/*`` REST routes using the in-process hub.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict

from ...connector_connection_status import build_connector_connection_status
from ...feature_flags import FeatureFlagService
from ...local_execution_connector_hub import get_local_execution_connector_hub


class ExecutionConnectorToolValidationError(ValueError):
    """Missing parameters for an execution connector MCP tool."""


def _require(arguments: Dict[str, Any], *fields: str) -> None:
    missing = [f for f in fields if not arguments.get(f)]
    if missing:
        raise ExecutionConnectorToolValidationError(
            "Missing required " + ("parameter" if len(missing) == 1 else "parameters") + ": " + ", ".join(missing)
        )


def _flag_enabled_global() -> bool:
    return FeatureFlagService().is_enabled("feature.local_execution_connector", context=None)


def create_execution_connector_handlers() -> Dict[str, Callable[..., Any]]:
    """Return async handlers keyed by internal tool name (``executionConnector.*``)."""

    async def handle_create_pairing_code(arguments: Dict[str, Any]) -> Dict[str, Any]:
        session = arguments.get("_session", {}) or {}
        user_id = arguments.get("user_id") or session.get("user_id")
        if not user_id:
            raise ExecutionConnectorToolValidationError("user_id is required (or authenticated session)")
        flags = FeatureFlagService()
        if not flags.is_enabled("feature.local_execution_connector", {"user_id": user_id}):
            return {"success": False, "error": "feature_disabled", "message": "feature.local_execution_connector is off"}
        hub = get_local_execution_connector_hub()

        def _sync() -> tuple[str, float]:
            return hub.create_pairing_code(user_id=user_id)

        code, expires = await asyncio.to_thread(_sync)
        return {"success": True, "code": code, "expires_at": expires}

    async def handle_claim_device(arguments: Dict[str, Any]) -> Dict[str, Any]:
        _require(arguments, "code")
        if not _flag_enabled_global():
            return {"success": False, "error": "feature_disabled", "message": "feature.local_execution_connector is off"}
        hub = get_local_execution_connector_hub()
        label = str(arguments.get("label") or "device")[:120]

        def _sync():
            return hub.claim_pairing_code(code=arguments["code"], label=label)

        try:
            dev = await asyncio.to_thread(_sync)
        except KeyError:
            return {"success": False, "error": "invalid_or_expired_pairing_code"}
        return {
            "success": True,
            "device_id": dev.device_id,
            "device_token": dev.device_token,
            "user_id": dev.user_id,
            "label": dev.label,
        }

    async def handle_revoke_device(arguments: Dict[str, Any]) -> Dict[str, Any]:
        _require(arguments, "device_token")
        if not _flag_enabled_global():
            return {"success": False, "error": "feature_disabled", "message": "feature.local_execution_connector is off"}
        hub = get_local_execution_connector_hub()

        def _sync() -> bool:
            return hub.revoke_device_token(arguments["device_token"])

        ok = await asyncio.to_thread(_sync)
        if not ok:
            return {"success": False, "error": "unknown_device_token"}
        return {"success": True}

    async def handle_verify_connection(arguments: Dict[str, Any]) -> Dict[str, Any]:
        session = arguments.get("_session", {}) or {}
        user_id = arguments.get("user_id") or session.get("user_id")
        if not user_id:
            raise ExecutionConnectorToolValidationError("user_id is required (or authenticated session)")
        depth_raw = str(arguments.get("depth") or "socket").strip().lower()
        flags = FeatureFlagService()
        if not flags.is_enabled("feature.local_execution_connector", {"user_id": user_id}):
            return {"success": False, "error": "feature_disabled", "message": "feature.local_execution_connector is off"}
        hub = get_local_execution_connector_hub()
        try:
            data = await build_connector_connection_status(user_id=str(user_id), depth=depth_raw, hub=hub)
        except ValueError as e:
            raise ExecutionConnectorToolValidationError(str(e)) from e
        out: Dict[str, Any] = {
            "success": True,
            "connected": data.connected,
            "depth": depth_raw,
        }
        if data.tool_invoke_ok is not None:
            out["tool_invoke_ok"] = data.tool_invoke_ok
        if data.tool_invoke_error is not None:
            out["tool_invoke_error"] = data.tool_invoke_error
        return out

    return {
        "executionConnector.createPairingCode": handle_create_pairing_code,
        "executionConnector.claimDevice": handle_claim_device,
        "executionConnector.revokeDevice": handle_revoke_device,
        "executionConnector.verifyConnection": handle_verify_connection,
    }
