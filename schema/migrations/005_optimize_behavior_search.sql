-- Optimize BehaviorService MCP retrieval.
--
-- These trigram indexes support cache-miss candidate narrowing for
-- behaviors.getForTask / behaviors.search without changing persisted data.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS idx_behaviors_search_text_trgm
    ON behavior.behaviors
    USING GIN (
        lower(
            concat_ws(
                ' ',
                name,
                description,
                array_to_string(keywords, ' '),
                category,
                role,
                triggers::text,
                steps::text
            )
        ) gin_trgm_ops
    );

CREATE INDEX IF NOT EXISTS idx_behavior_versions_search_text_trgm
    ON behavior.behavior_versions
    USING GIN (
        lower(
            concat_ws(
                ' ',
                name,
                description,
                triggers::text,
                steps::text
            )
        ) gin_trgm_ops
    );
