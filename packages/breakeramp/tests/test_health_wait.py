"""Tests for health wait / stack readiness polling."""

from unittest.mock import patch

import pytest

from breakeramp import health_wait


def test_endpoint_ready_non_strict_accepts_200_json() -> None:
    with patch.object(health_wait, "_fetch_json", return_value=(200, {"status": "degraded"})):
        ok, err = health_wait.endpoint_ready("http://example/health", strict=False)
        assert ok is True
        assert err is None


def test_endpoint_ready_strict_requires_healthy() -> None:
    with patch.object(health_wait, "_fetch_json", return_value=(200, {"status": "degraded"})):
        ok, err = health_wait.endpoint_ready("http://example/health", strict=True)
        assert ok is False
        assert err is not None


def test_endpoint_ready_strict_passes_when_healthy() -> None:
    with patch.object(health_wait, "_fetch_json", return_value=(200, {"status": "healthy"})):
        ok, err = health_wait.endpoint_ready("http://example/health", strict=True)
        assert ok is True


def test_wait_for_stack_health_stops_when_gateway_ok_without_direct() -> None:
    calls = []

    def fake_fetch(url: str, timeout_s: float):
        calls.append(url)
        return (200, {"status": "healthy"})

    with patch.object(health_wait, "_fetch_json", side_effect=fake_fetch):
        res = health_wait.wait_for_stack_health(
            gateway_health_url="http://localhost:8080/health",
            direct_api_health_url=None,
            strict=False,
            max_wait_s=10.0,
            interval_s=0.01,
        )
        assert res.ok is True
        assert res.attempts == 1
        assert len(calls) == 1


@pytest.mark.parametrize(
    ("status_payload", "strict", "want_ok"),
    [
        ((200, None), False, True),
        ((503, None), False, False),
        ((200, {"status": "healthy"}), True, True),
        ((200, {}), True, False),
    ],
)
def test_endpoint_ready_table(
    status_payload,
    strict: bool,
    want_ok: bool,
) -> None:
    with patch.object(health_wait, "_fetch_json", return_value=status_payload):
        ok, _ = health_wait.endpoint_ready("http://x", strict=strict)
        assert ok is want_ok
