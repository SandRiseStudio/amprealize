"""
MFA (Multi-Factor Authentication) service.

Provides TOTP-based MFA implementation using pyotp.

Behavior: behavior_lock_down_security_surface
"""

from __future__ import annotations

import base64
import io
import secrets
from typing import List, Optional, Tuple

import pyotp
import qrcode
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class MfaService:
    """Service for managing TOTP-based multi-factor authentication.

    Uses pyotp for TOTP generation/verification and Fernet for secret encryption.
    """

    def __init__(self, encryption_key: str):
        """
        Initialize MFA service.

        Args:
            encryption_key: Base64-encoded 32-byte key for encrypting TOTP secrets.
                           Generate with: base64.urlsafe_b64encode(os.urandom(32)).decode()
        """
        self._fernet = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)

    @staticmethod
    def generate_encryption_key() -> str:
        """Generate a new encryption key for MFA secrets."""
        return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()

    def generate_secret(self) -> str:
        """
        Generate a new TOTP secret.

        Returns:
            Base32-encoded secret (unencrypted)
        """
        return pyotp.random_base32()

    def encrypt_secret(self, secret: str) -> str:
        """
        Encrypt a TOTP secret for storage.

        Args:
            secret: Base32-encoded TOTP secret

        Returns:
            Encrypted secret string
        """
        return self._fernet.encrypt(secret.encode()).decode()

    def decrypt_secret(self, encrypted_secret: str) -> str:
        """
        Decrypt a stored TOTP secret.

        Args:
            encrypted_secret: Encrypted secret from storage

        Returns:
            Decrypted Base32-encoded secret
        """
        return self._fernet.decrypt(encrypted_secret.encode()).decode()

    def get_totp(self, secret: str) -> pyotp.TOTP:
        """
        Create a TOTP object from a secret.

        Args:
            secret: Base32-encoded TOTP secret

        Returns:
            pyotp.TOTP object
        """
        return pyotp.TOTP(secret)

    def verify_code(self, secret: str, code: str, valid_window: int = 1) -> bool:
        """
        Verify a TOTP code.

        Args:
            secret: Base32-encoded TOTP secret
            code: 6-digit code from authenticator app
            valid_window: Number of 30-second windows to check (default: 1 = ±30 seconds)

        Returns:
            True if code is valid
        """
        totp = self.get_totp(secret)
        return totp.verify(code, valid_window=valid_window)

    def get_current_code(self, secret: str) -> str:
        """
        Get the current TOTP code (for testing purposes).

        Args:
            secret: Base32-encoded TOTP secret

        Returns:
            Current 6-digit code
        """
        totp = self.get_totp(secret)
        return totp.now()

    def get_provisioning_uri(
        self,
        secret: str,
        username: str,
        issuer: str = "Amprealize",
    ) -> str:
        """
        Generate a provisioning URI for authenticator apps.

        Args:
            secret: Base32-encoded TOTP secret
            username: User identifier (usually email or username)
            issuer: Service name shown in authenticator app

        Returns:
            otpauth:// URI for QR code
        """
        totp = self.get_totp(secret)
        return totp.provisioning_uri(name=username, issuer_name=issuer)

    def generate_qr_code_base64(
        self,
        secret: str,
        username: str,
        issuer: str = "Amprealize",
    ) -> str:
        """
        Generate a QR code as base64-encoded PNG.

        Args:
            secret: Base32-encoded TOTP secret
            username: User identifier
            issuer: Service name

        Returns:
            Base64-encoded PNG image data
        """
        uri = self.get_provisioning_uri(secret, username, issuer)

        # Generate QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(uri)
        qr.make(fit=True)

        # Create image
        img = qr.make_image(fill_color="black", back_color="white")

        # Convert to base64
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)

        return base64.b64encode(buffer.getvalue()).decode()

    def generate_backup_codes(self, count: int = 10) -> List[str]:
        """
        Generate backup codes for account recovery.

        Args:
            count: Number of codes to generate

        Returns:
            List of 8-character alphanumeric backup codes
        """
        codes = []
        for _ in range(count):
            # Generate 8-character code in format XXXX-XXXX
            code = secrets.token_hex(4).upper()
            codes.append(f"{code[:4]}-{code[4:]}")
        return codes

    def encrypt_backup_codes(self, codes: List[str]) -> str:
        """
        Encrypt backup codes for storage.

        Args:
            codes: List of backup codes

        Returns:
            Encrypted JSON string
        """
        import json
        return self._fernet.encrypt(json.dumps(codes).encode()).decode()

    def decrypt_backup_codes(self, encrypted_codes: str) -> List[str]:
        """
        Decrypt stored backup codes.

        Args:
            encrypted_codes: Encrypted codes from storage

        Returns:
            List of backup codes
        """
        import json
        return json.loads(self._fernet.decrypt(encrypted_codes.encode()).decode())

    def verify_backup_code(
        self,
        encrypted_codes: str,
        code: str,
    ) -> Tuple[bool, Optional[str]]:
        """
        Verify a backup code and remove it from the list.

        Args:
            encrypted_codes: Encrypted backup codes from storage
            code: Backup code to verify

        Returns:
            Tuple of (is_valid, new_encrypted_codes or None if invalid)
        """
        codes = self.decrypt_backup_codes(encrypted_codes)

        # Normalize code (remove dashes, uppercase)
        normalized = code.upper().replace("-", "")
        normalized_with_dash = f"{normalized[:4]}-{normalized[4:]}" if len(normalized) == 8 else code

        if normalized_with_dash in codes:
            codes.remove(normalized_with_dash)
            new_encrypted = self.encrypt_backup_codes(codes) if codes else None
            return True, new_encrypted

        return False, None


# Singleton instance for the default MFA service
_mfa_service: Optional[MfaService] = None


def get_mfa_service(encryption_key: Optional[str] = None) -> MfaService:
    """
    Get or create the MFA service singleton.

    Args:
        encryption_key: Encryption key for TOTP secrets (required on first call)

    Returns:
        MfaService instance
    """
    global _mfa_service
    if _mfa_service is None:
        if encryption_key is None:
            raise ValueError("encryption_key required for first MfaService initialization")
        _mfa_service = MfaService(encryption_key)
    return _mfa_service
