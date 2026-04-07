"""Base ingester - OSS Stub. Full implementation in amprealize-enterprise."""

try:
    from amprealize_enterprise.research.ingesters.base import (
        BaseIngester,
        count_words,
        extract_figure_captions,
        extract_metadata_from_markdown,
        extract_table_captions,
        parse_markdown_sections,
    )
except ImportError:
    BaseIngester = None  # type: ignore[assignment,misc]
    count_words = None  # type: ignore[assignment]
    extract_figure_captions = None  # type: ignore[assignment]
    extract_metadata_from_markdown = None  # type: ignore[assignment]
    extract_table_captions = None  # type: ignore[assignment]
    parse_markdown_sections = None  # type: ignore[assignment]
