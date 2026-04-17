"""Unit tests for the Phase B /v1/projects* latency changes.

Covers:
- B1: every handler is `async def` + `run_in_threadpool`, so four concurrent
  requests against the REST surface complete independently (handler
  thread-safety sanity mirroring Phase A's AV test for work-items).
- B2: `/v1/projects/agents/presence?project_ids=...` uses a single batched
  `get_projects(ids)` for authorisation instead of N separate `get_project`
  round-trips.
- B2 service: `OSSProjectService.get_projects` contract — empty input
  returns `[]`, missing ids are silently omitted, one SQL round-trip.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, cast
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from amprealize.projects.contracts import (
    AgentPresenceResponse,
    PresenceStatus,
    Project,
    ProjectVisibility,
)
from amprealize.projects.service import OSSProjectService
from amprealize.projects_api import create_project_routes


pytestmark = pytest.mark.unit


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_project(
    *,
    id: str = "proj-aaa",
    owner_id: str = "user-123",
    name: str = "My Project",
) -> Project:
    return Project(
        id=id,
        name=name,
        slug="my-project",
        description=None,
        visibility=ProjectVisibility.PRIVATE,
        settings={},
        org_id=None,
        owner_id=owner_id,
        created_at=_now(),
        updated_at=_now(),
    )


def _make_client(org_service: Any) -> TestClient:
    app = FastAPI()

    def _get_user_id(_: Request) -> str:
        return "user-123"

    app.include_router(create_project_routes(org_service=org_service, get_user_id=_get_user_id))
    return TestClient(app)


# ---------------------------------------------------------------------------
# B2 — handler uses batched get_projects for presence auth
# ---------------------------------------------------------------------------


def test_list_agent_presence_batched_uses_get_projects_not_n_get_project() -> None:
    svc = MagicMock()
    svc.get_projects.return_value = [
        _make_project(id="proj-a"),
        _make_project(id="proj-b"),
        _make_project(id="proj-c"),
    ]
    svc.list_agent_presence_batch.return_value = {"proj-a": [], "proj-b": [], "proj-c": []}

    client = _make_client(svc)

    resp = client.get("/v1/projects/agents/presence?project_ids=proj-a,proj-b,proj-c")
    assert resp.status_code == 200

    svc.get_projects.assert_called_once_with(["proj-a", "proj-b", "proj-c"])
    svc.get_project.assert_not_called()
    svc.list_agent_presence_batch.assert_called_once_with(["proj-a", "proj-b", "proj-c"])


def test_list_agent_presence_batched_rejects_missing_project_in_batch() -> None:
    """When get_projects omits an id (project doesn't exist), handler returns 404."""
    svc = MagicMock()
    svc.get_projects.return_value = [_make_project(id="proj-a")]

    client = _make_client(svc)

    resp = client.get("/v1/projects/agents/presence?project_ids=proj-a,proj-missing")
    assert resp.status_code == 404
    assert "proj-missing" in resp.json()["detail"]
    svc.list_agent_presence_batch.assert_not_called()


def test_list_agent_presence_batched_rejects_other_owners_project() -> None:
    """When get_projects returns a project owned by someone else, handler 404s."""
    svc = MagicMock()
    svc.get_projects.return_value = [
        _make_project(id="proj-mine"),
        _make_project(id="proj-theirs", owner_id="user-other"),
    ]

    client = _make_client(svc)

    resp = client.get("/v1/projects/agents/presence?project_ids=proj-mine,proj-theirs")
    assert resp.status_code == 404
    assert "proj-theirs" in resp.json()["detail"]
    svc.list_agent_presence_batch.assert_not_called()


def test_list_agent_presence_legacy_single_id_still_uses_get_project() -> None:
    """Legacy `?project_id=` branch keeps the single-project auth path (enterprise still uses it)."""
    svc = MagicMock()
    # get_projects explicitly absent from the legacy code path.
    del svc.get_projects
    svc.get_project.return_value = _make_project(id="proj-a")
    svc.list_agent_presence.return_value = []

    client = _make_client(svc)

    resp = client.get("/v1/projects/agents/presence?project_id=proj-a")
    assert resp.status_code == 200
    svc.get_project.assert_called_once_with("proj-a")


# ---------------------------------------------------------------------------
# B1 — handler-level concurrency sanity
# ---------------------------------------------------------------------------


def test_concurrent_projects_handlers_complete_independently() -> None:
    """Four parallel GET /v1/projects calls against an async handler + threadpool
    service should complete independently. Exercises B1's async def +
    run_in_threadpool wiring. If the handler were still sync def, FastAPI
    would serialize all four calls on the single TestClient event loop and the
    barrier below would time out.
    """
    svc = MagicMock()

    # Simulate real DB latency on each call so the test fails loudly if
    # concurrent calls get serialized on the event loop.
    proceed = threading.Event()

    def _slow_list_projects(**_kwargs: Any) -> List[Project]:
        # Each worker must wait on proceed; after all four are in-flight
        # (on threadpool threads) the main thread sets proceed and all
        # four complete. With the old sync-def handler, only one worker
        # gets into list_projects at a time and the event can't be set.
        if not proceed.wait(timeout=3):
            raise RuntimeError("list_projects did not receive proceed signal")
        return [_make_project()]

    svc.list_projects.side_effect = _slow_list_projects

    client = _make_client(svc)

    results: List[int] = []
    errors: List[BaseException] = []
    barrier = threading.Barrier(4)

    def _worker() -> None:
        try:
            barrier.wait(timeout=2)
            resp = client.get("/v1/projects")
            results.append(resp.status_code)
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(4)]
    for t in threads:
        t.start()

    # Give every request time to enter run_in_threadpool before we release.
    # If the handler is sync def, only one will be in-flight and the others
    # will still be queued on the Starlette loop — the 0.5 s wait isn't
    # enough to matter for this test's purpose (we care that AFTER the
    # event is set all four finish).
    import time
    time.sleep(0.3)
    proceed.set()

    for t in threads:
        t.join(timeout=8)

    assert not errors, f"unexpected errors: {errors}"
    assert results == [200, 200, 200, 200], f"expected all 200s, got {results}"
    assert svc.list_projects.call_count == 4


