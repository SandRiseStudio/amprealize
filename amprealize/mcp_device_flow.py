"""
MCP Device Flow Integration

This module provides MCP tool implementations for OAuth 2.0 device authorization flow,
enabling AI assistants (Claude Desktop, Cursor, etc.) to authenticate with Amprealize
using the same token storage as the CLI.

Integration points:
- DeviceFlowManager (amprealize/device_flow.py) for RFC 8628 device auth
- PostgresDeviceFlowStore (amprealize/auth/postgres_device_flow.py) for shared state
- KeychainTokenStore (amprealize/auth_tokens.py) for cross-platform token persistence
- MCPDeviceFlowAdapter (amprealize/adapters.py) for MCP surface-specific operations

Tool manifest definitions:
- mcp/tools/auth.deviceLogin.json
- mcp/tools/auth.authStatus.json
- mcp/tools/auth.refreshToken.json
- mcp/tools/auth.logout.json
- mcp/tools/auth.consentLookup.json
- mcp/tools/auth.consentApprove.json
- mcp/tools/auth.consentDeny.json

Usage:
    # For MCP server stdio dispatch:
    handler = MCPDeviceFlowHandler()
    result = await handler.handle_tool_call("auth.deviceLogin", {
        "client_id": "amprealize-mcp-client",
        "scopes": ["behaviors.read", "runs.create"],
        "timeout": 300
    })

    # For direct Python integration:
    service = MCPDeviceFlowService()
    result = await service.device_login(
        client_id="amprealize-mcp-client",
        scopes=["behaviors.read"],
        poll_interval=5,
        timeout=300,
        store_tokens=True
    )
"""

import asyncio
import os
import time
import platform
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from pathlib import Path

from .device_flow import (
    DeviceFlowManager,
    DeviceAuthorizationSession,
    DevicePollResult,
    DeviceAuthorizationStatus,
)
from .auth_tokens import (
    AuthTokenBundle,
    TokenStore,
    TokenStoreError,
    get_default_token_store,
)
from .telemetry import TelemetryClient
from .services.agent_auth_service import (
    AgentAuthService,
    EnsureGrantRequest,
    ListGrantsRequest,
    PolicyPreviewRequest,
    RevokeGrantRequest,
)
from .auth.providers.registry import ProviderRegistry
from .auth.providers.base import OAuthProvider

if TYPE_CHECKING:
    from .auth.postgres_device_flow import PostgresDeviceFlowStore


