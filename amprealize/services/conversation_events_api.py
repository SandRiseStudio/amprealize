"""WebSocket endpoint for real-time conversation events (AMPREALIZE-574).

Provides ``ws://host/api/v1/conversations/{conversation_id}/ws`` —
a bidirectional WebSocket that:

- Broadcasts server events (message.new, reaction.added, typing.indicator, …)
- Accepts client commands (message.send, typing.start, read.update, …)

SSE endpoint for agent token streaming (AMPREALIZE-576):

- ``GET /api/v1/conversations/{conversation_id}/stream/{message_id}``
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from starlette.websockets import WebSocket, WebSocketDisconnect

from amprealize.conversation_contracts import ActorType, MessageType
from amprealize.conversation_event_hub import (
    EVENT_COMPLETE,
    EVENT_ERROR,
    EVENT_MESSAGE_DELETED,
    EVENT_MESSAGE_NEW,
    EVENT_MESSAGE_UPDATED,
    EVENT_REACTION_ADDED,
    EVENT_REACTION_REMOVED,
    ConversationEventHub,
)

logger = logging.getLogger(__name__)


def create_conversation_ws_routes(
    conversation_event_hub: ConversationEventHub,
    conversation_service: Any,
) -> APIRouter:
    """Create the SSE router for conversation token streaming.

    The WebSocket endpoint must be registered directly on the FastAPI app
    (not via a router) because Starlette doesn't support ``@router.websocket``
    with path params the same way.  See ``register_conversation_ws()`` below.

    Args:
        conversation_event_hub: The shared ConversationEventHub instance.
        conversation_service: The ConversationService for persistence.

    Returns:
        APIRouter with the SSE streaming endpoint.
    """
    router = APIRouter(tags=["conversation-events"])

    # ------------------------------------------------------------------
    # SSE — agent token streaming
    # ------------------------------------------------------------------

    async def _sse_generator(
        request: Request,
        queue: asyncio.Queue,
        hub: ConversationEventHub,
        conversation_id: str,
    ) -> AsyncGenerator[str, None]:
        """Yield SSE-formatted events from a queue."""
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=30.0)
                    event_type = message.get("type", "token")
                    payload = message.get("payload", {})
                    data = json.dumps(payload, default=str)
                    yield f"event: {event_type}\ndata: {data}\n\n"

                    # Stop streaming on completion or error
                    if event_type in (EVENT_COMPLETE, EVENT_ERROR):
                        break
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            await hub.unsubscribe_queue(queue, conversation_id=conversation_id)

    @router.get(
        "/v1/conversations/{conversation_id}/stream/{message_id}",
        summary="Stream agent reply tokens (SSE)",
        description=(
            "Server-Sent Events stream for agent token-by-token reply. "
            "Connect with EventSource or `curl -N`."
        ),
        responses={200: {"description": "SSE event stream", "content": {"text/event-stream": {}}}},
    )
    async def stream_message_tokens(
        request: Request,
        conversation_id: str,
        message_id: str,
    ) -> StreamingResponse:
        queue = await conversation_event_hub.subscribe_queue(
            conversation_id, message_id=message_id,
        )
        return StreamingResponse(
            _sse_generator(request, queue, conversation_event_hub, conversation_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # ------------------------------------------------------------------
    # SSE — conversation event stream (alternative to WebSocket)
    # ------------------------------------------------------------------

    async def _conversation_sse_generator(
        request: Request,
        queue: asyncio.Queue,
        hub: ConversationEventHub,
        conversation_id: str,
    ) -> AsyncGenerator[str, None]:
        """Yield all conversation events as SSE (for clients that don't support WS)."""
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=30.0)
                    event_type = message.get("type", "message.new")
                    payload = message.get("payload", {})
                    data = json.dumps(payload, default=str)
                    yield f"event: {event_type}\ndata: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            await hub.unsubscribe_queue(queue, conversation_id=conversation_id)

    @router.get(
        "/v1/conversations/{conversation_id}/events",
        summary="Stream conversation events (SSE)",
        description=(
            "Server-Sent Events stream for all conversation events. "
            "Alternative to WebSocket for clients that don't support WS."
        ),
        responses={200: {"description": "SSE event stream", "content": {"text/event-stream": {}}}},
    )
    async def stream_conversation_events(
        request: Request,
        conversation_id: str,
    ) -> StreamingResponse:
        queue = await conversation_event_hub.subscribe_queue(conversation_id)
        return StreamingResponse(
            _conversation_sse_generator(request, queue, conversation_event_hub, conversation_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return router


async def _handle_client_message(
    ws: WebSocket,
    data: Dict[str, Any],
    conversation_id: str,
    user_id: str,
    hub: ConversationEventHub,
    conversation_service: Any,
) -> None:
    """Process a single client→server WebSocket command."""
    msg_type = data.get("type", "")

    if msg_type == "ping":
        await ws.send_json({"type": "pong"})
        return

    if msg_type == "typing.start":
        hub.set_typing(conversation_id, user_id, "user", True)
        return

    if msg_type == "typing.stop":
        hub.set_typing(conversation_id, user_id, "user", False)
        return

    if msg_type == "read.update":
        last_read_message_id = data.get("last_read_message_id")
        if last_read_message_id:
            now = datetime.now(timezone.utc)
            try:
                conversation_service.update_participant(
                    conversation_id,
                    user_id,
                    last_read_at=now,
                )
                hub.publish_read_receipt(conversation_id, user_id, now.isoformat())
            except Exception as exc:
                logger.warning("read.update failed: %s", exc)
        return

    if msg_type == "message.send":
        content = data.get("content")
        message_type_str = data.get("message_type", "text")
        parent_id = data.get("parent_id")
        structured_payload = data.get("structured_payload")
        try:
            message_type = MessageType(message_type_str)
        except ValueError:
            message_type = MessageType.TEXT
        try:
            msg = conversation_service.send_message(
                conversation_id,
                sender_id=user_id,
                content=content,
                message_type=message_type,
                structured_payload=structured_payload,
                parent_id=parent_id,
            )
            # The event is published by the service via the hub hook
        except Exception as exc:
            await ws.send_json({
                "type": "error",
                "payload": {"code": "SEND_FAILED", "message": str(exc)},
            })
        return

    if msg_type == "message.edit":
        message_id = data.get("message_id")
        content = data.get("content")
        if message_id and content:
            try:
                conversation_service.edit_message(message_id, new_content=content, editor_id=user_id)
            except Exception as exc:
                await ws.send_json({
                    "type": "error",
                    "payload": {"code": "EDIT_FAILED", "message": str(exc)},
                })
        return

    if msg_type == "message.delete":
        message_id = data.get("message_id")
        if message_id:
            try:
                conversation_service.delete_message(message_id, deleter_id=user_id)
            except Exception as exc:
                await ws.send_json({
                    "type": "error",
                    "payload": {"code": "DELETE_FAILED", "message": str(exc)},
                })
        return

    if msg_type == "reaction.add":
        message_id = data.get("message_id")
        emoji = data.get("emoji")
        if message_id and emoji:
            try:
                conversation_service.add_reaction(message_id, actor_id=user_id, emoji=emoji)
            except Exception as exc:
                await ws.send_json({
                    "type": "error",
                    "payload": {"code": "REACTION_FAILED", "message": str(exc)},
                })
        return

    if msg_type == "reaction.remove":
        message_id = data.get("message_id")
        emoji = data.get("emoji")
        if message_id and emoji:
            try:
                conversation_service.remove_reaction(message_id, actor_id=user_id, emoji=emoji)
            except Exception as exc:
                await ws.send_json({
                    "type": "error",
                    "payload": {"code": "REACTION_FAILED", "message": str(exc)},
                })
        return

    # Unknown command
    await ws.send_json({
        "type": "error",
        "payload": {"code": "UNKNOWN_COMMAND", "message": f"Unknown type: {msg_type}"},
    })


def register_conversation_ws(
    app: Any,
    conversation_event_hub: ConversationEventHub,
    conversation_service: Any,
) -> None:
    """Register the conversation WebSocket endpoint directly on the FastAPI app.

    Called during app startup in api.py.
    """

    @app.websocket("/api/v1/conversations/{conversation_id}/ws")
    async def conversation_ws(websocket: WebSocket, conversation_id: str) -> None:
        user_id = websocket.query_params.get("user_id", "")
        if not user_id:
            await websocket.accept()
            await websocket.send_json({
                "type": "error",
                "code": "BAD_REQUEST",
                "message": "user_id query parameter required",
            })
            await websocket.close(code=1008)
            return

        await conversation_event_hub.connect(websocket, conversation_id)

        try:
            # Send initial state: who is currently typing
            typing_actors = conversation_event_hub.get_typing_actors(conversation_id)
            await websocket.send_json({
                "type": "conversation.ready",
                "payload": {
                    "conversation_id": conversation_id,
                    "typing": typing_actors,
                    "subscriber_count": conversation_event_hub.subscriber_count(conversation_id),
                },
            })

            while True:
                data = await websocket.receive_json()
                await _handle_client_message(
                    websocket,
                    data,
                    conversation_id,
                    user_id,
                    conversation_event_hub,
                    conversation_service,
                )

        except WebSocketDisconnect:
            pass
        except Exception:
            logger.exception("Conversation WS error for %s", conversation_id)
        finally:
            # Clear typing state on disconnect
            conversation_event_hub.set_typing(conversation_id, user_id, "user", False)
            await conversation_event_hub.disconnect(websocket, conversation_id)
