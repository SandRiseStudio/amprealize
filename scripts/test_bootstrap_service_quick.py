#!/usr/bin/env python3
"""Quick validation tests for BootstrapService."""

import tempfile
from pathlib import Path

from amprealize.bootstrap import BootstrapService, WorkspaceProfile


def main():
    svc = BootstrapService()

    # Test 1: Detection only
    result = svc.detect(Path("."))
    print(f"✅ Test 1: detect() -> {result.profile.value} ({result.confidence:.0%})")

    # Test 2: Get pack for profile
    pack = svc.get_pack_for_profile(WorkspaceProfile.API_BACKEND)
    print(f"✅ Test 2: get_pack_for_profile(API_BACKEND) -> {pack}")

    # Test 3: Full bootstrap with skip_pack (no DB)
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        # Create pyproject.toml with fastapi dependency to trigger api-backend profile
        (ws / "pyproject.toml").write_text('[project]\nname="myapi"\ndependencies=["fastapi"]')
        (ws / "openapi.yaml").touch()  # Also add OpenAPI spec signal
        result = svc.bootstrap(ws, skip_pack=True)
        print(
            f"✅ Test 3: bootstrap() -> profile={result.profile.value}, pack={result.pack_id}"
        )
        print(f"   Files written: {result.files_written}")
        print(f"   Notes: {result.notes}")
        agents_md = ws / "AGENTS.md"
        assert agents_md.exists(), "AGENTS.md not created"
        content = agents_md.read_text()
        assert "api-backend" in content, f"Wrong profile in AGENTS.md: got {result.profile.value}"

    # Test 4: Bootstrap with explicit profile override
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        result = svc.bootstrap(
            ws, profile=WorkspaceProfile.COMPLIANCE_SENSITIVE, skip_pack=True
        )
        print(f"✅ Test 4: bootstrap with override -> {result.profile.value}")
        assert "compliance-sensitive" in (ws / "AGENTS.md").read_text()

    # Test 5: Skip primer (no file)
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        result = svc.bootstrap(ws, skip_pack=True, skip_primer=True)
        print(f"✅ Test 5: skip_primer -> files_written={result.files_written}")
        assert not (ws / "AGENTS.md").exists()

    # Test 6: All profiles have primers
    for profile in WorkspaceProfile:
        template = svc.get_primer_template(profile)
        assert template is not None, f"Missing template for {profile.value}"
        assert profile.value in template, f"Profile name not in template for {profile.value}"
    print("✅ Test 6: All profiles have valid primer templates")

    # Test 7: Serialization
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        result = svc.bootstrap(ws, skip_pack=True)
        data = result.to_dict()
        assert "profile" in data
        assert "detection" in data
        assert "pack_id" in data
    print("✅ Test 7: BootstrapResult.to_dict() works")

    print("\n🎉 All BootstrapService tests passed!")


if __name__ == "__main__":
    main()
