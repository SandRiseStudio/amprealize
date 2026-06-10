"""Centralized construction of :class:`CredentialStore` with BYOK repository wiring.

Following ``behavior_externalize_configuration`` (Student): DSN comes from env /
:func:`PostgresPool` defaults — callers must not duplicate pool + repository setup
across REST, WebSocket, MCP, and API surfaces.
"""

from __future__ import annotations

from typing import Optional

from amprealize.auth.llm_credential_repository import LLMCredentialRepository
from amprealize.storage.postgres_pool import PostgresPool
from amprealize.work_item_execution_service import CredentialStore


def build_credential_store(
    pool: Optional[PostgresPool] = None,
    *,
    credential_repository: Optional[LLMCredentialRepository] = None,
) -> CredentialStore:
    """Return a :class:`CredentialStore` backed by Postgres BYOK when a pool exists.

    If ``pool`` is omitted, uses :class:`PostgresPool` default env DSN resolution.
    When no DSN is configured, :class:`PostgresPool` may still fail fast — callers
    that must tolerate missing DB should catch and fall back (MCP already picks a
    dev default DSN).
    """
    resolved_pool = pool or PostgresPool()
    repo = credential_repository or LLMCredentialRepository(pool=resolved_pool)
    return CredentialStore(pool=resolved_pool, credential_repository=repo)
