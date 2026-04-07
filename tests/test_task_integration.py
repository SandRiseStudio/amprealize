#!/usr/bin/env python3
"""Quick integration test for TaskService and MCP handler."""

import asyncio
import json
import sys
from datetime import datetime, timezone

# Test TaskService directly
print("=" * 60)
print("Testing TaskService...")
print("=" * 60)

try:
    from amprealize.services.task_service import TaskService, CreateTaskRequest, ListTasksRequest

    # Use default postgres URL
    dsn = "postgresql://amprealize_telemetry:dev_telemetry_pass@localhost:5432/telemetry"
    print(f"Connecting to: {dsn}")

    task_service = TaskService(dsn=dsn)
    print("✅ TaskService initialized")

    # Create a test task
    request = CreateTaskRequest(
        agent_id="test-agent-01",
        task_type="code_review",
        priority=2,
        title="Test MCP Integration",
        description="Verify TaskService works with MCP",
    )

    task = task_service.create_task(request)
    print(f"✅ Created task: {task.task_id}")
    print(f"   - Status: {task.status}")
    print(f"   - Priority: {task.priority}")

    # List tasks
    tasks = task_service.list_tasks(ListTasksRequest(
        agent_id="test-agent-01",
        limit=5
    ))
    print(f"✅ Listed {len(tasks)} tasks for test-agent-01")

    # Get stats
    stats = task_service.get_task_stats(agent_id="test-agent-01")
    print(f"✅ Task stats:")
    print(f"   - Total: {stats.total}")
    print(f"   - Pending: {stats.pending}")
    print(f"   - Completed: {stats.completed}")

    # Cleanup
    print("\nCleaning up test data...")
    from amprealize.storage.postgres_pool import PostgresPool
    pool = PostgresPool(dsn=dsn)
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tasks WHERE agent_id LIKE 'test-%'")
            deleted = cur.rowcount
            conn.commit()
            print(f"✅ Deleted {deleted} test tasks")

except Exception as e:
    print(f"❌ TaskService test failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test MCP handler
print("\n" + "=" * 60)
print("Testing MCPTaskHandler...")
print("=" * 60)

async def test_handler():
    try:
        from amprealize.mcp_task_handler import MCPTaskHandler
        from amprealize.services.task_service import TaskService

        # Use correct DSN
        dsn = "postgresql://amprealize_telemetry:dev_telemetry_pass@localhost:5432/telemetry"
        task_service = TaskService(dsn=dsn)

        handler = MCPTaskHandler(task_service=task_service)
        print("✅ MCPTaskHandler initialized")

        # Test create
        result = await handler.handle_create_task({
            "agent_id": "test-mcp-agent",
            "task_type": "testing",
            "priority": 1,
            "title": "MCP Handler Test",
            "description": "Testing async handler methods"
        })
        task_id = result["task_id"]
        print(f"✅ handle_create_task: {task_id}")

        # Test list
        result = await handler.handle_list_assignments({
            "agent_id": "test-mcp-agent",
            "limit": 10
        })
        print(f"✅ handle_list_assignments: {result['total']} tasks")

        # Test update
        result = await handler.handle_update_status({
            "task_id": task_id,
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat()
        })
        print(f"✅ handle_update_status: status={result['status']}")

        # Test stats
        result = await handler.handle_get_stats({
            "agent_id": "test-mcp-agent"
        })
        print(f"✅ handle_get_stats: completed={result['completed']}")

        # Cleanup
        print("\nCleaning up test data...")
        pool = PostgresPool(dsn=dsn)
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM tasks WHERE agent_id LIKE 'test-%'")
                deleted = cur.rowcount
                conn.commit()
                print(f"✅ Deleted {deleted} test tasks")

    except Exception as e:
        print(f"❌ MCPTaskHandler test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

asyncio.run(test_handler())

print("\n" + "=" * 60)
print("✅ All integration tests passed!")
print("=" * 60)
