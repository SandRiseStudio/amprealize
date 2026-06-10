"""Unit tests for PostgresPool schema support.

Tests the schema parameter without requiring a database connection.
"""

import pytest
from unittest.mock import MagicMock, patch


class TestPostgresPoolSchema:
    """Test schema-related functionality of PostgresPool."""

    @patch("amprealize.storage.postgres_pool._get_engine")
    @patch("amprealize.storage.postgres_pool.postgres_metrics")
    def test_init_with_schema(self, mock_metrics, mock_get_engine):
        """Test that PostgresPool accepts schema parameter."""
        from amprealize.storage.postgres_pool import PostgresPool

        mock_get_engine.return_value = MagicMock()
        mock_metrics.PROMETHEUS_AVAILABLE = False

        pool = PostgresPool(dsn="postgresql://test", schema="auth")

        assert pool._schema == "auth"
        mock_get_engine.assert_called_once_with("postgresql://test")

    @patch("amprealize.storage.postgres_pool._get_engine")
    @patch("amprealize.storage.postgres_pool.postgres_metrics")
    def test_init_without_schema(self, mock_metrics, mock_get_engine):
        """Test that PostgresPool works without schema (backwards compatible)."""
        from amprealize.storage.postgres_pool import PostgresPool

        mock_get_engine.return_value = MagicMock()
        mock_metrics.PROMETHEUS_AVAILABLE = False

        pool = PostgresPool(dsn="postgresql://test")

        assert pool._schema is None
        mock_get_engine.assert_called_once_with("postgresql://test")

    @patch("amprealize.storage.postgres_pool._get_engine")
    @patch("amprealize.storage.postgres_pool.postgres_metrics")
    def test_schema_with_custom_service_name(self, mock_metrics, mock_get_engine):
        """Test PostgresPool with schema and custom service_name."""
        from amprealize.storage.postgres_pool import PostgresPool

        mock_get_engine.return_value = MagicMock()
        mock_metrics.PROMETHEUS_AVAILABLE = False

        pool = PostgresPool(
            dsn="postgresql://test",
            schema="behavior",
            service_name="behavior_service",
        )

        assert pool._schema == "behavior"
        assert pool._service_name == "behavior_service"

    @patch("amprealize.storage.postgres_pool._get_engine")
    @patch("amprealize.storage.postgres_pool.postgres_metrics")
    def test_get_pool_stats_returns_service_info(self, mock_metrics, mock_get_engine):
        """Test that get_pool_stats() returns pool statistics."""
        from amprealize.storage.postgres_pool import PostgresPool

        mock_engine = MagicMock()
        mock_pool = MagicMock()
        mock_pool.checkedout.return_value = 0
        mock_pool.size.return_value = 10
        mock_pool.overflow.return_value = 0
        mock_engine.pool = mock_pool
        mock_get_engine.return_value = mock_engine
        mock_metrics.PROMETHEUS_AVAILABLE = False

        pool = PostgresPool(dsn="postgresql://test", schema="execution")
        stats = pool.get_pool_stats()

        assert stats["service"] == "postgres"
        assert stats["pool_size"] == 10

    def test_get_engine_cache_key(self):
        """Test that _get_engine uses cache for isolation."""
        from amprealize.storage.postgres_pool import _POOL_CACHE, _CACHE_LOCK

        # Verify the cache exists and is a dict
        with _CACHE_LOCK:
            assert isinstance(_POOL_CACHE, dict)


class TestSchemaSearchPath:
    """Test schema search_path event listener setup."""

    def test_search_path_set_on_connect(self):
        """Integration-style test that would verify search_path.

        Note: This test is marked for integration suite as it requires
        actual database connection. See tests/integration/ for full test.
        """
        pytest.skip("Requires database connection - run in integration suite")


class TestStripDsnOptions:
    """Pooler compatibility: the libpq ``options`` startup parameter (used to
    carry ``search_path``) must be stripped before connecting, because Neon's
    pgBouncer rejects it with "unsupported startup parameter". search_path is
    instead applied post-connect via the SQLAlchemy "connect" event.
    """

    def test_strips_options_preserves_other_params(self):
        from amprealize.storage.postgres_pool import _strip_dsn_options

        dsn = "postgresql://u:p@host/db?sslmode=require&options=-csearch_path%3Dbehavior"
        out = _strip_dsn_options(dsn)
        assert "options=" not in out
        assert "sslmode=require" in out

    def test_strips_sole_options_param(self):
        from amprealize.storage.postgres_pool import _strip_dsn_options

        out = _strip_dsn_options("postgresql://u:p@host/db?options=-csearch_path%3Dbehavior")
        assert "?" not in out
        assert out == "postgresql://u:p@host/db"

    def test_noop_when_no_options(self):
        from amprealize.storage.postgres_pool import _strip_dsn_options

        for dsn in (
            "postgresql://u:p@host/db",
            "postgresql://u:p@host/db?sslmode=require",
        ):
            assert _strip_dsn_options(dsn) == dsn

    def test_search_path_still_extractable_after_strip(self):
        """The stripped DSN drops options, but search_path is read from the
        original DSN and applied via the connect event, so it is not lost."""
        from amprealize.storage.postgres_pool import _dsn_search_path

        dsn = "postgresql://u:p@host/db?options=-csearch_path%3Dbehavior"
        assert _dsn_search_path(dsn) == "behavior"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
