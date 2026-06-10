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
import uuid
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
    EVENT_REPLY_COMPLETE,
    EVENT_REPLY_ERROR,
    ConversationEventHub,
)
from amprealize.llm.credential_factory import build_credential_store
from amprealize.llm.model_readiness import validate_and_enrich_chat_message_metadata

logger = logging.getLogger(__name__)


def _validate_model_metadata(
    metadata: Dict[str, Any],
    *,
    conversation_id: str,
    user_id: str,
    conversation_service: Any,
) -> Dict[str, Any]:
    model_id = metadata.get("llm_model_id")
    provider = metadata.get("llm_provider")
    credential_scope = metadata.get("credential_scope")
    if model_id is None and provider is None and credential_scope is None:
        return metadata

    conversation = conversation_service.get_conversation(conversation_id, user_id=user_id)
    return validate_and_enrich_chat_message_metadata(
        credential_store=build_credential_store(),
        conversation=conversation,
        user_id=user_id,
        effective_org_id=conversation.org_id,
        metadata=metadata,
    )


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
                    if event_type in (EVENT_COMPLETE, EVENT_ERROR, EVENT_REPLY_COMPLETE, EVENT_REPLY_ERROR):
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
    conversation_reply_service: Optional[Any] = None,
) -> None:
    """Process a single client→server WebSocket command."""
    msg_type = data.get("type", "")

    if msg_type == "ping":
        logger.debug(
            "conversation.ws.ping conversation_id=%s user_id=%s",
            conversation_id,
            user_id,
        )
        await ws.send_json({"type": "pong"})
        return

    logger.info(
        "conversation.ws.command conversation_id=%s user_id=%s command=%s",
        conversation_id,
        user_id,
        msg_type,
    )

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
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        try:
            message_type = MessageType(message_type_str)
        except ValueError:
            message_type = MessageType.TEXT
        run_id = data.get("run_id")
        work_item_id = data.get("work_item_id")
        try:
            metadata = _validate_model_metadata(
                metadata,
                conversation_id=conversation_id,
                user_id=user_id,
                conversation_service=conversation_service,
            )
            conversation = conversation_service.get_conversation(
                conversation_id,
                user_id=user_id,
            )
            msg = conversation_service.send_message(
                conversation_id,
                sender_id=user_id,
                content=content,
                message_type=message_type,
                structured_payload=structured_payload,
                parent_id=parent_id,
                run_id=run_id,
                work_item_id=work_item_id,
                metadata=metadata,
                org_id=conversation.org_id,
            )
            # The event is published by the service via the hub hook
            is_agent = bool(metadata.get("actor_type") == "agent") if metadata else False
            if (
                conversation_reply_service is not None
                and not is_agent
                and message_type.value == "text"
                and content
                and metadata.get("llm_model_id")
            ):
                from amprealize.services.conversation_reply_service import ReplyRequest

                stream_message_id = str(
                    metadata.get("stream_message_id")
                    or f"msg-{uuid.uuid4().hex[:12]}"
                )
                msg.metadata = {
                    **(msg.metadata or {}),
                    "stream_message_id": stream_message_id,
                }
                reply_metadata = {
                    **metadata,
                    "stream_message_id": stream_message_id,
                    "conversation_scope": conversation.scope.value,
                }

                async def _run_reply() -> None:
                    await conversation_reply_service.generate_reply(
                        ReplyRequest(
                            conversation_id=conversation_id,
                            user_message_id=msg.id,
                            user_message_content=content,
                            user_id=user_id,
                            work_item_id=work_item_id,
                            run_id=run_id,
                            org_id=conversation.org_id,
                            project_id=conversation.project_id,
                            metadata=reply_metadata,
                            stream_message_id=stream_message_id,
                        )
                    )

                reply_task = asyncio.create_task(_run_reply())

                def _log_reply_task_done(t: asyncio.Task) -> None:
                    try:
                        exc = t.exception()
                    except asyncio.CancelledError:
                        return
                    if exc is not None:
                        logger.error(
                            "conversation_reply.task_failed conversation_id=%s user_message_id=%s",
                            conversation_id,
                            msg.id,
                            exc_info=exc,
                        )

                reply_task.add_done_callback(_log_reply_task_done)
                logger.info(
                    "conversation_reply.scheduled conversation_id=%s user_message_id=%s model=%s",
                    conversation_id,
                    msg.id,
                    metadata.get("llm_model_id"),
                )
            elif message_type.value == "text" and content and not is_agent:
                skip_reasons: List[str] = []
                if conversation_reply_service is None:
                    skip_reasons.append("no_reply_service")
                if not metadata.get("llm_model_id"):
                    skip_reasons.append("no_llm_model_id_in_metadata")
                if skip_reasons:
                    logger.info(
                        "conversation_reply.skipped_ws conversation_id=%s user_message_id=%s "
                        "reasons=%s has_metadata_keys=%s",
                        conversation_id,
                        msg.id,
                        ",".join(skip_reasons),
                        sorted(metadata.keys()) if metadata else [],
                    )
        except Exception as exc:
            logger.warning(
                "conversation.ws.message_send_failed conversation_id=%s user_id=%s: %s",
                conversation_id,
                user_id,
                exc,
                exc_info=True,
            )
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
    conversation_reply_service: Optional[Any] = None,
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
                try:
                    raw = await websocket.receive()
                except WebSocketDisconnect:
                    break
                if raw.get("type") == "websocket.disconnect":
                    break
                if raw.get("type") != "websocket.receive":
                    continue
                text = raw.get("text")
                if text is None:
                    continue
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    await websocket.send_json({
                        "type": "error",
                        "payload": {"code": "BAD_JSON", "message": "Invalid JSON"},
                    })
                    continue
                if not isinstance(data, dict):
                    await websocket.send_json({
                        "type": "error",
                        "payload": {"code": "BAD_MESSAGE", "message": "JSON object expected"},
                    })
                    continue
                try:
                    await _handle_client_message(
                        websocket,
                        data,
                        conversation_id,
                        user_id,
                        conversation_event_hub,
                        conversation_service,
                        conversation_reply_service=conversation_reply_service,
                    )
                except WebSocketDisconnect:
                    break
                except Exception:
                    logger.exception(
                        "Conversation WS handler error for %s",
                        conversation_id,
                    )
                    try:
                        await websocket.send_json({
                            "type": "error",
                            "payload": {
                                "code": "INTERNAL",
                                "message": "Command failed",
                            },
                        })
                    except Exception:
                        break

        except WebSocketDisconnect:
            pass
        except Exception:
            logger.exception("Conversation WS error for %s", conversation_id)
        finally:
            # Clear typing state on disconnect
            conversation_event_hub.set_typing(conversation_id, user_id, "user", False)
            await conversation_event_hub.disconnect(websocket, conversation_id)
