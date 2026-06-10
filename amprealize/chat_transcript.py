"""Build OpenAI-style chat transcripts from persisted conversation messages.

Used by ConversationReplyService so the LLM receives native multi-turn user/assistant
messages (Codex/Claude Code style) instead of only the latest user turn.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from amprealize.context_composer import TokenCounter
from amprealize.conversation_contracts import ActorType, MessageType
from amprealize.llm.types import MODEL_CATALOG

logger = logging.getLogger(__name__)

# Optional persisted summary (Phase 2) — written to conversation.metadata by operators or future jobs
THREAD_SUMMARY_METADATA_KEY = "thread_summary"

_DEFAULT_TRANSCRIPT_MAX = 8192
_DEFAULT_FETCH_CAP = 5000


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid int for %s=%r; using default %s", name, raw, default)
        return default


def transcript_max_tokens_for_model(model_id: Optional[str]) -> int:
    """Cap transcript size using env and model context window from MODEL_CATALOG."""
    configured = _env_int("AMPREALIZE_CHAT_TRANSCRIPT_MAX_TOKENS", _DEFAULT_TRANSCRIPT_MAX)
    if model_id and model_id in MODEL_CATALOG:
        ctx = MODEL_CATALOG[model_id].context_limit
        # Reserve ~55% of context for system grounding + output headroom
        cap = max(1024, int(ctx * 0.45))
        return min(configured, cap)
    return configured


@dataclass
class TranscriptBuildResult:
    """Result of assembling LLM messages for a reply."""

    messages: List[Dict[str, str]]
    """OpenAI-style messages (user/assistant only), chronological."""

    transcript_turns: int
    """Number of transcript messages after coalescing."""

    thread_summary_injected: bool
    """True when conversation.metadata['thread_summary'] was prepended."""


def _message_text(msg: Any) -> str:
    """Extract user-visible text from a Message."""
    content = getattr(msg, "content", None) or ""
    if str(content).strip():
        return str(content)
    payload = getattr(msg, "structured_payload", None)
    if isinstance(payload, dict) and payload:
        try:
            return json.dumps(payload, default=str)[:8000]
        except (TypeError, ValueError):
            return str(payload)[:8000]
    return ""


def _role_for_sender(sender_type: Any) -> Optional[str]:
    if sender_type == ActorType.AGENT or (
        isinstance(sender_type, str) and sender_type.lower() == "agent"
    ):
        return "assistant"
    if sender_type == ActorType.USER or (
        isinstance(sender_type, str) and sender_type.lower() == "user"
    ):
        return "user"
    if sender_type == ActorType.SYSTEM or (
        isinstance(sender_type, str) and sender_type.lower() == "system"
    ):
        return None
    return "user"


def _coalesce_same_role(turns: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Merge consecutive messages with the same role (threading / multi-post)."""
    if not turns:
        return []
    out: List[Dict[str, str]] = []
    for t in turns:
        role = t["role"]
        content = t["content"]
        if out and out[-1]["role"] == role:
            out[-1]["content"] = f"{out[-1]['content']}\n\n---\n\n{content}"
        else:
            out.append({"role": role, "content": content})
    return out


def _trim_from_start(turns: List[Dict[str, str]], max_tokens: int) -> List[Dict[str, str]]:
    """Drop oldest turns until the transcript fits max_tokens (inclusive count)."""
    if not turns or max_tokens <= 0:
        return turns
    total = sum(TokenCounter.count_tokens(f"{m['role']}: {m['content']}") for m in turns)
    if total <= max_tokens:
        return turns
    dropped = 0
    while turns and total > max_tokens:
        removed = turns.pop(0)
        total -= TokenCounter.count_tokens(f"{removed['role']}: {removed['content']}")
        dropped += 1
    if dropped:
        logger.info(
            "chat.transcript.trimmed_dropped_oldest dropped_turns=%s max_tokens=%s",
            dropped,
            max_tokens,
        )
    return turns


