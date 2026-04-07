"""Execution event hub for real-time run updates over WebSocket and SSE."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional, Set

from starlette.websockets import WebSocket

logger = logging.getLogger(__name__)


class ExecutionEventHub:
    """In-memory pub/sub for execution updates.

    Supports two subscriber types:
    - WebSocket connections (existing, for web UI)
    - asyncio.Queue subscribers (new, for SSE endpoints)
    """

    def __init__(self) -> None:
        self._run_subscribers: Dict[str, Set[WebSocket]] = {}
        self._project_subscribers: Dict[str, Set[WebSocket]] = {}
        # Queue-based subscribers for SSE
        self._run_queues: Dict[str, Set[asyncio.Queue]] = {}
        self._project_queues: Dict[str, Set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def connect(
        self,
        websocket: WebSocket,
        *,
        run_id: Optional[str] = None,
        org_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> None:
        await websocket.accept()
        async with self._lock:
            if run_id:
                self._run_subscribers.setdefault(run_id, set()).add(websocket)
            if org_id and project_id:
                key = f"{org_id}:{project_id}"
                self._project_subscribers.setdefault(key, set()).add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            for subscribers in list(self._run_subscribers.values()):
                subscribers.discard(websocket)
            for subscribers in list(self._project_subscribers.values()):
                subscribers.discard(websocket)

    # ------------------------------------------------------------------
    # Queue-based subscribers (for SSE)
    # ------------------------------------------------------------------

    async def subscribe_queue(
        self,
        *,
        run_id: Optional[str] = None,
        org_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> asyncio.Queue:
        """Subscribe via an asyncio.Queue for SSE streaming.

        Returns a Queue that will receive events as dicts:
            {"type": "<event_type>", "payload": {...}}
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        async with self._lock:
            if run_id:
                self._run_queues.setdefault(run_id, set()).add(queue)
            if org_id and project_id:
                key = f"{org_id}:{project_id}"
                self._project_queues.setdefault(key, set()).add(queue)
        return queue

    async def unsubscribe_queue(self, queue: asyncio.Queue) -> None:
        """Remove a queue subscriber."""
        async with self._lock:
            for queues in list(self._run_queues.values()):
                queues.discard(queue)
            for queues in list(self._project_queues.values()):
                queues.discard(queue)

    def publish_status(self, payload: Dict[str, Any]) -> None:
        self._schedule_broadcast("execution.status", payload)

    def publish_step(self, payload: Dict[str, Any]) -> None:
        self._schedule_broadcast("execution.step", payload)

    def publish_gate_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Publish a gate-specific event (gate.waiting, gate.clarification_needed, etc.)."""
        self._schedule_broadcast(event_type, payload)

    def _schedule_broadcast(self, event_type: str, payload: Dict[str, Any]) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._broadcast(event_type, payload))

    async def _broadcast(self, event_type: str, payload: Dict[str, Any]) -> None:
        run_id = payload.get("run_id")
        org_id = payload.get("org_id")
        project_id = payload.get("project_id")

        # Collect WebSocket targets
        ws_targets: Set[WebSocket] = set()
        # Collect queue targets
        queue_targets: Set[asyncio.Queue] = set()

        async with self._lock:
            if run_id:
                if run_id in self._run_subscribers:
                    ws_targets.update(self._run_subscribers[run_id])
                if run_id in self._run_queues:
                    queue_targets.update(self._run_queues[run_id])
            if org_id and project_id:
                key = f"{org_id}:{project_id}"
                ws_targets.update(self._project_subscribers.get(key, set()))
                queue_targets.update(self._project_queues.get(key, set()))

        message = {"type": event_type, "payload": payload}

        # Send to WebSocket subscribers
        for websocket in list(ws_targets):
            try:
                await websocket.send_json(message)
            except Exception:
                await self.disconnect(websocket)

        # Send to queue subscribers
        for queue in list(queue_targets):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                logger.warning(
                    f"SSE queue full for run_id={run_id}, dropping event {event_type}"
                )
