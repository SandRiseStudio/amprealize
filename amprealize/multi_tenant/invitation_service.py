"""Invitation service — enterprise feature.

Full implementation available in amprealize-enterprise package.
Install: pip install amprealize-enterprise
"""

try:
    from amprealize_enterprise.multi_tenant.invitation_service import InvitationService
except ImportError:
    InvitationService = None

__all__ = ["InvitationService"]
