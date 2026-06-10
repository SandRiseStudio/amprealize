from __future__ import annotations

import pytest

import json
from types import SimpleNamespace

from amprealize.inventory_answer_service import InventoryAnswerService
from amprealize.resource_analysis import (
    ResourceAnalysisIntent,
    ResourceAnalysisService,
    ServiceBackedResourceInventoryProvider,
)

pytestmark = pytest.mark.unit


def _inventory():
    return {
        "projects": [
            {"project_id": "proj-guideai", "name": "GuideAI", "slug": "guideai"},
            {"project_id": "proj-core", "name": "Core", "slug": "core"},
        ],
        "boards_by_project": {
            "proj-guideai": [
                {"board_id": "board-guideai", "name": "GuideAI", "project_id": "proj-guideai"}
            ],
            "proj-core": [
                {"board_id": "board-core", "name": "Core", "project_id": "proj-core"}
            ],
        },
        "work_items_by_project": {
            "proj-guideai": [
                {
                    "item_id": "wi-1",
                    "title": "Fix chat routing",
                    "status": "blocked",
                    "board_id": "board-guideai",
                    "project_id": "proj-guideai",
                },
                {
                    "item_id": "wi-2",
                    "title": "Improve analytics",
                    "status": "todo",
                    "board_id": "board-guideai",
                    "project_id": "proj-guideai",
                },
            ],
            "proj-core": [
                {
                    "item_id": "wi-3",
                    "title": "Clean up settings",
                    "status": "blocked",
                    "board_id": "board-core",
                    "project_id": "proj-core",
                }
            ],
        },
        "runs": [
            {"run_id": "run-1", "status": "running", "project_id": "proj-guideai"},
            {"run_id": "run-2", "status": "failed", "project_id": "proj-guideai"},
        ],
        "behaviors": [{"name": "behavior_use_raze_for_logging", "status": "approved"}],
        "wiki_hits": [{"title": "GuideAI overview", "path": "wiki/guideai.md"}],
        "settings": {"execution_mode": "github_pr"},
        "files": [{"path": "docs/guideai.md", "name": "GuideAI docs", "project_id": "proj-guideai"}],
        "credentials": [{"credential_id": "cred-1", "name": "GitHub token", "scope": "repo"}],
        "conversations": [{"conversation_id": "conv-1", "title": "GuideAI planning"}],
        "conversation_messages": [{"message_id": "msg-1", "conversation_id": "conv-1", "content": "hello"}],
    }


def test_structured_payload_rows_are_json_serializable_with_datetime_fields() -> None:
    from datetime import datetime, timezone

    inv = {
        "work_items_by_project": {
            "proj-guideai": [
                {
                    "item_id": "wi-1",
                    "title": "Task A",
                    "board_id": "b1",
                    "project_id": "proj-guideai",
                    "created_at": datetime(2026, 4, 30, 12, 0, 0, tzinfo=timezone.utc),
                    "updated_at": datetime(2026, 4, 29, 8, 0, 0, tzinfo=timezone.utc),
                },
                {
                    "item_id": "wi-2",
                    "title": "Task B",
                    "board_id": "b1",
                    "project_id": "proj-guideai",
                    "created_at": datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc),
                },
            ],
        },
    }
    answer = ResourceAnalysisService().answer_sync(
        query="What is the most recent work item for GuideAI?",
        inventory=inv,
    )
    assert answer is not None
    import json

    json.dumps(answer.structured_payload)
    json.dumps(answer.source_rows)
    assert "2026-04-30" in answer.source_rows[0]["created_at"]


def test_counts_work_items_on_named_board() -> None:
    answer = ResourceAnalysisService().answer_sync(
        query="how many work items do i have on the guideai board?",
        inventory=_inventory(),
    )

    assert answer is not None
    assert answer.query_plan.intent == ResourceAnalysisIntent.COUNT
    assert answer.query_plan.resource_type == "work_items"
    assert "2 work items" in answer.content.lower()
    assert "matching" not in answer.content.lower()
    assert {row["id"] for row in answer.source_rows} == {"wi-1", "wi-2"}


