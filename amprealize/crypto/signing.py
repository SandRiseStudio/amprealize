"""Ed25519 cryptographic signing — OSS Stub.

Full implementation moved to amprealize-enterprise.
This module re-exports stubs from amprealize.crypto for backward compatibility.
"""

from amprealize.crypto import (
    AuditSigner,
    SignatureMetadata,
    SigningError,
    KeyNotLoadedError,
    InvalidSignatureError,
    generate_signing_key,
    load_signer_from_settings,
)

__all__ = [
    "AuditSigner",
    "SignatureMetadata",
    "SigningError",
    "KeyNotLoadedError",
    "InvalidSignatureError",
    "generate_signing_key",
    "load_signer_from_settings",
]
