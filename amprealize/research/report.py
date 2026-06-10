"""Research report renderer — Markdown output for evaluate pipeline."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from amprealize.research_contracts import (
        ComprehensionResult,
        EvaluationResult,
        IngestedPaper,
        Recommendation,
    )


def _one_line(text: str, max_len: int = 500, *, for_table_cell: bool = False) -> str:
    t = (text or "").strip().replace("\n", " ")
    if for_table_cell:
        t = t.replace("|", " · ")
    if len(t) > max_len:
        return t[: max_len - 1] + "…"
    return t


def _md_paragraph(text: str) -> str:
    """Turn free text into a safe markdown paragraph (no heading injection)."""
    if not (text or "").strip():
        return "_None provided._"
    # Indent so accidental "#" lines are not parsed as headings
    lines = [ln.rstrip() for ln in text.strip().splitlines() if ln.strip()]
    if not lines:
        return "_None provided._"
    return "\n".join(f"{ln}  " for ln in lines).rstrip()


def render_report(
    paper: "IngestedPaper",
    comprehension: "ComprehensionResult",
    evaluation: "EvaluationResult",
    recommendation: "Recommendation",
) -> str:
    """Render a full research evaluation as Markdown for storage and UI."""
    meta = paper.metadata
    title = meta.title or "Research evaluation"
    verdict = (
        recommendation.verdict.value
        if hasattr(recommendation.verdict, "value")
        else str(recommendation.verdict)
    )
    priority = (
        recommendation.priority.value
        if hasattr(recommendation.priority, "value")
        else str(recommendation.priority)
    )

    lines: list[str] = [
        f"# {title}",
        "",
        "## Paper",
        "",
        f"- **Paper ID:** `{paper.id}`",
        f"- **Source:** {meta.source_url or paper.source}",
        f"- **Words:** {paper.word_count:,}",
        f"- **Extraction confidence:** {paper.extraction_confidence:.0%}",
        "",
        "### Abstract",
        "",
        _md_paragraph(meta.abstract or "(no abstract)"),
        "",
        "## Comprehension",
        "",
        f"**Core idea:** {_one_line(comprehension.core_idea, 800)}",
        "",
        f"**Problem addressed:** {_one_line(comprehension.problem_addressed, 800)}",
        "",
        f"**Proposed solution:** {_one_line(comprehension.proposed_solution, 800)}",
        "",
        f"- **Novelty:** {comprehension.novelty_score:.1f}/10 — {_one_line(comprehension.novelty_rationale, 400)}",
        f"- **Comprehension confidence:** {comprehension.comprehension_confidence:.0%}",
        "",
    ]

    if comprehension.key_contributions:
        lines += ["### Key contributions", ""]
        lines += [f"- {c}" for c in comprehension.key_contributions]
        lines.append("")

    if comprehension.claimed_results:
        lines += ["### Claimed results", ""]
        for cr in comprehension.claimed_results:
            suffix = f" (_{cr.conditions}_)" if cr.conditions else ""
            lines.append(f"- **{cr.metric}:** {cr.improvement}{suffix}")
        lines.append("")

    lines += [
        "## Evaluation (Amprealize fit)",
        "",
        "| Dimension | Score | Notes |",
        "|-----------|------:|-------|",
        f"| Relevance | {evaluation.relevance_score:.1f} | {_one_line(evaluation.relevance_rationale, 200, for_table_cell=True)} |",
        f"| Feasibility | {evaluation.feasibility_score:.1f} | {_one_line(evaluation.feasibility_rationale, 200, for_table_cell=True)} |",
        f"| Novelty | {evaluation.novelty_score:.1f} | {_one_line(evaluation.novelty_rationale, 200, for_table_cell=True)} |",
        f"| ROI | {evaluation.roi_score:.1f} | {_one_line(evaluation.roi_rationale, 200, for_table_cell=True)} |",
        f"| Safety | {evaluation.safety_score:.1f} | {_one_line(evaluation.safety_rationale, 200, for_table_cell=True)} |",
        "",
        f"**Overall score:** {evaluation.overall_score:.2f}/10",
        "",
        "### Honest assessment",
        "",
        _md_paragraph(evaluation.honest_assessment or "(none)"),
        "",
    ]

    if evaluation.potential_benefits:
        lines += ["### Potential benefits", ""]
        lines += [f"- {b}" for b in evaluation.potential_benefits]
        lines.append("")

    if evaluation.concerns:
        lines += ["### Concerns", ""]
        lines += [f"- {c}" for c in evaluation.concerns]
        lines.append("")

    roadmap = recommendation.implementation_roadmap
    lines += [
        "## Recommendation",
        "",
        f"- **Verdict:** **{verdict}**",
        f"- **Priority:** {priority}",
        "",
        "### Rationale",
        "",
        _md_paragraph(recommendation.verdict_rationale),
        "",
    ]

    if recommendation.executive_summary:
        lines += ["### Executive summary", "", _md_paragraph(recommendation.executive_summary), ""]

    if roadmap and roadmap.proposed_steps:
        lines += ["### Implementation roadmap", ""]
        for step in sorted(roadmap.proposed_steps, key=lambda s: s.order):
            eff = f" ({step.effort})" if step.effort else ""
            lines.append(f"{step.order}. {step.description}{eff}")
        lines.append("")
        if roadmap.success_criteria:
            lines += ["#### Success criteria", ""]
            lines += [f"- {s}" for s in roadmap.success_criteria]
            lines.append("")

    strat = recommendation.adoption_strategy
    if strat:
        lines += [
            "### Adoption strategy",
            "",
            f"- **Approach:** {strat.approach}",
            "",
            _md_paragraph(strat.rationale),
            "",
        ]

    if recommendation.next_agent:
        lines.append(f"**Suggested next agent:** `{recommendation.next_agent}`")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
