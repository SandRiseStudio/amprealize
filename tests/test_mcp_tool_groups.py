"""Regression tests for MCP tool grouping and lazy-loader discoverability."""

from __future__ import annotations

import importlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

from amprealize.mcp_guidance import repo_roots_for_guidance


pytestmark = pytest.mark.unit


ROOT = Path(__file__).resolve().parents[1]


def _manifest_names() -> set[str]:
    return {
        json.loads(path.read_text())["name"]
        for path in (ROOT / "mcp" / "tools").glob("*.json")
    }


def _load_groups(monkeypatch: pytest.MonkeyPatch, *, whiteboard_enabled: bool) -> ModuleType:
    if whiteboard_enabled:
        monkeypatch.setenv("AMPREALIZE_ENABLE_WHITEBOARD", "true")
    else:
        monkeypatch.delenv("AMPREALIZE_ENABLE_WHITEBOARD", raising=False)

    import amprealize.mcp_tool_groups as groups

    return importlib.reload(groups)


def _load_lazy_loader_module() -> ModuleType:
    import amprealize.mcp_lazy_loader as lazy_loader

    return importlib.reload(lazy_loader)


def _discoverable_tools(groups: ModuleType, manifests: set[str]) -> set[str]:
    discoverable = set(groups.CORE_TOOLS) & manifests
    prefixes = [
        prefix
        for group in groups.TOOL_GROUPS.values()
        for prefix in group.tool_prefixes
    ]
    discoverable.update(
        name
        for name in manifests
        if any(name.startswith(prefix) for prefix in prefixes)
    )
    return discoverable


def test_core_tools_are_published_and_curated(monkeypatch: pytest.MonkeyPatch) -> None:
    groups = _load_groups(monkeypatch, whiteboard_enabled=False)
    manifests = _manifest_names()
    core_family_tools = {
        name for name in manifests if any(name.startswith(prefix) for prefix in groups.CORE_TOOL_PREFIXES)
    }
    effective_core_tools = core_family_tools | groups.CORE_TOOLS

    assert groups.CORE_TOOLS <= manifests
    assert effective_core_tools <= manifests
    assert len(effective_core_tools) <= groups.TOOL_GROUPS[groups.ToolGroupId.CORE].max_tools
    assert len(effective_core_tools) < 60
    assert {"auth.authStatus", "auth.deviceLogin", "auth.clientCredentials"} <= effective_core_tools
    assert {"projects.list", "projects.get", "projects.switch"} <= effective_core_tools
    assert {"orgs.list", "orgs.get", "orgs.switch"} <= effective_core_tools
    assert {"boards.list", "boards.get", "workItems.list", "workItems.get"} <= effective_core_tools
    assert {"behaviors.getForTask", "behaviors.search", "behaviors.get"} <= effective_core_tools
    assert {"wiki.list_pages", "wiki.read_page", "ai_learning_wiki.query"} <= effective_core_tools
    assert "workItems.delete" not in effective_core_tools
    assert "wiki.update_page" not in effective_core_tools
    assert "behaviors.approve" not in effective_core_tools
    assert not any(name.startswith(("research.", "whiteboard.", "brainstorm.")) for name in groups.CORE_TOOLS)
    assert {"tools.guide", "tools.catalog", "resources.analyze"} <= effective_core_tools


def test_lazy_loader_initializes_startup_groups_without_specialized_outcomes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    groups = _load_groups(monkeypatch, whiteboard_enabled=False)
    lazy_loader = _load_lazy_loader_module()

    loader = lazy_loader.MCPLazyToolLoader()
    loader.initialize(ROOT / "mcp" / "tools")
    loaded_original_names = {
        manifest["_original_name"]
        for manifest in loader.get_active_tools().values()
    }

    assert groups.CORE_TOOLS <= loaded_original_names
    assert "resources.analyze" in loaded_original_names
    assert groups.ToolGroupId.PROJECTS not in loader._state.active_groups
    assert groups.ToolGroupId.WORK_ITEMS not in loader._state.active_groups
    assert "project.setupComplete" not in loaded_original_names
    assert "workItems.update" in loaded_original_names
    assert "columns.list" not in loaded_original_names
    assert "wiki.list_pages" in loaded_original_names
    assert "ai_learning_wiki.query" in loaded_original_names
    assert "analytics.fullReport" not in loaded_original_names
    assert "compliance.fullValidation" not in loaded_original_names


