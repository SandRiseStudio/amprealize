"""MCP tool handlers for auth and AgentAuth tools."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict


class AuthToolValidationError(ValueError):
    """Raised when an auth MCP tool is missing required runtime arguments."""


AuthHandler = Callable[[Any, Dict[str, Any]], Awaitable[Dict[str, Any]]]


def _require(arguments: Dict[str, Any], *fields: str) -> None:
    missing = [field for field in fields if not arguments.get(field)]
    if not missing:
        return
    label = "parameter" if len(missing) == 1 else "parameters"
    raise AuthToolValidationError(f"Missing required {label}: {', '.join(missing)}")


def _session_identity(server: Any, arguments: Dict[str, Any]) -> str | None:
    session = arguments.get("_session", {})
    return (
        arguments.get("user_id")
        or session.get("user_id")
        or getattr(getattr(server, "_session_context", None), "identity", None)
    )


def _default_agent_id(server: Any, arguments: Dict[str, Any]) -> None:
    if arguments.get("agent_id"):
        return
    identity = _session_identity(server, arguments)
    if identity:
        arguments["agent_id"] = identity


def _default_actor_field(server: Any, arguments: Dict[str, Any], field: str) -> None:
    if arguments.get(field):
        return
    identity = _session_identity(server, arguments)
    if identity:
        arguments[field] = identity


async def _handle_device_tool(server: Any, arguments: Dict[str, Any], tool_name: str) -> Dict[str, Any]:
    device_flow_handler = getattr(server, "_device_flow_handler", None)
    if not device_flow_handler:
        raise RuntimeError("Device flow handler not available")
    return await device_flow_handler.handle_tool_call(tool_name, arguments)


async def handle_device_login(server: Any, arguments: Dict[str, Any]) -> Dict[str, Any]:
    return await _handle_device_tool(server, arguments, "auth.deviceLogin")


async def handle_device_init(server: Any, arguments: Dict[str, Any]) -> Dict[str, Any]:
    return await _handle_device_tool(server, arguments, "auth.deviceInit")


async def handle_device_poll(server: Any, arguments: Dict[str, Any]) -> Dict[str, Any]:
    _require(arguments, "device_code")
    return await _handle_device_tool(server, arguments, "auth.devicePoll")


async def handle_auth_status(server: Any, arguments: Dict[str, Any]) -> Dict[str, Any]:
    return await _handle_device_tool(server, arguments, "auth.authStatus")


async def handle_refresh_token(server: Any, arguments: Dict[str, Any]) -> Dict[str, Any]:
    return await _handle_device_tool(server, arguments, "auth.refreshToken")


async def handle_refresh(server: Any, arguments: Dict[str, Any]) -> Dict[str, Any]:
    return await _handle_device_tool(server, arguments, "auth.refresh")


async def handle_logout(server: Any, arguments: Dict[str, Any]) -> Dict[str, Any]:
    return await _handle_device_tool(server, arguments, "auth.logout")


async def handle_client_credentials(server: Any, arguments: Dict[str, Any]) -> Dict[str, Any]:
    _require(arguments, "client_id", "client_secret")
    return await server._handle_client_credentials(arguments)


async def handle_ensure_grant(server: Any, arguments: Dict[str, Any]) -> Dict[str, Any]:
    _default_agent_id(server, arguments)
    arguments.setdefault("surface", "MCP")
    _require(arguments, "agent_id", "tool_name", "scopes")
    return await _handle_device_tool(server, arguments, "auth.ensureGrant")


async def handle_list_grants(server: Any, arguments: Dict[str, Any]) -> Dict[str, Any]:
    _default_agent_id(server, arguments)
    _require(arguments, "agent_id")
    return await _handle_device_tool(server, arguments, "auth.listGrants")


async def handle_policy_preview(server: Any, arguments: Dict[str, Any]) -> Dict[str, Any]:
    _default_agent_id(server, arguments)
    _require(arguments, "agent_id", "tool_name", "scopes")
    return await _handle_device_tool(server, arguments, "auth.policy.preview")


async def handle_revoke(server: Any, arguments: Dict[str, Any]) -> Dict[str, Any]:
    _default_actor_field(server, arguments, "revoked_by")
    _require(arguments, "grant_id", "revoked_by")
    return await _handle_device_tool(server, arguments, "auth.revoke")


async def handle_consent_lookup(server: Any, arguments: Dict[str, Any]) -> Dict[str, Any]:
    _require(arguments, "user_code")
    return await _handle_device_tool(server, arguments, "auth.consentLookup")


async def handle_consent_status(server: Any, arguments: Dict[str, Any]) -> Dict[str, Any]:
    return await handle_consent_lookup(server, arguments)


async def handle_consent_approve(server: Any, arguments: Dict[str, Any]) -> Dict[str, Any]:
    _default_actor_field(server, arguments, "approver")
    _require(arguments, "user_code", "approver")
    return await _handle_device_tool(server, arguments, "auth.consentApprove")


async def handle_consent_deny(server: Any, arguments: Dict[str, Any]) -> Dict[str, Any]:
    _default_actor_field(server, arguments, "approver")
    _require(arguments, "user_code", "approver")
    return await _handle_device_tool(server, arguments, "auth.consentDeny")


AUTH_HANDLERS: Dict[str, AuthHandler] = {
    "auth.deviceLogin": handle_device_login,
    "auth.deviceInit": handle_device_init,
    "auth.devicePoll": handle_device_poll,
    "auth.authStatus": handle_auth_status,
    "auth.refreshToken": handle_refresh_token,
    "auth.refresh": handle_refresh,
    "auth.logout": handle_logout,
    "auth.clientCredentials": handle_client_credentials,
    "auth.ensureGrant": handle_ensure_grant,
    "auth.listGrants": handle_list_grants,
    "auth.policy.preview": handle_policy_preview,
    "auth.revoke": handle_revoke,
    "auth.consentLookup": handle_consent_lookup,
    "auth.consentStatus": handle_consent_status,
    "auth.consentApprove": handle_consent_approve,
    "auth.consentDeny": handle_consent_deny,
}
