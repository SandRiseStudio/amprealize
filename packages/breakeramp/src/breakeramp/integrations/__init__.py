"""BreakerAmp integrations for web frameworks.

This module provides optional integrations for popular web frameworks,
allowing easy embedding of BreakerAmp functionality into existing applications.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .fastapi import create_breakeramp_routes

__all__ = ["create_breakeramp_routes"]
