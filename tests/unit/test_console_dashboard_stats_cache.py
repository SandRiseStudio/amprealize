"""Unit tests for guideai-1153: Redis read-through + invalidation for dashboard stats."""

import json
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


def test_invalidate_console_dashboard_stats_deletes_pattern() -> None:
    from amprealize.storage.redis_cache import invalidate_console_dashboard_stats_cache

    mock_cache = MagicMock()
    mock_cache.delete.return_value = 3

    with patch("amprealize.storage.redis_cache.get_cache", return_value=mock_cache):
        n = invalidate_console_dashboard_stats_cache()

    assert n == 3
    mock_cache.delete.assert_called_once_with("console:dashboard_stats:*")


def test_invalidate_console_dashboard_stats_swallows_redis_errors() -> None:
    from amprealize.storage.redis_cache import invalidate_console_dashboard_stats_cache

    with patch("amprealize.storage.redis_cache.get_cache", side_effect=RuntimeError("no redis")):
        assert invalidate_console_dashboard_stats_cache() == 0


def test_get_ttl_console_dashboard_stats_matches_settings() -> None:
    from amprealize.config.settings import settings
    from amprealize.storage.redis_cache import get_ttl

    assert get_ttl("console", "dashboard_stats") == settings.cache_ttl.dashboard_stats_ttl


def test_dashboard_stats_cache_key_includes_version_and_day_bucket() -> None:
    """Key must vary by UTC date so completed_runs_today rolls over at midnight UTC."""
    with patch("amprealize.storage.redis_cache.redis.Redis"):
        with patch("amprealize.storage.redis_cache.ConnectionPool"):
            from amprealize.storage.redis_cache import RedisCache

            cache = RedisCache(host="localhost", port=6379)
            day = "2026-04-28"
            key = cache._make_key("console", "dashboard_stats", {"v": 1, "day": day})
            params_hash = hashlib_hex_digest({"v": 1, "day": day})
            assert key == f"console:dashboard_stats:{params_hash}"


def hashlib_hex_digest(params: dict) -> str:
    import hashlib

    params_str = json.dumps(params, sort_keys=True)
    return hashlib.md5(params_str.encode()).hexdigest()[:8]


def test_dashboard_stats_params_hash_differs_by_day() -> None:
    a = hashlib_hex_digest({"v": 1, "day": "2026-04-28"})
    b = hashlib_hex_digest({"v": 1, "day": "2026-04-29"})
    assert a != b