def test_named_project_id_substring_scopes_work_items(monkeypatch) -> None:
    """Hyphenated ids must not match a shorter ``proj`` word-boundary hit on another project."""

    inv = {
        "projects": [
            {"id": "proj-c3b47e3fd775", "name": "Docs project", "slug": "docs"},
            {"id": "proj-827288785acf", "name": "CLI project", "slug": "cli"},
        ],
        "boards_by_project": {
            "proj-c3b47e3fd775": [
                {"board_id": "brd-docs", "name": "Docs board", "project_id": "proj-c3b47e3fd775"},
            ],
            "proj-827288785acf": [
                {"board_id": "brd-cli", "name": "CLI board", "project_id": "proj-827288785acf"},
            ],
        },
        "work_items_by_project": {
            "proj-c3b47e3fd775": [
                {
                    "item_id": "wi-a",
                    "title": "Alpha",
                    "project_id": "proj-c3b47e3fd775",
                    "board_id": "brd-docs",
                    "status": "backlog",
                },
                {
                    "item_id": "wi-b",
                    "title": "Beta",
                    "project_id": "proj-c3b47e3fd775",
                    "board_id": "brd-docs",
                    "status": "backlog",
                },
            ],
            "proj-827288785acf": [
                {
                    "item_id": "wi-z",
                    "title": "Zed",
                    "project_id": "proj-827288785acf",
                    "board_id": "brd-cli",
                    "status": "backlog",
                },
            ],
        },
    }
    monkeypatch.setattr(
        "amprealize.resource_analysis.secrets.choice",
        lambda rows: rows[0],
    )
    answer = ResourceAnalysisService().answer_sync(
        query="give me a random work item on proj-c3b47e3fd775 board",
        inventory=inv,
    )
    assert answer is not None
    assert len(answer.source_rows) == 1
    assert answer.source_rows[0]["project_id"] == "proj-c3b47e3fd775"
    assert answer.source_rows[0]["item_id"] in {"wi-a", "wi-b"}


def test_list_work_items_named_by_full_project_id_filters_other_projects() -> None:
    inv = {
        "projects": [
            {"id": "proj-c3b47e3fd775", "name": "Docs", "slug": "docs"},
            {"id": "proj-827288785acf", "name": "CLI", "slug": "cli"},
        ],
        "boards_by_project": {
            "proj-c3b47e3fd775": [
                {"board_id": "brd-docs", "name": "Docs board", "project_id": "proj-c3b47e3fd775"},
            ],
            "proj-827288785acf": [
                {"board_id": "brd-cli", "name": "CLI board", "project_id": "proj-827288785acf"},
            ],
        },
        "work_items_by_project": {
            "proj-c3b47e3fd775": [
                {
                    "item_id": "wi-a",
                    "title": "Alpha",
                    "project_id": "proj-c3b47e3fd775",
                    "board_id": "brd-docs",
                    "status": "backlog",
                },
            ],
            "proj-827288785acf": [
                {
                    "item_id": "wi-z",
                    "title": "Zed",
                    "project_id": "proj-827288785acf",
                    "board_id": "brd-cli",
                    "status": "backlog",
                },
            ],
        },
    }
    answer = ResourceAnalysisService().answer_sync(
        query="what work items are on proj-c3b47e3fd775?",
        inventory=inv,
    )
    assert answer is not None
    assert len(answer.source_rows) == 1
    assert answer.source_rows[0]["item_id"] == "wi-a"


def test_counts_projects_includes_names_and_ids_without_meta_tail() -> None:
    answer = ResourceAnalysisService().answer_sync(
        query="how many projects do I have?",
        inventory=_inventory(),
    )
    assert answer is not None
    assert answer.query_plan.intent == ResourceAnalysisIntent.COUNT
    assert answer.query_plan.resource_type == "projects"
    lowered = answer.content.lower()
    assert "2 projects" in lowered
    assert "based on the data included" not in lowered
    assert "GuideAI" in answer.content
    assert "Core" in answer.content
    assert "proj-guideai" in answer.content
    assert "proj-core" in answer.content