def test_startup_groups_are_not_auto_deactivated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMPREALIZE_MCP_STARTUP_GROUPS", "projects,work_items")
    _load_groups(monkeypatch, whiteboard_enabled=False)
    lazy_loader = _load_lazy_loader_module()

    loader = lazy_loader.MCPLazyToolLoader()
    loader.initialize(ROOT / "mcp" / "tools")
    stale_time = datetime.utcnow() - timedelta(minutes=60)
    loader._state.active_groups.add(lazy_loader.ToolGroupId.WIKI)
    loader._state.last_activation[lazy_loader.ToolGroupId.WIKI] = stale_time
    loader._state.last_activation[lazy_loader.ToolGroupId.PROJECTS] = stale_time
    loader._state.last_activation[lazy_loader.ToolGroupId.WORK_ITEMS] = stale_time

    assert loader._state.get_stale_groups() == [lazy_loader.ToolGroupId.WIKI]


def test_runtime_guide_and_catalog_include_onboarding_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AMPREALIZE_MCP_STARTUP_GROUPS", raising=False)
    _load_groups(monkeypatch, whiteboard_enabled=False)
    lazy_loader = _load_lazy_loader_module()

    loader = lazy_loader.MCPLazyToolLoader()
    loader.initialize(ROOT / "mcp" / "tools")

    guide = loader.get_usage_guide()
    assert guide["success"] is True
    assert "auth.authStatus" in guide["core_tools"]
    assert guide["startup_protocol"][0].startswith("Call auth.authStatus")
    assert any("approved automatically" in note for note in guide["authorization_notes"])
    oss_root, ent_root = repo_roots_for_guidance()
    assert oss_root in guide["repo_parity_notes"][0]
    assert "amprealize-enterprise" in guide["repo_parity_notes"][1]
    assert ent_root in guide["repo_parity_notes"][1]
    assert any("unless the user explicitly" in note for note in guide["repo_parity_notes"])
    assert "tools.catalog" in guide["core_tools"]
    assert guide["startup_groups"] == []
    assert any("context.getContext" in step for step in guide["startup_protocol"])

    catalog = loader.get_tool_catalog(group="work_items", query="get", include_inactive=True)
    assert catalog["success"] is True
    assert any(
        tool["original_name"] == "workItems.get"
        and tool["normalized_name"] == "workitems_get"
        for tool in catalog["tools"]
    )


def test_catalog_can_discover_core_wiki_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    _load_groups(monkeypatch, whiteboard_enabled=False)
    lazy_loader = _load_lazy_loader_module()

    loader = lazy_loader.MCPLazyToolLoader()
    loader.initialize(ROOT / "mcp" / "tools")

    catalog = loader.get_tool_catalog(group="wiki", query="page", include_inactive=True)

    assert catalog["success"] is True
    assert any(tool["group"] == "wiki" and tool["is_active"] for tool in catalog["tools"])


def test_prompt_and_resource_guidance_are_available() -> None:
    from amprealize.mcp_guidance import MCP_GUIDE_PROMPT_NAME, MCP_GUIDE_RESOURCE_URI
    from amprealize.mcp_server import MCPServer

    server = MCPServer.__new__(MCPServer)
    prompts = json.loads(server._handle_prompts_list("prompts"))["result"]["prompts"]
    resources = json.loads(server._handle_resources_list("resources"))["result"]["resources"]

    assert prompts[0]["name"] == MCP_GUIDE_PROMPT_NAME
    assert resources[0]["uri"] == MCP_GUIDE_RESOURCE_URI

    prompt = json.loads(
        server._handle_prompts_get("prompt", {"name": MCP_GUIDE_PROMPT_NAME})
    )["result"]
    resource = json.loads(
        server._handle_resources_read("resource", {"uri": MCP_GUIDE_RESOURCE_URI})
    )["result"]

    assert "tools.catalog" in prompt["messages"][0]["content"]["text"]
    assert "auth.authStatus" in prompt["messages"][0]["content"]["text"]
    oss_root, ent_root = repo_roots_for_guidance()
    assert "amprealize-enterprise" in prompt["messages"][0]["content"]["text"]
    assert ent_root in prompt["messages"][0]["content"]["text"]
    assert "tools.guide" in resource["contents"][0]["text"]
    assert "auth.deviceLogin" in resource["contents"][0]["text"]
    assert oss_root in resource["contents"][0]["text"]


