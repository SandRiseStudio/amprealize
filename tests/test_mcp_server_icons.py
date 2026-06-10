"""Tests for MCP initialize ``serverInfo.icons`` (protocol-based icon)."""

from __future__ import annotations

from pathlib import Path

import pytest

from amprealize import mcp_server as mcp_mod
from amprealize.mcp_server import _resolve_mcp_server_icons

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BUNDLED_ICON = _REPO_ROOT / "amprealize" / "static" / "mcp_icon.png"


def _reset_icons_cache() -> None:
    mcp_mod._MCP_SERVER_ICONS_CACHE = None


@pytest.mark.unit
def test_resolve_icons_prefers_https_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_icons_cache()
    monkeypatch.setenv("AMPREALIZE_MCP_ICON_URL", "https://cdn.example.com/logo.png")
    monkeypatch.delenv("AMPREALIZE_MCP_ICON_PATH", raising=False)
    icons = _resolve_mcp_server_icons()
    assert len(icons) == 1
    assert icons[0]["src"] == "https://cdn.example.com/logo.png"
    assert icons[0]["mimeType"] == "image/png"


@pytest.mark.unit
def test_http_url_ignored_falls_back_to_bundled(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_icons_cache()
    monkeypatch.setenv("AMPREALIZE_MCP_ICON_URL", "http://insecure.example.com/x.png")
    monkeypatch.delenv("AMPREALIZE_MCP_ICON_PATH", raising=False)
    assert _BUNDLED_ICON.is_file()
    icons = _resolve_mcp_server_icons()
    assert len(icons) == 1
    assert icons[0]["src"].startswith("data:image/png;base64,")


@pytest.mark.unit
def test_path_override_data_uri(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_icons_cache()
    monkeypatch.delenv("AMPREALIZE_MCP_ICON_URL", raising=False)
    # Tiny valid 1x1 PNG
    tiny_png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n\x2d\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    p = tmp_path / "one.png"
    p.write_bytes(tiny_png)
    monkeypatch.setenv("AMPREALIZE_MCP_ICON_PATH", str(p))
    icons = _resolve_mcp_server_icons()
    assert len(icons) == 1
    assert icons[0]["src"].startswith("data:image/png;base64,")