def test_counts_features_filters_by_item_type() -> None:
    inv = {
        "projects": [{"project_id": "proj-guideai", "name": "GuideAI", "slug": "guideai"}],
        "boards_by_project": {
            "proj-guideai": [
                {"board_id": "board-guideai", "name": "GuideAI", "project_id": "proj-guideai"}
            ],
        },
        "work_items_by_project": {
            "proj-guideai": [
                {
                    "item_id": "wi-f1",
                    "title": "Ship analytics",
                    "status": "todo",
                    "item_type": "feature",
                    "board_id": "board-guideai",
                    "project_id": "proj-guideai",
                },
                {
                    "item_id": "wi-f2",
                    "title": "Polish onboarding",
                    "status": "todo",
                    "item_type": "feature",
                    "board_id": "board-guideai",
                    "project_id": "proj-guideai",
                },
                {
                    "item_id": "wi-b1",
                    "title": "Fix crash",
                    "status": "todo",
                    "item_type": "bug",
                    "board_id": "board-guideai",
                    "project_id": "proj-guideai",
                },
            ],
        },
    }
    answer = ResourceAnalysisService().answer_sync(
        query="how many features do I have on the guideai project board?",
        inventory=inv,
    )
    assert answer is not None
    assert answer.query_plan.intent == ResourceAnalysisIntent.COUNT
    assert answer.query_plan.resource_type == "work_items"
    assert answer.query_plan.filters.get("item_type_in") == {"feature"}
    assert "2 features" in answer.content.lower()
    assert "matching" not in answer.content.lower()
    assert "across the same scope" in answer.content.lower()
    assert "bug" in answer.content.lower()
    insights = answer.structured_payload.get("insights") or {}
    assert len(insights.get("by_item_type") or []) == 2
    assert {row["id"] for row in answer.source_rows} == {"wi-f1", "wi-f2"}


def test_count_zero_features_reports_other_types_in_scope() -> None:
    inv = {
        "projects": [{"project_id": "proj-guideai", "name": "GuideAI", "slug": "guideai"}],
        "boards_by_project": {
            "proj-guideai": [
                {"board_id": "board-guideai", "name": "GuideAI", "project_id": "proj-guideai"}
            ],
        },
        "work_items_by_project": {
            "proj-guideai": [
                {
                    "item_id": "wi-b1",
                    "title": "Fix crash",
                    "status": "todo",
                    "item_type": "bug",
                    "board_id": "board-guideai",
                    "project_id": "proj-guideai",
                },
            ],
        },
    }
    answer = ResourceAnalysisService().answer_sync(
        query="how many features on the guideai project board?",
        inventory=inv,
    )
    assert answer is not None
    assert answer.query_plan.intent == ResourceAnalysisIntent.COUNT
    assert "don't have any features" in answer.content.lower()
    assert "none match" in answer.content.lower() or "bug" in answer.content.lower()


def test_most_recent_work_item_uses_list_intent_and_latest_created_at() -> None:
    inv = _inventory()
    inv["work_items_by_project"]["proj-guideai"] = [
        {
            "item_id": "wi-old",
            "title": "Older task",
            "status": "todo",
            "board_id": "board-guideai",
            "project_id": "proj-guideai",
            "created_at": "2025-01-01T00:00:00Z",
        },
        {
            "item_id": "wi-new",
            "title": "Newer task",
            "status": "todo",
            "board_id": "board-guideai",
            "project_id": "proj-guideai",
            "created_at": "2026-04-01T00:00:00Z",
        },
    ]
    answer = ResourceAnalysisService().answer_sync(
        query="What is the most recent work item for GuideAI?",
        inventory=inv,
    )
    assert answer is not None
    assert answer.query_plan.intent == ResourceAnalysisIntent.LIST
    assert len(answer.source_rows) == 1
    assert answer.source_rows[0]["item_id"] == "wi-new"


def test_groups_blocked_work_items_by_project() -> None:
    answer = ResourceAnalysisService().answer_sync(
        query="which projects have the most blocked work items?",
        inventory=_inventory(),
    )

    assert answer is not None
    assert answer.query_plan.intent == ResourceAnalysisIntent.ANALYZE
    assert len(answer.source_rows) == 2
    grouped = ResourceAnalysisService().answer_sync(
        query="show blocked work items grouped by project",
        inventory=_inventory(),
    )
    assert grouped is not None
    assert grouped.structured_payload["groups"] == [
        {"group": "proj-core", "count": 1},
        {"group": "proj-guideai", "count": 1},
    ]


