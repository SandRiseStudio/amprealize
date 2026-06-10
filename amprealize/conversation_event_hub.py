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
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional, Protocol, Set

from starlette.websockets import WebSocket

logger = logging.getLogger(__name__)


class ConversationRealtimeBackend(Protocol):
    """Optional cross-process realtime backend for hot chat events."""

    async def publish(
        self,
        *,
        conversation_id: str,
        event: Dict[str, Any],
        message_id: Optional[str] = None,
    ) -> None:
        ...

    async def replay(
        self,
        *,
        conversation_id: str,
        message_id: Optional[str] = None,
        after_id: str = "0-0",
        limit: int = 250,
    ) -> list[Dict[str, Any]]:
        ...

    async def subscribe(
        self,
        *,
        conversation_id: str,
        callback: Callable[[Dict[str, Any]], Awaitable[None]],
    ) -> Any:
        ...


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

# Reply lifecycle events. Legacy token/complete/error names remain supported for
# clients that only need the raw text stream.
EVENT_REPLY_STARTED = "reply.started"
EVENT_REPLY_STEP = "reply.step"
EVENT_REPLY_TOKEN = "reply.token"
EVENT_REPLY_COMPLETE = "reply.complete"
EVENT_REPLY_ERROR = "reply.error"


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

    def __init__(
        self,
        realtime_backend: Optional[ConversationRealtimeBackend] = None,
        *,
        max_remote_subscriptions: Optional[int] = None,
    ) -> None:
        # conversation_id → set of WebSocket connections
        self._ws_subscribers: Dict[str, Set[WebSocket]] = {}
        # conversation_id → set of asyncio.Queue (for SSE)
        self._queue_subscribers: Dict[str, Set[asyncio.Queue]] = {}
        # conversation_id → {actor_id: _TypingState}
        self._typing: Dict[str, Dict[str, _TypingState]] = {}
        self._lock = asyncio.Lock()
        # Cache the main event loop so sync callers (threadpool) can schedule broadcasts.
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._realtime_backend = realtime_backend
        self._max_remote_subscriptions = (
            max_remote_subscriptions if (max_remote_subscriptions or 0) > 0 else None
        )
        self._origin_id = f"hub-{uuid.uuid4().hex}"
        self._remote_subscriptions: Dict[str, Any] = {}
        self._seen_event_ids: Set[str] = set()
        self._seen_event_order: deque[str] = deque(maxlen=2048)

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
        await self._ensure_remote_subscription(conversation_id)
        await self._replay_recent_events_to_websocket(websocket, conversation_id)

    async def disconnect(
        self,
        websocket: WebSocket,
        conversation_id: Optional[str] = None,
    ) -> None:
        """Remove a WebSocket subscriber.

        If *conversation_id* is ``None``, remove from **all** conversations
        (used on unexpected disconnection).
        """
        affected: list[str] = []
        async with self._lock:
            if conversation_id:
                subs = self._ws_subscribers.get(conversation_id)
                if subs and websocket in subs:
                    subs.discard(websocket)
                    affected.append(conversation_id)
            else:
                for cid, subs in list(self._ws_subscribers.items()):
                    if websocket in subs:
                        subs.discard(websocket)
                        affected.append(cid)
        for cid in affected:
            await self._maybe_teardown_remote_subscription(cid)

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
        await self._ensure_remote_subscription(conversation_id)
        await self._replay_recent_events(queue, conversation_id, message_id=message_id)
        return queue

    async def unsubscribe_queue(self, queue: asyncio.Queue, *, conversation_id: Optional[str] = None) -> None:
        """Remove a queue subscriber."""
        teardown_ids: list[str] = []
        async with self._lock:
            if conversation_id:
                for key in list(self._queue_subscribers):
                    if key == conversation_id or key.startswith(f"{conversation_id}:"):
                        self._queue_subscribers[key].discard(queue)
                teardown_ids.append(conversation_id)
            else:
                touched: Set[str] = set()
                for key, queues in list(self._queue_subscribers.items()):
                    if queue in queues:
                        queues.discard(queue)
                        touched.add(key.split(":", 1)[0] if ":" in key else key)
                teardown_ids.extend(sorted(touched))
        for cid in teardown_ids:
            await self._maybe_teardown_remote_subscription(cid)

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
        publish_remote: bool = True,
        event_id: Optional[str] = None,
        origin_id: Optional[str] = None,
    ) -> None:
        resolved_event_id = event_id or str(payload.get("_event_id") or uuid.uuid4())
        resolved_origin_id = origin_id or self._origin_id
        payload_with_metadata = dict(payload)
        payload_with_metadata.setdefault("_event_id", resolved_event_id)
        payload_with_metadata.setdefault("_origin_id", resolved_origin_id)
        if message_id:
            payload_with_metadata.setdefault("_stream_message_id", message_id)
        event = {
            "type": event_type,
            "payload": payload_with_metadata,
            "event_id": resolved_event_id,
            "origin_id": resolved_origin_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "created_at": time.time(),
        }

        if not self._remember_event_id(resolved_event_id):
            return

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
                await ws.send_json(event)
            except Exception:
                await self.disconnect(ws, conversation_id)

        # Send to queue subscribers
        for queue in list(queue_targets):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "SSE queue full for conversation_id=%s, dropping event %s",
                    conversation_id,
                    event_type,
                )

        if publish_remote and self._realtime_backend:
            await self._realtime_backend.publish(
                conversation_id=conversation_id,
                event=event,
                message_id=message_id,
            )

    async def _ensure_remote_subscription(self, conversation_id: str) -> None:
        if not self._realtime_backend or conversation_id in self._remote_subscriptions:
            return
        if self._max_remote_subscriptions is not None and len(
            self._remote_subscriptions
        ) >= self._max_remote_subscriptions:
            logger.warning(
                "chat_realtime.remote_subscription_cap_reached max=%s conversation_id=%s",
                self._max_remote_subscriptions,
                conversation_id,
            )
            return

        async def _handle_remote_event(event: Dict[str, Any]) -> None:
            if event.get("origin_id") == self._origin_id:
                return
            event_type = str(event.get("type") or "")
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            remote_conversation_id = str(event.get("conversation_id") or conversation_id)
            message_id = event.get("message_id")
            await self._broadcast(
                event_type,
                remote_conversation_id,
                payload,
                message_id=str(message_id) if message_id else None,
                publish_remote=False,
                event_id=str(event.get("event_id") or ""),
                origin_id=str(event.get("origin_id") or ""),
            )

        try:
            self._remote_subscriptions[conversation_id] = await self._realtime_backend.subscribe(
                conversation_id=conversation_id,
                callback=_handle_remote_event,
            )
        except Exception as exc:
            logger.warning(
                "chat_realtime.remote_subscription_failed conversation_id=%s err=%s",
                conversation_id,
                exc,
            )

    def _local_subscriber_count(self, conversation_id: str) -> int:
        """WebSocket + all queue keys scoped to this conversation (incl. message streams)."""
        ws_count = len(self._ws_subscribers.get(conversation_id, set()))
        q_count = sum(
            len(queues)
            for key, queues in self._queue_subscribers.items()
            if key == conversation_id or key.startswith(f"{conversation_id}:")
        )
        return ws_count + q_count

    async def _maybe_teardown_remote_subscription(self, conversation_id: str) -> None:
        """Close Redis listener when no local WS or queue subscribers remain."""
        handle: Any = None
        async with self._lock:
            if not self._realtime_backend:
                return
            if self._local_subscriber_count(conversation_id) > 0:
                return
            handle = self._remote_subscriptions.pop(conversation_id, None)
        if handle is None:
            return
        close_fn = getattr(handle, "close", None)
        if close_fn is None:
            return
        try:
            maybe_coro = close_fn()
            if asyncio.iscoroutine(maybe_coro):
                await maybe_coro
        except Exception as exc:
            logger.warning(
                "chat_realtime.remote_subscription_close_failed conversation_id=%s err=%s",
                conversation_id,
                exc,
            )

    async def _replay_recent_events_to_websocket(
        self,
        websocket: WebSocket,
        conversation_id: str,
    ) -> None:
        """Best-effort Redis Streams replay for a new WebSocket (conversation-wide only)."""
        if not self._realtime_backend:
            return
        try:
            events = await self._realtime_backend.replay(
                conversation_id=conversation_id,
                message_id=None,
            )
        except Exception as exc:
            logger.warning(
                "chat_realtime.ws_replay_failed conversation_id=%s err=%s",
                conversation_id,
                exc,
            )
            return
        for event in events:
            try:
                await websocket.send_json(event)
            except Exception:
                await self.disconnect(websocket, conversation_id)
                break

    async def _replay_recent_events(
        self,
        queue: asyncio.Queue,
        conversation_id: str,
        *,
        message_id: Optional[str],
    ) -> None:
        if not self._realtime_backend:
            return
        try:
            events = await self._realtime_backend.replay(
                conversation_id=conversation_id,
                message_id=message_id,
            )
        except Exception as exc:
            logger.warning(
                "chat_realtime.replay_failed conversation_id=%s message_id=%s err=%s",
                conversation_id,
                message_id,
                exc,
            )
            return
        for event in events:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "SSE queue full for conversation_id=%s, dropping replay event",
                    conversation_id,
                )
                break

    def _remember_event_id(self, event_id: str) -> bool:
        if not event_id:
            return True
        if event_id in self._seen_event_ids:
            return False
        if len(self._seen_event_order) == self._seen_event_order.maxlen:
            oldest = self._seen_event_order.popleft()
            self._seen_event_ids.discard(oldest)
        self._seen_event_order.append(event_id)
        self._seen_event_ids.add(event_id)
        return True

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def subscriber_count(self, conversation_id: str) -> int:
        """Return the number of active subscribers for a conversation."""
        return self._local_subscriber_count(conversation_id)
