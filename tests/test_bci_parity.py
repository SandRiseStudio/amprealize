from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Generator, List, cast

import pytest
from fastapi.testclient import TestClient

from amprealize.adapters import (
    MCPBCIAdapter,
    MCPReflectionAdapter,
    RestBCIAdapter,
    RestReflectionAdapter,
)
from amprealize.api import create_app
from amprealize.behavior_retriever import BehaviorRetriever
from amprealize.behavior_service import Behavior, BehaviorSearchResult, BehaviorService, BehaviorVersion
from amprealize.bci_contracts import (
    BehaviorSnippet,
    ComposePromptRequest,
    PromptFormat,
    PrependedBehavior,
    RetrieveRequest,
    RetrievalStrategy,
    RoleFocus,
    ValidateCitationsRequest,
)
from amprealize.bci_service import BCIService
from amprealize.reflection_service import ReflectionService
from amprealize.telemetry import TelemetryClient


class _StubBehaviorService:
    def __init__(self) -> None:
        self.behavior = Behavior(
            behavior_id="behavior_plan",
            name="Launch Playbook",
            description="Plan launches",
            tags=["launch", "plan"],
            created_at="2025-01-01T00:00:00Z",
            updated_at="2025-01-01T00:00:00Z",
            latest_version="v1",
            status="APPROVED",
        )
        self.version = BehaviorVersion(
            behavior_id="behavior_plan",
            version="v1",
            instruction="Follow the launch checklist",
            role_focus="STRATEGIST",
            status="APPROVED",
            trigger_keywords=["launch"],
            examples=[],
            metadata={"citation_label": "Launch Checklist"},
            effective_from="2025-01-01T00:00:00Z",
            effective_to=None,
            created_by="tester",
            approval_action_id=None,
            embedding_checksum=None,
            embedding=None,
        )

    def search_behaviors(self, request: Any, actor: Any = None) -> List[BehaviorSearchResult]:
        return [
            BehaviorSearchResult(
                behavior=self.behavior,
                active_version=self.version,
                score=0.88,
            )
        ]

    def list_behaviors(self, status: str | None = None, **_: Any) -> List[Dict[str, Any]]:
        """Mimic BehaviorService list response for retriever tests."""
        if status and status != self.behavior.status:
            return []
        return [
            {
                "behavior": self.behavior.to_dict(),
                "active_version": self.version.to_dict(),
            }
        ]


@pytest.fixture()
def bci_service() -> BCIService:
    return BCIService()


@pytest.fixture()
def api_client(tmp_path: Path) -> Generator[TestClient, None, None]:
    behavior_db = tmp_path / "behaviors.db"
    workflow_db = tmp_path / "workflows.db"
    app = create_app(behavior_db_path=behavior_db, workflow_db_path=workflow_db)
    with TestClient(app) as client:
        yield client


def test_bci_contract_roundtrip() -> None:
    request = RetrieveRequest(
        query="Draft a launch plan",
        top_k=7,
        strategy=RetrievalStrategy.EMBEDDING,
        role_focus=RoleFocus.STRATEGIST,
        tags=["launch", "strategy"],
        include_metadata=True,
        embedding_weight=0.65,
        keyword_weight=0.35,
        trace_context={"run_id": "run-123"},
    )
    payload = request.to_dict()
    assert payload["strategy"] == "embedding"
    assert payload["role_focus"] == "STRATEGIST"
    assert payload["trace_context"] == {"run_id": "run-123"}

    roundtrip = RetrieveRequest.from_dict(payload)
    assert roundtrip == request