def test_summarizes_board_state() -> None:
    answer = ResourceAnalysisService().answer_sync(
        query="summarize the state of the GuideAI board",
        inventory=_inventory(),
    )

    assert answer is not None
    assert answer.query_plan.resource_type == "boards"
    assert "1 boards" in answer.content.lower()


def test_reads_behaviors_wiki_pages_and_settings() -> None:
    service = ResourceAnalysisService()

    behaviors = service.answer_sync(query="what behaviors changed recently?", inventory=_inventory())
    wiki = service.answer_sync(query="show wiki pages about guideai", inventory=_inventory())
    settings = service.answer_sync(query="list settings", inventory=_inventory())

    assert behaviors is not None
    assert behaviors.query_plan.resource_type == "behaviors"
    assert wiki is not None
    assert wiki.query_plan.resource_type == "wiki_pages"
    assert settings is not None
    assert settings.query_plan.resource_type == "settings"


def test_reads_files_credentials_conversations_and_messages() -> None:
    service = ResourceAnalysisService()

    files = service.answer_sync(query="list files for guideai", inventory=_inventory())
    credentials = service.answer_sync(query="how many credentials are available?", inventory=_inventory())
    conversations = service.answer_sync(query="show conversations", inventory=_inventory())
    messages = service.answer_sync(query="list chat messages", inventory=_inventory())

    assert files is not None
    assert files.query_plan.resource_type == "files"
    assert credentials is not None
    assert credentials.query_plan.resource_type == "credentials"
    assert conversations is not None
    assert conversations.query_plan.resource_type == "conversations"
    assert messages is not None
    assert messages.query_plan.resource_type == "conversation_messages"


def test_local_project_path_questions_skip_project_resource_fast_path() -> None:
    """Chat questions about disk/IDE paths must not become *I found N projects…* lists."""

    service = ResourceAnalysisService()
    inv = _inventory()
    local_access = service.answer_sync(
        query="do you have access to my local project path files?",
        inventory=inv,
    )
    guideai_path = service.answer_sync(
        query="do you have access to guideai local project path?",
        inventory=inv,
    )
    assert local_access is None
    assert guideai_path is None

    still_projects = service.answer_sync(query="what projects do I have access to?", inventory=inv)
    assert still_projects is not None
    assert still_projects.query_plan.resource_type == "projects"

    inv_svc = InventoryAnswerService(resource_analysis_service=service)
    assert (
        inv_svc.answer(
            query="do you have access to guideai local project path?",
            inventory=inv,
        )
        is None
    )
    inv_list = inv_svc.answer(query="what projects are available?", inventory=inv)
    assert inv_list is not None
    assert inv_list.answer_type == "projects.list"


@pytest.mark.asyncio
async def test_service_backed_inventory_provider_uses_access_context() -> None:
    class ProjectService:
        def list_projects(self, *, user_id: str, org_id: str):
            assert user_id == "user-1"
            assert org_id == "org-1"
            return [{"project_id": "proj-1", "name": "Project One"}]

    class BoardService:
        def list_boards(self, *, project_id: str):
            assert project_id == "proj-1"
            return [{"board_id": "board-1", "name": "Main", "project_id": project_id}]

        def list_work_items(self, *, project_id: str):
            assert project_id == "proj-1"
            return [{"item_id": "wi-1", "title": "Do work", "project_id": project_id}]

    provider = ServiceBackedResourceInventoryProvider(
        project_service=ProjectService(),
        board_service=BoardService(),
    )

    inventory = await provider(query="list work items", user_id="user-1", org_id="org-1")

    assert inventory["projects"][0]["project_id"] == "proj-1"
    assert inventory["boards_by_project"]["proj-1"][0]["board_id"] == "board-1"
    assert inventory["work_items_by_project"]["proj-1"][0]["item_id"] == "wi-1"


class _PlannerLLM:
    def call(self, messages, **kwargs):  # noqa: ANN001, ANN002, ARG002
        if "read-only query plan" in messages[0]["content"]:
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "resource_type": "runs",
                        "intent": "group",
                        "filters": {"status_in": ["failed"]},
                        "group_by": "project_id",
                        "rationale": "The user asked for failed execution distribution.",
                    }
                )
            )
        return SimpleNamespace(content="There is 1 failed run, grouped under proj-guideai.")


