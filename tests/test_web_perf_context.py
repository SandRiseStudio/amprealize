"""Tests for X-Web-Perf-Session context propagation."""

from __future__ import annotations

import os

import pytest

# Ensure perf log can emit in test
os.environ.setdefault("AMPREALIZE_PERF_LOG", "1")

from amprealize.perf_log import perf_log
from amprealize.web_perf_context import get_web_perf_session_id


pytestmark = pytest.mark.unit


def test_get_web_perf_session_id_default_is_none() -> None:
    assert get_web_perf_session_id() is None


def test_perf_log_includes_web_perf_session_id_when_set() -> None:
    from amprealize.web_perf_context import bind_web_perf_session

    with bind_web_perf_session("sess-test-1"):
        import logging
        from io import StringIO

        import amprealize.perf_log as pl

        stream = StringIO()
        h = logging.StreamHandler(stream)
        h.setLevel(logging.INFO)
        pl.perf_logger.addHandler(h)
        pl.perf_logger.setLevel(logging.INFO)
        try:
            perf_log("test.endpoint", 1.0, extra_tag=42)
        finally:
            pl.perf_logger.removeHandler(h)

        out = stream.getvalue()
        assert "web_perf_session_id=sess-test-1" in out
        assert "extra_tag=42" in out
