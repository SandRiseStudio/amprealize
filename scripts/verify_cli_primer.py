#!/usr/bin/env python3
"""Verify CLI init uses profile-scoped primers from BootstrapService."""
# Run with: python scripts/verify_cli_primer.py

import sys
sys.path.insert(0, '/Users/nick/amprealize')

from amprealize.bootstrap.service import BootstrapService
from amprealize.bootstrap.profile import WorkspaceProfile

svc = BootstrapService()

print("=== BootstrapService Primer Templates ===")
all_ok = True
for profile in WorkspaceProfile:
    template = svc.get_primer_template(profile)
    size = len(template)
    # Check for profile-specific keywords
    keywords = {
        WorkspaceProfile.SOLO_DEV: ["solo", "single developer", "personal"],
        WorkspaceProfile.AMPREALIZE_PLATFORM: ["amprealize", "mcp", "behavior"],
        WorkspaceProfile.TEAM_COLLAB: ["team", "review", "code review"],
        WorkspaceProfile.EXTENSION_DEV: ["extension", "vscode", "webview"],
        WorkspaceProfile.API_BACKEND: ["api", "openapi", "endpoint"],
        WorkspaceProfile.COMPLIANCE_SENSITIVE: ["compliance", "audit", "soc2"],
    }
    found = [kw for kw in keywords.get(profile, []) if kw.lower() in template.lower()]
    if found:
        print(f"  ✅ {profile.value}: {size} chars, keywords: {found[:2]}")
    else:
        print(f"  ❌ {profile.value}: {size} chars, NO profile keywords found!")
        all_ok = False

if all_ok:
    print("\n🎉 All profile primers contain expected content!")
else:
    print("\n⚠️  Some primers missing profile-specific content")
    sys.exit(1)
