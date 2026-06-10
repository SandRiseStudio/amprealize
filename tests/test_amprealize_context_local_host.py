"""Tests for local-vs-remote Postgres detection on Amprealize CLI contexts."""

from __future__ import annotations

import importlib

import pytest
import yaml

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _restore_context_module_paths():
    """``context`` caches ``USER_CONFIG_PATH`` at import; reload after isolation."""
    yield
    import amprealize.context as ctx

    importlib.reload(ctx)


def _reload_context(monkeypatch, tmp_path):
    monkeypatch.setenv("AMPREALIZE_HOME", str(tmp_path))
    import amprealize.context as ctx

    return importlib.reload(ctx)


def test_postgres_dsn_uses_local_host():
    from amprealize.context import postgres_dsn_uses_local_host

    assert postgres_dsn_uses_local_host("postgresql://u:p@localhost:5432/db") is True
    assert postgres_dsn_uses_local_host("postgresql://u:p@127.0.0.1:5432/db") is True
    assert postgres_dsn_uses_local_host("postgresql://u:p@host.containers.internal:5432/db") is True
    assert postgres_dsn_uses_local_host("postgresql://u:p@ep-foo.us-east-2.aws.neon.tech/db") is False


def test_active_remote_neon_context(monkeypatch, tmp_path):
    ctx = _reload_context(monkeypatch, tmp_path)
    cfg = {
        "version": 2,
        "current_context": "neon",
        "contexts": {
            "neon": {
                "storage": {
                    "backend": "postgres",
                    "postgres": {"dsn": "postgresql://u:p@ep-x.aws.neon.tech/main"},
                }
            },
            "local-postgres": {
                "storage": {
                    "backend": "postgres",
                    "postgres": {"dsn": "postgresql://u:p@localhost:5432/amprealize"},
                }
            },
        },
    }
    (tmp_path / "config.yaml").write_text(yaml.dump(cfg))
    ctx = importlib.reload(ctx)

    remote, name, reason = ctx.active_amprealize_context_targets_remote_postgres()
    assert remote is True
    assert name == "neon"
    assert "non-local" in reason

    sugg = ctx.suggest_local_postgres_context_names()
    assert sugg == ["local-postgres"]


def test_ensure_standard_local_postgres_contexts_creates_both(monkeypatch, tmp_path):
    _reload_context(monkeypatch, tmp_path)
    import amprealize.context as ctx

    ctx = importlib.reload(ctx)
    created, lines = ctx.ensure_standard_local_postgres_contexts()
    assert created == 2
    assert len(lines) == 2
    assert "local-postgres-dev" in lines[0] or "local-postgres-dev" in str(lines)
    data = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert "local-postgres-dev" in data["contexts"]
    assert "local-postgres-test" in data["contexts"]
    d0 = data["contexts"]["local-postgres-dev"]["storage"]["postgres"]["dsn"]
    assert "localhost" in d0
    created2, lines2 = ctx.ensure_standard_local_postgres_contexts()
    assert created2 == 0
    assert "already exists" in lines2[0] or "already exists" in lines2[1]


def test_use_context_suggests_init_for_standard_local_names(monkeypatch, tmp_path):
    """Missing local-postgres-* names hint init-standard-local."""
    _reload_context(monkeypatch, tmp_path)
    cfg = {
        "version": 2,
        "current_context": "default",
        "contexts": {
            "default": {
                "storage": {"backend": "sqlite", "sqlite": {"path": ":memory:"}},
            },
            "neon": {
                "storage": {
                    "backend": "postgres",
                    "postgres": {"dsn": "postgresql://u:p@ep-x.aws.neon.tech/db"},
                }
            },
        },
    }
    (tmp_path / "config.yaml").write_text(yaml.dump(cfg))
    import amprealize.context as ctx

    ctx = importlib.reload(ctx)
    ok, msg = ctx.use_context("local-postgres-test")
    assert ok is False
    assert "init-standard-local" in msg


def test_amprealize_context_env_overrides_yaml_current(monkeypatch, tmp_path):
    """AMPREALIZE_CONTEXT selects a named context without changing current_context on disk."""
    _reload_context(monkeypatch, tmp_path)
    cfg = {
        "version": 2,
        "current_context": "neon",
        "contexts": {
            "neon": {
                "storage": {
                    "backend": "postgres",
                    "postgres": {"dsn": "postgresql://u:p@ep-neon.example/db"},
                }
            },
            "local-postgres-test": {
                "storage": {
                    "backend": "postgres",
                    "postgres": {"dsn": "postgresql://u:p@localhost:5999/amprealize_test"},
                }
            },
        },
    }
    (tmp_path / "config.yaml").write_text(yaml.dump(cfg))
    monkeypatch.setenv("AMPREALIZE_CONTEXT", "local-postgres-test")
    import amprealize.context as ctx

    ctx = importlib.reload(ctx)
    name, cfg_obj = ctx.get_current_context()
    assert name == "local-postgres-test"
    assert cfg_obj.storage.backend == "postgres"
    assert "5999" in (cfg_obj.storage.postgres.dsn or "")


