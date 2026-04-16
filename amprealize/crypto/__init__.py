"""Cryptographic utilities for amprealize platform.

Provides no-op stubs so consumers degrade gracefully.
The enterprise edition provides real Ed25519 signing.
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


class AuditSigner:
    """No-op audit signer for OSS builds.

    Returns empty signatures and always passes verification.
    The enterprise fork provides real Ed25519 signing.
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
    """No-op in OSS. Enterprise fork provides real Ed25519 key generation."""
    return AuditSigner()


def load_signer_from_settings(**kwargs):
    """Load a signer from settings. Returns no-op signer in OSS."""
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
