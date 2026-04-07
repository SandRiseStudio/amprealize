#!/usr/bin/env python3
"""Phase 8 Token Vault Test Suite.

Validates the KMS-encrypted token vault implementation for MCP Auth.

Tests cover:
1. Token storage and encryption
2. Token retrieval and decryption
3. Token rotation
4. Token revocation and blacklisting
5. Automatic expiration handling
6. Singleton pattern
7. Multiple encryption providers
8. Cleanup operations
9. Statistics tracking
10. Edge cases and error handling

Usage:
    python scripts/test_phase8_token_vault.py

Behavior: behavior_design_test_strategy, behavior_lock_down_security_surface
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_token_vault_initialization():
    """Test 1: TokenVault initialization with different providers."""
    print("\n" + "=" * 70)
    print("Test 1: TokenVault Initialization")
    print("=" * 70)

    from amprealize.auth.token_vault import (
        TokenVault,
        InMemoryTokenStorage,
        TokenType,
        TokenStatus,
        reset_token_vault,
    )

    reset_token_vault()  # Clear singleton

    # Test Fernet provider
    storage = InMemoryTokenStorage()
    key = TokenVault.generate_fernet_key()
    vault = TokenVault.create_fernet(storage, key)

    assert vault is not None
    print("✓ Created TokenVault with Fernet provider")

    # Test key generation
    key2 = TokenVault.generate_fernet_key()
    assert key != key2  # Keys should be different
    assert len(key) == 44  # Base64-encoded 32-byte key
    print(f"✓ Generated Fernet key: {key[:20]}...")

    # Verify storage backend
    assert vault._storage is storage
    print("✓ Storage backend attached correctly")

    print("\n✅ Test 1 PASSED: TokenVault initialization works")
    return True


def test_token_storage_and_retrieval():
    """Test 2: Store and retrieve tokens with encryption."""
    print("\n" + "=" * 70)
    print("Test 2: Token Storage and Retrieval")
    print("=" * 70)

    from amprealize.auth.token_vault import (
        TokenVault,
        InMemoryTokenStorage,
        TokenType,
        TokenStatus,
    )

    storage = InMemoryTokenStorage()
    key = TokenVault.generate_fernet_key()
    vault = TokenVault.create_fernet(storage, key)

    async def run_test():
        # Store a token
        token = await vault.store_token(
            user_id="user-123",
            provider="google",
            access_token="ya29.access_token_here",
            refresh_token="1//refresh_token_here",
            scopes=["openid", "email", "profile"],
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            metadata={"client_id": "google-oauth-client"},
        )

        assert token.id is not None
        assert token.user_id == "user-123"
        assert token.provider == "google"
        assert token.status == TokenStatus.ACTIVE
        print(f"✓ Stored token with ID: {token.id}")

        # Verify encryption in storage
        stored = await storage.get_token("user-123", "google", TokenType.ACCESS)
        assert stored is not None
        _, encrypted_data = stored
        assert "ya29.access_token_here" not in encrypted_data  # Must be encrypted
        print("✓ Token is encrypted in storage")

        # Retrieve token
        retrieved = await vault.get_token("user-123", "google")
        assert retrieved is not None
        assert retrieved.access_token == "ya29.access_token_here"
        assert retrieved.refresh_token == "1//refresh_token_here"
        assert retrieved.scopes == ["openid", "email", "profile"]
        print("✓ Retrieved and decrypted token successfully")

        # Verify last_used_at updated
        assert retrieved.last_used_at is not None
        print("✓ last_used_at timestamp updated on access")

        return True

    result = asyncio.run(run_test())
    print("\n✅ Test 2 PASSED: Token storage and retrieval works")
    return result


def test_token_expiration():
    """Test 3: Token expiration handling."""
    print("\n" + "=" * 70)
    print("Test 3: Token Expiration Handling")
    print("=" * 70)

    from amprealize.auth.token_vault import (
        TokenVault,
        InMemoryTokenStorage,
        TokenType,
        StoredToken,
    )

    storage = InMemoryTokenStorage()
    key = TokenVault.generate_fernet_key()
    vault = TokenVault.create_fernet(storage, key)

    async def run_test():
        # Store an already-expired token
        await vault.store_token(
            user_id="user-456",
            provider="github",
            access_token="gho_expired_token",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),  # Expired!
        )
        print("✓ Stored expired token")

        # Try to retrieve expired token
        retrieved = await vault.get_token("user-456", "github")
        assert retrieved is None  # Should not return expired tokens
        print("✓ Expired token not returned by get_token()")

        # Store a token that's about to expire
        soon_expiring = await vault.store_token(
            user_id="user-789",
            provider="microsoft",
            access_token="eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9",
            refresh_token="0.refresh_token",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=6),  # Within rotation threshold
        )

        # Check needs_rotation
        assert soon_expiring.needs_rotation(timedelta(hours=12))  # 12 hours threshold
        print("✓ Token correctly identified as needing rotation")

        return True

    result = asyncio.run(run_test())
    print("\n✅ Test 3 PASSED: Token expiration handling works")
    return result


def test_token_revocation():
    """Test 4: Token revocation and blacklisting."""
    print("\n" + "=" * 70)
    print("Test 4: Token Revocation and Blacklisting")
    print("=" * 70)

    from amprealize.auth.token_vault import (
        TokenVault,
        InMemoryTokenStorage,
        TokenType,
    )

    storage = InMemoryTokenStorage()
    key = TokenVault.generate_fernet_key()
    vault = TokenVault.create_fernet(storage, key)

    async def run_test():
        # Store a token
        token = await vault.store_token(
            user_id="user-revoke",
            provider="google",
            access_token="ya29.token_to_revoke",
            refresh_token="1//refresh_to_revoke",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        print(f"✓ Stored token for revocation test: {token.id}")

        # Verify token is accessible
        retrieved = await vault.get_token("user-revoke", "google")
        assert retrieved is not None
        print("✓ Token accessible before revocation")

        # Revoke the token
        revoked = await vault.revoke_token(
            user_id="user-revoke",
            provider="google",
            reason="User logged out",
            revoked_by="user-revoke",
        )
        assert revoked is True
        print("✓ Token revoked successfully")

        # Check blacklist
        is_blacklisted = await vault.check_blacklist("ya29.token_to_revoke")
        assert is_blacklisted is True
        print("✓ Access token is blacklisted")

        is_refresh_blacklisted = await vault.check_blacklist("1//refresh_to_revoke")
        assert is_refresh_blacklisted is True
        print("✓ Refresh token is also blacklisted")

        # Try to retrieve revoked token
        retrieved = await vault.get_token("user-revoke", "google")
        assert retrieved is None  # Should not return revoked tokens
        print("✓ Revoked token not returned by get_token()")

        return True

    result = asyncio.run(run_test())
    print("\n✅ Test 4 PASSED: Token revocation and blacklisting works")
    return result


def test_token_rotation():
    """Test 5: Token rotation."""
    print("\n" + "=" * 70)
    print("Test 5: Token Rotation")
    print("=" * 70)

    from amprealize.auth.token_vault import (
        TokenVault,
        InMemoryTokenStorage,
        TokenType,
    )

    storage = InMemoryTokenStorage()
    key = TokenVault.generate_fernet_key()
    vault = TokenVault.create_fernet(storage, key)

    async def run_test():
        # Store initial token
        old_token = await vault.store_token(
            user_id="user-rotate",
            provider="google",
            access_token="ya29.old_access_token",
            refresh_token="1//old_refresh_token",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        assert old_token.rotation_count == 0
        print(f"✓ Stored initial token (rotation_count=0)")

        # Rotate the token
        new_token = await vault.rotate_token(
            user_id="user-rotate",
            provider="google",
            new_access_token="ya29.new_access_token",
            new_refresh_token="1//new_refresh_token",
            new_expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
        )

        assert new_token is not None
        assert new_token.id == old_token.id  # Same ID for continuity
        assert new_token.rotation_count == 1
        print(f"✓ Token rotated (rotation_count=1)")

        # Verify old token is blacklisted
        is_old_blacklisted = await vault.check_blacklist("ya29.old_access_token")
        assert is_old_blacklisted is True
        print("✓ Old access token is blacklisted after rotation")

        # Verify new token is accessible
        retrieved = await vault.get_token("user-rotate", "google")
        assert retrieved is not None
        assert retrieved.access_token == "ya29.new_access_token"
        print("✓ New token is accessible")

        # Rotate again
        new_token2 = await vault.rotate_token(
            user_id="user-rotate",
            provider="google",
            new_access_token="ya29.newer_access_token",
            new_expires_at=datetime.now(timezone.utc) + timedelta(hours=3),
        )
        assert new_token2.rotation_count == 2
        print(f"✓ Token rotated again (rotation_count=2)")

        return True

    result = asyncio.run(run_test())
    print("\n✅ Test 5 PASSED: Token rotation works")
    return result


def test_token_listing():
    """Test 6: List tokens for a user."""
    print("\n" + "=" * 70)
    print("Test 6: Token Listing")
    print("=" * 70)

    from amprealize.auth.token_vault import (
        TokenVault,
        InMemoryTokenStorage,
        TokenType,
    )

    storage = InMemoryTokenStorage()
    key = TokenVault.generate_fernet_key()
    vault = TokenVault.create_fernet(storage, key)

    async def run_test():
        # Store multiple tokens for a user
        await vault.store_token(
            user_id="user-list",
            provider="google",
            access_token="google_token",
            scopes=["email", "profile"],
        )

        await vault.store_token(
            user_id="user-list",
            provider="github",
            access_token="github_token",
            scopes=["repo", "user"],
        )

        await vault.store_token(
            user_id="user-list",
            provider="microsoft",
            access_token="microsoft_token",
            scopes=["openid"],
        )

        # Store token for different user
        await vault.store_token(
            user_id="other-user",
            provider="google",
            access_token="other_google_token",
        )

        print("✓ Stored 4 tokens (3 for user-list, 1 for other-user)")

        # List all tokens for user-list
        tokens = await vault.list_tokens("user-list")
        assert len(tokens) == 3
        print(f"✓ Listed {len(tokens)} tokens for user-list")

        # Verify tokens are redacted
        for token in tokens:
            assert token.access_token == "[REDACTED]"
        print("✓ Token values are redacted in list")

        # List tokens with provider filter
        google_tokens = await vault.list_tokens("user-list", provider="google")
        assert len(google_tokens) == 1
        assert google_tokens[0].provider == "google"
        print("✓ Provider filter works correctly")

        # Verify other user's tokens not included
        other_tokens = await vault.list_tokens("other-user")
        assert len(other_tokens) == 1
        print("✓ User isolation works correctly")

        return True

    result = asyncio.run(run_test())
    print("\n✅ Test 6 PASSED: Token listing works")
    return result


def test_cleanup_expired():
    """Test 7: Cleanup of expired tokens and blacklist entries."""
    print("\n" + "=" * 70)
    print("Test 7: Cleanup of Expired Entries")
    print("=" * 70)

    from amprealize.auth.token_vault import (
        TokenVault,
        InMemoryTokenStorage,
        TokenType,
        TokenStatus,
        TokenBlacklistEntry,
    )

    storage = InMemoryTokenStorage()
    key = TokenVault.generate_fernet_key()
    vault = TokenVault.create_fernet(storage, key)

    async def run_test():
        # Store expired token (marked as expired status)
        expired_token = await vault.store_token(
            user_id="user-cleanup",
            provider="google",
            access_token="expired_token",
            expires_at=datetime.now(timezone.utc) - timedelta(days=7),
        )
        # Mark as expired
        await storage.update_token(expired_token.id, {"status": TokenStatus.EXPIRED})

        # Store active token
        active_token = await vault.store_token(
            user_id="user-cleanup-2",
            provider="github",
            access_token="active_token",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        # Add expired blacklist entry
        expired_blacklist = TokenBlacklistEntry(
            token_hash="expired_hash_123",
            user_id="user-cleanup",
            provider="google",
            reason="Test cleanup",
            revoked_at=datetime.now(timezone.utc) - timedelta(days=31),
            revoked_by="test",
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),  # Expired
        )
        await storage.add_to_blacklist(expired_blacklist)

        # Add valid blacklist entry
        valid_blacklist = TokenBlacklistEntry(
            token_hash="valid_hash_456",
            user_id="user-cleanup-2",
            provider="github",
            reason="Test valid",
            revoked_at=datetime.now(timezone.utc),
            revoked_by="test",
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        await storage.add_to_blacklist(valid_blacklist)

        print("✓ Created expired and active tokens + blacklist entries")

        # Get stats before cleanup
        stats_before = await vault.get_stats()
        print(f"  Before: {stats_before.total_tokens} tokens, {stats_before.blacklist_size} blacklist entries")

        # Run cleanup
        deleted = await vault.cleanup_expired()
        print(f"✓ Cleanup deleted {deleted} entries")

        # Get stats after cleanup
        stats_after = await vault.get_stats()
        print(f"  After: {stats_after.total_tokens} tokens, {stats_after.blacklist_size} blacklist entries")

        # Verify expired entries were cleaned
        assert deleted >= 1  # At least the expired blacklist entry

        # Verify active entries remain
        active = await vault.get_token("user-cleanup-2", "github")
        assert active is not None
        print("✓ Active tokens preserved after cleanup")

        return True

    result = asyncio.run(run_test())
    print("\n✅ Test 7 PASSED: Cleanup works correctly")
    return result


def test_vault_stats():
    """Test 8: Vault statistics."""
    print("\n" + "=" * 70)
    print("Test 8: Vault Statistics")
    print("=" * 70)

    from amprealize.auth.token_vault import (
        TokenVault,
        InMemoryTokenStorage,
        TokenType,
        TokenStatus,
    )

    storage = InMemoryTokenStorage()
    key = TokenVault.generate_fernet_key()
    vault = TokenVault.create_fernet(storage, key)

    async def run_test():
        # Store tokens for stats
        await vault.store_token(
            user_id="stats-user-1",
            provider="google",
            access_token="google_1",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        await vault.store_token(
            user_id="stats-user-2",
            provider="google",
            access_token="google_2",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        await vault.store_token(
            user_id="stats-user-3",
            provider="github",
            access_token="github_1",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        # Revoke one token
        await vault.revoke_token("stats-user-1", "google", "Test", "test")

        # Get stats
        stats = await vault.get_stats()

        assert stats.total_tokens == 3
        assert stats.active_tokens >= 2
        assert stats.revoked_tokens == 1
        assert stats.blacklist_size >= 1
        assert "google" in stats.providers
        assert "github" in stats.providers
        assert stats.providers["google"] == 2
        assert stats.providers["github"] == 1

        print(f"✓ Total tokens: {stats.total_tokens}")
        print(f"✓ Active tokens: {stats.active_tokens}")
        print(f"✓ Revoked tokens: {stats.revoked_tokens}")
        print(f"✓ Blacklist size: {stats.blacklist_size}")
        print(f"✓ Provider breakdown: {stats.providers}")

        return True

    result = asyncio.run(run_test())
    print("\n✅ Test 8 PASSED: Vault statistics work correctly")
    return result


def test_singleton_pattern():
    """Test 9: Singleton pattern for TokenVault."""
    print("\n" + "=" * 70)
    print("Test 9: Singleton Pattern")
    print("=" * 70)

    from amprealize.auth.token_vault import (
        get_token_vault,
        reset_token_vault,
        InMemoryTokenStorage,
    )

    # Reset any existing singleton
    reset_token_vault()

    # Create with storage
    storage = InMemoryTokenStorage()
    vault1 = get_token_vault(storage=storage)

    # Get again - should return same instance
    vault2 = get_token_vault()

    assert vault1 is vault2
    print("✓ Singleton returns same instance")

    # Reset and create new
    reset_token_vault()
    vault3 = get_token_vault()

    assert vault1 is not vault3
    print("✓ reset_token_vault() creates new instance")

    # Verify auto-generation of key when no env vars
    assert vault3 is not None
    print("✓ Auto-generates encryption key when not configured")

    print("\n✅ Test 9 PASSED: Singleton pattern works correctly")
    return True


def test_stored_token_dataclass():
    """Test 10: StoredToken dataclass methods."""
    print("\n" + "=" * 70)
    print("Test 10: StoredToken Dataclass")
    print("=" * 70)

    from amprealize.auth.token_vault import StoredToken, TokenType, TokenStatus

    # Create token
    token = StoredToken(
        id="test-123",
        user_id="user-abc",
        provider="google",
        token_type=TokenType.ACCESS,
        access_token="access_here",
        refresh_token="refresh_here",
        scopes=["email", "profile"],
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        metadata={"client": "test"},
    )

    # Test to_dict
    token_dict = token.to_dict()
    assert token_dict["id"] == "test-123"
    assert token_dict["user_id"] == "user-abc"
    assert token_dict["token_type"] == "access"
    assert token_dict["scopes"] == ["email", "profile"]
    print("✓ to_dict() works correctly")

    # Test from_dict
    restored = StoredToken.from_dict(token_dict)
    assert restored.id == token.id
    assert restored.user_id == token.user_id
    assert restored.token_type == token.token_type
    assert restored.scopes == token.scopes
    print("✓ from_dict() works correctly")

    # Test is_expired
    future_token = StoredToken(
        id="future-1",
        user_id="user",
        provider="google",
        token_type=TokenType.ACCESS,
        access_token="token",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    assert future_token.is_expired() is False
    print("✓ is_expired() returns False for future expiry")

    past_token = StoredToken(
        id="past-1",
        user_id="user",
        provider="google",
        token_type=TokenType.ACCESS,
        access_token="token",
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    assert past_token.is_expired() is True
    print("✓ is_expired() returns True for past expiry")

    # Test needs_rotation
    needs_rotation_token = StoredToken(
        id="rotate-1",
        user_id="user",
        provider="google",
        token_type=TokenType.ACCESS,
        access_token="token",
        refresh_token="refresh",  # Has refresh token
        expires_at=datetime.now(timezone.utc) + timedelta(hours=6),  # Within 12 hour threshold
    )
    assert needs_rotation_token.needs_rotation(timedelta(hours=12)) is True
    print("✓ needs_rotation() returns True when within threshold")

    no_rotation_token = StoredToken(
        id="no-rotate-1",
        user_id="user",
        provider="google",
        token_type=TokenType.ACCESS,
        access_token="token",
        refresh_token="refresh",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),  # Far future
    )
    assert no_rotation_token.needs_rotation(timedelta(hours=12)) is False
    print("✓ needs_rotation() returns False when far from expiry")

    print("\n✅ Test 10 PASSED: StoredToken dataclass works correctly")
    return True


def test_multiple_providers():
    """Test 11: Multiple OAuth providers."""
    print("\n" + "=" * 70)
    print("Test 11: Multiple OAuth Providers")
    print("=" * 70)

    from amprealize.auth.token_vault import (
        TokenVault,
        InMemoryTokenStorage,
        TokenProvider,
    )

    storage = InMemoryTokenStorage()
    key = TokenVault.generate_fernet_key()
    vault = TokenVault.create_fernet(storage, key)

    async def run_test():
        # Store tokens for multiple providers
        await vault.store_token(
            user_id="multi-user",
            provider=TokenProvider.GOOGLE.value,
            access_token="google_token",
            scopes=["email"],
        )

        await vault.store_token(
            user_id="multi-user",
            provider=TokenProvider.GITHUB.value,
            access_token="github_token",
            scopes=["repo"],
        )

        await vault.store_token(
            user_id="multi-user",
            provider=TokenProvider.MICROSOFT.value,
            access_token="microsoft_token",
            scopes=["openid"],
        )

        await vault.store_token(
            user_id="multi-user",
            provider=TokenProvider.AMPREALIZE.value,
            access_token="amprealize_internal_token",
            scopes=["behaviors:read"],
        )

        print("✓ Stored tokens for 4 different providers")

        # Retrieve each
        google = await vault.get_token("multi-user", TokenProvider.GOOGLE.value)
        github = await vault.get_token("multi-user", TokenProvider.GITHUB.value)
        microsoft = await vault.get_token("multi-user", TokenProvider.MICROSOFT.value)
        amprealize = await vault.get_token("multi-user", TokenProvider.AMPREALIZE.value)

        assert google.access_token == "google_token"
        assert github.access_token == "github_token"
        assert microsoft.access_token == "microsoft_token"
        assert amprealize.access_token == "amprealize_internal_token"

        print("✓ Retrieved tokens for all providers correctly")

        # List all tokens
        tokens = await vault.list_tokens("multi-user")
        assert len(tokens) == 4
        providers = {t.provider for t in tokens}
        assert providers == {"google", "github", "microsoft", "amprealize"}
        print("✓ Listed all provider tokens")

        return True

    result = asyncio.run(run_test())
    print("\n✅ Test 11 PASSED: Multiple OAuth providers work correctly")
    return result


def test_error_handling():
    """Test 12: Error handling and edge cases."""
    print("\n" + "=" * 70)
    print("Test 12: Error Handling and Edge Cases")
    print("=" * 70)

    from amprealize.auth.token_vault import (
        TokenVault,
        InMemoryTokenStorage,
        TokenType,
    )

    storage = InMemoryTokenStorage()
    key = TokenVault.generate_fernet_key()
    vault = TokenVault.create_fernet(storage, key)

    async def run_test():
        # Get non-existent token
        result = await vault.get_token("nonexistent-user", "google")
        assert result is None
        print("✓ Returns None for non-existent token")

        # Revoke non-existent token
        revoked = await vault.revoke_token(
            user_id="nonexistent-user",
            provider="google",
            reason="Test",
            revoked_by="test",
        )
        assert revoked is False
        print("✓ Revoke returns False for non-existent token")

        # Rotate non-existent token
        rotated = await vault.rotate_token(
            user_id="nonexistent-user",
            provider="google",
            new_access_token="new_token",
        )
        assert rotated is None
        print("✓ Rotate returns None for non-existent token")

        # Check blacklist for random hash
        is_blacklisted = await vault.check_blacklist("random_token_never_existed")
        assert is_blacklisted is False
        print("✓ Blacklist returns False for unknown token")

        # Store token with minimal fields
        minimal = await vault.store_token(
            user_id="minimal-user",
            provider="custom",
            access_token="minimal_token",
        )
        assert minimal.id is not None
        assert minimal.refresh_token is None
        assert minimal.expires_at is None
        assert minimal.scopes == []
        print("✓ Handles minimal token (no optional fields)")

        # List tokens for user with no tokens
        empty_list = await vault.list_tokens("user-with-no-tokens")
        assert empty_list == []
        print("✓ Returns empty list for user with no tokens")

        return True

    result = asyncio.run(run_test())
    print("\n✅ Test 12 PASSED: Error handling works correctly")
    return result


def main():
    """Run all Phase 8 Token Vault tests."""
    print("=" * 70)
    print("PHASE 8 TOKEN VAULT TEST SUITE")
    print("=" * 70)
    print(f"Started: {datetime.now().isoformat()}")

    tests = [
        ("TokenVault Initialization", test_token_vault_initialization),
        ("Token Storage and Retrieval", test_token_storage_and_retrieval),
        ("Token Expiration Handling", test_token_expiration),
        ("Token Revocation and Blacklisting", test_token_revocation),
        ("Token Rotation", test_token_rotation),
        ("Token Listing", test_token_listing),
        ("Cleanup of Expired Entries", test_cleanup_expired),
        ("Vault Statistics", test_vault_stats),
        ("Singleton Pattern", test_singleton_pattern),
        ("StoredToken Dataclass", test_stored_token_dataclass),
        ("Multiple OAuth Providers", test_multiple_providers),
        ("Error Handling and Edge Cases", test_error_handling),
    ]

    passed = 0
    failed = 0
    results = []

    for name, test_func in tests:
        try:
            test_func()
            passed += 1
            results.append((name, "✅ PASSED"))
        except Exception as e:
            failed += 1
            results.append((name, f"❌ FAILED: {e}"))
            import traceback
            traceback.print_exc()

    # Summary
    print("\n" + "=" * 70)
    print("TEST RESULTS SUMMARY")
    print("=" * 70)

    for name, status in results:
        print(f"  {status}: {name}")

    print()
    print(f"Total: {len(tests)} tests")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print()

    if failed == 0:
        print("🎉 ALL TESTS PASSED! Phase 8 Token Vault is ready.")
        return 0
    else:
        print(f"⚠️  {failed} test(s) failed. Please review the output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