def test_active_local_context(monkeypatch, tmp_path):
    _reload_context(monkeypatch, tmp_path)
    cfg = {
        "version": 2,
        "current_context": "local",
        "contexts": {
            "local": {
                "storage": {
                    "backend": "postgres",
                    "postgres": {"dsn": "postgresql://u:p@localhost:5432/amprealize"},
                }
            },
        },
    }
    (tmp_path / "config.yaml").write_text(yaml.dump(cfg))
    import amprealize.context as ctx

    ctx = importlib.reload(ctx)
    remote, name, _reason = ctx.active_amprealize_context_targets_remote_postgres()
    assert remote is False
    assert name == "local"


def test_check_port_conflicts_neon_does_not_conflict_with_localhost(monkeypatch, tmp_path):
    from amprealize.context import check_port_conflicts

    _reload_context(monkeypatch, tmp_path)
    ctxs = {
        "neon": {
            "storage": {
                "backend": "postgres",
                "postgres": {
                    "dsn": "postgresql://u:p@ep-jolly-surf-amsysllf.c-5.us-east-1.aws.neon.tech:5432/neondb?sslmode=require"
                },
            }
        },
        "local-postgres-dev": {
            "storage": {
                "backend": "postgres",
                "postgres": {"dsn": "postgresql://u:p@localhost:5432/amprealize"},
            }
        },
    }
    assert check_port_conflicts(ctxs) == {}


def test_check_port_conflicts_localhost_and_127_flag_each_other(monkeypatch, tmp_path):
    from amprealize.context import check_port_conflicts

    _reload_context(monkeypatch, tmp_path)
    ctxs = {
        "a": {
            "storage": {
                "backend": "postgres",
                "postgres": {"dsn": "postgresql://u:p@localhost:5432/a"},
            }
        },
        "b": {
            "storage": {
                "backend": "postgres",
                "postgres": {"dsn": "postgresql://u:p@127.0.0.1:5432/b"},
            }
        },
    }
    c = check_port_conflicts(ctxs)
    assert "a" in c and c["a"][0] == "b"


def test_check_port_conflicts_same_dsn_aliases_no_conflict(monkeypatch, tmp_path):
    """Standard local contexts share one DSN — not an actionable port conflict."""
    from amprealize.context import check_port_conflicts

    _reload_context(monkeypatch, tmp_path)
    dsn = "postgresql://amprealize:x@localhost:5432/amprealize"
    ctxs = {
        "local-postgres-dev": {
            "storage": {"backend": "postgres", "postgres": {"dsn": dsn}},
        },
        "local-postgres-test": {
            "storage": {"backend": "postgres", "postgres": {"dsn": dsn}},
        },
    }
    assert check_port_conflicts(ctxs) == {}


def test_check_port_conflicts_different_dsn_same_host_port(monkeypatch, tmp_path):
    from amprealize.context import check_port_conflicts

    _reload_context(monkeypatch, tmp_path)
    ctxs = {
        "a": {
            "storage": {
                "backend": "postgres",
                "postgres": {"dsn": "postgresql://u:p@localhost:5432/db_a"},
            }
        },
        "b": {
            "storage": {
                "backend": "postgres",
                "postgres": {"dsn": "postgresql://u:p@localhost:5432/db_b"},
            }
        },
    }
    c = check_port_conflicts(ctxs)
    assert "a" in c and c["a"][0] == "b"


def test_suggest_orders_priority(monkeypatch, tmp_path):
    _reload_context(monkeypatch, tmp_path)
    cfg = {
        "version": 2,
        "current_context": "neon",
        "contexts": {
            "neon": {
                "storage": {
                    "backend": "postgres",
                    "postgres": {"dsn": "postgresql://u:p@cloud.example/db"},
                }
            },
            "alpha": {
                "storage": {
                    "backend": "postgres",
                    "postgres": {"dsn": "postgresql://u:p@localhost:5432/a"},
                }
            },
            "local-test": {
                "storage": {
                    "backend": "postgres",
                    "postgres": {"dsn": "postgresql://u:p@localhost:5432/b"},
                }
            },
            "local-postgres-dev": {
                "storage": {
                    "backend": "postgres",
                    "postgres": {"dsn": "postgresql://u:p@127.0.0.1:5432/dev"},
                }
            },
            "local-postgres-test": {
                "storage": {
                    "backend": "postgres",
                    "postgres": {"dsn": "postgresql://u:p@localhost:5432/t"},
                }
            },
            "local-postgres": {
                "storage": {
                    "backend": "postgres",
                    "postgres": {"dsn": "postgresql://u:p@127.0.0.1:5432/c"},
                }
            },
        },
    }
    (tmp_path / "config.yaml").write_text(yaml.dump(cfg))
    import amprealize.context as ctx

    ctx = importlib.reload(ctx)
    names = ctx.suggest_local_postgres_context_names()
    assert names[:4] == [
        "local-postgres-test",
        "local-test",
        "local-postgres-dev",
        "local-postgres",
    ]
    assert names[4:] == ["alpha"]
