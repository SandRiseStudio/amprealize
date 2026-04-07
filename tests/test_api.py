from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, List
import uuid

import pytest
from fastapi.testclient import TestClient

from amprealize.api import create_app

# Avoid picking up a host ACTION / telemetry PG sink from .env so ActionService stays in-memory.
_ACTION_PG_ENV_KEYS = (
    "AMPREALIZE_ACTION_PG_DSN",
    "AMPREALIZE_PG_HOST_ACTION",
    "AMPREALIZE_PG_PORT_ACTION",
    "AMPREALIZE_PG_USER_ACTION",
    "AMPREALIZE_PG_PASS_ACTION",
    "AMPREALIZE_PG_DB_ACTION",
    "AMPREALIZE_PG_PARAMS_ACTION",
)


def _skip_unless_behavior_postgres_reachable() -> None:
    from tests.conftest import get_postgres_dsn

    dsn = get_postgres_dsn("BEHAVIOR")
    if not dsn:
        pytest.skip("BEHAVIOR PostgreSQL DSN not configured")
    try:
        import psycopg2

        conn = psycopg2.connect(dsn, connect_timeout=3)
        conn.close()
    except Exception as exc:
        pytest.skip(f"BEHAVIOR PostgreSQL unreachable: {exc}")


@pytest.fixture()
def api_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[TestClient, None, None]:
    for key in _ACTION_PG_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("AMPREALIZE_TELEMETRY_PG_DSN", raising=False)
    monkeypatch.setenv("AMPREALIZE_TELEMETRY_PATH", str(tmp_path / "telemetry.jsonl"))

    behavior_db = tmp_path / "behaviors.db"
    workflow_db = tmp_path / "workflows.db"
    app = create_app(behavior_db_path=behavior_db, workflow_db_path=workflow_db)
    with TestClient(app) as client:
        yield client


def _sample_actor(surface: str = "CLI") -> dict:
    return {"id": "tester", "role": "STRATEGIST", "surface": surface}


