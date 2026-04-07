#!/usr/bin/env python
"""Run the AI Research Agent on a specific work item in direct mode.

This script starts execution and polls for completion, showing real-time status updates.
"""

import asyncio
import os
import sys
import time


async def main():
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

    from amprealize.work_item_execution_service import WorkItemExecutionService
    from amprealize.work_item_execution_contracts import ExecuteWorkItemRequest

    work_item_id = sys.argv[1] if len(sys.argv) > 1 else "f6dddc21-df54-404c-b134-f039282b6363"
    user_id = sys.argv[2] if len(sys.argv) > 2 else "112316240869466547718"  # Nick Sanders

    print(f"EXECUTION_MODE: {os.environ.get('EXECUTION_MODE')}")
    print(f"ANTHROPIC_API_KEY: {'set' if os.environ.get('ANTHROPIC_API_KEY') else 'NOT SET'}")
    print(f"Work Item ID: {work_item_id}")
    print(f"User ID: {user_id}")
    print()

    service = WorkItemExecutionService()

    request = ExecuteWorkItemRequest(
        work_item_id=work_item_id,
        user_id=user_id,
        actor_surface="cli",
    )

    print("Starting execution...")
    response = await service.execute(request)
    print(f"Run ID: {response.run_id}")
    print(f"Cycle ID: {response.cycle_id}")
    print(f"Status: {response.status}")
    print(f"Phase: {response.phase}")
    print(f"Message: {response.message}")
    print()

    # In direct mode, the execution runs as a background task in the same process
    # We need to poll for completion
    print("Monitoring execution progress...")
    print("-" * 60)

    last_phase = response.phase
    poll_interval = 5  # seconds

    while True:
        await asyncio.sleep(poll_interval)

        status = service.get_status(work_item_id)
        current_phase = status.phase

        # Print update if phase changed
        if current_phase != last_phase:
            print(f"[{time.strftime('%H:%M:%S')}] Phase: {last_phase} -> {current_phase}")
            last_phase = current_phase

        # Check terminal states
        if status.status.value in ("COMPLETED", "FAILED", "CANCELLED"):
            print()
            print("=" * 60)
            print(f"EXECUTION {status.status.value}")
            print(f"Final Phase: {status.phase}")
            if hasattr(status, 'error') and status.error:
                print(f"Error: {status.error}")
            print("=" * 60)
            break

        # Print periodic status
        print(f"[{time.strftime('%H:%M:%S')}] Status: {status.status.value}, Phase: {status.phase}")


if __name__ == "__main__":
    asyncio.run(main())
