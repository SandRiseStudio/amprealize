"""Tests for LocalExecutionConnectorHub (pairing + pending runs)."""

import pytest

from amprealize.local_execution_connector_hub import (
    LocalExecutionConnectorHub,
    PendingLocalRun,
    get_local_execution_connector_hub,
    reset_local_execution_connector_hub_for_tests,
    schedule_local_connector_outbound,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_hub():
    reset_local_execution_connector_hub_for_tests()
    yield
    reset_local_execution_connector_hub_for_tests()


def test_pairing_and_claim_roundtrip():
    hub = LocalExecutionConnectorHub()
    code, _exp = hub.create_pairing_code(user_id="alice")
    dev = hub.claim_pairing_code(code=code, label="laptop")
    assert dev.user_id == "alice"
    assert dev.device_token.startswith("lec_")
    resolved = hub.resolve_device_token(dev.device_token)
    assert resolved is not None
    assert resolved.device_id == dev.device_id


def test_claim_invalid_code():
    hub = LocalExecutionConnectorHub()
    with pytest.raises(KeyError):
        hub.claim_pairing_code(code="ZZZZ-ZZZZ", label="x")


def test_user_has_live_connector_socket():
    hub = LocalExecutionConnectorHub()
    assert hub.user_has_live_connector_socket("alice") is False
    assert hub.user_has_live_connector_socket("") is False
    ws = object()  # hub stores arbitrary WebSocket-like references
    hub.register_websocket(user_id="alice", websocket=ws)
    assert hub.user_has_live_connector_socket("alice") is True
    hub.unregister_websocket(user_id="alice", websocket=ws)
    assert hub.user_has_live_connector_socket("alice") is False


def test_enqueue_and_pop_pending():
    hub = LocalExecutionConnectorHub()
    p = PendingLocalRun(
        run_id="r1",
        cycle_id="c1",
        user_id="alice",
        org_id="o1",
        project_id="p1",
        work_item_id="w1",
    )
    hub.enqueue_pending_run(p)
    popped = hub.pop_pending_runs_for_user("alice")
    assert len(popped) == 1
    assert popped[0].run_id == "r1"
    assert hub.pop_pending_runs_for_user("alice") == []


def test_schedule_outbound_buffers_without_event_loop():
    hub = get_local_execution_connector_hub()
    schedule_local_connector_outbound("bob", {"type": "run.cancel_requested", "run_id": "r9"})
    assert hub._outbound_buffer.get("bob")  # noqa: SLF001
    assert hub._outbound_buffer["bob"][0]["run_id"] == "r9"  # noqa: SLF001
