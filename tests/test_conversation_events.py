"""Integration tests for conversation event hub, WebSocket, and SSE (AMPREALIZE-578).

Tests cover:
- ConversationEventHub pub/sub lifecycle
- Typing indicator state and auto-expiry
- Read receipt broadcasting
- Token streaming (message-scoped queue subscribers)
- Event publishing from ConversationService mutations
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


from amprealize.conversation_event_hub import (
    EVENT_COMPLETE,
    EVENT_ERROR,
    EVENT_HEARTBEAT,
    EVENT_MESSAGE_DELETED,
    EVENT_MESSAGE_NEW,
    EVENT_MESSAGE_UPDATED,
    EVENT_PARTICIPANT_JOINED,
    EVENT_PARTICIPANT_LEFT,
    EVENT_PIN_UPDATED,
    EVENT_REACTION_ADDED,
    EVENT_REACTION_REMOVED,
    EVENT_READ_RECEIPT,
    EVENT_TOKEN,
    EVENT_TYPING_INDICATOR,
    ConversationEventHub,
    _TypingState,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeWebSocket:
    """Minimal WebSocket mock that records sent messages."""

    def __init__(self) -> None:
        self.messages: List[Dict[str, Any]] = []
        self.accepted = False
        self.closed = False

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, data: Dict[str, Any]) -> None:
        self.messages.append(data)

    async def close(self, code: int = 1000) -> None:
        self.closed = True


# ---------------------------------------------------------------------------
# ConversationEventHub — connection lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_and_disconnect():
    hub = ConversationEventHub()
    ws = FakeWebSocket()

    await hub.connect(ws, "conv-1")
    assert ws.accepted is True
    assert hub.subscriber_count("conv-1") == 1

    await hub.disconnect(ws, "conv-1")
    assert hub.subscriber_count("conv-1") == 0


@pytest.mark.asyncio
async def test_disconnect_all_conversations():
    hub = ConversationEventHub()
    ws = FakeWebSocket()

    await hub.connect(ws, "conv-1")
    await hub.connect(ws, "conv-2")
    assert hub.subscriber_count("conv-1") == 1
    assert hub.subscriber_count("conv-2") == 1

    # Disconnect from all
    await hub.disconnect(ws, conversation_id=None)
    assert hub.subscriber_count("conv-1") == 0
    assert hub.subscriber_count("conv-2") == 0


# ---------------------------------------------------------------------------
# Publishing to WebSocket subscribers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_to_ws_subscribers():
    hub = ConversationEventHub()
    ws1 = FakeWebSocket()
    ws2 = FakeWebSocket()

    await hub.connect(ws1, "conv-1")
    await hub.connect(ws2, "conv-1")

    # Direct broadcast call
    await hub._broadcast(EVENT_MESSAGE_NEW, "conv-1", {"text": "hello"})

    assert len(ws1.messages) == 1
    assert ws1.messages[0]["type"] == EVENT_MESSAGE_NEW
    assert ws1.messages[0]["payload"]["text"] == "hello"
    assert len(ws2.messages) == 1


@pytest.mark.asyncio
async def test_publish_does_not_leak_to_other_conversations():
    hub = ConversationEventHub()
    ws_conv1 = FakeWebSocket()
    ws_conv2 = FakeWebSocket()

    await hub.connect(ws_conv1, "conv-1")
    await hub.connect(ws_conv2, "conv-2")

    await hub._broadcast(EVENT_MESSAGE_NEW, "conv-1", {"text": "only for conv-1"})

    assert len(ws_conv1.messages) == 1
    assert len(ws_conv2.messages) == 0


# ---------------------------------------------------------------------------
# Queue-based subscribers (SSE)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscribe_and_publish_to_queue():
    hub = ConversationEventHub()
    queue = await hub.subscribe_queue("conv-1")

    await hub._broadcast(EVENT_MESSAGE_NEW, "conv-1", {"text": "from queue"})

    msg = queue.get_nowait()
    assert msg["type"] == EVENT_MESSAGE_NEW
    assert msg["payload"]["text"] == "from queue"


@pytest.mark.asyncio
async def test_message_scoped_queue():
    """Queue subscribers scoped to a specific message_id receive message-level events."""
    hub = ConversationEventHub()
    msg_queue = await hub.subscribe_queue("conv-1", message_id="msg-42")
    conv_queue = await hub.subscribe_queue("conv-1")

    # A message-scoped event
    await hub._broadcast(EVENT_TOKEN, "conv-1", {"token": "hello"}, message_id="msg-42")

    # Both should receive it
    assert not msg_queue.empty()
    assert not conv_queue.empty()

    token_msg = msg_queue.get_nowait()
    assert token_msg["type"] == EVENT_TOKEN

    # A different message's token should NOT go to msg_queue
    await hub._broadcast(EVENT_TOKEN, "conv-1", {"token": "world"}, message_id="msg-99")
    assert msg_queue.empty()  # Not for msg-42
    assert not conv_queue.empty()  # Conv-level queue gets everything


@pytest.mark.asyncio
async def test_unsubscribe_queue():
    hub = ConversationEventHub()
    queue = await hub.subscribe_queue("conv-1")
    await hub.unsubscribe_queue(queue, conversation_id="conv-1")

    await hub._broadcast(EVENT_MESSAGE_NEW, "conv-1", {"text": "should not receive"})
    assert queue.empty()


@pytest.mark.asyncio
async def test_queue_full_does_not_crash():
    """When the queue is full, events are dropped without crashing."""
    hub = ConversationEventHub()
    queue = await hub.subscribe_queue("conv-1")

    # Fill the queue (256 max)
    for i in range(256):
        queue.put_nowait({"type": "fill", "payload": {"i": i}})

    # This should not raise
    await hub._broadcast(EVENT_MESSAGE_NEW, "conv-1", {"text": "overflow"})


# ---------------------------------------------------------------------------
# Typing indicators
# ---------------------------------------------------------------------------


def test_set_typing_and_get_actors():
    hub = ConversationEventHub()
    hub.set_typing("conv-1", "user-a", "user", True)
    hub.set_typing("conv-1", "agent-b", "agent", True)

    actors = hub.get_typing_actors("conv-1")
    assert len(actors) == 2
    actor_ids = {a["actor_id"] for a in actors}
    assert actor_ids == {"user-a", "agent-b"}


def test_stop_typing():
    hub = ConversationEventHub()
    hub.set_typing("conv-1", "user-a", "user", True)
    hub.set_typing("conv-1", "user-a", "user", False)

    actors = hub.get_typing_actors("conv-1")
    assert len(actors) == 0


def test_typing_auto_expiry():
    hub = ConversationEventHub()
    # Manually create an expired typing state
    hub._typing["conv-1"] = {
        "user-a": _TypingState(
            actor_id="user-a",
            actor_type="user",
            started_at=time.monotonic() - 15.0,  # 15s ago, well past expiry
        ),
    }

    actors = hub.get_typing_actors("conv-1")
    assert len(actors) == 0
    assert "user-a" not in hub._typing.get("conv-1", {})


# ---------------------------------------------------------------------------
# Read receipts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_receipt_broadcast():
    hub = ConversationEventHub()
    ws = FakeWebSocket()
    await hub.connect(ws, "conv-1")

    hub.publish_read_receipt("conv-1", "user-a", "2025-03-31T12:00:00Z")

    # Give the asyncio task a chance to run
    await asyncio.sleep(0.05)

    assert len(ws.messages) == 1
    assert ws.messages[0]["type"] == EVENT_READ_RECEIPT
    assert ws.messages[0]["payload"]["actor_id"] == "user-a"


# ---------------------------------------------------------------------------
# Token streaming (publish_token)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_token():
    hub = ConversationEventHub()
    msg_queue = await hub.subscribe_queue("conv-1", message_id="msg-42")

    hub.publish_token("conv-1", "msg-42", {"token": "Hello"})

    # Give the asyncio task a chance to run
    await asyncio.sleep(0.05)

    msg = msg_queue.get_nowait()
    assert msg["type"] == EVENT_TOKEN
    assert msg["payload"]["token"] == "Hello"


@pytest.mark.asyncio
async def test_publish_token_custom_event_type():
    hub = ConversationEventHub()
    msg_queue = await hub.subscribe_queue("conv-1", message_id="msg-42")

    hub.publish_token("conv-1", "msg-42", {"status": "done"}, event_type=EVENT_COMPLETE)

    await asyncio.sleep(0.05)

    msg = msg_queue.get_nowait()
    assert msg["type"] == EVENT_COMPLETE


# ---------------------------------------------------------------------------
# Subscriber count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscriber_count():
    hub = ConversationEventHub()
    ws = FakeWebSocket()

    assert hub.subscriber_count("conv-1") == 0

    await hub.connect(ws, "conv-1")
    assert hub.subscriber_count("conv-1") == 1

    q = await hub.subscribe_queue("conv-1")
    assert hub.subscriber_count("conv-1") == 2

    await hub.disconnect(ws, "conv-1")
    assert hub.subscriber_count("conv-1") == 1

    await hub.unsubscribe_queue(q, conversation_id="conv-1")
    assert hub.subscriber_count("conv-1") == 0


# ---------------------------------------------------------------------------
# ConversationService event_hub integration
# ---------------------------------------------------------------------------


class FakeEventHub:
    """Simplified event hub that captures published events."""

    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []

    def publish(self, event_type: str, conversation_id: str, payload: Dict[str, Any]) -> None:
        self.events.append({
            "type": event_type,
            "conversation_id": conversation_id,
            "payload": payload,
        })


class MockPool:
    """Mock pool whose run_transaction just calls the executor with a mock connection."""

    def __init__(self, query_results: Optional[Dict[str, Any]] = None) -> None:
        self.query_results = query_results or {}

    def run_transaction(self, *, operation, service_prefix, metadata=None, executor, telemetry=None) -> Any:
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cur.description = None
        cur.fetchone.return_value = None
        cur.fetchall.return_value = []
        # Execute the executor with mock conn
        executor(conn)
        return None

    def run_query(self, *, operation, service_prefix, metadata=None, executor, telemetry=None) -> Any:
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cur.description = None
        cur.fetchone.return_value = None
        cur.fetchall.return_value = []
        return executor(conn)


def test_service_publish_event_helper():
    """_publish_event should delegate to event_hub.publish."""
    from amprealize.services.conversation_service import ConversationService

    fake_hub = FakeEventHub()
    svc = ConversationService(pool=MockPool(), event_hub=fake_hub)
    svc._publish_event("test.event", "conv-1", {"key": "val"})

    assert len(fake_hub.events) == 1
    assert fake_hub.events[0]["type"] == "test.event"
    assert fake_hub.events[0]["conversation_id"] == "conv-1"


def test_service_publish_event_noop_without_hub():
    """_publish_event should not crash when no event_hub is set."""
    from amprealize.services.conversation_service import ConversationService

    svc = ConversationService(pool=MockPool())
    # Should not raise
    svc._publish_event("test.event", "conv-1", {"key": "val"})


# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------


def test_event_constants():
    """Verify event type constants match the plan's protocol."""
    assert EVENT_MESSAGE_NEW == "message.new"
    assert EVENT_MESSAGE_UPDATED == "message.updated"
    assert EVENT_MESSAGE_DELETED == "message.deleted"
    assert EVENT_REACTION_ADDED == "reaction.added"
    assert EVENT_REACTION_REMOVED == "reaction.removed"
    assert EVENT_TYPING_INDICATOR == "typing.indicator"
    assert EVENT_READ_RECEIPT == "read.receipt"
    assert EVENT_PARTICIPANT_JOINED == "participant.joined"
    assert EVENT_PARTICIPANT_LEFT == "participant.left"
    assert EVENT_PIN_UPDATED == "pin.updated"
    assert EVENT_TOKEN == "token"
    assert EVENT_COMPLETE == "complete"
    assert EVENT_ERROR == "error"
    assert EVENT_HEARTBEAT == "heartbeat"


# ---------------------------------------------------------------------------
# WebSocket disconnect cleans up broken connections
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ws_disconnect_on_send_failure():
    """If sending to a WS fails, the WS is disconnected."""
    hub = ConversationEventHub()

    class BrokenWS(FakeWebSocket):
        async def send_json(self, data):
            raise ConnectionError("broken")

    ws = BrokenWS()
    await hub.connect(ws, "conv-1")
    assert hub.subscriber_count("conv-1") == 1

    await hub._broadcast(EVENT_MESSAGE_NEW, "conv-1", {"text": "fail"})

    # Broken WS should be removed
    assert hub.subscriber_count("conv-1") == 0