@pytest.mark.asyncio
async def test_tools_list_cache_invalidates_after_group_activation() -> None:
    from amprealize.mcp_server import MCPServer

    class FakeLazyLoader:
        def __init__(self) -> None:
            self.active_tools = {
                "tools_activegroups": {
                    "description": "List active groups",
                    "inputSchema": {"type": "object"},
                }
            }

        def get_active_tools(self):
            return dict(self.active_tools)

        def get_tool_scopes(self):
            return {}

        def get_stats(self):
            return {
                "active_tools": len(self.active_tools),
                "total_available_tools": 2,
                "active_groups": ["core"],
                "headroom": 126,
            }

        def activate_group(self, group_name):
            self.active_tools["wiki_getpage"] = {
                "description": f"Activated {group_name}",
                "inputSchema": {"type": "object"},
            }
            return True, "activated", 1

    notifications = []
    server = MCPServer.__new__(MCPServer)
    server._lazy_loading_enabled = True
    server._lazy_loader = FakeLazyLoader()
    server._tools = server._lazy_loader.get_active_tools()
    server._tool_scopes = {}
    server._tools_list_cache = None
    server._metrics = {"tool_groups_activated": 0, "tool_groups_deactivated": 0}
    server._send_notification = lambda method, params: notifications.append((method, params))

    first = json.loads(server._handle_tools_list("first"))["result"]
    second = json.loads(server._handle_tools_list("second"))["result"]

    assert first == second
    assert [tool["name"] for tool in second["tools"]] == ["tools_activegroups"]

    activation = await server._handle_tools_management(
        "tools.activateGroup",
        {"group_name": "wiki"},
    )
    third = json.loads(server._handle_tools_list("third"))["result"]

    assert activation["success"] is True
    assert "wiki_getpage" in {tool["name"] for tool in third["tools"]}
    assert notifications == [("notifications/tools/list_changed", {})]


def test_task_handler_initializes_service_lazily(monkeypatch: pytest.MonkeyPatch) -> None:
    from amprealize import mcp_task_handler
    from amprealize.mcp_server import MCPServer

    class FakeServices:
        def __init__(self) -> None:
            self.calls = 0

        def task_assignment_service(self):
            self.calls += 1
            return "task-service"

    class FakeTaskHandler:
        def __init__(self, task_service) -> None:
            self.task_service = task_service

    monkeypatch.setattr(mcp_task_handler, "MCPTaskHandler", FakeTaskHandler)

    server = MCPServer.__new__(MCPServer)
    server._task_handler = None
    server._services = FakeServices()

    assert server._services.calls == 0

    handler = server._get_task_handler()

    assert isinstance(handler, FakeTaskHandler)
    assert handler.task_service == "task-service"
    assert server._services.calls == 1
    assert server._get_task_handler() is handler
    assert server._services.calls == 1


def test_mcp_text_result_uses_compact_json_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from amprealize.mcp_server import MCPServer

    monkeypatch.delenv("MCP_PRETTY_JSON_RESPONSES", raising=False)
    server = MCPServer.__new__(MCPServer)

    result = server._mcp_text_result({"ok": True, "items": [1, 2]})

    assert result["content"][0]["text"] == '{"ok":true,"items":[1,2]}'
    assert json.loads(result["content"][0]["text"]) == {"ok": True, "items": [1, 2]}


def test_mcp_text_result_can_pretty_print_for_debug(monkeypatch: pytest.MonkeyPatch) -> None:
    from amprealize.mcp_server import MCPServer

    monkeypatch.setenv("MCP_PRETTY_JSON_RESPONSES", "true")
    server = MCPServer.__new__(MCPServer)

    result = server._mcp_text_result({"ok": True})

    assert result["content"][0]["text"] == '{\n  "ok": true\n}'


