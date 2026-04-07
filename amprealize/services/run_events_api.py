"""SSE (Server-Sent Events) endpoint for real-time execution events.

Provides `GET /v1/runs/{run_id}/events` — a streaming endpoint that
emits execution events as they occur. Clients can use `curl --no-buffer`
or any SSE client library to consume events.

Event types:
    execution.status     — Run status change (PENDING, RUNNING, etc.)
    execution.step       — New execution step recorded
    gate.waiting         — Execution paused at a STRICT gate
    gate.clarification_needed — Agent needs clarification
    gate.approved        — Gate was approved, execution resuming
    gate.soft_passed     — SOFT gate auto-passed with notification
    run.completed        — Execution completed successfully
    run.failed           — Execution failed

SSE format:
    event: <event_type>
    data: {"run_id": "...", ...}
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)


def create_run_events_routes(event_hub: Any) -> APIRouter:
    """Create FastAPI router for SSE run events.

    Args:
        event_hub: ExecutionEventHub instance with subscribe_queue support.

    Returns:
        APIRouter with SSE endpoint.
    """
    router = APIRouter(tags=["run-events"])

    async def _sse_generator(
        request: Request,
        queue: asyncio.Queue,
        event_hub_ref: Any,
    ) -> AsyncGenerator[str, None]:
        """Async generator that yields SSE-formatted events from a queue."""
        try:
            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    break

                try:
                    # Wait for events with a timeout for keep-alive
                    message = await asyncio.wait_for(queue.get(), timeout=30.0)
                    event_type = message.get("type", "execution.status")
                    payload = message.get("payload", {})
                    data = json.dumps(payload, default=str)
                    yield f"event: {event_type}\ndata: {data}\n\n"
                except asyncio.TimeoutError:
                    # Send keep-alive comment to prevent connection timeout
                    yield ": keepalive\n\n"

        except asyncio.CancelledError:
            pass
        finally:
            await event_hub_ref.unsubscribe_queue(queue)

    @router.get(
        "/v1/runs/{run_id}/events",
        summary="Stream execution events (SSE)",
        description=(
            "Server-Sent Events stream for real-time execution updates. "
            "Connect with `curl -N` or an EventSource client. "
            "Events include status changes, phase transitions, gate events, "
            "and clarification requests."
        ),
        responses={
            200: {
                "description": "SSE event stream",
                "content": {"text/event-stream": {}},
            },
        },
    )
    async def stream_run_events(
        run_id: str,
        request: Request,
        org_id: Optional[str] = Query(None, description="Organization ID"),
        project_id: Optional[str] = Query(None, description="Project ID"),
    ) -> StreamingResponse:
        """Stream execution events for a run via SSE.

        Usage:
            curl -N -H "Authorization: Bearer <token>" \\
                http://localhost:8000/api/v1/runs/<run_id>/events
        """
        queue = await event_hub.subscribe_queue(
            run_id=run_id,
            org_id=org_id,
            project_id=project_id,
        )

        return StreamingResponse(
            _sse_generator(request, queue, event_hub),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            },
        )

    return router
