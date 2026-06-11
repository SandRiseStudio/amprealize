"""Token storage utilities for CLI and IDE integrations.

This module provides a simple file-backed token store along with helper data
structures to represent issued access and refresh tokens. The implementation is
intentionally lightweight for prototype environments and will be upgraded to
use platform keychains in subsequent milestones.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:  # pragma: no cover - optional dependency import
    import keyring  # type: ignore[import-not-found]
    from keyring.errors import KeyringError as _KeyringError, PasswordDeleteError as _PasswordDeleteError  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - keyring not installed/available
    keyring = None  # type: ignore[assignment]
    _KeyringError = _PasswordDeleteError = None  # type: ignore[assignment]

KeyringErrorType: Any = _KeyringError or RuntimeError
PasswordDeleteErrorType: Any = _PasswordDeleteError or RuntimeError


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class AuthTokenBundle:
    """Container for access and refresh tokens."""

    access_token: str
    refresh_token: str
    token_type: str
    scopes: List[str]
    client_id: str
    issued_at: datetime
    expires_at: datetime
    refresh_expires_at: datetime
    provider: str = "github"  # Provider name: github, internal, gitlab, etc.

    def as_dict(self) -> Dict[str, object]:
        data = asdict(self)
        data["issued_at"] = self.issued_at.isoformat().replace("+00:00", "Z")
        data["expires_at"] = self.expires_at.isoformat().replace("+00:00", "Z")
        data["refresh_expires_at"] = self.refresh_expires_at.isoformat().replace("+00:00", "Z")
        return data

    @classmethod
    def from_dict(cls, payload: Dict[str, object]) -> "AuthTokenBundle":
        def _parse(name: str) -> datetime:
            value = payload[name]
            if isinstance(value, datetime):
                return value.astimezone(timezone.utc)
            if isinstance(value, str):
                return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
            raise ValueError(f"Unexpected datetime payload for {name}: {value!r}")

        raw_scopes = payload.get("scopes", [])
        if isinstance(raw_scopes, (list, tuple)):
            scopes = [str(scope) for scope in raw_scopes]
        elif raw_scopes in (None, ""):
            scopes = []
        else:
            scopes = [str(raw_scopes)]

        return cls(
            access_token=str(payload["access_token"]),
            refresh_token=str(payload["refresh_token"]),
            token_type=str(payload.get("token_type", "Bearer")),
            scopes=scopes,
            client_id=str(payload.get("client_id", "unknown")),
            issued_at=_parse("issued_at"),
            expires_at=_parse("expires_at"),
            refresh_expires_at=_parse("refresh_expires_at"),
            provider=str(payload.get("provider", "github")),  # Default to github for backward compatibility
        )

    def access_expires_in(self) -> int:
        return max(0, int((self.expires_at - _now()).total_seconds()))

    def refresh_expires_in(self) -> int:
        return max(0, int((self.refresh_expires_at - _now()).total_seconds()))

    def is_access_valid(self) -> bool:
        return self.access_expires_in() > 0

    def update_tokens(
        self,
        *,
        access_token: str,
        access_expires_at: datetime,
        refresh_token: Optional[str] = None,
        refresh_expires_at: Optional[datetime] = None,
    ) -> None:
        """Update stored token values after a refresh operation."""

        self.access_token = access_token
        self.expires_at = access_expires_at.astimezone(timezone.utc)
        self.issued_at = _now()
        if refresh_token is not None:
            self.refresh_token = refresh_token
        if refresh_expires_at is not None:
            self.refresh_expires_at = refresh_expires_at.astimezone(timezone.utc)


class TokenStoreError(Exception):
    """Raised when token persistence encounters an issue."""


class TokenStore:
    """Interface for storing and retrieving auth token bundles."""

    def save(self, bundle: AuthTokenBundle, provider: Optional[str] = None) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def load(self, provider: Optional[str] = None) -> Optional[AuthTokenBundle]:  # pragma: no cover - interface
        raise NotImplementedError

    def clear(self, provider: Optional[str] = None) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class FileTokenStore(TokenStore):
    """Persist tokens to a JSON file under the user's amprealize directory.

    Supports multi-provider storage with separate files per provider.
    Default behavior stores to auth_tokens.json for backward compatibility.
    Provider-specific storage uses auth_tokens_<provider>.json pattern.
    """

    def __init__(self, path: Optional[Path] = None, provider: Optional[str] = None) -> None:
        """Initialize token store with optional provider-specific path.

        Args:
            path: Custom path to token file. If None, uses AMPREALIZE_CONFIG_DIR or ~/.amprealize/.
            provider: Provider name for multi-provider storage. If specified, tokens
                     are stored in auth_tokens_<provider>.json.
        """

        configured_path = os.getenv("AMPREALIZE_AUTH_TOKEN_PATH")
        if configured_path:
            path = Path(configured_path).expanduser()

        resolved_path = Path(path).expanduser() if path else None

        if resolved_path is not None:
            base_dir = resolved_path.parent
            default_filename = resolved_path.name
        else:
            config_dir = os.getenv("AMPREALIZE_CONFIG_DIR")
            base_dir = Path(config_dir).expanduser() if config_dir else (Path.home() / ".amprealize")
            default_filename = "auth_tokens.json"

        base_dir.mkdir(parents=True, exist_ok=True)

        if provider:
            filename = f"auth_tokens_{provider}.json"
        else:
            filename = default_filename

        self._path = (base_dir / filename).expanduser().resolve()
        self._provider = provider

    def save(self, bundle: AuthTokenBundle, provider: Optional[str] = None) -> None:
        """Save token bundle to file.

        Args:
            bundle: Token bundle to save.
            provider: Override provider name. If specified, saves to auth_tokens_<provider>.json.
        """
        try:
            data = bundle.as_dict()

            # Determine target path
            if provider and provider != self._provider:
                # Override provider, compute new path
                target_path = self._path.parent / f"auth_tokens_{provider}.json"
            else:
                target_path = self._path

            target_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError as exc:  # pragma: no cover - filesystem errors
            raise TokenStoreError(f"Failed to write token file: {exc}") from exc

    def load(self, provider: Optional[str] = None) -> Optional[AuthTokenBundle]:
        """Load token bundle from file.

        Args:
            provider: Override provider name to load from auth_tokens_<provider>.json.

        Returns:
            Token bundle if found, None if file doesn't exist.
        """
        # Determine source path
        if provider and provider != self._provider:
            source_path = self._path.parent / f"auth_tokens_{provider}.json"
        else:
            source_path = self._path

        if not source_path.exists():
            return None
        try:
            payload = json.loads(source_path.read_text(encoding="utf-8"))
            return AuthTokenBundle.from_dict(payload)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise TokenStoreError(f"Failed to read token file: {exc}") from exc

    def clear(self, provider: Optional[str] = None) -> None:
        """Clear token file.

        Args:
            provider: Override provider name to clear auth_tokens_<provider>.json.
        """
        # Determine target path
        if provider and provider != self._provider:
            target_path = self._path.parent / f"auth_tokens_{provider}.json"
        else:
            target_path = self._path

        if not target_path.exists():
            return
        try:
            target_path.unlink()
        except OSError as exc:  # pragma: no cover - filesystem errors
            raise TokenStoreError(f"Failed to delete token file: {exc}") from exc

    def list_providers(self) -> List[str]:
        """List all providers with stored tokens.

        Returns:
            List of provider names found in token files.
        """
        providers = []
        token_dir = self._path.parent

        # Check default file
        if (token_dir / "auth_tokens.json").exists():
            providers.append("default")

        # Check provider-specific files
        for token_file in token_dir.glob("auth_tokens_*.json"):
            # Extract provider name from filename: auth_tokens_github.json -> github
            provider = token_file.stem.replace("auth_tokens_", "")
            providers.append(provider)

        return sorted(providers)


class KeychainTokenStore(TokenStore):
    """Persist tokens using the system keychain via keyring."""

    def __init__(
        self,
        *,
        service_name: Optional[str] = None,
        username: Optional[str] = None,
    ) -> None:
        if keyring is None:
            raise TokenStoreError(
                "keyring library is unavailable. Install the optional dependency or allow plaintext storage."
            )

        self._keyring: Any = keyring
        self._service_name = service_name or os.getenv("AMPREALIZE_KEYCHAIN_SERVICE", "amprealize.auth")
        self._username = username or os.getenv("AMPREALIZE_KEYCHAIN_USERNAME", "cli")

    def save(self, bundle: AuthTokenBundle, provider: Optional[str] = None) -> None:
        """Save token bundle to keychain.

        Note: Keychain storage does not support multi-provider storage natively.
        Provider parameter is accepted for interface compatibility but ignored.
        Use FileTokenStore for multi-provider support.
        """
        try:
            payload = json.dumps(bundle.as_dict())
            self._keyring.set_password(self._service_name, self._username, payload)
        except KeyringErrorType as exc:  # pragma: no cover - backend specific failures
            raise TokenStoreError(f"Failed to store tokens in keychain: {exc}") from exc

    def load(self, provider: Optional[str] = None) -> Optional[AuthTokenBundle]:
        """Load token bundle from keychain.

        Note: Provider parameter is accepted for interface compatibility but ignored.
        """
        try:
            raw = self._keyring.get_password(self._service_name, self._username)
        except KeyringErrorType as exc:  # pragma: no cover - backend specific failures
            raise TokenStoreError(f"Failed to read tokens from keychain: {exc}") from exc
        if not raw:
            return None
        try:
            payload = json.loads(raw)
            return AuthTokenBundle.from_dict(payload)
        except (json.JSONDecodeError, ValueError) as exc:
            raise TokenStoreError(f"Keychain payload corrupted: {exc}") from exc

    def clear(self, provider: Optional[str] = None) -> None:
        """Clear keychain entry.

        Note: Provider parameter is accepted for interface compatibility but ignored.
        """
        try:
            self._keyring.delete_password(self._service_name, self._username)
        except PasswordDeleteErrorType:  # pragma: no cover - already removed
            return
        except KeyringErrorType as exc:  # pragma: no cover - backend specific failures
            raise TokenStoreError(f"Failed to delete keychain entry: {exc}") from exc


def _flag_enabled(name: str) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def get_default_token_store(*, allow_plaintext: Optional[bool] = None) -> TokenStore:
    """Return the default token store implementation."""

    prefer_plaintext = allow_plaintext if allow_plaintext is not None else _flag_enabled(
        "AMPREALIZE_ALLOW_PLAINTEXT_TOKENS"
    )

    if not prefer_plaintext:
        try:
            return KeychainTokenStore()
        except TokenStoreError as exc:
            raise TokenStoreError(
                "Keychain storage is required by default. "
                "Pass --allow-plaintext or set AMPREALIZE_ALLOW_PLAINTEXT_TOKENS=1 to permit file storage."
            ) from exc

    return FileTokenStore()


__all__ = [
    "AuthTokenBundle",
    "TokenStore",
    "TokenStoreError",
    "FileTokenStore",
    "KeychainTokenStore",
    "get_default_token_store",
]
