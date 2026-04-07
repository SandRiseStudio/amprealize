"""Tests for the production database safety guards in conftest.py.

These tests verify the core safety functions do NOT require a running database.
They validate the logic of assert_test_database() and the DSN validation.
"""

import os
import pytest
from unittest.mock import patch

pytestmark = pytest.mark.unit

# Import the safety functions directly from conftest
from tests.conftest import (
    assert_test_database,
    _PRODUCTION_DB_NAMES,
    _PRODUCTION_HOSTNAMES,
    _mask_dsn_password,
)


class TestAssertTestDatabase:
    """Verify assert_test_database blocks production DSNs."""

    def test_blocks_production_db_name_amprealize(self):
        dsn = "postgresql://user:pass@localhost:5432/amprealize"  # pragma: allowlist secret
        with pytest.raises(RuntimeError, match="SAFETY GUARD.*production database"):
            assert_test_database(dsn)

    def test_blocks_production_db_name_telemetry(self):
        dsn = "postgresql://user:pass@localhost:5432/telemetry"  # pragma: allowlist secret
        with pytest.raises(RuntimeError, match="SAFETY GUARD.*production database"):
            assert_test_database(dsn)

    def test_blocks_production_hostname(self):
        dsn = "postgresql://user:pass@amprealize-db:5432/some_test_db"  # pragma: allowlist secret
        with pytest.raises(RuntimeError, match="SAFETY GUARD.*production database host"):
            assert_test_database(dsn)

    def test_allows_test_db_name(self):
        dsn = "postgresql://user:pass@localhost:6432/amprealize_test"  # pragma: allowlist secret
        # Should NOT raise
        assert_test_database(dsn)

    def test_allows_test_suffixed_db(self):
        dsn = "postgresql://user:pass@localhost:6433/behavior_test"  # pragma: allowlist secret
        assert_test_database(dsn)

    def test_allows_mock_dsn(self):
        dsn = "postgresql://mock:mock@mock-host:5432/amprealize"  # pragma: allowlist secret
        # "mock" in dsn.lower() triggers early return
        assert_test_database(dsn)

    def test_safety_override_env_var(self):
        dsn = "postgresql://user:pass@localhost:5432/amprealize"  # pragma: allowlist secret
        with patch.dict(os.environ, {"AMPREALIZE_TEST_SAFETY_OVERRIDE": "1"}):
            # Should NOT raise when override is set
            assert_test_database(dsn)

    def test_safety_override_must_be_explicit(self):
        dsn = "postgresql://user:pass@localhost:5432/amprealize"  # pragma: allowlist secret
        with patch.dict(os.environ, {"AMPREALIZE_TEST_SAFETY_OVERRIDE": "0"}):
            with pytest.raises(RuntimeError, match="SAFETY GUARD"):
                assert_test_database(dsn)

    def test_blocks_production_db_with_query_params(self):
        dsn = "postgresql://user:pass@localhost:5432/amprealize?options=-csearch_path%3Dpublic"  # pragma: allowlist secret
        with pytest.raises(RuntimeError, match="SAFETY GUARD"):
            assert_test_database(dsn)

    def test_allows_test_db_with_query_params(self):
        dsn = "postgresql://user:pass@localhost:6432/amprealize_test?options=-csearch_path%3Dpublic"  # pragma: allowlist secret
        assert_test_database(dsn)


class TestProductionDbNames:
    """Verify the production database name blocklist is correct."""

    def test_amprealize_in_blocklist(self):
        assert "amprealize" in _PRODUCTION_DB_NAMES

    def test_telemetry_in_blocklist(self):
        assert "telemetry" in _PRODUCTION_DB_NAMES

    def test_test_suffixed_not_in_blocklist(self):
        assert "amprealize_test" not in _PRODUCTION_DB_NAMES
        assert "telemetry_test" not in _PRODUCTION_DB_NAMES


class TestProductionHostnames:
    """Verify the production hostname blocklist."""

    def test_amprealize_db_blocked(self):
        assert "amprealize-db" in _PRODUCTION_HOSTNAMES

    def test_localhost_allowed(self):
        assert "localhost" not in _PRODUCTION_HOSTNAMES


class TestMaskDsnPassword:
    """Verify password masking in DSNs for safe logging."""

    def test_masks_password(self):
        dsn = "postgresql://myuser:secret123@localhost:5432/mydb"  # pragma: allowlist secret
        masked = _mask_dsn_password(dsn)
        assert "secret123" not in masked
        assert "***" in masked
        assert "myuser" in masked

    def test_handles_no_password(self):
        dsn = "postgresql://myuser@localhost:5432/mydb"  # pragma: allowlist secret
        masked = _mask_dsn_password(dsn)
        assert masked == dsn  # No change if no password pattern
