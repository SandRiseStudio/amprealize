"""Settings API routes — enterprise feature.

Full implementation available in amprealize-enterprise package.
Install: pip install amprealize-enterprise
"""

try:
    from amprealize_enterprise.multi_tenant.settings_api import create_settings_routes
    SETTINGS_ROUTES_AVAILABLE = True
except ImportError:
    SETTINGS_ROUTES_AVAILABLE = False

    def create_settings_routes(*args, **kwargs):
        """No-op: settings routes require amprealize-enterprise."""
        raise ImportError(
            "Settings API requires amprealize-enterprise. "
            "Install: pip install amprealize-enterprise"
        )

__all__ = ["create_settings_routes", "SETTINGS_ROUTES_AVAILABLE"]
