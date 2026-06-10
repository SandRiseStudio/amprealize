"""Unit tests for GET /v1/conversations/global-chat-bootstrap."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from amprealize.conversation_contracts import ActorType, ConversationScope, Message, MessageType
from amprealize.services.conversation_api import create_conversation_routes

pytestmark = pytest.mark.unit


def _make_message(*, mid: str = "msg-1", conversation_id: str = "conv-gh") -> Message:
    return Message(
        id=mid,
        conversation_id=conversation_id,
        sender_id="user-1",
        sender_type=ActorType.USER,
        content="hi",
        message_type=MessageType.TEXT,
        structured_payload=None,
        parent_id=None,
        run_id=None,
        behavior_id=None,
        work_item_id=None,
        is_edited=False,
        edited_at=None,
        is_deleted=False,
        deleted_at=None,
        resource_links=[],
        metadata={},
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        reactions=[],
        reply_count=0,
    )


def test_global_chat_bootstrap_calls_service_and_returns_payload() -> None:
    svc = MagicMock()
    conv = MagicMock()
    conv.id = "conv-gh"
    conv.to_dict.return_value = {
        "id": "conv-gh",
        "project_id": None,
        "org_id": None,
        "scope": ConversationScope.GLOBAL_USER_HOME.value,
        "title": "Global chat",
        "created_by": "user-1",
        "pinned_message_id": None,
        "is_archived": False,
        "metadata": {},
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "participant_count": 1,
    }
    msg = _make_message()
    svc.bootstrap_global_user_home.return_value = (conv, [msg], 1, False)

    app = FastAPI()

    @app.middleware("http")
    async def inject_user(request: Request, call_next):
        request.state.user_id = "user-1"
        request.state.org_id = None
        return await call_next(request)

    app.include_router(create_conversation_routes(svc))

    client = TestClient(app)
    resp = client.get("/v1/conversations/global-chat-bootstrap")
    assert resp.status_code == 200
    body = resp.json()
    assert body["conversation"]["id"] == "conv-gh"
    assert body["conversation"]["scope"] == "global_user_home"
    assert len(body["messages"]["items"]) == 1
    assert body["messages"]["items"][0]["id"] == "msg-1"
    assert body["messages"]["total"] == 1
    assert body["messages"]["has_more"] is False

    svc.bootstrap_global_user_home.assert_called_once_with(
        user_id="user-1",
        org_id=None,
        message_limit=50,
        message_offset=0,
        include_thread_replies=True,
    )


def test_global_chat_bootstrap_passes_query_params() -> None:
    svc = MagicMock()
    conv = MagicMock()
    conv.id = "c1"
    conv.to_dict.return_value = {
        "id": "c1",
        "project_id": None,
        "org_id": "org-x",
        "scope": ConversationScope.GLOBAL_USER_HOME.value,
        "title": "Global chat",
        "created_by": "user-1",
        "pinned_message_id": None,
        "is_archived": False,
        "metadata": {},
        "created_at": None,
        "updated_at": None,
        "participant_count": 1,
    }
    svc.bootstrap_global_user_home.return_value = (conv, [], 0, False)

    app = FastAPI()

    @app.middleware("http")
    async def inject_user(request: Request, call_next):
        request.state.user_id = "user-1"
        request.state.org_id = "org-x"
        return await call_next(request)

    app.include_router(create_conversation_routes(svc))
    client = TestClient(app)

    resp = client.get("/v1/conversations/global-chat-bootstrap?limit=20&offset=10&include_thread_replies=false")
    assert resp.status_code == 200
    svc.bootstrap_global_user_home.assert_called_once_with(
        user_id="user-1",
        org_id="org-x",
        message_limit=20,
        message_offset=10,
        include_thread_replies=False,
    )
