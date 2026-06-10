from __future__ import annotations

from typing import Optional

import pytest

from amprealize.auth.llm_credential_repository import CredentialScopeType, LLMCredential
from amprealize.work_item_execution_service import CredentialStore

pytestmark = [pytest.mark.unit]


class FakeCredentialRepository:
    def __init__(self) -> None:
        self.credentials: dict[tuple[CredentialScopeType, str, str], LLMCredential] = {}

    def add(
        self,
        *,
        scope_type: CredentialScopeType,
        scope_id: str,
        provider: str = "openai",
        decrypted_key: Optional[str] = None,
        is_valid: bool = True,
    ) -> None:
        credential = LLMCredential(
            id=f"cred-{scope_type.value}-{scope_id}-{provider}",
            scope_type=scope_type,
            scope_id=scope_id,
            provider=provider,
            name=f"{provider} key",
            key_prefix="sk-test",
            is_valid=is_valid,
        )
        credential._decrypted_key = decrypted_key
        self.credentials[(scope_type, scope_id, provider)] = credential

    def get_for_provider(
        self,
        provider: str,
        scope_type: CredentialScopeType,
        scope_id: str,
        decrypt: bool = False,
        include_invalid: bool = False,
    ) -> Optional[LLMCredential]:
        credential = self.credentials.get((scope_type, scope_id, provider))
        if credential and (include_invalid or credential.is_valid):
            return credential
        return None


def test_project_context_prefers_project_byok_over_user() -> None:
    repo = FakeCredentialRepository()
    repo.add(scope_type=CredentialScopeType.USER, scope_id="user-1", decrypted_key="user-key")
    repo.add(scope_type=CredentialScopeType.PROJECT, scope_id="project-1", decrypted_key="project-key")
    store = CredentialStore(credential_repository=repo)

    result = store.get_credential_for_model(
        "gpt-4o",
        project_id="project-1",
        user_id="user-1",
    )

    assert result == ("project-key", "project", True)


def test_personal_context_uses_user_byok() -> None:
    repo = FakeCredentialRepository()
    repo.add(scope_type=CredentialScopeType.USER, scope_id="user-1", decrypted_key="user-key")
    store = CredentialStore(credential_repository=repo)

    result = store.get_credential_for_model("gpt-4o", user_id="user-1")

    assert result == ("user-key", "user", True)


def test_prefer_user_can_override_project_byok() -> None:
    repo = FakeCredentialRepository()
    repo.add(scope_type=CredentialScopeType.USER, scope_id="user-1", decrypted_key="user-key")
    repo.add(scope_type=CredentialScopeType.PROJECT, scope_id="project-1", decrypted_key="project-key")
    store = CredentialStore(credential_repository=repo)

    result = store.get_credential_for_model(
        "gpt-4o",
        project_id="project-1",
        user_id="user-1",
        prefer_user=True,
    )

    assert result == ("user-key", "user", True)


def test_invalid_scoped_byok_falls_back_to_platform(monkeypatch) -> None:
    repo = FakeCredentialRepository()
    repo.add(
        scope_type=CredentialScopeType.USER,
        scope_id="user-1",
        decrypted_key=None,
        is_valid=False,
    )
    monkeypatch.setenv("OPENAI_API_KEY", "platform-key")
    store = CredentialStore(credential_repository=repo)

    result = store.get_credential_for_model("gpt-4o", user_id="user-1")

    assert result == ("platform-key", "platform", False)
