#!/usr/bin/env python3
"""Standalone test for safety guard functions — no pytest session fixtures needed."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.conftest import (
    assert_test_database,
    _PRODUCTION_DB_NAMES,
    _PRODUCTION_HOSTNAMES,
    _mask_dsn_password,
)

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


def expect_blocked(dsn, label=""):
    """Helper: assert that assert_test_database raises RuntimeError."""
    try:
        assert_test_database(dsn)
        raise AssertionError(f"Should have blocked DSN: {dsn}")
    except RuntimeError as e:
        if "SAFETY GUARD" not in str(e):
            raise


def expect_allowed(dsn, label=""):
    """Helper: assert that assert_test_database does NOT raise."""
    assert_test_database(dsn)


# ==========================================
print("\n=== Block production database names ===")
check("blocks amprealize", lambda: expect_blocked("postgresql://user:pass@localhost:5432/amprealize"))  # pragma: allowlist secret
check("blocks telemetry", lambda: expect_blocked("postgresql://user:pass@localhost:5432/telemetry"))  # pragma: allowlist secret
check("blocks amprealize with query params", lambda: expect_blocked(
    "postgresql://u:p@localhost:5432/amprealize?options=-csearch_path%3Dpublic"  # pragma: allowlist secret
))

# ==========================================
print("\n=== Block production hostnames ===")
check("blocks amprealize-db host", lambda: expect_blocked("postgresql://user:pass@amprealize-db:5432/any_db"))  # pragma: allowlist secret

# ==========================================
print("\n=== Allow test database names ===")
check("allows amprealize_test", lambda: expect_allowed("postgresql://user:pass@localhost:6432/amprealize_test"))  # pragma: allowlist secret
check("allows behavior_test", lambda: expect_allowed("postgresql://user:pass@localhost:6433/behavior_test"))  # pragma: allowlist secret
check("allows workflow_test", lambda: expect_allowed("postgresql://user:pass@localhost:6434/workflow_test"))  # pragma: allowlist secret
check("allows telemetry_test", lambda: expect_allowed("postgresql://user:pass@localhost:6432/telemetry_test"))  # pragma: allowlist secret
check("allows test DB with query params", lambda: expect_allowed(
    "postgresql://u:p@localhost:6432/amprealize_test?options=-csearch_path%3Dpublic"  # pragma: allowlist secret
))
check("allows mock DSN", lambda: expect_allowed("postgresql://mock:mock@mock-host:5432/amprealize"))  # pragma: allowlist secret

# ==========================================
print("\n=== Safety override env var ===")


def test_override_allows():
    os.environ["AMPREALIZE_TEST_SAFETY_OVERRIDE"] = "1"
    try:
        expect_allowed("postgresql://user:pass@localhost:5432/amprealize")  # pragma: allowlist secret
    finally:
        del os.environ["AMPREALIZE_TEST_SAFETY_OVERRIDE"]


def test_override_zero_still_blocks():
    os.environ["AMPREALIZE_TEST_SAFETY_OVERRIDE"] = "0"
    try:
        expect_blocked("postgresql://user:pass@localhost:5432/amprealize")  # pragma: allowlist secret
    finally:
        del os.environ["AMPREALIZE_TEST_SAFETY_OVERRIDE"]


check("override=1 bypasses guard", test_override_allows)
check("override=0 still blocks", test_override_zero_still_blocks)

# ==========================================
print("\n=== Blocklist contents ===")
check("amprealize in DB blocklist", lambda: None if "amprealize" in _PRODUCTION_DB_NAMES else (_ for _ in ()).throw(AssertionError("missing")))
check("telemetry in DB blocklist", lambda: None if "telemetry" in _PRODUCTION_DB_NAMES else (_ for _ in ()).throw(AssertionError("missing")))
check("amprealize_test NOT in blocklist", lambda: None if "amprealize_test" not in _PRODUCTION_DB_NAMES else (_ for _ in ()).throw(AssertionError("should not be")))
check("amprealize-db in host blocklist", lambda: None if "amprealize-db" in _PRODUCTION_HOSTNAMES else (_ for _ in ()).throw(AssertionError("missing")))
check("localhost NOT in host blocklist", lambda: None if "localhost" not in _PRODUCTION_HOSTNAMES else (_ for _ in ()).throw(AssertionError("should not be")))

# ==========================================
print("\n=== Password masking ===")


def test_mask():
    masked = _mask_dsn_password("postgresql://myuser:secret123@localhost:5432/mydb")  # pragma: allowlist secret
    assert "secret123" not in masked, f"Password not masked: {masked}"
    assert "***" in masked, f"Mask marker missing: {masked}"
    assert "myuser" in masked, f"Username lost: {masked}"


check("masks password in DSN", test_mask)

# ==========================================
print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
