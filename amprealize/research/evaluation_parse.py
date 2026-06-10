"""Normalize research LLM JSON list fields (evaluation, recommendation, comprehension).

Models sometimes return plain strings in arrays that the schema expects as objects.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from amprealize.research_contracts import (
    AffectedComponent,
    ClaimedResult,
    CompetitiveLandscapeItem,
    Complexity,
    ConflictItem,
    ImplementationStep,
    PaperSummary,
    ParsedSection,
    Priority,
    SourceType,
    StructuredCon,
    Verdict,
)

_log = logging.getLogger(__name__)

# LLMs sometimes emit MoSCoW / severity words instead of P1–P4.
_PRIORITY_ALIASES: Dict[str, Priority] = {
    "low": Priority.P4,
    "backlog": Priority.P4,
    "medium": Priority.P3,
    "normal": Priority.P3,
    "moderate": Priority.P3,
    "high": Priority.P2,
    "important": Priority.P2,
    "urgent": Priority.P1,
    "critical": Priority.P1,
    "p0": Priority.P1,
}


def parse_recommendation_priority(raw: Any) -> Priority:
    """Coerce recommendation JSON ``priority`` to a valid ``Priority`` (default P3)."""
    if raw is None:
        return Priority.P3
    if isinstance(raw, Priority):
        return raw
    s = str(raw).strip()
    if not s:
        return Priority.P3
    u = s.upper()
    if u in ("P1", "P2", "P3", "P4"):
        return Priority(u)  # type: ignore[arg-type]
    mapped = _PRIORITY_ALIASES.get(s.lower())
    if mapped is not None:
        return mapped
    try:
        return Priority(s)
    except ValueError:
        _log.debug("parse_recommendation_priority: unknown %r, defaulting to P3", raw)
        return Priority.P3


# LLMs emit compound labels (e.g. MEDIUM_HIGH) that are not enum members.
_COMPLEXITY_ALIASES: Dict[str, Complexity] = {
    "MEDIUM_HIGH": Complexity.HIGH,
    "HIGH_MEDIUM": Complexity.HIGH,
    "LOW_MEDIUM": Complexity.MEDIUM,
    "MEDIUM_LOW": Complexity.MEDIUM,
    "MODERATE": Complexity.MEDIUM,
    "MINIMAL": Complexity.LOW,
    "VERYLOW": Complexity.LOW,
    "NOT_APPLICABLE": Complexity.NONE,
    "NA": Complexity.NONE,
    "N_A": Complexity.NONE,
    "EXTREME": Complexity.VERY_HIGH,
    "VERYHIGH": Complexity.VERY_HIGH,
}


def parse_complexity(raw: Any, *, default: Complexity = Complexity.MEDIUM) -> Complexity:
    """Coerce evaluation JSON complexity fields to a valid ``Complexity``."""
    if raw is None:
        return default
    if isinstance(raw, Complexity):
        return raw
    s = str(raw).strip().upper().replace(" ", "_").replace("-", "_")
    if not s:
        return default
    mapped = _COMPLEXITY_ALIASES.get(s)
    if mapped is not None:
        return mapped
    try:
        return Complexity(s)
    except ValueError:
        _log.debug("parse_complexity: unknown %r, defaulting to %s", raw, default.value)
        return default


def coerce_estimated_effort(raw: Any) -> str:
    """Normalize evaluation ``estimated_effort`` to a string (LLMs may emit JSON objects)."""
    default = "M - Moderate effort"
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        try:
            out = json.dumps(raw, ensure_ascii=False)
        except (TypeError, ValueError):
            return default
        return out if out.strip() not in ("{}", "[]") else default
    s = str(raw).strip()
    return s if s else default


def paper_summaries_from_postgres_search(raw: Dict[str, Any]) -> List[PaperSummary]:
    """Turn ResearchStoragePostgres.search_papers payload into PaperSummary (skip bad entries)."""
    out: List[PaperSummary] = []
    papers_raw = raw.get("papers")
    if not isinstance(papers_raw, list):
        return out
    for p in papers_raw:
        if not isinstance(p, dict):
            _log.debug(
                "search_papers(postgres): skip non-dict paper entry type=%s",
                type(p).__name__,
            )
            continue
        pid = p.get("paper_id")
        if pid is None or str(pid).strip() == "":
            _log.debug("search_papers(postgres): skip row missing paper_id")
            continue
        try:
            st_raw = p.get("source_type")
            st = SourceType(st_raw) if st_raw else SourceType.URL
        except (ValueError, TypeError):
            st = SourceType.URL
        try:
            v_raw = p.get("verdict")
            verdict = Verdict(v_raw) if v_raw else Verdict.DEFER
        except (ValueError, TypeError):
            verdict = Verdict.DEFER
        try:
            score = float(p.get("overall_score", 0) or 0)
        except (TypeError, ValueError):
            score = 0.0
        try:
            ca = p.get("created_at")
            if ca:
                created_at = datetime.fromisoformat(str(ca).replace("Z", "+00:00"))
            else:
                created_at = datetime.now()
        except (ValueError, TypeError, OSError):
            created_at = datetime.now()
        out.append(
            PaperSummary(
                paper_id=str(pid),
                title=str(p.get("title", "") or ""),
                source_type=st,
                overall_score=score,
                verdict=verdict,
                core_idea=str(p.get("core_idea", "") or ""),
                created_at=created_at,
            )
        )
    return out


def paper_summary_from_sqlite_tuple(row: Any) -> Optional[PaperSummary]:
    """One PaperSummary from SQLite SELECT id, title, source_type, score, verdict, core_idea, created_at."""
    if row is None:
        return None
    try:
        n = len(row)
    except TypeError:
        _log.debug("search_papers(sqlite): skip row without len() type=%s", type(row).__name__)
        return None
    if n < 7:
        _log.debug("search_papers(sqlite): skip short row len=%s", n)
        return None
    try:
        paper_id = str(row[0]) if row[0] is not None else ""
        if not paper_id.strip():
            return None
        title = str(row[1] or "")
        try:
            st = SourceType(row[2]) if row[2] else SourceType.URL
        except (ValueError, TypeError):
            st = SourceType.URL
        try:
            score = float(row[3] or 0)
        except (TypeError, ValueError):
            score = 0.0
        try:
            verdict = Verdict(row[4]) if row[4] else Verdict.DEFER
        except (ValueError, TypeError):
            verdict = Verdict.DEFER
        core_idea = str(row[5] or "") if row[5] is not None else ""
        try:
            ca = row[6]
            if ca:
                created_at = datetime.fromisoformat(str(ca).replace("Z", "+00:00"))
            else:
                created_at = datetime.now()
        except (ValueError, TypeError, OSError):
            created_at = datetime.now()
        return PaperSummary(
            paper_id=paper_id,
            title=title,
            source_type=st,
            overall_score=score,
            verdict=verdict,
            core_idea=core_idea,
            created_at=created_at,
        )
    except (IndexError, TypeError) as exc:
        _log.debug("search_papers(sqlite): skip row error=%s", exc)
        return None


def paper_summaries_from_sqlite_rows(rows: Any) -> List[PaperSummary]:
    """Build PaperSummary list from sqlite3 cursor.fetchall() rows."""
    if not rows:
        return []
    out: List[PaperSummary] = []
    for row in rows:
        item = paper_summary_from_sqlite_tuple(row)
        if item is not None:
            out.append(item)
    return out


def parse_parsed_sections(raw: Any) -> List[ParsedSection]:
    """Build ParsedSection list from ingester output or stored JSON (dict or plain string rows)."""
    if not isinstance(raw, list):
        return []
    out: List[ParsedSection] = []
    for s in raw:
        if isinstance(s, dict):
            level_raw = s.get("level", 1)
            try:
                level = int(level_raw) if level_raw is not None else 1
            except (TypeError, ValueError):
                level = 1
            name = str(s.get("name", s.get("title", "")) or "")
            content = str(s.get("content", "") or "")
            out.append(ParsedSection(name=name, content=content, level=level))
        elif isinstance(s, str) and s.strip():
            out.append(ParsedSection(name="", content=s.strip(), level=1))
    return out


def ensure_str_list(raw: Any) -> List[str]:
    """Coerce JSON values into a list of non-empty strings (for bullet lists, deps, etc.)."""
    if raw is None:
        return []
    if isinstance(raw, str):
        s = raw.strip()
        return [s] if s else []
    if isinstance(raw, list):
        out: List[str] = []
        for x in raw:
            if x is None:
                continue
            if isinstance(x, str):
                t = x.strip()
                if t:
                    out.append(t)
            elif isinstance(x, (int, float, bool)):
                out.append(str(x))
        return out
    return [str(raw).strip()] if str(raw).strip() else []


def parse_claimed_results(raw: Any) -> List[ClaimedResult]:
    if not isinstance(raw, list):
        return []
    out: List[ClaimedResult] = []
    for r in raw:
        if isinstance(r, dict):
            out.append(
                ClaimedResult(
                    metric=str(r.get("metric", r.get("claim", "")) or ""),
                    improvement=str(r.get("improvement", r.get("evidence", "")) or ""),
                    conditions=str(r.get("conditions", "") or ""),
                )
            )
        elif isinstance(r, str) and r.strip():
            out.append(ClaimedResult(metric="", improvement=r.strip(), conditions=""))
    return out


def parse_affected_components(raw: Any) -> List[AffectedComponent]:
    if not isinstance(raw, list):
        return []
    out: List[AffectedComponent] = []
    for c in raw:
        if isinstance(c, dict):
            out.append(
                AffectedComponent(
                    path=str(c.get("path", "") or ""),
                    what_changes=str(c.get("what_changes", "") or ""),
                )
            )
        elif isinstance(c, str) and c.strip():
            out.append(AffectedComponent(path="", what_changes=c.strip()))
    return out


def parse_implementation_steps(raw: Any) -> List[ImplementationStep]:
    if not isinstance(raw, list):
        return []
    out: List[ImplementationStep] = []
    for i, s in enumerate(raw, start=1):
        if isinstance(s, dict):
            order_raw = s.get("order", i)
            try:
                order = int(order_raw) if order_raw is not None else i
            except (TypeError, ValueError):
                order = i
            out.append(
                ImplementationStep(
                    order=order,
                    description=str(s.get("description", "") or ""),
                    effort=str(s.get("effort", "M") or "M"),
                )
            )
        elif isinstance(s, str) and s.strip():
            out.append(ImplementationStep(order=i, description=s.strip(), effort="M"))
    return out


def parse_conflict_items(raw: Any) -> List[ConflictItem]:
    if not isinstance(raw, list):
        return []
    out: List[ConflictItem] = []
    for c in raw:
        if isinstance(c, dict):
            out.append(
                ConflictItem(
                    behavior_name=str(
                        c.get("behavior_name", c.get("component", "")) or ""
                    ),
                    description=str(c.get("description", "") or ""),
                    severity=str(c.get("severity", "medium") or "medium"),
                )
            )
        elif isinstance(c, str) and c.strip():
            out.append(
                ConflictItem(
                    behavior_name="",
                    description=c.strip(),
                    severity="medium",
                )
            )
    return out


def parse_competitive_landscape(raw: Any) -> List[CompetitiveLandscapeItem]:
    if not isinstance(raw, list):
        return []
    out: List[CompetitiveLandscapeItem] = []
    for item in raw:
        if isinstance(item, dict):
            diffs = item.get("differentiators", [])
            if isinstance(diffs, list):
                norm_diffs = [str(x) for x in diffs if x is not None]
            elif diffs is None:
                norm_diffs = []
            else:
                norm_diffs = [str(diffs)]
            raw_url = item.get("url")
            url: str | None = None
            if isinstance(raw_url, str) and raw_url.strip():
                url = raw_url.strip()
            out.append(
                CompetitiveLandscapeItem(
                    name=str(item.get("name", "") or ""),
                    category=str(item.get("category", "tool") or "tool"),
                    url=url,
                    description=str(item.get("description", "") or ""),
                    maturity=str(item.get("maturity", "unknown") or "unknown"),
                    overlap_description=str(item.get("overlap_description", "") or ""),
                    differentiators=norm_diffs,
                )
            )
        elif isinstance(item, str) and item.strip():
            s = item.strip()
            name = s if len(s) <= 200 else s[:199] + "…"
            out.append(
                CompetitiveLandscapeItem(
                    name=name,
                    category="tool",
                    description=s,
                    maturity="unknown",
                    overlap_description="",
                    differentiators=[],
                )
            )
    return out


def parse_structured_cons(raw: Any) -> List[StructuredCon]:
    if not isinstance(raw, list):
        return []
    out: List[StructuredCon] = []
    for con in raw:
        if isinstance(con, dict):
            out.append(
                StructuredCon(
                    description=str(con.get("description", "") or ""),
                    severity=str(con.get("severity", "medium") or "medium"),
                    likelihood=str(con.get("likelihood", "medium") or "medium"),
                    mitigation=str(con.get("mitigation", "") or ""),
                    category=str(con.get("category", "") or ""),
                )
            )
        elif isinstance(con, str) and con.strip():
            out.append(
                StructuredCon(
                    description=con.strip(),
                    severity="medium",
                    likelihood="medium",
                    mitigation="",
                    category="",
                )
            )
    return out
