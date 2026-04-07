"""Organization service — enterprise feature.

Full implementation available in amprealize-enterprise package.
Install: pip install amprealize-enterprise
"""

try:
    from amprealize_enterprise.multi_tenant.organization_service import OrganizationService
except ImportError:
    OrganizationService = None

__all__ = ["OrganizationService"]