class MCPDeviceFlowService:
    """
    High-level device flow service for MCP tools.

    Orchestrates device authorization flow with automatic polling,
    token storage, and telemetry integration.

    When postgres_store is provided, uses PostgreSQL-backed shared state
    for device sessions. This allows MCP server and REST API to share
    the same device authorization state for true E2E auth.
    """

    def __init__(
        self,
        manager: Optional[DeviceFlowManager] = None,
        token_store: Optional[TokenStore] = None,
        telemetry: Optional[TelemetryClient] = None,
        agent_auth_service: Optional[AgentAuthService] = None,
        postgres_store: Optional["PostgresDeviceFlowStore"] = None,
    ) -> None:
        """
        Initialize MCP device flow service.

        Args:
            manager: DeviceFlowManager instance (creates default if None)
            token_store: TokenStore instance (uses get_default_token_store if None)
            telemetry: TelemetryClient instance (optional)
            agent_auth_service: AgentAuthService instance for policy enforcement (optional)
            postgres_store: PostgresDeviceFlowStore for shared device session state (optional)
        """
        self._manager = manager or DeviceFlowManager()
        self._token_store = token_store
        self._telemetry = telemetry
        self._agent_auth_service = agent_auth_service
        self._postgres_store = postgres_store
        # Import from lightweight device_flow_adapters (not heavy adapters.py)
        from .device_flow_adapters import MCPDeviceFlowAdapter
        self._adapter = MCPDeviceFlowAdapter(self._manager)

    def _get_token_store(self) -> TokenStore:
        """Get token store instance, lazily initializing if needed."""
        if self._token_store is None:
            self._token_store = get_default_token_store()
        return self._token_store

    @staticmethod
    def _db_call_timeout_seconds() -> float:
        """Timeout for blocking database-backed device-flow calls."""
        try:
            return float(os.environ.get("MCP_DB_CALL_TIMEOUT_SECONDS", "5"))
        except ValueError:
            return 5.0

    @staticmethod
    def _token_store_timeout_seconds() -> float:
        """Timeout for token store operations that may block on keychain backends."""
        try:
            return float(os.environ.get("MCP_AUTH_STORE_TIMEOUT_SECONDS", "3"))
        except ValueError:
            return 3.0

    async def device_init(
        self,
        *,
        client_id: str = "amprealize-mcp-client",
        scopes: Optional[List[str]] = None,
        poll_interval: int = 5,
    ) -> Dict[str, Any]:
        """
        Initiate device authorization flow (non-blocking).

        Returns device code and verification URI immediately.
        Uses PostgreSQL store for shared state when available.
        """
        if scopes is None:
            scopes = ["behaviors.read", "workflows.read", "runs.create"]

        metadata = {
            "hostname": platform.node(),
            "platform": sys.platform,
            "mcp_client": "amprealize-mcp",
        }

        # Emit telemetry
        if self._telemetry:
            self._telemetry.emit_event(
                event_type="device_flow.mcp.init",
                payload={"client_id": client_id, "scopes": scopes},
            )

        # Use PostgreSQL store for shared state if available
        if self._postgres_store:
            try:
                # Wrap synchronous database call in asyncio.to_thread to avoid blocking event loop
                # and enforce timeout so auth.deviceInit cannot hang indefinitely.
                session = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._postgres_store.create_session,
                        client_id=client_id,
                        scopes=scopes,
                        surface="mcp",
                        metadata=metadata,
                    ),
                    timeout=self._db_call_timeout_seconds(),
                )

                # Auto-approve in dev mode (no real OAuth provider to redirect to).
                # Controlled by MCP_AUTO_APPROVE_DEVICE_FLOW env var (default: true).
                auto_approve = os.getenv("MCP_AUTO_APPROVE_DEVICE_FLOW", "true").lower() in ("1", "true", "yes")
                if auto_approve:
                    approver = os.getenv("AMPREALIZE_DEFAULT_APPROVER", "auto-approve@local")
                    try:
                        await asyncio.wait_for(
                            asyncio.to_thread(
                                self._postgres_store.approve,
                                session.device_code,
                                approver=approver,
                                approver_surface="mcp-auto",
                            ),
                            timeout=self._db_call_timeout_seconds(),
                        )
                    except Exception as exc:
                        # Non-fatal — poll can still work if approved manually later
                        if self._telemetry:
                            self._telemetry.emit_event(
                                event_type="device_flow.mcp.auto_approve_failed",
                                payload={"error": str(exc), "device_code": session.device_code},
                            )

                verification_uri = os.getenv("AMPREALIZE_DEVICE_VERIFICATION_URI", "https://device.amprealize.dev/activate")
                return {
                    "device_code": session.device_code,
                    "user_code": session.user_code,
                    "verification_uri": verification_uri,
                    "verification_uri_complete": f"{verification_uri}?user_code={session.user_code}",
                    "expires_in": int((session.expires_at - session.created_at).total_seconds()),
                    "interval": session.poll_interval,
                }
            except asyncio.TimeoutError:
                if self._telemetry:
                    self._telemetry.emit_event(
                        event_type="device_flow.mcp.db_timeout",
                        payload={"operation": "device_init", "client_id": client_id},
                    )
            except Exception as exc:
                if self._telemetry:
                    self._telemetry.emit_event(
                        event_type="device_flow.mcp.db_fallback",
                        payload={"operation": "device_init", "client_id": client_id, "error": str(exc)},
                    )

        # Fallback to in-memory manager
        session_data = self._adapter.start_authorization(
            client_id=client_id,
            scopes=scopes,
            metadata=metadata,
        )

        # Auto-approve in-memory session too
        auto_approve = os.getenv("MCP_AUTO_APPROVE_DEVICE_FLOW", "true").lower() in ("1", "true", "yes")
        if auto_approve and session_data.get("user_code"):
            approver = os.getenv("AMPREALIZE_DEFAULT_APPROVER", "auto-approve@local")
            try:
                self._adapter.approve(session_data["user_code"], approver=approver)
            except Exception:
                pass  # Non-fatal

        return {
            "device_code": session_data["device_code"],
            "user_code": session_data["user_code"],
            "verification_uri": session_data["verification_uri"],
            "verification_uri_complete": session_data.get("verification_uri_complete"),
            "expires_in": session_data.get("expires_in", 600),
            "interval": session_data.get("poll_interval", poll_interval),
        }

    async def device_poll(
        self,
        *,
        device_code: str,
        client_id: str = "amprealize-mcp-client",
        store_tokens: bool = True,
    ) -> Dict[str, Any]:
        """
        Poll for device authorization status (single check).
        Uses PostgreSQL store for shared state when available.
        """
        try:
            # Use PostgreSQL store for shared state if available
            if self._postgres_store:
                # Wrap synchronous database call in asyncio.to_thread to avoid blocking event loop
                session = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._postgres_store.get_by_device_code, device_code
                    ),
                    timeout=self._db_call_timeout_seconds(),
                )
                if session is None:
                    return {
                        "status": "error",
                        "error": "invalid_device_code",
                        "error_description": "Device code not found",
                    }

                status_normalized = {
                    "approved": "authorized",
                    "denied": "denied",
                    "expired": "expired",
                    "pending": "pending",
                }.get(session.status.lower(), session.status.lower())

                # Check for expiration
                if session.expires_at and session.expires_at < datetime.now(timezone.utc):
                    status_normalized = "expired"

                result: Dict[str, Any] = {"status": status_normalized}

                if status_normalized == "authorized":
                    if session.access_token is None:
                        return {
                            "status": "error",
                            "error": "tokens_not_ready",
                            "error_description": "Session approved but tokens not generated",
                        }

                    # Calculate expires_in
                    access_expires_in = 3600
                    if session.access_token_expires_at:
                        access_expires_in = int((session.access_token_expires_at - datetime.now(timezone.utc)).total_seconds())

                    result.update({
                        "access_token": session.access_token,
                        "refresh_token": session.refresh_token,
                        "token_type": "Bearer",
                        "scopes": session.scopes or [],
                        "expires_in": max(0, access_expires_in),
                        "user_id": session.oauth_user_id or session.oauth_email or session.approver,
                        "email": session.oauth_email or session.approver,
                    })

                    if store_tokens:
                        try:
                            store = self._get_token_store()
                            bundle = AuthTokenBundle(
                                access_token=session.access_token,
                                refresh_token=session.refresh_token,
                                token_type="Bearer",
                                scopes=session.scopes or [],
                                client_id=session.client_id or client_id,
                                issued_at=session.approved_at or datetime.now(timezone.utc),
                                expires_at=session.access_token_expires_at or datetime.now(timezone.utc),
                                refresh_expires_at=session.refresh_token_expires_at,
                            )
                            await asyncio.wait_for(
                                asyncio.to_thread(store.save, bundle),
                                timeout=self._token_store_timeout_seconds(),
                            )
                        except (TokenStoreError, asyncio.TimeoutError, Exception) as exc:
                            result["error"] = "storage_failed"
                            result["error_description"] = str(exc)

                elif status_normalized == "denied":
                    result["error"] = "access_denied"
                    result["error_description"] = session.denied_reason or "Denied"

                elif status_normalized == "expired":
                    result["error"] = "expired_token"

                return result

            # Fallback to in-memory manager
            poll_result = self._adapter.poll(device_code)
            status_value = poll_result["status"]

            # Map status to standard values
            status_normalized = {
                "APPROVED": "authorized",
                "DENIED": "denied",
                "EXPIRED": "expired",
                "PENDING": "pending",
            }.get(status_value.upper(), status_value.lower())

            result: Dict[str, Any] = {"status": status_normalized}

            if status_value.upper() == "APPROVED":
                result.update({
                    "access_token": poll_result["access_token"],
                    "refresh_token": poll_result["refresh_token"],
                    "token_type": poll_result.get("token_type", "Bearer"),
                    "scopes": poll_result["scopes"],
                    "expires_in": poll_result.get("expires_in", 3600),
                })

                if store_tokens:
                    try:
                        store = self._get_token_store()
                        bundle = AuthTokenBundle(
                            access_token=poll_result["access_token"],
                            refresh_token=poll_result["refresh_token"],
                            token_type=poll_result.get("token_type", "Bearer"),
                            scopes=poll_result["scopes"],
                            client_id=poll_result.get("client_id", client_id),
                            issued_at=datetime.now(timezone.utc),
                            expires_at=datetime.fromisoformat(poll_result["access_token_expires_at"]),
                            refresh_expires_at=datetime.fromisoformat(poll_result["refresh_token_expires_at"]),
                        )
                        await asyncio.wait_for(
                            asyncio.to_thread(store.save, bundle),
                            timeout=self._token_store_timeout_seconds(),
                        )
                    except (TokenStoreError, asyncio.TimeoutError, Exception) as exc:
                        result["error"] = "storage_failed"
                        result["error_description"] = str(exc)

            elif status_value.upper() == "DENIED":
                result["error"] = "access_denied"
                result["error_description"] = poll_result.get("denied_reason", "Denied")

            elif status_value.upper() == "EXPIRED":
                result["error"] = "expired_token"

            return result

        except Exception as exc:
            return {
                "status": "error",
                "error": "poll_failed",
                "error_description": str(exc)
            }

    async def device_login(
        self,
        *,
        client_id: str = "amprealize-mcp-client",
        scopes: Optional[List[str]] = None,
        poll_interval: int = 5,
        timeout: int = 300,
        store_tokens: bool = True,
        wait_for_authorization: bool = False,
    ) -> Dict[str, Any]:
        """
        Initiate device authorization flow and poll until completion.

        This implements the full auth.deviceLogin MCP tool flow:
        1. Start device authorization (get device_code and user_code)
        2. Return verification URL and user code to display
        3. Poll authorization server until user approves/denies
        4. If successful, optionally persist tokens to keychain
        5. Return final authorization status with tokens

        Args:
            client_id: OAuth client identifier
            scopes: Requested OAuth scopes (defaults to ["behaviors.read", "runs.create"])
            poll_interval: Polling interval in seconds (server may override)
            timeout: Maximum wait time in seconds before giving up
            store_tokens: Whether to persist tokens in keychain/file storage
            wait_for_authorization: If True, block and poll until authorized/denied/expired/timeout.
                If False (recommended for MCP agents), return pending status immediately and
                use auth.devicePoll with returned device_code.

        Returns:
            Dictionary with status, tokens, and metadata per auth.deviceLogin.json schema
        """
        if scopes is None:
            scopes = ["behaviors.read", "workflows.read", "runs.create"]

        metadata = {
            "hostname": platform.node(),
            "platform": sys.platform,
            "mcp_client": "amprealize-mcp",
        }

        # Emit telemetry for device login start
        if self._telemetry:
            self._telemetry.emit_event(
                event_type="device_flow.mcp.login_started",
                payload={
                    "client_id": client_id,
                    "scopes": scopes,
                    "timeout": timeout,
                    "store_tokens": store_tokens,
                },
            )

        try:
            # Start authorization and get device/user codes.
            # IMPORTANT: use device_init so auth.deviceLogin shares the same backing store
            # (PostgreSQL when configured), matching auth.devicePoll semantics.
            init_result = await self.device_init(
                client_id=client_id,
                scopes=scopes,
                poll_interval=poll_interval,
            )

            result: Dict[str, Any] = {
                "status": "pending",
                "device_code": init_result["device_code"],
                "user_code": init_result["user_code"],
                "verification_uri": init_result["verification_uri"],
                "verification_uri_complete": init_result.get("verification_uri_complete"),
                "expires_in": init_result.get("expires_in", timeout),
                "interval": init_result.get("interval", poll_interval),
            }

            # Best practice for MCP agents: return immediately and let the client poll.
            if not wait_for_authorization:
                return result

            # Optional legacy/blocking behavior: poll until authorization completes.
            deadline = time.monotonic() + timeout
            retry_after = int(result["interval"])

            while time.monotonic() < deadline:
                await asyncio.sleep(retry_after)

                poll_result = await self.device_poll(
                    device_code=result["device_code"],
                    client_id=client_id,
                    store_tokens=store_tokens,
                )
                status = str(poll_result.get("status", "error")).lower()

                if status == "pending":
                    continue

                result["status"] = status

                # Merge non-status fields from poll response.
                for key, value in poll_result.items():
                    if key != "status":
                        result[key] = value

                if status == "authorized":
                    if store_tokens:
                        store = self._get_token_store()
                        result["token_storage_path"] = self._get_storage_path_description(store)

                        if self._telemetry:
                            storage_type = type(store).__name__
                            self._telemetry.emit_event(
                                event_type="device_flow.mcp.tokens_stored",
                                payload={
                                    "client_id": client_id,
                                    "storage_type": storage_type,
                                },
                            )

                    if self._telemetry:
                        self._telemetry.emit_event(
                            event_type="device_flow.mcp.login_success",
                            payload={
                                "client_id": client_id,
                                "scopes": result.get("scopes", []),
                                "tokens_stored": store_tokens and "error" not in result,
                            },
                        )

                    return result

                if status == "denied":
                    if self._telemetry:
                        self._telemetry.emit_event(
                            event_type="device_flow.mcp.login_denied",
                            payload={
                                "client_id": client_id,
                                "reason": result.get("error_description", "User denied authorization"),
                            },
                        )
                    return result

                if status == "expired":
                    if self._telemetry:
                        self._telemetry.emit_event(
                            event_type="device_flow.mcp.login_expired",
                            payload={"client_id": client_id},
                        )
                    return result

                # Unknown or explicit error status - return as-is.
                return result

            # Timeout reached while still pending.
            result["status"] = "error"
            result["error"] = "authorization_pending"
            result["error_description"] = f"Timed out after {timeout}s waiting for user authorization"

            if self._telemetry:
                self._telemetry.emit_event(
                    event_type="device_flow.mcp.login_timeout",
                    payload={"client_id": client_id, "timeout": timeout},
                )

            return result

        except Exception as exc:
            error_result = {
                "status": "error",
                "error": "invalid_request",
                "error_description": str(exc),
            }

            if self._telemetry:
                self._telemetry.emit_event(
                    event_type="device_flow.mcp.login_error",
                    payload={"client_id": client_id, "error": str(exc)},
                )

            return error_result

    async def auth_status(
        self,
        *,
        client_id: str = "amprealize-mcp-client",
        validate_remote: bool = False,
    ) -> Dict[str, Any]:
        """
        Check current authentication status from stored tokens.

        Implements auth.authStatus MCP tool by reading from KeychainTokenStore
        and reporting token validity, expiry, and scopes.

        Args:
            client_id: OAuth client identifier to check tokens for
            validate_remote: Whether to validate with authorization server (not yet implemented)

        Returns:
            Dictionary with authentication status per auth.authStatus.json schema
        """
        try:
            store = self._get_token_store()
            bundle = await asyncio.wait_for(
                asyncio.to_thread(store.load),
                timeout=self._token_store_timeout_seconds(),
            )

            if bundle is None or bundle.client_id != client_id:
                return {
                    "is_authenticated": False,
                    "access_token_valid": False,
                    "refresh_token_valid": False,
                    "client_id": client_id,
                    "needs_login": True,
                }

            now = datetime.now(timezone.utc)
            access_token_valid = bundle.expires_at > now
            refresh_token_valid = bundle.refresh_expires_at > now

            result: Dict[str, Any] = {
                "is_authenticated": access_token_valid or refresh_token_valid,
                "access_token_valid": access_token_valid,
                "refresh_token_valid": refresh_token_valid,
                "client_id": bundle.client_id,
                "scopes": bundle.scopes,
                "expires_in": int((bundle.expires_at - now).total_seconds()),
                "expires_at": bundle.expires_at.isoformat(),
                "refresh_expires_in": int((bundle.refresh_expires_at - now).total_seconds()),
                "refresh_expires_at": bundle.refresh_expires_at.isoformat(),
                "token_storage_type": "keychain" if "keyring" in type(store).__module__ else "file",
                "token_storage_path": self._get_storage_path_description(store),
                "needs_refresh": not access_token_valid and refresh_token_valid,
                "needs_login": not access_token_valid and not refresh_token_valid,
            }

            if self._telemetry:
                self._telemetry.emit_event(
                    event_type="device_flow.mcp.status_checked",
                    payload={
                        "client_id": client_id,
                        "is_authenticated": result["is_authenticated"],
                        "needs_refresh": result["needs_refresh"],
                    },
                )

            return result

        except TokenStoreError as exc:
            return {
                "is_authenticated": False,
                "access_token_valid": False,
                "refresh_token_valid": False,
                "client_id": client_id,
                "needs_login": True,
                "error_description": str(exc),
            }
        except asyncio.TimeoutError:
            return {
                "is_authenticated": False,
                "access_token_valid": False,
                "refresh_token_valid": False,
                "client_id": client_id,
                "needs_login": True,
                "error_description": "Token store operation timed out",
            }

    async def refresh_token(
        self,
        *,
        client_id: str = "amprealize-mcp-client",
        store_tokens: bool = True,
    ) -> Dict[str, Any]:
        """
        Refresh an expired access token using stored refresh token.

        Implements auth.refreshToken MCP tool by reading refresh token from
        KeychainTokenStore, and refreshing via PostgresDeviceFlowStore (if available)
        or DeviceFlowManager (fallback).

        Args:
            client_id: OAuth client identifier to refresh tokens for
            store_tokens: Whether to persist refreshed tokens (recommended true)

        Returns:
            Dictionary with refresh status and new tokens per auth.refreshToken.json schema
        """
        try:
            store = self._get_token_store()
            bundle = await asyncio.wait_for(
                asyncio.to_thread(store.load),
                timeout=self._token_store_timeout_seconds(),
            )

            if bundle is None or bundle.client_id != client_id:
                return {
                    "status": "no_refresh_token",
                    "error_description": f"No stored tokens found for client_id={client_id}",
                }

            now = datetime.now(timezone.utc)
            if bundle.refresh_expires_at <= now:
                return {
                    "status": "invalid_token",
                    "error": "invalid_grant",
                    "error_description": "Refresh token has expired",
                }

            refresh_data: Optional[Dict[str, Any]] = None

            # Try PostgreSQL store first (tokens were likely issued there)
            if self._postgres_store:
                try:
                    session = await asyncio.wait_for(
                        asyncio.to_thread(
                            self._postgres_store.refresh_access_token,
                            bundle.refresh_token,
                        ),
                        timeout=self._db_call_timeout_seconds(),
                    )
                    if session and session.access_token:
                        refresh_data = {
                            "access_token": session.access_token,
                            "refresh_token": session.refresh_token,
                            "token_type": "Bearer",
                            "scopes": list(session.scopes),
                            "client_id": session.client_id,
                            "access_token_expires_at": session.access_token_expires_at.isoformat() if session.access_token_expires_at else None,
                            "refresh_token_expires_at": session.refresh_token_expires_at.isoformat() if session.refresh_token_expires_at else None,
                            "access_expires_in": int((session.access_token_expires_at - now).total_seconds()) if session.access_token_expires_at else 3600,
                            "refresh_expires_in": int((session.refresh_token_expires_at - now).total_seconds()) if session.refresh_token_expires_at else 604800,
                            # Include user info for session context population
                            "user_id": session.oauth_user_id or session.approver,
                            "email": session.oauth_email or session.approver,
                        }
                except asyncio.TimeoutError:
                    if self._telemetry:
                        self._telemetry.emit_event(
                            event_type="device_flow.mcp.db_timeout",
                            payload={"operation": "refresh_token", "client_id": client_id},
                        )
                except Exception as exc:
                    if self._telemetry:
                        self._telemetry.emit_event(
                            event_type="device_flow.mcp.db_fallback",
                            payload={"operation": "refresh_token", "client_id": client_id, "error": str(exc)},
                        )

            # Fallback to in-memory manager if postgres didn't work
            if refresh_data is None:
                try:
                    refresh_data = self._adapter.refresh(bundle.refresh_token)
                except Exception as fallback_exc:
                    return {
                        "status": "error",
                        "error": "invalid_request",
                        "error_description": str(fallback_exc),
                    }

            result: Dict[str, Any] = {
                "status": "refreshed",
                "access_token": refresh_data["access_token"],
                "refresh_token": refresh_data["refresh_token"],
                "token_type": refresh_data.get("token_type", "Bearer"),
                "scopes": refresh_data["scopes"],
                "expires_in": refresh_data.get("access_expires_in", 3600),
                "expires_at": refresh_data["access_token_expires_at"],
                "refresh_expires_at": refresh_data["refresh_token_expires_at"],
            }

            # Persist refreshed tokens
            if store_tokens:
                try:
                    new_bundle = AuthTokenBundle(
                        access_token=refresh_data["access_token"],
                        refresh_token=refresh_data["refresh_token"],
                        token_type=refresh_data.get("token_type", "Bearer"),
                        scopes=refresh_data["scopes"],
                        client_id=refresh_data.get("client_id", client_id),
                        issued_at=datetime.now(timezone.utc),
                        expires_at=datetime.fromisoformat(refresh_data["access_token_expires_at"]) if refresh_data.get("access_token_expires_at") else now + timedelta(hours=1),
                        refresh_expires_at=datetime.fromisoformat(refresh_data["refresh_token_expires_at"]) if refresh_data.get("refresh_token_expires_at") else bundle.refresh_expires_at,
                    )
                    await asyncio.wait_for(
                        asyncio.to_thread(store.save, new_bundle),
                        timeout=self._token_store_timeout_seconds(),
                    )
                    result["token_storage_path"] = self._get_storage_path_description(store)

                    if self._telemetry:
                        self._telemetry.emit_event(
                            event_type="device_flow.mcp.token_refreshed",
                            payload={
                                "client_id": client_id,
                                "storage_type": type(store).__name__,
                            },
                        )
                except TokenStoreError as exc:
                    result["error_description"] = f"Tokens refreshed but storage failed: {exc}"

            return result

        except TokenStoreError as exc:
            return {
                "status": "error",
                "error_description": str(exc),
            }
        except Exception as exc:
            return {
                "status": "error",
                "error": "invalid_request",
                "error_description": str(exc),
            }

    async def logout(
        self,
        *,
        client_id: str = "amprealize-mcp-client",
        revoke_remote: bool = True,
    ) -> Dict[str, Any]:
        """
        Revoke OAuth tokens and clear local storage.

        Implements auth.logout MCP tool by optionally revoking tokens with
        authorization server (RFC 7009), then clearing KeychainTokenStore.

        RFC 7009 Token Revocation:
        - Access tokens are revoked to prevent further API access
        - Refresh tokens are revoked to prevent new token issuance
        - Revocation is best-effort (graceful degradation on failure)

        Args:
            client_id: OAuth client identifier to logout from
            revoke_remote: Whether to revoke with server before clearing (recommended true)

        Returns:
            Dictionary with logout status per auth.logout.json schema
        """
        try:
            store = self._get_token_store()
            bundle = await asyncio.wait_for(
                asyncio.to_thread(store.load),
                timeout=self._token_store_timeout_seconds(),
            )

            warnings: List[str] = []
            access_revoked = False
            refresh_revoked = False

            # Revoke with server if requested and tokens exist
            if revoke_remote and bundle and bundle.client_id == client_id:
                provider_name = getattr(bundle, 'provider', 'github')

                try:
                    # Get provider for remote revocation
                    provider = await self._get_oauth_provider(provider_name)

                    if provider:
                        # RFC 7009: Revoke access token first
                        if bundle.access_token:
                            try:
                                await provider.revoke_token(bundle.access_token)
                                access_revoked = True
                            except Exception as e:
                                warnings.append(f"Access token revocation failed: {e}")

                        # RFC 7009: Revoke refresh token
                        if bundle.refresh_token:
                            try:
                                await provider.revoke_token(bundle.refresh_token)
                                refresh_revoked = True
                            except Exception as e:
                                warnings.append(f"Refresh token revocation failed: {e}")

                        # Clean up provider resources
                        if hasattr(provider, 'close'):
                            await provider.close()
                    else:
                        warnings.append(f"Provider '{provider_name}' not available for remote revocation")

                except ValueError as e:
                    # Provider credentials not configured
                    warnings.append(f"Remote revocation skipped: {e}")
                except Exception as e:
                    warnings.append(f"Remote revocation error: {e}")

            # Clear local token storage
            tokens_cleared = False
            if bundle and bundle.client_id == client_id:
                store.clear()
                tokens_cleared = True

                if self._telemetry:
                    self._telemetry.emit_event(
                        event_type="device_flow.mcp.logout",
                        payload={
                            "client_id": client_id,
                            "tokens_cleared": True,
                            "remote_revocation_attempted": revoke_remote,
                            "access_token_revoked": access_revoked,
                            "refresh_token_revoked": refresh_revoked,
                        },
                    )

            # Determine status based on results
            if tokens_cleared:
                if revoke_remote and warnings:
                    status = "partial_revocation"
                else:
                    status = "logged_out"
            else:
                status = "no_tokens"

            result: Dict[str, Any] = {
                "status": status,
                "tokens_cleared": tokens_cleared,
                "access_token_revoked": access_revoked,
                "refresh_token_revoked": refresh_revoked,
                "token_storage_path": self._get_storage_path_description(store),
            }

            if warnings:
                result["warnings"] = warnings

            return result

        except TokenStoreError as exc:
            return {
                "status": "error",
                "tokens_cleared": False,
                "access_token_revoked": False,
                "refresh_token_revoked": False,
                "error_description": str(exc),
            }

    async def _get_oauth_provider(self, provider_name: str) -> Optional[OAuthProvider]:
        """
        Get OAuth provider instance for token revocation.

        Args:
            provider_name: Provider name (github, google, internal)

        Returns:
            OAuthProvider instance or None if not available

        Raises:
            ValueError: If provider credentials not configured
        """
        try:
            return ProviderRegistry.create_provider(provider_name)
        except ValueError:
            # Credentials not available - this is expected in some environments
            return None

    @staticmethod
    def _get_storage_path_description(store: TokenStore) -> str:
        """Get human-readable description of token storage location."""
        store_type = type(store).__name__
        if "Keychain" in store_type:
            return f"keychain:amprealize-{sys.platform}"
        elif "File" in store_type:
            # Try to get file path from store
            if hasattr(store, "_path"):
                return str(store._path)
            return "~/.amprealize/tokens.json"
        return f"unknown:{store_type}"


