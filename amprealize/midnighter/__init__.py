"""Amprealize Midnighter Integration.

Provides stubs for the Midnighter scheduler.  The enterprise edition
replaces this module with BC-SFT training integration.
"""


def create_midnighter_service(**kwargs):
    """Create a Midnighter service. Returns None in OSS."""
    return None


MidnighterService = None
MidnighterHooks = None

__all__ = [
    "create_midnighter_service",
    "MidnighterService",
    "MidnighterHooks",
]