def test_bci_service_prompt_rendering(bci_service: BCIService) -> None:
    request = ComposePromptRequest(
        query="Summarize the retro",
        behaviors=[
            BehaviorSnippet(
                behavior_id="behavior_plan",
                name="Plan",
                instruction="Lay out the plan",
                citation_label="Plan",
            ),
            BehaviorSnippet(
                behavior_id="behavior_retro",
                name="Retro",
                instruction="Capture learnings",
                citation_label="Retro",
            ),
        ],
        citation_instruction="Reference behaviors explicitly",
        format=PromptFormat.LIST,
    )
    response = bci_service.compose_prompt(request)

    assert "Summarize the retro" in response.prompt
    assert "Reference behaviors explicitly" in response.prompt
    assert response.metadata == {
        "citation_mode": "explicit",
        "format": "list",
        "citation_instruction": "Reference behaviors explicitly",
    }


def test_bci_service_validate_citations_marks_missing(bci_service: BCIService) -> None:
    output = "Use behavior_plan to structure the effort."
    request = ValidateCitationsRequest(
        output_text=output,
        prepended_behaviors=[
            PrependedBehavior(behavior_name="behavior_plan", behavior_id="plan-001"),
            PrependedBehavior(behavior_name="behavior_review", behavior_id="review-001"),
        ],
        minimum_citations=1,
    )
    response = bci_service.validate_citations(request)

    assert response.total_citations >= 1
    assert len(response.valid_citations) == 1
    assert response.missing_behaviors == ["behavior_review"]
    assert response.is_compliant is True


def test_bci_adapters_share_payload_shapes(bci_service: BCIService) -> None:
    rest_adapter = RestBCIAdapter(bci_service)
    mcp_adapter = MCPBCIAdapter(bci_service)

    savings = rest_adapter.compute_token_savings({"baseline_tokens": 750, "bci_tokens": 500})
    assert savings["token_savings"] == 250
    assert savings["token_savings_pct"] == pytest.approx(0.3333, rel=1e-3)

    segment_payload = {"trace_text": "- Plan\n- Execute", "format": "plan_markdown"}
    rest_steps = rest_adapter.segment_trace(segment_payload)["steps"]
    mcp_steps = mcp_adapter.segmentTrace(segment_payload)["steps"]
    assert rest_steps == mcp_steps
    assert len(rest_steps) == 2


def test_bci_mcp_parity_for_core_tools(bci_service: BCIService) -> None:
    rest_adapter = RestBCIAdapter(bci_service)
    mcp_adapter = MCPBCIAdapter(bci_service)

    retrieve_payload = {"query": "Plan a launch", "top_k": 3, "include_metadata": True}
    rest_retrieve = rest_adapter.retrieve(retrieve_payload)
    mcp_retrieve = mcp_adapter.retrieve(retrieve_payload)
    assert rest_retrieve["query"] == mcp_retrieve["query"]
    assert rest_retrieve["strategy_used"] == mcp_retrieve["strategy_used"]
    assert rest_retrieve["results"] == mcp_retrieve["results"]
    assert rest_retrieve["metadata"] == mcp_retrieve["metadata"]

    compose_payload = {
        "query": "Summarize the retro",
        "behaviors": [
            {
                "behavior_id": "behavior_plan",
                "name": "Launch Plan",
                "instruction": "Outline launch plan",
                "citation_label": "Launch Plan",
            }
        ],
        "format": "list",
        "citation_instruction": "Reference behaviors explicitly",
    }
    rest_compose = rest_adapter.compose_prompt(compose_payload)
    mcp_compose = mcp_adapter.composePrompt(compose_payload)
    assert rest_compose == mcp_compose

    validate_payload = {
        "output_text": "Use behavior_plan and behavior_review when communicating decisions.",
        "prepended_behaviors": [
            {"behavior_name": "behavior_plan", "behavior_id": "plan-001"},
            {"behavior_name": "behavior_review", "behavior_id": "review-002"},
        ],
        "minimum_citations": 1,
    }
    rest_validate = rest_adapter.validate_citations(validate_payload)
    mcp_validate = mcp_adapter.validateCitations(validate_payload)
    assert rest_validate.keys() == mcp_validate.keys()
    assert rest_validate["total_citations"] == mcp_validate["total_citations"]
    assert rest_validate["is_compliant"] == mcp_validate["is_compliant"]
    assert rest_validate["missing_behaviors"] == mcp_validate["missing_behaviors"]


