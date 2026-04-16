"""Cloud client — OSS stub (raise on call).

The real authenticated HTTP client to Amprealize.io lives in the
enterprise fork.  This stub raises a clear ``ImportError`` when any
method is called in the OSS edition.
"""

from __future__ import annotations

_ENTERPRISE_MSG = (
    "Cloud deployment requires the enterprise edition. "
    "See https://amprealize.io/enterprise for details."
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
# Factory — always returns OSS stub (enterprise fork overrides this module)
# ---------------------------------------------------------------------------


def get_cloud_client(
    cloud_url: str = "https://api.amprealize.io",
) -> CloudClient:
    """Return the cloud client.

    In the OSS edition this always returns the stub that raises on any
    method call.  The enterprise fork replaces this module entirely.
    """
    return CloudClient(cloud_url=cloud_url)