def test_tools_list_cache_is_pre_serialized_string() -> None:
    """tools/list cache should store a pre-serialized JSON string, not a dict.

    On cache hits, _handle_tools_list replaces a sentinel in the cached
    string rather than running json.dumps on the full 60 KB envelope.
    """
    import os

    os.environ.setdefault("MCP_REQUIRE_AUTH", "false")
    os.environ.setdefault("MCP_RATE_LIMIT_ENABLED", "false")
    from amprealize.mcp_server import MCPServer

    server = MCPServer()

    # First call: builds and caches
    r1 = server._handle_tools_list("req-001")

    # Cache must be a string (the pre-serialized envelope)
    assert isinstance(server._tools_list_cache, str)
    assert "__MCP_REQUEST_ID__" in server._tools_list_cache

    # The returned string must be valid JSON containing the real request id
    payload = json.loads(r1)
    assert payload["id"] == "req-001"
    assert "tools" in payload["result"]

    # Second call uses cache path (different request id)
    r2 = server._handle_tools_list("req-002")
    payload2 = json.loads(r2)
    assert payload2["id"] == "req-002"
    # Body should be identical apart from the id
    assert payload["result"] == payload2["result"]


def test_tools_list_cache_handles_none_request_id() -> None:
    """Cache hit path must handle None request ids (notifications use null)."""
    import os

    os.environ.setdefault("MCP_REQUIRE_AUTH", "false")
    os.environ.setdefault("MCP_RATE_LIMIT_ENABLED", "false")
    from amprealize.mcp_server import MCPServer

    server = MCPServer()
    server._handle_tools_list("seed")  # prime cache

    r = server._handle_tools_list(None)
    payload = json.loads(r)
    assert payload["id"] is None


def test_agent_docs_reference_mcp_startup_protocol() -> None:
    required_paths = [
        ROOT / "AGENTS.md",
        ROOT / "CLAUDE.md",
        ROOT / ".cursor" / "rules" / "amprealize-mcp-startup.mdc",
        ROOT / ".github" / "agents" / "WorkItemPlanner.agent.md",
        ROOT / "skills" / "work-item-planner" / "SKILL.md",
    ]

    for path in required_paths:
        text = path.read_text()
        assert "tools.guide" in text or "tools_guide" in text
        assert "tools.catalog" in text or "tools_catalog" in text
        assert "auth.authStatus" in text or "auth_authstatus" in text
        assert "amprealize-enterprise" in text
        assert "OSS" in text


def test_every_manifest_is_discoverable_when_feature_groups_are_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    groups = _load_groups(monkeypatch, whiteboard_enabled=True)
    manifests = _manifest_names()

    assert _discoverable_tools(groups, manifests) == manifests


def test_only_whiteboard_family_is_gated_when_whiteboard_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    groups = _load_groups(monkeypatch, whiteboard_enabled=False)
    manifests = _manifest_names()

    missing = manifests - _discoverable_tools(groups, manifests)
    assert missing
    assert all(name.startswith(("whiteboard.", "brainstorm.")) for name in missing)


def test_group_prefixes_match_manifests_and_fit_budgets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    groups = _load_groups(monkeypatch, whiteboard_enabled=True)
    manifests = _manifest_names()

    for group_id, group in groups.TOOL_GROUPS.items():
        if group_id == groups.ToolGroupId.CORE:
            continue

        matching = {
            name
            for name in manifests
            if any(name.startswith(prefix) for prefix in group.tool_prefixes)
        }
        assert matching, f"{group_id.value} does not match any published manifests"
        assert len(matching) <= group.max_tools, f"{group_id.value} exceeds max_tools"


def test_activation_keywords_cover_normalized_tool_families(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    groups = _load_groups(monkeypatch, whiteboard_enabled=True)

    assert groups.ToolGroupId.WIKI in groups.suggest_groups_for_query("query the platform wiki")
    assert groups.ToolGroupId.RESEARCH in groups.suggest_groups_for_query("evaluate this arxiv paper")
    assert groups.ToolGroupId.WORK_ITEMS in groups.suggest_groups_for_query("create a work item on the board")
    assert groups.ToolGroupId.AUTHORIZATION in groups.suggest_groups_for_query("check consent grant status")
    assert groups.ToolGroupId.WHITEBOARD in groups.suggest_groups_for_query("open a brainstorm whiteboard")
