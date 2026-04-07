"""Cloud client — OSS stub (Pattern 3: raise on call).

The real authenticated HTTP client to Amprealize.io lives in
``amprealize_enterprise.cloud_client``. This stub raises a clear
``ImportError`` when any method is called in the OSS edition.

Part of Phase 1 of GUIDEAI-619 (Modular Installation System v3).
"""

from __future__ import annotations

_ENTERPRISE_MSG = (
    "Cloud deployment requires amprealize-enterprise. "
    "Install with: pip install amprealize-enterprise"
)


class CloudClient:
    """OSS stub — all methods raise ``ImportError``."""

    def __init__(self, cloud_url: str = "https://api.amprealize.io") -> None:
        self._cloud_url = cloud_url

    def _raise(self) -> None:
        raise ImportError(_ENTERPRISE_MSG)

    # Storage
    def upload(self, *args: object, **kwargs: object) -> None:
        self._raise()

    def download(self, *args: object, **kwargs: object) -> None:
        self._raise()

    # Compute
    def submit_job(self, *args: object, **kwargs: object) -> None:
        self._raise()

    def get_job_status(self, *args: object, **kwargs: object) -> None:
        self._raise()

    # Auth
    def authenticate(self, *args: object, **kwargs: object) -> None:
        self._raise()

    # Generic
    def request(self, *args: object, **kwargs: object) -> None:
        self._raise()


# ---------------------------------------------------------------------------
# Factory — tries enterprise first, falls back to stub
# ---------------------------------------------------------------------------


def get_cloud_client(
    cloud_url: str = "https://api.amprealize.io",
) -> CloudClient:
    """Return the cloud client.

    Tries to import the real client from ``amprealize_enterprise``.
    Falls back to the OSS stub that raises on any method call.
    """
    try:
        from amprealize_enterprise.cloud_client import (  # type: ignore[import-not-found]
            CloudClient as EnterpriseCloudClient,
        )
        return EnterpriseCloudClient(cloud_url=cloud_url)
    except ImportError:
        return CloudClient(cloud_url=cloud_url)
