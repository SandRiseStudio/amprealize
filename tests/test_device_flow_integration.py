"""Test DeviceFlowManager integration with GitHubOAuthProvider."""

import asyncio
import os

import pytest

from amprealize.device_flow import DeviceFlowManager
from amprealize.auth.providers import GitHubOAuthProvider


@pytest.mark.skip(reason="Interactive integration test requiring real OAuth credentials and human input()")
async def test_device_flow_with_github():
    """Test DeviceFlowManager using GitHubOAuthProvider."""

    # Load credentials
    client_id = os.getenv("OAUTH_CLIENT_ID")
    client_secret = os.getenv("OAUTH_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("❌ OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET must be set")
        return

    # Initialize provider
    provider = GitHubOAuthProvider(client_id=client_id, client_secret=client_secret)

    # Initialize DeviceFlowManager with provider
    manager = DeviceFlowManager(provider=provider, use_real_oauth=True)

    print("=" * 70)
    print("DEVICE FLOW MANAGER + GITHUB OAUTH INTEGRATION TEST")
    print("=" * 70)

    # Step 1: Start authorization
    print("\n1️⃣  Starting device authorization...")
    session = await manager.start_authorization_real_oauth(
        scopes=["read:user", "user:email"],
        surface="cli",
        metadata={"test": "integration"}
    )

    print(f"✅ Device flow started!")
    print(f"   Verification URI: {session.verification_uri}")
    print(f"   User Code: {session.user_code}")
    print(f"   Device Code: {session.device_code[:20]}...")
    print(f"   Expires in: {session.expires_in()} seconds")
    print(f"   Poll interval: {session.poll_interval} seconds")

    # Step 2: Display instructions
    print("\n" + "=" * 70)
    print("2️⃣  AUTHORIZATION REQUIRED")
    print("=" * 70)
    print(f"1. Visit: {session.verification_uri}")
    print(f"2. Enter code: {session.user_code}")
    print(f"3. Authorize the application")
    print()

    input("Press Enter after authorizing...")

    # Step 3: Poll for token
    print("\n3️⃣  Polling for authorization...")
    max_attempts = 60
    attempt = 0
    approved_result = None

    while attempt < max_attempts:
        attempt += 1
        result = await manager.poll_device_code_real_oauth(session.device_code)

        if result.status.value == "APPROVED":
            approved_result = result
            assert result.tokens is not None
            print(f"✅ Authorization approved!")
            print(f"   Access token: {result.tokens.access_token[:20]}...")
            print(f"   Token type: {result.tokens.token_type}")
            print(f"   Expires in: {result.tokens.access_expires_in()} seconds")
            print(f"   Scopes: {', '.join(result.scopes or [])}")
            break

        elif result.status.value == "DENIED":
            print(f"❌ Authorization denied: {result.denied_reason}")
            return

        elif result.status.value == "EXPIRED":
            print(f"❌ Device code expired")
            return

        elif result.status.value == "PENDING":
            print(f"   ⏳ Still pending (attempt {attempt}/{max_attempts})...")
            await asyncio.sleep(result.retry_after or 5)

        else:
            print(f"❌ Unknown status: {result.status}")
            return

    if attempt >= max_attempts or approved_result is None:
        print(f"❌ Timeout: Authorization not completed after {max_attempts} attempts")
        return

    # Step 4: Validate token with GitHub
    print("\n4️⃣  Validating token with GitHub...")
    assert approved_result.tokens is not None
    user_info = await provider.validate_token(approved_result.tokens.access_token)

    print(f"✅ Token validated!")
    print(f"   Provider: {user_info.provider}")
    print(f"   Username: {user_info.username}")
    print(f"   User ID: {user_info.user_id}")
    print(f"   Email: {user_info.email}")
    print(f"   Name: {user_info.display_name}")

    print("\n" + "=" * 70)
    print("✅ ALL INTEGRATION TESTS PASSED!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_device_flow_with_github())
