"""Tests for ZombieReaper functionality."""

import asyncio
import sys
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add amprealize to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "amprealize"))

from amprealize.zombie_reaper import ZombieReaper, ZombieReaperConfig, ReaperStats


class TestZombieReaperConfig:
    """Tests for ZombieReaperConfig."""

    def test_default_config(self):
        """Default config has sensible values."""
        config = ZombieReaperConfig()

        assert config.check_interval_seconds == 60
        assert config.max_idle_seconds == 120
        assert config.enabled is True

    def test_custom_config(self):
        """Custom config values are preserved."""
        config = ZombieReaperConfig(
            check_interval_seconds=30,
            max_idle_seconds=90,
            enabled=False,
        )

        assert config.check_interval_seconds == 30
        assert config.max_idle_seconds == 90
        assert config.enabled is False


class TestReaperStats:
    """Tests for ReaperStats."""

    def test_initial_stats(self):
        """Stats start at zero."""
        stats = ReaperStats()

        assert stats.runs_completed == 0
        assert stats.zombies_reaped == 0
        assert stats.last_run_at is None
        assert stats.last_zombies_found == 0
        assert stats.errors == 0


class TestZombieReaper:
    """Tests for ZombieReaper."""

    @pytest.fixture
    def mock_orchestrator(self):
        """Create a mock orchestrator."""
        orchestrator = AsyncMock()
        orchestrator.cleanup_zombies = AsyncMock(return_value=[])
        return orchestrator

    def test_init(self, mock_orchestrator):
        """Reaper initializes with default config."""
        reaper = ZombieReaper(mock_orchestrator)

        assert reaper._config.check_interval_seconds == 60
        assert reaper._config.max_idle_seconds == 120
        assert reaper._running is False

    def test_init_custom_config(self, mock_orchestrator):
        """Reaper accepts custom config."""
        config = ZombieReaperConfig(check_interval_seconds=30)
        reaper = ZombieReaper(mock_orchestrator, config=config)

        assert reaper._config.check_interval_seconds == 30

    @pytest.mark.asyncio
    async def test_run_once_no_zombies(self, mock_orchestrator):
        """run_once returns empty list when no zombies."""
        mock_orchestrator.cleanup_zombies = AsyncMock(return_value=[])
        reaper = ZombieReaper(mock_orchestrator)

        result = await reaper.run_once()

        assert result == []
        mock_orchestrator.cleanup_zombies.assert_called_once_with(max_idle_seconds=120)

    @pytest.mark.asyncio
    async def test_run_once_with_zombies(self, mock_orchestrator):
        """run_once returns zombie run_ids."""
        mock_orchestrator.cleanup_zombies = AsyncMock(
            return_value=["run-1", "run-2"]
        )
        reaper = ZombieReaper(mock_orchestrator)

        result = await reaper.run_once()

        assert result == ["run-1", "run-2"]

    @pytest.mark.asyncio
    async def test_run_once_disabled(self, mock_orchestrator):
        """run_once returns empty when disabled."""
        config = ZombieReaperConfig(enabled=False)
        reaper = ZombieReaper(mock_orchestrator, config=config)

        result = await reaper.run_once()

        assert result == []
        mock_orchestrator.cleanup_zombies.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_and_reap_updates_stats(self, mock_orchestrator):
        """_check_and_reap updates stats."""
        mock_orchestrator.cleanup_zombies = AsyncMock(
            return_value=["run-1", "run-2"]
        )
        reaper = ZombieReaper(mock_orchestrator)

        await reaper._check_and_reap()

        assert reaper.stats.runs_completed == 1
        assert reaper.stats.zombies_reaped == 2
        assert reaper.stats.last_zombies_found == 2
        assert reaper.stats.last_run_at is not None

    @pytest.mark.asyncio
    async def test_check_and_reap_accumulates_zombies(self, mock_orchestrator):
        """Multiple reaps accumulate zombie count."""
        mock_orchestrator.cleanup_zombies = AsyncMock(
            return_value=["run-1"]
        )
        reaper = ZombieReaper(mock_orchestrator)

        await reaper._check_and_reap()
        await reaper._check_and_reap()
        await reaper._check_and_reap()

        assert reaper.stats.runs_completed == 3
        assert reaper.stats.zombies_reaped == 3

    def test_stop(self, mock_orchestrator):
        """stop sets _running to False."""
        reaper = ZombieReaper(mock_orchestrator)
        reaper._running = True

        reaper.stop()

        assert reaper._running is False

    @pytest.mark.asyncio
    async def test_run_loop_can_be_stopped(self, mock_orchestrator):
        """run loop exits when stop is called."""
        config = ZombieReaperConfig(check_interval_seconds=1)
        reaper = ZombieReaper(mock_orchestrator, config=config)

        # Start the run loop
        task = asyncio.create_task(reaper.run())

        # Wait a bit then stop
        await asyncio.sleep(0.1)
        reaper.stop()

        # Should complete quickly
        await asyncio.wait_for(task, timeout=2.0)

        assert reaper._running is False

    @pytest.mark.asyncio
    async def test_context_manager(self, mock_orchestrator):
        """Context manager starts and stops reaper."""
        config = ZombieReaperConfig(check_interval_seconds=60)

        async with ZombieReaper(mock_orchestrator, config=config) as reaper:
            # Wait a tiny bit for the task to start
            await asyncio.sleep(0.05)
            assert reaper._running is True
            assert reaper._task is not None

        assert reaper._running is False


class TestZombieReaperMetrics:
    """Tests for ZombieReaper Prometheus metrics integration."""

    @pytest.fixture
    def mock_orchestrator(self):
        orchestrator = AsyncMock()
        orchestrator.cleanup_zombies = AsyncMock(return_value=[])
        return orchestrator

    @pytest.mark.asyncio
    async def test_reaper_run_records_metric(self, mock_orchestrator):
        """Reaper records run metric."""
        with patch("amprealize.zombie_reaper.record_reaper_run") as mock_metric:
            reaper = ZombieReaper(mock_orchestrator)
            await reaper._check_and_reap()

            mock_metric.assert_called_once()

    @pytest.mark.asyncio
    async def test_zombies_reaped_records_metric(self, mock_orchestrator):
        """Reaper records zombies reaped metric."""
        mock_orchestrator.cleanup_zombies = AsyncMock(
            return_value=["run-1", "run-2"]
        )

        with patch("amprealize.zombie_reaper.record_zombies_reaped") as mock_metric:
            reaper = ZombieReaper(mock_orchestrator)
            await reaper._check_and_reap()

            mock_metric.assert_called_once_with(2)

    @pytest.mark.asyncio
    async def test_error_records_metric(self, mock_orchestrator):
        """Reaper records error metric on failure."""
        mock_orchestrator.cleanup_zombies = AsyncMock(
            side_effect=Exception("Connection failed")
        )

        with patch("amprealize.zombie_reaper.record_reaper_error") as mock_metric:
            config = ZombieReaperConfig(check_interval_seconds=60)
            reaper = ZombieReaper(mock_orchestrator, config=config)

            # Start and let it run one iteration with error
            task = asyncio.create_task(reaper.run())
            await asyncio.sleep(0.1)
            reaper.stop()
            await asyncio.wait_for(task, timeout=2.0)

            mock_metric.assert_called()
