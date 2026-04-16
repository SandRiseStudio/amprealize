"""Research ingesters."""

from amprealize.research.ingesters.base import (
    BaseIngester,
    IngestResult,
    count_words,
    extract_figure_captions,
    extract_metadata_from_markdown,
    extract_table_captions,
    parse_markdown_sections,
)
from amprealize.research.ingesters.markdown_ingester import MarkdownIngester
from amprealize.research.ingesters.url_ingester import URLIngester
from amprealize.research.ingesters.pdf_ingester import PDFIngester

__all__ = [
    "BaseIngester",
    "IngestResult",
    "MarkdownIngester",
    "URLIngester",
    "PDFIngester",
    "count_words",
    "extract_figure_captions",
    "extract_metadata_from_markdown",
    "extract_table_captions",
    "parse_markdown_sections",
]
