"""Tests for chat transcript → OpenAI-style message assembly."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from amprealize.chat_transcript import (
    THREAD_SUMMARY_METADATA_KEY,
    build_transcript_openai_messages,
    messages_to_transcript_turns,
)
from amprealize.conversation_contracts import ActorType, Message, MessageType

pytestmark = pytest.mark.unit


def _msg(
    mid: str,
    content: str,
    *,
    sender_type: ActorType,
    created: datetime,
) -> Message:
    return Message(
        id=mid,
        conversation_id="conv-1",
        sender_id="u1" if sender_type == ActorType.USER else "agent-1",
        sender_type=sender_type,
        content=content,
        message_type=MessageType.TEXT,
        created_at=created,
    )


def test_messages_to_transcript_turns_maps_roles_and_anchor():
    base = datetime(2026, 4, 1, tzinfo=timezone.utc)
    m_user = _msg("u1", "hello", sender_type=ActorType.USER, created=base)
    m_agent = _msg("a1", "hi there", sender_type=ActorType.AGENT, created=base + timedelta(minutes=1))
    m_user2 = _msg("u2", "follow up", sender_type=ActorType.USER, created=base + timedelta(minutes=2))
    turns = messages_to_transcript_turns(
        [m_user2, m_user, m_agent],
        anchor_message_id="u2",
    )
    assert [t["role"] for t in turns] == ["user", "assistant", "user"]
    assert turns[-1]["content"] == "follow up"


def test_coalesce_same_role_merges_consecutive():
    base = datetime(2026, 4, 1, tzinfo=timezone.utc)
    m1 = _msg("u1", "a", sender_type=ActorType.USER, created=base)
    m2 = _msg("u2", "b", sender_type=ActorType.USER, created=base + timedelta(minutes=1))
    turns = messages_to_transcript_turns([m1, m2], anchor_message_id="u2")
    assert len(turns) == 1
    assert "---" in turns[0]["content"]


def test_build_transcript_includes_thread_summary_prefix():
    class _SVC:
        def list_messages(self, *args, **kwargs):
            base = datetime(2026, 4, 1, tzinfo=timezone.utc)
            return (
                [
                    _msg("u1", "ping", sender_type=ActorType.USER, created=base),
                ],
                1,
                False,
            )

    res = build_transcript_openai_messages(
        conversation_service=_SVC(),
        conversation_id="conv-1",
        user_id="user-1",
        org_id=None,
        user_message_id="u1",
        model_id="gpt-4o",
        thread_summary="Earlier we discussed auth.",
    )
    assert res.thread_summary_injected is True
    assert res.messages[0]["role"] == "user"
    assert "Earlier we discussed auth." in res.messages[0]["content"]
    assert res.messages[-1]["content"] == "ping"


def test_thread_summary_metadata_key_constant():
    assert THREAD_SUMMARY_METADATA_KEY == "thread_summary"