def test_reflection_rest_mcp_parity() -> None:
    reflection_service = ReflectionService(bci_service=BCIService(), telemetry=TelemetryClient.noop())
    rest_adapter = RestReflectionAdapter(reflection_service)
    mcp_adapter = MCPReflectionAdapter(reflection_service)

    payload = {
        "trace_text": "Define launch objectives\nOutline launch checklist\nReview risks",
        "trace_format": "chain_of_thought",
        "max_candidates": 2,
        "min_quality_score": 0.3,
        "include_examples": False,
    }

    rest_response = rest_adapter.extract(payload)
    mcp_response = mcp_adapter.extract(payload)

    assert rest_response["trace_step_count"] == mcp_response["trace_step_count"]
    assert rest_response["summary"] == mcp_response["summary"]
    assert rest_response["candidates"] == mcp_response["candidates"]

    rest_metadata = dict(rest_response.get("metadata") or {})
    mcp_metadata = dict(mcp_response.get("metadata") or {})
    rest_metadata.pop("elapsed_ms", None)
    mcp_metadata.pop("elapsed_ms", None)
    assert rest_metadata == mcp_metadata


def test_bci_api_endpoints(api_client: TestClient) -> None:
    """Test BCI RPC-style API endpoint contracts and response shapes.

    This test validates the API contract (status codes, response shapes) rather than
    specific behavior retrieval results, since behavior database state varies across
    test runs and test ordering.
    """
    retrieve_payload = {"query": "How do I plan a launch?", "top_k": 3}
    retrieve = api_client.post("/v1/bci:retrieve", json=retrieve_payload)
    assert retrieve.status_code == 200
    body = retrieve.json()
    assert body["query"] == retrieve_payload["query"]
    assert isinstance(body["results"], list)
    # Validate result shape if results exist (results may be empty if no behaviors indexed)
    if body["results"]:
        first_result = body["results"][0]
        assert first_result["behavior_id"]
        assert first_result["instruction"]
        assert first_result.get("citation_label")
    assert body["metadata"]["retriever_mode"] in {"keyword", "semantic", "legacy"}
    # behavior_count should be >= number of results returned
    assert body["metadata"].get("behavior_count", 0) >= len(body["results"])

    compose_payload = {
        "query": "Summarize the meeting",
        "behaviors": [
            {
                "behavior_id": "behavior_meeting",
                "name": "Meeting Summary",
                "instruction": "Summarize key insights",
            }
        ],
    }
    compose = api_client.post("/v1/bci:composePrompt", json=compose_payload)
    assert compose.status_code == 200
    compose_body = compose.json()
    assert "Summarize the meeting" in compose_body["prompt"]
    assert compose_body["metadata"]["format"] == "list"

    savings_payload = {"baseline_tokens": 1000, "bci_tokens": 600}
    savings = api_client.post("/v1/bci:computeTokenSavings", json=savings_payload)
    assert savings.status_code == 200
    assert savings.json()["token_savings_pct"] == pytest.approx(0.4, rel=1e-3)

    segment_payload = {"trace_text": "- Step one\n- Step two", "format": "plan_markdown"}
    segment = api_client.post("/v1/bci:segmentTrace", json=segment_payload)
    assert segment.status_code == 200
    steps = segment.json()["steps"]
    assert [step["text"] for step in steps] == ["Step one", "Step two"]

    rebuild = api_client.post("/v1/bci:rebuildIndex")
    assert rebuild.status_code == 200
    rebuild_body = rebuild.json()
    assert rebuild_body["status"] in {"ready", "degraded", "unsupported"}


