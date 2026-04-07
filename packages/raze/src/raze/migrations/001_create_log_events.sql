-- Raze Structured Logging: TimescaleDB Schema
-- Migration: 001_create_log_events
--
-- This creates the log_events hypertable for structured log storage.
-- The schema includes versioning for forward compatibility.

-- Enable TimescaleDB extension (if not already enabled)
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- Create the log events table
CREATE TABLE IF NOT EXISTS log_events (
    -- Primary key: UUID for global uniqueness
    log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Schema version for forward compatibility (enables migrations)
    schema_version TEXT NOT NULL DEFAULT 'v1',

    -- Timestamp: When the log event occurred (UTC)
    -- This is the hypertable partition column
    event_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Log level: TRACE, DEBUG, INFO, WARNING, ERROR, CRITICAL
    level TEXT NOT NULL,

    -- Service name: The component that generated this log
    service TEXT NOT NULL,

    -- Human-readable message
    message TEXT NOT NULL,

    -- Correlation IDs for distributed tracing
    run_id TEXT,           -- Execution run ID
    action_id TEXT,        -- Action ID within run
    session_id TEXT,       -- User session ID

    -- Actor surface: Which surface generated this log
    -- Values: api, cli, vscode, web, mcp, system
    actor_surface TEXT,

    -- Structured context: Additional fields as JSONB
    -- Enables flexible querying with GIN index
    context JSONB NOT NULL DEFAULT '{}',

    -- Metadata: When this record was inserted
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Convert to hypertable with 1-day chunks
-- This enables efficient time-range queries and automatic data management
SELECT create_hypertable(
    'log_events',
    'event_timestamp',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

-- Create indexes for common query patterns
-- B-tree index on timestamp for range scans (hypertable already optimizes this)
CREATE INDEX IF NOT EXISTS idx_log_events_timestamp
    ON log_events (event_timestamp DESC);

-- Index on log level for filtering by severity
CREATE INDEX IF NOT EXISTS idx_log_events_level
    ON log_events (level);

-- Index on service for filtering by component
CREATE INDEX IF NOT EXISTS idx_log_events_service
    ON log_events (service);

-- Partial indexes on correlation IDs (most logs won't have all IDs)
CREATE INDEX IF NOT EXISTS idx_log_events_run_id
    ON log_events (run_id)
    WHERE run_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_log_events_action_id
    ON log_events (action_id)
    WHERE action_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_log_events_session_id
    ON log_events (session_id)
    WHERE session_id IS NOT NULL;

-- Index on actor surface for filtering by origin
CREATE INDEX IF NOT EXISTS idx_log_events_actor_surface
    ON log_events (actor_surface)
    WHERE actor_surface IS NOT NULL;

-- GIN index on JSONB context for flexible querying
-- Supports @>, ?, ?|, ?& operators
CREATE INDEX IF NOT EXISTS idx_log_events_context
    ON log_events USING GIN (context);

-- Composite index for common dashboard queries
CREATE INDEX IF NOT EXISTS idx_log_events_service_level_ts
    ON log_events (service, level, event_timestamp DESC);

-- Enable compression on older chunks (optional, improves storage efficiency)
-- Compress chunks older than 7 days
ALTER TABLE log_events SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'service,level',
    timescaledb.compress_orderby = 'event_timestamp DESC'
);

-- Add compression policy: compress chunks older than 7 days
SELECT add_compression_policy('log_events', INTERVAL '7 days', if_not_exists => TRUE);

-- Add retention policy: drop chunks older than 90 days (optional)
-- Uncomment the line below to enable automatic data retention
-- SELECT add_retention_policy('log_events', INTERVAL '90 days', if_not_exists => TRUE);

-- Create a view for easy level-based querying
CREATE OR REPLACE VIEW log_events_by_level AS
SELECT
    level,
    COUNT(*) as count,
    MIN(event_timestamp) as first_seen,
    MAX(event_timestamp) as last_seen
FROM log_events
WHERE event_timestamp > NOW() - INTERVAL '24 hours'
GROUP BY level
ORDER BY
    CASE level
        WHEN 'CRITICAL' THEN 1
        WHEN 'ERROR' THEN 2
        WHEN 'WARNING' THEN 3
        WHEN 'INFO' THEN 4
        WHEN 'DEBUG' THEN 5
        WHEN 'TRACE' THEN 6
        ELSE 7
    END;

-- Create a view for service-level aggregation
CREATE OR REPLACE VIEW log_events_by_service AS
SELECT
    service,
    level,
    COUNT(*) as count,
    MIN(event_timestamp) as first_seen,
    MAX(event_timestamp) as last_seen
FROM log_events
WHERE event_timestamp > NOW() - INTERVAL '24 hours'
GROUP BY service, level
ORDER BY service,
    CASE level
        WHEN 'CRITICAL' THEN 1
        WHEN 'ERROR' THEN 2
        WHEN 'WARNING' THEN 3
        WHEN 'INFO' THEN 4
        WHEN 'DEBUG' THEN 5
        WHEN 'TRACE' THEN 6
        ELSE 7
    END;

-- Add comment for documentation
COMMENT ON TABLE log_events IS 'Raze structured logging events stored as a TimescaleDB hypertable';
COMMENT ON COLUMN log_events.schema_version IS 'Schema version for forward compatibility (currently v1)';
COMMENT ON COLUMN log_events.event_timestamp IS 'When the log event occurred (UTC) - hypertable partition column';
COMMENT ON COLUMN log_events.context IS 'Flexible JSONB context data with GIN index for querying';