@pytest.mark.asyncio
async def test_llm_planning_is_validated_before_rows_are_answered() -> None:
    answer = await ResourceAnalysisService(llm_client=_PlannerLLM()).answer(
        query="analyze failed executions by project",
        inventory=_inventory(),
    )

    assert answer is not None
    assert answer.query_plan.llm_assisted is True
    assert answer.query_plan.resource_type == "runs"
    assert answer.structured_payload["analysis_mode"] == "llm_assisted"
    assert {row["id"] for row in answer.source_rows} == {"run-2"}


def test_list_empty_user_copy_avoids_engineering_jargon() -> None:
    inv = {
        "projects": [{"project_id": "p1", "name": "Solo", "slug": "solo"}],
        "boards_by_project": {"p1": [{"board_id": "b1", "name": "Main", "project_id": "p1"}]},
        "work_items_by_project": {
            "p1": [
                {
                    "item_id": "w1",
                    "title": "Done task",
                    "status": "done",
                    "board_id": "b1",
                    "project_id": "p1",
                },
            ],
        },
    }
    answer = ResourceAnalysisService().answer_sync(
        query="show open work items on the solo board",
        inventory=inv,
    )
    assert answer is not None
    assert answer.query_plan.intent == ResourceAnalysisIntent.LIST
    lowered = answer.content.lower()
    assert "inventory" not in lowered
    assert "rows" not in lowered
    assert "filters" not in lowered
    assert answer.structured_payload.get("empty_reason") == "filters_excluded_all"


def test_scope_hints_default_project_narrows_work_items() -> None:
    answer = ResourceAnalysisService().answer_sync(
        query="how many work items are on the project board?",
        inventory=_inventory(),
        scope_hints={"project_id": "proj-core"},
    )
    assert answer is not None
    assert answer.query_plan.intent == ResourceAnalysisIntent.COUNT
    assert "1 work item" in answer.content.lower()


def test_multi_board_clarification_requires_choice() -> None:
    inv = {
        "projects": [{"project_id": "p1", "name": "Alpha", "slug": "alpha"}],
        "boards_by_project": {
            "p1": [
                {"board_id": "b1", "name": "Sprint", "project_id": "p1"},
                {"board_id": "b2", "name": "Backlog", "project_id": "p1"},
            ],
        },
        "work_items_by_project": {
            "p1": [
                {"item_id": "w1", "title": "A", "status": "todo", "board_id": "b1", "project_id": "p1"},
                {"item_id": "w2", "title": "B", "status": "todo", "board_id": "b2", "project_id": "p1"},
            ],
        },
    }
    answer = ResourceAnalysisService().answer_sync(
        query="how many work items on the alpha project board?",
        inventory=inv,
        scope_hints={"project_id": "p1"},
    )
    assert answer is not None
    assert answer.requires_clarification is True
    assert "Sprint" in answer.content
    assert "Backlog" in answer.content


def test_backlog_to_in_progress_velocity_with_timestamps() -> None:
    inv = {
        "projects": [{"project_id": "p1", "name": "Alpha", "slug": "alpha"}],
        "boards_by_project": {"p1": [{"board_id": "b1", "name": "Main", "project_id": "p1"}]},
        "work_items_by_project": {
            "p1": [
                {
                    "item_id": "w1",
                    "title": "One",
                    "status": "in progress",
                    "board_id": "b1",
                    "project_id": "p1",
                    "created_at": "2026-04-01T00:00:00Z",
                    "in_progress_at": "2026-04-03T12:00:00Z",
                },
                {
                    "item_id": "w2",
                    "title": "Two",
                    "status": "in progress",
                    "board_id": "b1",
                    "project_id": "p1",
                    "created_at": "2026-04-10T00:00:00Z",
                    "started_at": "2026-04-11T00:00:00Z",
                },
            ],
        },
    }
    q = "How quickly are items moving from backlog to in progress on the alpha project board?"
    answer = ResourceAnalysisService().answer_sync(
        query=q,
        inventory=inv,
        scope_hints={"project_id": "p1"},
    )
    assert answer is not None
    assert answer.answer_type == "work_items.velocity.backlog_to_in_progress"
    assert "median" in answer.content.lower()
    assert answer.structured_payload.get("analysis_mode") == "metric"


