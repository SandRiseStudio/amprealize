"""PDF source ingester."""

from __future__ import annotations

from typing import Any

from amprealize.research.ingesters.base import BaseIngester, IngestResult


class PDFIngester(BaseIngester):
    """Ingests content from PDF files.

    Stub — replace with real PDF parsing (pdfplumber, PyMuPDF, etc.).
    """

    def can_handle(self, source: str) -> bool:
        return source.lower().endswith(".pdf")

    def ingest(self, source: str, **kwargs: Any) -> IngestResult:
        raise NotImplementedError("PDFIngester.ingest not yet implemented")
