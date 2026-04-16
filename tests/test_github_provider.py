"""
Test GitHub OAuth provider implementation.

This test validates the GitHubOAuthProvider against the real GitHub OAuth API
using the configured credentials.
"""

import asyncio
import os
import pytest
from amprealize.auth.providers import GitHubOAuthProvider, AuthorizationPendingError


@pytest.mark.asyncio
@pytest.mark.manual
async def test_github_provider_device_flow():
    """Test GitHub OAuth device flow with real credentials.

    Manual test only: requires a human to authorize the device code in GitHub.
    Run with:
        AMPREALIZE_RUN_MANUAL_GITHUB_OAUTH=1 pytest -v -s -m manual \
            tests/test_github_provider.py::test_github_provider_device_flow
    """

    manual_oauth_enabled = os.getenv("AMPREALIZE_RUN_MANUAL_GITHUB_OAUTH", "0").lower() in {"1", "true", "yes"}
    if not manual_oauth_enabled:
        pytest.skip(
            "Manual GitHub OAuth test disabled. Set AMPREALIZE_RUN_MANUAL_GITHUB_OAUTH=1 to enable."
        )

    # Get credentials from environment
    client_id = os.getenv("OAUTH_GITHUB_CLIENT_ID") or os.getenv("OAUTH_CLIENT_ID")
    client_secret = os.getenv("OAUTH_GITHUB_CLIENT_SECRET") or os.getenv("OAUTH_CLIENT_SECRET")

    if not client_id or not client_secret:
        pytest.skip("GitHub OAuth credentials not configured")

    # Initialize provider
    provider = GitHubOAuthProvider(client_id=client_id, client_secret=client_secret)

    assert provider.name == "github"

    # Start device flow
    device_response = await provider.start_device_flow(scopes=["read:user", "user:email"])

    print("\n" + "="*70)
    print("GITHUB OAUTH DEVICE FLOW TEST")
    print("="*70)
    print(f"Provider: {provider.name}")
    print(f"Verification URI: {device_response.verification_uri}")
    print(f"User Code: {device_response.user_code}")
    print(f"Expires in: {device_response.expires_in} seconds")
    print(f"Poll interval: {device_response.interval} seconds")
    print("="*70)
    print(f"\n1. Visit: {device_response.verification_uri}")
    print(f"2. Enter code: {device_response.user_code}")
    print("3. Authorize the application")
    print("\nWaiting for authorization (press Enter after authorizing)...")

    # Wait for user to authorize
    input()

    # Poll for token (with timeout)
    max_attempts = 20
    attempt = 0
    token_response = None

    while attempt < max_attempts:
        try:
            token_response = await provider.poll_token(device_response.device_code)
            break
        except AuthorizationPendingError:
            print(f"Attempt {attempt + 1}/{max_attempts}: Still waiting for authorization...")
            await asyncio.sleep(device_response.interval)
            attempt += 1

    if not token_response:
        pytest.fail("Timeout waiting for authorization")

    print("\n✅ Access token received!")
    print(f"Token type: {token_response.token_type}")
    print(f"Expires in: {token_response.expires_in} seconds")
    print(f"Scope: {token_response.scope}")

    # Validate token and get user info
    user_info = await provider.validate_token(token_response.access_token)

    print(f"\n✅ Token validated!")
    print(f"Provider: {user_info.provider}")
    print(f"Username: {user_info.username}")
    print(f"User ID: {user_info.user_id}")
    print(f"Email: {user_info.email}")
    print(f"Display name: {user_info.display_name}")

    # Verify expected values
    assert user_info.provider == "github"
    assert user_info.username
    assert user_info.user_id

    print("\n✅ All assertions passed!")


if __name__ == "__main__":
    # Run test directly
    asyncio.run(test_github_provider_device_flow())
