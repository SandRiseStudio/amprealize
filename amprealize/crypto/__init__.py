"""Cryptographic utilities for amprealize platform — OSS Stub.

The full Ed25519 signing implementation has moved to amprealize-enterprise.
Install amprealize-enterprise[crypto] for audit log signing.

OSS provides NoOp stubs so consumers degrade gracefully.
"""

# Exception classes are kept in OSS for compatible error handling
class SigningError(Exception):
    """Base exception for signing operations."""
    pass


class KeyNotLoadedError(SigningError):
    """Raised when attempting to sign without a loaded key."""
    pass


class InvalidSignatureError(SigningError):
    """Raised when signature verification fails."""
    pass


class SignatureMetadata:
    """Metadata for a signature (no-op stub)."""
    def __init__(self, algorithm="none", key_id="", signed_at="", signature_b64=""):
        self.algorithm = algorithm
        self.key_id = key_id
        self.signed_at = signed_at
        self.signature_b64 = signature_b64


try:
    from amprealize_enterprise.crypto.signing import (
        AuditSigner,
        generate_signing_key,
        load_signer_from_settings,
    )
except ImportError:

    class AuditSigner:  # type: ignore[no-redef]
        """No-op audit signer for OSS builds.

        Returns empty signatures and always passes verification.
        Install amprealize-enterprise[crypto] for real Ed25519 signing.
        """

        def __init__(self, **kwargs):
            pass

        @property
        def is_loaded(self) -> bool:
            return False

        @property
        def can_sign(self) -> bool:
            return False

        @property
        def can_verify(self) -> bool:
            return False

        @property
        def key_id(self):
            return None

        def generate_key_pair(self):
            return self

        def sign_record(self, record_bytes, **kwargs):
            return SignatureMetadata()

        def verify_record(self, record_bytes, signature, **kwargs):
            return True

        def sign_bytes(self, data):
            return b""

    def generate_signing_key(**kwargs):
        raise ImportError(
            "Signing key generation requires amprealize-enterprise[crypto]. "
            "Install with: pip install amprealize-enterprise[crypto]"
        )

    def load_signer_from_settings(**kwargs):
        return AuditSigner()


__all__ = [
    "AuditSigner",
    "SignatureMetadata",
    "SigningError",
    "KeyNotLoadedError",
    "InvalidSignatureError",
    "generate_signing_key",
    "load_signer_from_settings",
]
