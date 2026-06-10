"""Tests for ExecutionGateway bootstrap defaults."""

from __future__ import annotations

import pytest

from amprealize.execution_gateway_bootstrap import is_execution_gateway_enabled

pytestmark = pytest.mark.unit


def test_execution_gateway_enabled_by_default() -> None:
    assert is_execution_gateway_enabled(None) is True


def test_execution_gateway_can_be_explicitly_disabled() -> None:
    for raw_value in ("0", "false", "no", "off", " FALSE "):
        assert is_execution_gateway_enabled(raw_value) is False


def test_execution_gateway_accepts_explicit_enabled_values() -> None:
    for raw_value in ("1", "true", "yes", "on", " TRUE "):
        assert is_execution_gateway_enabled(raw_value) is True


def test_execution_gateway_unknown_value_fails_open_to_canonical_gateway() -> None:
    assert is_execution_gateway_enabled("unexpected") is True
