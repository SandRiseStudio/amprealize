"""Tests for referential follow-up and meta-correction bypass logic.

Verifies that:
- _is_referential_followup detects pronoun-based follow-up messages.
- _is_meta_correction detects user push-back on clarification replies.
- _routing_tail_hints_sync returns referential_followup / meta_correction / has_prior_turns
  when applicable.
- The clarification short-circuit is skipped when there are prior turns AND the message
  is a referential follow-up or meta-correction.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from amprealize.services.conversation_reply_service import (
    ConversationReplyService,
    _is_meta_correction,
    _is_referential_followup,
    ReplyRequest,
)
from amprealize.chat_query_planner import ChatQueryPlanner
from amprealize.feature_flags import FeatureFlagService
from amprealize.resource_analysis import ResourceAnalysisService

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Unit tests for module-level helpers
# ---------------------------------------------------------------------------


class TestIsReferentialFollowup:
    def test_these(self):
        assert _is_referential_followup("these") is True

    def test_those(self):
        assert _is_referential_followup("those") is True

    def test_are_any_of_these_completed(self):
        assert _is_referential_followup("are any of these completed?") is True

    def test_completed_question_at_end(self):
        assert _is_referential_followup("completed?") is True

    def test_done_question(self):
        assert _is_referential_followup("done?") is True

    def test_status_question(self):
        assert _is_referential_followup("status?") is True

    def test_which_of_them(self):
        assert _is_referential_followup("which of them") is True

    def test_long_non_referential_message(self):
        long_msg = "Look at the GuideAI project board and check if agent execution is implemented"
        assert _is_referential_followup(long_msg) is False

    def test_empty(self):
        assert _is_referential_followup("") is False

    def test_regular_question(self):
        assert _is_referential_followup("have we implemented agent execution?") is False


class TestIsMetaCorrection:
    def test_im_asking_you_a_question(self):
        assert _is_meta_correction("I'm asking you a question") is True

    def test_im_no_apostrophe(self):
        assert _is_meta_correction("im asking you a question") is True

    def test_you_didnt_answer(self):
        assert _is_meta_correction("You didn't answer my question") is True

    def test_not_what_i_asked(self):
        assert _is_meta_correction("That's not what I asked") is True

    def test_regular_message(self):
        assert _is_meta_correction("look at the GuideAI project board") is False

    def test_empty(self):
        assert _is_meta_correction("") is False


# ---------------------------------------------------------------------------
# Integration-style tests for _routing_tail_hints_sync
# ---------------------------------------------------------------------------


def _make_msg(sender_type, content, msg_id="x"):
    m = MagicMock()
    m.id = msg_id
    m.sender_type = sender_type
    m.content = content
    return m


class FakeActorType:
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


@pytest.fixture(autouse=True)
def patch_actor_type():
    with patch(
        "amprealize.services.conversation_reply_service.ActorType", FakeActorType
    ):
        yield


def _make_service_with_messages(msgs):
    """Return a minimal ConversationReplyService with _conversation_service returning msgs."""
    from amprealize.services.conversation_reply_service import ConversationReplyService

    svc = ConversationReplyService.__new__(ConversationReplyService)
    svc._conversation_service = MagicMock()
    svc._conversation_service.list_messages.return_value = (msgs, None, None)
    # Minimal stubs for methods called inside _routing_tail_hints_sync
    svc._prior_assistant_suggests_work_item_slot = MagicMock(return_value=False)
    svc._looks_like_short_slot_reply = MagicMock(return_value=False)
    return svc


def _make_request(user_msg: str, conv_id: str = "c1", msg_id: str = "m_current"):
    return ReplyRequest(
        conversation_id=conv_id,
        user_message_id=msg_id,
        user_message_content=user_msg,
        user_id="u1",
    )


class TestRoutingTailHints:
    """Tests for the extended _routing_tail_hints_sync."""

    def test_no_conversation_service_returns_empty(self):
        from amprealize.services.conversation_reply_service import ConversationReplyService

        svc = ConversationReplyService.__new__(ConversationReplyService)
        svc._conversation_service = None
        req = _make_request("completed?")
        result = svc._routing_tail_hints_sync(req)
        assert result == {}

    def test_referential_followup_detected(self):
        """has_prior_turns and referential_followup set when message uses referential pronoun."""
        current_msg = _make_msg(FakeActorType.USER, "are any of these completed?", "m_current")
        prior_agent_msg = _make_msg(FakeActorType.AGENT, "I found 50 work items: ...", "m_prev")
        msgs = [current_msg, prior_agent_msg]

        svc = _make_service_with_messages(msgs)
        req = _make_request("are any of these completed?")
        hints = svc._routing_tail_hints_sync(req)

        assert hints.get("has_prior_turns") is True
        assert hints.get("referential_followup") is True
        assert hints.get("meta_correction") is None or hints.get("meta_correction") is False

    def test_meta_correction_detected(self):
        """meta_correction and has_prior_turns set when user pushes back on clarification."""
        current_msg = _make_msg(FakeActorType.USER, "I'm asking you a question", "m_current")
        prior_agent_msg = _make_msg(FakeActorType.AGENT, "Please clarify.", "m_prev")
        msgs = [current_msg, prior_agent_msg]

        svc = _make_service_with_messages(msgs)
        req = _make_request("I'm asking you a question")
        hints = svc._routing_tail_hints_sync(req)

        assert hints.get("has_prior_turns") is True
        assert hints.get("meta_correction") is True

    def test_no_prior_turns_for_first_message(self):
        """Returns empty when the current message has no prior assistant message."""
        current_msg = _make_msg(FakeActorType.USER, "are any of these completed?", "m_current")
        msgs = [current_msg]  # no prior messages

        svc = _make_service_with_messages(msgs)
        req = _make_request("are any of these completed?")
        hints = svc._routing_tail_hints_sync(req)

        assert hints == {}

    def test_prior_assistant_message_included_in_hints(self):
        """routing_prior_assistant_message is set when prior assistant context exists."""
        current_msg = _make_msg(FakeActorType.USER, "those", "m_current")
        prior_agent_msg = _make_msg(FakeActorType.AGENT, "Found 10 items.", "m_prev")
        msgs = [current_msg, prior_agent_msg]

        svc = _make_service_with_messages(msgs)
        req = _make_request("those")
        hints = svc._routing_tail_hints_sync(req)

        assert hints.get("routing_prior_assistant_message") == "Found 10 items."
        assert hints.get("has_prior_turns") is True


# ---------------------------------------------------------------------------
# _try_execution_capability_answer — work-item enrichment
# ---------------------------------------------------------------------------


class _FakeComposedFragment:
    def __init__(self, inventory: dict) -> None:
        self.source = "workspace_inventory"
        self.metadata = {"inventory": inventory}


class _FakeComposedContext:
    def __init__(self, inventory: dict) -> None:
        self.fragments_included = [_FakeComposedFragment(inventory)]
        self.sources_included: list = []
        self.total_tokens = 0


def _make_capability_request(message: str) -> ReplyRequest:
    return _make_request(message, conv_id="conv-cap-test", msg_id="msg-cap-test")


class TestTryExecutionCapabilityAnswerEnrichment:
    """_try_execution_capability_answer enriches answer with matching work items."""

    def _make_service(self):
        svc = MagicMock()
        svc._routing_tail_hints_sync = MagicMock(return_value={})
        # Use the real implementation via the actual class
        from amprealize.services.conversation_reply_service import ConversationReplyService
        real_svc = ConversationReplyService.__new__(ConversationReplyService)
        return real_svc

    def test_static_facts_returned_without_inventory(self):
        svc = self._make_service()
        req = _make_capability_request("have we already implemented agent execution?")
        result = svc._try_execution_capability_answer(req)
        assert result is not None
        assert "Agent execution is implemented" in result.content
        assert result.answer_type == "capability.agent_execution"

    def test_no_related_items_when_none_match(self):
        svc = self._make_service()
        inventory = {
            "projects": [{"id": "proj-1", "name": "GuideAI"}],
            "work_items_by_project": {
                "proj-1": [
                    {"id": "wi-1", "title": "Add dashboard feature", "status": "done"},
                ]
            },
        }
        composed = _FakeComposedContext(inventory)
        req = _make_capability_request("have we implemented agent execution?")
        result = svc._try_execution_capability_answer(req, composed)
        assert result is not None
        assert result.structured_payload["related_work_item_count"] == 0

    def test_related_items_appended_when_found(self):
        svc = self._make_service()
        inventory = {
            "projects": [{"id": "proj-1", "name": "GuideAI"}],
            "work_items_by_project": {
                "proj-1": [
                    {"id": "wi-exec-1", "title": "Implement GEP execution phases", "status": "done"},
                    {"id": "wi-exec-2", "title": "Agent execution feature flag", "status": "in_progress"},
                    {"id": "wi-other", "title": "Fix login page", "status": "done"},
                ]
            },
        }
        composed = _FakeComposedContext(inventory)
        req = _make_capability_request("from the guideai project, have we implemented agent execution?")
        result = svc._try_execution_capability_answer(req, composed)
        assert result is not None
        assert result.structured_payload["related_work_item_count"] == 2
        titles = [i["title"] for i in result.structured_payload["related_work_items"]]
        assert any("GEP" in t or "execution" in t.lower() for t in titles)
        # Work items section appears in content
        assert "Related work items" in result.content
        assert "wi-other" not in result.content

    def test_project_label_used_in_content(self):
        svc = self._make_service()
        inventory = {
            "projects": [{"id": "proj-g", "name": "GuideAI", "slug": "guideai"}],
            "work_items_by_project": {
                "proj-g": [
                    {"id": "wi-1", "title": "WorkItemExecutionService implementation", "status": "done"},
                ]
            },
        }
        composed = _FakeComposedContext(inventory)
        req = _make_capability_request("from guideai, is agent execution implemented?")
        result = svc._try_execution_capability_answer(req, composed)
        assert result is not None
        assert "GuideAI" in result.content

    def test_work_items_vs_runs_terminology_note_present(self):
        svc = self._make_service()
        req = _make_capability_request("is agent execution available?")
        result = svc._try_execution_capability_answer(req)
        assert result is not None
        assert "Work items" in result.content or "work items" in result.content
        assert "Runs" in result.content or "runs" in result.content

    def test_status_enum_rendered_as_value_not_class_name(self):
        """WorkItemStatus enum objects must render as plain values, not 'WorkItemStatus.DONE'."""

        class _FakeStatus:
            value = "done"

            def __str__(self):
                return "WorkItemStatus.DONE"

        svc = self._make_service()
        inventory = {
            "projects": [{"id": "p1", "name": "GuideAI"}],
            "work_items_by_project": {
                "p1": [
                    {
                        "id": "wi-enum",
                        "title": "Agent execution phases",
                        "status": _FakeStatus(),
                    }
                ]
            },
        }
        composed = _FakeComposedContext(inventory)
        req = _make_capability_request("from guideai, have we implemented agent execution?")
        result = svc._try_execution_capability_answer(req, composed)
        assert result is not None
        # Status in content must be the enum value, not the class.__str__ representation
        assert "WorkItemStatus.DONE" not in result.content
        assert "`done`" in result.content
        # Also in structured payload
        statuses = [i["status"] for i in result.structured_payload["related_work_items"]]
        assert all(s == "done" for s in statuses)


class TestChatQueryPlanAnswer:
    """Fast chat plans should answer board progress before static platform facts."""

    def test_guideai_implementation_question_uses_work_item_plan(self):
        class _Resp:
            content = """
            {
              "mode": "answer",
              "operation": "summarize_resources",
              "resource_type": "work_items",
              "scope": {"project_id": "proj-g", "project_name": "GuideAI"},
              "topic": "agent execution",
              "metrics": ["status_breakdown", "matching_items"],
              "latency_tier": "fast",
              "requires_approval": false,
              "confidence": 0.9
            }
            """

        class _LLM:
            def call(self, *args, **kwargs):  # noqa: ANN001, ANN003
                return _Resp()

        svc = ConversationReplyService.__new__(ConversationReplyService)
        svc._feature_flags = FeatureFlagService()
        svc._feature_flags.set_flag("feature.chat_query_planner", enabled=True)
        svc._llm_client = _LLM()
        svc._resource_analysis_service = ResourceAnalysisService()
        svc._chat_query_planner = ChatQueryPlanner()

        inventory = {
            "projects": [{"id": "proj-g", "name": "GuideAI"}],
            "work_items_by_project": {
                "proj-g": [
                    {"id": "wi-1", "title": "Agent execution phases", "status": "done"},
                    {"id": "wi-2", "title": "Agent execution UI", "status": "in_progress"},
                    {"id": "wi-3", "title": "Fix login page", "status": "done"},
                ]
            },
        }
        req = _make_capability_request(
            "from the guideai project, have we already implemented agent execution?"
        )
        req.project_id = "proj-g"

        result = svc._try_chat_query_plan_answer(req, _FakeComposedContext(inventory))

        assert result is not None
        assert result.answer_type == "work_items.planned_summary"
        assert "For GuideAI, I found 2 work items related to agent execution." in result.content
        assert "Agent execution is implemented in Amprealize" not in result.content
        assert result.structured_payload["chat_query_plan"]["resource_type"] == "work_items"

    def test_planned_work_item_summary_streams_inline_chips_only(self) -> None:
        published = []

        class _Hub:
            def publish_token(self, conversation_id, stream_message_id, payload, *, event_type):  # noqa: ANN001
                published.append(
                    {
                        "conversation_id": conversation_id,
                        "stream_message_id": stream_message_id,
                        "payload": payload,
                        "event_type": event_type,
                    }
                )

        svc = ConversationReplyService.__new__(ConversationReplyService)
        svc._event_hub = _Hub()
        req = _make_request("from the guideai project, have we already implemented agent execution?")

        svc._publish_reply_event(
            req,
            "stream-1",
            "reply.step",
            phase="direct_answer",
            label="Answering from workspace inventory",
            source_rows=[],
            badge="Workspace inventory",
        )

        assert published
        assert "source_rows" not in published[0]["payload"]
