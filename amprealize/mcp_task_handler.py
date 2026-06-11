#!/usr/bin/env python3
"""
MCP Task Handler

Handles MCP tool calls for agent task management (assignment, status updates, analytics).
Routes to TaskService for PostgreSQL persistence and business logic.

Tools:
- tasks.listAssignments - List tasks with filters (agent_id, status, task_type, limit)
- tasks.create - Create new task assignment
- tasks.updateStatus - Update task status and completion
- tasks.getStats - Get task analytics

Example MCP call (tasks.listAssignments):
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "tasks.listAssignments",
    "arguments": {
      "agent_id": "agent-engineering-01",
      "status": "in_progress",
      "limit": 10
    }
  }
}
"""

import logging
from datetime import datetime
from typing import Any, Dict

from .services.task_service import TaskService, CreateTaskRequest, UpdateTaskRequest, ListTasksRequest


class MCPTaskHandler:
    """MCP handler for task management tools."""

    def __init__(self, task_service: TaskService) -> None:
        """
        Initialize handler with TaskService.

        Args:
            task_service: TaskService instance for persistence
        """
        self._task_service = task_service
        self._logger = logging.getLogger("amprealize.mcp_task_handler")

    async def handle_list_assignments(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle tasks.listAssignments tool call.

        Example call:
        {
          "agent_id": "agent-engineering-01",
          "status": "in_progress",
          "task_type": "code_review",
          "limit": 20
        }

        Response:
        {
          "tasks": [
            {
              "task_id": "uuid",
              "agent_id": "agent-engineering-01",
              "task_type": "code_review",
              "status": "in_progress",
              "priority": 2,
              "title": "Review PR #123",
              "description": "Code review for new feature",
              "metadata": {},
              "created_at": "2025-11-12T10:00:00Z",
              "updated_at": "2025-11-12T10:30:00Z",
              "completed_at": null,
              "deadline": "2025-11-13T18:00:00Z"
            }
          ],
          "total": 1
        }
        """
        self._logger.info(f"Listing tasks with filters: {arguments}")

        # Parse filters from MCP arguments
        request = ListTasksRequest(
            agent_id=arguments.get("agent_id"),
            status=arguments.get("status"),
            task_type=arguments.get("task_type"),
            behavior_id=arguments.get("behavior_id"),
            run_id=arguments.get("run_id"),
            limit=arguments.get("limit", 50),
        )

        # Query TaskService
        tasks = self._task_service.list_tasks(request)

        # Map to MCP response format
        tasks_list = [
            {
                "task_id": task.task_id,
                "agent_id": task.agent_id,
                "task_type": task.task_type,
                "status": task.status,
                "priority": task.priority,
                "title": task.title,
                "description": task.description,
                "metadata": task.metadata or {},
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "updated_at": task.updated_at.isoformat() if task.updated_at else None,
                "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                "deadline": task.deadline.isoformat() if task.deadline else None,
            }
            for task in tasks
        ]

        return {
            "tasks": tasks_list,
            "total": len(tasks_list),
        }

    async def handle_create_task(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle tasks.create tool call.

        Example call:
        {
          "agent_id": "agent-engineering-01",
          "task_type": "code_review",
          "priority": 2,
          "title": "Review PR #123",
          "description": "Code review for authentication feature",
          "deadline": "2025-11-13T18:00:00Z",
          "metadata": {
            "pr_number": 123,
            "repository": "amprealize/core"
          }
        }

        Response:
        {
          "task_id": "uuid",
          "agent_id": "agent-engineering-01",
          "task_type": "code_review",
          "status": "pending",
          "priority": 2,
          "title": "Review PR #123",
          "description": "Code review for authentication feature",
          "metadata": {...},
          "created_at": "2025-11-12T10:00:00Z",
          "updated_at": "2025-11-12T10:00:00Z",
          "completed_at": null,
          "deadline": "2025-11-13T18:00:00Z"
        }
        """
        self._logger.info(f"Creating task: {arguments}")

        # Parse deadline if provided
        deadline = None
        if arguments.get("deadline"):
            try:
                deadline = datetime.fromisoformat(arguments["deadline"].replace("Z", "+00:00"))
            except ValueError as e:
                self._logger.warning(f"Invalid deadline format: {e}")

        # Build creation request
        request = CreateTaskRequest(
            agent_id=arguments["agent_id"],
            task_type=arguments["task_type"],
            priority=arguments.get("priority", 3),
            title=arguments["title"],
            description=arguments.get("description"),
            behavior_id=arguments.get("behavior_id"),
            run_id=arguments.get("run_id"),
            deadline=deadline,
            metadata=arguments.get("metadata"),
        )

        # Create task via TaskService
        task = self._task_service.create_task(request)

        # Map to MCP response format
        return {
            "task_id": task.task_id,
            "agent_id": task.agent_id,
            "task_type": task.task_type,
            "status": task.status,
            "priority": task.priority,
            "title": task.title,
            "description": task.description,
            "metadata": task.metadata or {},
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "updated_at": task.updated_at.isoformat() if task.updated_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "deadline": task.deadline.isoformat() if task.deadline else None,
        }

    async def handle_update_status(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle tasks.updateStatus tool call.

        Example call:
        {
          "task_id": "uuid",
          "status": "completed",
          "priority": 2,
          "metadata": {
            "completion_notes": "Reviewed and approved"
          },
          "completed_at": "2025-11-12T12:00:00Z"
        }

        Response:
        {
          "task_id": "uuid",
          "agent_id": "agent-engineering-01",
          "task_type": "code_review",
          "status": "completed",
          "priority": 2,
          "title": "Review PR #123",
          "description": "Code review for authentication feature",
          "metadata": {...},
          "created_at": "2025-11-12T10:00:00Z",
          "updated_at": "2025-11-12T12:00:00Z",
          "completed_at": "2025-11-12T12:00:00Z",
          "deadline": "2025-11-13T18:00:00Z"
        }
        """
        self._logger.info(f"Updating task status: {arguments}")

        # Parse completed_at if provided
        completed_at = None
        if arguments.get("completed_at"):
            try:
                completed_at = datetime.fromisoformat(arguments["completed_at"].replace("Z", "+00:00"))
            except ValueError as e:
                self._logger.warning(f"Invalid completed_at format: {e}")

        # Build update request
        request = UpdateTaskRequest(
            task_id=arguments["task_id"],
            status=arguments.get("status"),
            priority=arguments.get("priority"),
            metadata=arguments.get("metadata"),
            completed_at=completed_at,
        )

        # Update task via TaskService
        task = self._task_service.update_task(request)

        # Map to MCP response format
        return {
            "task_id": task.task_id,
            "agent_id": task.agent_id,
            "task_type": task.task_type,
            "status": task.status,
            "priority": task.priority,
            "title": task.title,
            "description": task.description,
            "metadata": task.metadata or {},
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "updated_at": task.updated_at.isoformat() if task.updated_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "deadline": task.deadline.isoformat() if task.deadline else None,
        }

    async def handle_get_stats(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle tasks.getStats tool call.

        Example call:
        {
          "agent_id": "agent-engineering-01",
          "task_type": "code_review"
        }

        Response:
        {
          "total": 42,
          "pending": 5,
          "in_progress": 3,
          "completed": 30,
          "failed": 2,
          "blocked": 1,
          "cancelled": 1,
          "avg_completion_time_hours": 4.5
        }
        """
        self._logger.info(f"Getting task stats: {arguments}")

        # Query TaskService
        stats = self._task_service.get_task_stats(
            agent_id=arguments.get("agent_id"),
            task_type=arguments.get("task_type"),
        )

        # Map to MCP response format
        return {
            "total": stats.total,
            "pending": stats.pending,
            "in_progress": stats.in_progress,
            "completed": stats.completed,
            "failed": stats.failed,
            "blocked": stats.blocked,
            "cancelled": stats.cancelled,
            "avg_completion_time_hours": stats.avg_completion_time_hours,
        }
