from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

from amprealize.conversation_realtime_redis import RedisConversationRealtimeBackend

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


class FakeRedisClient:
    def __init__(self) -> None:
        self.xadd_calls: List[Dict[str, Any]] = []
        self.expire_calls: List[tuple[str, int]] = []
        self.publish_calls: List[tuple[str, str]] = []
        self.stream_rows: List[tuple[str, Dict[str, str]]] = []

    async def xadd(
        self,
        key: str,
        fields: Dict[str, str],
        *,
        maxlen: int,
        approximate: bool,
    ) -> None:
        self.xadd_calls.append(
            {
                "key": key,
                "fields": fields,
                "maxlen": maxlen,
                "approximate": approximate,
            }
        )

    async def expire(self, key: str, ttl: int) -> None:
        self.expire_calls.append((key, ttl))

    async def publish(self, channel: str, encoded: str) -> None:
        self.publish_calls.append((channel, encoded))

    async def xrange(self, key: str, min: str = "0-0", count: Optional[int] = None) -> List[tuple[str, Dict[str, str]]]:
        return self.stream_rows


@pytest.mark.asyncio
async def test_redis_backend_publishes_to_pubsub_and_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeRedisClient()
    monkeypatch.setattr(
        "amprealize.conversation_realtime_redis.redis_async.from_url",
        lambda *args, **kwargs: client,
    )
    backend = RedisConversationRealtimeBackend(
        redis_url="redis://localhost:6379/0",
        replay_ttl_seconds=120,
        stream_maxlen=10,
    )

    await backend.publish(
        conversation_id="conv-1",
        message_id="msg-1",
        event={
            "type": "reply.token",
            "event_id": "evt-1",
            "payload": {"token": "hello"},
        },
    )

    assert len(client.xadd_calls) == 2
    assert client.xadd_calls[0]["key"] == "amprealize:chat:conversation:conv-1:events"
    assert client.xadd_calls[1]["key"] == "amprealize:chat:conversation:conv-1:message:msg-1"
    assert client.expire_calls == [
        ("amprealize:chat:conversation:conv-1:events", 120),
        ("amprealize:chat:conversation:conv-1:message:msg-1", 120),
    ]
    assert client.publish_calls[0][0] == "amprealize:chat:conversation:conv-1:pubsub"
    assert json.loads(client.publish_calls[0][1])["event_id"] == "evt-1"


@pytest.mark.asyncio
async def test_redis_backend_replays_message_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeRedisClient()
    client.stream_rows = [
        (
            "1-0",
            {
                "event": json.dumps(
                    {
                        "type": "reply.started",
                        "event_id": "evt-1",
                        "payload": {"label": "Thinking..."},
                    }
                )
            },
        )
    ]
    monkeypatch.setattr(
        "amprealize.conversation_realtime_redis.redis_async.from_url",
        lambda *args, **kwargs: client,
    )
    backend = RedisConversationRealtimeBackend(redis_url="redis://localhost:6379/0")

    events = await backend.replay(conversation_id="conv-1", message_id="msg-1")

    assert events == [
        {
            "type": "reply.started",
            "event_id": "evt-1",
            "payload": {"label": "Thinking..."},
        }
    ]
