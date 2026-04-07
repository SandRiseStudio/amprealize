"""ConversationReplyService — Orchestrates agent replies in conversations.

This service bridges the conversation system with AI-powered response generation:
1. Receives user message context
2. Calls ContextComposer to assemble relevant context
3. Invokes LLM to generate response with composed context
4. Stores agent reply via ConversationService
5. Emits token stream via ConversationEventHub for SSE

Flow:
    User message -> ContextComposer.compose() -> LLM call -> ConversationService.send_message()

AMPREALIZE-581: Integrate ContextComposer with agent execution loop for conversation replies.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional

from amprealize.context_composer import ContextComposer, ComposedContext
from amprealize.conversation_contracts import ActorType, MessageType
from amprealize.conversation_event_hub import (
    EVENT_COMPLETE,
    EVENT_ERROR,
    EVENT_TOKEN,
    ConversationEventHub,
)

logger = logging.getLogger(__name__)


@dataclass
class ReplyRequest:
    """Request to generate an agent reply in a conversation."""

    conversation_id: str
    """ID of the conversation where the agent should reply."""

    user_message_id: str
    """ID of the user message being replied to."""

    user_message_content: str
    """Content of the user message (used for relevance scoring)."""

    user_id: str
    """ID of the user who sent the message."""

    agent_id: str = "amprealize-agent"
    """ID of the agent generating the reply."""

    work_item_id: Optional[str] = None
    """Optional work item context."""

    run_id: Optional[str] = None
    """Optional run context."""

    org_id: Optional[str] = None
    """Organization ID for multi-tenant isolation."""

    project_id: Optional[str] = None
    """Project ID for context scoping."""

    system_prompt_override: Optional[str] = None
    """Optional override for the system prompt."""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """Additional metadata for the reply."""


@dataclass
class ReplyResult:
    """Result of generating an agent reply."""

    message_id: str
    """ID of the generated message."""

    content: str
    """Generated reply content."""

    conversation_id: str
    """Conversation where the reply was posted."""

    composed_context: ComposedContext
    """Context that was composed for generation."""

    token_count: int
    """Number of tokens in the generated response."""

    latency_ms: float
    """Total latency in milliseconds."""

    success: bool = True
    """Whether the reply was successful."""

    error: Optional[str] = None
    """Error message if failed."""


class ConversationReplyService:
    """Orchestrates context-aware agent replies in conversations.

    This service integrates:
    - ContextComposer: Assembles project context for grounding
    - LLM Client: Generates responses
    - ConversationService: Persists messages
    - ConversationEventHub: Streams tokens via SSE
    """

    # Default system prompt for conversational replies
    DEFAULT_SYSTEM_PROMPT = """You are a helpful AI assistant with full context about the user's project.

Use the provided context to give accurate, relevant answers:
- Reference specific work items, runs, or conversations when relevant
- If you cite information from the context, mention the source
- If the question is about something not in the context, say so
- Keep responses concise but thorough