def test_backlog_to_in_progress_velocity_insufficient_without_timestamps() -> None:
    inv = {
        "projects": [{"project_id": "p1", "name": "Alpha", "slug": "alpha"}],
        "boards_by_project": {"p1": [{"board_id": "b1", "name": "Main", "project_id": "p1"}]},
        "work_items_by_project": {
            "p1": [
                {
                    "item_id": "w1",
                    "title": "One",
                    "status": "in progress",
                    "board_id": "b1",
                    "project_id": "p1",
                },
            ],
        },
    }
    q = "How quickly are items moving from backlog to in progress on the alpha project board?"
    answer = ResourceAnalysisService().answer_sync(query=q, inventory=inv, scope_hints={"project_id": "p1"})
    assert answer is not None
    assert answer.answer_type == "work_items.velocity.insufficient_data"
    assert answer.structured_payload.get("empty_reason") == "insufficient_transition_timestamps"


def test_agent_project_membership_returns_direct_yes_answer() -> None:
    inv = {
        "projects": [
            {"project_id": "proj-guideai", "name": "GuideAI", "slug": "guideai"},
        ],
        "agent_assignments": [
            {
                "agent_id": "a1",
                "name": "AI Research Agent",
                "slug": "ai_research",
                "project_id": "proj-guideai",
                "role": "primary",
            },
            {
                "agent_id": "a2",
                "name": "Engineering Agent",
                "slug": "engineering",
                "project_id": "proj-guideai",
                "role": "contributor",
            },
        ],
    }
    answer = ResourceAnalysisService().answer_sync(
        query="Is the AI Research agent assigned to the GuideAI project?",
        inventory=inv,
    )
    assert answer is not None
    assert answer.answer_type == "agents.membership"
    assert "yes" in answer.content.lower()
    assert "ai research" in answer.content.lower()
    assert "guideai" in answer.content.lower()
    assert "primary" in answer.content.lower()


def test_agent_project_membership_uses_scope_hint_when_project_not_in_query() -> None:
    inv = {
        "projects": [
            {"project_id": "proj-guideai", "name": "GuideAI", "slug": "guideai"},
            {"project_id": "proj-other", "name": "Other", "slug": "other"},
        ],
        "agent_assignments": [
            {
                "agent_id": "a1",
                "name": "AI Research Agent",
                "slug": "ai_research",
                "project_id": "proj-guideai",
                "role": "primary",
            },
            {
                "agent_id": "a2",
                "name": "AI Research Agent",
                "slug": "ai_research",
                "project_id": "proj-other",
                "role": "contributor",
            },
        ],
    }
    answer = ResourceAnalysisService().answer_sync(
        query="Is the AI Research agent assigned?",
        inventory=inv,
        scope_hints={"project_id": "proj-guideai"},
    )
    assert answer is not None
    assert answer.answer_type == "agents.membership"
    assert "primary" in answer.content.lower()
    assert "guideai" in answer.content.lower()


def test_what_agents_question_stays_on_list_path_not_membership() -> None:
    inv = {
        "projects": [{"project_id": "proj-guideai", "name": "GuideAI", "slug": "guideai"}],
        "agent_assignments": [
            {
                "agent_id": "a1",
                "name": "AI Research Agent",
                "slug": "ai_research",
                "project_id": "proj-guideai",
                "role": "primary",
            },
        ],
    }
    answer = ResourceAnalysisService().answer_sync(
        query="What agents are available on GuideAI?",
        inventory=inv,
    )
    assert answer is not None
    assert answer.answer_type == "agents.list"


# ---------------------------------------------------------------------------
# Answer-synthesis regression tests — completed filter, text_search, large
# result-set synthesis, and agent-membership false-positive guard.
# ---------------------------------------------------------------------------


def _guideai_items_inventory(items: list) -> dict:
    """Helper: wrap a list of work items into a GuideAI inventory dict."""
    return {
        "projects": [{"project_id": "proj-guideai", "name": "GuideAI", "slug": "guideai"}],
        "boards_by_project": {
            "proj-guideai": [
                {"board_id": "board-guideai", "name": "GuideAI", "project_id": "proj-guideai"}
            ]
        },
        "work_items_by_project": {"proj-guideai": items},
    }


