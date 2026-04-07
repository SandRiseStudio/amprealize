#!/usr/bin/env python3
"""
Manage GitHub OAuth Apps for Amprealize device flow.
Follows: behavior_externalize_configuration, behavior_prevent_secret_leaks

Simple interactive script to:
1. Help create GitHub OAuth Apps (opens browser)
2. Configure credentials in Amprealize
3. Verify configuration

No GitHub API token needed - just your OAuth app credentials.
"""

import os
import sys
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional


def open_github_oauth_apps():
    """Open GitHub OAuth Apps page in browser."""
    url = "https://github.com/settings/developers"
    print(f"\n🌐 Opening: {url}")
    try:
        webbrowser.open(url)
        return True
    except Exception as e:
        print(f"⚠️  Could not open browser: {e}")
        print(f"   Please visit: {url}")
        return False


def save_credentials(client_id: str, client_secret: str) -> str:
    """Save OAuth credentials to .env file."""
    env_file = Path.cwd() / ".env.github-oauth"

    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    content = f"""# GitHub OAuth Configuration
# Generated: {timestamp}
# DO NOT COMMIT THIS FILE

OAUTH_CLIENT_ID={client_id}
OAUTH_CLIENT_SECRET={client_secret}

# GitHub OAuth URLs (defaults)
OAUTH_DEVICE_CODE_URL=https://github.com/login/device/code
OAUTH_TOKEN_URL=https://github.com/login/oauth/access_token
OAUTH_USER_URL=https://api.github.com/user

# Device Flow Settings (optional overrides)
# AMPREALIZE_DEVICE_VERIFICATION_URI=https://device.amprealize.dev/activate
# AMPREALIZE_DEVICE_CODE_TTL_SECONDS=600
# AMPREALIZE_DEVICE_POLL_INTERVAL_SECONDS=5
# AMPREALIZE_ACCESS_TOKEN_TTL_SECONDS=3600
# AMPREALIZE_REFRESH_TOKEN_TTL_SECONDS=604800
"""

    env_file.write_text(content)
    env_file.chmod(0o600)

    # Add to .gitignore
    gitignore = Path.cwd() / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text()
        if ".env.github-oauth" not in content:
            with gitignore.open("a") as f:
                f.write("\n.env.github-oauth\n")
            print("✓ Added .env.github-oauth to .gitignore")

    return str(env_file)


def print_instructions():
    """Print instructions for creating OAuth app."""
    print("\n" + "=" * 70)
    print("  GitHub OAuth App Setup Instructions")
    print("=" * 70)
    print("\n1️⃣  On the GitHub OAuth Apps page:")
    print("   • Click the green 'Register a new application' button")
    print()
    print("2️⃣  Fill in the application details:")
    print()
    print("   Application name:")
    print("     Amprealize Device Flow")
    print()
    print("   Homepage URL:")
    print("     https://github.com/YOUR_USERNAME/amprealize")
    print("     (or your actual Amprealize homepage)")
    print()
    print("   Application description: (optional)")
    print("     Amprealize device authorization for CLI, MCP, and IDE surfaces")
    print()
    print("   Authorization callback URL:")
    print("     http://localhost:8000/auth/callback")
    print()
    print("   ⚠️  IMPORTANT: Check this box:")
    print("     ☑ Enable Device Flow")
    print("     (This is required for Amprealize to work!)")
    print()
    print("3️⃣  Click 'Register application'")
    print()
    print("4️⃣  After creating the app:")
    print("   • Copy the 'Client ID' (starts with Iv1. or Iv23)")
    print("   • Click 'Generate a new client secret'")
    print("   • Copy the 'Client secret' immediately (you won't see it again!)")
    print()
    print("5️⃣  Return to this script and enter your credentials")
    print()


def main():
    """Main entry point."""
    print("=" * 70)
    print("  Amprealize GitHub OAuth App Manager")
    print("=" * 70)
    print()
    print("This script helps you configure GitHub OAuth for Amprealize device flow.")
    print()

    # Menu
    print("Choose an option:")
    print("  1) View existing OAuth Apps (opens browser)")
    print("  2) Create new OAuth App (opens browser + shows instructions)")
    print("  3) Enter existing OAuth App credentials")
    print()

    choice = input("Enter choice (1-3): ").strip()

    client_id = None
    client_secret = None

    if choice == "1":
        # View existing apps
        print("\n📋 Opening GitHub OAuth Apps page...")
        open_github_oauth_apps()
        print()
        print("ℹ️  Look for existing apps that might work for Amprealize")
        print("   Apps with 'Amprealize', 'Device Flow', or similar names")
        print()
        use_existing = input("Do you have an existing app to use? (y/N): ").strip().lower()

        if use_existing == 'y':
            choice = "3"  # Enter credentials
        else:
            create_new = input("Create a new OAuth App? (y/N): ").strip().lower()
            if create_new == 'y':
                choice = "2"
            else:
                print("\n❌ Cancelled")
                sys.exit(0)

    if choice == "2":
        # Create new app
        print_instructions()
        open_github_oauth_apps()
        print()
        input("Press Enter after you've created the OAuth App and copied credentials...")
        print()
        choice = "3"  # Continue to credential entry

    if choice == "3":
        # Manual entry
        print("\n📝 Enter OAuth App Credentials\n")

        client_id = input("Client ID (starts with Iv1. or Iv23): ").strip()

        if not client_id:
            print("❌ Client ID is required")
            sys.exit(1)

        if not client_id.startswith("Iv"):
            print("⚠️  Warning: Client ID should start with 'Iv1.' or 'Iv23'")
            confirm = input("Continue anyway? (y/N): ").strip().lower()
            if confirm != 'y':
                sys.exit(1)

        client_secret = input("Client Secret: ").strip()

        if not client_secret:
            print("❌ Client Secret is required")
            sys.exit(1)

        if len(client_secret) < 20:
            print(f"⚠️  Warning: Client Secret seems short ({len(client_secret)} chars)")
            confirm = input("Continue anyway? (y/N): ").strip().lower()
            if confirm != 'y':
                sys.exit(1)

    else:
        print("❌ Invalid choice")
        sys.exit(1)

    # Save credentials
    print("\n💾 Saving credentials...")
    env_file = save_credentials(client_id, client_secret)

    print(f"\n✅ Configuration saved to: {env_file}")
    print()
    print("=" * 70)
    print("  Next Steps")
    print("=" * 70)
    print()
    print("1️⃣  Load the credentials:")
    print(f"   $ source {env_file}")
    print()
    print("2️⃣  Verify configuration:")
    print("   $ python scripts/verify_oauth_config.py")
    print()
    print("3️⃣  Start API server:")
    print("   $ source .env.github-oauth")
    print("   $ uvicorn amprealize.api:app --host 127.0.0.1 --port 8000")
    print()
    print("4️⃣  Run integration tests:")
    print("   $ source .env.github-oauth")
    print("   $ pytest tests/integration/test_staging_device_flow.py -v")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
