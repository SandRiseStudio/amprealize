#!/usr/bin/env python3
"""Test validate_all_dsns logic in isolation.

Simulates what the pytest session fixture does: scans all AMPREALIZE_*_PG_DSN
env vars and blocks if any point to production databases.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.conftest import assert_test_database, _mask_dsn_password

passed = 0
failed = 0


def check(name, func):
    global passed, failed
    try:
        func()
        print(f"  PASS: {name}")
        passed += 1
    except Exception as e:
        print(f"  FAIL: {name}: {e}")
        failed += 1


def simulate_validate_all_dsns(env_overrides):
    """Simulate the validate_all_dsns fixture with custom env vars."""
    offending = []
    for key, value in sorted(env_overrides.items()):
        if not key.startswith("AMPREALIZE_") or not key.endswith("_PG_DSN"):
            continue
        if not value or "mock" in value.lower():
            continue
        try:
            assert_test_database(value)
        except RuntimeError as exc:
            offending.append(f"  {key}: {_mask_dsn_password(value)}")
    return offending


# ==========================================
print("\n=== validate_all_dsns: all test DSNs pass ===")


def test_all_test_dsns():
    env = {
        "AMPREALIZE_WORKFLOW_PG_DSN": "postgresql://wf_test:pass@localhost:6434/workflow_test",  # pragma: allowlist secret
        "AMPREALIZE_RUN_PG_DSN": "postgresql://run_test:pass@localhost:6436/run_test",  # pragma: allowlist secret
        "AMPREALIZE_BOARD_PG_DSN": "postgresql://board_test:pass@localhost:6432/amprealize_test",  # pragma: allowlist secret
        "AMPREALIZE_BEHAVIOR_PG_DSN": "postgresql://beh_test:pass@localhost:6433/behavior_test",  # pragma: allowlist secret
        "AMPREALIZE_ACTION_PG_DSN": "postgresql://act_test:pass@localhost:6435/action_test",  # pragma: allowlist secret
        "AMPREALIZE_COMPLIANCE_PG_DSN": "postgresql://comp_test:pass@localhost:6437/compliance_test",  # pragma: allowlist secret
        "AMPREALIZE_TELEMETRY_PG_DSN": "postgresql://tel_test:pass@localhost:6432/telemetry_test",  # pragma: allowlist secret
        "AMPREALIZE_AUTH_PG_DSN": "postgresql://auth_test:pass@localhost:6440/auth_test",  # pragma: allowlist secret
        "AMPREALIZE_METRICS_PG_DSN": "postgresql://metrics_test:pass@localhost:6439/metrics_test",  # pragma: allowlist secret
        "AMPREALIZE_ORG_PG_DSN": "postgresql://org_test:pass@localhost:6432/amprealize_test",  # pragma: allowlist secret
        "AMPREALIZE_EXECUTION_PG_DSN": "postgresql://exec_test:pass@localhost:6435/execution_test",  # pragma: allowlist secret
        "AMPREALIZE_AGENT_ORCHESTRATOR_PG_DSN": "postgresql://orch_test:pass@localhost:6435/orch_test",  # pragma: allowlist secret
        "AMPREALIZE_AGENT_REGISTRY_PG_DSN": "postgresql://reg_test:pass@localhost:6435/reg_test",  # pragma: allowlist secret
    }
    offending = simulate_validate_all_dsns(env)
    assert len(offending) == 0, f"Expected 0 offending DSNs, got {len(offending)}: {offending}"


check("all test DSNs pass validation", test_all_test_dsns)

# ==========================================
print("\n=== validate_all_dsns: detects production DSN mixed in ===")


def test_one_production_dsn():
    env = {
        "AMPREALIZE_WORKFLOW_PG_DSN": "postgresql://wf_test:pass@localhost:6434/workflow_test",  # pragma: allowlist secret
        "AMPREALIZE_BOARD_PG_DSN": "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize",  # pragma: allowlist secret  # <-- BAD
        "AMPREALIZE_BEHAVIOR_PG_DSN": "postgresql://beh_test:pass@localhost:6433/behavior_test",  # pragma: allowlist secret
    }
    offending = simulate_validate_all_dsns(env)
    assert len(offending) == 1, f"Expected 1 offending DSN, got {len(offending)}: {offending}"
    assert "AMPREALIZE_BOARD_PG_DSN" in offending[0]


check("catches one production DSN mixed in", test_one_production_dsn)


def test_multiple_production_dsns():
    env = {
        "AMPREALIZE_BOARD_PG_DSN": "postgresql://u:p@localhost:5432/amprealize",  # pragma: allowlist secret
        "AMPREALIZE_TELEMETRY_PG_DSN": "postgresql://u:p@localhost:5432/telemetry",  # pragma: allowlist secret
        "AMPREALIZE_BEHAVIOR_PG_DSN": "postgresql://beh_test:pass@localhost:6433/behavior_test",  # pragma: allowlist secret
    }
    offending = simulate_validate_all_dsns(env)
    assert len(offending) == 2, f"Expected 2 offending DSNs, got {len(offending)}"


check("catches multiple production DSNs", test_multiple_production_dsns)


def test_production_host_detected():
    env = {
        "AMPREALIZE_BOARD_PG_DSN": "postgresql://u:p@amprealize-db:5432/board_test",  # pragma: allowlist secret  # production HOST
    }
    offending = simulate_validate_all_dsns(env)
    assert len(offending) == 1, f"Expected 1 offending DSN for production host"


check("catches production hostname", test_production_host_detected)

# ==========================================
print("\n=== validate_all_dsns: ignores non-DSN env vars ===")


def test_ignores_non_dsn():
    env = {
        "AMPREALIZE_API_PORT": "8000",
        "SOME_OTHER_VAR": "postgresql://u:p@localhost:5432/amprealize",  # pragma: allowlist secret
        "AMPREALIZE_BOARD_PG_DSN": "postgresql://u:p@localhost:6432/amprealize_test",  # pragma: allowlist secret
    }
    offending = simulate_validate_all_dsns(env)
    assert len(offending) == 0


check("ignores non-AMPREALIZE_*_PG_DSN vars", test_ignores_non_dsn)


def test_ignores_empty_dsn():
    env = {
        "AMPREALIZE_BOARD_PG_DSN": "",
    }
    offending = simulate_validate_all_dsns(env)
    assert len(offending) == 0


check("ignores empty DSN values", test_ignores_empty_dsn)


def test_ignores_mock_dsn():
    env = {
        "AMPREALIZE_BOARD_PG_DSN": "postgresql://mock:mock@mock:5432/amprealize",  # pragma: allowlist secret
    }
    offending = simulate_validate_all_dsns(env)
    assert len(offending) == 0


check("ignores mock DSNs", test_ignores_mock_dsn)

# ==========================================
print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