def test_completed_filter_returns_only_done_items() -> None:
    """Queries asking for completed work items must apply a done/completed status filter."""
    items = [
        {"item_id": "wi-1", "title": "Build agent execution", "status": "completed", "project_id": "proj-guideai"},
        {"item_id": "wi-2", "title": "Write tests", "status": "todo", "project_id": "proj-guideai"},
        {"item_id": "wi-3", "title": "Add logging", "status": "done", "project_id": "proj-guideai"},
    ]
    answer = ResourceAnalysisService().answer_sync(
        query="which work items have a completed status?",
        inventory=_guideai_items_inventory(items),
    )
    assert answer is not None
    # Should find only the done/completed items, not all items.
    assert answer.metadata["row_count"] < len(items)
    assert all(
        row.get("status") in {"completed", "done"}
        for row in answer.source_rows
    )


def test_text_search_filter_matches_title_and_description() -> None:
    """Text search filter applied in _apply_filters covers both title and description."""
    from amprealize.resource_analysis import ResourceAnalysisService
    items = [
        {"item_id": "wi-1", "title": "Agent execution pipeline", "description": "Core GEP logic", "status": "todo"},
        {"item_id": "wi-2", "title": "Fix login screen", "description": "Auth improvements", "status": "todo"},
        {"item_id": "wi-3", "title": "Refactor storage", "description": "Improve agent execution scaling", "status": "todo"},
    ]
    filters = {"text_search": "agent execution"}
    result = ResourceAnalysisService._apply_filters(items, filters)
    ids = {r["item_id"] for r in result}
    assert "wi-1" in ids, "Title match should be returned"
    assert "wi-3" in ids, "Description match should be returned"
    assert "wi-2" not in ids, "Non-matching item should be excluded"


def test_large_result_set_returns_concise_synthesis_not_raw_dump() -> None:
    """When >10 work items match, answer should include status breakdown, not all rows."""
    items = [
        {
            "item_id": f"wi-{i}",
            "title": f"Work item {i}",
            "status": "todo" if i % 3 else "done",
            "project_id": "proj-guideai",
        }
        for i in range(30)
    ]
    answer = ResourceAnalysisService().answer_sync(
        query="list all work items",
        inventory=_guideai_items_inventory(items),
    )
    assert answer is not None
    # Content should mention the total count and a status breakdown.
    assert "30" in answer.content
    assert "Status breakdown" in answer.content
    # Should NOT include all 30 items inline as bullet points.
    bullet_count = answer.content.count("\n-")
    assert bullet_count <= 12, f"Expected ≤12 bullets for large result, got {bullet_count}"


def test_agent_execution_capability_question_does_not_route_to_agents_membership() -> None:
    """'have we implemented agent execution?' must not activate agent membership analysis."""
    inv = {
        "projects": [{"project_id": "proj-guideai", "name": "GuideAI", "slug": "guideai"}],
        "agent_assignments": [
            {"agent_id": "a1", "name": "GuideAI agent", "slug": "guideai_agent", "project_id": "proj-guideai"},
        ],
    }
    answer = ResourceAnalysisService().answer_sync(
        query="have we already implemented agent execution?",
        inventory=inv,
    )
    # If resource_analysis returns an answer, it must NOT be the agents.membership type.
    if answer is not None:
        assert answer.answer_type != "agents.membership", (
            "Capability questions about execution should not trigger membership lookup"
        )


def test_done_filter_not_applied_when_negated() -> None:
    """'work items not done' should NOT apply a positive done filter."""
    items = [
        {"item_id": "wi-1", "title": "Open task", "status": "todo", "project_id": "proj-guideai"},
        {"item_id": "wi-2", "title": "Closed task", "status": "done", "project_id": "proj-guideai"},
    ]
    answer = ResourceAnalysisService().answer_sync(
        query="show me work items that are not done",
        inventory=_guideai_items_inventory(items),
    )
    assert answer is not None
    # Should only return the open item, not the done one.
    result_ids = {r["item_id"] for r in answer.source_rows}
    assert "wi-1" in result_ids
    assert "wi-2" not in result_ids
