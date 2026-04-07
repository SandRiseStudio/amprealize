"""
FastAPI authentication middleware for RBAC.

Provides middleware and dependency functions for:
- JWT validation and user extraction
- Permission service injection into request state
- Multi-tenant context (org_id, project_id) resolution

Behavior: behavior_lock_down_security_surface
"""

from __future__ import annotations

import os
from typing import Optional, Annotated

from fastapi import Request, HTTPException, Header, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt

from amprealize.auth.jwt_service import JWTService


# Security scheme for Swagger docs
security_scheme = HTTPBearer(auto_error=False)


class AuthConfig:
    """Configuration for auth middleware."""

    def __init__(
        self,
        jwt_secret: Optional[str] = None,
        jwt_algorithm: str = "HS256",
        auth_dsn: Optional[str] = None,
        skip_paths: Optional[set] = None,
        auth_required: bool = False,
    ):
        """Initialize auth configuration.

        Args:
            jwt_secret: Secret key for JWT validation. Falls back to AMPREALIZE_JWT_SECRET env var.
            jwt_algorithm: JWT algorithm (default: HS256).
            auth_dsn: PostgreSQL DSN for AsyncPermissionService. Falls back to AMPREALIZE_AUTH_PG_DSN.
            skip_paths: Paths to skip authentication (e.g., health checks).
            auth_required: If True, reject unauthenticated requests with 401 on non-skip paths.
        """
        self.jwt_secret = jwt_secret or os.getenv("AMPREALIZE_JWT_SECRET")
        self.jwt_algorithm = jwt_algorithm
        self.auth_dsn = auth_dsn or os.getenv("AMPREALIZE_AUTH_PG_DSN")
        self.skip_paths = skip_paths or {"/health", "/health/", "/metrics", "/docs", "/openapi.json"}
        self.auth_required = auth_required

        if not self.jwt_secret:
            # Generate a random secret if not provided (development mode)
            import secrets
            self.jwt_secret = secrets.token_urlsafe(32)


