"""Runtime guidance for using Amprealize MCP tools."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List


MCP_GUIDE_PROMPT_NAME = "amprealize-mcp-quickstart"
MCP_GUIDE_RESOURCE_URI = "amprealize://mcp/quickstart"


def repo_roots_for_guidance() -> tuple[str, str]:
    """Return (oss_checkout_root, enterprise_checkout_root) for MCP copy.

    OSS root is the parent of the installed ``amprealize`` package (editable
    checkout or site-packages layout). Enterprise defaults to sibling directory
    ``amprealize-enterprise`` next to that root, or ``AMPREALIZE_ENTERPRISE_REPO_PATH``.
    """
    pkg = Path(__file__).resolve().parent
    oss_root = str(pkg.parent)
    override = os.environ.get("AMPREALIZE_ENTERPRISE_REPO_PATH", "").strip()
    if override:
        return oss_root, override
    sibling = Path(oss_root).parent / "amprealize-enterprise"
    ent = str(sibling.resolve())
    return oss_root, ent


def _build_quickstart_markdown() -> str:
    oss, ent = repo_roots_for_guidance()
    return f"""# Amprealize MCP Quickstart

Use this protocol at the start of every Amprealize task:

1. Call `auth.authStatus` before non-auth Amprealize tool calls.
2. If unauthenticated or expired with a valid refresh token, call `auth.refreshToken`, then re-check `auth.authStatus`.
3. If login is needed, call `auth.deviceLogin` (or `auth.deviceInit` + `auth.devicePoll`). In this MCP agent environment, the device login/init path is approved automatically after the auth tool call; do not ask the human to open the URL unless the auth tool explicitly returns a pending manual-consent state that cannot be polled to completion.
4. If any Amprealize tool returns unauthorized/auth expired, stop that workflow, complete the auth flow above, then retry the original call.
5. Call `behaviors.getForTask` to retrieve task-specific behaviors.
6. Call `context.getContext` to discover the active org/project/session.
7. Call `tools.activeGroups` to see which MCP tool groups are loaded.
8. Call `tools.catalog` for the domain you need before guessing tool names.
9. If a needed domain is inactive, call `tools.listGroups` then `tools.activateGroup`.
10. Prefer session defaults for `user_id`, `org_id`, `project_id`, and actor fields instead of inventing IDs.
11. Use exact catalog names. Cursor normalizes dot names: `workItems.get` appears as `workitems_get`.
12. Amprealize has two platform repos: OSS at `{oss}` and Enterprise at `{ent}`. Implement all platform work/features in both repos unless the user explicitly says OSS-only or Enterprise-only.

Never search raw manifest JSON or guess calls until `tools.guide`, `tools.catalog`, and active groups have been checked.
"""


MCP_QUICKSTART_TEXT = _build_quickstart_markdown()


def build_mcp_usage_guide(
    *,
    active_groups: List[str],
    startup_groups: List[str],
    total_available_tools: int,
    active_tools: int,
) -> Dict[str, Any]:
    """Build the canonical MCP usage guide returned by runtime guide surfaces."""

    oss_root, ent_root = repo_roots_for_guidance()
    return {
        "success": True,
        "title": "Amprealize MCP Quickstart",
        "summary": "Check auth status first, then use guide, context, active groups, and catalog before guessing Amprealize MCP calls.",
        "startup_protocol": [
            "Call auth.authStatus before any non-auth Amprealize tool call.",
            "If auth.authStatus reports needs_refresh or an expired access token with a valid refresh token, call auth.refreshToken and then re-check auth.authStatus.",
            "If auth.authStatus reports needs_login or no valid tokens, call auth.deviceLogin, or auth.deviceInit followed by auth.devicePoll.",
            "In this MCP agent environment, auth.deviceLogin/auth.deviceInit is approved automatically after the auth tool call; do not ask the human to open the verification URL unless polling cannot complete and the tool explicitly requires manual consent.",
            "If any Amprealize tool returns unauthorized or auth expired, complete the auth flow first, then retry the original call.",
            "Call behaviors.getForTask for task-specific behaviors.",
            "Call context.getContext to inspect active org/project/session defaults.",
            "Call tools.activeGroups to see currently loaded groups.",
            "Call tools.catalog with a group, query, or use_case before guessing tool names.",
            "Activate inactive domains with tools.listGroups and tools.activateGroup.",
            "Prefer session defaults for user_id, org_id, project_id, actor, and author fields.",
            "Use exact catalog names; Cursor exposes workItems.get as workitems_get.",
            (
                "For Amprealize platform work, update both repos by default: OSS "
                f"{oss_root} and Enterprise {ent_root}, "
                "unless the user explicitly scopes the work to one repo."
            ),
        ],
        "core_tools": [
            "auth.authStatus",
            "auth.refreshToken",
            "auth.deviceLogin",
            "auth.deviceInit",
            "auth.devicePoll",
            "behaviors.getForTask",
            "context.getContext",
            "tools.guide",
            "tools.catalog",
            "tools.activeGroups",
            "tools.listGroups",
            "tools.activateGroup",
        ],
        "startup_groups": startup_groups,
        "active_groups": active_groups,
        "discovery_examples": [
            {
                "goal": "Authorize before using Amprealize tools",
                "call": "auth.authStatus",
                "arguments": {"validate_remote": False},
            },
            {
                "goal": "Start automated device auth when login is needed",
                "call": "auth.deviceLogin",
                "arguments": {"wait_for_authorization": True, "store_tokens": True},
            },
            {
                "goal": "Find work item tools",
                "call": "tools.catalog",
                "arguments": {"group": "work_items", "query": "get update comments"},
            },
            {
                "goal": "Find wiki tools",
                "call": "tools.catalog",
                "arguments": {"query": "wiki ingest query status"},
            },
            {
                "goal": "Load a specialized group",
                "call": "tools.activateGroup",
                "arguments": {"group_name": "wiki"},
            },
        ],
        "tool_name_notes": [
            "Manifest/original names use dots, for example workItems.get.",
            "Cursor tool names are normalized to lowercase with underscores, for example workitems_get.",
            "Use tools.catalog to see both original_name and normalized_name.",
        ],
        "session_default_notes": [
            "Most org_id, project_id, user_id, actor, and author_id fields are optional when MCP session context is available.",
            "Do not fabricate IDs; ask the user or use context/tools catalog if session context is missing.",
        ],
        "authorization_notes": [
            "Treat auth.authStatus as the gate for all non-auth Amprealize MCP calls.",
            "Only auth.* and tools.guide/tools.catalog/tools.activeGroups/tools.listGroups/tools.activateGroup are safe before full authorization.",
            "Use auth.refreshToken before auth.deviceLogin when refresh_token_valid is true.",
            "The MCP device login/init path is approved automatically in this agent environment; agents should poll or use wait_for_authorization instead of asking the human to visit the URL.",
            "On unauthorized/auth expired responses, authenticate and retry once rather than continuing with unrelated tool calls.",
        ],
        "repo_parity_notes": [
            f"Amprealize OSS repo: {oss_root}.",
            f"Amprealize Enterprise repo: {ent_root}.",
            "Implement platform work/features in both repos unless the user explicitly says OSS-only or Enterprise-only.",
            "Mirror code, manifests, tests, docs, and BUILD_TIMELINE entries where applicable.",
            "Validate focused tests and manifest sync in both repos, or state why a repo was intentionally skipped.",
        ],
        "stats": {
            "total_available_tools": total_available_tools,
            "active_tools": active_tools,
        },
        "text": MCP_QUICKSTART_TEXT,
    }
