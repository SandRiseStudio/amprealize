"""Organization management API routes — enterprise feature.

Full implementation lives in the enterprise fork.
"""

ORG_ROUTES_AVAILABLE = False


def create_org_routes(*args, **kwargs):
    """No-op: org management routes require enterprise fork."""
    raise ImportError(
        "Organization management API requires the enterprise fork."
    )

__all__ = ["create_org_routes", "ORG_ROUTES_AVAILABLE"]
