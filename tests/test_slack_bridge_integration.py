"""Integration tests for the Slack bridge message flow (AMPREALIZE-608).

Validates full end-to-end paths through the bridge service:
- Inbound: Slack Events API → SlackBridgeService → ConversationService
- Outbound: ConversationEventHub → SlackBridgeService → Slack chat.postMessage
- Thread correlation across multi-turn conversations
- Reaction sync in both directions
- Slash command (/amprealize connect) registration flow
- Startup binding discovery via list_all_active_bindings
- FastAPI route wiring (request verification → dispatch → response)
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, call, patch

import httpx
import pytest

from amprealize.conversation_contracts import (
    ActorType,
    ConversationScope,
    ExternalBinding,
    ExternalProvider,
    Message,
    MessageType,
)
from amprealize.services.slack_bridge import SlackBridgeService

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeSlackConfig:
    bot_token: str = "xoxb-integration-test"
    signing_secret: str = "integration-signing-secret"
    app_token: Optional[str] = None
    default_bot_name: str = "Amprealize"
    default_bot_icon: str = ":robot_face:"

    def is_configured(self) -> bool:
        return bool(self.bot_token and self.signing_secret)


def _sign(secret: str, timestamp: str, body: str) -> str:
    sig_basestring = f"v0:{timestamp}:{body}"
    digest = hmac.new(
        secret.encode(),
        sig_basestring.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"v0={digest}"


def _make_binding(
    *,
    binding_id: str = "bind-int-1",
    conversation_id: str = "conv-int-1",
    channel_id: str = "C_INT_1",
    workspace_id: str = "T_INT_1",
) -> ExternalBinding:
    return ExternalBinding(
        id=binding_id,
        conversation_id=conversation_id,
        provider=ExternalProvider.SLACK,
        external_channel_id=channel_id,
        external_workspace_id=workspace_id,
        config={},
        is_active=True,
        bound_by="tester",
    )


def _make_message(
    *,
    msg_id: str = "msg-int-1",
    conversation_id: str = "conv-int-1",
    content: str = "Hello from Amprealize",
    message_type: MessageType = MessageType.TEXT,
    parent_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Message:
    return Message(
        id=msg_id,
        conversation_id=conversation_id,
        sender_id="agent:greeter",
        sender_type=ActorType.AGENT,
        content=content,
        message_type=message_type,
        parent_id=parent_id,
        metadata=metadata or {},
    )


def _slack_event_payload(
    event_type: str = "message",
    channel: str = "C_INT_1",
    user: str = "U_SLACK_1",
    text: str = "Hi from Slack",
    ts: str = "1700000001.000001",
    thread_ts: Optional[str] = None,
) -> Dict[str, Any]:
    event: Dict[str, Any] = {
        "type": event_type,
        "channel": channel,
        "user": user,
        "text": text,
        "ts": ts,
    }
    if thread_ts:
        event["thread_ts"] = thread_ts
    return {
        "token": "test-token",
        "team_id": "T_INT_1",
        "event": event,
        "type": "event_callback",
        "event_id": "Ev_INT_1",
    }


@pytest.fixture
def config():
    return FakeSlackConfig()


@pytest.fixture
def mock_conv():
    svc = MagicMock()
    svc.get_external_binding.return_value = None
    svc.get_binding_by_conversation.return_value = None
    svc.create_external_binding.return_value = _make_binding()
    svc.create_conversation.return_value = MagicMock(id="conv-int-1")
    svc.send_message.return_value = _make_message()
    svc.list_all_active_bindings.return_value = []
    return svc


@pytest.fixture
def mock_http():
    client = AsyncMock()
    response = MagicMock()
    response.json.return_value = {"ok": True, "ts": "1700000099.000001"}
    response.raise_for_status = MagicMock()
    client.post.return_value = response
    return client


@pytest.fixture
def bridge(config, mock_conv, mock_http):
    return SlackBridgeService(
        config=config,
        conversation_service=mock_conv,
        http_client=mock_http,
    )


# =============================================================================
# 1. Startup binding discovery
# =============================================================================


class TestStartupBindingDiscovery:
    """Validates that _discover_bound_conversations queries the DB on startup."""

    def test_discover_returns_conversation_ids(self, bridge, mock_conv):
        bindings = [
            _make_binding(binding_id="b1", conversation_id="conv-A", channel_id="CA"),
            _make_binding(binding_id="b2", conversation_id="conv-B", channel_id="CB"),
        ]
        mock_conv.list_all_active_bindings.return_value = bindings

        result = bridge._discover_bound_conversations()

        mock_conv.list_all_active_bindings.assert_called_once_with(ExternalProvider.SLACK)
        assert result == ["conv-A", "conv-B"]

    def test_discover_returns_empty_on_no_bindings(self, bridge, mock_conv):
        mock_conv.list_all_active_bindings.return_value = []
        assert bridge._discover_bound_conversations() == []

    def test_discover_swallows_exceptions(self, bridge, mock_conv):
        mock_conv.list_all_active_bindings.side_effect = RuntimeError("DB down")
        result = bridge._discover_bound_conversations()
        assert result == []

    async def test_start_outbound_subscription_subscribes_all_bound(
        self, bridge, mock_conv
    ):
        bindings = [
            _make_binding(binding_id="b1", conversation_id="conv-A"),
            _make_binding(binding_id="b2", conversation_id="conv-B"),
        ]
        mock_conv.list_all_active_bindings.return_value = bindings

        hub = AsyncMock()
        q = asyncio.Queue()
        hub.subscribe_queue = AsyncMock(return_value=q)
        bridge._event_hub = hub

        with patch.object(bridge, "_consume_queue", new_callable=AsyncMock):
            await bridge.start_outbound_subscription()

        assert hub.subscribe_queue.call_count == 2
        assert set(bridge._subscribed_queues.keys()) == {"conv-A", "conv-B"}


# =============================================================================
# 2. Inbound flow: Slack Events API → ConversationService
# =============================================================================


class TestInboundMessageFlow:
    """Full inbound relay: Slack event → bridge → ConversationService.send_message."""

    async def test_message_event_creates_amprealize_message(self, bridge, mock_conv):
        binding = _make_binding()
        mock_conv.get_external_binding.return_value = binding

        payload = _slack_event_payload()
        await bridge.handle_event(payload)

        mock_conv.send_message.assert_called_once()
        send_args, send_kwargs = mock_conv.send_message.call_args
        # conversation_id is the first positional arg
        assert send_args[0] == binding.conversation_id
        assert "Hi from Slack" in send_kwargs["content"]
        assert send_kwargs["sender_id"] == "slack:U_SLACK_1"
        assert send_kwargs["sender_type"] == ActorType.USER

    async def test_message_event_without_binding_is_ignored(self, bridge, mock_conv):
        mock_conv.get_external_binding.return_value = None
        payload = _slack_event_payload(channel="C_UNKNOWN")
        await bridge.handle_event(payload)
        mock_conv.send_message.assert_not_called()

    async def test_bot_message_is_ignored(self, bridge, mock_conv):
        binding = _make_binding()
        mock_conv.get_external_binding.return_value = binding

        payload = _slack_event_payload()
        payload["event"]["bot_id"] = "B12345"
        await bridge.handle_event(payload)
        mock_conv.send_message.assert_not_called()

    async def test_echo_guard_prevents_relay_loop(self, bridge, mock_conv):
        binding = _make_binding()
        mock_conv.get_external_binding.return_value = binding

        ts = "1700000999.000001"
        # Simulate that this ts was just posted by us
        bridge._echo_guard[ts] = time.time()

        payload = _slack_event_payload(ts=ts)
        await bridge.handle_event(payload)
        mock_conv.send_message.assert_not_called()

    async def test_threaded_reply_sets_parent_id(self, bridge, mock_conv):
        binding = _make_binding()
        mock_conv.get_external_binding.return_value = binding

        parent_ts = "1700000001.000001"
        reply_ts = "1700000002.000001"
        amprealize_parent_id = "msg-parent"

        # Pre-seed reverse thread map: parent_ts in this channel → Amprealize message id
        key = f"{binding.external_channel_id}:{parent_ts}"
        bridge._reverse_thread_map[key] = amprealize_parent_id

        payload = _slack_event_payload(ts=reply_ts, thread_ts=parent_ts)
        await bridge.handle_event(payload)

        _, send_kwargs = mock_conv.send_message.call_args
        assert send_kwargs["parent_id"] == amprealize_parent_id


# =============================================================================
# 3. Inbound reaction sync: Slack → Amprealize
# =============================================================================


class TestInboundReactionSync:
    """Reaction events from Slack are forwarded to ConversationService."""

    async def test_reaction_added_is_forwarded(self, bridge, mock_conv):
        binding = _make_binding()
        mock_conv.get_external_binding.return_value = binding
        msg_ts = "1700000001.000001"
        key = f"{binding.external_channel_id}:{msg_ts}"
        bridge._reverse_thread_map[key] = "msg-int-1"

        payload = {
            "type": "event_callback",
            "event": {
                "type": "reaction_added",
                "user": "U_SLACK_1",
                "reaction": "thumbsup",
                "item": {
                    "type": "message",
                    "channel": binding.external_channel_id,
                    "ts": msg_ts,
                },
            },
        }
        await bridge.handle_event(payload)
        mock_conv.add_reaction.assert_called_once()

    async def test_reaction_removed_is_forwarded(self, bridge, mock_conv):
        binding = _make_binding()
        mock_conv.get_external_binding.return_value = binding
        msg_ts = "1700000001.000001"
        key = f"{binding.external_channel_id}:{msg_ts}"
        bridge._reverse_thread_map[key] = "msg-int-1"

        payload = {
            "type": "event_callback",
            "event": {
                "type": "reaction_removed",
                "user": "U_SLACK_1",
                "reaction": "thumbsup",
                "item": {
                    "type": "message",
                    "channel": binding.external_channel_id,
                    "ts": msg_ts,
                },
            },
        }
        await bridge.handle_event(payload)
        mock_conv.remove_reaction.assert_called_once()


# =============================================================================
# 4. Outbound flow: EventHub event → Slack chat.postMessage
# =============================================================================


class TestOutboundMessageFlow:
    """Full outbound relay: Amprealize message → relay_to_slack → Slack API."""

    async def test_relay_text_message_posts_to_slack(self, bridge, mock_http, mock_conv):
        binding = _make_binding()
        mock_conv.get_binding_by_conversation.return_value = binding

        message = _make_message(content="Hello Slack!")
        await bridge.relay_to_slack(message, binding)

        mock_http.post.assert_called_once()
        call_args = mock_http.post.call_args
        url = call_args[0][0] if call_args[0] else call_args.kwargs.get("url", "")
        assert "chat.postMessage" in str(url) or "chat.postMessage" in str(call_args)
        payload = call_args.kwargs.get("json") or (call_args[1].get("json") if len(call_args) > 1 else {})
        assert payload["channel"] == binding.external_channel_id
        assert "Hello Slack!" in payload.get("text", "")

    async def test_relay_threaded_reply_uses_thread_ts(self, bridge, mock_http, mock_conv):
        binding = _make_binding()
        mock_conv.get_binding_by_conversation.return_value = binding

        parent_id = "msg-parent"
        slack_thread_ts = "1700000001.000001"
        bridge._thread_map[parent_id] = slack_thread_ts

        message = _make_message(msg_id="msg-reply", parent_id=parent_id)
        await bridge.relay_to_slack(message, binding)

        payload = mock_http.post.call_args.kwargs.get("json") or {}
        assert payload.get("thread_ts") == slack_thread_ts

    async def test_relay_stores_ts_in_thread_map(self, bridge, mock_http, mock_conv):
        binding = _make_binding()
        mock_conv.get_binding_by_conversation.return_value = binding
        response = MagicMock()
        response.json.return_value = {"ok": True, "ts": "1700000099.000001"}
        response.raise_for_status = MagicMock()
        mock_http.post.return_value = response

        message = _make_message(msg_id="msg-new")
        await bridge.relay_to_slack(message, binding)

        # Forward map: Amprealize id → Slack ts
        assert bridge._thread_map.get("msg-new") == "1700000099.000001"
        # Reverse map: channel:ts → Amprealize id
        reverse_key = f"{binding.external_channel_id}:1700000099.000001"
        assert bridge._reverse_thread_map.get(reverse_key) == "msg-new"

    async def test_relay_populates_echo_guard(self, bridge, mock_http, mock_conv):
        binding = _make_binding()
        mock_conv.get_binding_by_conversation.return_value = binding
        response = MagicMock()
        response.json.return_value = {"ok": True, "ts": "1700000099.000001"}
        response.raise_for_status = MagicMock()
        mock_http.post.return_value = response

        message = _make_message()
        await bridge.relay_to_slack(message, binding)

        assert "1700000099.000001" in bridge._echo_guard

    async def test_relay_uses_agent_display_override(self, bridge, mock_http, mock_conv):
        binding = _make_binding()
        mock_conv.get_binding_by_conversation.return_value = binding
        bridge.register_agent_display("agent:greeter", "Greeter Bot", ":wave:")

        message = _make_message()
        await bridge.relay_to_slack(message, binding)

        payload = mock_http.post.call_args.kwargs.get("json") or {}
        assert payload.get("username") == "Greeter Bot"
        assert payload.get("icon_emoji") == ":wave:"


# =============================================================================
# 5. Outbound reaction sync: Amprealize → Slack
# =============================================================================


class TestOutboundReactionSync:
    """Reaction events from Amprealize are forwarded to Slack reactions.add/remove."""

    async def test_add_reaction_calls_reactions_add(self, bridge, mock_http, mock_conv):
        from amprealize.conversation_event_hub import EVENT_REACTION_ADDED

        binding = _make_binding()
        mock_conv.get_binding_by_conversation.return_value = binding
        msg_ts = "1700000001.000001"
        bridge._thread_map["msg-int-1"] = msg_ts

        await bridge.on_amprealize_event(
            EVENT_REACTION_ADDED,
            binding.conversation_id,
            {"message_id": "msg-int-1", "emoji": ":thumbsup:", "user_id": "user-1"},
        )

        calls = [str(c) for c in mock_http.post.call_args_list]
        assert any("reactions.add" in c for c in calls)

    async def test_remove_reaction_calls_reactions_remove(
        self, bridge, mock_http, mock_conv
    ):
        from amprealize.conversation_event_hub import EVENT_REACTION_REMOVED

        binding = _make_binding()
        mock_conv.get_binding_by_conversation.return_value = binding
        msg_ts = "1700000001.000001"
        bridge._thread_map["msg-int-1"] = msg_ts

        await bridge.on_amprealize_event(
            EVENT_REACTION_REMOVED,
            binding.conversation_id,
            {"message_id": "msg-int-1", "emoji": ":thumbsup:", "user_id": "user-1"},
        )

        calls = [str(c) for c in mock_http.post.call_args_list]
        assert any("reactions.remove" in c for c in calls)


# =============================================================================
# 6. Thread correlation end-to-end
# =============================================================================


class TestThreadCorrelationEndToEnd:
    """A multi-turn Slack conversation maps thread_ts ↔ Amprealize parent_id correctly."""

    async def test_full_thread_round_trip(self, bridge, mock_http, mock_conv):
        binding = _make_binding()
        mock_conv.get_external_binding.return_value = binding
        mock_conv.get_binding_by_conversation.return_value = binding

        # Step 1: Slack sends first message → Amprealize creates msg-root
        root_ts = "1700000001.000001"
        root_msg = _make_message(msg_id="msg-root", content="Root message")
        mock_conv.send_message.return_value = root_msg

        root_payload = _slack_event_payload(ts=root_ts)
        await bridge.handle_event(root_payload)

        # Step 2: Amprealize replies → relay_to_slack stores thread_ts
        response = MagicMock()
        response.json.return_value = {"ok": True, "ts": root_ts}
        response.raise_for_status = MagicMock()
        mock_http.post.return_value = response

        reply_msg = _make_message(msg_id="msg-reply", content="Amprealize reply")
        await bridge.relay_to_slack(reply_msg, binding)

        # Thread map should now have msg-reply → root_ts
        assert bridge._thread_map.get("msg-reply") == root_ts

        # Step 3: Slack sends threaded reply → Amprealize gets parent_id
        bridge._reverse_thread_map[f"{binding.external_channel_id}:{root_ts}"] = "msg-root"
        threaded_payload = _slack_event_payload(
            ts="1700000003.000001",
            thread_ts=root_ts,
            text="Threaded Slack reply",
        )
        mock_conv.send_message.reset_mock()
        mock_conv.send_message.return_value = _make_message(msg_id="msg-thread-reply")
        await bridge.handle_event(threaded_payload)

        _, send_kwargs = mock_conv.send_message.call_args
        assert send_kwargs["parent_id"] == "msg-root"


# =============================================================================
# 7. Slash command flow (/amprealize connect)
# =============================================================================


class TestSlashCommandFlow:
    """The /amprealize connect command binds a Slack channel to a Amprealize project."""

    async def test_connect_creates_binding(self, bridge, mock_conv):
        mock_conv.get_external_binding.return_value = None
        mock_conv.create_conversation.return_value = MagicMock(id="conv-new")
        binding = _make_binding(
            conversation_id="conv-new",
            channel_id="C_CONNECT",
        )
        mock_conv.create_external_binding.return_value = binding

        result = await bridge.handle_slash_command({
            "command": "/amprealize",
            "text": "connect proj-abc",
            "channel_id": "C_CONNECT",
            "channel_name": "general",
            "user_id": "U_ADMIN",
            "team_id": "T_INT_1",
        })

        mock_conv.create_conversation.assert_called_once()
        mock_conv.create_external_binding.assert_called_once()
        assert result.get("response_type") == "in_channel" or "connect" in str(result).lower() or "bound" in str(result).lower() or result.get("text")

    async def test_disconnect_deactivates_binding(self, bridge, mock_conv):
        existing = _make_binding(channel_id="C_CONNECT")
        mock_conv.get_external_binding.return_value = existing

        await bridge.handle_slash_command({
            "command": "/amprealize",
            "text": "disconnect",
            "channel_id": "C_CONNECT",
            "user_id": "U_ADMIN",
            "team_id": "T_INT_1",
        })

        mock_conv.deactivate_external_binding.assert_called_once_with(existing.id)

    async def test_status_returns_binding_info(self, bridge, mock_conv):
        existing = _make_binding(channel_id="C_CONNECT", conversation_id="conv-abc")
        mock_conv.get_external_binding.return_value = existing

        result = await bridge.handle_slash_command({
            "command": "/amprealize",
            "text": "status",
            "channel_id": "C_CONNECT",
            "user_id": "U_ADMIN",
            "team_id": "T_INT_1",
        })

        assert result  # must return something
        assert "conv-abc" in str(result) or "connected" in str(result).lower()


# =============================================================================
# 8. FastAPI route integration (request → response)
# =============================================================================


class TestFastAPIRouteIntegration:
    """Verify create_slack_bridge_routes wires correctly and verifies signatures."""

    @pytest.fixture
    def app(self, bridge):
        from fastapi import FastAPI
        from amprealize.services.slack_bridge_api import create_slack_bridge_routes

        test_app = FastAPI()
        router = create_slack_bridge_routes(slack_bridge=bridge, tags=["slack"])
        test_app.include_router(router)
        return test_app

    async def test_url_verification_returns_challenge(self, app, config):
        body = json.dumps({"type": "url_verification", "challenge": "test-challenge-xyz"})
        ts = str(int(time.time()))
        sig = _sign(config.signing_secret, ts, body)

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/v1/integrations/slack/events",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Slack-Request-Timestamp": ts,
                    "X-Slack-Signature": sig,
                },
            )

        assert resp.status_code == 200
        assert resp.json()["challenge"] == "test-challenge-xyz"

    async def test_invalid_signature_returns_401(self, app):
        body = b'{"type":"url_verification","challenge":"abc"}'
        ts = str(int(time.time()))

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/v1/integrations/slack/events",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Slack-Request-Timestamp": ts,
                    "X-Slack-Signature": "v0=badhash",
                },
            )

        assert resp.status_code == 401

    async def test_missing_signature_headers_returns_401(self, app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/v1/integrations/slack/events",
                content=b'{"type":"event_callback"}',
                headers={"Content-Type": "application/json"},
            )

        assert resp.status_code == 401

    async def test_event_dispatch_returns_200(self, app, config, mock_conv):
        from httpx import AsyncClient

        mock_conv.get_external_binding.return_value = None
        body = json.dumps(_slack_event_payload())
        ts = str(int(time.time()))
        sig = _sign(config.signing_secret, ts, body)

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/v1/integrations/slack/events",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Slack-Request-Timestamp": ts,
                    "X-Slack-Signature": sig,
                },
            )

        assert resp.status_code == 200

    async def test_slash_command_returns_json(self, app, config, mock_conv):
        from httpx import AsyncClient

        mock_conv.get_external_binding.return_value = None
        body = "command=%2Famprealize&text=help&channel_id=C123&user_id=U1&team_id=T1"
        ts = str(int(time.time()))
        sig = _sign(config.signing_secret, ts, body)

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/v1/integrations/slack/commands",
                content=body,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-Slack-Request-Timestamp": ts,
                    "X-Slack-Signature": sig,
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "text" in data or "blocks" in data or data
