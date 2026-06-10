"""Conversation REST API routes (AMPREALIZE-571).

Provides REST endpoints for the messaging system.
Follows the board_api_v2.py factory pattern.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from enum import Enum
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request, status

from amprealize.conversation_contracts import (
    ConversationListResponse,
    ConversationResponse,
    ConversationScope,
    CreateConversationRequest,
    DirectConversationRequest,
    DirectConversationResponse,
    EditMessageRequest,
    GlobalChatBootstrapResponse,
    MessageListResponse,
    MessageResponse,
    PinMessageRequest,
    SearchResult,
    SearchResultsResponse,
    SendMessageRequest,
    UpdateConversationRequest,
    UpdateParticipantRequest,
    normalize_conversation_scope,
)
from amprealize.llm.credential_factory import build_credential_store
from amprealize.llm.model_readiness import validate_and_enrich_chat_message_metadata
from amprealize.perf_log import perf_span
from amprealize.services.conversation_circuit_breaker import (
    AmplificationCircuitBreaker,
)
from amprealize.services.conversation_rate_limiter import (
    ConversationRateLimiter,
    Lane,
    RateLimitExceeded,
)
from amprealize.services.conversation_service import (
    AccessDeniedError,
    Conversation,
    ConversationNotFoundError,
    ConversationService,
    ConversationServiceError,
    DuplicateReactionError,
    EditWindowClosedError,
    Message,
    MessageNotFoundError,
)

logger = logging.getLogger(__name__)


def _conv_to_response(c: Conversation) -> ConversationResponse:
    d = c.to_dict()
    return ConversationResponse(**d)


def _msg_to_response(m: Message) -> MessageResponse:
    d = m.to_dict()
    return MessageResponse(**d)


# Module-level singletons — shared across all routers created in this process.
_rate_limiter = ConversationRateLimiter()
_circuit_breaker = AmplificationCircuitBreaker()


def create_conversation_routes(
    conversation_service: ConversationService,
    tags: Optional[List[str | Enum]] = None,
    rate_limiter: Optional[ConversationRateLimiter] = None,
    circuit_breaker: Optional[AmplificationCircuitBreaker] = None,
    conversation_reply_service: Optional[Any] = None,
) -> APIRouter:
    """Create FastAPI router for conversation/messaging endpoints.

    Args:
        conversation_service: ConversationService instance.
        tags: Optional OpenAPI tags.

    Returns:
        APIRouter with all conversation endpoints.
    """
    rl = rate_limiter or _rate_limiter
    cb = circuit_breaker or _circuit_breaker
    router_tags: List[str | Enum] = list(tags) if tags else ["conversations"]
    router = APIRouter(tags=router_tags)

    def _get_user_id(request: Request) -> str:
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        return user_id

    def _get_org_id(request: Request) -> Optional[str]:
        return getattr(request.state, "org_id", None)

    def _validate_model_metadata(
        *,
        metadata: Dict[str, Any],
        conversation_id: str,
        user_id: str,
        org_id: Optional[str],
    ) -> Dict[str, Any]:
        """Validate optional chat model selection metadata before persistence."""
        model_id = metadata.get("llm_model_id")
        provider = metadata.get("llm_provider")
        credential_scope = metadata.get("credential_scope")
        if model_id is None and provider is None and credential_scope is None:
            return metadata

        conversation = conversation_service.get_conversation(
            conversation_id,
            org_id=org_id,
            user_id=user_id,
        )
        try:
            return validate_and_enrich_chat_message_metadata(
                credential_store=build_credential_store(),
                conversation=conversation,
                user_id=user_id,
                effective_org_id=org_id or conversation.org_id,
                metadata=metadata,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    # =========================================================================
    # Conversations
    # =========================================================================

    @router.post(
        "/v1/projects/{project_id}/conversations",
        response_model=ConversationResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Create conversation",
    )
    def create_conversation(
        request: Request,
        body: CreateConversationRequest,
        project_id: str,
    ) -> ConversationResponse:
        user_id = _get_user_id(request)
        org_id = _get_org_id(request)
        try:
            conv = conversation_service.create_conversation(
                project_id=project_id,
                scope=body.scope,
                title=body.title,
                created_by=user_id,
                participant_ids=body.participant_ids,
                org_id=org_id,
            )
            return _conv_to_response(conv)
        except ConversationServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @router.post(
        "/v1/conversations",
        response_model=ConversationResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Create global or project conversation",
    )
    def create_conversation_any_scope(
        request: Request,
        body: CreateConversationRequest,
    ) -> ConversationResponse:
        user_id = _get_user_id(request)
        org_id = _get_org_id(request)
        try:
            conv = conversation_service.create_conversation(
                project_id=body.project_id,
                scope=body.scope,
                title=body.title,
                created_by=user_id,
                participant_ids=body.participant_ids,
                org_id=org_id,
            )
            return _conv_to_response(conv)
        except ConversationServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @router.post(
        "/v1/projects/{project_id}/conversations/direct",
        response_model=DirectConversationResponse,
        status_code=status.HTTP_200_OK,
        summary="Get or create a direct conversation",
    )
    def get_or_create_direct(
        request: Request,
        body: DirectConversationRequest,
        project_id: str,
    ) -> DirectConversationResponse:
        user_id = _get_user_id(request)
        org_id = _get_org_id(request)
        try:
            conv, created = conversation_service.get_or_create_direct_conversation(
                project_id=project_id,
                user_id=user_id,
                target_participant_id=body.target_participant_id,
                target_actor_type=body.actor_type,
                org_id=org_id,
            )
            return DirectConversationResponse(
                conversation=_conv_to_response(conv),
                created=created,
            )
        except ConversationServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @router.get(
        "/v1/projects/{project_id}/conversations",
        response_model=ConversationListResponse,
        summary="List conversations",
    )
    def list_conversations(
        request: Request,
        project_id: str,
        scope: Optional[str] = Query(default=None, description="Filter by a single scope"),
        scopes: Annotated[
            Optional[List[str]],
            Query(
                description=(
                    "Repeat to filter by several scopes at once (union). "
                    "When set, overrides `scope`."
                ),
            ),
        ] = None,
        include_archived: bool = Query(default=False),
        include_total: bool = Query(
            default=True,
            description="When false, skips COUNT and returns total=-1.",
        ),
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> ConversationListResponse:
        user_id = _get_user_id(request)
        org_id = _get_org_id(request)
        try:
            scopes_enum: Optional[List[ConversationScope]] = None
            scope_enum: Optional[ConversationScope] = None
            if scopes:
                scopes_enum = [normalize_conversation_scope(ConversationScope(s)) for s in scopes]
            elif scope:
                scope_enum = normalize_conversation_scope(ConversationScope(scope))
            convs, total = conversation_service.list_conversations(
                project_id=project_id,
                user_id=user_id,
                org_id=org_id,
                scope=scope_enum,
                scopes=scopes_enum,
                include_archived=include_archived,
                limit=limit,
                offset=offset,
                include_total=include_total,
            )
        except (ConversationServiceError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return ConversationListResponse(
            items=[_conv_to_response(c) for c in convs],
            total=total,
        )

    @router.get(
        "/v1/conversations",
        response_model=ConversationListResponse,
        summary="List global or project conversations",
    )
    def list_conversations_any_scope(
        request: Request,
        project_id: Optional[str] = Query(default=None, description="Filter by project"),
        scope: Optional[str] = Query(default=None, description="Filter by a single scope"),
        scopes: Annotated[
            Optional[List[str]],
            Query(
                description=(
                    "Repeat to filter by several scopes at once (union). "
                    "When set, overrides `scope`."
                ),
            ),
        ] = None,
        include_archived: bool = Query(default=False),
        include_total: bool = Query(
            default=True,
            description="When false, skips COUNT and returns total=-1.",
        ),
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> ConversationListResponse:
        user_id = _get_user_id(request)
        org_id = _get_org_id(request)
        try:
            scopes_enum: Optional[List[ConversationScope]] = None
            scope_enum: Optional[ConversationScope] = None
            if scopes:
                scopes_enum = [normalize_conversation_scope(ConversationScope(s)) for s in scopes]
            elif scope:
                scope_enum = normalize_conversation_scope(ConversationScope(scope))
            convs, total = conversation_service.list_conversations(
                project_id=project_id,
                user_id=user_id,
                org_id=org_id,
                scope=scope_enum,
                scopes=scopes_enum,
                include_archived=include_archived,
                limit=limit,
                offset=offset,
                include_total=include_total,
            )
        except (ConversationServiceError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return ConversationListResponse(
            items=[_conv_to_response(c) for c in convs],
            total=total,
        )

    @router.get(
        "/v1/conversations/global-chat-bootstrap",
        response_model=GlobalChatBootstrapResponse,
        summary="Bootstrap global user-home chat",
        description=(
            "Return the global_user_home conversation (creating it if missing) and the first page "
            "of messages in one request—used when opening Amprealize Chat from the dock."
        ),
    )
    def global_chat_bootstrap(
        request: Request,
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        include_thread_replies: bool = Query(
            default=True,
            description="Same as GET .../messages: include assistant replies in the transcript.",
        ),
    ) -> GlobalChatBootstrapResponse:
        user_id = _get_user_id(request)
        org_id = _get_org_id(request)
        try:
            with perf_span("conversations.global_chat_bootstrap") as span:
                conv, msgs, total, has_more = conversation_service.bootstrap_global_user_home(
                    user_id=user_id,
                    org_id=org_id,
                    message_limit=limit,
                    message_offset=offset,
                    include_thread_replies=include_thread_replies,
                )
                span["conversation_id"] = conv.id
                span["message_batch"] = len(msgs)
                return GlobalChatBootstrapResponse(
                    conversation=_conv_to_response(conv),
                    messages=MessageListResponse(
                        items=[_msg_to_response(m) for m in msgs],
                        total=total,
                        has_more=has_more,
                    ),
                )
        except ConversationServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @router.get(
        "/v1/conversations/{conversation_id}",
        response_model=ConversationResponse,
        summary="Get conversation",
    )
    def get_conversation(
        request: Request,
        conversation_id: str,
    ) -> ConversationResponse:
        user_id = _get_user_id(request)
        org_id = _get_org_id(request)
        try:
            conv = conversation_service.get_conversation(
                conversation_id, org_id=org_id, user_id=user_id,
            )
            return _conv_to_response(conv)
        except ConversationNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @router.patch(
        "/v1/conversations/{conversation_id}",
        response_model=ConversationResponse,
        summary="Update conversation",
    )
    def patch_conversation(
        request: Request,
        body: UpdateConversationRequest,
        conversation_id: str,
    ) -> ConversationResponse:
        user_id = _get_user_id(request)
        org_id = _get_org_id(request)
        patch = body.model_dump(exclude_unset=True)
        if not patch:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields to update",
            )
        try:
            conv = conversation_service.patch_conversation(
                conversation_id,
                user_id=user_id,
                org_id=org_id,
                patch=patch,
            )
            return _conv_to_response(conv)
        except ConversationNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except AccessDeniedError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        except ConversationServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @router.post(
        "/v1/conversations/{conversation_id}/archive",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Archive conversation",
    )
    def archive_conversation(
        request: Request,
        conversation_id: str,
    ) -> None:
        user_id = _get_user_id(request)
        org_id = _get_org_id(request)
        try:
            conversation_service.archive_conversation(
                conversation_id, user_id=user_id, org_id=org_id,
            )
        except ConversationNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except AccessDeniedError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    # =========================================================================
    # Messages
    # =========================================================================

    @router.post(
        "/v1/conversations/{conversation_id}/messages",
        response_model=MessageResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Send message",
    )
    async def send_message(
        request: Request,
        body: SendMessageRequest,
        conversation_id: str,
    ) -> MessageResponse:
        user_id = _get_user_id(request)
        org_id = _get_org_id(request)
        body.metadata = _validate_model_metadata(
            metadata=body.metadata,
            conversation_id=conversation_id,
            user_id=user_id,
            org_id=org_id,
        )

        # --- Rate limiting (AMPREALIZE-593) ---
        is_agent = bool(body.metadata.get("actor_type") == "agent") if body.metadata else False
        try:
            rl.check(user_id, conversation_id, Lane.MESSAGE, is_agent=is_agent)
        except RateLimitExceeded as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=str(exc),
                headers={"Retry-After": str(int(exc.wait_seconds) + 1)},
            ) from exc

        # --- Circuit breaker for agent-to-agent loops (AMPREALIZE-594) ---
        if is_agent:
            if not cb.allow_agent_message(conversation_id, user_id):
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Agent-to-agent amplification circuit breaker open; please wait",
                )

        try:
            msg = conversation_service.send_message(
                conversation_id,
                sender_id=user_id,
                content=body.content,
                message_type=body.message_type,
                structured_payload=body.structured_payload,
                parent_id=body.parent_id,
                run_id=body.run_id,
                behavior_id=body.behavior_id,
                work_item_id=body.work_item_id,
                resource_links=body.resource_links,
                metadata=body.metadata,
                org_id=org_id,
            )

            # Record agent message for circuit breaker tracking
            if is_agent:
                cb.record_agent_message(conversation_id, user_id)

            if (
                conversation_reply_service is not None
                and not is_agent
                and body.message_type.value == "text"
                and body.content
                and body.metadata.get("llm_model_id")
            ):
                from amprealize.services.conversation_reply_service import ReplyRequest

                stream_message_id = str(
                    body.metadata.get("stream_message_id")
                    or f"msg-{uuid.uuid4().hex[:12]}"
                )
                msg.metadata = {
                    **(msg.metadata or {}),
                    "stream_message_id": stream_message_id,
                }
                conversation = conversation_service.get_conversation(
                    conversation_id,
                    org_id=org_id,
                    user_id=user_id,
                )
                reply_metadata = {
                    **body.metadata,
                    "stream_message_id": stream_message_id,
                    "conversation_scope": conversation.scope.value,
                }

                async def _run_reply() -> None:
                    await conversation_reply_service.generate_reply(
                        ReplyRequest(
                            conversation_id=conversation_id,
                            user_message_id=msg.id,
                            user_message_content=body.content,
                            user_id=user_id,
                            work_item_id=body.work_item_id,
                            run_id=body.run_id,
                            org_id=org_id or conversation.org_id,
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
                    body.metadata.get("llm_model_id"),
                )
            elif body.message_type.value == "text" and body.content and not is_agent:
                skip_reasons: list[str] = []
                if conversation_reply_service is None:
                    skip_reasons.append("no_reply_service")
                if not body.metadata.get("llm_model_id"):
                    skip_reasons.append("no_llm_model_id_in_metadata")
                if skip_reasons:
                    logger.info(
                        "conversation_reply.skipped_rest conversation_id=%s user_message_id=%s "
                        "reasons=%s metadata_keys=%s",
                        conversation_id,
                        msg.id,
                        ",".join(skip_reasons),
                        sorted(body.metadata.keys()) if body.metadata else [],
                    )

            return _msg_to_response(msg)
        except AccessDeniedError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        except MessageNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @router.get(
        "/v1/conversations/{conversation_id}/messages",
        response_model=MessageListResponse,
        summary="List messages",
    )
    def list_messages(
        request: Request,
        conversation_id: str,
        parent_id: Optional[str] = Query(default=None, description="Filter to thread replies"),
        include_thread_replies: bool = Query(
            default=False,
            description=(
                "When true and parent_id is omitted, include replies (e.g. assistant messages "
                "with parent_id set). Default is roots-only for backward compatibility."
            ),
        ),
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        include_total: bool = Query(
            default=True,
            description="When false, skips COUNT and returns total=-1; has_more uses page size.",
        ),
    ) -> MessageListResponse:
        user_id = _get_user_id(request)
        org_id = _get_org_id(request)
        msgs, total, has_more = conversation_service.list_messages(
            conversation_id,
            user_id=user_id,
            org_id=org_id,
            parent_id=parent_id,
            include_thread_replies=include_thread_replies,
            limit=limit,
            offset=offset,
            include_total=include_total,
        )
        return MessageListResponse(
            items=[_msg_to_response(m) for m in msgs],
            total=total,
            has_more=has_more,
        )

    @router.get(
        "/v1/messages/{message_id}",
        response_model=MessageResponse,
        summary="Get message",
    )
    def get_message(
        request: Request,
        message_id: str,
    ) -> MessageResponse:
        user_id = _get_user_id(request)
        org_id = _get_org_id(request)
        try:
            msg = conversation_service.get_message(message_id, org_id=org_id, user_id=user_id)
            return _msg_to_response(msg)
        except MessageNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @router.patch(
        "/v1/messages/{message_id}",
        response_model=MessageResponse,
        summary="Edit message",
    )
    def edit_message(
        request: Request,
        body: EditMessageRequest,
        message_id: str,
    ) -> MessageResponse:
        user_id = _get_user_id(request)
        org_id = _get_org_id(request)
        try:
            msg = conversation_service.edit_message(
                message_id, new_content=body.content, editor_id=user_id, org_id=org_id,
            )
            return _msg_to_response(msg)
        except MessageNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except AccessDeniedError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        except EditWindowClosedError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    @router.delete(
        "/v1/messages/{message_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Delete message",
    )
    def delete_message(
        request: Request,
        message_id: str,
    ) -> None:
        user_id = _get_user_id(request)
        org_id = _get_org_id(request)
        try:
            conversation_service.delete_message(
                message_id, deleter_id=user_id, org_id=org_id,
            )
        except MessageNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except AccessDeniedError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    # =========================================================================
    # Reactions
    # =========================================================================

    @router.post(
        "/v1/messages/{message_id}/reactions",
        status_code=status.HTTP_201_CREATED,
        summary="Add reaction",
    )
    def add_reaction(
        request: Request,
        message_id: str,
        emoji: str = Query(..., min_length=1, max_length=32, description="Emoji to react with"),
    ) -> Dict[str, Any]:
        user_id = _get_user_id(request)
        org_id = _get_org_id(request)

        # Rate-limit reaction spam (AMPREALIZE-593)
        try:
            rl.check(user_id, "_global", Lane.REACTION)
        except RateLimitExceeded as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=str(exc),
                headers={"Retry-After": str(int(exc.wait_seconds) + 1)},
            ) from exc

        try:
            reaction = conversation_service.add_reaction(
                message_id, actor_id=user_id, emoji=emoji, org_id=org_id,
            )
            return reaction.to_dict()
        except MessageNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except DuplicateReactionError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    @router.delete(
        "/v1/messages/{message_id}/reactions",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Remove reaction",
    )
    def remove_reaction(
        request: Request,
        message_id: str,
        emoji: str = Query(..., min_length=1, max_length=32),
    ) -> None:
        user_id = _get_user_id(request)
        org_id = _get_org_id(request)
        conversation_service.remove_reaction(
            message_id, actor_id=user_id, emoji=emoji, org_id=org_id,
        )

    # =========================================================================
    # Participants
    # =========================================================================

    @router.patch(
        "/v1/conversations/{conversation_id}/participants/me",
        summary="Update my participant settings",
    )
    def update_my_participant(
        request: Request,
        body: UpdateParticipantRequest,
        conversation_id: str,
    ) -> Dict[str, Any]:
        user_id = _get_user_id(request)
        org_id = _get_org_id(request)
        try:
            from datetime import datetime, timezone
            last_read = datetime.now(timezone.utc) if body.last_read_message_id else None
            part = conversation_service.update_participant(
                conversation_id,
                user_id,
                is_muted=body.is_muted,
                notification_preference=body.notification_preference,
                last_read_at=last_read,
                org_id=org_id,
            )
            return part.to_dict()
        except AccessDeniedError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    @router.get(
        "/v1/conversations/{conversation_id}/participants",
        summary="List participants",
    )
    def list_participants(
        request: Request,
        conversation_id: str,
    ) -> Dict[str, Any]:
        user_id = _get_user_id(request)
        org_id = _get_org_id(request)
        parts = conversation_service.list_participants(
            conversation_id, org_id=org_id, user_id=user_id,
        )
        return {"items": [p.to_dict() for p in parts], "total": len(parts)}

    # =========================================================================
    # Pin
    # =========================================================================

    @router.put(
        "/v1/conversations/{conversation_id}/pin",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Pin message",
    )
    def pin_message(
        request: Request,
        body: PinMessageRequest,
        conversation_id: str,
    ) -> None:
        user_id = _get_user_id(request)
        org_id = _get_org_id(request)
        try:
            conversation_service.pin_message(
                conversation_id, body.message_id, user_id=user_id, org_id=org_id,
            )
        except (ConversationNotFoundError, MessageNotFoundError) as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except AccessDeniedError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    @router.delete(
        "/v1/conversations/{conversation_id}/pin",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Unpin message",
    )
    def unpin_message(
        request: Request,
        conversation_id: str,
    ) -> None:
        user_id = _get_user_id(request)
        org_id = _get_org_id(request)
        try:
            conversation_service.unpin_message(
                conversation_id, user_id=user_id, org_id=org_id,
            )
        except AccessDeniedError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    # =========================================================================
    # Search
    # =========================================================================

    @router.get(
        "/v1/conversations/{conversation_id}/search",
        response_model=SearchResultsResponse,
        summary="Search messages",
    )
    def search_messages(
        request: Request,
        conversation_id: str,
        q: str = Query(..., min_length=1, max_length=500, description="Search query"),
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> SearchResultsResponse:
        user_id = _get_user_id(request)
        org_id = _get_org_id(request)

        # Rate-limit full-text search (AMPREALIZE-593)
        try:
            rl.check(user_id, conversation_id, Lane.SEARCH)
        except RateLimitExceeded as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=str(exc),
                headers={"Retry-After": str(int(exc.wait_seconds) + 1)},
            ) from exc

        results, total = conversation_service.search_messages(
            conversation_id,
            query=q,
            user_id=user_id,
            org_id=org_id,
            limit=limit,
            offset=offset,
        )
        items = [
            SearchResult(
                message=_msg_to_response(msg),
                rank=rank,
                headline=headline,
            )
            for msg, rank, headline in results
        ]
        return SearchResultsResponse(items=items, total=total, query=q)

    return router
