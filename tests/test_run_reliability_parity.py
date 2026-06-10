"""Parity tests for run reliability snapshot across CLI/REST/MCP."""

from __future__ import annotations

import os
from typing import Generator

import pytest

from amprealize.action_contracts import Actor
from amprealize.adapters import CLIRunServiceAdapter, MCPRunServiceAdapter, RestRunServiceAdapter
from amprealize.run_contracts import Run, RunStatus
from amprealize.run_reliability import (
    GEP_CHECKPOINT_CYCLE_KEY,
    GEP_CHECKPOINT_SEQ_KEY,
    GEP_PHASE_CHECKPOINT_KEY,
    RELIABILITY_CIRCUITS_KEY,
    build_reliability_snapshot,
)
from amprealize.run_service_postgres import PostgresRunService as RunService


@pytest.mark.unit
def test_build_reliability_snapshot_in_memory() -> None:
    actor = Actor(id="a", role="STUDENT", surface="test")
    run = Run(
        run_id="rid-1",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        actor=actor,
        status=RunStatus.RUNNING,
        metadata={
            GEP_CHECKPOINT_SEQ_KEY: 5,
            GEP_CHECKPOINT_CYCLE_KEY: "c1",
            GEP_PHASE_CHECKPOINT_KEY: {"EXECUTING": {"x": 1}},
            RELIABILITY_CIRCUITS_KEY: {"tool:t": {"failures": 0}},
        },
    )
    snap = build_reliability_snapshot(run)
    assert snap["run_id"] == "rid-1"
    assert snap["status"] == RunStatus.RUNNING
    assert snap["checkpoint"]["seq"] == 5
    assert snap["checkpoint"]["cycle_id"] == "c1"
    assert "EXECUTING" in (snap["checkpoint"]["phase_keys"] or [])
    assert snap["circuits"]["tool:t"]["failures"] == 0


def _truncate_run_tables(dsn: str) -> None:
    from conftest import safe_truncate

    safe_truncate(dsn, ["run_steps", "runs"])


def _seed_test_users(dsn: str) -> None:
    import psycopg2

    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            for uid, email, name in [
                ("cli-user", "cli-user@example.com", "CLI User"),
                ("rest-user", "rest-user@example.com", "REST User"),
                ("mcp-user", "mcp-user@example.com", "MCP User"),
            ]:
                cur.execute(
                    """
                    INSERT INTO auth.users (id, email, display_name)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (uid, email, name),
                )
    finally:
        conn.close()


@pytest.fixture
def run_service() -> Generator[RunService, None, None]:
    dsn = os.environ.get("AMPREALIZE_RUN_PG_DSN")
    if not dsn:
        pytest.skip("AMPREALIZE_RUN_PG_DSN not set; skipping PostgreSQL parity tests")

    _truncate_run_tables(dsn)
    _seed_test_users(dsn)
    service = RunService(dsn=dsn)

    try:
        yield service
    finally:
        _truncate_run_tables(dsn)
        if hasattr(service, "_pool") and service._pool:
            service._pool.close()


@pytest.fixture
def cli_adapter(run_service: RunService) -> CLIRunServiceAdapter:
    return CLIRunServiceAdapter(run_service)


@pytest.fixture
def rest_adapter(run_service: RunService) -> RestRunServiceAdapter:
    return RestRunServiceAdapter(run_service)


@pytest.fixture
def mcp_adapter(run_service: RunService) -> MCPRunServiceAdapter:
    return MCPRunServiceAdapter(run_service)


class TestRunReliabilitySnapshotParity:
    def test_reliability_snapshot_matches_across_surfaces(
        self,
        cli_adapter: CLIRunServiceAdapter,
        rest_adapter: RestRunServiceAdapter,
        mcp_adapter: MCPRunServiceAdapter,
    ) -> None:
        created = cli_adapter.create_run(
            actor_id="cli-user",
            actor_role="STRATEGIST",
            workflow_id="wf-rel",
        )
        run_id = created["run_id"]

        meta_patch = {
            "execution_policy": {
                "outbound_reliability": {
                    "defaults": {"max_retries": 2, "timeout_seconds": 30.0},
                }
            },
            GEP_CHECKPOINT_SEQ_KEY: 2,
            GEP_CHECKPOINT_CYCLE_KEY: "cycle-test-1",
            GEP_PHASE_CHECKPOINT_KEY: {
                "PLANNING": {"summary": "ok"},
            },
            RELIABILITY_CIRCUITS_KEY: {
                "tool:example": {"failures": 1, "open_until": None},
            },
        }
        cli_adapter.update_run(run_id, metadata=meta_patch)

        cli_snap = cli_adapter.get_run_reliability(run_id)
        rest_snap = rest_adapter.get_run_reliability(run_id)
        mcp_snap = mcp_adapter.get_reliability(run_id)

        assert cli_snap == rest_snap == mcp_snap
        assert cli_snap["run_id"] == run_id
        assert cli_snap["checkpoint"]["seq"] == 2
        assert cli_snap["checkpoint"]["cycle_id"] == "cycle-test-1"
        assert "PLANNING" in (cli_snap["checkpoint"]["phase_keys"] or [])
        assert cli_snap["outbound_reliability"]["defaults"]["max_retries"] == 2
        assert "tool:example" in cli_snap["circuits"]
        assert cli_snap["status"] == RunStatus.PENDING

    def test_reliability_empty_checkpoint_when_no_gep_metadata(
        self,
        cli_adapter: CLIRunServiceAdapter,
    ) -> None:
        created = cli_adapter.create_run(
            actor_id="cli-user",
            actor_role="STRATEGIST",
            workflow_id="wf-rel-2",
        )
        run_id = created["run_id"]
        snap = cli_adapter.get_run_reliability(run_id)
        assert snap["checkpoint"]["seq"] is None
        assert snap["checkpoint"]["cycle_id"] is None
        assert snap["outbound_reliability"] is None
        assert snap["circuits"] == {}

    def test_reliability_after_status_change(
        self,
        rest_adapter: RestRunServiceAdapter,
        mcp_adapter: MCPRunServiceAdapter,
    ) -> None:
        payload = {
            "actor": {"id": "rest-user", "role": "TEACHER", "surface": "REST_API"},
            "workflow_id": "wf-rel-3",
        }
        created = rest_adapter.create_run(payload)
        run_id = created["run_id"]
        rest_adapter.update_run(
            run_id,
            {"status": RunStatus.RUNNING.value, "metadata": {GEP_CHECKPOINT_SEQ_KEY: 1}},
        )
        r1 = rest_adapter.get_run_reliability(run_id)
        r2 = mcp_adapter.get_reliability(run_id)
        assert r1 == r2
        assert r1["status"] == RunStatus.RUNNING.value
        assert r1["checkpoint"]["seq"] == 1
