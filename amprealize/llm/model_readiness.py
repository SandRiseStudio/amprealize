"""Model readiness and shared chat LLM metadata validation.

Single source of truth for "can this conversation send with this model?" used by
REST, WebSocket, OpenAPI, and MCP config tooling.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from amprealize.llm.byok_policy import byok_persistence_status
from amprealize.llm.types import get_model
from amprealize.work_item_execution_contracts import AvailableModel
from amprealize.work_item_execution_service import CredentialStore

logger = logging.getLogger(__name__)


def _serialize_available_model(available: AvailableModel, *, include_pricing: bool = True) -> Dict[str, Any]:
    """Mirror ``config_handlers._available_model_to_dict`` without MCP-layer imports."""
    model = available.model
    result: Dict[str, Any] = {
        "model_id": model.model_id,
        "api_name": model.api_name,
        "provider": model.provider.value if hasattr(model.provider, "value") else str(model.provider),
        "display_name": model.display_name,
        "context_limit": model.context_limit,
        "max_output_tokens": model.max_output_tokens,
        "supports_tool_calls": model.supports_tool_calls,
        "supports_structured_output": model.metadata.get("supports_structured_output", False),
        "supports_reasoning_delta": model.metadata.get("supports_reasoning_delta", False),
        "supports_streaming": model.metadata.get("supports_streaming", True),
        "is_open_model": model.metadata.get("is_open_model", False),
        "is_default": model.metadata.get("is_default", False),
        "free_endpoint": model.metadata.get("free_endpoint", False),
        "credential_source": available.credential_source,
        "is_byok": available.is_byok,
    }
    if include_pricing:
        result["input_price_per_m"] = model.input_price_per_m
        result["output_price_per_m"] = model.output_price_per_m
    return result


def validate_and_enrich_chat_message_metadata(
    *,
    credential_store: CredentialStore,
    conversation: Any,
    user_id: str,
    effective_org_id: Optional[str],
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    """Validate ``metadata`` LLM fields and enrich with canonical model fields.

    Raises:
        ValueError: Invalid or unusable model metadata (REST maps to HTTP 400).
    """
    model_id = metadata.get("llm_model_id")
    provider = metadata.get("llm_provider")
    credential_scope = metadata.get("credential_scope")
    if model_id is None and provider is None and credential_scope is None:
        return metadata

    if not isinstance(model_id, str) or not model_id:
        raise ValueError("metadata.llm_model_id must be a non-empty string")

    model = get_model(model_id)
    if not model:
        raise ValueError(f"Unknown LLM model: {model_id}")
    if provider is not None and provider != model.provider.value:
        raise ValueError("metadata.llm_provider does not match metadata.llm_model_id")

    prefer_user = credential_scope == "user"
    credential = credential_store.get_credential_for_model(
        model_id,
        project_id=getattr(conversation, "project_id", None),
        org_id=effective_org_id,
        user_id=user_id,
        prefer_user=prefer_user,
    )
    if not credential:
        if credential_store.credential_blocked_by_invalid_scoped_byok(
            model_id,
            project_id=getattr(conversation, "project_id", None),
            org_id=effective_org_id,
            user_id=user_id,
            prefer_user=prefer_user,
        ):
            raise ValueError(
                f"BYOK credential for provider {model.provider.value} is configured but invalid "
                f"or locked; fix or remove it before using model {model_id}."
            )
        raise ValueError(f"Selected model is not available: {model_id}")

    _, resolved_scope, is_byok = credential
    enriched = dict(metadata)
    enriched["llm_model_id"] = model.model_id
    enriched["llm_model_api_name"] = model.api_name
    enriched["llm_provider"] = model.provider.value
    enriched["credential_scope"] = resolved_scope
    enriched["is_byok"] = is_byok
    return enriched


def _pick_suggested_model(models: List[AvailableModel]) -> Optional[str]:
    if not models:
        return None
    for m in models:
        if m.model.metadata.get("is_default"):
            return m.model.model_id
    return models[0].model.model_id


def compute_model_readiness_payload(
    credential_store: CredentialStore,
    *,
    user_id: str,
    org_id: Optional[str],
    project_id: Optional[str],
    prefer_user: bool = False,
    provider_filter: Optional[str] = None,
    free_open_only: bool = False,
    selected_model_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build API/MCP-ready readiness document for a credential context."""
    enc = byok_persistence_status()
    models = credential_store.get_available_models(
        project_id=project_id,
        org_id=org_id,
        user_id=user_id,
        prefer_user=prefer_user,
        provider_filter=provider_filter,
        free_open_only=free_open_only,
    )

    serialized = [_serialize_available_model(m, include_pricing=True) for m in models]
    suggested = _pick_suggested_model(models)

    state = "ready"
    detail: Optional[str] = None
    has_models = len(models) > 0
    can_send = has_models

    if not has_models:
        state = "no_model_available"
        can_send = False
        detail = "No LLM models are available for this context. Add a platform API key or BYOK credential."

    if selected_model_id:
        if not has_models:
            state = "needs_api_key"
            can_send = False
            detail = f"No models available; cannot use {selected_model_id}."
        else:
            cred = credential_store.get_credential_for_model(
                selected_model_id,
                project_id=project_id,
                org_id=org_id,
                user_id=user_id,
                prefer_user=prefer_user,
            )
            if not cred:
                if credential_store.credential_blocked_by_invalid_scoped_byok(
                    selected_model_id,
                    project_id=project_id,
                    org_id=org_id,
                    user_id=user_id,
                    prefer_user=prefer_user,
                ):
                    state = "invalid_key"
                    can_send = False
                    detail = (
                        "Scoped BYOK exists for this provider but cannot be used "
                        "(invalid, locked, or undecryptable)."
                    )
                else:
                    state = "needs_api_key"
                    can_send = False
                    detail = f"No usable credential for model {selected_model_id}."
            else:
                state = "ready"
                can_send = True

    if enc.get("reason") in ("encryption_required", "missing_fernet_key_production"):
        enc = {**enc, "readiness_note": enc.get("warning")}

    return {
        "state": state,
        "can_send": can_send,
        "detail": detail,
        "suggested_model_id": suggested,
        "selected_model_id": selected_model_id,
        "models": serialized,
        "total_count": len(serialized),
        "has_byok": any(m.is_byok for m in models),
        "encryption": enc,
        "project_id": project_id,
        "org_id": org_id,
        "user_id": user_id,
        "prefer_user": prefer_user,
    }
