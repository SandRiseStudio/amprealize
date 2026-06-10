"""URL ingester: trafilatura fallback when naive HTML extraction is too thin."""

from __future__ import annotations

from http.client import HTTPMessage
from io import BytesIO
import socket
import pytest
from urllib.error import HTTPError

from amprealize.research.ingesters import url_ingester as url_ingester_mod
from amprealize.research.ingesters.url_ingester import (
    URLIngester,
    URLIngesterError,
    _backoff_seconds_before_url_retry,
)

pytestmark = pytest.mark.unit


def test_backoff_respects_retry_after_integer() -> None:
    msg = HTTPMessage()
    msg.add_header("Retry-After", "7")
    exc = HTTPError("https://example.com/a", 429, "Too Many", msg, BytesIO(b""))
    assert _backoff_seconds_before_url_retry(99, exc) == 7.0


def test_backoff_exponential_without_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(url_ingester_mod.random, "uniform", lambda _a, _b: 0.1)
    msg = HTTPMessage()
    exc = HTTPError("https://example.com/b", 503, "Err", msg, BytesIO(b""))
    assert _backoff_seconds_before_url_retry(0, exc) == pytest.approx(1.1, rel=0.01)
    assert _backoff_seconds_before_url_retry(3, exc) == pytest.approx(8.1, rel=0.01)


def test_url_ingester_retries_429_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Transient 429 responses are retried before giving up."""
    monkeypatch.setattr(url_ingester_mod.time, "sleep", lambda _s: None)

    html = (
        b"<html><head><title>VB</title></head><body>"
        + (b"<p>word </p>" * 80)
        + b"</body></html>"
    )
    chunks: list[bytes] = []
    pos = 0
    while pos < len(html):
        chunks.append(html[pos : pos + 65536])
        pos += 65536
    chunks.append(b"")

    class FakeHeaders:
        def get_content_type(self) -> str:
            return "text/html"

    class FakeResponse:
        def __init__(self, final_url: str) -> None:
            self._final_url = final_url
            self.headers = FakeHeaders()

        def geturl(self) -> str:
            return self._final_url

        def read(self, n: int = -1) -> bytes:
            return chunks.pop(0)

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    calls = {"n": 0}

    class FakeOpener:
        def open(self, req: object, timeout: object = None) -> FakeResponse:
            calls["n"] += 1
            if calls["n"] < 3:
                h = HTTPMessage()
                h.add_header("Retry-After", "0")
                raise HTTPError(getattr(req, "full_url", "https://x"), 429, "Many", h, BytesIO(b""))
            return FakeResponse("https://example.com/final")

    monkeypatch.setattr(url_ingester_mod, "build_opener", lambda *a, **k: FakeOpener())

    ingester = URLIngester()
    result = ingester.ingest("https://example.com/start")
    assert calls["n"] == 3
    assert result.word_count >= 70
    assert "VB" in (result.metadata.get("title") or "")


def test_url_ingester_trafilatura_supplements_sparse_naive(monkeypatch: pytest.MonkeyPatch) -> None:
    """When naive word count is below threshold, richer trafilatura output replaces content."""
    sparse_html = b"<html><head><title>Site</title></head><body><div id='root'></div></body></html>"

    def fake_fetch(self, source: str) -> tuple[str, str, bytes, bool]:
        assert source.startswith("https://")
        return "https://example.com/page", "text/html", sparse_html, False

    def fake_trafilatura(html: str, page_url: str) -> tuple[str, str]:
        assert "html" in html.lower()
        text = "word " * 80
        return text, "Article Title From Trafilatura"

    monkeypatch.setattr(URLIngester, "_fetch", fake_fetch)
    monkeypatch.setattr(url_ingester_mod, "_extract_with_trafilatura", fake_trafilatura)

    ingester = URLIngester()
    result = ingester.ingest("https://example.com/page")
    assert result.word_count >= 70
    assert result.metadata.get("title") == "Article Title From Trafilatura"


def test_reader_jina_proxy_builds_expected_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMPREALIZE_RESEARCH_READER_PROXY", "jina")
    monkeypatch.setenv("AMPREALIZE_RESEARCH_JINA_READER_BASE", "https://r.jina.ai")
    ing = URLIngester()
    assert ing._reader_fetch_url("https://venturebeat.com/a?x=1") == "https://r.jina.ai/https://venturebeat.com/a?x=1"


def test_reader_unknown_proxy_mode_logs_and_returns_none(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setenv("AMPREALIZE_RESEARCH_READER_PROXY", "nope")
    ing = URLIngester()
    assert ing._reader_fetch_url("https://example.com/") is None
    assert "unsupported" in caplog.text.lower()


def test_url_ingester_raises_when_both_naive_and_trafilatura_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMPREALIZE_RESEARCH_JINA_AUTO_FALLBACK", "false")
    empty_html = b"<html></html>"

    def fake_fetch(self, source: str) -> tuple[str, str, bytes, bool]:
        return "https://example.com/e", "text/html", empty_html, False

    monkeypatch.setattr(URLIngester, "_fetch", fake_fetch)
    monkeypatch.setattr(url_ingester_mod, "_extract_with_trafilatura", lambda html, url: ("", ""))

    ingester = URLIngester()
    with pytest.raises(URLIngesterError, match="extractable text"):
        ingester.ingest("https://example.com/e")


def test_jina_auto_fallback_after_direct_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """SandRise-style: direct fetch fails (e.g. 403); relay via r.jina.ai succeeds."""
    monkeypatch.setenv("AMPREALIZE_RESEARCH_JINA_AUTO_FALLBACK", "true")
    monkeypatch.delenv("AMPREALIZE_RESEARCH_READER_PROXY", raising=False)
    monkeypatch.setattr(url_ingester_mod.time, "sleep", lambda _s: None)

    def fake_getaddrinfo(_hostname: object, *_a: object, **_kw: object) -> list[tuple]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 443))]

    monkeypatch.setattr(url_ingester_mod.socket, "getaddrinfo", fake_getaddrinfo)

    good_html = (
        b"<html><head><title>Article</title></head><body>"
        + (b"<p>paragraph word </p>" * 40)
        + b"</body></html>"
    )

    class FakeHeaders:
        def get_content_type(self) -> str:
            return "text/html"

    class FakeResponse:
        def __init__(self, final_url: str, body: bytes) -> None:
            self._final_url = final_url
            self.headers = FakeHeaders()
            self._body = body
            self._pos = 0

        def geturl(self) -> str:
            return self._final_url

        def read(self, n: int = -1) -> bytes:
            if self._pos >= len(self._body):
                return b""
            chunk = self._body[self._pos : self._pos + 65536]
            self._pos += len(chunk)
            return chunk

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    class FakeOpener:
        def open(self, req: object, timeout: object = None) -> FakeResponse:
            u = getattr(req, "full_url", "")
            if "r.jina.ai" in u:
                return FakeResponse("https://example.com/via-jina", good_html)
            msg = HTTPMessage()
            raise HTTPError(u, 403, "Forbidden", msg, BytesIO(b""))

    monkeypatch.setattr(url_ingester_mod, "build_opener", lambda *a, **k: FakeOpener())

    ingester = URLIngester()
    result = ingester.ingest("https://example.com/article")
    assert result.metadata.get("fetch_via_reader_proxy") is True
    assert result.word_count >= 32
    assert "Article" in (result.metadata.get("title") or "")
