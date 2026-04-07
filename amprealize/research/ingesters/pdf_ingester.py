"""PDF ingester - OSS Stub. Full implementation in amprealize-enterprise."""

try:
    from amprealize_enterprise.research.ingesters.pdf_ingester import PDFIngester
except ImportError:
    PDFIngester = None  # type: ignore[assignment,misc]
