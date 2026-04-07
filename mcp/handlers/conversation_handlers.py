"""MCP handlers for conversations/messaging (AMPREALIZE-573).

Follows the board_handlers.py pattern:
- Sync handler functions taking (service, arguments)
- Returns Dict[str, Any] with success/error
- Handler registry dicts exported for dispatch
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from amprealize.conversation_contracts import ConversationScope, MessageType
from amprealize.services.conversation_service import (
    AccessDeniedError,
    ConversationNotFoundError,
    ConversationService,
    ConversationServiceError,
    DuplicateReactionError,
    EditWindowClosedError,
    MessageNotFoundError,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Helpers
# ============================================================================

def _serialize_value(value: Any) -> Any:
    """Recursively serialize values for JSON output."""
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "to_dict"):
        return _serialize_dict(value.to_dict())
    if hasattr(value, "model_dump"):
        return _serialize_dict(value.model_dump())
    if isinstance(value, dict):
        return _serialize_dict(value)
    if isinstance(value, (list, tuple)):
        return [_serialize_value(v) for v in value]
    if hasattr(value, "value"):  # Enum
        return value.value
    return value


def _serialize_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: _serialize_value(v) for k, v in d.items()}


def _get_user_id(arguments: Dict[str, Any]) -> str:
    return arguments.get("user_id", "mcp-user")


def _get_org_id(arguments: Dict[str, Any]) -> Optional[str]:
    return arguments.get("org_id")


# ============================================================================
# Conversation Handlers
# ============================================================================

def handle_create_conversation(
    service: ConversationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """MCP Tool: conversations.create"""
    project_id = arguments.get("project_id")
    if not project_id:
        return {"success": False, "error": "project_id is required"}

    scope_str = arguments.get("scope", "project_room")
    try:
        scope = ConversationScope(scope_str)
    except ValueError:
        return {"success": False, "error": f"Invalid scope: {scope_str}"}

    user_id = _get_user_id(arguments)
    org_id = _get_org_id(arguments)

    try:
        conv = service.create_conversation(
            project_id=project_id,
            scope=scope,
            title=arguments.get("title"),
            created_by=user_id,
            participant_ids=arguments.get("participant_ids"),
            org_id=org_id,
        )
        return {
            "success": True,
            "conversation": _serialize_dict(conv.to_dict()),
            "message": f"Conversation created in project {project_id}",
        }
    except ConversationServiceError as exc:
        return {"success": False, "error": str(exc)}


def handle_list_conversations(
    service: ConversationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """MCP Tool: conversations.list"""
    project_id = arguments.get("project_id")
    if not project_id:
        return {"success": False, "error": "project_id is required"}

    user_id = _get_user_id(arguments)
    org_id = _get_org_id(arguments)
    scope_str = arguments.get("scope")
    scope = ConversationScope(scope_str) if scope_str else None

    convs, total = service.list_conversations(
        project_id=project_id,
        user_id=user_id,
        org_id=org_id,
        scope=scope,
        include_archived=arguments.get("include_archived", False),
        limit=arguments.get("limit", 50),
        offset=arguments.get("offset", 0),
    )
    return {
        "success": True,
        "conversations": [_serialize_dict(c.to_dict()) for c in convs],
        "total": total,
    }


def handle_get_conversation(
    service: ConversationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """MCP Tool: conversations.get"""
    conversation_id = arguments.get("conversation_id")
    if not conversation_id:
        return {"success": False, "error": "conversation_id is required"}

    try:
        conv = service.get_conversation(
            conversation_id,
            org_id=_get_org_id(arguments),
            user_id=_get_user_id(arguments),
        )
        return {"success": True, "conversation": _serialize_dict(conv.to_dict())}
    except ConversationNotFoundError as exc:
        return {"success": False, "error": str(exc)}


def handle_archive_conversation(
    service: ConversationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """MCP Tool: conversations.archive"""
    conversation_id = arguments.get("conversation_id")
    if not conversation_id:
        return {"success": False, "error": "conversation_id is required"}

    try:
        service.archive_conversation(
            conversation_id,
            user_id=_get_user_id(arguments),
            org_id=_get_org_id(arguments),
        )
        return {"success": True, "message": f"Conversation {conversation_id} archived"}
    except ConversationNotFoundError as exc:
        return {"success": False, "error": str(exc)}
    except AccessDeniedError as exc:
        return {"success": False, "error": str(exc)}


# ============================================================================
# Message Handlers
# ============================================================================

def handle_send_message(
    service: ConversationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """MCP Tool: messages.send"""
    conversation_id = arguments.get("conversation_id")
    content = arguments.get("content")
    if not conversation_id:
        return {"success": False, "error": "conversation_id is required"}
    if not content:
        return {"success": False, "error": "content is required"}

    msg_type_str = arguments.get("message_type", "text")
    try:
        msg_type = MessageType(msg_type_str)
    except ValueError:
        return {"success": False, "error": f"Invalid message_type: {msg_type_str}"}

    try:
        msg = service.send_message(
            conversation_id,
            sender_id=_get_user_id(arguments),
            content=content,
            message_type=msg_type,
            structured_payload=arguments.get("structured_payload"),
            parent_id=arguments.get("parent_id"),
            run_id=arguments.get("run_id"),
            behavior_id=arguments.get("behavior_id"),
            work_item_id=arguments.get("work_item_id"),
            metadata=arguments.get("metadata"),
            org_id=_get_org_id(arguments),
        )
        return {
            "success": True,
            "message": _serialize_dict(msg.to_dict()),
        }
    except AccessDeniedError as exc:
        return {"success": False, "error": str(exc)}
    except MessageNotFoundError as exc:
        return {"success": False, "error": str(exc)}


def handle_list_messages(
    service: ConversationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """MCP Tool: messages.list"""
    conversation_id = arguments.get("conversation_id")
    if not conversation_id:
        return {"success": False, "error": "conversation_id is required"}

    msgs, total, has_more = service.list_messages(
        conversation_id,
        user_id=_get_user_id(arguments),
        org_id=_get_org_id(arguments),
        parent_id=arguments.get("parent_id"),
        limit=arguments.get("limit", 50),
        offset=arguments.get("offset", 0),
    )
    return {
        "success": True,
        "messages": [_serialize_dict(m.to_dict()) for m in msgs],
        "total": total,
        "has_more": has_more,
    }


def handle_get_message(
    service: ConversationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """MCP Tool: messages.get"""
    message_id = arguments.get("message_id")
    if not message_id:
        return {"success": False, "error": "message_id is required"}

    try:
        msg = service.get_message(
            message_id,
            org_id=_get_org_id(arguments),
            user_id=_get_user_id(arguments),
        )
        return {"success": True, "message": _serialize_dict(msg.to_dict())}
    except MessageNotFoundError as exc:
        return {"success": False, "error": str(exc)}


def handle_edit_message(
    service: ConversationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """MCP Tool: messages.edit"""
    message_id = arguments.get("message_id")
    content = arguments.get("content")
    if not message_id:
        return {"success": False, "error": "message_id is required"}
    if not content:
        return {"success": False, "error": "content is required"}

    try:
        msg = service.edit_message(
            message_id,
            new_content=content,
            editor_id=_get_user_id(arguments),
            org_id=_get_org_id(arguments),
        )
        return {"success": True, "message": _serialize_dict(msg.to_dict())}
    except MessageNotFoundError as exc:
        return {"success": False, "error": str(exc)}
    except AccessDeniedError as exc:
        return {"success": False, "error": str(exc)}
    except EditWindowClosedError as exc:
        return {"success": False, "error": str(exc)}


def handle_delete_message(
    service: ConversationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """MCP Tool: messages.delete"""
    message_id = arguments.get("message_id")
    if not message_id:
        return {"success": False, "error": "message_id is required"}

    try:
        service.delete_message(
            message_id,
            deleter_id=_get_user_id(arguments),
            org_id=_get_org_id(arguments),
        )
        return {"success": True, "message": f"Message {message_id} deleted"}
    except MessageNotFoundError as exc:
        return {"success": False, "error": str(exc)}
    except AccessDeniedError as exc:
        return {"success": False, "error": str(exc)}


def handle_search_messages(
    service: ConversationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """MCP Tool: messages.search"""
    conversation_id = arguments.get("conversation_id")
    query = arguments.get("query")
    if not conversation_id:
        return {"success": False, "error": "conversation_id is required"}
    if not query:
        return {"success": False, "error": "query is required"}

    results, total = service.search_messages(
        conversation_id,
        query=query,
        user_id=_get_user_id(arguments),
        org_id=_get_org_id(arguments),
        limit=arguments.get("limit", 20),
        offset=arguments.get("offset", 0),
    )
    items = []
    for msg, rank, headline in results:
        items.append({
            "message": _serialize_dict(msg.to_dict()),
            "rank": rank,
            "headline": headline,
        })
    return {
        "success": True,
        "results": items,
        "total": total,
        "query": query,
    }


# ============================================================================
# Reaction Handlers
# ============================================================================

def handle_add_reaction(
    service: ConversationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """MCP Tool: messages.addReaction"""
    message_id = arguments.get("message_id")
    emoji = arguments.get("emoji")
    if not message_id:
        return {"success": False, "error": "message_id is required"}
    if not emoji:
        return {"success": False, "error": "emoji is required"}

    try:
        reaction = service.add_reaction(
            message_id,
            actor_id=_get_user_id(arguments),
            emoji=emoji,
            org_id=_get_org_id(arguments),
        )
        return {"success": True, "reaction": _serialize_dict(reaction.to_dict())}
    except MessageNotFoundError as exc:
        return {"success": False, "error": str(exc)}
    except DuplicateReactionError as exc:
        return {"success": False, "error": str(exc)}


def handle_remove_reaction(
    service: ConversationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """MCP Tool: messages.removeReaction"""
    message_id = arguments.get("message_id")
    emoji = arguments.get("emoji")
    if not message_id:
        return {"success": False, "error": "message_id is required"}
    if not emoji:
        return {"success": False, "error": "emoji is required"}

    service.remove_reaction(
        message_id,
        actor_id=_get_user_id(arguments),
        emoji=emoji,
        org_id=_get_org_id(arguments),
    )
    return {"success": True, "message": f"Reaction '{emoji}' removed"}


# ============================================================================
# Reply Generation Handlers (async)
# ============================================================================

async def handle_generate_reply(
    service: ConversationService,
    arguments: Dict[str, Any],
    *,
    reply_service: Optional[Any] = None,
) -> Dict[str, Any]:
    """MCP Tool: messages.generateReply

    Generates an AI-powered agent reply using ContextComposer for
    context-aware response generation.

    Args:
        service: ConversationService for message lookup
        arguments: MCP tool arguments
        reply_service: ConversationReplyService for generation

    Returns:
        Dict with generated message or error
    """
    conversation_id = arguments.get("conversation_id")
    user_message_id = arguments.get("user_message_id")

    if not conversation_id:
        return {"success": False, "error": "conversation_id is required"}
    if not user_message_id:
        return {"success": False, "error": "user_message_id is required"}

    if reply_service is None:
        return {
            "success": False,
            "error": "Reply service not configured - agent replies disabled",
        }

    # Get the user message content
    try:
        user_message = service.get_message(
            user_message_id,
            org_id=_get_org_id(arguments),
            user_id=_get_user_id(arguments),
        )
    except MessageNotFoundError as exc:
        return {"success": False, "error": str(exc)}

    # Import here to avoid circular imports
    from amprealize.services.conversation_reply_service import ReplyRequest

    request = ReplyRequest(
        conversation_id=conversation_id,
        user_message_id=user_message_id,
        user_message_content=user_message.content,
        user_id=_get_user_id(arguments),
        agent_id=arguments.get("agent_id", "amprealize-agent"),
        work_item_id=arguments.get("work_item_id"),
        run_id=arguments.get("run_id"),
        org_id=_get_org_id(arguments),
        project_id=arguments.get("project_id"),
        system_prompt_override=arguments.get("system_prompt"),
        metadata=arguments.get("metadata", {}),
    )

    try:
        result = await reply_service.generate_reply(request)

        if not result.success:
            return {"success": False, "error": result.error}

        return {
            "success": True,
            "message_id": result.message_id,
            "content": result.content,
            "conversation_id": result.conversation_id,
            "context": {
                "tokens_used": result.composed_context.total_tokens,
                "sources_included": result.composed_context.sources_included,
                "budget_used": result.composed_context.budget_used,
            },
            "latency_ms": result.latency_ms,
        }
    except Exception as exc:
        logger.error(f"Reply generation failed: {exc}", exc_info=True)
        return {"success": False, "error": str(exc)}


# ============================================================================
# Handler Registries
# ============================================================================

CONVERSATION_HANDLERS = {
    "conversations.create": handle_create_conversation,
    "conversations.list": handle_list_conversations,
    "conversations.get": handle_get_conversation,
    "conversations.archive": handle_archive_conversation,
}

MESSAGE_HANDLERS = {
    "messages.send": handle_send_message,
    "messages.list": handle_list_messages,
    "messages.get": handle_get_message,
    "messages.edit": handle_edit_message,
    "messages.delete": handle_delete_message,
    "messages.search": handle_search_messages,
    "messages.addReaction": handle_add_reaction,
    "messages.removeReaction": handle_remove_reaction,
}

# Async handlers that require special dispatch
ASYNC_MESSAGE_HANDLERS = {
    "messages.generateReply": handle_generate_reply,
}
