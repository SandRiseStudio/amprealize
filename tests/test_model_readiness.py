"""Tests for model readiness, BYOK policy, and credential factory."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from amprealize.llm.byok_policy import assert_byok_persistence_allowed, byok_persistence_status
from amprealize.llm.model_readiness import compute_model_readiness_payload
from amprealize.work_item_execution_service import CredentialStore


def test_byok_persistence_status_allows_explicit_fernet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AMPREALIZE_REQUIRE_BYOK_ENCRYPTION", raising=False)
    monkeypatch.setenv("BYOK_KMS_PROVIDER", "fernet")
    monkeypatch.setenv("BYOK_ENCRYPTION_KEY", "x" * 43 + "=")  # invalid length but exercises path
    # FernetProvider will fail on invalid key — use generate_key pattern
    from amprealize.auth.credential_encryption import CredentialEncryptionService

    key = CredentialEncryptionService.generate_key()
    monkeypatch.setenv("BYOK_ENCRYPTION_KEY", key)
    st = byok_persistence_status()
    assert st["can_persist"] is True
    assert st.get("ephemeral") is False


def test_require_encryption_blocks_persist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMPREALIZE_REQUIRE_BYOK_ENCRYPTION", "1")
    monkeypatch.setenv("AMPREALIZE_ENV", "development")
    monkeypatch.delenv("BYOK_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("BYOK_KMS_PROVIDER", "fernet")
    st = byok_persistence_status()
    assert st["can_persist"] is False
    with pytest.raises(ValueError):
        assert_byok_persistence_allowed()


def test_first_chat_model_id_for_provider_covers_nvidia() -> None:
    from amprealize.execution_wiring import first_chat_model_id_for_provider

    mid = first_chat_model_id_for_provider("nvidia")
    assert mid is not None


def test_credential_store_scope_pairs_order() -> None:
    store = CredentialStore(pool=None, credential_repository=None)
    pairs = store._credential_scope_pairs(
        project_id="p1",
        org_id="o1",
        user_id="u1",
        prefer_user=True,
    )
    labels = [p[0].value if hasattr(p[0], "value") else str(p[0]) for p in pairs]
    assert labels == ["user", "project", "org"]

    pairs_proj_first = store._credential_scope_pairs(
        project_id="p1",
        org_id="o1",
        user_id="u1",
        prefer_user=False,
    )
    labels2 = [p[0].value if hasattr(p[0], "value") else str(p[0]) for p in pairs_proj_first]
    assert labels2 == ["project", "user", "org"]


def test_compute_readiness_platform_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key-not-real")
    store = CredentialStore(pool=None, credential_repository=None)
    payload = compute_model_readiness_payload(
        store,
        user_id="user-1",
        org_id=None,
        project_id=None,
        prefer_user=True,
        provider_filter="nvidia",
        free_open_only=True,
        selected_model_id=None,
    )
    assert payload["total_count"] >= 1
    assert payload["can_send"] is True
    assert payload["state"] == "ready"