{context}"""

    def __init__(
        self,
        *,
        context_composer: Optional[ContextComposer] = None,
        conversation_service: Optional[Any] = None,  # ConversationService
        llm_client: Optional[Any] = None,  # LLMClient
        event_hub: Optional[ConversationEventHub] = None,
        telemetry: Optional[Any] = None,
    ):
        """Initialize ConversationReplyService.

        Args:
            context_composer: Composer for assembling context
            conversation_service: Service for message CRUD
            llm_client: Client for LLM calls
            event_hub: Hub for token streaming events
            telemetry: Telemetry client
        """
        self._composer = context_composer or ContextComposer()
        self._conversation_service = conversation_service
        self._llm_client = llm_client
        self._event_hub = event_hub
        self._telemetry = telemetry

    def set_llm_client(self, client: Any) -> None:
        """Set the LLM client (avoids circular import)."""
        self._llm_client = client

    def set_conversation_service(self, service: Any) -> None:
        """Set the conversation service."""
        self._conversation_service = service

    async def generate_reply(
        self,
        request: ReplyRequest,
    ) -> ReplyResult:
        """Generate and store an agent reply in a conversation.

        Flow:
        1. Compose context via ContextComposer
        2. Build LLM messages with context
        3. Call LLM and stream tokens
        4. Store completed reply via ConversationService

        Args:
            request: Reply request with conversation context

        Returns:
            ReplyResult with generated message details
        """
        t_start = time.monotonic()
        message_id = f"msg-{uuid.uuid4().hex[:12]}"

        try:
            # Step 1: Compose context
            composed = await self._composer.compose(
                conversation_id=request.conversation_id,
                user_id=request.user_id,
                query=request.user_message_content,
                work_item_id=request.work_item_id,
                run_id=request.run_id,
            )

            logger.info(
                f"Composed context for reply: {composed.total_tokens} tokens, "
                f"{len(composed.sources_included)} sources"
            )

            # Step 2: Build LLM messages
            system_prompt = (
                request.system_prompt_override
                or self.DEFAULT_SYSTEM_PROMPT.format(context=composed.composed_text)
            )

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": request.user_message_content},
            ]

            # Step 3: Generate response
            if self._llm_client is None:
                raise RuntimeError("LLM client not configured")

            response_content = await self._generate_with_streaming(
                messages=messages,
                conversation_id=request.conversation_id,
                message_id=message_id,
            )

            # Step 4: Store the reply
            if self._conversation_service is not None:
                self._conversation_service.send_message(
                    request.conversation_id,
                    sender_id=request.agent_id,
                    content=response_content,
                    message_type=MessageType.TEXT,
                    parent_id=request.user_message_id,
                    run_id=request.run_id,
                    work_item_id=request.work_item_id,
                    metadata={
                        **request.metadata,
                        "generated": True,
                        "composed_context_tokens": composed.total_tokens,
                        "sources_used": composed.sources_included,
                    },
                    org_id=request.org_id,
                    actor_type=ActorType.AGENT,
                )

            latency_ms = (time.monotonic() - t_start) * 1000

            # Emit telemetry
            if self._telemetry:
                self._telemetry.emit_event(
                    event_type="conversation_reply.generated",
                    payload={
                        "conversation_id": request.conversation_id,
                        "message_id": message_id,
                        "agent_id": request.agent_id,
                        "context_tokens": composed.total_tokens,
                        "response_length": len(response_content),
                        "latency_ms": latency_ms,
                        "sources_count": len(composed.sources_included),
                    },
                )

            return ReplyResult(
                message_id=message_id,
                content=response_content,
                conversation_id=request.conversation_id,
                composed_context=composed,
                token_count=len(response_content.split()),  # Rough estimate
                latency_ms=latency_ms,
            )

        except Exception as exc:
            logger.error(f"Failed to generate reply: {exc}", exc_info=True)
            latency_ms = (time.monotonic() - t_start) * 1000

            # Emit error event to SSE
            if self._event_hub:
                await self._event_hub.publish(
                    event_type=EVENT_ERROR,
                    conversation_id=request.conversation_id,
                    payload={
                        "message_id": message_id,
                        "error": str(exc),
                    },
                )

            return ReplyResult(
                message_id=message_id,
                content="",
                conversation_id=request.conversation_id,
                composed_context=ComposedContext(
                    composed_text="",
                    total_tokens=0,
                    sources_included=[],
                    sources_excluded=[],
                    budget_used={},
                    budget_remaining={},
                    elapsed_ms=0.0,
                ),
                token_count=0,
                latency_ms=latency_ms,
                success=False,
                error=str(exc),
            )

    async def _generate_with_streaming(
        self,
        messages: List[Dict[str, str]],
        conversation_id: str,
        message_id: str,
    ) -> str:
        """Generate LLM response with optional token streaming.

        Args:
            messages: Chat messages for LLM
            conversation_id: For event routing
            message_id: For event routing

        Returns:
            Complete generated text
        """
        # Check if LLM client supports streaming
        if hasattr(self._llm_client, "stream"):
            tokens = []
            async for token in self._llm_client.stream(messages):
                tokens.append(token)

                # Broadcast token via event hub
                if self._event_hub:
                    await self._event_hub.publish(
                        event_type=EVENT_TOKEN,
                        conversation_id=conversation_id,
                        payload={
                            "message_id": message_id,
                            "token": token,
                        },
                    )

            content = "".join(tokens)

        else:
            # Non-streaming fallback
            response = self._llm_client.call(messages)
            content = response.content if hasattr(response, "content") else str(response)

        # Publish completion event
        if self._event_hub:
            await self._event_hub.publish(
                event_type=EVENT_COMPLETE,
                conversation_id=conversation_id,
                payload={
                    "message_id": message_id,
                    "content": content,
                },
            )

        return content

    async def generate_reply_stream(
        self,
        request: ReplyRequest,
    ) -> AsyncGenerator[str, None]:
        """Generate reply as an async token stream.

        Yields tokens as they are generated. Useful for direct SSE streaming
        without going through ConversationEventHub.

        Args:
            request: Reply request

        Yields:
            Generated tokens
        """
        # Compose context
        composed = await self._composer.compose(
            conversation_id=request.conversation_id,
            user_id=request.user_id,
            query=request.user_message_content,
            work_item_id=request.work_item_id,
            run_id=request.run_id,
        )

        # Build messages
        system_prompt = (
            request.system_prompt_override
            or self.DEFAULT_SYSTEM_PROMPT.format(context=composed.composed_text)
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": request.user_message_content},
        ]

        if self._llm_client is None:
            raise RuntimeError("LLM client not configured")

        # Stream tokens
        if hasattr(self._llm_client, "stream"):
            async for token in self._llm_client.stream(messages):
                yield token
        else:
            # Non-streaming fallback - yield entire response
            response = self._llm_client.call(messages)
            content = response.content if hasattr(response, "content") else str(response)
            yield content


__all__ = [
    "ConversationReplyService",
    "ReplyRequest",
    "ReplyResult",
]
