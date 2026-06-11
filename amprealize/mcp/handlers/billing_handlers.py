"""MCP tool handlers for BillingService.

Provides handlers for subscription and billing management.
Following `behavior_prefer_mcp_tools` - MCP provides consistent schemas and automatic telemetry.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, TYPE_CHECKING
# NOTE: Billing objects may be Pydantic models - use .model_dump() not asdict()

if TYPE_CHECKING:
    from billing.service import BillingService


# Marker for handler discovery
_handler_module_stub = True


# ==============================================================================
# Serialization Helpers
# ==============================================================================


def _serialize_value(value: Any) -> Any:
    """Recursively serialize values for JSON output."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, 'value'):  # Enum
        return value.value
    if hasattr(value, 'model_dump'):  # Pydantic model
        return {k: _serialize_value(v) for k, v in value.model_dump().items()}
    if isinstance(value, list):
        return [_serialize_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    return value


# ==============================================================================
# Billing Handlers
# ==============================================================================


async def handle_get_subscription(
    service: BillingService,
    arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """Get subscription details for an organization."""
    user_id = arguments["user_id"]
    org_id = arguments["org_id"]

    subscription = await service.get_subscription(
        user_id=user_id,
        org_id=org_id,
    )

    if not subscription:
        return {
            "success": True,
            "subscription": None,
            "message": "No active subscription",
        }

    return {
        "success": True,
        "subscription": _serialize_value(subscription),
    }


async def handle_get_usage(
    service: BillingService,
    arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """Get usage metrics for the current billing period."""
    user_id = arguments["user_id"]
    org_id = arguments["org_id"]
    period = arguments.get("period", "current")

    usage = await service.get_usage(
        user_id=user_id,
        org_id=org_id,
        period=period,
    )

    return {
        "success": True,
        "usage": _serialize_value(usage),
        "period": period,
    }


async def handle_get_limits(
    service: BillingService,
    arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """Get plan limits for an organization."""
    user_id = arguments["user_id"]
    org_id = arguments["org_id"]

    limits = await service.get_limits(
        user_id=user_id,
        org_id=org_id,
    )

    return {
        "success": True,
        "limits": _serialize_value(limits),
    }


async def handle_check_limit(
    service: BillingService,
    arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """Check if a specific limit would be exceeded."""
    user_id = arguments["user_id"]
    org_id = arguments["org_id"]
    limit_type = arguments["limit_type"]
    requested_amount = arguments.get("requested_amount", 1)

    result = await service.check_limit(
        user_id=user_id,
        org_id=org_id,
        limit_type=limit_type,
        requested_amount=requested_amount,
    )

    return {
        "success": True,
        "allowed": result.get("allowed", False),
        "current_usage": result.get("current_usage", 0),
        "limit": result.get("limit", 0),
        "remaining": result.get("remaining", 0),
        "message": result.get("message"),
    }


async def handle_get_invoices(
    service: BillingService,
    arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """Get invoice history for an organization."""
    user_id = arguments["user_id"]
    org_id = arguments["org_id"]
    limit = arguments.get("limit", 10)
    starting_after = arguments.get("starting_after")

    invoices = await service.get_invoices(
        user_id=user_id,
        org_id=org_id,
        limit=limit,
        starting_after=starting_after,
    )

    return {
        "success": True,
        "invoices": [_serialize_value(inv) for inv in invoices],
        "count": len(invoices),
    }


async def handle_create_checkout_session(
    service: BillingService,
    arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """Create a Stripe checkout session for subscription."""
    user_id = arguments["user_id"]
    org_id = arguments["org_id"]
    plan = arguments["plan"]
    success_url = arguments["success_url"]
    cancel_url = arguments["cancel_url"]

    session = await service.create_checkout_session(
        user_id=user_id,
        org_id=org_id,
        plan=plan,
        success_url=success_url,
        cancel_url=cancel_url,
    )

    return {
        "success": True,
        "session_id": session.get("session_id"),
        "url": session.get("url"),
        "message": "Checkout session created",
    }


async def handle_create_portal_session(
    service: BillingService,
    arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """Create a Stripe billing portal session."""
    user_id = arguments["user_id"]
    org_id = arguments["org_id"]
    return_url = arguments["return_url"]

    session = await service.create_portal_session(
        user_id=user_id,
        org_id=org_id,
        return_url=return_url,
    )

    return {
        "success": True,
        "url": session.get("url"),
        "message": "Billing portal session created",
    }


async def handle_cancel_subscription(
    service: BillingService,
    arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """Cancel an organization's subscription."""
    user_id = arguments["user_id"]
    org_id = arguments["org_id"]
    at_period_end = arguments.get("at_period_end", True)
    reason = arguments.get("reason")

    result = await service.cancel_subscription(
        user_id=user_id,
        org_id=org_id,
        at_period_end=at_period_end,
        reason=reason,
    )

    return {
        "success": True,
        "cancel_at": result.get("cancel_at"),
        "message": "Subscription scheduled for cancellation" if at_period_end else "Subscription cancelled immediately",
    }


# ==============================================================================
# Handler Registry
# ==============================================================================


BILLING_HANDLERS: Dict[str, Any] = {
    "billing.getSubscription": handle_get_subscription,
    "billing.getUsage": handle_get_usage,
    "billing.getLimits": handle_get_limits,
    "billing.checkLimit": handle_check_limit,
    "billing.getInvoices": handle_get_invoices,
    "billing.createCheckoutSession": handle_create_checkout_session,
    "billing.createPortalSession": handle_create_portal_session,
    "billing.cancelSubscription": handle_cancel_subscription,
}
