"""URL source ingester."""

from __future__ import annotations

import html
import ipaddress
import logging
import os
import random
import re
import socket
import time
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from amprealize.research.ingesters.base import (
    BaseIngester,
    IngestResult,
    count_words,
    parse_markdown_sections,
)

logger = logging.getLogger(__name__)


class URLIngesterError(ValueError):
    """Raised when a URL cannot be safely ingested."""


# Browser-like UA reduces empty responses from some news sites that filter bots.
DEFAULT_RESEARCH_UA = (
    "Mozilla/5.0 (compatible; AmprealizeResearch/1.0; +https://github.com/SandRiseStudio/amprealize) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# If naive HTML→text yields fewer words than this, try trafilatura main-content extraction.
NAIVE_WORD_THRESHOLD_FOR_TRAFILATURA = 32

# Transient HTTP responses worth retrying (shared egress IPs often see 429 from publishers).
_RETRIABLE_HTTP_CODES = frozenset({429, 500, 502, 503, 504})


def _backoff_seconds_before_url_retry(attempt_index: int, exc: HTTPError) -> float:
    """Compute sleep before retrying the same URL after a retriable HTTP error.

    Honors ``Retry-After`` when it is a non-negative integer (seconds), capped.
    Otherwise uses exponential backoff with small jitter (bounded).
    """
    ra = exc.headers.get("Retry-After")
    if ra:
        token = ra.strip().split(",")[0].strip()
        if token.isdigit():
            return min(max(float(token), 0.0), 60.0)
    base = min(2.0**attempt_index, 32.0)
    return min(base + random.uniform(0.05, 0.35), 45.0)


def _extract_with_trafilatura(html: str, page_url: str) -> tuple[str, str]:
    """Extract main text and title using trafilatura; returns ("", "") if unavailable."""
    try:
        import trafilatura
        from trafilatura.metadata import extract_metadata
    except ImportError:
        return "", ""
    title = ""
    try:
        meta = extract_metadata(html, default_url=page_url)
        if meta is not None:
            title = (getattr(meta, "title", None) or "").strip()
    except Exception:
        pass
    try:
        extracted = trafilatura.extract(
            html,
            url=page_url,
            favor_recall=True,
            include_tables=True,
            include_comments=False,
        )
    except Exception:
        return "", title
    return ((extracted or "").strip(), title)


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in {"p", "br", "div", "section", "article", "li", "h1", "h2", "h3"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title = f"{self.title} {text}".strip()
        self._chunks.append(text)

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", " ".join(self._chunks)).strip()


class URLIngester(BaseIngester):
    """Ingests content from public HTTP(S) URLs."""

    max_redirects = 5
    max_bytes = 2_000_000
    timeout_seconds = 15
    #: Retries per URL for transient HTTP errors (429, 5xx) before surfacing failure.
    max_transient_fetch_attempts = 5
    allowed_content_types = (
        "text/html",
        "text/plain",
        "text/markdown",
        "application/xhtml+xml",
    )

    def can_handle(self, source: str) -> bool:
        return source.startswith(("http://", "https://"))

    def _decode_and_extract_text(self, final_url: str, content_type: str, raw: bytes) -> tuple[str, str]:
        charset = self._charset_from_content_type(content_type)
        decoded = raw.decode(charset, errors="replace")

        if content_type.startswith("text/html") or content_type.startswith("application/xhtml+xml"):
            extractor = _HTMLTextExtractor()
            extractor.feed(decoded)
            content = html.unescape(extractor.text())
            title = extractor.title or final_url
            naive_words = count_words(content)
            if not content.strip() or naive_words < NAIVE_WORD_THRESHOLD_FOR_TRAFILATURA:
                alt_text, alt_title = _extract_with_trafilatura(decoded, final_url)
                alt_words = count_words(alt_text)
                if alt_text.strip() and alt_words > naive_words:
                    content = alt_text
                    if alt_title.strip():
                        title = alt_title.strip()
            return content, title

        return decoded, final_url

    def ingest(self, source: str, **kwargs: Any) -> IngestResult:
        final_url, content_type, raw, used_reader_proxy = self._fetch(source)
        content, title = self._decode_and_extract_text(
            final_url, content_type, raw
        )

        if (
            not content.strip()
            and self._jina_auto_fallback_enabled()
            and not used_reader_proxy
        ):
            jina_url = self._jina_relay_url(source)
            logger.info(
                "Research URL had no extractable text; fetching via Jina Reader relay: %s",
                jina_url[:120],
            )
            self._assert_public_http_url(jina_url)
            opener = build_opener(_NoRedirectHandler)
            final_url, content_type, raw = self._fetch_with_retries(opener, jina_url, source)
            used_reader_proxy = True
            content, title = self._decode_and_extract_text(
                final_url, content_type, raw
            )

        if not content.strip():
            raise URLIngesterError("Fetched URL did not contain extractable text")

        return IngestResult(
            content=content,
            metadata={
                "title": title,
                "source_url": final_url,
                "content_type": content_type,
                "bytes_read": len(raw),
                "fetch_via_reader_proxy": used_reader_proxy,
            },
            word_count=count_words(content),
            sections=parse_markdown_sections(content),
        )

    def _jina_relay_url(self, source: str) -> str:
        """Build Jina Reader relay URL for ``source`` (same pattern as SandRise exploring-ingest)."""
        base = (os.environ.get("AMPREALIZE_RESEARCH_JINA_READER_BASE") or "https://r.jina.ai").rstrip("/")
        return f"{base}/{source}"

    def _jina_auto_fallback_enabled(self) -> bool:
        """When true (default), retry failed or empty extractions via ``r.jina.ai/<url>``."""
        v = (os.environ.get("AMPREALIZE_RESEARCH_JINA_AUTO_FALLBACK") or "true").strip().lower()
        return v not in ("0", "false", "off", "no", "none")

    def _reader_fetch_url(self, source: str) -> str | None:
        """Return a proxy URL to fetch ``source`` through, or None for direct HTTP.

        When ``AMPREALIZE_RESEARCH_READER_PROXY=jina``, uses Jina Reader
        (``https://r.jina.ai/<original url>`` by default). Override base with
        ``AMPREALIZE_RESEARCH_JINA_READER_BASE`` if you self-host a compatible reader.
        """
        mode = (os.environ.get("AMPREALIZE_RESEARCH_READER_PROXY") or "").strip().lower()
        if not mode or mode in ("0", "false", "off", "no", "none"):
            return None
        if mode != "jina":
            logger.warning(
                "AMPREALIZE_RESEARCH_READER_PROXY=%r is unsupported (expected 'jina'); "
                "fetching the URL directly",
                mode,
            )
            return None
        return self._jina_relay_url(source)

    def _request_headers(self) -> dict[str, str]:
        """Browser-like headers; mirrors SandRise exploring-ingest (reduces empty/blocked responses)."""
        return {
            "User-Agent": DEFAULT_RESEARCH_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    def _fetch_with_retries(
        self,
        opener: Any,
        initial_url: str,
        attribution_url: str | None,
    ) -> tuple[str, str, bytes]:
        """Follow redirects (up to ``max_redirects``) and retry transient HTTP errors."""
        url = initial_url
        for _redirect_guard in range(self.max_redirects + 1):
            self._assert_public_http_url(url)
            redirected = False

            for attempt in range(self.max_transient_fetch_attempts):
                request = Request(url, headers=self._request_headers(), method="GET")
                try:
                    with opener.open(request, timeout=self.timeout_seconds) as response:
                        content_type = response.headers.get_content_type()
                        if not self._is_allowed_content_type(content_type):
                            raise URLIngesterError(f"Unsupported content type: {content_type}")
                        resolved = (
                            attribution_url if attribution_url is not None else response.geturl()
                        )
                        return resolved, content_type, self._read_limited(response)
                except HTTPError as exc:
                    if exc.code in {301, 302, 303, 307, 308}:
                        location = exc.headers.get("Location")
                        if not location:
                            raise URLIngesterError("Redirect response missing Location header") from exc
                        url = urljoin(url, location)
                        redirected = True
                        break

                    if exc.code in _RETRIABLE_HTTP_CODES:
                        if attempt >= self.max_transient_fetch_attempts - 1:
                            raise URLIngesterError(
                                f"URL fetch failed with HTTP {exc.code} after "
                                f"{self.max_transient_fetch_attempts} attempts. "
                                "The site may be rate-limiting or blocking datacenter IPs—"
                                "paste the article body into the research work item, or retry later."
                            ) from exc
                        delay = _backoff_seconds_before_url_retry(attempt, exc)
                        time.sleep(delay)
                        continue

                    raise URLIngesterError(f"URL fetch failed with HTTP {exc.code}") from exc

            if not redirected:
                break

        raise URLIngesterError("Too many redirects while fetching URL")

    def _fetch(self, source: str) -> tuple[str, str, bytes, bool]:
        self._assert_public_http_url(source)
        reader_first = self._reader_fetch_url(source)
        opener = build_opener(_NoRedirectHandler)
        if reader_first:
            self._assert_public_http_url(reader_first)
            resolved, ct, raw = self._fetch_with_retries(opener, reader_first, source)
            return resolved, ct, raw, True

        direct_error: URLIngesterError | None = None
        try:
            resolved, ct, raw = self._fetch_with_retries(opener, source, None)
            return resolved, ct, raw, False
        except URLIngesterError as exc:
            direct_error = exc

        if self._jina_auto_fallback_enabled():
            jina_url = self._jina_relay_url(source)
            logger.info(
                "Research URL direct fetch failed; retrying via Jina Reader relay (first 120 chars): %s",
                jina_url[:120],
            )
            self._assert_public_http_url(jina_url)
            try:
                resolved, ct, raw = self._fetch_with_retries(opener, jina_url, source)
                return resolved, ct, raw, True
            except URLIngesterError as jina_exc:
                raise direct_error from jina_exc

        assert direct_error is not None
        raise direct_error

    def _read_limited(self, response: Any) -> bytes:
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > self.max_bytes:
                raise URLIngesterError("Fetched URL exceeded maximum size")
            chunks.append(chunk)
        return b"".join(chunks)

    def _assert_public_http_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise URLIngesterError("Research URL must be an absolute http(s) URL")
        if parsed.username or parsed.password:
            raise URLIngesterError("Research URL must not include credentials")
        for addr_info in socket.getaddrinfo(parsed.hostname, parsed.port or 443):
            ip = ipaddress.ip_address(addr_info[4][0])
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
                or ip.is_unspecified
            ):
                raise URLIngesterError("Research URL resolves to a non-public network address")

    def _is_allowed_content_type(self, content_type: str) -> bool:
        return any(content_type.startswith(allowed) for allowed in self.allowed_content_types)

    def _charset_from_content_type(self, content_type: str) -> str:
        match = re.search(r"charset=([^;\s]+)", content_type, flags=re.IGNORECASE)
        return match.group(1) if match else "utf-8"
