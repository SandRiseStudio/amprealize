from __future__ import annotations

from typing import Any, Dict

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from amprealize.resource_analysis import ResourceAnalysisService
from amprealize.services.resource_analysis_api import create_resource_analysis_routes

pytestmark = pytest.mark.unit


def _inventory(**kwargs: Any) -> Dict[str, Any]:
    assert kwargs["user_id"] == "user-1"
    return {
        "projects": [{"project_id": "proj-guideai", "name": "GuideAI"}],
        "boards_by_project": {
            "proj-guideai": [{"board_id": "board-guideai", "name": "GuideAI board"}]
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
            ]
        },
    }


def _current_user() -> Dict[str, Any]:
    return {"user_id": "user-1", "org_id": "org-1"}


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(
        create_resource_analysis_routes(
            resource_analysis_service=ResourceAnalysisService(inventory_provider=_inventory),
            get_current_user=_current_user,
        )
    )
    return TestClient(app)


def test_resources_analyze_rest_endpoint_returns_analyst_payload() -> None:
    response = _client().post(
        "/v1/resources:analyze",
        json={"query": "how many work items are on the guideai board?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["answer_type"] == "work_items.count"
    assert payload["query_plan"]["intent"] == "count"
    assert payload["structured_payload"]["card_kind"] == "resource_analysis"
    assert payload["metadata"]["row_count"] == 2


def test_resources_analyze_rest_endpoint_rejects_unknown_resource_query() -> None:
    response = _client().post(
        "/v1/resources:analyze",
        json={"query": "what is the weather today?"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "No supported resource analysis query was detected."