@pytest.mark.unit
def test_action_endpoints(api_client: TestClient) -> None:
    create_payload = {
        "artifact_path": "docs/sample.md",
        "summary": "Document milestone update",
        "behaviors_cited": ["behavior_update_docs_after_changes"],
        "metadata": {"commands": ["amprealize record-action"]},
        "actor": _sample_actor(),
    }
    created = api_client.post("/api/v1/actions", json=create_payload)
    assert created.status_code == 201
    action = created.json()
    assert action["artifact_path"] == "docs/sample.md"

    listed = api_client.get("/api/v1/actions")
    assert listed.status_code == 200
    assert any(item["action_id"] == action["action_id"] for item in listed.json())

    fetched = api_client.get(f"/api/v1/actions/{action['action_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["summary"] == "Document milestone update"

    replay_request = {
        "action_ids": [action["action_id"]],
        "strategy": "SEQUENTIAL",
        "options": {"skip_existing": False, "dry_run": False},
        "actor": _sample_actor(),
    }
    replay = api_client.post("/api/v1/actions:replay", json=replay_request)
    assert replay.status_code == 202
    replay_id = replay.json()["replay_id"]

    status = api_client.get(f"/api/v1/actions/replays/{replay_id}")
    assert status.status_code == 200
    assert status.json()["status"] == "SUCCEEDED"


@pytest.mark.unit
@pytest.mark.integration
def test_behavior_workflow_and_compliance_flows(api_client: TestClient) -> None:
    _skip_unless_behavior_postgres_reachable()
    unique_suffix = uuid.uuid4().hex[:8]
    behavior_payload = {
        "name": f"Rest Behavior {unique_suffix}",
        "description": "Test behavior via REST",
        "instruction": "Follow documented workflow",
        "role_focus": "STRATEGIST",
        "trigger_keywords": ["rest", "test"],
        "tags": ["api"],
        "examples": [],
        "metadata": {"source": "api"},
        "actor": _sample_actor("REST_API"),
    }
    behavior_resp = api_client.post("/api/v1/behaviors", json=behavior_payload)
    assert behavior_resp.status_code == 201
    behavior = behavior_resp.json()
    behavior_id = behavior["behavior"]["behavior_id"]

    template_payload = {
        "name": f"REST Workflow {unique_suffix}",
        "description": "Exercise API integration",
        "role_focus": "STRATEGIST",
        "steps": [
            {
                "name": "Plan",
                "description": "Draft strategy",
                "prompt_template": "Use behaviors: {{BEHAVIORS}}",
                "behavior_injection_point": "{{BEHAVIORS}}",
                "required_behaviors": [behavior_id],
                "validation_rules": {},
                "metadata": {},
            }
        ],
        "tags": ["api"],
        "metadata": {"source": "tests"},
        "actor": _sample_actor("REST_API"),
    }
    template_resp = api_client.post("/api/v1/workflows/templates", json=template_payload)
    assert template_resp.status_code == 201
    template = template_resp.json()
    template_id = template["template_id"]

    run_payload = {
        "template_id": template_id,
        "actor": _sample_actor("REST_API"),
        "behavior_ids": [behavior_id],
        "metadata": {"ticket": "TST-123"},
    }
    run_resp = api_client.post("/api/v1/workflows/runs", json=run_payload)
    assert run_resp.status_code == 201
    run = run_resp.json()
    run_id = run["run_id"]

    status_resp = api_client.get(f"/api/v1/workflows/runs/{run_id}")
    assert status_resp.status_code == 200
    assert status_resp.json()["run_id"] == run_id

    checklist_payload = {
        "title": f"API Compliance {unique_suffix}",
        "description": "Ensure parity",
        "template_id": template_id,
        "milestone": "Milestone 2",
        "compliance_category": ["parity"],
        "actor": _sample_actor("REST_API"),
    }
    checklist_resp = api_client.post("/api/v1/compliance/checklists", json=checklist_payload)
    assert checklist_resp.status_code == 201
    checklist = checklist_resp.json()
    checklist_id = checklist["checklist_id"]

    step_payload = {
        "title": "Document evidence",
        "status": "COMPLETED",
        "evidence": {"docs": ["PRD.md"]},
        "behaviors_cited": [behavior_id],
        "actor": _sample_actor("REST_API"),
    }
    step_resp = api_client.post(f"/api/v1/compliance/checklists/{checklist_id}/steps", json=step_payload)
    assert step_resp.status_code == 201

    validate_resp = api_client.post(
        f"/api/v1/compliance/checklists/{checklist_id}:validate",
        json={"actor": _sample_actor("REST_API")},
    )
    assert validate_resp.status_code == 200
    assert "coverage_score" in validate_resp.json()


@pytest.mark.unit
def test_invalid_uuid_paths_return_404(api_client: TestClient) -> None:
    invalid_id = "not-a-valid-uuid"

    run_resp = api_client.get(f"/api/v1/runs/{invalid_id}")
    assert run_resp.status_code == 404
    assert run_resp.json()["detail"] == "Run not found"

    checklist_resp = api_client.get(f"/api/v1/compliance/checklists/{invalid_id}")
    assert checklist_resp.status_code == 404
    assert checklist_resp.json()["detail"] == "Checklist not found"

    record_resp = api_client.post(
        f"/api/v1/compliance/checklists/{invalid_id}/steps",
        json={
            "title": "Invalid reference",
            "status": "PENDING",
            "evidence": {},
            "actor": _sample_actor("REST_API"),
        },
    )
    assert record_resp.status_code == 404

    validate_resp = api_client.post(
        f"/api/v1/compliance/checklists/{invalid_id}:validate",
        json={"actor": _sample_actor("REST_API")},
    )
    assert validate_resp.status_code == 404


@pytest.mark.unit
def test_task_assignment_and_analytics(api_client: TestClient) -> None:
    tasks_resp = api_client.post("/api/v1/tasks:listAssignments", json={"function": "engineering"})
    assert tasks_resp.status_code == 200
    tasks: List[dict] = tasks_resp.json()
    assert all(task["function"] == "Engineering" for task in tasks)

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    events = [
        {
            "event_id": "evt-plan",
            "timestamp": now,
            "event_type": "plan_created",
            "actor": _sample_actor(),
            "run_id": "run-analytics",
            "action_id": None,
            "session_id": None,
            "payload": {
                "template_id": "wf-analytics",
                "template_name": "Analytics",
                "behavior_ids": ["behavior_curate_behavior_handbook"],
                "baseline_tokens": 200,
            },
        },
        {
            "event_id": "evt-update",
            "timestamp": now,
            "event_type": "execution_update",
            "actor": _sample_actor(),
            "run_id": "run-analytics",
            "action_id": None,
            "session_id": None,
            "payload": {
                "template_id": "wf-analytics",
                "behaviors_cited": ["behavior_curate_behavior_handbook"],
                "status": "COMPLETED",
                "output_tokens": 120,
                "token_savings_pct": 0.4,
            },
        },
    ]

    projection_resp = api_client.post(
        "/api/v1/analytics:projectKPI",
        json={"events": events, "include_facts": False},
    )
    assert projection_resp.status_code == 200
    summary = projection_resp.json()["summary"]
    assert summary["total_runs"] == 1
    assert summary["behavior_reuse_pct"] == 100.0


@pytest.mark.unit
def test_reflection_extract_endpoint(api_client: TestClient) -> None:
    trace_text = "Analyze stakeholder goals and constraints\nDesign reusable interaction checklist\nShare draft behaviors with team"
    payload = {
        "trace_text": trace_text,
        "trace_format": "chain_of_thought",
        "run_id": "run-reflection-test",
        "max_candidates": 3,
        "min_quality_score": 0.5,
        "include_examples": False,
        "preferred_tags": ["reflection", "planning"],
    }

    response = api_client.post("/api/v1/reflection:extract", json=payload)
    assert response.status_code == 200
    body = response.json()

    assert body["trace_step_count"] >= 2
    assert body["metadata"]["total_candidates"] >= 1

    candidates = body["candidates"]
    assert candidates, "expected at least one reflection candidate"
    top_candidate = candidates[0]
    assert top_candidate["instruction"].startswith("Analyze")
    assert top_candidate["slug"].startswith("behavior_")
    assert top_candidate["quality_scores"]["clarity"] >= 0.0
