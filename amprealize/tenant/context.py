"""Tenant context management for Row-Level Security (RLS).

This module provides request-scoped tenant isolation by setting the
PostgreSQL session variable `app.current_org_id` which RLS policies use
to filter data automatically.

Behavior: behavior_migrate_postgres_schema (tenant context middleware)

Usage:
    # As async context manager (recommended)
    async with TenantContext(pool, org_id="org-123"):
        # All queries within this block are scoped to org-123
        results = await pool.fetch("SELECT * FROM behaviors")

    # Manual management (for middleware)
    ctx = TenantContext(pool, org_id="org-123")
    await ctx.activate()
    try:
        # ... handle request ...
    finally:
        await ctx.deactivate()

Tenant Resolution Priority (TenantMiddleware):
    1. Auth context (organization from authenticated user's JWT claims)
    2. X-Tenant-ID header (explicit tenant selection)
    3. X-Tenant-Slug header (resolved to ID via cache/DB)
    4. Subdomain parsing (e.g., acme.amprealize.dev -> "acme")
    5. Path parameter (e.g., /api/v1/tenants/{tenant_slug}/...)
"""

from __future__ import annotations

import contextvars
import re
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Set, Tuple
from dataclasses import dataclass, field
from urllib.parse import urlparse

if TYPE_CHECKING:
    from amprealize.storage.postgres_pool import PostgresPool

# Context variables for tracking tenant info in async context
_current_org_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_org_id", default=None
)
_current_tenant_slug: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_tenant_slug", default=None
)

# Default TTL for slug->org_id cache (5 minutes)
DEFAULT_SLUG_CACHE_TTL = 300

# Subdomain regex pattern (captures first subdomain before domain)
# Handles: acme.amprealize.dev, acme.localhost, etc.
SUBDOMAIN_PATTERN = re.compile(r"^([a-z0-9][-a-z0-9]*[a-z0-9]?)\.(?!localhost).*$", re.IGNORECASE)

# Path tenant pattern (captures tenant slug from URL path)
# Matches: /api/v1/tenants/{slug}/..., /t/{slug}/..., /org/{slug}/...
PATH_TENANT_PATTERN = re.compile(r"/(?:tenants?|t|org)/([a-z0-9][-a-z0-9]*)/", re.IGNORECASE)


def get_current_org_id() -> Optional[str]:
    """Get the current organization ID from async context.

    Returns:
        The current org_id if set, None otherwise.
    """
    return _current_org_id.get()


def get_current_tenant_slug() -> Optional[str]:
    """Get the current tenant slug from async context.

    Returns:
        The current tenant slug if set, None otherwise.
    """
    return _current_tenant_slug.get()


def require_org_context() -> str:
    """Get current org_id, raising if not set.

    Returns:
        The current org_id.

    Raises:
        RuntimeError: If no tenant context is active.
    """
    org_id = get_current_org_id()
    if org_id is None:
        raise RuntimeError(
            "No tenant context active. Wrap request in TenantContext or "
            "call TenantContext.activate() first."
        )
    return org_id


