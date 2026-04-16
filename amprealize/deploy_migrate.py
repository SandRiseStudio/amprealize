"""Deploy migration — OSS stub (raise on call).

All deploy-migration functions are enterprise-only.  In the OSS edition
every function raises ``ImportError`` with a clear upgrade message.
The enterprise fork replaces this module with real implementations.
"""

from __future__ import annotations

from typing import Any

_ENTERPRISE_MSG = (
    "Deploy migration requires the enterprise edition. "
    "See https://amprealize.io/enterprise for details."
)


def export_data(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Export all data to a portable format. (Enterprise only.)"""
    raise ImportError(_ENTERPRISE_MSG)


def import_data(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Import data from a portable format. (Enterprise only.)"""
    raise ImportError(_ENTERPRISE_MSG)


def sync_to_cloud(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Sync local data to cloud. (Enterprise only.)"""
    raise ImportError(_ENTERPRISE_MSG)


def sync_from_cloud(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Sync cloud data to local. (Enterprise only.)"""
    raise ImportError(_ENTERPRISE_MSG)


def migrate_deployment(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Full deployment migration (local→cloud or cloud→local). (Enterprise only.)"""
    raise ImportError(_ENTERPRISE_MSG)
