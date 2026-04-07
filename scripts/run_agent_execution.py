#!/usr/bin/env python
"""Run an agent execution synchronously (blocking until completion).

This is useful for CLI/testing where you want to wait for the full execution
to complete rather than returning immediately.

Usage:
    python scripts/run_agent_execution.py <work_item_id> [user_id]
"""

import asyncio
import os
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger("run_agent_execution")


async def main():
    """Run agent execution synchronously."""
    # Set environment for direct execution mode
    os.environ.setdefault("EXECUTION_MODE", "direct")
    os.environ.setdefault(
        "AMPREALIZE_EXECUTION_PG_DSN",
        "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize?options=-csearch_path%3Dexecution"
    )
    os.environ.setdefault(
        "BYOK_ENCRYPTION_KEY",
        "F8mx5M0oI4byBM353Yu5dtcz8d4AxlEKl1cBf2FW0Y4="
    )

    # Lazy imports after environment setup
    from amprealize.work_item_execution_service import WorkItemExecutionService
    from amprealize.work_item_execution_contracts import ExecuteWorkItemRequest

    work_item_id = sys.argv[1] if len(sys.argv) > 1 else "f6dddc21-df54-404c-b134-f039282b6363"
    user_id = sys.argv[2] if len(sys.argv) > 2 else "112316240869466547718"  # Nick Sanders

    logger.info(f"EXECUTION_MODE: {os.environ.get('EXECUTION_MODE')}")
    logger.info(f"ANTHROPIC_API_KEY: {'set' if os.environ.get('ANTHROPIC_API_KEY') else 'NOT SET'}")
    logger.info(f"Work Item ID: {work_item_id}")
    logger.info(f"User ID: {user_id}")

    service = WorkItemExecutionService()

    # First check if there's an existing execution
    status = service.get_status(work_item_id)
    if status and status.status.value in ("PENDING", "RUNNING"):
        logger.warning(f"Existing execution in progress: {status.run_id} ({status.status.value})")
        logger.warning("Cancelling existing execution...")
        service.cancel(work_item_id=work_item_id, user_id=user_id, reason="Restarting execution")
        await asyncio.sleep(1)  # Let cancellation propagate

    # Create request
    request = ExecuteWorkItemRequest(
        work_item_id=work_item_id,
        user_id=user_id,
        actor_surface="cli",
    )

    logger.info("Starting execution...")

    # Execute - this returns immediately but schedules background task
    response = await service.execute(request)
    logger.info(f"Run ID: {response.run_id}")
    logger.info(f"Cycle ID: {response.cycle_id}")
    logger.info(f"Status: {response.status}")
    logger.info(f"Phase: {response.phase}")

    # Now we need to find the background task and await it
    # The task was created with asyncio.create_task in execute()
    # Since we're in the same event loop, we can find pending tasks

    # Get all pending tasks and look for _run_execution_loop
    pending_tasks = asyncio.all_tasks()
    execution_task = None

    for task in pending_tasks:
        coro = task.get_coro()
        if coro and hasattr(coro, "__qualname__"):
            if "_run_execution_loop" in coro.__qualname__:
                execution_task = task
                break

    if execution_task:
        logger.info("Found execution task, waiting for completion...")
        logger.info("-" * 60)
        try:
            await execution_task
            logger.info("-" * 60)
            logger.info("Execution completed successfully!")
        except Exception as e:
            logger.error(f"Execution failed: {e}")
            raise
    else:
        logger.warning("No execution task found - execution may have failed to start")

    # Get final status
    final_status = service.get_status(work_item_id)
    logger.info(f"Final Status: {final_status.status.value}")
    logger.info(f"Final Phase: {final_status.phase}")


if __name__ == "__main__":
    asyncio.run(main())
