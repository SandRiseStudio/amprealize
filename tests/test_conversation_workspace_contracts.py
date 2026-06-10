"""Contract tests for target Amprealize Chat workspace scopes."""

from __future__ import annotations

import pytest

from amprealize.conversation_contracts import (
    CHAT_PERMISSION_DENY_BY_DEFAULT,
    CHAT_PERMISSION_MATRIX,
    Conversation,
    ConversationResourceLink,
    ConversationResourceType,
    ConversationScope,
    ConversationScopeResolution,
    ConversationWorkspaceKind,
    ChatPermissionAction,
    ChatPermissionEffect,
    ChatPermissionScope,
    ChatPermissionSurface,
    PROJECT_SCOPED_CONVERSATION_SCOPES,
    get_chat_permission_requirement,
    normalize_conversation_scope,
)

pytestmark = pytest.mark.unit


def test_target_scopes_cover_global_and_project_workspace_model():
    assert ConversationScope.GLOBAL_USER_HOME.value == "global_user_home"
    assert ConversationScope.PROJECT_SPACE.value == "project_space"
    assert ConversationScope.GROUP_CHAT in PROJECT_SCOPED_CONVERSATION_SCOPES
    assert ConversationScope.WORK_ITEM_THREAD in PROJECT_SCOPED_CONVERSATION_SCOPES
    assert ConversationScope.RUN_THREAD in PROJECT_SCOPED_CONVERSATION_SCOPES


def test_global_scope_resolution_rejects_project_binding():
    resolution = ConversationScopeResolution(
        scope=ConversationScope.GLOBAL_USER_HOME,
        workspace_kind=ConversationWorkspaceKind.GLOBAL,
        user_id="user-1",
        project_id="proj-1",
    )

    with pytest.raises(ValueError, match="must not be bound to a project_id"):
        resolution.validate()


def test_project_scoped_resolution_requires_project_id():
    resolution = ConversationScopeResolution(
        scope=ConversationScope.GROUP_CHAT,
        workspace_kind=ConversationWorkspaceKind.PROJECT,
        user_id="user-1",
    )

    with pytest.raises(ValueError, match="requires a project_id"):
        resolution.validate()


def test_conversation_workspace_kind_distinguishes_global_from_project():
    global_conversation = Conversation(
        id="conv-global",
        project_id=None,
        org_id=None,
        scope=ConversationScope.GLOBAL_USER_HOME,
        title="Nick's chat",
        created_by="user-1",
    )
    personal_thread = Conversation(
        id="conv-personal",
        project_id=None,
        org_id=None,
        scope=ConversationScope.GLOBAL_PERSONAL_THREAD,
        title="Side thread",
        created_by="user-1",
    )
    project_conversation = Conversation(
        id="conv-project",
        project_id="proj-1",
        org_id="org-1",
        scope=ConversationScope.PROJECT_ROOM,
        title="Project room",
        created_by="user-1",
    )

    assert global_conversation.workspace_kind == ConversationWorkspaceKind.GLOBAL
    assert personal_thread.workspace_kind == ConversationWorkspaceKind.GLOBAL
    assert project_conversation.workspace_kind == ConversationWorkspaceKind.PROJECT
    assert global_conversation.to_dict()["project_id"] is None


def test_legacy_agent_dm_normalizes_to_target_dm_scope():
    assert (
        normalize_conversation_scope(ConversationScope.AGENT_DM) == ConversationScope.DM
    )
    assert (
        normalize_conversation_scope(ConversationScope.PROJECT_ROOM)
        == ConversationScope.PROJECT_ROOM
    )


def test_mcp_create_global_home_does_not_require_project_id():
    from mcp.handlers.conversation_handlers import handle_create_conversation

    class FakeConversationService:
        def create_conversation(self, **kwargs):
            assert kwargs["project_id"] is None
            assert kwargs["scope"] == ConversationScope.GLOBAL_USER_HOME
            return Conversation(
                id="conv-global",
                project_id=None,
                org_id=kwargs["org_id"],
                scope=kwargs["scope"],
                title=kwargs["title"],
                created_by=kwargs["created_by"],
            )

    result = handle_create_conversation(
        FakeConversationService(),
        {
            "scope": "global_user_home",
            "title": "Personal command center",
            "user_id": "user-1",
            "org_id": "org-1",
        },
    )

    assert result["success"] is True
    assert result["conversation"]["project_id"] is None
    assert result["conversation"]["scope"] == "global_user_home"


