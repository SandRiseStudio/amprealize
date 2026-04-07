"""Create research schema with RLS policies.

Migrates research storage from local SQLite to PostgreSQL with:
- 5 tables: papers, comprehensions, evaluations, recommendations, reports
- Row-Level Security (RLS) on all tables
- Ownership via owner_id + optional org_id/project_id
- Visibility column on papers (PRIVATE, PROJECT, ORG, PUBLIC)

Revision ID: 20260327_create_research
Revises: 20260321_agent_presence
Create Date: 2026-03-27

Behavior: behavior_migrate_postgres_schema
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260327_create_research"
down_revision: Union[str, None] = "20260321_agent_presence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create research schema with all tables, indexes, and RLS policies."""

    # -- Schema ----------------------------------------------------------
    op.execute("CREATE SCHEMA IF NOT EXISTS research")

    # -- research.papers -------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS research.papers (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            authors JSONB,
            source_url TEXT,
            source_type VARCHAR(32) NOT NULL,
            arxiv_id TEXT,
            publication_date TEXT,
            raw_text TEXT NOT NULL,
            sections JSONB,
            metadata JSONB,

            -- Ownership / multi-tenancy
            owner_id TEXT NOT NULL,
            org_id TEXT,
            project_id TEXT,
            visibility VARCHAR(32) NOT NULL DEFAULT 'PRIVATE'
                CHECK (visibility IN ('PRIVATE', 'PROJECT', 'ORG', 'PUBLIC')),

            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by TEXT
        );
        """
    )

    # -- research.comprehensions -----------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS research.comprehensions (
            id TEXT PRIMARY KEY,
            paper_id TEXT NOT NULL REFERENCES research.papers(id) ON DELETE CASCADE,
            core_idea TEXT NOT NULL,
            problem_addressed TEXT,
            proposed_solution TEXT,
            key_contributions JSONB,
            technical_approach TEXT,
            claimed_results JSONB,
            novelty_score REAL,
            novelty_rationale TEXT,
            comprehension_confidence REAL,
            key_terms JSONB,
            llm_model TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )

    # -- research.evaluations --------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS research.evaluations (
            id TEXT PRIMARY KEY,
            paper_id TEXT NOT NULL REFERENCES research.papers(id) ON DELETE CASCADE,
            comprehension_id TEXT NOT NULL REFERENCES research.comprehensions(id) ON DELETE CASCADE,
            relevance_score REAL,
            relevance_rationale TEXT,
            feasibility_score REAL,
            feasibility_rationale TEXT,
            novelty_score REAL,
            novelty_rationale TEXT,
            roi_score REAL,
            roi_rationale TEXT,
            safety_score REAL,
            safety_rationale TEXT,
            overall_score REAL,
            conflicts JSONB,
            implementation_complexity VARCHAR(32),
            maintenance_burden VARCHAR(32),
            expertise_gap VARCHAR(32),
            estimated_effort TEXT,
            concerns JSONB,
            risks JSONB,
            potential_benefits JSONB,
            llm_model TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )

    # -- research.recommendations ----------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS research.recommendations (
            id TEXT PRIMARY KEY,
            paper_id TEXT NOT NULL REFERENCES research.papers(id) ON DELETE CASCADE,
            evaluation_id TEXT NOT NULL REFERENCES research.evaluations(id) ON DELETE CASCADE,
            verdict VARCHAR(32) NOT NULL,
            verdict_rationale TEXT,
            implementation_roadmap JSONB,
            next_agent TEXT,
            priority VARCHAR(8),
            blocking_dependencies JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by TEXT
        );
        """
    )

    # -- research.reports ------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS research.reports (
            id TEXT PRIMARY KEY,
            paper_id TEXT NOT NULL REFERENCES research.papers(id) ON DELETE CASCADE,
            report_markdown TEXT NOT NULL,
            word_count INTEGER,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            accessed_by TEXT
        );
        """
    )

    # -- Indexes ---------------------------------------------------------
    op.execute("CREATE INDEX IF NOT EXISTS idx_papers_source_type ON research.papers (source_type)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_papers_created_at ON research.papers (created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_papers_owner ON research.papers (owner_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_papers_project ON research.papers (project_id) WHERE project_id IS NOT NULL")
    op.execute("CREATE INDEX IF NOT EXISTS idx_papers_org ON research.papers (org_id) WHERE org_id IS NOT NULL")
    op.execute("CREATE INDEX IF NOT EXISTS idx_papers_visibility ON research.papers (visibility)")

    op.execute("CREATE INDEX IF NOT EXISTS idx_comprehensions_paper ON research.comprehensions (paper_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_evaluations_paper ON research.evaluations (paper_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_evaluations_score ON research.evaluations (overall_score)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_recommendations_paper ON research.recommendations (paper_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_recommendations_verdict ON research.recommendations (verdict)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_reports_paper ON research.reports (paper_id)")

    # -- RLS Policies ----------------------------------------------------
    # Enable RLS on all research tables
    op.execute("ALTER TABLE research.papers ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE research.comprehensions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE research.evaluations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE research.recommendations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE research.reports ENABLE ROW LEVEL SECURITY")

    # -- Papers: owner can do everything
    op.execute(
        """
        CREATE POLICY papers_owner_policy ON research.papers
            FOR ALL
            USING (owner_id = current_setting('app.current_user_id', TRUE))
        """
    )

    # -- Papers: project members can SELECT if visibility >= PROJECT
    op.execute(
        """
        CREATE POLICY papers_project_member_policy ON research.papers
            FOR SELECT
            USING (
                visibility IN ('PROJECT', 'ORG', 'PUBLIC')
                AND project_id IS NOT NULL
                AND EXISTS (
                    SELECT 1 FROM auth.project_memberships pm
                    WHERE pm.project_id = research.papers.project_id
                      AND pm.user_id = current_setting('app.current_user_id', TRUE)
                )
            )
        """
    )

    # -- Papers: org members can SELECT if visibility >= ORG
    op.execute(
        """
        CREATE POLICY papers_org_policy ON research.papers
            FOR SELECT
            USING (
                visibility IN ('ORG', 'PUBLIC')
                AND org_id IS NOT NULL
                AND org_id = current_setting('app.current_org_id', TRUE)
            )
        """
    )

    # -- Papers: anyone can SELECT PUBLIC papers
    op.execute(
        """
        CREATE POLICY papers_public_policy ON research.papers
            FOR SELECT
            USING (visibility = 'PUBLIC')
        """
    )

    # -- Child tables: inherit access from papers via subquery
    for child_table in ("comprehensions", "evaluations", "recommendations", "reports"):
        op.execute(
            f"""
            CREATE POLICY {child_table}_access_policy ON research.{child_table}
                FOR ALL
                USING (
                    paper_id IN (SELECT id FROM research.papers)
                )
            """
        )


def downgrade() -> None:
    """Drop the entire research schema."""
    op.execute("DROP SCHEMA IF EXISTS research CASCADE")
