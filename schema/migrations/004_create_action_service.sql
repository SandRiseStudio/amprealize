-- Action Service Schema (PostgresActionService)
-- Creates public.actions + public.replays tables for WORM action recording and replay tracking.
-- Always in `public` schema to avoid collision with execution.actions (Alembic-managed).

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ───────────────────────────────────────────────────────────────
-- Helper: updated_at trigger
-- ───────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ───────────────────────────────────────────────────────────────
-- Table: public.actions (WORM action log)
-- ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.actions (
    action_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor_id TEXT NOT NULL,
    actor_role TEXT NOT NULL,
    actor_surface TEXT NOT NULL CHECK (actor_surface IN ('cli', 'api', 'mcp', 'web')),
    artifact_path TEXT NOT NULL,
    summary TEXT NOT NULL,
    behaviors_cited JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    related_run_id TEXT,
    audit_log_event_id TEXT,
    checksum TEXT NOT NULL,
    replay_status TEXT NOT NULL DEFAULT 'NOT_STARTED'
        CHECK (replay_status IN ('NOT_STARTED', 'IN_PROGRESS', 'SUCCEEDED', 'FAILED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.actions IS 'WORM log of platform actions for audit and replay';

CREATE INDEX IF NOT EXISTS idx_actions_timestamp ON public.actions (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_actions_actor_id ON public.actions (actor_id);
CREATE INDEX IF NOT EXISTS idx_actions_related_run_id ON public.actions (related_run_id);
CREATE INDEX IF NOT EXISTS idx_actions_replay_status ON public.actions (replay_status);
CREATE INDEX IF NOT EXISTS idx_actions_behaviors_cited ON public.actions USING GIN (behaviors_cited);
CREATE INDEX IF NOT EXISTS idx_actions_metadata ON public.actions USING GIN (metadata);

DROP TRIGGER IF EXISTS set_actions_updated_at ON public.actions;
CREATE TRIGGER set_actions_updated_at
    BEFORE UPDATE ON public.actions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ───────────────────────────────────────────────────────────────
-- Table: public.replays (replay job tracking)
-- ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.replays (
    replay_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'IN_PROGRESS', 'SUCCEEDED', 'FAILED')),
    progress FLOAT NOT NULL DEFAULT 0.0 CHECK (progress >= 0.0 AND progress <= 1.0),
    logs JSONB NOT NULL DEFAULT '[]'::jsonb,
    failed_action_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    action_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    succeeded_action_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    audit_log_event_id TEXT,
    strategy TEXT NOT NULL DEFAULT 'sequential',
    actor_id TEXT,
    actor_role TEXT,
    actor_surface TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.replays IS 'Replay job status records for action replay orchestration';

CREATE INDEX IF NOT EXISTS idx_replays_status ON public.replays (status);
CREATE INDEX IF NOT EXISTS idx_replays_created_at ON public.replays (created_at DESC);

DROP TRIGGER IF EXISTS set_replays_updated_at ON public.replays;
CREATE TRIGGER set_replays_updated_at
    BEFORE UPDATE ON public.replays
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