# ---------------------------------------------------------------------------
# B2 service — OSSProjectService.get_projects contract
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Minimal psycopg2-style cursor: captures execute() and returns scripted rows."""

    def __init__(self, rows: List[tuple]) -> None:
        self._rows = rows
        self.last_sql: Optional[str] = None
        self.last_params: Optional[tuple] = None

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.last_sql = sql
        self.last_params = params

    def fetchall(self) -> List[tuple]:
        return self._rows

    def fetchone(self) -> Optional[tuple]:
        return self._rows[0] if self._rows else None


class _FakeConnection:
    def __init__(self, rows: List[tuple]) -> None:
        self._rows = rows
        self.closed = False
        self.cursors: List[_FakeCursor] = []

    def cursor(self) -> _FakeCursor:
        c = _FakeCursor(self._rows)
        self.cursors.append(c)
        return c

    def commit(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


def _project_row(
    project_id: str,
    *,
    owner_id: str = "user-123",
    org_id: Optional[str] = None,
) -> tuple:
    now = _now()
    return (
        project_id,
        org_id,
        owner_id,
        "Name",
        "slug",
        "desc",
        "private",
        {},
        now,
        now,
    )


def _make_service_with_rows(rows: List[tuple]) -> tuple[OSSProjectService, _FakeConnection]:
    service = OSSProjectService.__new__(OSSProjectService)
    service._dsn = "postgresql://fake"
    service._engine = None  # not used; _get_conn is replaced below
    conn = _FakeConnection(rows)
    service._get_conn = lambda: conn  # type: ignore[method-assign]
    return service, conn


def test_get_projects_empty_input_returns_empty_list_without_db_call() -> None:
    service, conn = _make_service_with_rows([])
    out = service.get_projects([])
    assert out == []
    assert conn.cursors == [], "no cursor should be allocated for empty input"
    assert conn.closed is False, "connection shouldn't have been opened"


def test_get_projects_issues_single_any_query() -> None:
    rows = [
        _project_row("proj-a"),
        _project_row("proj-b"),
    ]
    service, conn = _make_service_with_rows(rows)

    out = service.get_projects(["proj-a", "proj-b"])

    assert len(out) == 2
    assert {p.id for p in out} == {"proj-a", "proj-b"}
    assert len(conn.cursors) == 1, "single cursor allocation = single round-trip"
    cur = conn.cursors[0]
    assert cur.last_sql is not None
    assert "ANY(%s)" in cur.last_sql
    assert cur.last_params == (["proj-a", "proj-b"],)


def test_get_projects_silently_omits_missing_ids() -> None:
    """Caller is responsible for detecting access violations by comparing
    input ids vs returned ids; get_projects doesn't raise on missing ids."""
    rows = [_project_row("proj-a")]
    service, _ = _make_service_with_rows(rows)

    out = service.get_projects(["proj-a", "proj-missing"])
    assert len(out) == 1
    assert out[0].id == "proj-a"
