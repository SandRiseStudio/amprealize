"""Settings API routes — enterprise feature.

Full implementation lives in the enterprise fork.
"""

SETTINGS_ROUTES_AVAILABLE = False


def create_settings_routes(*args, **kwargs):
    """No-op: settings routes require enterprise fork."""
    raise ImportError(
        "Settings API requires the enterprise fork."
    )

__all__ = ["create_settings_routes", "SETTINGS_ROUTES_AVAILABLE"]