@dataclass
class TenantContext:
    """Request-scoped tenant context for RLS isolation.

    This context manager:
    1. Sets the PostgreSQL session variable `app.current_org_id`
    2. Applies tenant-specific resource limits (statement_timeout, lock_timeout)
    3. Updates the Python contextvars for in-process checks
    4. Clears all on exit

    The RLS policies defined in migration 023 use `current_org_id()`
    function which reads from `app.current_org_id` session variable.

    Attributes:
        pool: PostgresPool instance for database operations.
        org_id: Organization ID to scope queries to.
        user_id: Optional user ID for audit logging.
        tenant_slug: Optional tenant slug (for logging/debugging).
        apply_limits: Whether to apply tenant-specific resource limits.

    Example:
        async with TenantContext(pool, org_id="org-123", user_id="user-456"):
            # All queries are automatically filtered to org-123
            behaviors = await behavior_service.list_behaviors()
    """

    pool: "PostgresPool"
    org_id: Optional[str]
    user_id: Optional[str] = None
    tenant_slug: Optional[str] = None
    apply_limits: bool = True

    _org_token: Optional[contextvars.Token] = field(default=None, repr=False)
    _slug_token: Optional[contextvars.Token] = field(default=None, repr=False)

    async def __aenter__(self) -> "TenantContext":
        """Activate tenant context on entry."""
        await self.activate()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Deactivate tenant context on exit."""
        await self.deactivate()

    async def activate(self) -> None:
        """Activate the tenant context.

        Sets both the PostgreSQL session variable and Python contextvar.
        Optionally applies tenant-specific resource limits.
        Call deactivate() when done to clean up.
        """
        # Set Python contextvars
        self._org_token = _current_org_id.set(self.org_id)
        if self.tenant_slug:
            self._slug_token = _current_tenant_slug.set(self.tenant_slug)

        # Set PostgreSQL session variable for RLS (with resource limits)
        if self.org_id:
            if self.apply_limits:
                # Use set_tenant_context which also applies limits
                await self.pool.execute(
                    "SELECT set_tenant_context($1, $2)",
                    self.org_id,
                    self.user_id
                )
            else:
                # Legacy: just set org without limits
                await self.pool.execute(
                    "SELECT set_current_org($1, $2)",
                    self.org_id,
                    self.user_id
                )
        else:
            # Clear any existing context
            await self.pool.execute("SELECT clear_current_org()")

    async def deactivate(self) -> None:
        """Deactivate the tenant context.

        Clears both PostgreSQL session variable and Python contextvar.
        """
        # Clear PostgreSQL session variable
        await self.pool.execute("SELECT clear_current_org()")

        # Reset Python contextvars
        if self._org_token is not None:
            _current_org_id.reset(self._org_token)
            self._org_token = None
        if self._slug_token is not None:
            _current_tenant_slug.reset(self._slug_token)
            self._slug_token = None


@dataclass
class SlugCache:
    """Simple TTL cache for tenant slug -> org_id mappings.

    Avoids repeated database lookups for slug resolution.
    Thread-safe using a simple dict with expiration timestamps.
    """
    _cache: Dict[str, Tuple[str, float]] = field(default_factory=dict)
    ttl_seconds: float = DEFAULT_SLUG_CACHE_TTL

    def get(self, slug: str) -> Optional[str]:
        """Get org_id for slug if cached and not expired."""
        entry = self._cache.get(slug)
        if entry is None:
            return None
        org_id, expires_at = entry
        if time.time() > expires_at:
            del self._cache[slug]
            return None
        return org_id

    def set(self, slug: str, org_id: str) -> None:
        """Cache slug -> org_id mapping with TTL."""
        self._cache[slug] = (org_id, time.time() + self.ttl_seconds)

    def invalidate(self, slug: str) -> None:
        """Remove a slug from cache."""
        self._cache.pop(slug, None)

    def clear(self) -> None:
        """Clear all cached entries."""
        self._cache.clear()


# Global slug cache instance
_slug_cache = SlugCache()


def get_slug_cache() -> SlugCache:
    """Get the global slug cache instance."""
    return _slug_cache


class TenantMiddleware:
    """FastAPI middleware for automatic tenant context management.

    Resolves tenant from multiple sources in priority order:
    1. X-Tenant-ID header (explicit org_id)
    2. X-Tenant-Slug header (resolved to org_id via cache/DB)
    3. Subdomain parsing (e.g., acme.amprealize.dev -> slug "acme")
    4. Path parameter (e.g., /api/v1/tenants/{slug}/...)
    5. Auth context (organization from authenticated user's claims)

    Usage:
        from fastapi import FastAPI
        from amprealize.multi_tenant.context import TenantMiddleware

        app = FastAPI()
        app.add_middleware(TenantMiddleware, pool=postgres_pool)

    Configuration:
        - Enable/disable resolution sources via constructor flags
        - Custom slug resolver for database lookups
        - Configurable subdomain extraction pattern
    """

    def __init__(
        self,
        app,
        pool: "PostgresPool",
        *,
        enable_header: bool = True,
        enable_subdomain: bool = True,
        enable_path: bool = True,
        enable_auth_context: bool = True,
        slug_resolver: Optional[Callable[[str], Optional[str]]] = None,
        apply_limits: bool = True,
        base_domain: Optional[str] = None,  # e.g., "amprealize.dev" to strip from subdomain
        skip_paths: Optional[Set[str]] = None,
    ):
        """Initialize TenantMiddleware.

        Args:
            app: ASGI application to wrap.
            pool: PostgresPool instance for database operations.
            enable_header: Allow X-Tenant-ID/X-Tenant-Slug headers (default: True).
            enable_subdomain: Extract tenant from subdomain (default: True).
            enable_path: Extract tenant from URL path (default: True).
            enable_auth_context: Use authenticated user's org (default: True).
            slug_resolver: Custom async function to resolve slug -> org_id.
                          If None, uses database lookup with caching.
            apply_limits: Apply tenant-specific resource limits (default: True).
            base_domain: Base domain to strip when parsing subdomains.
            skip_paths: Paths to skip tenant resolution for (e.g., /health).
        """
        self.app = app
        self.pool = pool
        self.enable_header = enable_header
        self.enable_subdomain = enable_subdomain
        self.enable_path = enable_path
        self.enable_auth_context = enable_auth_context
        self.slug_resolver = slug_resolver
        self.apply_limits = apply_limits
        self.base_domain = base_domain
        self.skip_paths = skip_paths or set()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Skip tenant resolution for public paths
        path = scope.get("path", "")
        if path in self.skip_paths or any(
            path.startswith(p.rstrip('/')) for p in self.skip_paths
        ):
            await self.app(scope, receive, send)
            return

        # Resolve tenant from multiple sources
        org_id, tenant_slug, user_id = await self._resolve_tenant(scope)

        # Activate tenant context for this request
        ctx = TenantContext(
            self.pool,
            org_id=org_id,
            user_id=user_id,
            tenant_slug=tenant_slug,
            apply_limits=self.apply_limits,
        )
        await ctx.activate()

        try:
            await self.app(scope, receive, send)
        finally:
            await ctx.deactivate()

    async def _resolve_tenant(
        self, scope: Dict[str, Any]
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Resolve tenant from request scope.

        Returns:
            Tuple of (org_id, tenant_slug, user_id).
        """
        org_id: Optional[str] = None
        tenant_slug: Optional[str] = None
        user_id: Optional[str] = None

        # Priority 1: Auth context (from auth middleware — trusted, not spoofable)
        if self.enable_auth_context and "state" in scope:
            state = scope["state"]
            auth_org_id = state.get("org_id") if isinstance(state, dict) else getattr(state, "org_id", None)
            auth_user_id = state.get("user_id") if isinstance(state, dict) else getattr(state, "user_id", None)
            auth_slug = state.get("tenant_slug") if isinstance(state, dict) else getattr(state, "tenant_slug", None)
            if auth_org_id or auth_user_id:
                return auth_org_id, auth_slug, auth_user_id

        headers = dict(scope.get("headers", []))

        # Priority 2: X-Tenant-ID header (explicit org_id)
        if self.enable_header:
            tenant_id_header = headers.get(b"x-tenant-id")
            if tenant_id_header:
                org_id = tenant_id_header.decode("utf-8")
                return org_id, None, user_id

            # Priority 3: X-Tenant-Slug header (needs resolution)
            slug_header = headers.get(b"x-tenant-slug")
            if slug_header:
                tenant_slug = slug_header.decode("utf-8")
                org_id = await self._resolve_slug(tenant_slug)
                if org_id:
                    return org_id, tenant_slug, user_id

        # Priority 4: Subdomain parsing
        if self.enable_subdomain:
            host_header = headers.get(b"host")
            if host_header:
                host = host_header.decode("utf-8").split(":")[0]  # Remove port
                tenant_slug = self._extract_subdomain(host)
                if tenant_slug:
                    org_id = await self._resolve_slug(tenant_slug)
                    if org_id:
                        return org_id, tenant_slug, user_id

        # Priority 5: Path parameter
        if self.enable_path:
            path = scope.get("path", "")
            tenant_slug = self._extract_path_tenant(path)
            if tenant_slug:
                org_id = await self._resolve_slug(tenant_slug)
                if org_id:
                    return org_id, tenant_slug, user_id

        return org_id, tenant_slug, user_id

    def _extract_subdomain(self, host: str) -> Optional[str]:
        """Extract tenant slug from subdomain.

        Examples:
            - acme.amprealize.dev -> "acme"
            - api.amprealize.dev -> None (reserved)
            - amprealize.dev -> None (no subdomain)
            - localhost -> None
        """
        # Skip localhost
        if host in ("localhost", "127.0.0.1", "0.0.0.0"):
            return None

        # Strip base domain if configured
        if self.base_domain and host.endswith(f".{self.base_domain}"):
            subdomain = host[: -(len(self.base_domain) + 1)]
            # Skip reserved subdomains
            if subdomain in ("api", "www", "app", "admin", "internal"):
                return None
            return subdomain if subdomain else None

        # Use regex for general subdomain extraction
        match = SUBDOMAIN_PATTERN.match(host)
        if match:
            subdomain = match.group(1).lower()
            # Skip reserved subdomains
            if subdomain in ("api", "www", "app", "admin", "internal"):
                return None
            return subdomain

        return None

    def _extract_path_tenant(self, path: str) -> Optional[str]:
        """Extract tenant slug from URL path.

        Examples:
            - /api/v1/tenants/acme/behaviors -> "acme"
            - /t/acme/runs -> "acme"
            - /org/acme-corp/actions -> "acme-corp"
        """
        match = PATH_TENANT_PATTERN.search(path)
        if match:
            return match.group(1).lower()
        return None

    async def _resolve_slug(self, slug: str) -> Optional[str]:
        """Resolve tenant slug to org_id.

        Uses cache first, then custom resolver or database lookup.
        """
        # Check cache first
        cached_org_id = _slug_cache.get(slug)
        if cached_org_id:
            return cached_org_id

        # Use custom resolver if provided
        if self.slug_resolver:
            org_id = await self.slug_resolver(slug)
        else:
            # Default: database lookup
            org_id = await self._db_resolve_slug(slug)

        # Cache the result
        if org_id:
            _slug_cache.set(slug, org_id)

        return org_id

    async def _db_resolve_slug(self, slug: str) -> Optional[str]:
        """Resolve slug via database lookup.

        Queries the organizations table for the org_id matching the slug.
        """
        try:
            rows = await self.pool.fetch(
                "SELECT id FROM organizations WHERE slug = $1 AND deleted_at IS NULL",
                slug
            )
            if rows:
                return rows[0]["id"]
        except Exception:
            # Log error but don't fail the request
            pass
        return None


def tenant_scoped(func):
    """Decorator to require active tenant context for a function.

    Usage:
        @tenant_scoped
        async def get_behaviors(self):
            org_id = get_current_org_id()
            # org_id is guaranteed to be set here
            ...
    """
    import functools

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        require_org_context()
        return await func(*args, **kwargs)

    return wrapper
