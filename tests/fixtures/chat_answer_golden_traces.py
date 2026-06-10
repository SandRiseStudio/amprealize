"""Golden trace fixtures for deterministic and execution-handoff chat answers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple


REQUIRED_CHAT_TRACE_FIELDS: Tuple[str, ...] = (
    "trace_id",
    "span_id",
    "parent_span_id",
    "conversation_id",
    "user_message_id",
    "reply_message_id",
    "route_action_id",
    "route_category",
    "route_mode",
    "answer_path",
)


@dataclass(frozen=True)
class ChatAnswerGoldenScenario:
    """Canonical chat answer scenario for golden trace tests."""

    name: str
    user_message_content: str
    expected_route_action_id: str
    expected_route_category: str
    expected_answer_path: str
    expected_answer_type: Optional[str]
    run_id: Optional[str] = None
    work_item_id: Optional[str] = None
    expect_llm_call: bool = False
    expected_event_types: Tuple[str, ...] = ()


CHAT_ANSWER_GOLDEN_SCENARIOS: Tuple[ChatAnswerGoldenScenario, ...] = (
    ChatAnswerGoldenScenario(
        name="deterministic_workspace_inventory",
        user_message_content="what boards exist on the guideai project?",
        expected_route_action_id="resource.analyze",
        expected_route_category="resource_analysis",
        expected_answer_path="deterministic",
        expected_answer_type="boards.list",
        expected_event_types=(
            "chat.trace.started",
            "chat.span.completed",
            "governed_chat.audit_record",
            "chat.phase.latency_ms",
            "chat.context.source_count",
            "chat.span.completed",
            "chat.fast_path.hit",
            "chat.span.completed",
            "chat.span.completed",
            "conversation_reply.generated",
            "chat.span.completed",
            "chat.span.completed",
            "chat.trace.completed",
        ),
    ),
    ChatAnswerGoldenScenario(
        name="execution_handoff_reply",
        user_message_content="execute this work item",
        expected_route_action_id="execution.start",
        expected_route_category="execution_start",
        expected_answer_path="llm",
        expected_answer_type=None,
        run_id="run-chat-handoff-1",
        work_item_id="wi-chat-handoff-1",
        expect_llm_call=True,
        expected_event_types=(
            "chat.trace.started",
            "chat.span.completed",
            "chat.span.completed",
            "governed_chat.audit_record",
            "chat.phase.latency_ms",
            "chat.context.source_count",
            "chat.span.completed",
            "chat.fast_path.miss",
            "chat.span.completed",
            "chat.span.completed",
            "chat.span.completed",
            "conversation_reply.generated",
            "chat.span.completed",
            "chat.span.completed",
            "chat.trace.completed",
        ),
    ),
)


def assert_event_types_subsequence(events: Iterable[Any], expected_types: Sequence[str]) -> None:
    """Assert expected_types occur in order within emitted events (extra prefix events allowed)."""
    actual = [getattr(e, "event_type", str(e)) for e in events]
    exp_list = list(expected_types)
    pos = 0
    for et in actual:
        if pos < len(exp_list) and et == exp_list[pos]:
            pos += 1
    assert pos == len(exp_list), (
        f"Expected ordered subsequence {exp_list!r} not found in {actual!r} "
        f"(matched {pos}/{len(exp_list)})"
    )


def get_chat_answer_scenario(name: str) -> ChatAnswerGoldenScenario:
    for scenario in CHAT_ANSWER_GOLDEN_SCENARIOS:
        if scenario.name == name:
            return scenario
    raise KeyError(f"Unknown chat answer golden scenario: {name}")


def assert_chat_trace_fields(trace: Mapping[str, Any]) -> None:
    missing = [field for field in REQUIRED_CHAT_TRACE_FIELDS if not trace.get(field)]
    assert not missing, f"Missing chat trace fields: {missing}"


def assert_no_llm_generation_events(events: Iterable[Any]) -> None:
    event_types = [getattr(event, "event_type", "") for event in events]
    assert not any(event_type.startswith("execution.llm.") for event_type in event_types)
    assert not any(event_type.startswith("llm.generation.") for event_type in event_types)
