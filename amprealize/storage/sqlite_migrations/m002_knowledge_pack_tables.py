"""002 — Knowledge Pack tables for local/OSS mode.

Translates the four Postgres tables from
``migrations/versions/20260318_add_knowledge_pack_tables.py`` into
SQLite-compatible DDL.

Key translations (same as m001):
- JSONB → TEXT (store JSON strings)
- TEXT[] / ARRAY → TEXT (store JSON arrays as strings)
- TIMESTAMPTZ → TEXT (ISO-8601)
- server_default now() → datetime('now')
- Composite primary key on manifests
"""

VERSION = 2
NAME = "knowledge_pack_tables"

SQL = """
-- ==========================================================================
-- KNOWLEDGE PACK TABLES
-- ==========================================================================

CREATE TABLE IF NOT EXISTS knowledge_pack_sources (
    source_id           VARCHAR(64) PRIMARY KEY,
    source_type         VARCHAR(16) NOT NULL,       -- file | service
    ref                 TEXT NOT NULL,
    scope               VARCHAR(32) NOT NULL DEFAULT 'canonical',
    owner               VARCHAR(128),
    version_hash        VARCHAR(64),
    generation_eligible INTEGER DEFAULT 1,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_kp_sources_scope ON knowledge_pack_sources (scope);

CREATE TABLE IF NOT EXISTS knowledge_pack_manifests (
    pack_id             VARCHAR(128) NOT NULL,
    version             VARCHAR(32)  NOT NULL,
    manifest_json       TEXT NOT NULL,               -- JSON blob (JSONB on Postgres)
    status              VARCHAR(16)  NOT NULL DEFAULT 'draft',
    created_by          VARCHAR(128),
    created_at          TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (pack_id, version)
);
CREATE INDEX IF NOT EXISTS ix_kp_manifests_status ON knowledge_pack_manifests (status);

CREATE TABLE IF NOT EXISTS knowledge_pack_overlays (
    overlay_id          VARCHAR(128) PRIMARY KEY,
    pack_id             VARCHAR(128) NOT NULL,
    pack_version        VARCHAR(32)  NOT NULL,
    kind                VARCHAR(16)  NOT NULL,       -- task | surface | role
    applies_to          TEXT DEFAULT '{}',           -- JSON (JSONB on Postgres)
    instructions        TEXT DEFAULT '[]',           -- JSON (JSONB on Postgres)
    retrieval_keywords  TEXT DEFAULT '[]',           -- JSON array (TEXT[] on Postgres)
    priority            INTEGER DEFAULT 0,
    created_at          TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_kp_overlays_pack ON knowledge_pack_overlays (pack_id, pack_version);
CREATE INDEX IF NOT EXISTS ix_kp_overlays_kind ON knowledge_pack_overlays (kind);

CREATE TABLE IF NOT EXISTS knowledge_pack_activations (
    activation_id       VARCHAR(64) PRIMARY KEY,
    workspace_id        VARCHAR(128) NOT NULL,
    pack_id             VARCHAR(128) NOT NULL,
    pack_version        VARCHAR(32)  NOT NULL,
    profile             VARCHAR(64),
    activated_at        TEXT DEFAULT (datetime('now')),
    activated_by        VARCHAR(128),
    status              VARCHAR(16)  NOT NULL DEFAULT 'active'
);
CREATE INDEX IF NOT EXISTS ix_kp_activations_workspace ON knowledge_pack_activations (workspace_id);
CREATE INDEX IF NOT EXISTS ix_kp_activations_pack ON knowledge_pack_activations (pack_id, pack_version);
"""
