"""Deploy migration — OSS stub (Pattern 3: raise on call).

The real export/import/sync implementation lives in
``amprealize_enterprise.deploy_migrate``. This stub raises a clear
``ImportError`` when any function is called in the OSS edition.

Part of Phase 1 of GUIDEAI-619 (Modular Installation System v3).
"""

from __future__ import annotations

_ENTERPRISE_MSG = (
    "Deploy migration requires amprealize-enterprise. "
    "Install with: pip install amprealize-enterprise"
)


def export_data(*args: object, **kwargs: object) -> None:
    """Export all data to a portable format. (Enterprise only.)"""
    raise ImportError(_ENTERPRISE_MSG)


def import_data(*args: object, **kwargs: object) -> None:
    """Import data from a portable format. (Enterprise only.)"""
    raise ImportError(_ENTERPRISE_MSG)


def sync_to_cloud(*args: object, **kwargs: object) -> None:
    """Sync local data to cloud. (Enterprise only.)"""
    raise ImportError(_ENTERPRISE_MSG)


def sync_from_cloud(*args: object, **kwargs: object) -> None:
    """Sync cloud data to local. (Enterprise only.)"""
    raise ImportError(_ENTERPRISE_MSG)


def migrate_deployment(*args: object, **kwargs: object) -> None:
    """Full deployment migration (local→cloud or cloud→local). (Enterprise only.)"""
    raise ImportError(_ENTERPRISE_MSG)
