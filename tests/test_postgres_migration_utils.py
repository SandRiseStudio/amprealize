import importlib
import sqlite3
import sys
from pathlib import Path

import pytest

from scripts._postgres_migration_utils import split_sql_statements


@pytest.mark.parametrize(
    "sql,expected",
    [
        ("SELECT 1;", ["SELECT 1"]),
        (
            """
            CREATE TABLE foo (id SERIAL PRIMARY KEY);
            CREATE FUNCTION bar() RETURNS void AS $$
            BEGIN
                PERFORM 1;
            END;
            $$ LANGUAGE plpgsql;
            """,
            [
                "CREATE TABLE foo (id SERIAL PRIMARY KEY)",
                "CREATE FUNCTION bar() RETURNS void AS $$\n            BEGIN\n                PERFORM 1;\n            END;\n            $$ LANGUAGE plpgsql",
            ],
        ),
        (
            """
            INSERT INTO demo VALUES ('name; still name');
            INSERT INTO demo VALUES ($tag$; literal ; text$tag$);
            """,
            [
                "INSERT INTO demo VALUES ('name; still name')",
                "INSERT INTO demo VALUES ($tag$; literal ; text$tag$)",
            ],
        ),
    ],
)
def test_split_sql_statements_handles_quotes_and_dollar_quoting(sql, expected):
    statements = split_sql_statements(sql)
    assert statements == expected


class _FakePsycopgModule:
    def __init__(self) -> None:
        self.connected = False

    def connect(self, *args, **kwargs):  # pragma: no cover - guard assertion
        raise AssertionError("connect() should not be called during dry run")


def _create_sqlite_fixture(tmp_path: Path) -> Path:
    db_path = tmp_path / "behaviors.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE behaviors (
            behavior_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            tags TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            latest_version TEXT NOT NULL,
            status TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE behavior_versions (
            behavior_id TEXT NOT NULL,
            version TEXT NOT NULL,
            instruction TEXT NOT NULL,
            role_focus TEXT NOT NULL,
            status TEXT NOT NULL,
            trigger_keywords TEXT NOT NULL,
            examples TEXT NOT NULL,
            metadata TEXT NOT NULL,
            effective_from TEXT NOT NULL,
            effective_to TEXT,
            created_by TEXT NOT NULL,
            approval_action_id TEXT,
            embedding_checksum TEXT,
            embedding BLOB
        )
        """
    )
    conn.close()
    return db_path


def _create_workflow_sqlite_fixture(tmp_path: Path) -> Path:
    db_path = tmp_path / "workflows.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE workflow_templates (
            template_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            role_focus TEXT NOT NULL,
            version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            created_by_id TEXT NOT NULL,
            created_by_role TEXT NOT NULL,
            created_by_surface TEXT NOT NULL,
            template_data TEXT NOT NULL,
            tags TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE workflow_runs (
            run_id TEXT PRIMARY KEY,
            template_id TEXT NOT NULL,
            template_name TEXT NOT NULL,
            role_focus TEXT NOT NULL,
            status TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            actor_role TEXT NOT NULL,
            actor_surface TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            total_tokens INTEGER DEFAULT 0,
            run_data TEXT NOT NULL
        )
        """
    )
    conn.close()
    return db_path


def test_migrate_dry_run_avoids_postgres_connection(monkeypatch, tmp_path):
    fake_psycopg = _FakePsycopgModule()
    monkeypatch.setitem(sys.modules, "psycopg2", fake_psycopg)
    fake_extras = type(
        "extras",
        (),
        {
            "Json": staticmethod(lambda value: value),
            "execute_values": staticmethod(lambda *args, **kwargs: None),
        },
    )
    monkeypatch.setitem(sys.modules, "psycopg2.extras", fake_extras)

    sqlite_path = _create_sqlite_fixture(tmp_path)

    helper_module = importlib.import_module("scripts._postgres_migration_utils")
    monkeypatch.setitem(sys.modules, "_postgres_migration_utils", helper_module)

    behavior_migrate = importlib.import_module("scripts.migrate_behavior_sqlite_to_postgres")

    behavior_migrate.migrate(
        sqlite_path,
        dsn="postgresql://ignored",
        connect_timeout=1,
        truncate=False,
        chunk_size=100,
        dry_run=True,
    )


def test_workflow_migrate_dry_run_avoids_postgres_connection(monkeypatch, tmp_path):
    fake_psycopg = _FakePsycopgModule()
    monkeypatch.setitem(sys.modules, "psycopg2", fake_psycopg)
    fake_extras = type(
        "extras",
        (),
        {
            "Json": staticmethod(lambda value: value),
            "execute_values": staticmethod(lambda *args, **kwargs: None),
        },
    )
    monkeypatch.setitem(sys.modules, "psycopg2.extras", fake_extras)

    sqlite_path = _create_workflow_sqlite_fixture(tmp_path)

    helper_module = importlib.import_module("scripts._postgres_migration_utils")
    monkeypatch.setitem(sys.modules, "_postgres_migration_utils", helper_module)

    workflow_migrate = importlib.import_module("scripts.migrate_workflow_sqlite_to_postgres")

    workflow_migrate.migrate(
        sqlite_path,
        dsn="postgresql://ignored",
        connect_timeout=1,
        truncate=False,
        chunk_size=100,
        dry_run=True,
    )
