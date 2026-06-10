"""Redis realtime backend for chat event fanout and short replay.

Redis is the hot path for ephemeral chat events. Neon/Postgres remains the
durable transcript and query store.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

import redis.asyncio as redis_async
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

RealtimeEvent = Dict[str, Any]
RealtimeCallback = Callable[[RealtimeEvent], Awaitable[None]]


@dataclass
class RedisRealtimeSubscription:
    """Handle for a running Redis Pub/Sub listener."""

    task: asyncio.Task
    pubsub: Any

    async def close(self) -> None:
        self.task.cancel()
        try:
            await self.task
        except asyncio.CancelledError:
            pass
        try:
            await self.pubsub.close()
        except Exception:
            logger.debug("chat_realtime.redis_pubsub_close_failed", exc_info=True)


class RedisConversationRealtimeBackend:
    """Redis Pub/Sub plus Redis Streams backend for conversation events."""

    def __init__(
        self,
        *,
        redis_url: str,
        replay_ttl_seconds: int = 900,
        stream_maxlen: int = 1000,
        key_prefix: str = "amprealize:chat",
    ) -> None:
        self._redis_url = redis_url
        self._replay_ttl_seconds = replay_ttl_seconds
        self._stream_maxlen = stream_maxlen
        self._key_prefix = key_prefix.rstrip(":")
        self._client = redis_async.from_url(redis_url, decode_responses=True)

    @property
    def redis_url(self) -> str:
        return self._redis_url

    def _channel_key(self, conversation_id: str) -> str:
        return f"{self._key_prefix}:conversation:{conversation_id}:pubsub"

    def _conversation_stream_key(self, conversation_id: str) -> str:
        return f"{self._key_prefix}:conversation:{conversation_id}:events"

    def _message_stream_key(self, conversation_id: str, message_id: str) -> str:
        return f"{self._key_prefix}:conversation:{conversation_id}:message:{message_id}"

    async def publish(
        self,
        *,
        conversation_id: str,
        event: RealtimeEvent,
        message_id: Optional[str] = None,
    ) -> None:
        """Publish a realtime event and persist a short replay window."""
        encoded = json.dumps(event, default=str, separators=(",", ":"))
        fields = {
            "event": encoded,
            "event_id": str(event.get("event_id") or ""),
            "type": str(event.get("type") or ""),
            "message_id": str(message_id or event.get("message_id") or ""),
        }
        try:
            conversation_stream_key = self._conversation_stream_key(conversation_id)
            await self._client.xadd(
                conversation_stream_key,
                fields,
                maxlen=self._stream_maxlen,
                approximate=True,
            )
            await self._client.expire(conversation_stream_key, self._replay_ttl_seconds)
            if message_id:
                message_stream_key = self._message_stream_key(conversation_id, message_id)
                await self._client.xadd(
                    message_stream_key,
                    fields,
                    maxlen=self._stream_maxlen,
                    approximate=True,
                )
                await self._client.expire(message_stream_key, self._replay_ttl_seconds)
            await self._client.publish(self._channel_key(conversation_id), encoded)
        except RedisError as exc:
            logger.warning(
                "chat_realtime.redis_publish_failed conversation_id=%s event_type=%s err=%s",
                conversation_id,
                event.get("type"),
                exc,
            )

    async def replay(
        self,
        *,
        conversation_id: str,
        message_id: Optional[str] = None,
        after_id: str = "0-0",
        limit: int = 250,
    ) -> List[RealtimeEvent]:
        """Replay recent events for a conversation or in-flight message."""
        stream_key = (
            self._message_stream_key(conversation_id, message_id)
            if message_id
            else self._conversation_stream_key(conversation_id)
        )
        try:
            rows = await self._client.xrange(stream_key, min=after_id, count=limit)
        except RedisError as exc:
            logger.warning(
                "chat_realtime.redis_replay_failed conversation_id=%s message_id=%s err=%s",
                conversation_id,
                message_id,
                exc,
            )
            return []

        events: List[RealtimeEvent] = []
        for _, fields in rows:
            encoded = fields.get("event")
            if not encoded:
                continue
            try:
                event = json.loads(encoded)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
        return events

    async def subscribe(
        self,
        *,
        conversation_id: str,
        callback: RealtimeCallback,
    ) -> RedisRealtimeSubscription:
        """Subscribe to live events for one conversation."""
        pubsub = self._client.pubsub()
        await pubsub.subscribe(self._channel_key(conversation_id))

        async def _listen() -> None:
            try:
                async for message in pubsub.listen():
                    if message.get("type") != "message":
                        continue
                    data = message.get("data")
                    if not isinstance(data, str):
                        continue
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(event, dict):
                        await callback(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "chat_realtime.redis_subscribe_failed conversation_id=%s err=%s",
                    conversation_id,
                    exc,
                )

        return RedisRealtimeSubscription(task=asyncio.create_task(_listen()), pubsub=pubsub)

    async def close(self) -> None:
        await self._client.aclose()


__all__ = [
    "RedisConversationRealtimeBackend",
    "RedisRealtimeSubscription",
]
