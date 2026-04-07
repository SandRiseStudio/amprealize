"""Lightweight device-flow surface adapters.

Extracted from adapters.py to avoid pulling in the full heavy import chain
(ActionService, BCIService, FAISS, etc.) when only device flow functionality
is needed — especially at MCP server startup.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .device_flow import (
    DeviceFlowManager,
    DeviceAuthorizationSession,
    DevicePollResult,
)


class BaseDeviceFlowAdapter:
    """Surface-specific wrapper around DeviceFlowManager."""

    def __init__(self, manager: DeviceFlowManager, surface: str) -> None:
        self._manager = manager
        self.surface = surface

    @staticmethod
    def _normalize_user_code(user_code: str) -> str:
        stripped = "".join(ch for ch in user_code if ch.isalnum())
        if not stripped:
            raise ValueError("user_code must contain letters or numbers")
        upper = stripped.upper()
        if len(upper) >= 8:
            midpoint = len(upper) // 2
            return f"{upper[:midpoint]}-{upper[midpoint:]}"
        return upper

    @staticmethod
    def _format_session(session: DeviceAuthorizationSession) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "device_code": session.device_code,
            "user_code": session.user_code,
            "client_id": session.client_id,
            "scopes": list(session.scopes),
            "surface": session.surface,
            "status": session.status.value,
            "verification_uri": session.verification_uri,
            "verification_uri_complete": session.verification_uri_complete,
            "created_at": session.created_at.isoformat(),
            "expires_at": session.expires_at.isoformat(),
            "poll_interval": session.poll_interval,
        }
        if session.approved_at:
            payload["approved_at"] = session.approved_at.isoformat()
        if session.denied_at:
            payload["denied_at"] = session.denied_at.isoformat()
        if session.denied_reason:
            payload["denied_reason"] = session.denied_reason
        return payload

    @staticmethod
    def _format_poll_result(result: DevicePollResult) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "status": result.status.value,
            "retry_after": result.retry_after,
            "expires_in": result.expires_in,
            "client_id": result.client_id,
            "scopes": list(result.scopes or []),
        }
        if result.denied_reason:
            payload["denied_reason"] = result.denied_reason
        if result.tokens:
            payload.update(
                {
                    "access_token": result.tokens.access_token,
                    "refresh_token": result.tokens.refresh_token,
                    "token_type": result.tokens.token_type,
                    "access_token_expires_at": result.tokens.access_token_expires_at.isoformat(),
                    "refresh_token_expires_at": result.tokens.refresh_token_expires_at.isoformat(),
                }
            )
        return payload

    def start_authorization(
        self,
        *,
        client_id: str,
        scopes: List[str],
        metadata: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        session = self._manager.start_authorization(
            client_id=client_id,
            scopes=scopes,
            surface=self.surface,
            metadata=metadata,
        )
        return self._format_session(session)

    def lookup_user_code(self, user_code: str) -> Dict[str, Any]:
        normalized = self._normalize_user_code(user_code)
        session = self._manager.describe_user_code(normalized)
        return self._format_session(session)

    def poll(self, device_code: str) -> Dict[str, Any]:
        result = self._manager.poll_device_code(device_code)
        return self._format_poll_result(result)

    def refresh(self, refresh_token: str) -> Dict[str, Any]:
        session = self._manager.refresh_access_token(refresh_token)
        tokens = session.tokens
        assert tokens is not None, "refreshed session must include tokens"
        return {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "token_type": tokens.token_type,
            "access_token_expires_at": tokens.access_token_expires_at.isoformat(),
            "refresh_token_expires_at": tokens.refresh_token_expires_at.isoformat(),
            "access_expires_in": tokens.access_expires_in(),
            "refresh_expires_in": tokens.refresh_expires_in(),
            "client_id": session.client_id,
            "scopes": list(session.scopes),
            # Include user info for session context re-establishment
            "user_id": session.approver,
            "email": session.approver,
        }

    def approve(
        self,
        user_code: str,
        *,
        approver: str,
        roles: Optional[List[str]] = None,
        mfa_verified: bool = False,
    ) -> Dict[str, Any]:
        normalized = self._normalize_user_code(user_code)
        session = self._manager.approve_user_code(
            normalized,
            approver,
            approver_surface=self.surface,
            roles=roles,
            mfa_verified=mfa_verified,
        )
        return self._format_session(session)

    def deny(
        self,
        user_code: str,
        *,
        approver: str,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized = self._normalize_user_code(user_code)
        session = self._manager.deny_user_code(
            normalized,
            approver,
            approver_surface=self.surface,
            reason=reason,
        )
        return self._format_session(session)


class CLIDeviceFlowAdapter(BaseDeviceFlowAdapter):
    """Device flow adapter scoped to CLI surface."""

    def __init__(self, manager: DeviceFlowManager) -> None:
        super().__init__(manager, surface="cli")


class MCPDeviceFlowAdapter(BaseDeviceFlowAdapter):
    """Device flow adapter scoped to MCP surface."""

    def __init__(self, manager: DeviceFlowManager) -> None:
        super().__init__(manager, surface="mcp")
