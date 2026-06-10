"""Tests for Server-Timing middleware (guideai-1144)."""

import pytest

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from amprealize.server_timing_middleware import ServerTimingMiddleware

pytestmark = pytest.mark.unit


async def _hello(_: Request):
    return PlainTextResponse("ok")


def test_server_timing_middleware_adds_header():
    app = Starlette(routes=[Route("/", _hello)])
    app.add_middleware(ServerTimingMiddleware)
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "server-timing" in r.headers
    assert "total;dur=" in r.headers["server-timing"].lower()


def test_server_timing_middleware_stacks_with_inner_middleware():
    class AddHeaderMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            response = await call_next(request)
            response.headers["X-Test"] = "1"
            return response

    app = Starlette(routes=[Route("/", _hello)])
    app.add_middleware(ServerTimingMiddleware)
    app.add_middleware(AddHeaderMiddleware)
    client = TestClient(app)
    r = client.get("/")
    assert r.headers.get("X-Test") == "1"
    assert "total;dur=" in r.headers["server-timing"].lower()
