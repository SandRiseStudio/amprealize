"""GitHub App Service.

Handles GitHub App authentication, installation token generation,
and installation URL generation.

Behavior: behavior_externalize_configuration
Behavior: behavior_use_raze_for_logging

Unlike PATs (Personal Access Tokens), GitHub App tokens:
- Are short-lived (1 hour)
- Are scoped to specific installations
- Don't require users to manage secrets
- Support organization-wide installations
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import httpx

from ..storage.postgres_pool import PostgresPool
from ..utils.dsn import resolve_postgres_dsn
from .github_app_installation_repository import (
    GitHubAppInstallation,
    GitHubAppInstallationRepository,
)
from .github_credential_repository import CredentialScopeType


logger = logging.getLogger(__name__)

# DSN resolution constants (same as other auth services)
_AUTH_PG_DSN_ENV = "AMPREALIZE_AUTH_PG_DSN"
_DEFAULT_PG_DSN = "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize"


# ==============================================================================
# Configuration
# ==============================================================================


@dataclass
class GitHubAppConfig:
    """Configuration for GitHub App.

    All values should come from environment variables.
    Behavior: behavior_externalize_configuration
    """

    app_id: str
    private_key: str  # PEM format (can be base64-encoded)
    slug: str  # App URL slug for install URL
    client_id: str
    client_secret: str
    webhook_secret: Optional[str] = None  # For webhook signature verification
    callback_url: Optional[str] = None  # Override default callback URL

    @classmethod
    def from_env(cls) -> Optional["GitHubAppConfig"]:
        """Load configuration from environment variables.

        Returns None if required variables are not set.
        Supports GITHUB_APP_PRIVATE_KEY (inline) or GITHUB_APP_PRIVATE_KEY_PATH (file).
        """
        app_id = os.getenv("GITHUB_APP_ID")
        slug = os.getenv("GITHUB_APP_SLUG")
        client_id = os.getenv("GITHUB_APP_CLIENT_ID")
        client_secret = os.getenv("GITHUB_APP_CLIENT_SECRET")

        # Load private key from file or environment variable
        private_key = os.getenv("GITHUB_APP_PRIVATE_KEY")
        private_key_path = os.getenv("GITHUB_APP_PRIVATE_KEY_PATH")

        if not private_key and private_key_path:
            try:
                with open(private_key_path, "r") as f:
                    private_key = f.read()
            except Exception as e:
                logger.warning(f"Failed to read private key from {private_key_path}: {e}")
                private_key = None

        if not all([app_id, private_key, slug, client_id, client_secret]):
            return None

        # Decode private key if base64-encoded
        if private_key and not private_key.startswith("-----BEGIN"):
            try:
                private_key = base64.b64decode(private_key).decode("utf-8")
            except Exception:
                pass  # Not base64, use as-is

        return cls(
            app_id=app_id,  # type: ignore
            private_key=private_key,  # type: ignore
            slug=slug,  # type: ignore
            client_id=client_id,  # type: ignore
            client_secret=client_secret,  # type: ignore
            webhook_secret=os.getenv("GITHUB_APP_WEBHOOK_SECRET"),
            callback_url=os.getenv("GITHUB_APP_CALLBACK_URL"),
        )

    @property
    def is_configured(self) -> bool:
        """Check if GitHub App is properly configured."""
        return bool(self.app_id and self.private_key and self.slug)


# ==============================================================================
# State Management (for OAuth-like flow)
# ==============================================================================


@dataclass
class InstallationState:
    """State object for installation callback verification.

    Contains scope info and is signed with HMAC for security.
    """

    scope_type: str
    scope_id: str
    redirect_uri: Optional[str] = None
    nonce: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    created_at: float = field(default_factory=time.time)

    def encode(self, secret: str) -> str:
        """Encode state as signed string."""
        import json
        data = {
            "t": self.scope_type,
            "s": self.scope_id,
            "r": self.redirect_uri,
            "n": self.nonce,
            "c": self.created_at,
        }
        payload = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()
        signature = hmac.new(
            secret.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()[:16]
        return f"{payload}.{signature}"

    @classmethod
    def decode(cls, state: str, secret: str, max_age: int = 3600) -> Optional["InstallationState"]:
        """Decode and verify signed state string.

        Returns None if invalid or expired.
        """
        import json
        try:
            parts = state.split(".")
            if len(parts) != 2:
                return None

            payload, signature = parts

            # Verify signature
            expected_sig = hmac.new(
                secret.encode(),
                payload.encode(),
                hashlib.sha256,
            ).hexdigest()[:16]
            if not hmac.compare_digest(signature, expected_sig):
                logger.warning("Invalid state signature")
                return None

            data = json.loads(base64.urlsafe_b64decode(payload))

            # Check expiration
            created_at = data.get("c", 0)
            if time.time() - created_at > max_age:
                logger.warning("State expired")
                return None

            return cls(
                scope_type=data["t"],
                scope_id=data["s"],
                redirect_uri=data.get("r"),
                nonce=data.get("n", ""),
                created_at=created_at,
            )
        except Exception as e:
            logger.warning(f"Failed to decode state: {e}")
            return None


# ==============================================================================
# Service
# ==============================================================================


class GitHubAppService:
    """Service for GitHub App authentication and token management.

    Handles:
    - JWT generation for GitHub App API calls
    - Installation access token generation and caching
    - Installation URL generation for OAuth-like flow
    - Installation callback processing

    Behavior: behavior_prefer_mcp_tools (used by MCP handlers)
    """

    def __init__(
        self,
        config: Optional[GitHubAppConfig] = None,
        pool: Optional[PostgresPool] = None,
        state_secret: Optional[str] = None,
    ) -> None:
        self._config = config or GitHubAppConfig.from_env()
        if pool:
            self._pool = pool
        else:
            resolved_dsn = resolve_postgres_dsn(
                service="AUTH",
                explicit_dsn=None,
                env_var=_AUTH_PG_DSN_ENV,
                default_dsn=_DEFAULT_PG_DSN,
            )
            self._pool = PostgresPool(resolved_dsn)
        self._repo = GitHubAppInstallationRepository(self._pool)

        # State signing secret (defaults to client_secret for convenience)
        self._state_secret = (
            state_secret
            or os.getenv("GITHUB_APP_STATE_SECRET")
            or (self._config.client_secret if self._config else None)
            or "default-secret-change-me"
        )

    @property
    def is_configured(self) -> bool:
        """Check if GitHub App is properly configured."""
        return self._config is not None and self._config.is_configured

    # --------------------------------------------------------------------------
    # Installation URL Generation
    # --------------------------------------------------------------------------

    def get_install_url(
        self,
        scope_type: str,
        scope_id: str,
        redirect_uri: Optional[str] = None,
    ) -> Tuple[str, str]:
        """Generate URL to install/configure the GitHub App.

        Returns tuple of (install_url, state) for CSRF verification.
        """
        if not self._config:
            raise ValueError("GitHub App not configured")

        # Create signed state
        state = InstallationState(
            scope_type=scope_type,
            scope_id=scope_id,
            redirect_uri=redirect_uri,
        )
        state_str = state.encode(self._state_secret)

        # Build installation URL
        # https://docs.github.com/en/apps/using-github-apps/installing-a-github-app
        url = f"https://github.com/apps/{self._config.slug}/installations/new"
        params = {"state": state_str}
        if redirect_uri:
            params["redirect_uri"] = redirect_uri

        return f"{url}?{urlencode(params)}", state_str

    def get_configure_url(
        self,
        installation_id: int,
    ) -> str:
        """Get URL to configure an existing installation's repo selection."""
        if not self._config:
            raise ValueError("GitHub App not configured")
        return f"https://github.com/apps/{self._config.slug}/installations/{installation_id}"

    # --------------------------------------------------------------------------
    # JWT Generation
    # --------------------------------------------------------------------------

    def generate_jwt(self) -> str:
        """Generate JWT for GitHub App API calls.

        JWTs are used to authenticate as the App itself (not an installation).
        They're valid for up to 10 minutes.
        """
        if not self._config:
            raise ValueError("GitHub App not configured")

        try:
            import jwt
        except ImportError:
            raise ImportError("PyJWT is required for GitHub App authentication. Install with: pip install PyJWT")

        now = int(time.time())
        payload = {
            "iat": now - 60,  # 1 minute in the past to account for clock drift
            "exp": now + (10 * 60),  # 10 minutes
            "iss": self._config.app_id,
        }

        return jwt.encode(
            payload,
            self._config.private_key,
            algorithm="RS256",
        )

    # --------------------------------------------------------------------------
    # Installation Token Management
    # --------------------------------------------------------------------------

    async def get_installation_token(
        self,
        installation_id: int,
        repository_ids: Optional[List[int]] = None,
        permissions: Optional[Dict[str, str]] = None,
        force_refresh: bool = False,
    ) -> str:
        """Get or generate an installation access token.

        Tokens are cached and auto-refreshed when expired (with 5 min buffer).

        Args:
            installation_id: GitHub App installation ID
            repository_ids: Optional list of repo IDs to scope token to
            permissions: Optional permissions to request (subset of installation permissions)
            force_refresh: Skip cache and generate new token

        Returns:
            Installation access token (valid for ~1 hour)
        """
        if not force_refresh:
            cached = self._repo.get_cached_token(installation_id)
            if cached and not cached.is_expired:
                logger.debug(f"Using cached token for installation {installation_id}")
                return cached.token

        # Generate new token
        app_jwt = self.generate_jwt()

        async with httpx.AsyncClient() as client:
            payload: Dict[str, Any] = {}
            if repository_ids:
                payload["repository_ids"] = repository_ids
            if permissions:
                payload["permissions"] = permissions

            response = await client.post(
                f"https://api.github.com/app/installations/{installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {app_jwt}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                json=payload if payload else None,
            )

            if response.status_code == 404:
                # Installation not found - may have been uninstalled
                logger.warning(f"Installation {installation_id} not found - may be uninstalled")
                self._repo.deactivate_installation(installation_id, "Not found (404)")
                raise ValueError(f"GitHub App installation {installation_id} not found")

            response.raise_for_status()
            data = response.json()

        token = data["token"]
        expires_at = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))

        # Cache the token
        self._repo.cache_installation_token(installation_id, token, expires_at)
        logger.info(f"Generated new token for installation {installation_id}, expires {expires_at}")

        return token

    def get_installation_token_sync(
        self,
        installation_id: int,
        repository_ids: Optional[List[int]] = None,
        permissions: Optional[Dict[str, str]] = None,
        force_refresh: bool = False,
    ) -> str:
        """Synchronous version of get_installation_token."""
        import asyncio

        # Handle running in existing event loop
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Create a new thread to run the coroutine
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run,
                        self.get_installation_token(
                            installation_id, repository_ids, permissions, force_refresh
                        )
                    )
                    return future.result()
            else:
                return loop.run_until_complete(
                    self.get_installation_token(
                        installation_id, repository_ids, permissions, force_refresh
                    )
                )
        except RuntimeError:
            return asyncio.run(
                self.get_installation_token(
                    installation_id, repository_ids, permissions, force_refresh
                )
            )

    # --------------------------------------------------------------------------
    # Installation Callback Handling
    # --------------------------------------------------------------------------

    async def handle_installation_callback(
        self,
        installation_id: int,
        setup_action: str,  # 'install', 'update', 'delete'
        state: str,
        installed_by: Optional[str] = None,
    ) -> Optional[GitHubAppInstallation]:
        """Process installation callback from GitHub.

        Called when GitHub redirects back after app installation/configuration.

        Args:
            installation_id: GitHub installation ID from callback
            setup_action: Action type ('install', 'update', 'delete')
            state: Signed state string for verification
            installed_by: Amprealize user ID who initiated the flow

        Returns:
            GitHubAppInstallation object (or None for deletions)
        """
        # Verify state
        decoded_state = InstallationState.decode(state, self._state_secret)
        if not decoded_state:
            raise ValueError("Invalid or expired state parameter")

        scope_type = CredentialScopeType(decoded_state.scope_type)
        scope_id = decoded_state.scope_id

        if setup_action == "delete":
            self._repo.deactivate_installation(installation_id, "User deleted")
            return None

        # Fetch installation details from GitHub
        details = await self._fetch_installation_details(installation_id)
        if not details:
            raise ValueError(f"Could not fetch installation {installation_id} details")

        # Create or update installation record
        installation = self._repo.create_or_update_installation(
            installation_id=installation_id,
            account_type=details["account"]["type"],
            account_login=details["account"]["login"],
            account_id=details["account"]["id"],
            account_avatar_url=details["account"].get("avatar_url"),
            app_id=details.get("app_id"),
            scope_type=scope_type,
            scope_id=scope_id,
            repository_selection=details.get("repository_selection"),
            selected_repository_ids=[],  # Fetched separately if needed
            permissions=details.get("permissions", {}),
            events=details.get("events", []),
            installed_by=installed_by,
            metadata={
                "html_url": details.get("html_url"),
                "target_type": details.get("target_type"),
            },
        )

        # Create link for this scope
        self._repo.link_installation_to_scope(
            installation_id=installation_id,
            scope_type=scope_type,
            scope_id=scope_id,
            linked_by=installed_by,
        )

        logger.info(
            f"Processed installation callback: {setup_action} for "
            f"{installation.account_login} -> {scope_type.value}:{scope_id}"
        )

        return installation

    async def _fetch_installation_details(
        self,
        installation_id: int,
    ) -> Optional[Dict[str, Any]]:
        """Fetch installation details from GitHub API."""
        app_jwt = self.generate_jwt()

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.github.com/app/installations/{installation_id}",
                headers={
                    "Authorization": f"Bearer {app_jwt}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )

            if response.status_code == 404:
                return None

            response.raise_for_status()
            return response.json()

    async def list_installations(self) -> List[Dict[str, Any]]:
        """List installations for this GitHub App.

        Uses the App's JWT to fetch all installations from GitHub API.
        Returns the raw list of installation objects.
        """
        app_jwt = self.generate_jwt()

        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.github.com/app/installations",
                headers={
                    "Authorization": f"Bearer {app_jwt}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                params={"per_page": 100},
            )

            response.raise_for_status()
            data = response.json()

            # GitHub API returns a list directly, not a dict with "installations" key
            if isinstance(data, list):
                return data
            # Handle potential API changes
            return data.get("installations", []) if isinstance(data, dict) else []

    async def get_installation_repositories(self, installation_id: int) -> List[int]:
        """Get the list of repository IDs accessible to an installation.

        Uses an installation access token to fetch repositories.
        Returns a list of repository IDs.
        """
        try:
            token = await self.get_installation_token(installation_id)

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.github.com/installation/repositories",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    params={"per_page": 100},
                )
                response.raise_for_status()
                data = response.json()

                repositories = data.get("repositories", [])
                return [repo.get("id") for repo in repositories if repo.get("id")]
        except Exception as e:
            logger.warning(f"Failed to fetch repositories for installation {installation_id}: {e}")
            return []

    # --------------------------------------------------------------------------
    # Installation Management
    # --------------------------------------------------------------------------

    def get_installation_for_scope(
        self,
        scope_type: CredentialScopeType,
        scope_id: str,
    ) -> Optional[GitHubAppInstallation]:
        """Get the active GitHub App installation for a scope."""
        return self._repo.get_installation_for_scope(scope_type, scope_id)

    async def link_existing_installation(
        self,
        installation_id: int,
        scope_type: CredentialScopeType,
        scope_id: str,
        linked_by: Optional[str] = None,
    ) -> bool:
        """Link an existing installation to a new scope.

        Useful for sharing one GitHub App installation across multiple projects.
        If the installation isn't in the database yet, fetches it from GitHub
        and saves it first.
        """
        # Check if installation exists in database
        installation = self._repo.get_installation_by_id(installation_id)

        if not installation:
            # Not in DB - try to fetch from GitHub and save it
            try:
                installations = await self.list_installations()
                matching = next(
                    (i for i in installations if i.get("id") == installation_id),
                    None
                )
                if not matching:
                    logger.warning(f"Installation {installation_id} not found in GitHub API")
                    return False

                # Fetch selected repository IDs if repository_selection is "selected"
                selected_repo_ids: List[int] = []
                if matching.get("repository_selection") == "selected":
                    selected_repo_ids = await self.get_installation_repositories(installation_id)

                # Save to database
                account = matching.get("account", {})
                installation = self._repo.create_or_update_installation(
                    installation_id=installation_id,
                    account_type=account.get("type", "User"),
                    account_login=account.get("login", "unknown"),
                    account_id=account.get("id", 0),
                    scope_type=scope_type,
                    scope_id=scope_id,
                    app_id=matching.get("app_id"),
                    account_avatar_url=account.get("avatar_url"),
                    repository_selection=matching.get("repository_selection"),
                    selected_repository_ids=selected_repo_ids,
                    permissions=matching.get("permissions"),
                    events=matching.get("events"),
                    installed_by=linked_by,
                )
                logger.info(f"Saved GitHub installation {installation_id} from API with {len(selected_repo_ids)} repos")
                return True
            except Exception as e:
                logger.error(f"Failed to fetch/save installation {installation_id}: {e}")
                return False

        if not installation.is_active:
            return False

        self._repo.link_installation_to_scope(
            installation_id=installation_id,
            scope_type=scope_type,
            scope_id=scope_id,
            linked_by=linked_by,
        )
        return True

    def unlink_installation(
        self,
        scope_type: CredentialScopeType,
        scope_id: str,
    ) -> bool:
        """Unlink GitHub App installation from a scope.

        Note: This does NOT uninstall the app from GitHub.
        """
        return self._repo.unlink_installation_from_scope(scope_type, scope_id)


# ==============================================================================
# Singleton Instance
# ==============================================================================


_github_app_service: Optional[GitHubAppService] = None


def get_github_app_service() -> GitHubAppService:
    """Get the singleton GitHubAppService instance."""
    global _github_app_service
    if _github_app_service is None:
        _github_app_service = GitHubAppService()
    return _github_app_service
