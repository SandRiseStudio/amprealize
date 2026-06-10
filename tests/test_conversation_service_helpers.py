"""Unit tests for ConversationService helpers (no DB)."""

import pytest

from amprealize.services.conversation_service import _is_postgres_unique_violation

pytestmark = pytest.mark.unit

try:
    from psycopg2.errors import UniqueViolation
except ImportError:
    UniqueViolation = None  # type: ignore[misc, assignment]


@pytest.mark.skipif(UniqueViolation is None, reason="psycopg2 required")
def test_is_postgres_unique_violation_direct() -> None:
    exc = UniqueViolation()
    assert _is_postgres_unique_violation(exc) is True


@pytest.mark.skipif(UniqueViolation is None, reason="psycopg2 required")
def test_is_postgres_unique_violation_wrapped_in_cause() -> None:
    inner = UniqueViolation()
    outer = RuntimeError("wrapper")
    outer.__cause__ = inner
    assert _is_postgres_unique_violation(outer) is True


def test_is_postgres_unique_violation_pgcode_only() -> None:
    class FakeExc(Exception):
        pgcode = "23505"

    assert _is_postgres_unique_violation(FakeExc()) is True


def test_is_postgres_unique_violation_false_for_other() -> None:
    assert _is_postgres_unique_violation(ValueError("not unique")) is False
