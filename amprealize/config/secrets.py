"""Secrets management abstraction for multi-environment deployments.

Provides unified interface for retrieving secrets from:
- Environment variables (local development)
- AWS Secrets Manager (production)
- GCP Secret Manager (GCP deployments)
- Azure Key Vault (Azure deployments)

Behaviors referenced:
- behavior_lock_down_security_surface: Secrets abstraction layer
- behavior_externalize_configuration: Provider selection via settings
- behavior_prevent_secret_leaks: Never log or expose secret values
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

try:
    import boto3
    from botocore.exceptions import ClientError
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False

# Import settings for multi-environment configuration
try:
    from amprealize.config.settings import settings
    SETTINGS_AVAILABLE = True
except ImportError:
    SETTINGS_AVAILABLE = False


class SecretsManager:
    """Multi-provider secrets management with automatic fallback."""

    def __init__(self, provider: Optional[str] = None, prefix: Optional[str] = None):
        """Initialize secrets manager with provider selection.

        Args:
            provider: Secret provider ('env', 'aws-secrets', 'gcp-secret', 'azure-vault')
                     If None, uses settings.secrets.provider
            prefix: Secret path prefix (e.g., 'amprealize/production')
                   If None, uses settings.secrets.secret_path_prefix
        """
        if SETTINGS_AVAILABLE and provider is None:
            self.provider = settings.secrets.provider  # type: ignore[possibly-unbound]
            self.prefix = prefix or settings.secrets.secret_path_prefix  # type: ignore[possibly-unbound]
        else:
            self.provider = provider or "env"
            self.prefix = prefix or "amprealize"

        # Initialize provider-specific clients
        self._aws_client: Optional[Any] = None
        self._gcp_client: Optional[Any] = None
        self._azure_client: Optional[Any] = None

        if self.provider == "aws-secrets" and BOTO3_AVAILABLE:
            self._aws_client = boto3.client("secretsmanager")

    def get_secret(self, key: str, *, default: Optional[str] = None) -> Optional[str]:
        """Retrieve a secret value by key.

        Args:
            key: Secret key/name (e.g., 'database_password')
            default: Default value if secret not found

        Returns:
            Secret value as string or default if not found

        Raises:
            RuntimeError: If provider is misconfigured or unavailable
        """
        if self.provider == "env":
            return self._get_from_env(key, default=default)
        elif self.provider == "aws-secrets":
            return self._get_from_aws(key, default=default)
        elif self.provider == "gcp-secret":
            return self._get_from_gcp(key, default=default)
        elif self.provider == "azure-vault":
            return self._get_from_azure(key, default=default)
        else:
            raise ValueError(f"Unknown secrets provider: {self.provider}")

    def get_secret_json(self, key: str, *, default: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Retrieve a secret that contains JSON data.

        Args:
            key: Secret key/name
            default: Default dict if secret not found

        Returns:
            Parsed JSON dict or default if not found
        """
        value = self.get_secret(key)
        if value is None:
            return default

        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default

    def _get_from_env(self, key: str, *, default: Optional[str] = None) -> Optional[str]:
        """Retrieve secret from environment variable.

        Args:
            key: Environment variable name (will be uppercased)
            default: Default value if not found

        Returns:
            Environment variable value or default
        """
        env_key = key.upper()
        return os.getenv(env_key, default)

    def _get_from_aws(self, key: str, *, default: Optional[str] = None) -> Optional[str]:
        """Retrieve secret from AWS Secrets Manager.

        Args:
            key: Secret name (will be prefixed with self.prefix)
            default: Default value if not found

        Returns:
            Secret value or default

        Raises:
            RuntimeError: If AWS Secrets Manager is unavailable
        """
        if not BOTO3_AVAILABLE or self._aws_client is None:
            raise RuntimeError(
                "AWS Secrets Manager requires boto3. Install with: pip install boto3"
            )

        secret_name = f"{self.prefix}/{key}"

        try:
            response = self._aws_client.get_secret_value(SecretId=secret_name)

            # Secrets can be stored as SecretString or SecretBinary
            if "SecretString" in response:
                return response["SecretString"]
            else:
                # Handle binary secrets (base64 decode if needed)
                return response["SecretBinary"].decode("utf-8")

        except ClientError as e:  # type: ignore[possibly-unbound]
            error_code = e.response["Error"]["Code"]

            if error_code == "ResourceNotFoundException":
                # Secret doesn't exist, return default
                return default
            elif error_code == "InvalidRequestException":
                # Invalid request format
                raise RuntimeError(f"Invalid AWS secret request: {secret_name}") from e
            elif error_code == "InvalidParameterException":
                # Invalid parameter value
                raise RuntimeError(f"Invalid AWS secret parameter: {secret_name}") from e
            else:
                # Other AWS errors
                raise RuntimeError(f"AWS Secrets Manager error: {error_code}") from e

    def _get_from_gcp(self, key: str, *, default: Optional[str] = None) -> Optional[str]:
        """Retrieve secret from GCP Secret Manager.

        Args:
            key: Secret name
            default: Default value if not found

        Returns:
            Secret value or default

        Raises:
            NotImplementedError: GCP Secret Manager not yet implemented
        """
        # TODO: Implement GCP Secret Manager support
        # Requires: pip install google-cloud-secret-manager
        raise NotImplementedError(
            "GCP Secret Manager support not yet implemented. "
            "Use provider='env' or provider='aws-secrets'"
        )

    def _get_from_azure(self, key: str, *, default: Optional[str] = None) -> Optional[str]:
        """Retrieve secret from Azure Key Vault.

        Args:
            key: Secret name
            default: Default value if not found

        Returns:
            Secret value or default

        Raises:
            NotImplementedError: Azure Key Vault not yet implemented
        """
        # TODO: Implement Azure Key Vault support
        # Requires: pip install azure-keyvault-secrets azure-identity
        raise NotImplementedError(
            "Azure Key Vault support not yet implemented. "
            "Use provider='env' or provider='aws-secrets'"
        )

    def set_secret(self, key: str, value: str) -> None:
        """Store a secret value (only supported for writable providers).

        Args:
            key: Secret key/name
            value: Secret value to store

        Raises:
            NotImplementedError: Secret writing not yet fully implemented
        """
        if self.provider == "env":
            raise RuntimeError(
                "Cannot write secrets to environment variables. "
                "Use cloud provider or manual configuration."
            )

        # TODO: Implement secret writing for AWS/GCP/Azure
        raise NotImplementedError(
            f"Secret writing not yet implemented for provider={self.provider}"
        )


# Singleton instance for convenience
_secrets_manager: Optional[SecretsManager] = None


def get_secrets_manager() -> SecretsManager:
    """Get or create the global SecretsManager instance.

    Returns:
        Singleton SecretsManager instance
    """
    global _secrets_manager
    if _secrets_manager is None:
        _secrets_manager = SecretsManager()
    return _secrets_manager


def get_secret(key: str, *, default: Optional[str] = None) -> Optional[str]:
    """Convenience function to retrieve a secret from the global manager.

    Args:
        key: Secret key/name
        default: Default value if not found

    Returns:
        Secret value or default
    """
    return get_secrets_manager().get_secret(key, default=default)
