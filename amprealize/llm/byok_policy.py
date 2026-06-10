"""BYOK persistence / encryption policy for OSS and Enterprise deployments.

Cloud-dev and locked-down environments can set ``AMPREALIZE_REQUIRE_BYOK_ENCRYPTION``
so credential *creation* fails until a stable KMS, Vault, or Fernet key is configured.
"""

from __future__ import annotations

import os
from typing import Any, Dict


def _truthy(raw: str | None) -> bool:
    if raw is None:
        return False
    return raw.strip().lower() in ("1", "true", "yes", "on")


def byok_persistence_status() -> Dict[str, Any]:
    """Describe whether persisted BYOK is allowed and how encryption is configured.

    Returns keys:
        - ``encryption_mode``: ``fernet`` | ``aws-kms`` | ``vault``
        - ``configured``: encryption backend is fully configured
        - ``ephemeral``: Fernet key would be auto-generated on first use (dev only)
        - ``can_persist``: BYOK rows may be created/rotated (false blocks ``repo.create``)
        - ``reason``: machine-readable when ``can_persist`` is false
        - ``warning``: human-facing non-fatal guidance
    """
    require_stable = _truthy(os.getenv("AMPREALIZE_REQUIRE_BYOK_ENCRYPTION"))
    env_profile = (os.getenv("AMPREALIZE_ENV") or "development").strip().lower()
    kms = (os.getenv("BYOK_KMS_PROVIDER") or "fernet").strip().lower()

    if kms == "aws-kms":
        ok = bool(os.getenv("AWS_KMS_KEY_ID"))
        return {
            "encryption_mode": "aws-kms",
            "configured": ok,
            "ephemeral": False,
            "can_persist": ok and (not require_stable or ok),
            "reason": None if ok else "missing_aws_kms_key_id",
            "warning": None,
        }

    if kms == "vault":
        ok = bool(os.getenv("VAULT_ADDR") and os.getenv("VAULT_TRANSIT_KEY"))
        return {
            "encryption_mode": "vault",
            "configured": ok,
            "ephemeral": False,
            "can_persist": ok,
            "reason": None if ok else "missing_vault_config",
            "warning": None,
        }

    # --- Fernet (default) ---
    from amprealize.auth.credential_encryption import CredentialEncryptionService

    raw = os.getenv("BYOK_ENCRYPTION_KEY")
    resolved = CredentialEncryptionService._resolve_shell_default_value(raw) if raw else None
    explicit = bool(resolved)

    if explicit:
        return {
            "encryption_mode": "fernet",
            "configured": True,
            "ephemeral": False,
            "can_persist": True,
            "reason": None,
            "warning": None,
        }

    if env_profile == "production":
        return {
            "encryption_mode": "fernet",
            "configured": False,
            "ephemeral": False,
            "can_persist": False,
            "reason": "missing_fernet_key_production",
            "warning": "Set BYOK_ENCRYPTION_KEY or BYOK_KMS_PROVIDER before persisting BYOK.",
        }

    if require_stable:
        return {
            "encryption_mode": "fernet",
            "configured": False,
            "ephemeral": True,
            "can_persist": False,
            "reason": "encryption_required",
            "warning": (
                "AMPREALIZE_REQUIRE_BYOK_ENCRYPTION is set but BYOK_ENCRYPTION_KEY is missing. "
                "Set a stable Fernet key or configure KMS/Vault."
            ),
        }

    return {
        "encryption_mode": "fernet",
        "configured": True,
        "ephemeral": True,
        "can_persist": True,
        "reason": None,
        "warning": (
            "BYOK_ENCRYPTION_KEY is not set; the server may generate an ephemeral dev key. "
            "BYOK credentials may not survive restarts."
        ),
    }


def assert_byok_persistence_allowed() -> None:
    """Raise ``ValueError`` when persisted BYOK must not be created."""
    status = byok_persistence_status()
    if not status.get("can_persist", False):
        reason = status.get("reason") or "persistence_blocked"
        raise ValueError(reason)
