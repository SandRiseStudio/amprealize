"""MCP handler parity tests for wiki tools."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from amprealize.mcp.handlers.wiki_handlers import (
    WIKI_HANDLERS,
    WikiToolValidationError,
    handle_ai_learning_wiki_query,
    handle_platform_wiki_query,
    handle_wiki_list_pages,
)


pytestmark = pytest.mark.unit


def _manifest_names() -> set[str]:
    root = Path(__file__).resolve().parents[1]
    return {
        json.loads(path.read_text())["name"]
        for path in (root / "mcp" / "tools").glob("*wiki*.json")
    }


def test_wiki_manifests_have_handlers() -> None:
    assert _manifest_names() == set(WIKI_HANDLERS)


def test_query_requires_query_text() -> None:
    with pytest.raises(WikiToolValidationError):
        asyncio.run(handle_ai_learning_wiki_query(MagicMock(), {}))


def test_generic_wiki_rejects_invalid_domain() -> None:
    with pytest.raises(WikiToolValidationError):
        asyncio.run(handle_wiki_list_pages(MagicMock(), {"domain": "unknown"}))


def test_platform_wiki_query_is_routed_to_platform_domain() -> None:
    service = MagicMock()
    service.query.return_value = {"success": True, "results": []}

    result = asyncio.run(handle_platform_wiki_query(service, {"query": "MCP tools"}))

    assert result == {"success": True, "results": []}
    service.query.assert_called_once_with(
        domain="platform",
        query_text="MCP tools",
        page_type=None,
        max_results=10,
    )