def test_bci_api_rest_endpoints(api_client: TestClient) -> None:
    """Test BCI REST API endpoint contracts and response shapes.

    This test validates the API contract (status codes, response shapes) rather than
    specific behavior retrieval results, since behavior database state varies across
    test runs and test ordering.
    """
    # Test retrieve endpoint shape
    retrieve_payload = {"query": "How do I plan a launch?", "top_k": 2}
    rest_retrieve = api_client.post("/v1/bci/retrieve", json=retrieve_payload)
    assert rest_retrieve.status_code == 200
    retrieve_body = rest_retrieve.json()
    assert retrieve_body["query"] == retrieve_payload["query"]
    assert isinstance(retrieve_body["results"], list)
    # Validate result shape if any results exist
    if retrieve_body["results"]:
        first_rest_result = retrieve_body["results"][0]
        assert first_rest_result["behavior_id"]
        assert first_rest_result["instruction"]
        assert first_rest_result.get("citation_label")
    assert retrieve_body["metadata"]["retriever_mode"] in {"keyword", "semantic", "legacy"}

    compose_payload = {
        "query": "Summarize the sprint",
        "behaviors": [
            {
                "behavior_id": "behavior_sprint",
                "name": "Sprint Summary",
                "instruction": "Highlight blockers and wins",
            }
        ],
    }
    rest_compose = api_client.post("/v1/bci/compose-prompt", json=compose_payload)
    assert rest_compose.status_code == 200
    compose_body = rest_compose.json()
    assert "Summarize the sprint" in compose_body["prompt"]
    assert compose_body["metadata"]["format"] == "list"

    validate_payload = {
        "output_text": "Refer to behavior_plan when outlining the launch.",
        "prepended_behaviors": [
            {"behavior_name": "behavior_plan", "behavior_id": "plan-001"},
            {"behavior_name": "behavior_review", "behavior_id": "review-001"},
        ],
        "minimum_citations": 1,
    }
    rest_validate = api_client.post("/v1/bci/validate-citations", json=validate_payload)
    assert rest_validate.status_code == 200
    validate_body = rest_validate.json()
    assert validate_body["total_citations"] >= 1
    assert validate_body["missing_behaviors"]

    rebuild = api_client.post("/v1/bci/rebuild-index")
    assert rebuild.status_code == 200
    assert rebuild.json()["status"] in {"ready", "degraded", "unsupported"}


def test_behavior_retriever_respects_metadata_toggle(tmp_path: Path) -> None:
    stub = _StubBehaviorService()
    retriever = BehaviorRetriever(
        behavior_service=cast(BehaviorService, stub),
        telemetry=TelemetryClient.noop(),
        index_path=tmp_path / "index.faiss",
        metadata_path=tmp_path / "index.json",
    )
    request = RetrieveRequest(query="Plan the launch", top_k=1, include_metadata=True)

    with_metadata = retriever.retrieve(request)
    assert with_metadata and with_metadata[0].metadata == {"citation_label": "Launch Checklist"}
    assert with_metadata[0].citation_label == "Launch Checklist"

    without_metadata = retriever.retrieve(replace(request, include_metadata=False))
    assert without_metadata and without_metadata[0].metadata is None
    assert without_metadata[0].citation_label == "Launch Checklist"


def test_bci_service_uses_retriever_metadata() -> None:
    stub = _StubBehaviorService()
    telemetry = TelemetryClient.noop()
    retriever = BehaviorRetriever(
        behavior_service=cast(BehaviorService, stub),
        telemetry=telemetry,
    )
    service = BCIService(
        behavior_service=cast(BehaviorService, stub),
        telemetry=telemetry,
        behavior_retriever=retriever,
    )

    response = service.retrieve(RetrieveRequest(query="Plan the launch", top_k=1, include_metadata=False))
    assert response.metadata is not None
    assert response.metadata["retriever_mode"] in {"keyword", "semantic"}
    assert response.results and response.results[0].metadata is None
