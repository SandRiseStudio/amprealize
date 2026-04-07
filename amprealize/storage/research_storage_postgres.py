"""PostgreSQL storage backend for the Research Service.

Replaces the local SQLite ResearchStorage with multi-tenant PostgreSQL
backed by RLS policies on the ``research`` schema.  Each method accepts
explicit ``owner_id`` / ``org_id`` / ``project_id`` so the caller
(ResearchService) can thread identity from the session context.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from amprealize.research_contracts import (
    ComprehensionResult,
    EvaluationResult,
    IngestedPaper,
    Recommendation,
)

logger = logging.getLogger(__name__)


class ResearchStoragePostgres:
    """PostgreSQL-backed research storage with RLS."""

    def __init__(self, pool: Any) -> None:
        """
        Args:
            pool: A ``PostgresPool`` instance.
        """
        self._pool = pool

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    def save_evaluation(
        self,
        paper: IngestedPaper,
        comprehension: ComprehensionResult,
        evaluation: EvaluationResult,
        recommendation: Recommendation,
        *,
        owner_id: str,
        org_id: Optional[str] = None,
        project_id: Optional[str] = None,
        visibility: str = "PRIVATE",
    ) -> None:
        """Persist a full evaluation pipeline result to PostgreSQL."""

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, owner_id)
            now = datetime.now(timezone.utc).isoformat()

            with conn.cursor() as cur:
                # Upsert paper
                cur.execute(
                    """
                    INSERT INTO research.papers
                        (id, title, authors, source_url, source_type, arxiv_id,
                         publication_date, raw_text, sections, metadata,
                         owner_id, org_id, project_id, visibility, created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (id) DO UPDATE SET
                        title = EXCLUDED.title,
                        authors = EXCLUDED.authors,
                        source_url = EXCLUDED.source_url,
                        raw_text = EXCLUDED.raw_text,
                        sections = EXCLUDED.sections,
                        metadata = EXCLUDED.metadata
                    """,
                    (
                        paper.id,
                        paper.metadata.title,
                        json.dumps(paper.metadata.authors),
                        paper.metadata.source_url,
                        paper.source_type.value,
                        paper.metadata.arxiv_id,
                        paper.metadata.publication_date,
                        paper.raw_text,
                        json.dumps([s.to_dict() for s in paper.sections]),
                        json.dumps(paper.metadata.to_dict()),
                        owner_id,
                        org_id,
                        project_id,
                        visibility,
                        now,
                    ),
                )

                # Comprehension
                comp_id = f"comp_{uuid4().hex[:12]}"
                cur.execute(
                    """
                    INSERT INTO research.comprehensions
                        (id, paper_id, core_idea, problem_addressed, proposed_solution,
                         key_contributions, technical_approach, claimed_results,
                         novelty_score, novelty_rationale, comprehension_confidence,
                         key_terms, llm_model, created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        comp_id,
                        paper.id,
                        comprehension.core_idea,
                        comprehension.problem_addressed,
                        comprehension.proposed_solution,
                        json.dumps(comprehension.key_contributions),
                        comprehension.technical_approach,
                        json.dumps([r.to_dict() for r in comprehension.claimed_results]),
                        comprehension.novelty_score,
                        comprehension.novelty_rationale,
                        comprehension.comprehension_confidence,
                        json.dumps(comprehension.key_terms),
                        comprehension.llm_model,
                        now,
                    ),
                )

                # Evaluation
                eval_id = f"eval_{uuid4().hex[:12]}"
                cur.execute(
                    """
                    INSERT INTO research.evaluations
                        (id, paper_id, comprehension_id,
                         relevance_score, relevance_rationale,
                         feasibility_score, feasibility_rationale,
                         novelty_score, novelty_rationale,
                         roi_score, roi_rationale,
                         safety_score, safety_rationale,
                         overall_score, honest_assessment,
                         conflicts,
                         implementation_complexity, maintenance_burden, expertise_gap,
                         estimated_effort, concerns, risks, potential_benefits,
                         structured_cons, competitive_landscape, value_proposition,
                         llm_model, created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        eval_id,
                        paper.id,
                        comp_id,
                        evaluation.relevance_score,
                        evaluation.relevance_rationale,
                        evaluation.feasibility_score,
                        evaluation.feasibility_rationale,
                        evaluation.novelty_score,
                        evaluation.novelty_rationale,
                        evaluation.roi_score,
                        evaluation.roi_rationale,
                        evaluation.safety_score,
                        evaluation.safety_rationale,
                        evaluation.overall_score,
                        evaluation.honest_assessment,
                        json.dumps([c.to_dict() for c in evaluation.conflicts_with_existing]),
                        evaluation.implementation_complexity.value,
                        evaluation.maintenance_burden.value,
                        evaluation.expertise_gap.value,
                        evaluation.estimated_effort,
                        json.dumps(evaluation.concerns),
                        json.dumps(evaluation.risks),
                        json.dumps(evaluation.potential_benefits),
                        json.dumps([sc.to_dict() for sc in evaluation.structured_cons]),
                        json.dumps([cl.to_dict() for cl in evaluation.competitive_landscape]),
                        json.dumps(evaluation.value_proposition.to_dict())
                            if evaluation.value_proposition else None,
                        evaluation.llm_model,
                        now,
                    ),
                )

                # Recommendation
                rec_id = f"rec_{uuid4().hex[:12]}"
                cur.execute(
                    """
                    INSERT INTO research.recommendations
                        (id, paper_id, evaluation_id, verdict, verdict_rationale,
                         executive_summary,
                         implementation_roadmap, adoption_strategy,
                         next_agent, priority,
                         blocking_dependencies, handoff_context, created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        rec_id,
                        paper.id,
                        eval_id,
                        recommendation.verdict.value,
                        recommendation.verdict_rationale,
                        recommendation.executive_summary,
                        json.dumps(recommendation.implementation_roadmap.to_dict())
                        if recommendation.implementation_roadmap
                        else None,
                        json.dumps(recommendation.adoption_strategy.to_dict())
                        if recommendation.adoption_strategy
                        else None,
                        recommendation.next_agent,
                        recommendation.priority.value,
                        json.dumps(recommendation.blocking_dependencies),
                        json.dumps(recommendation.handoff_context)
                        if recommendation.handoff_context
                        else None,
                        now,
                    ),
                )

            logger.info("Saved evaluation for paper %s (pg)", paper.id)

        self._pool.run_transaction(
            operation="research.save_evaluation",
            service_prefix="research",
            executor=_execute,
        )

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------

    def save_report(
        self,
        paper_id: str,
        report_markdown: str,
        title: Optional[str] = None,
        *,
        owner_id: str,
        org_id: Optional[str] = None,
    ) -> str:
        """Save a markdown report to PostgreSQL.

        Returns:
            The generated report ID.
        """
        report_id = f"report_{uuid4().hex[:12]}"

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, owner_id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO research.reports
                        (id, paper_id, report_markdown, word_count, created_at)
                    VALUES (%s, %s, %s, %s, NOW())
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        report_id,
                        paper_id,
                        report_markdown,
                        len(report_markdown.split()),
                    ),
                )

        self._pool.run_transaction(
            operation="research.save_report",
            service_prefix="research",
            executor=_execute,
        )
        logger.info("Saved report %s for paper %s (pg)", report_id, paper_id)
        return report_id

    def get_report(
        self,
        paper_id: str,
        *,
        owner_id: str,
        org_id: Optional[str] = None,
    ) -> Optional[str]:
        """Retrieve the markdown report for a paper (RLS-filtered)."""

        def _execute(conn: Any) -> Optional[str]:
            self._pool.set_tenant_context(conn, org_id, owner_id)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT report_markdown FROM research.reports WHERE paper_id = %s LIMIT 1",
                    (paper_id,),
                )
                row = cur.fetchone()
                return row[0] if row else None

        return self._pool.run_query(
            operation="research.get_report",
            service_prefix="research",
            executor=_execute,
        )

    def list_reports(
        self,
        limit: int = 20,
        *,
        owner_id: str,
        org_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List available research reports (RLS-filtered)."""

        def _execute(conn: Any) -> List[Dict[str, Any]]:
            self._pool.set_tenant_context(conn, org_id, owner_id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT rr.paper_id, p.title, r.verdict, e.overall_score,
                           rr.word_count, rr.created_at
                    FROM research.reports rr
                    JOIN research.papers p ON p.id = rr.paper_id
                    JOIN research.recommendations r ON r.paper_id = rr.paper_id
                    JOIN research.evaluations e ON e.paper_id = rr.paper_id
                    ORDER BY rr.created_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                return [
                    {
                        "paper_id": row[0],
                        "title": row[1],
                        "verdict": row[2],
                        "overall_score": row[3],
                        "word_count": row[4],
                        "created_at": row[5].isoformat() if row[5] else None,
                    }
                    for row in cur.fetchall()
                ]

        return self._pool.run_query(
            operation="research.list_reports",
            service_prefix="research",
            executor=_execute,
        )

    # ------------------------------------------------------------------
    # Paper queries
    # ------------------------------------------------------------------

    def search_papers(
        self,
        query: Optional[str] = None,
        verdict: Optional[str] = None,
        min_score: Optional[float] = None,
        max_score: Optional[float] = None,
        source_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        *,
        owner_id: str,
        org_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Search papers with filters (RLS-filtered)."""

        def _execute(conn: Any) -> Dict[str, Any]:
            self._pool.set_tenant_context(conn, org_id, owner_id)
            conditions: List[str] = []
            params: List[Any] = []

            if query:
                conditions.append("(p.title ILIKE %s OR c.core_idea ILIKE %s)")
                like = f"%{query}%"
                params.extend([like, like])
            if verdict:
                conditions.append("r.verdict = %s")
                params.append(verdict)
            if min_score is not None:
                conditions.append("e.overall_score >= %s")
                params.append(min_score)
            if max_score is not None:
                conditions.append("e.overall_score <= %s")
                params.append(max_score)
            if source_type:
                conditions.append("p.source_type = %s")
                params.append(source_type)

            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

            with conn.cursor() as cur:
                # Count
                cur.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM research.papers p
                    JOIN research.recommendations r ON r.paper_id = p.id
                    JOIN research.evaluations e ON e.paper_id = p.id
                    LEFT JOIN research.comprehensions c ON c.paper_id = p.id
                    {where}
                    """,
                    params,
                )
                total = cur.fetchone()[0]

                # Results
                cur.execute(
                    f"""
                    SELECT p.id, p.title, p.source_type,
                           e.overall_score, r.verdict,
                           c.core_idea, p.created_at
                    FROM research.papers p
                    JOIN research.recommendations r ON r.paper_id = p.id
                    JOIN research.evaluations e ON e.paper_id = p.id
                    LEFT JOIN research.comprehensions c ON c.paper_id = p.id
                    {where}
                    ORDER BY p.created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    params + [limit, offset],
                )
                papers = [
                    {
                        "paper_id": row[0],
                        "title": row[1],
                        "source_type": row[2],
                        "overall_score": row[3],
                        "verdict": row[4],
                        "core_idea": row[5],
                        "created_at": row[6].isoformat() if row[6] else None,
                    }
                    for row in cur.fetchall()
                ]

                return {
                    "papers": papers,
                    "total_count": total,
                    "has_more": (offset + limit) < total,
                }

        return self._pool.run_query(
            operation="research.search_papers",
            service_prefix="research",
            executor=_execute,
        )

    def get_paper(
        self,
        paper_id: str,
        *,
        owner_id: str,
        org_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Get full evaluation data for a single paper (RLS-filtered)."""

        def _execute(conn: Any) -> Optional[Dict[str, Any]]:
            self._pool.set_tenant_context(conn, org_id, owner_id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT p.id, p.title, p.authors, p.source_url, p.source_type,
                           p.arxiv_id, p.publication_date, p.visibility,
                           c.core_idea, c.problem_addressed, c.proposed_solution,
                           c.key_contributions, c.technical_approach,
                           c.novelty_score as comp_novelty, c.comprehension_confidence,
                           e.relevance_score, e.feasibility_score, e.novelty_score,
                           e.roi_score, e.safety_score, e.overall_score,
                           e.honest_assessment,
                           e.implementation_complexity, e.maintenance_burden,
                           e.estimated_effort, e.concerns, e.risks, e.potential_benefits,
                           e.structured_cons, e.competitive_landscape, e.value_proposition,
                           r.verdict, r.verdict_rationale,
                           r.executive_summary,
                           r.implementation_roadmap, r.adoption_strategy,
                           r.next_agent, r.priority, r.blocking_dependencies,
                           r.handoff_context,
                           rr.report_markdown,
                           p.created_at
                    FROM research.papers p
                    LEFT JOIN research.comprehensions c ON c.paper_id = p.id
                    LEFT JOIN research.evaluations e ON e.paper_id = p.id
                    LEFT JOIN research.recommendations r ON r.paper_id = p.id
                    LEFT JOIN research.reports rr ON rr.paper_id = p.id
                    WHERE p.id = %s
                    LIMIT 1
                    """,
                    (paper_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None

                return {
                    "paper_id": row[0],
                    "title": row[1],
                    "authors": row[2],
                    "source_url": row[3],
                    "source_type": row[4],
                    "arxiv_id": row[5],
                    "publication_date": row[6],
                    "visibility": row[7],
                    "core_idea": row[8],
                    "problem_addressed": row[9],
                    "proposed_solution": row[10],
                    "key_contributions": row[11],
                    "technical_approach": row[12],
                    "comp_novelty_score": row[13],
                    "comprehension_confidence": row[14],
                    "relevance_score": row[15],
                    "feasibility_score": row[16],
                    "novelty_score": row[17],
                    "roi_score": row[18],
                    "safety_score": row[19],
                    "overall_score": row[20],
                    "honest_assessment": row[21],
                    "implementation_complexity": row[22],
                    "maintenance_burden": row[23],
                    "estimated_effort": row[24],
                    "concerns": row[25],
                    "risks": row[26],
                    "potential_benefits": row[27],
                    "structured_cons": row[28],
                    "competitive_landscape": row[29],
                    "value_proposition": row[30],
                    "verdict": row[31],
                    "verdict_rationale": row[32],
                    "executive_summary": row[33],
                    "implementation_roadmap": row[34],
                    "adoption_strategy": row[35],
                    "next_agent": row[36],
                    "priority": row[37],
                    "blocking_dependencies": row[38],
                    "handoff_context": row[39],
                    "markdown_report": row[40],
                    "created_at": row[41].isoformat() if row[41] else None,
                }

        return self._pool.run_query(
            operation="research.get_paper",
            service_prefix="research",
            executor=_execute,
        )
