"""
MCP Authorization Middleware

Phase 3: MCP_AUTH_IMPLEMENTATION_PLAN.md

Enforces scope-based authorization before tool dispatch.
Supports both human users (via AgentAuthService) and service principals (via pre-granted scopes).

Note: org_id is OPTIONAL - users can use Amprealize without an organization,
and projects can exist independently of orgs.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Dict, List, Optional, Set
import logging

if TYPE_CHECKING:
    from .mcp_server import MCPSessionContext
    from .services.agent_auth_service import AgentAuthService


class AuthDecision(Enum):
    """Authorization decision types."""
    ALLOW = "allow"
    DENY = "deny"
    CONSENT_REQUIRED = "consent_required"


@dataclass
class AuthResult:
    """Result of an authorization check.

    Attributes:
        decision: The authorization decision
        reason: Human-readable explanation (for DENY)
        consent_url: URL for user to grant consent (for CONSENT_REQUIRED)
        required_scopes: Scopes the tool requires
        granted_scopes: Scopes the user/SP has
        missing_scopes: Scopes required but not granted
    """
    decision: AuthDecision
    reason: Optional[str] = None
    consent_url: Optional[str] = None
    required_scopes: List[str] = field(default_factory=list)
    granted_scopes: List[str] = field(default_factory=list)
    missing_scopes: List[str] = field(default_factory=list)


class MCPAuthMiddleware:
    """
    Middleware for MCP tool authorization.

    Checks if the current session is authorized to call a tool based on:
    1. Tool's required_scopes (from manifest)
    2. Session's granted_scopes (from auth)

    For service principals: Direct scope comparison
    For human users: May trigger consent flow if scopes not yet granted

    Note: org_id is optional - authorization works for users without orgs.
    """

    def __init__(
        self,
        tool_scopes: Dict[str, List[str]],
        auth_service: Optional["AgentAuthService"] = None,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize authorization middleware.

        Args:
            tool_scopes: Map of tool_name -> required_scopes
            auth_service: Optional AgentAuthService for consent flows (human users)
            logger: Optional logger instance
        """
        self._tool_scopes = tool_scopes
        self._auth_service = auth_service
        self._logger = logger or logging.getLogger(__name__)

    async def authorize(
        self,
        tool_name: str,
        session: "MCPSessionContext",
        tool_params: Optional[Dict] = None,
    ) -> AuthResult:
        """
        Check if the current session is authorized to call the tool.

        Args:
            tool_name: MCP tool being invoked (normalized name)
            session: Current authenticated session
            tool_params: Tool parameters (for future resource-level checks)

        Returns:
            AuthResult with decision and context
        """
        required_scopes = self._tool_scopes.get(tool_name, [])

        # No scopes required = tool is open to authenticated users
        if not required_scopes:
            self._logger.debug(f"Tool {tool_name} has no required_scopes, allowing")
            return AuthResult(
                decision=AuthDecision.ALLOW,
                granted_scopes=list(session.granted_scopes),
            )

        # Check if session has all required scopes
        missing = session.missing_scopes(required_scopes)

        if not missing:
            # All scopes granted
            self._logger.debug(
                f"Tool {tool_name} authorized: "
                f"required={required_scopes}, granted={session.granted_scopes}"
            )
            return AuthResult(
                decision=AuthDecision.ALLOW,
                required_scopes=required_scopes,
                granted_scopes=list(session.granted_scopes),
            )

        # Missing scopes - determine response based on auth method
        if session.auth_method == "client_credentials":
            # Service principals cannot acquire new scopes at runtime
            # They must be pre-configured with allowed_scopes
            self._logger.warning(
                f"Service principal {session.service_principal_id} denied access to {tool_name}: "
                f"missing scopes {missing}"
            )
            return AuthResult(
                decision=AuthDecision.DENY,
                reason=f"Service principal lacks required scopes: {', '.join(sorted(missing))}",
                required_scopes=required_scopes,
                granted_scopes=list(session.granted_scopes),
                missing_scopes=list(missing),
            )

        # Human user - could trigger consent flow
        if self._auth_service:
            # Try to acquire consent via AgentAuthService
            consent_result = await self._request_consent(
                session=session,
                tool_name=tool_name,
                required_scopes=required_scopes,
                tool_params=tool_params,
            )
            return consent_result

        # No auth service available - deny with missing scopes
        self._logger.warning(
            f"User {session.user_id} denied access to {tool_name}: "
            f"missing scopes {missing}, no consent service available"
        )
        return AuthResult(
            decision=AuthDecision.DENY,
            reason=f"Missing required scopes: {', '.join(sorted(missing))}",
            required_scopes=required_scopes,
            granted_scopes=list(session.granted_scopes),
            missing_scopes=list(missing),
        )

    async def _request_consent(
        self,
        session: "MCPSessionContext",
        tool_name: str,
        required_scopes: List[str],
        tool_params: Optional[Dict] = None,
    ) -> AuthResult:
        """
        Request consent from user via AgentAuthService.

        This triggers the consent UX flow (Phase 6) where user can grant
        additional scopes.

        Args:
            session: Current session
            tool_name: Tool requesting scopes
            required_scopes: Scopes to request
            tool_params: Tool parameters for context

        Returns:
            AuthResult with CONSENT_REQUIRED or DENY
        """
        try:
            # Note: org_id is optional - user may not be in an org
            grant_result = await self._auth_service.ensure_grant(
                user_id=session.user_id,
                agent_id="mcp_server",  # MCP server as requesting agent
                tool_name=tool_name,
                scopes=required_scopes,
                context={
                    "org_id": session.org_id,  # May be None
                    "project_id": session.project_id,  # May be None
                    "params": tool_params or {},
                    "auth_method": session.auth_method,
                },
            )

            if grant_result.decision == "ALLOW":
                # User already granted these scopes
                return AuthResult(
                    decision=AuthDecision.ALLOW,
                    required_scopes=required_scopes,
                    granted_scopes=grant_result.granted_scopes,
                )
            elif grant_result.decision == "CONSENT_REQUIRED":
                # User needs to visit consent URL
                return AuthResult(
                    decision=AuthDecision.CONSENT_REQUIRED,
                    consent_url=grant_result.consent_url,
                    required_scopes=required_scopes,
                    missing_scopes=list(session.missing_scopes(required_scopes)),
                )
            else:
                # DENY or other
                return AuthResult(
                    decision=AuthDecision.DENY,
                    reason=grant_result.reason or "Access denied by policy",
                    required_scopes=required_scopes,
                    granted_scopes=list(session.granted_scopes),
                    missing_scopes=list(session.missing_scopes(required_scopes)),
                )

        except Exception as e:
            self._logger.error(f"Consent request failed: {e}", exc_info=True)
            return AuthResult(
                decision=AuthDecision.DENY,
                reason=f"Consent service error: {str(e)}",
                required_scopes=required_scopes,
            )

    def get_tool_scopes(self, tool_name: str) -> List[str]:
        """Get required scopes for a tool.

        Args:
            tool_name: Normalized tool name

        Returns:
            List of required scopes (empty if none required)
        """
        return self._tool_scopes.get(tool_name, [])

    def get_all_scopes(self) -> Set[str]:
        """Get all unique scopes across all tools.

        Returns:
            Set of all scope names
        """
        all_scopes = set()
        for scopes in self._tool_scopes.values():
            all_scopes.update(scopes)
        return all_scopes