class AuthMiddleware:
    """FastAPI middleware for JWT and device flow token authentication.

    Validates JWT tokens from Authorization header and populates request.state with:
    - user_id: User ID from token subject
    - username: Username from token claims
    - token_claims: Full decoded token payload

    Also supports Amprealize device flow tokens (ga_* prefix) via DeviceFlowManager.

    Usage:
        from amprealize.auth.middleware import AuthMiddleware, AuthConfig

        config = AuthConfig()
        app.add_middleware(AuthMiddleware, config=config)
    """

    def __init__(self, app, config: Optional[AuthConfig] = None, device_flow_manager=None):
        """Initialize auth middleware.

        Args:
            app: FastAPI application instance.
            config: AuthConfig instance. Uses defaults if not provided.
            device_flow_manager: Optional DeviceFlowManager for ga_* token validation.
        """
        self.app = app
        self.config = config or AuthConfig()
        self.device_flow_manager = device_flow_manager
        self.jwt_service = JWTService(
            secret_key=self.config.jwt_secret,
            algorithm=self.config.jwt_algorithm,
        )

    async def __call__(self, scope, receive, send):
        """Process request and validate authentication."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Build request to access path and headers
        request = Request(scope, receive)
        path = request.url.path

        # Determine if this is a skip (public) path — auth not enforced but tokens still parsed
        is_skip_path = path in self.config.skip_paths or any(
            path.startswith(p.rstrip('/')) for p in self.config.skip_paths
        )

        # Extract and validate token
        auth_header = request.headers.get("Authorization")
        user_info = None
        rejection_reason = None

        import logging
        logger = logging.getLogger("amprealize.auth.middleware")

        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]
            logger.info(f"AuthMiddleware: Processing token prefix: {token[:20]}...")

            # Check for Amprealize device flow tokens (ga_* prefix) first
            if token.startswith("ga_") and self.device_flow_manager:
                logger.info(f"AuthMiddleware: Validating ga_* token via device_flow_manager")
                df_user_info = self.device_flow_manager.get_user_info_from_access_token(token)
                logger.info(f"AuthMiddleware: device_flow_manager returned: {df_user_info}")
                if df_user_info:
                    user_info = {
                        "user_id": df_user_info.get("sub"),
                        "username": df_user_info.get("name") or df_user_info.get("email"),
                        "claims": df_user_info,
                    }
                    logger.info(f"AuthMiddleware: Set user_id={user_info['user_id']}")
                else:
                    rejection_reason = "Invalid device flow token"

            # Fall back to JWT validation (skip if device flow already gave a definitive rejection)
            if user_info is None and rejection_reason is None:
                try:
                    payload = self.jwt_service.validate_token(token, expected_type="access")
                    user_info = {
                        "user_id": payload.get("sub"),
                        "username": payload.get("username"),
                        "claims": payload,
                    }
                except jwt.ExpiredSignatureError:
                    user_info = None
                    rejection_reason = "Token expired"
                except jwt.InvalidTokenError:
                    user_info = None
                    rejection_reason = "Invalid token"
                except ValueError:
                    user_info = None
                    rejection_reason = "Invalid token"
        elif auth_header:
            rejection_reason = "Invalid authorization format"
        else:
            rejection_reason = "Authorization header missing"

        # Enforce authentication if required and not a skip path
        if self.config.auth_required and not is_skip_path and user_info is None:
            from starlette.responses import JSONResponse
            detail = rejection_reason or "Authentication required"
            response = JSONResponse(
                status_code=401,
                content={"detail": detail},
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return
        elif user_info is None and auth_header:
            logger.warning("Auth failed (non-enforcing): %s", rejection_reason)

        # Store user info in scope state for downstream access
        scope["state"] = scope.get("state", {})
        if user_info:
            scope["state"]["user_id"] = user_info["user_id"]
            scope["state"]["username"] = user_info["username"]
            scope["state"]["token_claims"] = user_info["claims"]
            scope["state"]["org_id"] = user_info["claims"].get("org_id")
        else:
            scope["state"]["user_id"] = None
            scope["state"]["username"] = None
            scope["state"]["token_claims"] = None
            scope["state"]["org_id"] = None

        await self.app(scope, receive, send)


async def get_current_user(
    request: Request,
    authorization: Annotated[Optional[HTTPAuthorizationCredentials], security_scheme] = None,
) -> dict:
    """FastAPI dependency to get the current authenticated user.

    Extracts user from request.state populated by AuthMiddleware, or validates
    the Authorization header directly if middleware wasn't used.

    Args:
        request: FastAPI request object.
        authorization: Optional HTTP authorization credentials.

    Returns:
        Dictionary with user_id, username, and claims.

    Raises:
        HTTPException: 401 if not authenticated.

    Usage:
        from amprealize.auth.middleware import get_current_user

        @app.get("/me")
        async def get_profile(user: dict = Depends(get_current_user)):
            return {"user_id": user["user_id"]}
    """
    # Check if user was already set by middleware
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return {
            "user_id": user_id,
            "username": getattr(request.state, "username", None),
            "claims": getattr(request.state, "token_claims", {}),
        }

    # Fallback: validate authorization header directly
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    jwt_service = JWTService()
    try:
        payload = jwt_service.validate_token(authorization.credentials, expected_type="access")
        return {
            "user_id": payload.get("sub"),
            "username": payload.get("username"),
            "claims": payload,
        }
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def get_current_user_optional(
    request: Request,
    authorization: Annotated[Optional[HTTPAuthorizationCredentials], security_scheme] = None,
) -> Optional[dict]:
    """FastAPI dependency to optionally get the current user.

    Like get_current_user but returns None instead of raising if not authenticated.
    Useful for endpoints that work with or without authentication.

    Args:
        request: FastAPI request object.
        authorization: Optional HTTP authorization credentials.

    Returns:
        User dictionary or None if not authenticated.
    """
    try:
        return await get_current_user(request, authorization)
    except HTTPException:
        return None


def get_org_context(
    request: Request,
    org_id: Optional[str] = Header(None, alias="X-Org-ID"),
) -> Optional[str]:
    """Extract organization context from request header.

    Args:
        request: FastAPI request object.
        org_id: Organization ID from X-Org-ID header.

    Returns:
        Organization ID or None.
    """
    # Check header first, then request state
    if org_id:
        return org_id
    return getattr(request.state, "org_id", None)


def get_project_context(
    request: Request,
    project_id: Optional[str] = Header(None, alias="X-Project-ID"),
) -> Optional[str]:
    """Extract project context from request header.

    Args:
        request: FastAPI request object.
        project_id: Project ID from X-Project-ID header.

    Returns:
        Project ID or None.
    """
    # Check header first, then request state
    if project_id:
        return project_id
    return getattr(request.state, "project_id", None)


async def require_org_context(
    request: Request,
    org_id: Optional[str] = Header(None, alias="X-Org-ID"),
) -> str:
    """Require organization context - raises if not provided.

    Args:
        request: FastAPI request object.
        org_id: Organization ID from X-Org-ID header.

    Returns:
        Organization ID.

    Raises:
        HTTPException: 400 if organization context not provided.
    """
    result = get_org_context(request, org_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization context required (set X-Org-ID header)",
        )
    return result


async def require_project_context(
    request: Request,
    project_id: Optional[str] = Header(None, alias="X-Project-ID"),
) -> str:
    """Require project context - raises if not provided.

    Args:
        request: FastAPI request object.
        project_id: Project ID from X-Project-ID header.

    Returns:
        Project ID.

    Raises:
        HTTPException: 400 if project context not provided.
    """
    result = get_project_context(request, project_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Project context required (set X-Project-ID header)",
        )
    return result


# Type alias for dependency injection
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from amprealize.multi_tenant.permissions import AsyncPermissionService


async def get_permission_service(request: Request) -> "AsyncPermissionService":
    """Get AsyncPermissionService from app state.

    The service should be initialized and stored in app.state during app startup.

    Args:
        request: FastAPI request object.

    Returns:
        AsyncPermissionService instance.

    Raises:
        HTTPException: 500 if service not configured.
    """
    perm_service = getattr(request.app.state, "async_permission_service", None)
    if perm_service is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Permission service not configured",
        )
    return perm_service


# =============================================================================
# Permission-Checking Dependency Factories
# =============================================================================

def require_org_permission_dep(permission_name: str):
    """Create a FastAPI dependency that requires an organization permission.

    This dependency factory creates a function that can be used with Depends()
    to require the current user has a specific permission in the org specified
    by the X-Org-ID header.

    Args:
        permission_name: Name of OrgPermission (e.g., "VIEW_MEMBERS", "MANAGE_BILLING").

    Returns:
        Async dependency function.

    Usage:
        from amprealize.auth.middleware import require_org_permission_dep

        @app.get("/v1/org/members")
        async def list_members(
            user: dict = Depends(get_current_user),
            _perm: None = Depends(require_org_permission_dep("VIEW_MEMBERS")),
        ):
            # User is authenticated and has VIEW_MEMBERS permission in org
            pass
    """
    async def dependency(
        request: Request,
        user: dict = None,  # Will be injected if get_current_user is also a dependency
        org_id: Optional[str] = Header(None, alias="X-Org-ID"),
    ) -> None:
        from amprealize.multi_tenant.permissions import OrgPermission, NotAMember, PermissionDenied

        # Get user from request state if not injected
        user_id = getattr(request.state, "user_id", None)
        if not user_id and user:
            user_id = user.get("user_id")

        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not org_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Organization context required (set X-Org-ID header)",
            )

        # Get permission service
        perm_service = getattr(request.app.state, "async_permission_service", None)
        if perm_service is None:
            # Permission service not configured - allow request in development
            import os
            if os.getenv("AMPREALIZE_AUTH_STRICT", "").lower() in ("true", "1", "yes"):
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Permission service not configured",
                )
            return None

        # Resolve permission enum
        try:
            permission = OrgPermission[permission_name]
        except KeyError:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Unknown permission: {permission_name}",
            )

        # Check permission
        try:
            await perm_service.require_org_permission(user_id, org_id, permission)
        except NotAMember:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found",
            )
        except PermissionDenied as e:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(e),
            )

        return None

    return dependency


def require_project_permission_dep(permission_name: str):
    """Create a FastAPI dependency that requires a project permission.

    Args:
        permission_name: Name of ProjectPermission (e.g., "VIEW_RUNS", "EXECUTE_ACTIONS").

    Returns:
        Async dependency function.

    Usage:
        @app.get("/v1/project/runs")
        async def list_runs(
            user: dict = Depends(get_current_user),
            _perm: None = Depends(require_project_permission_dep("VIEW_RUNS")),
        ):
            pass
    """
    async def dependency(
        request: Request,
        user: dict = None,
        project_id: Optional[str] = Header(None, alias="X-Project-ID"),
    ) -> None:
        from amprealize.multi_tenant.permissions import ProjectPermission, NotAMember, PermissionDenied

        # Get user from request state if not injected
        user_id = getattr(request.state, "user_id", None)
        if not user_id and user:
            user_id = user.get("user_id")

        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Project context required (set X-Project-ID header)",
            )

        # Get permission service
        perm_service = getattr(request.app.state, "async_permission_service", None)
        if perm_service is None:
            import os
            if os.getenv("AMPREALIZE_AUTH_STRICT", "").lower() in ("true", "1", "yes"):
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Permission service not configured",
                )
            return None

        # Resolve permission enum
        try:
            permission = ProjectPermission[permission_name]
        except KeyError:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Unknown permission: {permission_name}",
            )

        # Check permission
        try:
            await perm_service.require_project_permission(user_id, project_id, permission)
        except NotAMember:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )
        except PermissionDenied as e:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(e),
            )

        return None

    return dependency


__all__ = [
    "AuthConfig",
    "AuthMiddleware",
    "get_current_user",
    "get_current_user_optional",
    "get_org_context",
    "get_project_context",
    "require_org_context",
    "require_project_context",
    "get_permission_service",
    "require_org_permission_dep",
    "require_project_permission_dep",
    "security_scheme",
]