def test_mcp_create_legacy_agent_dm_normalizes_to_dm_scope():
    from mcp.handlers.conversation_handlers import handle_create_conversation

    class FakeConversationService:
        def create_conversation(self, **kwargs):
            assert kwargs["project_id"] == "proj-1"
            assert kwargs["scope"] == ConversationScope.DM
            return Conversation(
                id="conv-dm",
                project_id=kwargs["project_id"],
                org_id=None,
                scope=kwargs["scope"],
                title=None,
                created_by=kwargs["created_by"],
            )

    result = handle_create_conversation(
        FakeConversationService(),
        {
            "project_id": "proj-1",
            "scope": "agent_dm",
            "user_id": "user-1",
        },
    )

    assert result["success"] is True
    assert result["conversation"]["scope"] == "dm"


def test_mcp_update_conversation_title():
    from mcp.handlers.conversation_handlers import handle_update_conversation

    class FakeConversationService:
        def patch_conversation(self, conversation_id, *, user_id, org_id, patch):
            assert conversation_id == "conv-1"
            assert user_id == "user-1"
            assert org_id == "org-1"
            assert patch == {"title": "Renamed"}
            return Conversation(
                id=conversation_id,
                project_id=None,
                org_id=org_id,
                scope=ConversationScope.GLOBAL_PERSONAL_THREAD,
                title="Renamed",
                created_by=user_id,
            )

    result = handle_update_conversation(
        FakeConversationService(),
        {
            "conversation_id": "conv-1",
            "title": "Renamed",
            "user_id": "user-1",
            "org_id": "org-1",
        },
    )

    assert result["success"] is True
    assert result["conversation"]["title"] == "Renamed"


def test_resource_links_can_reference_project_scoped_resources_from_global_chat():
    link = ConversationResourceLink(
        resource_type=ConversationResourceType.WORK_ITEM,
        resource_id="guideai-1037",
        project_id="proj-b575d734aa37",
        label="Build Governed Agent Execution And Chat Platform",
    )

    assert link.resource_type == ConversationResourceType.WORK_ITEM
    assert link.project_id == "proj-b575d734aa37"


def test_chat_permission_matrix_covers_every_surface_and_action():
    expected_pairs = {
        (surface, action)
        for surface in ChatPermissionSurface
        for action in ChatPermissionAction
    }

    assert set(CHAT_PERMISSION_MATRIX) == expected_pairs


def test_chat_permission_matrix_distinguishes_all_required_scope_types():
    covered_scopes = {
        scope
        for requirement in CHAT_PERMISSION_MATRIX.values()
        for scope in requirement.scopes
    }

    assert covered_scopes == set(ChatPermissionScope)


def test_chat_permission_matrix_denies_personal_global_chat_sharing_and_publishing():
    share = get_chat_permission_requirement(
        ChatPermissionSurface.GLOBAL_CHAT,
        ChatPermissionAction.INVITE_SHARE,
    )
    publish = get_chat_permission_requirement(
        ChatPermissionSurface.GLOBAL_CHAT,
        ChatPermissionAction.PUBLISH,
    )

    assert share.effect == ChatPermissionEffect.DENY
    assert share.scopes == ()
    assert publish.effect == ChatPermissionEffect.DENY
    assert publish.scopes == ()


@pytest.mark.parametrize(
    "surface",
    [
        ChatPermissionSurface.GLOBAL_CHAT,
        ChatPermissionSurface.PROJECT_SPACE,
        ChatPermissionSurface.GROUP_CHAT,
        ChatPermissionSurface.WORK_ITEM_THREAD,
        ChatPermissionSurface.RUN_THREAD,
        ChatPermissionSurface.AGENT_LIFECYCLE,
        ChatPermissionSurface.MCP_TOOL,
        ChatPermissionSurface.ATTACHMENT,
        ChatPermissionSurface.PLATFORM_ACTION,
    ],
)
def test_execution_related_surfaces_require_approval(surface):
    requirement = get_chat_permission_requirement(
        surface,
        ChatPermissionAction.EXECUTE,
    )

    assert requirement.effect == ChatPermissionEffect.REQUIRE_APPROVAL
    assert requirement.scopes


def test_ambiguous_chat_permission_pairs_are_deny_by_default():
    requirement = get_chat_permission_requirement(
        ChatPermissionSurface.GLOBAL_CHAT,
        ChatPermissionAction.INVITE_SHARE,
    )

    assert requirement.is_denied
    assert "personal" in requirement.notes
    assert "denies any action/surface pair" in CHAT_PERMISSION_DENY_BY_DEFAULT
