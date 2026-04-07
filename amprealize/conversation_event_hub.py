"""Conversation event hub for real-time messaging over WebSocket and SSE (AMPREALIZE-575).

In-memory pub/sub for conversation events — new messages, edits, reactions,
typing indicators, read receipts, and participant changes.  Mirrors the
ExecutionEventHub pattern but indexes subscribers by conversation_id.

Two subscriber types:
- WebSocket connections  (bidirectional, for web UI / VS Code)
- asyncio.Queue          (unidirectional, for SSE token-streaming)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set

from starlette.websockets import WebSocket

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event type constants — must stay in sync with the plan's event protocol
# ---------------------------------------------------------------------------

# Server → Client
EVENT_MESSAGE_NEW = "message.new"
EVENT_MESSAGE_UPDATED = "message.updated"
EVENT_MESSAGE_DELETED = "message.deleted"
EVENT_REACTION_ADDED = "reaction.added"
EVENT_REACTION_REMOVED = "reaction.removed"
EVENT_TYPING_INDICATOR = "typing.indicator"
EVENT_READ_RECEIPT = "read.receipt"
EVENT_PARTICIPANT_JOINED = "participant.joined"
EVENT_PARTICIPANT_LEFT = "participant.left"
EVENT_PIN_UPDATED = "pin.updated"
EVENT_SYSTEM_ANNOUNCEMENT = "system.announcement"

# SSE-only (agent token streaming)
EVENT_TOKEN = "token"
EVENT_STRUCTURED_START = "structured_start"
EVENT_STRUCTURED_UPDATE = "structured_update"
EVENT_COMPLETE = "complete"
EVENT_ERROR = "error"
EVENT_HEARTBEAT = "heartbeat"


# ---------------------------------------------------------------------------
# Typing indicator state (ephemeral, in-memory only)
# ---------------------------------------------------------------------------

@dataclass
class _TypingState:
    """Tracks who is currently typing in a conversation."""
    actor_id: str
    actor_type: str
    started_at: float = field(default_factory=time.monotonic)
    # Typing indicators auto-expire after 10 seconds if not refreshed
    EXPIRY_SECONDS: float = 10.0

    @property
    def is_expired(self) -> bool:
        return (time.monotonic() - self.started_at) > self.EXPIRY_SECONDS


class ConversationEventHub:
    """In-memory pub/sub for conversation events.

    Subscribers are indexed by ``conversation_id``.  A single hub
    instance is shared across the application (stored in ``app.state``).
    """

    def __init__(self) -> None:
        # conversation_id → set of WebSocket connections
        self._ws_subscribers: Dict[str, Set[WebSocket]] = {}
        # conversation_id → set of asyncio.Queue (for SSE)
        self._queue_subscribers: Dict[str, Set[asyncio.Queue]] = {}
        # conversation_id → {actor_id: _TypingState}
        self._typing: Dict[str, Dict[str, _TypingState]] = {}
        self._lock = asyncio.Lock()
        # Cache the main event loop so sync callers (threadpool) can schedule broadcasts.
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ------------------------------------------------------------------
    # WebSocket lifecycle
    # ------------------------------------------------------------------

    async def connect(
        self,
        websocket: WebSocket,
        conversation_id: str,
    ) -> None:
        """Accept and register a WebSocket subscriber for a conversation."""
        # Capture the main event loop on first async call.
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        await websocket.accept()
        async with self._lock:
            self._ws_subscribers.setdefault(conversation_id, set()).add(websocket)

    async def disconnect(
        self,
        websocket: WebSocket,
        conversation_id: Optional[str] = None,
    ) -> None:
        """Remove a WebSocket subscriber.

        If *conversation_id* is ``None``, remove from **all** conversations
        (used on unexpected disconnection).
        """
        async with self._lock:
            if conversation_id:
                subs = self._ws_subscribers.get(conversation_id)
                if subs:
                    subs.discard(websocket)
            else:
                for subs in self._ws_subscribers.values():
                    subs.discard(websocket)

    # ------------------------------------------------------------------
    # Queue-based subscribers (for SSE)
    # ------------------------------------------------------------------

    async def subscribe_queue(
        self,
        conversation_id: str,
        *,
        message_id: Optional[str] = None,
    ) -> asyncio.Queue:
        """Subscribe via asyncio.Queue for SSE streaming.

        Args:
            conversation_id: The conversation to subscribe to.
            message_id: Optional — subscribe only to events for a specific
                        message (used for agent token streaming).

        Returns:
            An ``asyncio.Queue`` that receives dicts::

                {"type": "<event_type>", "payload": {...}}
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        key = f"{conversation_id}:{message_id}" if message_id else conversation_id
        async with self._lock:
            self._queue_subscribers.setdefault(key, set()).add(queue)
        return queue

    async def unsubscribe_queue(self, queue: asyncio.Queue, *, conversation_id: Optional[str] = None) -> None:
        """Remove a queue subscriber."""
        async with self._lock:
            if conversation_id:
                for key in list(self._queue_subscribers):
                    if key == conversation_id or key.startswith(f"{conversation_id}:"):
                        self._queue_subscribers[key].discard(queue)
            else:
                for queues in self._queue_subscribers.values():
                    queues.discard(queue)

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    def publish(self, event_type: str, conversation_id: str, payload: Dict[str, Any]) -> None:
        """Publish an event to all subscribers of a conversation.

        Non-blocking — schedules broadcast as an asyncio task.
        """
        self._schedule_broadcast(event_type, conversation_id, payload)

    def publish_token(
        self,
        conversation_id: str,
        message_id: str,
        payload: Dict[str, Any],
        event_type: str = EVENT_TOKEN,
    ) -> None:
        """Publish a token-streaming event scoped to a specific message.

        These events are delivered to:
        - All WebSocket subscribers of the conversation
        - Queue subscribers keyed to ``conversation_id:message_id``
        """
        self._schedule_broadcast(event_type, conversation_id, payload, message_id=message_id)

    # ------------------------------------------------------------------
    # Typing indicators
    # ------------------------------------------------------------------

    def set_typing(self, conversation_id: str, actor_id: str, actor_type: str, is_typing: bool) -> None:
        """Update typing state and broadcast indicator."""
        if is_typing:
            self._typing.setdefault(conversation_id, {})[actor_id] = _TypingState(
                actor_id=actor_id,
                actor_type=actor_type,
            )
        else:
            conv_typing = self._typing.get(conversation_id, {})
            conv_typing.pop(actor_id, None)

        self.publish(
            EVENT_TYPING_INDICATOR,
            conversation_id,
            {"actor_id": actor_id, "actor_type": actor_type, "is_typing": is_typing},
        )

    def get_typing_actors(self, conversation_id: str) -> list:
        """Return list of actors currently typing (pruning expired)."""
        conv_typing = self._typing.get(conversation_id, {})
        active = []
        expired_keys = []
        for actor_id, state in conv_typing.items():
            if state.is_expired:
                expired_keys.append(actor_id)
            else:
                active.append({"actor_id": state.actor_id, "actor_type": state.actor_type})
        for k in expired_keys:
            conv_typing.pop(k, None)
        return active

    # ------------------------------------------------------------------
    # Read receipts
    # ------------------------------------------------------------------

    def publish_read_receipt(self, conversation_id: str, actor_id: str, last_read_at: str) -> None:
        """Broadcast a read receipt update."""
        self.publish(
            EVENT_READ_RECEIPT,
            conversation_id,
            {"actor_id": actor_id, "last_read_at": last_read_at},
        )

    # ------------------------------------------------------------------
    # Internal broadcast machinery
    # ------------------------------------------------------------------

    def _schedule_broadcast(
        self,
        event_type: str,
        conversation_id: str,
        payload: Dict[str, Any],
        *,
        message_id: Optional[str] = None,
    ) -> None:
        # Try the current thread's running loop first (works inside async handlers).
        # If there's no running loop (sync handler running in a threadpool), fall
        # back to the cached main loop and use call_soon_threadsafe so the coroutine
        # is scheduled on the correct (main) event loop.
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._broadcast(event_type, conversation_id, payload, message_id=message_id))
        except RuntimeError:
            loop = self._loop
            if loop is None or loop.is_closed():
                return
            loop.call_soon_threadsafe(
                loop.create_task,
                self._broadcast(event_type, conversation_id, payload, message_id=message_id),
            )

    async def _broadcast(
        self,
        event_type: str,
        conversation_id: str,
        payload: Dict[str, Any],
        *,
        message_id: Optional[str] = None,
    ) -> None:
        message = {"type": event_type, "payload": payload}

        # WebSocket subscribers — always keyed by conversation_id
        ws_targets: Set[WebSocket] = set()
        queue_targets: Set[asyncio.Queue] = set()

        async with self._lock:
            ws_targets.update(self._ws_subscribers.get(conversation_id, set()))

            # Queue subscribers — conversation level
            queue_targets.update(self._queue_subscribers.get(conversation_id, set()))
            # Queue subscribers — message level (for SSE token streaming)
            if message_id:
                msg_key = f"{conversation_id}:{message_id}"
                queue_targets.update(self._queue_subscribers.get(msg_key, set()))

        # Send to WebSocket subscribers
        for ws in list(ws_targets):
            try:
                await ws.send_json(message)
            except Exception:
                await self.disconnect(ws, conversation_id)

        # Send to queue subscribers
        for queue in list(queue_targets):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                logger.warning(
                    "SSE queue full for conversation_id=%s, dropping event %s",
                    conversation_id,
                    event_type,
                )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def subscriber_count(self, conversation_id: str) -> int:
        """Return the number of active subscribers for a conversation."""
        ws_count = len(self._ws_subscribers.get(conversation_id, set()))
        q_count = sum(
            len(queues)
            for key, queues in self._queue_subscribers.items()
            if key == conversation_id or key.startswith(f"{conversation_id}:")
        )
        return ws_count + q_count
