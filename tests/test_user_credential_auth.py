"""User BYOK credential authorization tests."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from amprealize.api import _resolve_user_credential_target

pytestmark = pytest.mark.unit


def test_user_credential_target_allows_me_alias():
    target = _resolve_user_credential_target(
        requested_user_id="me",
        current_user={"user_id": "user-123"},
    )

    assert target == "user-123"


def test_user_credential_target_allows_own_user_id_with_matching_actor():
    target = _resolve_user_credential_target(
        requested_user_id="user-123",
        current_user={"user_id": "user-123"},
        actor_id="user-123",
    )

    assert target == "user-123"


def test_user_credential_target_rejects_actor_mismatch():
    with pytest.raises(HTTPException) as exc:
        _resolve_user_credential_target(
            requested_user_id="user-123",
            current_user={"user_id": "user-123"},
            actor_id="other-user",
        )

    assert exc.value.status_code == 403


def test_user_credential_target_rejects_cross_user_access():
    with pytest.raises(HTTPException) as exc:
        _resolve_user_credential_target(
            requested_user_id="other-user",
            current_user={"user_id": "user-123"},
        )

    assert exc.value.status_code == 403


def test_user_credential_target_requires_authenticated_user():
    with pytest.raises(HTTPException) as exc:
        _resolve_user_credential_target(
            requested_user_id="me",
            current_user={},
        )

    assert exc.value.status_code == 401
