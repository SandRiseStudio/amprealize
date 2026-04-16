"""Base ingester and utility functions for the research pipeline."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class IngestResult:
    """Result from ingesting a source."""

    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    word_count: int = 0
    sections: list[dict[str, str]] = field(default_factory=list)


class BaseIngester:
    """Abstract base class for source ingesters."""

    def __init__(self, **kwargs: Any) -> None:
        self._config = kwargs

    async def ingest(self, source: str, **kwargs: Any) -> IngestResult:
        raise NotImplementedError("Subclasses must implement ingest()")


def count_words(text: str) -> int:
    """Count words in a text string."""
    return len(text.split())


def extract_figure_captions(text: str) -> list[str]:
    """Extract figure captions from markdown text."""
    pattern = r"!\[([^\]]*)\]"
    return re.findall(pattern, text)


def extract_metadata_from_markdown(text: str) -> dict[str, str]:
    """Extract YAML front matter metadata from markdown."""
    metadata: dict[str, str] = {}
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].strip().split("\n"):
                if ":" in line:
                    key, _, value = line.partition(":")
                    metadata[key.strip()] = value.strip()
    return metadata


def extract_table_captions(text: str) -> list[str]:
    """Extract table captions (text before markdown tables)."""
    captions: list[str] = []
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("|") and i > 0:
            prev = lines[i - 1].strip()
            if prev and not prev.startswith("|"):
                captions.append(prev)
    return captions


def parse_markdown_sections(text: str) -> list[dict[str, str]]:
    """Parse markdown into sections by heading."""
    sections: list[dict[str, str]] = []
    current_title = ""
    current_content: list[str] = []

    for line in text.split("\n"):
        if line.startswith("#"):
            if current_title or current_content:
                sections.append({
                    "title": current_title,
                    "content": "\n".join(current_content).strip(),
                })
            current_title = line.lstrip("#").strip()
            current_content = []
        else:
            current_content.append(line)

    if current_title or current_content:
        sections.append({
            "title": current_title,
            "content": "\n".join(current_content).strip(),
        })

    return sections
