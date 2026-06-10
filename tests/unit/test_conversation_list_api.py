"""Unit tests for GET /v1/conversations list query wiring (multi-scope, include_total)."""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from amprealize.conversation_contracts import ConversationScope
from amprealize.services.conversation_api import create_conversation_routes

pytestmark = pytest.mark.unit


def _app_with_user(svc: MagicMock) -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def inject_user(request: Request, call_next):
        request.state.user_id = "user-1"
        request.state.org_id = None
        return await call_next(request)

    app.include_router(create_conversation_routes(svc))
    return TestClient(app)


def test_list_conversations_any_scope_passes_scopes_and_include_total() -> None:
    svc = MagicMock()
    svc.list_conversations.return_value = ([], -1)
    client = _app_with_user(svc)
    resp = client.get(
        "/v1/conversations"
        "?scopes=global_user_home&scopes=global_personal_thread&include_total=false",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == -1
    svc.list_conversations.assert_called_once()
    _, kwargs = svc.list_conversations.call_args
    assert kwargs["project_id"] is None
    assert kwargs["user_id"] == "user-1"
    assert kwargs["scope"] is None
    assert kwargs["scopes"] == [
        ConversationScope.GLOBAL_USER_HOME,
        ConversationScope.GLOBAL_PERSONAL_THREAD,
    ]
    assert kwargs["include_total"] is False


def test_list_conversations_messages_include_total_false() -> None:
    svc = MagicMock()
    svc.list_messages.return_value = ([], -1, True)
    client = _app_with_user(svc)
    resp = client.get("/v1/conversations/conv-1/messages?include_total=false")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == -1
    svc.list_messages.assert_called_once()
    _, kwargs = svc.list_messages.call_args
    assert kwargs["include_total"] is False
