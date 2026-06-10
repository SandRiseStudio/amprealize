"""Tests for ``local_execution_connector_ws_handler`` (daemon → RunService bridge)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from amprealize.action_contracts import Actor
from amprealize.local_execution_connector_ws_handler import apply_connector_daemon_message
from amprealize.run_contracts import RunCreateRequest, RunStatus
from amprealize.run_service import RunService


@pytest.fixture()
def run_service() -> RunService:
    with tempfile.TemporaryDirectory() as tmp:
        yield RunService(db_path=Path(tmp) / "runs.db")


def _make_local_run(run_service: RunService, *, run_user_id: str = "user-1") -> str:
    actor = Actor(id=run_user_id, role="user", surface="api")
    req = RunCreateRequest(
        actor=actor,
        workflow_id="wf",
        workflow_name="work_item_execution",
        metadata={"execution_workspace_kind": "local_connector", "cycle_id": "c1"},
    )
    run = run_service.create_run(req)
    return run.run_id


def test_progress_and_complete_authorized(run_service: RunService) -> None:
    rid = _make_local_run(run_service)
    r1 = apply_connector_daemon_message(
        device_user_id="user-1",
        message={"type": "run.progress", "run_id": rid, "status": "RUNNING", "progress_pct": 10.0},
        run_service=run_service,
    )
    assert r1["ok"] is True
    run = run_service.get_run(rid)
    assert run.status == "RUNNING"

    r2 = apply_connector_daemon_message(
        device_user_id="user-1",
        message={
            "type": "run.complete",
            "run_id": rid,
            "message": "done",
            "outputs": {"x": 1},
        },
        run_service=run_service,
    )
    assert r2["ok"] is True
    done = run_service.get_run(rid)
    assert done.status == RunStatus.COMPLETED


def test_reject_wrong_user(run_service: RunService) -> None:
    rid = _make_local_run(run_service, run_user_id="owner")
    out = apply_connector_daemon_message(
        device_user_id="other",
        message={"type": "run.progress", "run_id": rid, "status": "RUNNING"},
        run_service=run_service,
    )
    assert out == {"ok": False, "error": "forbidden"}


def test_reject_non_local_connector_run(run_service: RunService) -> None:
    actor = Actor(id="u1", role="user", surface="api")
    run = run_service.create_run(
        RunCreateRequest(actor=actor, metadata={"execution_workspace_kind": "cloud_git"})
    )
    out = apply_connector_daemon_message(
        device_user_id="u1",
        message={"type": "run.progress", "run_id": run.run_id, "status": "RUNNING"},
        run_service=run_service,
    )
    assert out["ok"] is False
    assert out["error"] == "run_not_local_connector"


def test_run_fail(run_service: RunService) -> None:
    rid = _make_local_run(run_service)
    out = apply_connector_daemon_message(
        device_user_id="user-1",
        message={"type": "run.fail", "run_id": rid, "error": "boom", "message": "failed"},
        run_service=run_service,
    )
    assert out["ok"] is True
    assert run_service.get_run(rid).status == RunStatus.FAILED


def test_ack_cancel(run_service: RunService) -> None:
    rid = _make_local_run(run_service)
    out = apply_connector_daemon_message(
        device_user_id="user-1",
        message={"type": "run.ack_cancel", "run_id": rid},
        run_service=run_service,
    )
    assert out == {"ok": True}