class MCPDeviceFlowHandler:
    """
    MCP tool call dispatcher for device flow authentication.

    Routes MCP tool calls (auth.deviceLogin, auth.authStatus, etc.)
    to MCPDeviceFlowService methods and handles JSON-RPC protocol.

    This is the integration point for MCP server stdio implementations.
    """

    def __init__(self, service: Optional[MCPDeviceFlowService] = None) -> None:
        """
        Initialize MCP device flow handler.

        Args:
            service: MCPDeviceFlowService instance (creates default if None)
        """
        self._service = service or MCPDeviceFlowService()

    async def handle_tool_call(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle MCP tool call for device flow authentication.

        Args:
            tool_name: MCP tool name (auth.deviceLogin, auth.authStatus, etc.)
            params: Tool parameters from MCP client

        Returns:
            Tool result per corresponding JSON schema

        Raises:
            ValueError: If tool_name is not recognized
        """
        if tool_name == "auth.deviceLogin":
            return await self._service.device_login(
                client_id=params.get("client_id", "amprealize-mcp-client"),
                scopes=params.get("scopes"),
                poll_interval=params.get("poll_interval", 5),
                timeout=params.get("timeout", 300),
                store_tokens=params.get("store_tokens", True),
                wait_for_authorization=params.get("wait_for_authorization", False),
            )

        elif tool_name == "auth.deviceInit":
            return await self._service.device_init(
                client_id=params.get("client_id", "amprealize-mcp-client"),
                scopes=params.get("scopes"),
                poll_interval=params.get("poll_interval", 5),
            )

        elif tool_name == "auth.devicePoll":
            return await self._service.device_poll(
                device_code=params.get("device_code"),
                client_id=params.get("client_id", "amprealize-mcp-client"),
                store_tokens=params.get("store_tokens", True),
            )

        elif tool_name == "auth.authStatus" or tool_name == "auth.devicePoll" or tool_name == "device_poll":
            return await self._service.auth_status(
                client_id=params.get("client_id", "amprealize-mcp-client"),
                validate_remote=params.get("validate_remote", False),
            )

        elif tool_name == "auth.refreshToken" or tool_name == "auth.refresh":
            return await self._service.refresh_token(
                client_id=params.get("client_id", "amprealize-mcp-client"),
                store_tokens=params.get("store_tokens", True),
            )

        elif tool_name == "auth.logout":
            return await self._service.logout(
                client_id=params.get("client_id", "amprealize-mcp-client"),
                revoke_remote=params.get("revoke_remote", True),
            )

        elif tool_name == "auth.ensureGrant":
            # Policy-based authorization check
            if not self._service._agent_auth_service:
                # Fallback to stub response if service not configured
                return {
                    "decision": "ALLOW",
                    "reason": "Policy enforcement not configured - allowing by default",
                    "grant": {
                        "grant_id": f"stub-grant-{params.get('agent_id', 'unknown')}",
                        "scopes": params.get("scopes", []),
                        "provider": "stub",
                    },
                    "audit_action_id": None,
                }

            # Build request from params
            request = EnsureGrantRequest(
                agent_id=params.get("agent_id", "unknown"),
                surface="MCP",
                tool_name=params.get("tool_name", "unknown"),
                scopes=params.get("scopes", []),
                user_id=params.get("user_id"),
                context=params.get("context", {}),
            )

            # Call service
            response = self._service._agent_auth_service.ensure_grant(request)

            # Map to MCP response format
            result: Dict[str, Any] = {
                "decision": response.decision.value,
                "audit_action_id": response.audit_action_id,
            }

            if response.reason:
                result["reason"] = response.reason.value

            if response.consent_url:
                result["consent_url"] = response.consent_url
                result["consent_request_id"] = response.consent_request_id

            if response.grant:
                result["grant"] = {
                    "grant_id": response.grant.grant_id,
                    "agent_id": response.grant.agent_id,
                    "user_id": response.grant.user_id,
                    "tool_name": response.grant.tool_name,
                    "scopes": response.grant.scopes,
                    "provider": response.grant.provider,
                    "issued_at": response.grant.issued_at,
                    "expires_at": response.grant.expires_at,
                    "obligations": [
                        {"type": ob.type, "attributes": ob.attributes}
                        for ob in response.grant.obligations
                    ],
                }

            return result

        elif tool_name == "auth.listGrants":
            # List active grants for an agent
            if not self._service._agent_auth_service:
                return {"grants": []}

            # agent_id is required
            agent_id = params.get("agent_id")
            if not agent_id:
                return {"grants": [], "error": "agent_id required"}

            # Build request from params
            request = ListGrantsRequest(
                agent_id=agent_id,
                user_id=params.get("user_id"),
                tool_name=params.get("tool_name"),
                include_expired=params.get("include_expired", False),
            )

            # Call service
            grants = self._service._agent_auth_service.list_grants(request)

            # Map to MCP response format
            return {
                "grants": [
                    {
                        "grant_id": g.grant_id,
                        "agent_id": g.agent_id,
                        "user_id": g.user_id,
                        "tool_name": g.tool_name,
                        "scopes": g.scopes,
                        "provider": g.provider,
                        "issued_at": g.issued_at,
                        "expires_at": g.expires_at,
                        "obligations": [
                            {"type": ob.type, "attributes": ob.attributes}
                            for ob in g.obligations
                        ],
                    }
                    for g in grants
                ]
            }

        elif tool_name == "auth.policy.preview":
            # Preview policy decision without creating grant
            if not self._service._agent_auth_service:
                return {
                    "decision": "ALLOW",
                    "reason": "Policy enforcement not configured - allowing by default",
                    "bundle_version": None,
                    "obligations": [],
                }

            # Build request from params
            request = PolicyPreviewRequest(
                agent_id=params.get("agent_id", "unknown"),
                tool_name=params.get("tool_name", "unknown"),
                scopes=params.get("scopes", []),
                user_id=params.get("user_id"),
                context=params.get("context", {}),
                bundle_version=params.get("bundle_version"),
            )

            # Call service
            response = self._service._agent_auth_service.policy_preview(request)

            # Map to MCP response format
            result: Dict[str, Any] = {
                "decision": response.decision.value,
                "bundle_version": response.bundle_version,
                "obligations": [
                    {"type": ob.type, "attributes": ob.attributes}
                    for ob in response.obligations
                ],
            }

            if response.reason:
                result["reason"] = response.reason.value

            return result

        elif tool_name == "auth.revoke":
            # Revoke a grant
            if not self._service._agent_auth_service:
                grant_id = params.get("grant_id")
                return {
                    "grant_id": grant_id,
                    "success": True,
                    "reason": "Policy enforcement not configured - stub revocation",
                }

            # Build request from params
            grant_id = params.get("grant_id")
            if not grant_id:
                return {
                    "success": False,
                    "reason": "grant_id required",
                }

            request = RevokeGrantRequest(
                grant_id=grant_id,
                revoked_by=params.get("revoked_by", "MCP"),
                reason=params.get("reason"),
            )

            # Call service
            response = self._service._agent_auth_service.revoke_grant(request)

            # Map to MCP response format
            result: Dict[str, Any] = {
                "grant_id": response.grant_id,
                "success": response.success,
            }

            if response.reason:
                result["reason"] = response.reason.value

            return result

        elif tool_name == "auth.consentLookup" or tool_name == "consent.lookup":
            # Lookup consent request details by user code
            user_code = params.get("user_code")
            if not user_code:
                return {"error": "user_code required"}

            try:
                session_data = self._service._adapter.lookup_user_code(user_code)
                return {
                    "user_code": session_data["user_code"],
                    "status": session_data["status"],
                    "client_id": session_data["client_id"],
                    "scopes": session_data["scopes"],
                    "surface": session_data["surface"],
                    "created_at": session_data["created_at"],
                    "expires_at": session_data["expires_at"],
                    "verification_uri": session_data["verification_uri"],
                    "verification_uri_complete": session_data.get("verification_uri_complete"),
                    "approved_at": session_data.get("approved_at"),
                    "denied_at": session_data.get("denied_at"),
                    "denied_reason": session_data.get("denied_reason"),
                }
            except ValueError as e:
                return {"error": str(e)}
            except Exception as e:
                return {"error": f"Consent lookup failed: {str(e)}"}

        elif tool_name == "auth.consentApprove" or tool_name == "consent.approve":
            # Approve a consent request via user code
            user_code = params.get("user_code")
            approver = params.get("approver")
            if not user_code:
                return {"success": False, "error": "user_code required"}
            if not approver:
                return {"success": False, "error": "approver required"}

            try:
                session_data = self._service._adapter.approve(
                    user_code=user_code,
                    approver=approver,
                    roles=params.get("roles"),
                    mfa_verified=params.get("mfa_verified", False),
                )
                return {
                    "success": True,
                    "user_code": session_data["user_code"],
                    "status": session_data["status"],
                    "scopes": session_data["scopes"],
                    "approved_at": session_data.get("approved_at"),
                }
            except ValueError as e:
                return {"success": False, "error": str(e)}
            except Exception as e:
                return {"success": False, "error": f"Consent approval failed: {str(e)}"}

        elif tool_name == "auth.consentDeny" or tool_name == "consent.deny":
            # Deny a consent request via user code
            user_code = params.get("user_code")
            approver = params.get("approver")
            if not user_code:
                return {"success": False, "error": "user_code required"}
            if not approver:
                return {"success": False, "error": "approver required"}

            try:
                session_data = self._service._adapter.deny(
                    user_code=user_code,
                    approver=approver,
                    reason=params.get("reason"),
                )
                return {
                    "success": True,
                    "user_code": session_data["user_code"],
                    "status": session_data["status"],
                    "denied_at": session_data.get("denied_at"),
                    "denied_reason": session_data.get("denied_reason"),
                }
            except ValueError as e:
                return {"success": False, "error": str(e)}
            except Exception as e:
                return {"success": False, "error": f"Consent denial failed: {str(e)}"}

        else:
            raise ValueError(f"Unknown MCP tool: {tool_name}")
