from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from amprealize.boards.contracts import (
    CreateWorkItemRequest,
    UpdateWorkItemRequest,
    WorkItemType,
    get_research_body_markdown,
    get_research_url,
)
from amprealize.execution_gateway import ExecutionGateway
from amprealize.research.ingesters.url_ingester import URLIngester, URLIngesterError
from amprealize.research_service import ResearchService
from amprealize.research_contracts import IngestPaperRequest, SourceType
from amprealize.research.ingesters.base import IngestResult

pytestmark = pytest.mark.unit


def test_get_research_body_markdown_reads_metadata() -> None:
    md = "# Title\n\nBody text."
    assert get_research_body_markdown({"research_body_markdown": md}) == md
    assert get_research_body_markdown({"research_body_markdown": "  "}) is None
    assert get_research_body_markdown(None) is None


def test_research_work_item_normalizes_research_url_alias() -> None:
    request = CreateWorkItemRequest(
        item_type="research",
        title="Evaluate Metacognitive Reuse",
        researchUrl="https://example.com/paper",
    )

    assert request.item_type == WorkItemType.RESEARCH
    assert get_research_url(request.metadata) == "https://example.com/paper"


def test_research_work_item_requires_http_url() -> None:
    with pytest.raises(ValidationError, match="Research URL"):
        CreateWorkItemRequest(
            item_type="research",
            title="Evaluate Unsafe Source",
            metadata={"research_url": "file:///etc/passwd"},
        )


def test_update_request_without_research_url_does_not_replace_metadata() -> None:
    request = UpdateWorkItemRequest(title="Rename existing task")

    assert request.metadata is None


def test_url_ingester_blocks_private_network_targets() -> None:
    ingester = URLIngester()

    with pytest.raises(URLIngesterError, match="non-public network"):
        ingester._assert_public_http_url("http://127.0.0.1/paper")

    with pytest.raises(URLIngesterError, match="non-public network"):
        ingester._assert_public_http_url("http://10.0.0.5/paper")


def test_ingest_paper_markdown_carries_source_url_for_attribution() -> None:
    """Markdown ingest with metadata.source_url supports pasted-body + URL citation."""
    svc = ResearchService(context_dir=".")
    md = "# Hello\n\n" + ("word " * 50)
    paper = svc.ingest_paper(
        IngestPaperRequest(
            source=md,
            source_type=SourceType.MARKDOWN,
            title_override="Override title",
            metadata={"source_url": "https://example.com/article"},
        ),
    )
    assert paper.metadata.source_url == "https://example.com/article"
    assert paper.word_count >= 40


def test_research_service_converts_ingest_result_to_paper() -> None:
    service = ResearchService(context_dir=".")
    paper = service._to_ingested_paper(
        "https://example.com/paper",
        SourceType.URL,
        IngestResult(
            content="# Abstract\nUseful research content.",
            metadata={"title": "Useful Research", "source_url": "https://example.com/paper"},
            word_count=4,
            sections=[{"title": "Abstract", "content": "Useful research content."}],
        ),
    )

    assert paper.metadata.title == "Useful Research"
    assert paper.source_type == SourceType.URL
    assert paper.word_count == 4
    assert paper.sections[0].name == "Abstract"


def test_execution_gateway_research_items_reject_non_research_override() -> None:
    gateway = ExecutionGateway.__new__(ExecutionGateway)
    gateway._agents = SimpleNamespace(
        get_agent=lambda agent_id: {
            "agent": SimpleNamespace(agent_id=agent_id, slug="engineering")
        }
    )
    work_item = SimpleNamespace(metadata={"research_url": "https://example.com/paper"})
    request = SimpleNamespace(agent_id_override="agent-1", org_id=None)

    with pytest.raises(ValueError, match="AI Research agent"):
        gateway._load_ai_research_agent(work_item, request)


def test_execution_gateway_research_items_resolve_builtin_agent() -> None:
    agent = SimpleNamespace(agent_id="agent-research", slug="ai_research")
    version = SimpleNamespace(version_id="agent-research:1.0.0")
    gateway = ExecutionGateway.__new__(ExecutionGateway)
    gateway._agents = SimpleNamespace(
        _find_agent_by_slug=lambda slug: agent if slug == "ai_research" else None,
        get_latest_version=lambda agent_id, org_id=None: version,
    )
    work_item = SimpleNamespace(metadata={"research_url": "https://example.com/paper"})
    request = SimpleNamespace(agent_id_override=None, org_id=None)

    resolved_agent, resolved_version = gateway._load_ai_research_agent(work_item, request)

    assert resolved_agent.agent_id == "agent-research"
    assert resolved_version is version
