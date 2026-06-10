"""MCP tool handlers for BehaviorService."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ...adapters import MCPBehaviorServiceAdapter
from ...behavior_service import BehaviorService

logger = logging.getLogger(__name__)


class BehaviorToolValidationError(ValueError):
    """Raised when a behavior MCP tool is missing required runtime arguments."""


def _require(arguments: Dict[str, Any], *fields: str) -> None:
    missing = [field for field in fields if not arguments.get(field)]
    if not missing:
        return
    label = "parameter" if len(missing) == 1 else "parameters"
    raise BehaviorToolValidationError(f"Missing required {label}: {', '.join(missing)}")


def _ensure_actor(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Default actor from injected session when callers omit actor."""
    if arguments.get("actor"):
        return arguments
    session = arguments.get("_session", {})
    arguments["actor"] = {
        "id": session.get("user_id") or session.get("service_principal_id") or "mcp-session",
        "role": "MCP",
        "surface": "MCP",
    }
    return arguments


async def handle_create(service: BehaviorService, arguments: Dict[str, Any]) -> Dict[str, Any]:
    _require(arguments, "name", "description", "instruction", "role_focus")
    return MCPBehaviorServiceAdapter(service).create(_ensure_actor(arguments))


async def handle_propose(service: BehaviorService, arguments: Dict[str, Any]) -> Dict[str, Any]:
    _require(arguments, "name", "description", "instruction", "role_focus", "confidence_score")
    return MCPBehaviorServiceAdapter(service).propose(_ensure_actor(arguments))


async def handle_list(service: BehaviorService, arguments: Dict[str, Any]) -> Dict[str, Any]:
    return MCPBehaviorServiceAdapter(service).list(arguments)


async def handle_search(service: BehaviorService, arguments: Dict[str, Any]) -> Dict[str, Any]:
    _require(arguments, "query")
    return MCPBehaviorServiceAdapter(service).search(_ensure_actor(arguments))


async def handle_get(service: BehaviorService, arguments: Dict[str, Any]) -> Dict[str, Any]:
    _require(arguments, "behavior_id")
    return MCPBehaviorServiceAdapter(service).get(arguments)


async def handle_get_for_task(
    service: BehaviorService,
    arguments: Dict[str, Any],
    *,
    run_service: Optional[Any] = None,
) -> Dict[str, Any]:
    out = MCPBehaviorServiceAdapter(service).get_for_task(_ensure_actor(arguments))
    refs = list(out.get("behavior_retrieval_refs") or [])
    from amprealize.knowledge_retrieval_receipt import spans_from_behavior_retrieval_refs

    spans = spans_from_behavior_retrieval_refs(refs, channel="mcp_behaviors_getForTask")
    out["retrieval_receipt"] = {"span_count": len(spans), "spans": spans}
    session = arguments.get("_session") if isinstance(arguments.get("_session"), dict) else {}
    run_id = session.get("run_id") or arguments.get("run_id")
    if run_service is not None and run_id and spans:
        try:
            run_service.append_knowledge_receipt_spans(str(run_id), spans)
            out["receipt_persisted"] = True
        except Exception as exc:  # pragma: no cover - persistence optional
            logger.debug("Knowledge receipt persist skipped: %s", exc)
            out["receipt_persisted"] = False
    else:
        out["receipt_persisted"] = False
    return out


async def handle_update(service: BehaviorService, arguments: Dict[str, Any]) -> Dict[str, Any]:
    _require(arguments, "behavior_id", "version")
    return MCPBehaviorServiceAdapter(service).update(_ensure_actor(arguments))


async def handle_submit(service: BehaviorService, arguments: Dict[str, Any]) -> Dict[str, Any]:
    _require(arguments, "behavior_id", "version")
    return MCPBehaviorServiceAdapter(service).submit(_ensure_actor(arguments))


async def handle_approve(service: BehaviorService, arguments: Dict[str, Any]) -> Dict[str, Any]:
    _require(arguments, "behavior_id", "version", "effective_from")
    return MCPBehaviorServiceAdapter(service).approve(_ensure_actor(arguments))


async def handle_deprecate(service: BehaviorService, arguments: Dict[str, Any]) -> Dict[str, Any]:
    _require(arguments, "behavior_id", "version", "effective_to")
    return MCPBehaviorServiceAdapter(service).deprecate(_ensure_actor(arguments))


async def handle_delete_draft(service: BehaviorService, arguments: Dict[str, Any]) -> Dict[str, Any]:
    _require(arguments, "behavior_id", "version")
    adapter = MCPBehaviorServiceAdapter(service)
    adapter.delete_draft(_ensure_actor(arguments))
    return {
        "success": True,
        "message": f"Draft {arguments['behavior_id']} v{arguments['version']} deleted",
    }


BEHAVIOR_HANDLERS = {
    "behaviors.create": handle_create,
    "behaviors.propose": handle_propose,
    "behaviors.list": handle_list,
    "behaviors.search": handle_search,
    "behaviors.get": handle_get,
    "behaviors.getForTask": handle_get_for_task,
    "behaviors.update": handle_update,
    "behaviors.submit": handle_submit,
    "behaviors.approve": handle_approve,
    "behaviors.deprecate": handle_deprecate,
    "behaviors.deleteDraft": handle_delete_draft,
}
