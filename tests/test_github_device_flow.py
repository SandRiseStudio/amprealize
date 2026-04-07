#!/usr/bin/env python3
"""
Direct test of GitHub OAuth Device Flow.

This script tests the actual GitHub device flow endpoints to verify
our OAuth app configuration is working.

This is a manual interactive script — NOT a pytest test.
Run directly: python tests/test_github_device_flow.py
"""
import os
import sys
import time
import requests


def main() -> None:
    """Run the interactive GitHub device flow test."""
    # Load OAuth credentials
    CLIENT_ID = os.getenv("OAUTH_CLIENT_ID")
    CLIENT_SECRET = os.getenv("OAUTH_CLIENT_SECRET")

    if not CLIENT_ID or not CLIENT_SECRET:
        print("❌ OAuth credentials not set!")
        print("\nPlease run:")
        print("  export OAUTH_CLIENT_ID=<your_client_id>")
        print("  export OAUTH_CLIENT_SECRET=<your_client_secret>")
        sys.exit(1)

    print("=" * 70)
    print("GitHub OAuth Device Flow Test")
    print("=" * 70)
    print(f"\nClient ID: {CLIENT_ID}")
    print(f"Client Secret: {CLIENT_SECRET[:8]}..." + ("*" * 32))

    # Step 1: Request device code from GitHub
    print("\n1️⃣  Requesting device code from GitHub...")
    response = requests.post(
        "https://github.com/login/device/code",
        headers={"Accept": "application/json"},
        data={
            "client_id": CLIENT_ID,
            "scope": "read:user user:email"
        }
    )

    if response.status_code != 200:
        print(f"❌ Failed to get device code: {response.status_code}")
        print(f"Response: {response.text}")
        sys.exit(1)

    device_data = response.json()
    print("✅ Device code received!")
    print(f"\nDevice Code: {device_data['device_code'][:20]}...")
    print(f"User Code: {device_data['user_code']}")
    print(f"Verification URI: {device_data['verification_uri']}")
    print(f"Expires in: {device_data['expires_in']}s")
    print(f"Poll interval: {device_data['interval']}s")

    # Step 2: Display instructions
    print("\n" + "=" * 70)
    print("⚠️  MANUAL ACTION REQUIRED")
    print("=" * 70)
    print(f"\n👉 Visit: {device_data['verification_uri']}")
    print(f"👉 Enter code: {device_data['user_code']}")
    print("\nWaiting for authorization...")
    print("(Press Ctrl+C to cancel)")

    # Step 3: Poll for access token
    device_code = device_data['device_code']
    interval = device_data['interval']
    expires_at = time.time() + device_data['expires_in']
    poll_count = 0

    while time.time() < expires_at:
        poll_count += 1
        time.sleep(interval)

        print(f"  Polling... (attempt {poll_count})", end="\r")

        response = requests.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": CLIENT_ID,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code"
            }
        )

        if response.status_code != 200:
            print(f"\n❌ Polling failed: {response.status_code}")
            print(f"Response: {response.text}")
            break

        result = response.json()

        if "error" in result:
            error = result["error"]
            if error == "authorization_pending":
                continue
            elif error == "slow_down":
                interval += 5
                print(f"\n⚠️  Slowing down: new interval = {interval}s")
                continue
            elif error == "expired_token":
                print("\n❌ Device code expired!")
                sys.exit(1)
            elif error == "access_denied":
                print("\n❌ User denied access!")
                sys.exit(1)
            else:
                print(f"\n❌ Unknown error: {error}")
                print(f"Response: {result}")
                sys.exit(1)

        if "access_token" in result:
            print("\n\n" + "=" * 70)
            print("✅ AUTHORIZATION SUCCESSFUL!")
            print("=" * 70)
            print(f"\nAccess Token: {result['access_token'][:20]}...")
            print(f"Token Type: {result['token_type']}")
            print(f"Scope: {result['scope']}")

            # Test the token
            print("\n2️⃣  Testing access token...")
            user_response = requests.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {result['access_token']}",
                    "Accept": "application/json"
                }
            )

            if user_response.status_code == 200:
                user = user_response.json()
                print(f"✅ Token works! Authenticated as: {user['login']}")
                print(f"   Name: {user.get('name', 'N/A')}")
                print(f"   Email: {user.get('email', 'N/A')}")
                print(f"   Profile: {user['html_url']}")
            else:
                print(f"❌ Token validation failed: {user_response.status_code}")
                print(f"Response: {user_response.text}")

            sys.exit(0)

    print("\n❌ Timed out waiting for authorization")
    sys.exit(1)


if __name__ == "__main__":
    main()
