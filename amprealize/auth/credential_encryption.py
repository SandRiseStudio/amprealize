"""Credential Encryption Service.

Provides secure encryption/decryption for BYOK credentials using Fernet
(AES-128-CBC). Supports optional KMS integration for enterprise deployments.

Behavior: behavior_lock_down_security_surface
"""

from __future__ import annotations

import abc
import base64
import logging
import os
import secrets
from typing import Optional, Protocol

from cryptography.fernet import Fernet, InvalidToken


logger = logging.getLogger(__name__)


class EncryptionProvider(Protocol):
    """Protocol for encryption providers (Fernet, KMS, etc.)."""

    def encrypt(self, plaintext: str) -> str:
        """Encrypt plaintext to ciphertext."""
        ...

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt ciphertext to plaintext."""
        ...


class FernetProvider:
    """Local Fernet-based encryption provider."""

    def __init__(self, encryption_key: str) -> None:
        """
        Initialize Fernet provider.

        Args:
            encryption_key: Base64-encoded 32-byte key.
                           Generate with: CredentialEncryptionService.generate_key()
        """
        try:
            key_bytes = encryption_key.encode() if isinstance(encryption_key, str) else encryption_key
            self._fernet = Fernet(key_bytes)
        except Exception as e:
            raise ValueError(f"Invalid Fernet encryption key: {e}") from e

    def encrypt(self, plaintext: str) -> str:
        """Encrypt plaintext to base64 ciphertext."""
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt base64 ciphertext to plaintext."""
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken as e:
            raise ValueError("Failed to decrypt credential - invalid token or key mismatch") from e


