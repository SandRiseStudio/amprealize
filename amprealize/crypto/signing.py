"""Ed25519 cryptographic signing — OSS Stub.

Re-exports stubs from amprealize.crypto for backward compatibility.
The enterprise edition provides a full signing implementation.
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
