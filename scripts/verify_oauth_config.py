#!/usr/bin/env python3
"""
Verify OAuth configuration for Amprealize device flow.
Follows: behavior_externalize_configuration
"""

import os
import sys
from pathlib import Path

# Add amprealize to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from amprealize.config.settings import settings


def check_value(name: str, value: str, min_length: int = 1) -> bool:
    """Check if a configuration value is set."""
    if not value or len(value) < min_length:
        print(f"✗ {name}: NOT SET")
        return False

    # Mask secrets
    if "secret" in name.lower() or "token" in name.lower():
        display = f"{value[:8]}..." if len(value) > 8 else "***"
        print(f"✓ {name}: {display} ({len(value)} characters)")
    else:
        print(f"✓ {name}: {value}")
    return True


def main():
    """Verify OAuth configuration."""
    print("=== Amprealize OAuth Configuration Verification ===\n")

    all_ok = True

    # Check OAuth credentials
    print("OAuth Credentials:")
    all_ok &= check_value("  OAuth Client ID", settings.oauth_client_id, min_length=10)
    all_ok &= check_value("  OAuth Client Secret", settings.oauth_client_secret, min_length=20)
    print()

    # Check OAuth URLs
    print("OAuth URLs:")
    all_ok &= check_value("  Device Code URL", settings.oauth_device_code_url)
    all_ok &= check_value("  Token URL", settings.oauth_token_url)
    all_ok &= check_value("  User URL", settings.oauth_user_url)
    print()

    # Check Device Flow Settings
    print("Device Flow Settings:")
    verification_uri = os.getenv(
        "AMPREALIZE_DEVICE_VERIFICATION_URI",
        "https://device.amprealize.dev/activate"
    )
    print(f"  Verification URI: {verification_uri}")

    device_code_ttl = os.getenv("AMPREALIZE_DEVICE_CODE_TTL_SECONDS", "600")
    print(f"  Device Code TTL: {device_code_ttl}s")

    poll_interval = os.getenv("AMPREALIZE_DEVICE_POLL_INTERVAL_SECONDS", "5")
    print(f"  Poll Interval: {poll_interval}s")

    access_token_ttl = os.getenv("AMPREALIZE_ACCESS_TOKEN_TTL_SECONDS", "3600")
    print(f"  Access Token TTL: {access_token_ttl}s")

    refresh_token_ttl = os.getenv("AMPREALIZE_REFRESH_TOKEN_TTL_SECONDS", "604800")
    print(f"  Refresh Token TTL: {refresh_token_ttl}s")
    print()

    # Validate Client ID format (GitHub uses Iv1., Iv23, or Ov23 prefixes)
    if settings.oauth_client_id and not (settings.oauth_client_id.startswith("Iv") or settings.oauth_client_id.startswith("Ov")):
        print("✗ Warning: Client ID should start with 'Iv1.', 'Iv23', or 'Ov23'")
        print("  Please verify this is a valid GitHub OAuth App Client ID")
        all_ok = False

    # Summary
    print("=" * 50)
    if all_ok:
        print("✓ Configuration is ready for device flow testing")
        print()
        print("Next steps:")
        print("  1. Start API server:")
        print("     $ uvicorn amprealize.api:app --host 127.0.0.1 --port 8000")
        print()
        print("  2. Run device flow test:")
        print("     $ pytest tests/integration/test_staging_device_flow.py::TestStagingDeviceFlow::test_device_login_real_oauth -v")
        return 0
    else:
        print("✗ Configuration incomplete")
        print()
        print("To configure OAuth credentials:")
        print("  1. Create GitHub OAuth App (see docs/GITHUB_OAUTH_SETUP.md)")
        print("  2. Run: ./scripts/setup_github_oauth.sh")
        print("  3. Or set environment variables:")
        print("     export OAUTH_CLIENT_ID=Iv1.YOUR_CLIENT_ID")
        print("     export OAUTH_CLIENT_SECRET=your_client_secret")
        return 1


if __name__ == "__main__":
    sys.exit(main())
