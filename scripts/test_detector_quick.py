#!/usr/bin/env python3
"""Quick validation tests for WorkspaceDetector."""

import tempfile
from pathlib import Path

from amprealize.bootstrap import WorkspaceDetector, WorkspaceProfile


def main():
    d = WorkspaceDetector()

    # Test 1: empty workspace -> solo-dev
    with tempfile.TemporaryDirectory() as tmp:
        result = d.detect(Path(tmp))
        assert result.profile == WorkspaceProfile.SOLO_DEV
        print("✅ Test 1: Empty workspace defaults to solo-dev")

    # Test 2: solo-dev signals
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        (ws / "pyproject.toml").write_text('[project]\nname="app"')
        (ws / "src").mkdir()
        result = d.detect(ws)
        assert result.profile == WorkspaceProfile.SOLO_DEV
        print("✅ Test 2: pyproject.toml + src dir = solo-dev")

    # Test 3: extension-dev signals
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        ext = ws / "extension"
        ext.mkdir()
        (ext / "package.json").write_text('{"engines":{"vscode":"^1.80.0"}}')
        result = d.detect(ws)
        assert result.profile == WorkspaceProfile.EXTENSION_DEV
        print("✅ Test 3: extension/package.json with vscode engine = extension-dev")

    # Test 4: api-backend signals
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        (ws / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()")
        (ws / "openapi.yaml").touch()
        result = d.detect(ws)
        assert result.profile == WorkspaceProfile.API_BACKEND
        print("✅ Test 4: FastAPI + openapi.yaml = api-backend")

    # Test 5: team-collab signals
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        (ws / ".github").mkdir()
        (ws / ".github" / "CODEOWNERS").write_text("* @team")
        (ws / ".github" / "pull_request_template.md").write_text("PR template")
        result = d.detect(ws)
        assert result.profile == WorkspaceProfile.TEAM_COLLAB
        print("✅ Test 5: CODEOWNERS + PR template = team-collab")

    # Test 6: compliance-sensitive signals
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        (ws / "policy").mkdir()
        (ws / "SECURITY.md").write_text("Security policy")
        (ws / "soc2_controls.md").write_text("SOC2")
        result = d.detect(ws)
        assert result.profile == WorkspaceProfile.COMPLIANCE_SENSITIVE
        print("✅ Test 6: policy dir + SECURITY.md + SOC2 = compliance-sensitive")

    # Test 7: amprealize-platform detection
    result = d.detect(Path("."))
    assert result.profile == WorkspaceProfile.AMPREALIZE_PLATFORM
    assert result.confidence >= 0.9
    detected = [s.signal_name for s in result.signals if s.detected]
    assert "agents_md" in detected
    assert "mcp_tools_dir" in detected
    print(f"✅ Test 7: Amprealize repo = amprealize-platform ({result.confidence:.0%})")

    # Test 8: serialization
    result = d.detect(Path("."))
    data = result.to_dict()
    assert data["profile"] == "amprealize-platform"
    assert "signals" in data
    assert "confidence" in data
    print("✅ Test 8: to_dict() serialization works")

    print("\n🎉 All 8 detector tests passed!")


if __name__ == "__main__":
    main()
