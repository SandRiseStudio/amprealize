"""001 — Initial schema: all core tables for local/OSS mode.

Translates the PostgreSQL schema across auth, credentials, behavior,
execution, workflow, board, consent, and audit schemas into
SQLite-compatible DDL.

Key translations:
- JSONB → TEXT (store JSON strings)
- TEXT[] / ARRAY → TEXT (store JSON arrays)
- TIMESTAMPTZ → TEXT (ISO-8601)
- UUID → TEXT or VARCHAR(36)
- gen_random_uuid() → application-level UUID generation
- Schema prefixes removed (no CREATE SCHEMA in SQLite)
- GIN indexes → regular or omitted
- RLS policies → application-level
- GENERATED ALWAYS AS ... STORED → omitted (SQLite ≥3.31 supports but
  not worth the compatibility risk for optional columns)
- Triggers for updated_at → omitted (handled at application layer)
"""

VERSION = 1
NAME = "initial_schema"

SQL = """
-- ==========================================================================
-- AUTH TABLES
-- ==========================================================================

CREATE TABLE IF NOT EXISTS organizations (
    id              VARCHAR(36) PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    slug            VARCHAR(128) UNIQUE,
    display_name    VARCHAR(255),
    plan            VARCHAR(64) DEFAULT 'free',
    status          VARCHAR(64) DEFAULT 'active',
    stripe_customer_id VARCHAR(255),
    settings        TEXT DEFAULT '{}',
    metadata        TEXT DEFAULT '{}',
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS users (
    id              VARCHAR(36) PRIMARY KEY,
    email           VARCHAR(255) NOT NULL UNIQUE,
    password_hash   VARCHAR(255),
    display_name    VARCHAR(255),
    avatar_url      TEXT,
    is_active       INTEGER DEFAULT 1,
    email_verified  INTEGER DEFAULT 0,
    email_verified_at TEXT,
    last_login_at   TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    metadata        TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS org_memberships (
    membership_id   VARCHAR(36) PRIMARY KEY,
    org_id          VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id         VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role            VARCHAR(64) DEFAULT 'member',
    invited_by      VARCHAR(36),
    invited_at      TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(org_id, user_id)
);

CREATE TABLE IF NOT EXISTS projects (
    project_id      VARCHAR(36) PRIMARY KEY,
    org_id          VARCHAR(36) REFERENCES organizations(id) ON DELETE SET NULL,
    name            VARCHAR(255) NOT NULL,
    slug            VARCHAR(128),
    description     TEXT,
    visibility      VARCHAR(64) DEFAULT 'private',
    local_project_path TEXT,
    settings        TEXT DEFAULT '{}',
    created_by      VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    owner_id        VARCHAR(255) NOT NULL,
    archived_at     TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_projects_owner_id ON projects (owner_id);

CREATE TABLE IF NOT EXISTS project_memberships (
    membership_id   VARCHAR(36) PRIMARY KEY,
    project_id      VARCHAR(36) NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    user_id         VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role            VARCHAR(64) DEFAULT 'member',
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(project_id, user_id)
);

CREATE TABLE IF NOT EXISTS subscriptions (
    subscription_id VARCHAR(36) PRIMARY KEY,
    org_id          VARCHAR(36) REFERENCES organizations(id) ON DELETE CASCADE,
    user_id         VARCHAR(36) REFERENCES users(id) ON DELETE CASCADE,
    plan            VARCHAR(64) DEFAULT 'free',
    status          VARCHAR(64) DEFAULT 'active',
    stripe_subscription_id VARCHAR(255),
    current_period_start TEXT,
    current_period_end   TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id              VARCHAR(36) PRIMARY KEY,
    user_id         VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash      VARCHAR(255) NOT NULL,
    device_info     TEXT DEFAULT '{}',
    ip_address      VARCHAR(45),
    expires_at      TEXT NOT NULL,
    created_at      TEXT DEFAULT (datetime('now')),
    last_used_at    TEXT
);

CREATE TABLE IF NOT EXISTS api_keys (
    id              VARCHAR(36) PRIMARY KEY,
    user_id         VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    org_id          VARCHAR(36) REFERENCES organizations(id) ON DELETE CASCADE,
    name            VARCHAR(255) NOT NULL,
    key_prefix      VARCHAR(16) NOT NULL,
    key_hash        VARCHAR(255) NOT NULL,
    scopes          TEXT DEFAULT '[]',
    expires_at      TEXT,
    last_used_at    TEXT,
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS federated_identities (
    id              VARCHAR(36) PRIMARY KEY,
    user_id         VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider        VARCHAR(50) NOT NULL,
    provider_user_id VARCHAR(255) NOT NULL,
    provider_email  VARCHAR(255),
    provider_username VARCHAR(255),
    provider_display_name VARCHAR(255),
    provider_avatar_url TEXT,
    access_token_encrypted TEXT,
    refresh_token_encrypted TEXT,
    token_expires_at TEXT,
    scopes          TEXT,
    raw_profile     TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    last_used_at    TEXT,
    UNIQUE(provider, provider_user_id)
);

CREATE TABLE IF NOT EXISTS mfa_devices (
    id              VARCHAR(36) PRIMARY KEY,
    user_id         VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device_type     VARCHAR(50) DEFAULT 'totp',
    device_name     VARCHAR(255),
    secret_encrypted TEXT NOT NULL,
    backup_codes_encrypted TEXT,
    is_verified     INTEGER DEFAULT 0,
    is_primary      INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now')),
    verified_at     TEXT,
    last_used_at    TEXT
);

CREATE TABLE IF NOT EXISTS service_principals (
    id              VARCHAR(36) PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    client_id       VARCHAR(255) NOT NULL UNIQUE,
    client_secret_hash TEXT NOT NULL,
    allowed_scopes  TEXT DEFAULT '[]',
    rate_limit      INTEGER DEFAULT 100,
    role            VARCHAR(20) DEFAULT 'STUDENT' CHECK (role IN ('STRATEGIST','TEACHER','STUDENT','ADMIN','OBSERVER')),
    is_active       INTEGER DEFAULT 1,
    created_by      VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    last_used_at    TEXT,
    metadata        TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS consent_requests (
    id              VARCHAR(36) PRIMARY KEY,
    user_id         VARCHAR(255) NOT NULL,
    agent_id        VARCHAR(255) NOT NULL,
    tool_name       VARCHAR(255) NOT NULL,
    scopes          TEXT NOT NULL,
    context         TEXT,
    status          VARCHAR(50) NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','approved','denied','expired')),
    user_code       VARCHAR(20) NOT NULL UNIQUE,
    user_code_normalized VARCHAR(20) NOT NULL,
    verification_uri VARCHAR(500) NOT NULL,
    expires_at      TEXT NOT NULL,
    decided_at      TEXT,
    decision_by     VARCHAR(255),
    decision_reason TEXT,
    created_at      TEXT DEFAULT (datetime('now')) NOT NULL,
    updated_at      TEXT DEFAULT (datetime('now')) NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_consent_requests_user_code ON consent_requests (user_code_normalized);
CREATE INDEX IF NOT EXISTS ix_consent_requests_user_status ON consent_requests (user_id, status);
CREATE INDEX IF NOT EXISTS ix_consent_requests_expires ON consent_requests (expires_at);
CREATE INDEX IF NOT EXISTS ix_consent_requests_agent ON consent_requests (agent_id);

CREATE TABLE IF NOT EXISTS token_vault (
    id              VARCHAR(36) PRIMARY KEY,
    user_id         VARCHAR(255) NOT NULL,
    provider        VARCHAR(100) NOT NULL,
    token_type      VARCHAR(50) NOT NULL,
    encrypted_data  TEXT NOT NULL,
    scopes          TEXT,
    expires_at      TEXT,
    issued_at       TEXT DEFAULT (datetime('now')) NOT NULL,
    last_used_at    TEXT,
    rotation_count  INTEGER DEFAULT 0 NOT NULL,
    status          VARCHAR(50) DEFAULT 'active' NOT NULL,
    metadata        TEXT,
    created_at      TEXT DEFAULT (datetime('now')) NOT NULL,
    updated_at      TEXT DEFAULT (datetime('now')) NOT NULL,
    UNIQUE(user_id, provider, token_type)
);
CREATE INDEX IF NOT EXISTS ix_token_vault_user_id ON token_vault (user_id);
CREATE INDEX IF NOT EXISTS ix_token_vault_user_provider ON token_vault (user_id, provider);
CREATE INDEX IF NOT EXISTS ix_token_vault_status ON token_vault (status);
CREATE INDEX IF NOT EXISTS ix_token_vault_expires_at ON token_vault (expires_at);

CREATE TABLE IF NOT EXISTS token_blacklist (
    id              VARCHAR(36) PRIMARY KEY,
    token_hash      VARCHAR(64) NOT NULL UNIQUE,
    user_id         VARCHAR(255) NOT NULL,
    provider        VARCHAR(100) NOT NULL,
    reason          TEXT NOT NULL,
    revoked_at      TEXT NOT NULL,
    revoked_by      VARCHAR(255) NOT NULL,
    expires_at      TEXT,
    created_at      TEXT DEFAULT (datetime('now')) NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_token_blacklist_hash ON token_blacklist (token_hash);
CREATE INDEX IF NOT EXISTS ix_token_blacklist_user_id ON token_blacklist (user_id);

CREATE TABLE IF NOT EXISTS token_audit_log (
    id              VARCHAR(36) PRIMARY KEY,
    token_id        VARCHAR(36),
    user_id         VARCHAR(255) NOT NULL,
    provider        VARCHAR(100) NOT NULL,
    operation       VARCHAR(50) NOT NULL,
    status          VARCHAR(50) NOT NULL,
    details         TEXT,
    ip_address      VARCHAR(45),
    user_agent      TEXT,
    performed_by    VARCHAR(255) NOT NULL,
    created_at      TEXT DEFAULT (datetime('now')) NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_token_audit_log_user_id ON token_audit_log (user_id);
CREATE INDEX IF NOT EXISTS ix_token_audit_log_token_id ON token_audit_log (token_id);

CREATE TABLE IF NOT EXISTS device_sessions (
    device_code     VARCHAR(255) PRIMARY KEY,
    user_code       VARCHAR(20) NOT NULL UNIQUE,
    client_id       VARCHAR(255) NOT NULL,
    scopes          TEXT NOT NULL DEFAULT '[]',
    status          VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    approver        VARCHAR(255),
    approver_surface VARCHAR(50),
    denial_reason   VARCHAR(500),
    access_token    VARCHAR(255),
    refresh_token   VARCHAR(255),
    access_token_expires_at TEXT,
    refresh_token_expires_at TEXT,
    oauth_user_id   VARCHAR(255),
    oauth_username  VARCHAR(255),
    oauth_email     VARCHAR(255),
    oauth_display_name VARCHAR(255),
    oauth_avatar_url VARCHAR(1024),
    oauth_provider  VARCHAR(50),
    surface         VARCHAR(50) NOT NULL DEFAULT 'mcp',
    metadata        TEXT,
    poll_interval   INTEGER NOT NULL DEFAULT 5,
    created_at      TEXT DEFAULT (datetime('now')),
    expires_at      TEXT NOT NULL,
    approved_at     TEXT
);
CREATE INDEX IF NOT EXISTS ix_device_sessions_user_code ON device_sessions (user_code);
CREATE INDEX IF NOT EXISTS ix_device_sessions_expires_at ON device_sessions (expires_at);

CREATE TABLE IF NOT EXISTS github_app_installations (
    id                  VARCHAR(36) PRIMARY KEY,
    installation_id     INTEGER NOT NULL,
    app_id              INTEGER,
    account_type        VARCHAR(16) NOT NULL,
    account_login       VARCHAR(255) NOT NULL,
    account_id          INTEGER NOT NULL,
    account_avatar_url  TEXT,
    scope_type          VARCHAR(16) NOT NULL,
    scope_id            VARCHAR(36) NOT NULL,
    repository_selection VARCHAR(16),
    selected_repository_ids TEXT DEFAULT '[]',
    permissions         TEXT DEFAULT '{}',
    events              TEXT DEFAULT '[]',
    cached_token_encrypted TEXT,
    cached_token_expires_at TEXT,
    is_active           INTEGER DEFAULT 1,
    suspended_at        TEXT,
    suspended_reason    TEXT,
    installed_by        VARCHAR(36),
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now')),
    metadata            TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS github_app_installation_links (
    id              VARCHAR(36) PRIMARY KEY,
    installation_id INTEGER NOT NULL,
    scope_type      VARCHAR(16) NOT NULL,
    scope_id        VARCHAR(36) NOT NULL,
    linked_by       VARCHAR(36),
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(scope_type, scope_id)
);

CREATE TABLE IF NOT EXISTS user_project_github_links (
    id                  VARCHAR(36) PRIMARY KEY,
    user_id             VARCHAR(36) NOT NULL,
    project_id          VARCHAR(36) NOT NULL,
    link_type           VARCHAR(16) NOT NULL,
    github_credential_id VARCHAR(36),
    installation_link_id VARCHAR(36),
    is_preferred        INTEGER DEFAULT 0,
    priority            INTEGER DEFAULT 100,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now')),
    metadata            TEXT DEFAULT '{}',
    UNIQUE(user_id, project_id, link_type),
    CHECK (
        (link_type = 'pat' AND github_credential_id IS NOT NULL AND installation_link_id IS NULL) OR
        (link_type = 'app' AND installation_link_id IS NOT NULL AND github_credential_id IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS user_github_preferences (
    id                          VARCHAR(36) PRIMARY KEY,
    user_id                     VARCHAR(36) NOT NULL UNIQUE,
    default_pat_credential_id   VARCHAR(36),
    default_app_installation_id VARCHAR(36),
    auto_link_new_projects      INTEGER DEFAULT 0,
    prefer_app_over_pat         INTEGER DEFAULT 1,
    created_at                  TEXT DEFAULT (datetime('now')),
    updated_at                  TEXT DEFAULT (datetime('now')),
    metadata                    TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS github_credential_usage_log (
    id              VARCHAR(36) PRIMARY KEY,
    run_id          VARCHAR(36) NOT NULL,
    triggering_user_id VARCHAR(36),
    resolved_source VARCHAR(32) NOT NULL,
    credential_id   VARCHAR(36),
    project_id      VARCHAR(36) NOT NULL,
    org_id          VARCHAR(36),
    operations      TEXT DEFAULT '{}',
    success         INTEGER NOT NULL,
    error_message   TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    metadata        TEXT DEFAULT '{}'
);

-- ==========================================================================
-- CREDENTIALS TABLES
-- ==========================================================================

CREATE TABLE IF NOT EXISTS llm_credentials (
    id              VARCHAR(36) PRIMARY KEY,
    scope_type      VARCHAR(16) NOT NULL,
    scope_id        VARCHAR(36) NOT NULL,
    provider        VARCHAR(32) NOT NULL,
    name            VARCHAR(255) NOT NULL,
    key_prefix      VARCHAR(16) NOT NULL,
    key_encrypted   TEXT NOT NULL,
    is_valid        INTEGER DEFAULT 1,
    failure_count   INTEGER DEFAULT 0,
    last_used_at    TEXT,
    last_validated_at TEXT,
    created_by      VARCHAR(36) NOT NULL,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    metadata        TEXT DEFAULT '{}',
    UNIQUE(scope_type, scope_id, provider)
);

CREATE TABLE IF NOT EXISTS llm_credential_audit_log (
    id              VARCHAR(36) PRIMARY KEY,
    credential_id   VARCHAR(36) NOT NULL,
    action          VARCHAR(32) NOT NULL,
    actor_id        VARCHAR(36),
    actor_type      VARCHAR(16) DEFAULT 'user',
    details         TEXT DEFAULT '{}',
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS github_credentials (
    id              VARCHAR(36) PRIMARY KEY,
    scope_type      VARCHAR(16) NOT NULL,
    scope_id        VARCHAR(36) NOT NULL,
    token_type      VARCHAR(32) NOT NULL,
    name            VARCHAR(255) NOT NULL,
    token_prefix    VARCHAR(24) NOT NULL,
    token_encrypted TEXT NOT NULL,
    is_valid        INTEGER DEFAULT 1,
    failure_count   INTEGER DEFAULT 0,
    scopes          TEXT,
    rate_limit      INTEGER,
    rate_limit_remaining INTEGER,
    rate_limit_reset TEXT,
    last_used_at    TEXT,
    last_validated_at TEXT,
    github_username VARCHAR(64),
    github_user_id  INTEGER,
    created_by      VARCHAR(36) NOT NULL,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    metadata        TEXT DEFAULT '{}',
    UNIQUE(scope_type, scope_id)
);

CREATE TABLE IF NOT EXISTS github_credential_audit_log (
    id              VARCHAR(36) PRIMARY KEY,
    credential_id   VARCHAR(36) NOT NULL,
    action          VARCHAR(32) NOT NULL,
    actor_id        VARCHAR(36),
    actor_type      VARCHAR(16) DEFAULT 'user',
    details         TEXT DEFAULT '{}',
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ==========================================================================
-- BEHAVIOR TABLES
-- ==========================================================================

CREATE TABLE IF NOT EXISTS behaviors (
    id              VARCHAR(36) PRIMARY KEY,
    org_id          VARCHAR(36) REFERENCES organizations(id) ON DELETE CASCADE,
    name            VARCHAR(128) NOT NULL,
    namespace       VARCHAR(64) DEFAULT 'default',
    description     TEXT,
    category        VARCHAR(64),
    triggers        TEXT DEFAULT '[]',
    steps           TEXT DEFAULT '[]',
    role            VARCHAR(32),
    confidence_threshold REAL DEFAULT 0.8,
    keywords        TEXT DEFAULT '[]',
    version         INTEGER DEFAULT 1,
    is_active       INTEGER DEFAULT 1,
    is_deprecated   INTEGER DEFAULT 0,
    deprecation_reason TEXT,
    status          VARCHAR(32) DEFAULT 'ACTIVE',
    tags            TEXT DEFAULT '[]',
    latest_version  VARCHAR(32) DEFAULT '1',
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(org_id, namespace, name)
);

CREATE TABLE IF NOT EXISTS behavior_versions (
    id              VARCHAR(36) PRIMARY KEY,
    behavior_id     VARCHAR(36) NOT NULL REFERENCES behaviors(id) ON DELETE CASCADE,
    version         INTEGER NOT NULL,
    name            VARCHAR(128) NOT NULL,
    description     TEXT,
    triggers        TEXT DEFAULT '[]',
    steps           TEXT DEFAULT '[]',
    change_reason   TEXT,
    changed_by      VARCHAR(128),
    instruction     TEXT DEFAULT '',
    role_focus      VARCHAR(32) DEFAULT 'student',
    status          VARCHAR(32) DEFAULT 'APPROVED',
    confidence_score REAL,
    historical_validations TEXT DEFAULT '[]',
    proposed_by_role VARCHAR(32),
    pattern_id      VARCHAR(64),
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(behavior_id, version)
);

CREATE TABLE IF NOT EXISTS behavior_embeddings (
    id              VARCHAR(36) PRIMARY KEY,
    behavior_id     VARCHAR(36) REFERENCES behaviors(id) ON DELETE CASCADE,
    behavior_version INTEGER,
    embedding_model VARCHAR(64) DEFAULT 'text-embedding-3-small',
    embedding_data  TEXT NOT NULL,
    text_hash       VARCHAR(64) NOT NULL,
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(behavior_id, behavior_version, embedding_model)
);

CREATE TABLE IF NOT EXISTS behavior_executions (
    id              VARCHAR(36) PRIMARY KEY,
    behavior_id     VARCHAR(36) REFERENCES behaviors(id) ON DELETE CASCADE,
    run_id          VARCHAR(36) REFERENCES runs(id) ON DELETE SET NULL,
    action_id       VARCHAR(36) REFERENCES actions(id) ON DELETE SET NULL,
    success         INTEGER,
    tokens_saved    INTEGER,
    context         TEXT DEFAULT '{}',
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reflection_patterns (
    pattern_id      VARCHAR(64) PRIMARY KEY,
    run_id          VARCHAR(36),
    trace_id        VARCHAR(64),
    pattern_type    VARCHAR(64) NOT NULL,
    description     TEXT NOT NULL,
    frequency       INTEGER DEFAULT 1,
    confidence      REAL DEFAULT 0.5,
    context         TEXT,
    metadata        TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS behavior_candidates (
    candidate_id    VARCHAR(64) PRIMARY KEY,
    pattern_id      VARCHAR(64) REFERENCES reflection_patterns(pattern_id) ON DELETE SET NULL,
    name            VARCHAR(128) NOT NULL,
    summary         TEXT NOT NULL,
    triggers        TEXT,
    steps           TEXT,
    confidence      REAL DEFAULT 0.5,
    status          VARCHAR(32) DEFAULT 'proposed',
    role            VARCHAR(32) DEFAULT 'student',
    keywords        TEXT,
    historical_validation TEXT,
    reviewed_by     VARCHAR(128),
    reviewed_at     TEXT,
    merged_behavior_id VARCHAR(64),
    metadata        TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reflection_sessions (
    session_id      VARCHAR(64) PRIMARY KEY,
    run_id          VARCHAR(36),
    trace_id        VARCHAR(64),
    session_type    VARCHAR(32) DEFAULT 'automatic',
    patterns_extracted INTEGER DEFAULT 0,
    candidates_generated INTEGER DEFAULT 0,
    status          VARCHAR(32) DEFAULT 'pending',
    started_at      TEXT,
    completed_at    TEXT,
    error_message   TEXT,
    metadata        TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pattern_observations (
    observation_id  VARCHAR(64) PRIMARY KEY,
    pattern_hash    VARCHAR(64) NOT NULL,
    pattern_type    VARCHAR(64) NOT NULL,
    description     TEXT NOT NULL,
    run_id          VARCHAR(36) NOT NULL,
    trace_id        VARCHAR(64),
    file_path       TEXT,
    line_range      VARCHAR(32),
    observed_at     TEXT DEFAULT (datetime('now')),
    metadata        TEXT
);

-- ==========================================================================
-- EXECUTION TABLES
-- NOTE: workflow_runs is referenced by runs, so create workflow tables first
-- ==========================================================================

CREATE TABLE IF NOT EXISTS workflow_templates (
    id              VARCHAR(36) PRIMARY KEY,
    org_id          VARCHAR(36) REFERENCES organizations(id) ON DELETE CASCADE,
    name            VARCHAR(128) NOT NULL,
    description     TEXT,
    version         INTEGER DEFAULT 1,
    steps           TEXT NOT NULL,
    triggers        TEXT,
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(org_id, name)
);

CREATE TABLE IF NOT EXISTS workflow_runs (
    id              VARCHAR(36) PRIMARY KEY,
    template_id     VARCHAR(36) REFERENCES workflow_templates(id) ON DELETE SET NULL,
    template_version INTEGER,
    status          VARCHAR(32) DEFAULT 'pending',
    current_step    INTEGER,
    context         TEXT,
    result          TEXT,
    error           TEXT,
    started_at      TEXT,
    completed_at    TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS workflow_step_runs (
    id              VARCHAR(36) PRIMARY KEY,
    workflow_run_id VARCHAR(36) NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
    step_index      INTEGER NOT NULL,
    step_name       VARCHAR(128) NOT NULL,
    status          VARCHAR(32) DEFAULT 'pending',
    action_id       VARCHAR(36),
    input_data      TEXT,
    output_data     TEXT,
    error           TEXT,
    started_at      TEXT,
    completed_at    TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(workflow_run_id, step_index)
);

CREATE TABLE IF NOT EXISTS task_cycles (
    id              VARCHAR(36) PRIMARY KEY,
    task_id         VARCHAR(255) NOT NULL,
    org_id          VARCHAR(36) REFERENCES organizations(id) ON DELETE SET NULL,
    current_phase   VARCHAR(32) DEFAULT 'PLANNING',
    status          VARCHAR(32) DEFAULT 'active',
    acceptance_criteria TEXT,
    timeout_config  TEXT,
    test_iteration  INTEGER DEFAULT 0,
    max_test_iterations INTEGER DEFAULT 5,
    metadata        TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    completed_at    TEXT
);

-- Now execution tables (runs depends on workflow_runs)

CREATE TABLE IF NOT EXISTS runs (
    id              VARCHAR(36) PRIMARY KEY,
    org_id          VARCHAR(36) REFERENCES organizations(id) ON DELETE SET NULL,
    project_id      VARCHAR(36) REFERENCES projects(project_id) ON DELETE SET NULL,
    user_id         VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    name            VARCHAR(256),
    status          VARCHAR(32) DEFAULT 'pending',
    workflow_run_id VARCHAR(36) REFERENCES workflow_runs(id) ON DELETE SET NULL,
    session_id      VARCHAR(128),
    actor_surface   VARCHAR(64),
    context         TEXT DEFAULT '{}',
    result          TEXT,
    error           TEXT,
    total_actions   INTEGER,
    completed_actions INTEGER,
    failed_actions  INTEGER,
    total_tokens_used INTEGER,
    total_tokens_saved INTEGER,
    workflow_id     VARCHAR(128),
    workflow_name   VARCHAR(256),
    started_at      TEXT,
    completed_at    TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_runs_workflow_id ON runs (workflow_id);

CREATE TABLE IF NOT EXISTS actions (
    id              VARCHAR(36) PRIMARY KEY,
    run_id          VARCHAR(36) REFERENCES runs(id) ON DELETE CASCADE,
    parent_action_id VARCHAR(36) REFERENCES actions(id) ON DELETE SET NULL,
    name            VARCHAR(128) NOT NULL,
    action_type     VARCHAR(64) NOT NULL,
    status          VARCHAR(32) DEFAULT 'pending',
    input_data      TEXT,
    output_data     TEXT,
    error           TEXT,
    behaviors_applied TEXT,
    tokens_used     INTEGER,
    tokens_saved    INTEGER,
    duration_ms     INTEGER,
    started_at      TEXT,
    completed_at    TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS run_steps (
    id              VARCHAR(36) PRIMARY KEY,
    run_id          VARCHAR(36) NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    step_number     INTEGER NOT NULL,
    name            VARCHAR(128) NOT NULL,
    status          VARCHAR(32) DEFAULT 'pending',
    action_id       VARCHAR(36) REFERENCES actions(id) ON DELETE SET NULL,
    input_data      TEXT,
    output_data     TEXT,
    error           TEXT,
    started_at      TEXT,
    completed_at    TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(run_id, step_number)
);

CREATE TABLE IF NOT EXISTS replays (
    id              VARCHAR(36) PRIMARY KEY,
    action_id       VARCHAR(36) NOT NULL REFERENCES actions(id) ON DELETE CASCADE,
    replay_type     VARCHAR(32) NOT NULL,
    status          VARCHAR(32) DEFAULT 'pending',
    original_input  TEXT,
    modified_input  TEXT,
    replay_output   TEXT,
    comparison      TEXT,
    error           TEXT,
    metadata        TEXT,
    tags            TEXT,
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    completed_at    TEXT
);

CREATE TABLE IF NOT EXISTS agent_personas (
    id              VARCHAR(36) PRIMARY KEY,
    org_id          VARCHAR(36) REFERENCES organizations(id) ON DELETE CASCADE,
    name            VARCHAR(128) NOT NULL,
    description     TEXT,
    role            VARCHAR(32) NOT NULL,
    capabilities    TEXT,
    default_behaviors TEXT,
    system_prompt   TEXT,
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(org_id, name)
);

CREATE TABLE IF NOT EXISTS agent_assignments (
    id              VARCHAR(36) PRIMARY KEY,
    run_id          VARCHAR(36) NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    persona_id      VARCHAR(36) NOT NULL REFERENCES agent_personas(id) ON DELETE CASCADE,
    assigned_at     TEXT DEFAULT (datetime('now')),
    unassigned_at   TEXT,
    status          VARCHAR(32) DEFAULT 'active',
    context         TEXT
);

CREATE TABLE IF NOT EXISTS agents (
    agent_id        TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    slug            TEXT NOT NULL,
    description     TEXT NOT NULL,
    tags            TEXT DEFAULT '[]',
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    latest_version  TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('DRAFT','ACTIVE','DEPRECATED')),
    visibility      TEXT NOT NULL DEFAULT 'PRIVATE' CHECK (visibility IN ('PRIVATE','ORG','PUBLIC')),
    owner_id        TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    org_id          TEXT,
    published_at    TEXT,
    is_builtin      INTEGER DEFAULT 0,
    service_principal_id VARCHAR(36) REFERENCES service_principals(id) ON DELETE SET NULL,
    project_id      VARCHAR(36)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_agents_org_slug ON agents (org_id, slug);
CREATE INDEX IF NOT EXISTS ix_agents_project_id ON agents (project_id) WHERE project_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS agent_versions (
    agent_id        TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
    version         TEXT NOT NULL,
    mission         TEXT NOT NULL,
    role_alignment  TEXT NOT NULL CHECK (role_alignment IN ('STUDENT','TEACHER','STRATEGIST')),
    capabilities    TEXT,
    default_behaviors TEXT,
    playbook_content TEXT,
    status          TEXT NOT NULL CHECK (status IN ('DRAFT','ACTIVE','DEPRECATED')),
    created_at      TEXT DEFAULT (datetime('now')),
    created_by      TEXT NOT NULL,
    effective_from  TEXT,
    effective_to    TEXT,
    created_from    TEXT,
    metadata        TEXT,
    PRIMARY KEY (agent_id, version)
);

CREATE TABLE IF NOT EXISTS project_agent_assignments (
    id              VARCHAR(36) PRIMARY KEY,
    project_id      VARCHAR(36) NOT NULL,
    agent_id        TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
    assigned_by     VARCHAR(36) NOT NULL,
    assigned_at     TEXT DEFAULT (datetime('now')),
    unassigned_at   TEXT,
    config_overrides TEXT DEFAULT '{}',
    role            VARCHAR(50) DEFAULT 'contributor',
    status          VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active','inactive','removed')),
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(project_id, agent_id, status)
);

-- ==========================================================================
-- BOARD TABLES
-- ==========================================================================

CREATE TABLE IF NOT EXISTS boards (
    id              VARCHAR(36) PRIMARY KEY,
    org_id          VARCHAR(36) REFERENCES organizations(id) ON DELETE CASCADE,
    project_id      VARCHAR(36) REFERENCES projects(project_id) ON DELETE CASCADE,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    settings        TEXT,
    created_by      VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    display_number  INTEGER,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_boards_project_display_number ON boards (project_id, display_number);

CREATE TABLE IF NOT EXISTS columns (
    id              VARCHAR(36) PRIMARY KEY,
    board_id        VARCHAR(36) NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
    name            VARCHAR(255) NOT NULL,
    position        INTEGER NOT NULL,
    wip_limit       INTEGER,
    color           VARCHAR(32),
    status_mapping  VARCHAR(64),
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS work_items (
    id              VARCHAR(36) PRIMARY KEY,
    board_id        VARCHAR(36) NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
    column_id       VARCHAR(36) REFERENCES columns(id) ON DELETE SET NULL,
    title           VARCHAR(500) NOT NULL,
    description     TEXT,
    item_type       VARCHAR(64) DEFAULT 'task',
    status          VARCHAR(64) DEFAULT 'open',
    priority        INTEGER DEFAULT 0,
    position        INTEGER DEFAULT 0,
    assignee_id     VARCHAR(36),
    reporter_id     VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    run_id          VARCHAR(36) REFERENCES runs(id) ON DELETE SET NULL,
    labels          TEXT,
    metadata        TEXT,
    due_date        TEXT,
    assignee_type   VARCHAR(32),
    assigned_at     TEXT,
    assigned_by     VARCHAR(36),
    project_id      VARCHAR(36),
    org_id          VARCHAR(36),
    display_number  INTEGER,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_work_items_project_id ON work_items (project_id);
CREATE INDEX IF NOT EXISTS ix_work_items_org_id ON work_items (org_id);
CREATE INDEX IF NOT EXISTS ix_work_items_board_display_number ON work_items (board_id, display_number);

CREATE TABLE IF NOT EXISTS sprints (
    id              VARCHAR(36) PRIMARY KEY,
    board_id        VARCHAR(36) NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
    name            VARCHAR(255) NOT NULL,
    goal            TEXT,
    status          VARCHAR(32) DEFAULT 'planning',
    start_date      TEXT,
    end_date        TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS assignment_history (
    history_id          VARCHAR(32) PRIMARY KEY,
    project_id          VARCHAR(36),
    assignable_id       VARCHAR(64) NOT NULL,
    assignable_type     VARCHAR(32) NOT NULL CHECK (assignable_type IN ('story','task','epic','bug','feature')),
    assignee_id         VARCHAR(36),
    assignee_type       VARCHAR(32),
    action              VARCHAR(32) NOT NULL,
    performed_by        VARCHAR(36) NOT NULL,
    performed_at        TEXT DEFAULT (datetime('now')),
    previous_assignee_id VARCHAR(36),
    previous_assignee_type VARCHAR(32),
    reason              TEXT,
    metadata            TEXT DEFAULT '{}',
    org_id              VARCHAR(36)
);
CREATE INDEX IF NOT EXISTS ix_ah_assignable ON assignment_history (assignable_id, assignable_type);
CREATE INDEX IF NOT EXISTS ix_ah_assignee ON assignment_history (assignee_id);
CREATE INDEX IF NOT EXISTS ix_ah_project ON assignment_history (project_id);

CREATE TABLE IF NOT EXISTS work_item_comments (
    id              VARCHAR(36) PRIMARY KEY,
    work_item_id    VARCHAR(36) NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
    author_id       VARCHAR(36) NOT NULL,
    author_type     VARCHAR(32) NOT NULL CHECK (author_type IN ('user','agent')),
    content         TEXT NOT NULL,
    run_id          VARCHAR(36) REFERENCES runs(id) ON DELETE SET NULL,
    metadata        TEXT DEFAULT '{}',
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    org_id          VARCHAR(36)
);
CREATE INDEX IF NOT EXISTS ix_wic_work_item ON work_item_comments (work_item_id);
CREATE INDEX IF NOT EXISTS ix_wic_author ON work_item_comments (author_id);

CREATE TABLE IF NOT EXISTS project_counters (
    project_id      VARCHAR(255) NOT NULL,
    entity_type     VARCHAR(50) NOT NULL,
    next_number     INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (project_id, entity_type)
);

CREATE TABLE IF NOT EXISTS collaboration_workspaces (
    workspace_id    VARCHAR(64) PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    owner_id        VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    workspace_type  VARCHAR(32) DEFAULT 'shared',
    settings        TEXT,
    is_active       INTEGER,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS workspace_members (
    member_id       VARCHAR(64) PRIMARY KEY,
    workspace_id    VARCHAR(64) NOT NULL REFERENCES collaboration_workspaces(workspace_id) ON DELETE CASCADE,
    user_id         VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role            VARCHAR(32) DEFAULT 'editor',
    permissions     TEXT,
    joined_at       TEXT DEFAULT (datetime('now')),
    last_active_at  TEXT,
    is_active       INTEGER,
    UNIQUE(workspace_id, user_id)
);

CREATE TABLE IF NOT EXISTS collaboration_documents (
    document_id     VARCHAR(64) PRIMARY KEY,
    workspace_id    VARCHAR(64) NOT NULL REFERENCES collaboration_workspaces(workspace_id) ON DELETE CASCADE,
    title           VARCHAR(500) NOT NULL,
    content         TEXT,
    document_type   VARCHAR(32) DEFAULT 'text',
    version         INTEGER DEFAULT 1,
    locked_by       VARCHAR(36),
    locked_at       TEXT,
    lock_expires_at TEXT,
    created_by      VARCHAR(36) NOT NULL REFERENCES users(id),
    last_edited_by  VARCHAR(36),
    metadata        TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS document_versions (
    version_id      VARCHAR(64) PRIMARY KEY,
    document_id     VARCHAR(64) NOT NULL REFERENCES collaboration_documents(document_id) ON DELETE CASCADE,
    version_number  INTEGER NOT NULL,
    content         TEXT NOT NULL,
    edited_by       VARCHAR(36) NOT NULL,
    edit_summary    TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(document_id, version_number)
);

CREATE TABLE IF NOT EXISTS active_cursors (
    cursor_id       VARCHAR(64) PRIMARY KEY,
    document_id     VARCHAR(64) NOT NULL REFERENCES collaboration_documents(document_id) ON DELETE CASCADE,
    user_id         VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    position_line   INTEGER,
    position_column INTEGER,
    selection_start_line INTEGER,
    selection_start_column INTEGER,
    selection_end_line INTEGER,
    selection_end_column INTEGER,
    color           VARCHAR(32),
    last_updated    TEXT DEFAULT (datetime('now')),
    UNIQUE(document_id, user_id)
);

CREATE TABLE IF NOT EXISTS pending_edits (
    edit_id         VARCHAR(64) PRIMARY KEY,
    document_id     VARCHAR(64) NOT NULL REFERENCES collaboration_documents(document_id) ON DELETE CASCADE,
    user_id         VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    operation       VARCHAR(32) NOT NULL,
    position_start  INTEGER NOT NULL,
    position_end    INTEGER,
    content         TEXT,
    base_version    INTEGER NOT NULL,
    status          VARCHAR(32) DEFAULT 'pending',
    conflict_resolution TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    applied_at      TEXT
);

CREATE TABLE IF NOT EXISTS collaboration_events (
    event_id        VARCHAR(64) PRIMARY KEY,
    workspace_id    VARCHAR(64) NOT NULL REFERENCES collaboration_workspaces(workspace_id) ON DELETE CASCADE,
    document_id     VARCHAR(64) REFERENCES collaboration_documents(document_id) ON DELETE CASCADE,
    user_id         VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    event_type      VARCHAR(64) NOT NULL,
    event_data      TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ==========================================================================
-- CONSENT TABLES
-- ==========================================================================

CREATE TABLE IF NOT EXISTS consent_scopes (
    id              VARCHAR(36) PRIMARY KEY,
    name            VARCHAR(128) NOT NULL UNIQUE,
    description     TEXT,
    risk_level      VARCHAR(32) DEFAULT 'low',
    requires_mfa    INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS consents (
    id              VARCHAR(36) PRIMARY KEY,
    user_id         VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    scope_id        VARCHAR(36) NOT NULL REFERENCES consent_scopes(id) ON DELETE CASCADE,
    granted_at      TEXT DEFAULT (datetime('now')),
    expires_at      TEXT,
    revoked_at      TEXT,
    context         TEXT
);

-- ==========================================================================
-- AUDIT TABLES
-- ==========================================================================

CREATE TABLE IF NOT EXISTS audit_log (
    id              VARCHAR(36) PRIMARY KEY,
    event_type      VARCHAR(64) NOT NULL,
    actor_type      VARCHAR(32) NOT NULL,
    actor_id        VARCHAR(36),
    org_id          VARCHAR(36),
    resource_type   VARCHAR(64),
    resource_id     VARCHAR(255),
    action          VARCHAR(64) NOT NULL,
    status          VARCHAR(32) DEFAULT 'success',
    ip_address      VARCHAR(45),
    user_agent      TEXT,
    details         TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS checklists (
    id              VARCHAR(36) PRIMARY KEY,
    org_id          VARCHAR(36) REFERENCES organizations(id) ON DELETE SET NULL,
    name            VARCHAR(128) NOT NULL,
    description     TEXT,
    run_id          VARCHAR(36) REFERENCES runs(id) ON DELETE SET NULL,
    status          VARCHAR(32) DEFAULT 'pending',
    is_template     INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    completed_at    TEXT
);

CREATE TABLE IF NOT EXISTS checklist_steps (
    id              VARCHAR(36) PRIMARY KEY,
    checklist_id    VARCHAR(36) NOT NULL REFERENCES checklists(id) ON DELETE CASCADE,
    step_number     INTEGER NOT NULL,
    name            VARCHAR(256) NOT NULL,
    description     TEXT,
    status          VARCHAR(32) DEFAULT 'pending',
    is_required     INTEGER DEFAULT 1,
    behavior_ref    VARCHAR(128),
    evidence        TEXT,
    checked_by      VARCHAR(128),
    checked_at      TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(checklist_id, step_number)
);
"""
