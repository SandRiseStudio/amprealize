"""Conversation REST API routes (AMPREALIZE-571).

Provides REST endpoints for the messaging system.
Follows the board_api_v2.py factory pattern.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request, status

from amprealize.conversation_contracts import (
    ConversationListResponse,
    ConversationResponse,
    ConversationScope,
    CreateConversationRequest,
    DirectConversationRequest,
    DirectConversationResponse,
    EditMessageRequest,
    MessageListResponse,
    MessageResponse,
    PinMessageRequest,
    SearchResult,
    SearchResultsResponse,
    SendMessageRequest,
    UpdateParticipantRequest,
)
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
        scope: Optional[str] = Query(default=None, description="Filter by scope"),
        include_archived: bool = Query(default=False),
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> ConversationListResponse:
        user_id = _get_user_id(request)
        org_id = _get_org_id(request)
        scope_enum = ConversationScope(scope) if scope else None
        convs, total = conversation_service.list_conversations(
            project_id=project_id,
            user_id=user_id,
            org_id=org_id,
            scope=scope_enum,
            include_archived=include_archived,
            limit=limit,
            offset=offset,
        )
        return ConversationListResponse(
            items=[_conv_to_response(c) for c in convs],
            total=total,
        )

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
    def send_message(
        request: Request,
        body: SendMessageRequest,
        conversation_id: str,
    ) -> MessageResponse:
        user_id = _get_user_id(request)
        org_id = _get_org_id(request)

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
                metadata=body.metadata,
                org_id=org_id,
            )

            # Record agent message for circuit breaker tracking
            if is_agent:
                cb.record_agent_message(conversation_id, user_id)

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
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> MessageListResponse:
        user_id = _get_user_id(request)
        org_id = _get_org_id(request)
        msgs, total, has_more = conversation_service.list_messages(
            conversation_id,
            user_id=user_id,
            org_id=org_id,
            parent_id=parent_id,
            limit=limit,
            offset=offset,
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
