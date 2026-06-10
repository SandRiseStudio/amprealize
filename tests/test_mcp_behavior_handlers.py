"""Unit tests for behavior MCP handlers."""

import json
from pathlib import Path

import pytest

from amprealize.mcp.handlers.behavior_handlers import (
    BEHAVIOR_HANDLERS,
    BehaviorToolValidationError,
    handle_get_for_task,
    handle_search,
)


pytestmark = pytest.mark.unit


class FakeBehaviorService:
    def __init__(self) -> None:
        self.last_task_description = None
        self.last_actor = None

    def get_relevant_behaviors_for_task(
        self,
        *,
        task_description,
        role,
        limit,
        actor,
        role_context,
    ):
        self.last_task_description = task_description
        self.last_actor = actor
        return {
            "role": role,
            "task_description": task_description,
            "role_advisory": {"role": role},
            "recommended_behaviors": [],
        }


@pytest.mark.asyncio
async def test_get_for_task_accepts_session_only_arguments():
    service = FakeBehaviorService()

    result = await handle_get_for_task(service, {"_session": {"user_id": "user-123"}})

    assert result["task_description"] == "Start a new Amprealize task using the current session context"
    assert service.last_task_description == result["task_description"]
    assert service.last_actor.id == "user-123"
    assert service.last_actor.surface == "mcp"


@pytest.mark.asyncio
async def test_search_requires_query_at_runtime():
    with pytest.raises(BehaviorToolValidationError, match="query"):
        await handle_search(FakeBehaviorService(), {})


def test_behavior_manifests_have_handlers():
    root = Path(__file__).resolve().parents[1]
    manifest_names = {
        json.loads(path.read_text())["name"]
        for path in (root / "mcp" / "tools").glob("behaviors.*.json")
    }

    assert manifest_names <= set(BEHAVIOR_HANDLERS)
