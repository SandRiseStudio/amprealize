"""Tests for ``amprealize.runtime_env`` BreakerAmp-aware dotenv merge."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_merge_dotenv_skips_pg_dsn_keys(monkeypatch, tmp_path: Path) -> None:
    from amprealize.runtime_env import merge_dotenv_skipping_database_keys

    env_file = tmp_path / ".env"
    env_file.write_text(
        "AMPREALIZE_ACTION_PG_DSN=postgresql://u:p@ep-neon.example/db\n"
        "OPENAI_API_KEY=sk-test\n"
        "DATABASE_URL=postgresql://u:p@ep-neon.example/main\n"
    )
    monkeypatch.delenv("AMPREALIZE_ACTION_PG_DSN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    merge_dotenv_skipping_database_keys(env_file)

    assert "OPENAI_API_KEY" in os.environ
    assert os.environ["OPENAI_API_KEY"] == "sk-test"  # pragma: allowlist secret
    assert "AMPREALIZE_ACTION_PG_DSN" not in os.environ
    assert "DATABASE_URL" not in os.environ


def test_load_dotenv_files_respects_breakeramp(monkeypatch, tmp_path: Path) -> None:
    from amprealize.runtime_env import load_dotenv_files

    env_file = tmp_path / ".env"
    env_file.write_text("FOO_FROM_ENV=bar\nAMPREALIZE_BEHAVIOR_PG_DSN=postgresql://cloud/db\n")
    monkeypatch.setenv("AMPREALIZE_TEST_INFRA_MODE", "breakeramp")
    monkeypatch.delenv("FOO_FROM_ENV", raising=False)
    monkeypatch.delenv("AMPREALIZE_BEHAVIOR_PG_DSN", raising=False)

    load_dotenv_files((env_file,))

    assert os.environ.get("FOO_FROM_ENV") == "bar"
    assert "AMPREALIZE_BEHAVIOR_PG_DSN" not in os.environ
