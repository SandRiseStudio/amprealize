"""Golden trace fixtures for LLM and MCP/platform-action chat paths."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence, Tuple

from tests.fixtures.chat_answer_golden_traces import REQUIRED_CHAT_TRACE_FIELDS


@dataclass(frozen=True)
class LlmMcpGoldenScenario:
    """Canonical LLM, platform-action, or MCP scenario."""

    name: str
    user_message_content: str
    expected_route_action_id: str
    expected_route_category: str
    expected_answer_path: str
    expected_answer_type: Optional[str]
    expected_event_types: Tuple[str, ...]


LLM_MCP_GOLDEN_SCENARIOS: Tuple[LlmMcpGoldenScenario, ...] = (
    LlmMcpGoldenScenario(
        name="llm_read_synthesis",
        user_message_content="explain the current workspace architecture",
        expected_route_action_id="chat.read_synthesis",
        expected_route_category="read_synthesis",
        expected_answer_path="llm",
        expected_answer_type=None,
        expected_event_types=(
            "governed_chat.audit_record",
            "chat.phase.latency_ms",
            "chat.context.source_count",
            "chat.fast_path.miss",
            "conversation_reply.generated",
        ),
    ),
    LlmMcpGoldenScenario(
        name="platform_action_work_item_create",
        user_message_content='create a new work item called "golden MCP trace" (work type task) on the guideai project board',
        expected_route_action_id="work_item.manage",
        expected_route_category="work_management",
        expected_answer_path="platform_action",
        expected_answer_type="platform_action_result",
        expected_event_types=(
            "governed_chat.audit_record",
            "chat.phase.latency_ms",
            "chat.context.source_count",
            "chat.fast_path.hit",
            "conversation_reply.generated",
        ),
    ),
)


def get_llm_mcp_scenario(name: str) -> LlmMcpGoldenScenario:
    for scenario in LLM_MCP_GOLDEN_SCENARIOS:
        if scenario.name == name:
            return scenario
    raise KeyError(f"Unknown LLM/MCP golden scenario: {name}")


def last_telemetry_event_for_event_type(events: Sequence[Any], event_type: str) -> Any:
    """Return the last sink event with the given ``event_type`` (search from end)."""
    for ev in reversed(events):
        if getattr(ev, "event_type", None) == event_type:
            return ev
    raise AssertionError(f"No telemetry event with event_type={event_type!r}")


def assert_chat_trace_exporter_parity(
    *,
    stored_trace: Mapping[str, Any],
    telemetry_event: Any,
) -> None:
    exported = telemetry_event.to_dict()
    payload_trace = exported["payload"]["chat_trace"]
    assert payload_trace == stored_trace
    assert all(payload_trace.get(field) for field in REQUIRED_CHAT_TRACE_FIELDS)
    json.dumps(exported)
