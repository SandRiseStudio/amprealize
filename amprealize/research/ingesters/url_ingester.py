"""URL source ingester."""

from __future__ import annotations

from typing import Any

from amprealize.research.ingesters.base import BaseIngester, IngestResult


class URLIngester(BaseIngester):
    """Ingests content from URLs.

    Stub — replace with real HTTP fetching and content extraction.
    """

    async def ingest(self, source: str, **kwargs: Any) -> IngestResult:
        raise NotImplementedError("URLIngester.ingest not yet implemented")
