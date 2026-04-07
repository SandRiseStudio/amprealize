"""Unit tests for the Slack bridge service (AMPREALIZE-602).

Tests:
- Signature verification (valid, invalid, stale timestamp)
- URL verification challenge
- Echo guard (prevent relay loops)
- Thread correlation store/lookup
- Inbound message dispatch (message, reaction_added, reaction_removed)
- Slash commands (connect, disconnect, status, help)
- Outbound relay (post_message with display overrides)
- Block Kit formatting for different message types
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from amprealize.conversation_contracts import (
    ActorType,
    ConversationScope,
    ExternalBinding,
    ExternalProvider,
    Message,
    MessageType,
)

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@dataclass
class FakeSlackConfig:
    bot_token: str = "xoxb-test-token"
    signing_secret: str = "test-signing-secret"
    app_token: Optional[str] = None
    default_bot_name: str = "Amprealize"
    default_bot_icon: str = ":robot_face:"

    def is_configured(self) -> bool:
        return bool(self.bot_token and self.signing_secret)


def _make_signature(secret: str, timestamp: str, body: str) -> str:
    """Compute a valid Slack signature for test payloads."""
    sig_basestring = f"v0:{timestamp}:{body}"
    computed = hmac.new(
        secret.encode("utf-8"),
        sig_basestring.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"v0={computed}"


def _make_binding(
    *,
    binding_id: str = "bind-1",
    conversation_id: str = "conv-1",
    channel_id: str = "C12345",
    workspace_id: str = "T12345",
    is_active: bool = True,
) -> ExternalBinding:
    """Create a test ExternalBinding."""
    return ExternalBinding(
        id=binding_id,
        conversation_id=conversation_id,
        provider=ExternalProvider.SLACK,
        external_channel_id=channel_id,
        external_workspace_id=workspace_id,
        config={},
        is_active=is_active,
        bound_by="test-user",
    )


def _make_message(
    *,
    msg_id: str = "msg-1",
    conversation_id: str = "conv-1",
    sender_type: ActorType = ActorType.AGENT,
    content: str = "Hello from Amprealize",
    message_type: MessageType = MessageType.TEXT,
    parent_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    structured_payload: Optional[Dict[str, Any]] = None,
) -> Message:
    """Create a test Message."""
    return Message(
        id=msg_id,
        conversation_id=conversation_id,
        sender_id="agent-1",
        sender_type=sender_type,
        content=content,
        message_type=message_type,
        parent_id=parent_id,
        metadata=metadata or {},
        structured_payload=structured_payload,
    )


@pytest.fixture
def slack_config():
    return FakeSlackConfig()


@pytest.fixture
def mock_conversation():
    svc = MagicMock()
    svc.get_external_binding.return_value = None
    svc.get_binding_by_conversation.return_value = None
    svc.create_external_binding.return_value = _make_binding()
    svc.create_conversation.return_value = MagicMock(id="conv-1")
    svc.send_message.return_value = _make_message()
    return svc


@pytest.fixture
def mock_http():
    return AsyncMock()


@pytest.fixture
def bridge(slack_config, mock_conversation, mock_http):
    from amprealize.services.slack_bridge import SlackBridgeService
    return SlackBridgeService(
        config=slack_config,
        conversation_service=mock_conversation,
        http_client=mock_http,
    )


# =====================================================================
# Signature verification
# =====================================================================


class TestSignatureVerification:
    """Tests for Slack request signature verification."""

    def test_valid_signature(self, bridge, slack_config):
        body = b'{"type":"url_verification","challenge":"abc"}'
        ts = str(int(time.time()))
        sig = _make_signature(slack_config.signing_secret, ts, body.decode("utf-8"))

        # Should not raise
        bridge.verify_request(ts, sig, body)

    def test_invalid_signature(self, bridge):
        body = b'{"type":"url_verification"}'
        ts = str(int(time.time()))
        bad_sig = "v0=invalid_signature"

        from amprealize.services.slack_bridge import SlackVerificationError
        with pytest.raises(SlackVerificationError, match="Signature mismatch"):
            bridge.verify_request(ts, bad_sig, body)

    def test_stale_timestamp(self, bridge, slack_config):
        body = b'{"type":"event_callback"}'
        ts = str(int(time.time()) - 600)  # 10 minutes old
        sig = _make_signature(slack_config.signing_secret, ts, body.decode("utf-8"))

        from amprealize.services.slack_bridge import SlackVerificationError
        with pytest.raises(SlackVerificationError, match="too old"):
            bridge.verify_request(ts, sig, body)

    def test_invalid_timestamp(self, bridge):
        from amprealize.services.slack_bridge import SlackVerificationError
        with pytest.raises(SlackVerificationError, match="Invalid timestamp"):
            bridge.verify_request("not-a-number", "v0=x", b'{}')

    def test_missing_signing_secret(self, mock_conversation, mock_http):
        from amprealize.services.slack_bridge import SlackBridgeService, SlackVerificationError
        config = FakeSlackConfig(signing_secret="")
        b = SlackBridgeService(config=config, conversation_service=mock_conversation, http_client=mock_http)
        with pytest.raises(SlackVerificationError, match="not configured"):
            b.verify_request("123", "v0=x", b'{}')


# =====================================================================
# URL verification challenge
# =====================================================================


class TestUrlVerification:
    """Tests for Slack URL verification challenge."""

    @pytest.mark.asyncio
    async def test_url_verification_returns_challenge(self, bridge):
        payload = {"type": "url_verification", "challenge": "test-challenge-token"}
        result = await bridge.handle_event(payload)
        assert result == {"challenge": "test-challenge-token"}

    @pytest.mark.asyncio
    async def test_url_verification_empty_challenge(self, bridge):
        payload = {"type": "url_verification"}
        result = await bridge.handle_event(payload)
        assert result == {"challenge": ""}


# =====================================================================
# Echo guard
# =====================================================================


class TestEchoGuard:
    """Tests for the echo/loop prevention mechanism."""

    def test_mark_and_check_echo(self, bridge):
        bridge._mark_echo("1234567890.123456")
        assert bridge._is_echo("1234567890.123456")

    def test_unknown_ts_not_echo(self, bridge):
        assert not bridge._is_echo("9999999999.999999")


# =====================================================================
# Thread correlation
# =====================================================================


class TestThreadCorrelation:
    """Tests for bidirectional thread mapping."""

    def test_store_and_retrieve_slack_ts(self, bridge):
        bridge.store_thread_mapping("msg-1", "C12345", "1234.5678")
        assert bridge.get_slack_ts("msg-1") == "1234.5678"

    def test_store_and_retrieve_amprealize_id(self, bridge):
        bridge.store_thread_mapping("msg-1", "C12345", "1234.5678")
        assert bridge.get_amprealize_message_id("C12345", "1234.5678") == "msg-1"

    def test_missing_mapping_returns_none(self, bridge):
        assert bridge.get_slack_ts("nonexistent") is None
        assert bridge.get_amprealize_message_id("C99", "9999.9999") is None


# =====================================================================
# Inbound relay: Slack → Amprealize
# =====================================================================


class TestInboundRelay:
    """Tests for processing inbound Slack events."""

    @pytest.mark.asyncio
    async def test_message_event_creates_amprealize_message(self, bridge, mock_conversation):
        binding = _make_binding()
        mock_conversation.get_external_binding.return_value = binding

        payload = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "channel": "C12345",
                "user": "U12345",
                "text": "Hello from Slack",
                "ts": "1234567890.123456",
            },
        }

        await bridge.handle_event(payload)

        mock_conversation.send_message.assert_called_once()
        call_kwargs = mock_conversation.send_message.call_args
        assert call_kwargs[1]["content"] == "Hello from Slack"
        assert call_kwargs[1]["sender_id"] == "slack:U12345"
        assert call_kwargs[1]["sender_type"] == ActorType.USER
        assert call_kwargs[1]["metadata"]["slack_ts"] == "1234567890.123456"

    @pytest.mark.asyncio
    async def test_bot_message_ignored(self, bridge, mock_conversation):
        payload = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "channel": "C12345",
                "bot_id": "B12345",
                "text": "I am a bot",
                "ts": "1234567890.123456",
            },
        }

        await bridge.handle_event(payload)
        mock_conversation.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_echo_message_ignored(self, bridge, mock_conversation):
        # Mark a ts as our own echo
        bridge._mark_echo("1234567890.123456")

        binding = _make_binding()
        mock_conversation.get_external_binding.return_value = binding

        payload = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "channel": "C12345",
                "user": "U12345",
                "text": "Our own echo",
                "ts": "1234567890.123456",
            },
        }

        await bridge.handle_event(payload)
        mock_conversation.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_unbound_channel_ignored(self, bridge, mock_conversation):
        mock_conversation.get_external_binding.return_value = None

        payload = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "channel": "C99999",
                "user": "U12345",
                "text": "No binding for this channel",
                "ts": "1234567890.123456",
            },
        }

        await bridge.handle_event(payload)
        mock_conversation.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_threaded_message_sets_parent_id(self, bridge, mock_conversation):
        binding = _make_binding()
        mock_conversation.get_external_binding.return_value = binding

        # Pre-populate thread mapping for the parent
        bridge.store_thread_mapping("parent-msg-1", "C12345", "1111111111.111111")

        payload = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "channel": "C12345",
                "user": "U12345",
                "text": "Threaded reply",
                "ts": "2222222222.222222",
                "thread_ts": "1111111111.111111",
            },
        }

        await bridge.handle_event(payload)
        call_kwargs = mock_conversation.send_message.call_args[1]
        assert call_kwargs["parent_id"] == "parent-msg-1"

    @pytest.mark.asyncio
    async def test_reaction_added_syncs(self, bridge, mock_conversation):
        bridge.store_thread_mapping("msg-1", "C12345", "1234.5678")

        payload = {
            "type": "event_callback",
            "event": {
                "type": "reaction_added",
                "user": "U12345",
                "reaction": "thumbsup",
                "item": {"type": "message", "channel": "C12345", "ts": "1234.5678"},
            },
        }

        await bridge.handle_event(payload)
        mock_conversation.add_reaction.assert_called_once_with(
            "msg-1",
            actor_id="slack:U12345",
            actor_type=ActorType.USER,
            emoji=":thumbsup:",
        )

    @pytest.mark.asyncio
    async def test_reaction_removed_syncs(self, bridge, mock_conversation):
        bridge.store_thread_mapping("msg-1", "C12345", "1234.5678")

        payload = {
            "type": "event_callback",
            "event": {
                "type": "reaction_removed",
                "user": "U12345",
                "reaction": "thumbsup",
                "item": {"type": "message", "channel": "C12345", "ts": "1234.5678"},
            },
        }

        await bridge.handle_event(payload)
        mock_conversation.remove_reaction.assert_called_once_with(
            "msg-1",
            actor_id="slack:U12345",
            emoji=":thumbsup:",
        )


# =====================================================================
# Outbound relay: Amprealize → Slack
# =====================================================================


class TestOutboundRelay:
    """Tests for relaying Amprealize messages to Slack."""

    @pytest.mark.asyncio
    async def test_relay_text_message(self, bridge, mock_http):
        # Mock the HTTP response
        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True, "ts": "9999.9999"}
        mock_response.raise_for_status = MagicMock()
        mock_http.post = AsyncMock(return_value=mock_response)

        msg = _make_message(sender_type=ActorType.AGENT)
        binding = _make_binding()

        ts = await bridge.relay_to_slack(msg, binding)

        assert ts == "9999.9999"
        mock_http.post.assert_called_once()
        call_args = mock_http.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["channel"] == "C12345"
        assert payload["text"] == "Hello from Amprealize"
        # sender_id="agent-1" → resolve_agent_display → "Agent 1"
        assert payload["username"] == "Agent 1"

    @pytest.mark.asyncio
    async def test_relay_agent_with_custom_name(self, bridge, mock_http):
        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True, "ts": "9999.9999"}
        mock_response.raise_for_status = MagicMock()
        mock_http.post = AsyncMock(return_value=mock_response)

        msg = _make_message(sender_type=ActorType.AGENT)
        binding = _make_binding()

        await bridge.relay_to_slack(msg, binding, agent_name="CodeReviewer", agent_icon=":mag:")

        call_args = mock_http.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["username"] == "CodeReviewer"
        assert payload["icon_emoji"] == ":mag:"

    @pytest.mark.asyncio
    async def test_relay_threaded_reply(self, bridge, mock_http):
        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True, "ts": "9999.9999"}
        mock_response.raise_for_status = MagicMock()
        mock_http.post = AsyncMock(return_value=mock_response)

        # Pre-populate parent mapping
        bridge.store_thread_mapping("parent-1", "C12345", "1111.1111")

        msg = _make_message(parent_id="parent-1")
        binding = _make_binding()

        await bridge.relay_to_slack(msg, binding)

        call_args = mock_http.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["thread_ts"] == "1111.1111"

    @pytest.mark.asyncio
    async def test_relay_stores_thread_mapping(self, bridge, mock_http):
        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True, "ts": "8888.8888"}
        mock_response.raise_for_status = MagicMock()
        mock_http.post = AsyncMock(return_value=mock_response)

        msg = _make_message(msg_id="new-msg-1")
        binding = _make_binding()

        await bridge.relay_to_slack(msg, binding)

        assert bridge.get_slack_ts("new-msg-1") == "8888.8888"


# =====================================================================
# Block Kit formatting
# =====================================================================


class TestBlockFormatting:
    """Tests for message type → Block Kit conversion."""

    def test_text_message_no_blocks(self, bridge):
        msg = _make_message(message_type=MessageType.TEXT)
        result = bridge._format_message_blocks(msg)
        assert result is None

    def test_code_block_message(self, bridge):
        msg = _make_message(
            message_type=MessageType.CODE_BLOCK,
            content="print('hello')",
        )
        blocks = bridge._format_message_blocks(msg)
        assert blocks is not None
        assert len(blocks) == 1
        assert "```" in blocks[0]["text"]["text"]

    def test_status_card_message(self, bridge):
        msg = _make_message(
            message_type=MessageType.STATUS_CARD,
            content="Build succeeded",
            structured_payload={"title": "Build Status", "body": "All tests pass"},
        )
        blocks = bridge._format_message_blocks(msg)
        assert blocks is not None
        assert any(b["type"] == "header" for b in blocks)
        assert any("All tests pass" in str(b) for b in blocks)

    def test_system_message(self, bridge):
        msg = _make_message(
            message_type=MessageType.SYSTEM,
            content="User joined",
        )
        blocks = bridge._format_message_blocks(msg)
        assert blocks is not None
        assert blocks[0]["type"] == "context"


# =====================================================================
# Slash commands
# =====================================================================


class TestSlashCommands:
    """Tests for /amprealize slash command handler."""

    @pytest.mark.asyncio
    async def test_connect_command(self, bridge, mock_conversation):
        payload = {
            "text": "connect proj-123",
            "channel_id": "C12345",
            "team_id": "T12345",
            "user_id": "U12345",
        }

        result = await bridge.handle_slash_command(payload)

        assert result["response_type"] == "in_channel"
        assert "Connected" in result["text"]
        mock_conversation.create_conversation.assert_called_once()
        mock_conversation.create_external_binding.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_already_bound(self, bridge, mock_conversation):
        existing = _make_binding(is_active=True)
        mock_conversation.get_external_binding.return_value = existing

        payload = {
            "text": "connect proj-456",
            "channel_id": "C12345",
            "team_id": "T12345",
            "user_id": "U12345",
        }

        result = await bridge.handle_slash_command(payload)
        assert result["response_type"] == "ephemeral"
        assert "already connected" in result["text"]

    @pytest.mark.asyncio
    async def test_connect_missing_project_id(self, bridge):
        payload = {"text": "connect", "channel_id": "C12345", "team_id": "T12345", "user_id": "U12345"}
        result = await bridge.handle_slash_command(payload)
        assert "Usage" in result["text"]

    @pytest.mark.asyncio
    async def test_disconnect_command(self, bridge, mock_conversation):
        binding = _make_binding()
        mock_conversation.get_external_binding.return_value = binding

        payload = {"text": "disconnect", "channel_id": "C12345", "team_id": "T12345", "user_id": "U12345"}
        result = await bridge.handle_slash_command(payload)

        assert "Disconnected" in result["text"]
        mock_conversation.deactivate_external_binding.assert_called_once_with(binding.id)

    @pytest.mark.asyncio
    async def test_disconnect_not_bound(self, bridge, mock_conversation):
        mock_conversation.get_external_binding.return_value = None

        payload = {"text": "disconnect", "channel_id": "C12345", "team_id": "T12345", "user_id": "U12345"}
        result = await bridge.handle_slash_command(payload)
        assert "not connected" in result["text"]

    @pytest.mark.asyncio
    async def test_status_command_bound(self, bridge, mock_conversation):
        binding = _make_binding()
        mock_conversation.get_external_binding.return_value = binding

        payload = {"text": "status", "channel_id": "C12345", "team_id": "T12345", "user_id": "U12345"}
        result = await bridge.handle_slash_command(payload)
        assert "Connected to Amprealize" in result["text"]
        assert binding.conversation_id in result["text"]

    @pytest.mark.asyncio
    async def test_status_command_unbound(self, bridge, mock_conversation):
        mock_conversation.get_external_binding.return_value = None

        payload = {"text": "status", "channel_id": "C12345", "team_id": "T12345", "user_id": "U12345"}
        result = await bridge.handle_slash_command(payload)
        assert "not connected" in result["text"]

    @pytest.mark.asyncio
    async def test_unknown_command_shows_help(self, bridge):
        payload = {"text": "", "channel_id": "C12345", "team_id": "T12345", "user_id": "U12345"}
        result = await bridge.handle_slash_command(payload)
        assert "Usage" in result["text"]


# =====================================================================
# Event hub outbound relay
# =====================================================================


class TestEventHubRelay:
    """Tests for the outbound relay triggered by Amprealize events."""

    @pytest.mark.asyncio
    async def test_relay_ignores_slack_sourced_events(self, bridge, mock_conversation):
        binding = _make_binding()
        mock_conversation.get_binding_by_conversation.return_value = binding

        from amprealize.conversation_event_hub import EVENT_MESSAGE_NEW

        await bridge.on_amprealize_event(
            EVENT_MESSAGE_NEW,
            "conv-1",
            {"metadata": {"source": "slack"}, "content": "from slack"},
        )

        # post_message should NOT have been called (mock_http.post)
        bridge._http.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_relay_skips_unbound_conversations(self, bridge, mock_conversation):
        mock_conversation.get_binding_by_conversation.return_value = None

        from amprealize.conversation_event_hub import EVENT_MESSAGE_NEW

        await bridge.on_amprealize_event(
            EVENT_MESSAGE_NEW,
            "conv-unbound",
            {"content": "no binding"},
        )

        bridge._http.post.assert_not_called()


# =====================================================================
# Agent display overrides (AMPREALIZE-603)
# =====================================================================


class TestAgentDisplayOverrides:
    """Tests for agent display name/icon resolution."""

    def test_registered_agent(self, bridge):
        bridge.register_agent_display("agent:code-reviewer", "Code Reviewer", ":mag:")
        name, icon = bridge.resolve_agent_display("agent:code-reviewer")
        assert name == "Code Reviewer"
        assert icon == ":mag:"

    def test_unregistered_agent_derives_name(self, bridge):
        name, icon = bridge.resolve_agent_display("agent:code-reviewer")
        assert name == "Code Reviewer"
        assert icon == ":robot_face:"  # default

    def test_unregistered_agent_underscores(self, bridge):
        name, icon = bridge.resolve_agent_display("agent:test_runner_bot")
        assert name == "Test Runner Bot"

    def test_plain_id_without_prefix(self, bridge):
        name, icon = bridge.resolve_agent_display("my-agent")
        assert name == "My Agent"

    @pytest.mark.asyncio
    async def test_relay_uses_resolved_display(self, bridge, mock_http):
        """relay_to_slack should use resolve_agent_display when no explicit overrides."""
        bridge.register_agent_display("agent-1", "Custom Agent", ":star:")

        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True, "ts": "9999.9999"}
        mock_response.raise_for_status = MagicMock()
        mock_http.post = AsyncMock(return_value=mock_response)

        msg = _make_message(sender_type=ActorType.AGENT)  # sender_id="agent-1"
        binding = _make_binding()

        await bridge.relay_to_slack(msg, binding)

        call_args = mock_http.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["username"] == "Custom Agent"
        assert payload["icon_emoji"] == ":star:"


# =====================================================================
# Outbound subscription wiring (AMPREALIZE-603)
# =====================================================================


class TestOutboundSubscription:
    """Tests for event hub subscription lifecycle."""

    @pytest.mark.asyncio
    async def test_start_without_event_hub_logs_warning(self, bridge, caplog):
        bridge._event_hub = None
        import logging
        with caplog.at_level(logging.WARNING):
            await bridge.start_outbound_subscription()
        assert "No event hub configured" in caplog.text

    @pytest.mark.asyncio
    async def test_subscribe_conversation_creates_queue(self, bridge):
        mock_hub = AsyncMock()
        mock_queue = MagicMock()
        mock_hub.subscribe_queue = AsyncMock(return_value=mock_queue)
        bridge._event_hub = mock_hub

        with patch.object(bridge, "_consume_queue", new_callable=AsyncMock):
            await bridge._subscribe_conversation("conv-1")

        mock_hub.subscribe_queue.assert_called_once_with("conv-1")
        assert "conv-1" in bridge._subscribed_queues

    @pytest.mark.asyncio
    async def test_stop_unsubscribes_all(self, bridge):
        mock_hub = AsyncMock()
        bridge._event_hub = mock_hub
        q1 = MagicMock()
        q2 = MagicMock()
        bridge._subscribed_queues = {"conv-1": q1, "conv-2": q2}

        await bridge.stop_outbound_subscription()

        assert mock_hub.unsubscribe_queue.call_count == 2
        assert len(bridge._subscribed_queues) == 0

    @pytest.mark.asyncio
    async def test_double_subscribe_is_idempotent(self, bridge):
        mock_hub = AsyncMock()
        mock_queue = MagicMock()
        mock_hub.subscribe_queue = AsyncMock(return_value=mock_queue)
        bridge._event_hub = mock_hub

        with patch.object(bridge, "_consume_queue", new_callable=AsyncMock):
            await bridge._subscribe_conversation("conv-1")
            await bridge._subscribe_conversation("conv-1")  # second call should be no-op

        assert mock_hub.subscribe_queue.call_count == 1
