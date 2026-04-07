"""MCP tool handlers for Config operations.

Provides handlers for configuration-related tools including model availability,
LLM connectors, and project settings.
Following `behavior_prefer_mcp_tools` - MCP provides consistent schemas and automatic telemetry.

See WORK_ITEM_EXECUTION_PLAN.md Section 11.6 for specification.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Callable

from ...work_item_execution_service import CredentialStore
from ...work_item_execution_contracts import AvailableModel, MODEL_CATALOG, LLMProvider


# ==============================================================================
# Serialization Helpers
# ==============================================================================


def _serialize_value(value: Any) -> Any:
    """Recursively serialize values for JSON output."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, 'value'):  # Enum
        return value.value
    if hasattr(value, 'model_dump'):  # Pydantic model
        return {k: _serialize_value(v) for k, v in value.model_dump().items()}
    if hasattr(value, '__dataclass_fields__'):  # Dataclass
        import dataclasses
        return {k: _serialize_value(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize_value(v) for v in value]
    return str(value)


def _available_model_to_dict(
    available: AvailableModel,
    include_pricing: bool = True,
) -> Dict[str, Any]:
    """Convert AvailableModel to response dict.

    Args:
        available: The AvailableModel instance
        include_pricing: Whether to include pricing fields

    Returns:
        Dict with model availability info
    """
    model = available.model
    result = {
        "model_id": model.model_id,
        "provider": model.provider.value if hasattr(model.provider, 'value') else str(model.provider),
        "display_name": model.display_name,
        "context_limit": model.context_limit,
        "max_output_tokens": model.max_output_tokens,
        "supports_tool_calls": model.supports_tool_calls,
        "credential_source": available.credential_source,
        "is_byok": available.is_byok,
    }

    if include_pricing:
        result["input_price_per_m"] = model.input_price_per_m
        result["output_price_per_m"] = model.output_price_per_m

    return result


# ==============================================================================
# Handler Functions
# ==============================================================================


def handle_get_model_availability(
    credential_store: CredentialStore,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Get available LLM models for a project.

    MCP Tool: config.getModelAvailability

    Returns models available based on credential resolution order:
    1. Project credential (BYOK) - highest priority
    2. Org credential (BYOK)
    3. Platform credential - admin-managed defaults

    Args:
        credential_store: The credential store service
        arguments: {
            "project_id": Required - project to check availability for
            "org_id": Optional - org ID for credential resolution
            "include_pricing": Optional - include pricing info (default: true)
            "provider_filter": Optional - filter by provider
        }

    Returns:
        {
            "project_id": str,
            "org_id": str | null,
            "models": [...],
            "total_count": int,
            "has_byok": bool
        }
    """
    project_id = arguments.get("project_id")
    if not project_id:
        raise KeyError("project_id")

    org_id = arguments.get("org_id")
    include_pricing = arguments.get("include_pricing", True)
    provider_filter = arguments.get("provider_filter")

    # Validate provider filter if provided
    if provider_filter:
        valid_providers = {"anthropic", "openai", "openrouter", "local"}
        if provider_filter not in valid_providers:
            raise ValueError(f"Invalid provider_filter: {provider_filter}. Must be one of: {', '.join(valid_providers)}")

    # Get available models from credential store
    available_models = credential_store.get_available_models(
        project_id=project_id,
        org_id=org_id,
    )

    # Apply provider filter if specified
    if provider_filter:
        try:
            filter_enum = LLMProvider(provider_filter)
            available_models = [
                m for m in available_models
                if m.model.provider == filter_enum
            ]
        except ValueError:
            # If enum conversion fails, compare as string
            available_models = [
                m for m in available_models
                if (m.model.provider.value if hasattr(m.model.provider, 'value') else str(m.model.provider)) == provider_filter
            ]

    # Convert to response format
    models = [
        _available_model_to_dict(m, include_pricing=include_pricing)
        for m in available_models
    ]

    # Calculate summary stats
    has_byok = any(m.is_byok for m in available_models)

    return {
        "project_id": project_id,
        "org_id": org_id,
        "models": models,
        "total_count": len(models),
        "has_byok": has_byok,
    }


def handle_list_llm_connectors(
    credential_store: CredentialStore,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    List configured LLM connectors/providers.

    MCP Tool: config.listLLMConnectors

    Returns summary of configured providers at platform/org/project levels.

    Args:
        credential_store: The credential store service
        arguments: {
            "project_id": Optional - project to check
            "org_id": Optional - org to check
        }

    Returns:
        {
            "connectors": [...],
            "total_count": int
        }
    """
    project_id = arguments.get("project_id")
    org_id = arguments.get("org_id")

    # Group available models by provider to get connector status
    available_models = credential_store.get_available_models(
        project_id=project_id,
        org_id=org_id,
    )

    # Build connector summary by provider
    connectors_by_provider: Dict[str, Dict[str, Any]] = {}

    for available in available_models:
        provider = available.model.provider.value if hasattr(available.model.provider, 'value') else str(available.model.provider)

        if provider not in connectors_by_provider:
            connectors_by_provider[provider] = {
                "provider": provider,
                "credential_source": available.credential_source,
                "is_byok": available.is_byok,
                "model_count": 0,
                "models": [],
            }

        connectors_by_provider[provider]["model_count"] += 1
        connectors_by_provider[provider]["models"].append(available.model.model_id)

        # BYOK at any level takes priority in the summary
        if available.is_byok:
            connectors_by_provider[provider]["is_byok"] = True
            # Show most specific credential source (project > org > platform)
            if available.credential_source == "project":
                connectors_by_provider[provider]["credential_source"] = "project"
            elif available.credential_source == "org" and connectors_by_provider[provider]["credential_source"] == "platform":
                connectors_by_provider[provider]["credential_source"] = "org"

    connectors = list(connectors_by_provider.values())

    return {
        "connectors": connectors,
        "total_count": len(connectors),
        "project_id": project_id,
        "org_id": org_id,
    }


# ==============================================================================
# Handler Registry
# ==============================================================================


# Maps MCP tool names to handler functions
CONFIG_HANDLERS: Dict[str, Callable[[CredentialStore, Dict[str, Any]], Dict[str, Any]]] = {
    "config.getModelAvailability": handle_get_model_availability,
    "config.listLLMConnectors": handle_list_llm_connectors,
}
