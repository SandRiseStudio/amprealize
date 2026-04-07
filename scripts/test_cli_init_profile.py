#!/usr/bin/env python3
"""Quick validation: CLI init creates profile-scoped AGENTS.md"""

import subprocess
import tempfile
import os
from pathlib import Path

print("=== Testing CLI init with profile-scoped AGENTS.md ===\n")

# Test 1: API backend profile detection
print("Test 1: Init with api-backend profile (auto-detected)")
with tempfile.TemporaryDirectory() as tmpdir:
    # Setup api-backend signals
    pyproject = Path(tmpdir) / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\ndependencies = ["fastapi"]')
    openapi = Path(tmpdir) / "openapi.yaml"
    openapi.write_text("openapi: 3.0.0")

    # Run init
    result = subprocess.run(
        ["python", "-m", "amprealize", "init", "--name", "test-api"],
        cwd=tmpdir,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parent.parent)},
    )

    agents_path = Path(tmpdir) / "AGENTS.md"
    if not agents_path.exists():
        print(f"  ❌ AGENTS.md not created!")
        print(f"  stdout: {result.stdout[:500]}")
        print(f"  stderr: {result.stderr[:500]}")
    else:
        content = agents_path.read_text()
        # Check for api-backend profile markers
        if "API-First Development" in content or "OpenAPI" in content or "endpoint" in content.lower():
            print(f"  ✅ AGENTS.md created with api-backend profile content")
            # Show first few lines
            lines = content.split("\n")[:5]
            for line in lines:
                print(f"     {line[:70]}")
        else:
            print(f"  ⚠️  AGENTS.md created but may not have profile-specific content")
            print(f"     First line: {content[:100]}")

# Test 2: Manual profile override
print("\nTest 2: Init with --profile compliance-sensitive")
with tempfile.TemporaryDirectory() as tmpdir:
    result = subprocess.run(
        ["python", "-m", "amprealize", "init", "--name", "test-compliance", "--profile", "compliance-sensitive"],
        cwd=tmpdir,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parent.parent)},
    )

    agents_path = Path(tmpdir) / "AGENTS.md"
    if not agents_path.exists():
        print(f"  ❌ AGENTS.md not created!")
    else:
        content = agents_path.read_text()
        # Check for compliance profile markers
        if "Compliance" in content or "audit" in content.lower() or "SOC2" in content or "HIPAA" in content:
            print(f"  ✅ AGENTS.md created with compliance-sensitive profile content")
        else:
            print(f"  ⚠️  AGENTS.md created but may not have compliance-specific content")
            print(f"     First 200 chars: {content[:200]}")

# Test 3: Solo-dev profile
print("\nTest 3: Init with --profile solo-dev")
with tempfile.TemporaryDirectory() as tmpdir:
    result = subprocess.run(
        ["python", "-m", "amprealize", "init", "--name", "my-project", "--profile", "solo-dev"],
        cwd=tmpdir,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parent.parent)},
    )

    agents_path = Path(tmpdir) / "AGENTS.md"
    if not agents_path.exists():
        print(f"  ❌ AGENTS.md not created!")
    else:
        content = agents_path.read_text()
        # Check for solo-dev profile markers
        if "Solo" in content or "single developer" in content.lower() or "personal" in content.lower():
            print(f"  ✅ AGENTS.md created with solo-dev profile content")
        else:
            print(f"  ⚠️  AGENTS.md created but may not have solo-dev-specific content")
            print(f"     First 200 chars: {content[:200]}")

print("\n🎉 CLI init profile tests complete!")