class AWSKMSProvider:
    """AWS KMS encryption provider for enterprise deployments.

    Requires boto3 and AWS credentials configured.
    Uses envelope encryption: data key encrypted by KMS, data encrypted locally.
    """

    def __init__(self, key_id: str, region: Optional[str] = None) -> None:
        """
        Initialize AWS KMS provider.

        Args:
            key_id: AWS KMS key ID or ARN
            region: AWS region (defaults to AWS_DEFAULT_REGION)
        """
        try:
            import boto3
        except ImportError:
            raise ImportError("boto3 required for AWS KMS provider: pip install boto3")

        self._key_id = key_id
        self._region = region or os.getenv("AWS_DEFAULT_REGION", "us-east-1")
        self._client = boto3.client("kms", region_name=self._region)

    def encrypt(self, plaintext: str) -> str:
        """Encrypt using KMS envelope encryption."""
        response = self._client.encrypt(
            KeyId=self._key_id,
            Plaintext=plaintext.encode(),
        )
        ciphertext_blob = response["CiphertextBlob"]
        return base64.b64encode(ciphertext_blob).decode()

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt using KMS."""
        ciphertext_blob = base64.b64decode(ciphertext)
        response = self._client.decrypt(
            CiphertextBlob=ciphertext_blob,
        )
        return response["Plaintext"].decode()


class HashiCorpVaultProvider:
    """HashiCorp Vault encryption provider for enterprise deployments.

    Uses Vault's Transit secrets engine for encryption.
    """

    def __init__(
        self,
        vault_addr: str,
        transit_key: str,
        token: Optional[str] = None,
    ) -> None:
        """
        Initialize Vault provider.

        Args:
            vault_addr: Vault server address (e.g., https://vault.example.com:8200)
            transit_key: Transit secrets engine key name
            token: Vault token (defaults to VAULT_TOKEN env var)
        """
        try:
            import hvac
        except ImportError:
            raise ImportError("hvac required for Vault provider: pip install hvac")

        self._transit_key = transit_key
        self._client = hvac.Client(
            url=vault_addr,
            token=token or os.getenv("VAULT_TOKEN"),
        )

        if not self._client.is_authenticated():
            raise ValueError("Failed to authenticate with Vault")

    def encrypt(self, plaintext: str) -> str:
        """Encrypt using Vault Transit."""
        plaintext_b64 = base64.b64encode(plaintext.encode()).decode()
        response = self._client.secrets.transit.encrypt_data(
            name=self._transit_key,
            plaintext=plaintext_b64,
        )
        return response["data"]["ciphertext"]

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt using Vault Transit."""
        response = self._client.secrets.transit.decrypt_data(
            name=self._transit_key,
            ciphertext=ciphertext,
        )
        plaintext_b64 = response["data"]["plaintext"]
        return base64.b64decode(plaintext_b64).decode()


class CredentialEncryptionService:
    """Service for encrypting/decrypting BYOK credentials.

    Supports multiple backends:
    - fernet: Local Fernet encryption (default)
    - aws-kms: AWS Key Management Service
    - vault: HashiCorp Vault Transit

    Configuration via environment variables:
    - BYOK_ENCRYPTION_KEY: Fernet key (required if using fernet)
    - BYOK_KMS_PROVIDER: Provider type (fernet, aws-kms, vault)
    - AWS_KMS_KEY_ID: AWS KMS key ID (if using aws-kms)
    - VAULT_ADDR: Vault address (if using vault)
    - VAULT_TRANSIT_KEY: Vault transit key name (if using vault)
    """

    # Failure lockout threshold
    FAILURE_LOCKOUT_THRESHOLD = 3

    def __init__(
        self,
        provider: Optional[EncryptionProvider] = None,
        encryption_key: Optional[str] = None,
    ) -> None:
        """
        Initialize credential encryption service.

        Args:
            provider: Optional explicit provider instance
            encryption_key: Optional Fernet key (overrides env var)
        """
        if provider:
            self._provider = provider
        else:
            self._provider = self._create_provider_from_env(encryption_key)

    def _create_provider_from_env(self, encryption_key: Optional[str] = None) -> EncryptionProvider:
        """Create provider based on environment configuration."""
        kms_provider = os.getenv("BYOK_KMS_PROVIDER", "fernet").lower()

        if kms_provider == "aws-kms":
            key_id = os.getenv("AWS_KMS_KEY_ID")
            if not key_id:
                raise ValueError("AWS_KMS_KEY_ID required for aws-kms provider")
            return AWSKMSProvider(key_id)

        elif kms_provider == "vault":
            vault_addr = os.getenv("VAULT_ADDR")
            transit_key = os.getenv("VAULT_TRANSIT_KEY")
            if not vault_addr or not transit_key:
                raise ValueError("VAULT_ADDR and VAULT_TRANSIT_KEY required for vault provider")
            return HashiCorpVaultProvider(vault_addr, transit_key)

        else:
            # Default: Fernet
            key = encryption_key or os.getenv("BYOK_ENCRYPTION_KEY")
            if not key:
                # In production, this should fail. In development, we can auto-generate.
                env = os.getenv("AMPREALIZE_ENV", "development")
                if env == "production":
                    raise ValueError(
                        "BYOK_ENCRYPTION_KEY required in production. "
                        "Generate with: python -c \"from amprealize.auth.credential_encryption import CredentialEncryptionService; print(CredentialEncryptionService.generate_key())\""
                    )
                else:
                    logger.warning(
                        "BYOK_ENCRYPTION_KEY not set - generating ephemeral key. "
                        "Credentials will be lost on restart!"
                    )
                    key = self.generate_key()
            return FernetProvider(key)

    @staticmethod
    def generate_key() -> str:
        """Generate a new Fernet encryption key.

        Returns:
            Base64-encoded 32-byte key suitable for BYOK_ENCRYPTION_KEY env var.
        """
        return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()

    def encrypt(self, plaintext: str) -> str:
        """Encrypt an API key for storage.

        Args:
            plaintext: The raw API key

        Returns:
            Encrypted ciphertext safe for database storage
        """
        return self._provider.encrypt(plaintext)

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt a stored API key.

        Args:
            ciphertext: Encrypted credential from database

        Returns:
            Decrypted API key for use in API calls

        Raises:
            ValueError: If decryption fails (wrong key, corrupted data)
        """
        return self._provider.decrypt(ciphertext)

    @staticmethod
    def get_key_prefix(api_key: str, length: int = 8) -> str:
        """Extract prefix for display purposes.

        Example: "sk-proj-abc123xyz789" -> "sk-proj-"

        Args:
            api_key: Full API key
            length: Number of characters to extract (default 8)

        Returns:
            First N characters of the key for identification
        """
        return api_key[:length] if len(api_key) >= length else api_key

    @staticmethod
    def mask_key(api_key: str, show_prefix: int = 8, show_suffix: int = 4) -> str:
        """Create a masked representation of an API key.

        Example: "sk-proj-abc123xyz789000" -> "sk-proj-****0000"

        Args:
            api_key: Full API key
            show_prefix: Characters to show at start
            show_suffix: Characters to show at end

        Returns:
            Masked key with middle replaced by asterisks
        """
        if len(api_key) <= show_prefix + show_suffix:
            return api_key[:show_prefix] + "****"

        prefix = api_key[:show_prefix]
        suffix = api_key[-show_suffix:] if show_suffix > 0 else ""
        return f"{prefix}****{suffix}"