def messages_to_transcript_turns(
    raw_messages: List[Any],
    *,
    anchor_message_id: str,
) -> List[Dict[str, str]]:
    """Map persisted messages (chronological) to user/assistant turns up to anchor."""
    # Sort chronological
    min_dt = datetime.min.replace(tzinfo=timezone.utc)
    sorted_msgs = sorted(
        raw_messages,
        key=lambda m: m.created_at or min_dt,
    )
    anchor_idx = None
    for i, m in enumerate(sorted_msgs):
        if m.id == anchor_message_id:
            anchor_idx = i
            break
    if anchor_idx is None:
        logger.warning(
            "chat.transcript.anchor_not_found anchor_message_id=%s",
            anchor_message_id,
        )
        return []
    slice_msgs = sorted_msgs[: anchor_idx + 1]

    turns: List[Dict[str, str]] = []
    for m in slice_msgs:
        mt = getattr(m, "message_type", MessageType.TEXT)
        if mt not in (MessageType.TEXT, MessageType.CODE_BLOCK, MessageType.STATUS_CARD):
            # Still allow if we salvage text
            pass
        role = _role_for_sender(m.sender_type)
        if role is None:
            continue
        text = _message_text(m)
        if not text.strip():
            continue
        # Normalize agent id line if needed
        turns.append({"role": role, "content": text})

    turns = _coalesce_same_role(turns)
    return turns


def _paginate_all_messages(conversation_service: Any, **kwargs: Any) -> List[Any]:
    """Fetch messages with include_thread_replies until cap or exhaustion."""
    cap = _env_int("AMPREALIZE_CHAT_TRANSCRIPT_FETCH_CAP", _DEFAULT_FETCH_CAP)
    all_rows: List[Any] = []
    offset = 0
    page = 100
    while offset < cap:
        batch, _total, has_more = conversation_service.list_messages(
            kwargs["conversation_id"],
            user_id=kwargs["user_id"],
            org_id=kwargs.get("org_id"),
            include_thread_replies=True,
            limit=page,
            offset=offset,
        )
        if not batch:
            break
        all_rows.extend(batch)
        offset += len(batch)
        if not has_more or len(batch) < page:
            break
    return all_rows


def build_transcript_openai_messages(
    *,
    conversation_service: Any,
    conversation_id: str,
    user_id: str,
    org_id: Optional[str],
    user_message_id: str,
    model_id: Optional[str],
    thread_summary: Optional[str] = None,
) -> TranscriptBuildResult:
    """Load persisted messages and return OpenAI-style transcript messages (no system)."""
    raw = _paginate_all_messages(
        conversation_service,
        conversation_id=conversation_id,
        user_id=user_id,
        org_id=org_id,
    )
    turns = messages_to_transcript_turns(
        raw,
        anchor_message_id=user_message_id,
    )
    max_tok = transcript_max_tokens_for_model(model_id)
    turns = _trim_from_start(turns, max_tok)

    messages: List[Dict[str, str]] = []
    thread_summary_injected = False
    if thread_summary and str(thread_summary).strip():
        messages.append(
            {
                "role": "user",
                "content": (
                    "[Earlier thread summary — compressed history before the messages below]\n"
                    + str(thread_summary).strip()
                ),
            }
        )
        thread_summary_injected = True

    messages.extend(turns)

    return TranscriptBuildResult(
        messages=messages,
        transcript_turns=len(messages),
        thread_summary_injected=thread_summary_injected,
    )


def merge_system_and_transcript(
    system_prompt: str,
    transcript_messages: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    """Prepend system message to transcript."""
    return [{"role": "system", "content": system_prompt}, *transcript_messages]


__all__ = [
    "THREAD_SUMMARY_METADATA_KEY",
    "TranscriptBuildResult",
    "build_transcript_openai_messages",
    "merge_system_and_transcript",
    "messages_to_transcript_turns",
    "transcript_max_tokens_for_model",
]
