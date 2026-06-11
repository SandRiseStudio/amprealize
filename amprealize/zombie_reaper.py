"""Zombie workspace reaper for cleaning up stale executions.

This module provides the ZombieReaper class that runs as a background task
to detect and terminate workspaces that have gone silent (no heartbeat).

A workspace becomes a "zombie" when:
1. Its heartbeat hasn't been updated for max_idle_seconds
2. The worker that was processing it has died
3. The execution was cancelled but cleanup failed

The reaper:
- Runs periodically (configurable interval)
- Detects zombies via the orchestrator
- Terminates zombie containers
- Logs cleanup actions for auditing
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

# Metrics
from amprealize.execution_metrics import (
    record_zombies_reaped,
    record_reaper_run,
    record_reaper_error,
)

if TYPE_CHECKING:
    from breakeramp import AmpOrchestrator

logger = logging.getLogger(__name__)


@dataclass
class ZombieReaperConfig:
    """Configuration for the zombie reaper."""

    # How often to check for zombies (seconds)
    check_interval_seconds: int = 60

    # How long before a workspace is considered a zombie (seconds)
    # Should be > 2x heartbeat interval
    max_idle_seconds: int = 120

    # Whether to actually terminate zombies (False = dry run)
    enabled: bool = True


@dataclass
class ReaperStats:
    """Statistics for zombie reaper runs."""

    runs_completed: int = 0
    zombies_reaped: int = 0
    last_run_at: Optional[datetime] = None
    last_zombies_found: int = 0
    errors: int = 0


class ZombieReaper:
    """Background task that cleans up zombie workspaces.

    Zombies are workspaces whose workers have died or stopped sending
    heartbeats. This prevents resource leaks and stuck executions.

    Example:
        orchestrator = get_orchestrator()
        reaper = ZombieReaper(orchestrator)

        # Start as background task
        reaper_task = asyncio.create_task(reaper.run())

        # Later: stop gracefully
        reaper.stop()
        await reaper_task

    Or with context manager:
        async with ZombieReaper(orchestrator) as reaper:
            # Reaper runs in background
            await some_other_work()
    """

    def __init__(
        self,
        orchestrator: AmpOrchestrator,
        config: Optional[ZombieReaperConfig] = None,
    ):
        """Initialize the zombie reaper.

        Args:
            orchestrator: AmpOrchestrator for workspace management
            config: Reaper configuration
        """
        self._orchestrator = orchestrator
        self._config = config or ZombieReaperConfig()
        self._running = False
        self._stats = ReaperStats()
        self._task: Optional[asyncio.Task] = None

    @property
    def stats(self) -> ReaperStats:
        """Get current reaper statistics."""
        return self._stats

    async def run(self) -> None:
        """Run the reaper loop.

        Periodically checks for and terminates zombie workspaces.
        Runs until stop() is called.
        """
        self._running = True
        logger.info(
            "ZombieReaper started",
            extra={
                "check_interval": self._config.check_interval_seconds,
                "max_idle": self._config.max_idle_seconds,
                "enabled": self._config.enabled,
            },
        )

        while self._running:
            try:
                await self._check_and_reap()
            except asyncio.CancelledError:
                logger.info("ZombieReaper cancelled")
                break
            except Exception as e:
                logger.exception(f"ZombieReaper error: {e}")
                self._stats.errors += 1
                record_reaper_error()

            # Wait for next check interval
            try:
                await asyncio.sleep(self._config.check_interval_seconds)
            except asyncio.CancelledError:
                break

        logger.info(
            "ZombieReaper stopped",
            extra={
                "total_runs": self._stats.runs_completed,
                "total_reaped": self._stats.zombies_reaped,
                "total_errors": self._stats.errors,
            },
        )

    async def _check_and_reap(self) -> None:
        """Check for zombies and terminate them."""
        self._stats.runs_completed += 1
        self._stats.last_run_at = datetime.now(timezone.utc)
        record_reaper_run()

        if not self._config.enabled:
            logger.debug("ZombieReaper dry run (enabled=False)")
            return

        # Call orchestrator to find and cleanup zombies
        zombies = await self._orchestrator.cleanup_zombies(
            max_idle_seconds=self._config.max_idle_seconds
        )

        self._stats.last_zombies_found = len(zombies)

        if zombies:
            self._stats.zombies_reaped += len(zombies)
            record_zombies_reaped(len(zombies))
            logger.warning(
                f"Reaped {len(zombies)} zombie workspace(s)",
                extra={
                    "zombie_run_ids": zombies,
                    "max_idle_seconds": self._config.max_idle_seconds,
                },
            )
        else:
            logger.debug("No zombie workspaces found")

    def stop(self) -> None:
        """Signal the reaper to stop after current check."""
        self._running = False

    async def run_once(self) -> List[str]:
        """Run a single zombie check (for testing or manual cleanup).

        Returns:
            List of run_ids that were reaped
        """
        if not self._config.enabled:
            return []

        zombies = await self._orchestrator.cleanup_zombies(
            max_idle_seconds=self._config.max_idle_seconds
        )

        if zombies:
            logger.info(f"Manual reap: cleaned up {len(zombies)} zombies")

        return zombies

    # Context manager support
    async def __aenter__(self) -> "ZombieReaper":
        """Start reaper as background task."""
        self._task = asyncio.create_task(self.run())
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Stop reaper and wait for completion."""
        self.stop()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
