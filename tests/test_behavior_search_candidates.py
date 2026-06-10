"""Unit tests for BehaviorService search candidate narrowing."""

from __future__ import annotations

import pytest

from amprealize.behavior_service import (
    Behavior,
    BehaviorSearchResult,
    BehaviorService,
    BehaviorVersion,
    SearchBehaviorsRequest,
)
from amprealize.telemetry import TelemetryClient


pytestmark = pytest.mark.unit


class FakeCache:
    def __init__(self) -> None:
        self.cached = {}

    def _make_key(self, service, operation, params=None):
        return f"{service}:{operation}:{params}"

    def get(self, key):
        return None

    def set(self, key, value, ttl=300):
        self.cached[key] = value
        return True


class CandidateBehaviorService(BehaviorService):
    def __init__(self) -> None:
        self._telemetry = TelemetryClient.noop()
        self.candidate_tokens = None
        self.full_fetch_called = False
        self.behavior = Behavior(
            behavior_id="behavior-1",
            name="behavior_use_raze_for_logging",
            description="Use structured logs",
            tags=["logging", "raze"],
            created_at="",
            updated_at="",
            latest_version="1.0.0",
            status="APPROVED",
        )
        self.version = BehaviorVersion(
            behavior_id="behavior-1",
            version="1.0.0",
            instruction="Add Raze logging to service calls",
            role_focus="Student",
            status="APPROVED",
            trigger_keywords=["logging"],
            examples=[],
            metadata={},
            effective_from="",
            effective_to=None,
            created_by="test",
            approval_action_id=None,
            embedding_checksum=None,
        )

    def _fetch_behavior_candidates_with_versions(
        self,
        *,
        query_tokens,
        status=None,
        namespace=None,
        limit=100,
    ):
        self.candidate_tokens = query_tokens
        return [(self.behavior, [self.version])]

    def _fetch_behaviors_with_versions(self, status=None, namespace=None):
        self.full_fetch_called = True
        return [(self.behavior, [self.version])]


def test_search_behaviors_uses_ranked_candidates_for_query(monkeypatch) -> None:
    import amprealize.behavior_service as behavior_service_module

    monkeypatch.setattr(behavior_service_module, "get_cache", lambda: FakeCache())
    service = CandidateBehaviorService()

    results = service.search_behaviors(
        SearchBehaviorsRequest(query="raze logging", status="APPROVED", limit=5)
    )

    assert service.candidate_tokens == ["raze", "logging"]
    assert service.full_fetch_called is False
    assert [result.behavior.name for result in results] == ["behavior_use_raze_for_logging"]
    assert all(isinstance(result, BehaviorSearchResult) for result in results)


def test_search_behaviors_uses_full_fetch_without_query(monkeypatch) -> None:
    import amprealize.behavior_service as behavior_service_module

    monkeypatch.setattr(behavior_service_module, "get_cache", lambda: FakeCache())
    service = CandidateBehaviorService()

    service.search_behaviors(SearchBehaviorsRequest(query="", status="APPROVED", limit=5))

    assert service.candidate_tokens is None
    assert service.full_fetch_called is True


class FakeRelevantBehaviorService:
    def get_relevant_behaviors_for_task(self, **kwargs):
        return {
            "role": kwargs["role"],
            "task_description": kwargs["task_description"],
            "role_advisory": "Use behavior_use_raze_for_logging.",
            "recommended_behaviors": [
                {
                    "name": "behavior_use_raze_for_logging",
                    "instruction": "Use Raze for structured logging.",
                    "role_focus": "Student",
                    "trigger_keywords": ["logging", "raze"],
                    "score": 0.9,
                    "confidence_score": 0.8,
                }
            ],
        }


def test_mcp_get_for_task_brief_mode_reduces_behavior_metadata() -> None:
    from amprealize.adapters import MCPBehaviorServiceAdapter

    result = MCPBehaviorServiceAdapter(FakeRelevantBehaviorService()).get_for_task(
        {
            "task_description": "Add logging",
            "role": "Student",
            "brief": True,
            "actor": {"id": "test", "role": "MCP", "surface": "MCP"},
        }
    )

    behavior = result["recommended_behaviors"][0]
    assert behavior == {
        "name": "behavior_use_raze_for_logging",
        "instruction": "Use Raze for structured logging.",
        "role_focus": "Student",
        "score": 0.9,
    }
