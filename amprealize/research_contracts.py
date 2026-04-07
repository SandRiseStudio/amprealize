"""Research Service dataclasses for AI research evaluation pipeline.

These dataclasses define the contracts for the research evaluation pipeline:
- Ingestion of research papers (URL, markdown, PDF)
- LLM-driven comprehension and analysis
- Evaluation against Amprealize fit criteria
- Recommendation generation with implementation roadmaps

See RESEARCH_SERVICE_CONTRACT.md for full specification.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────


class SourceType(str, Enum):
    """Type of research paper source."""

    URL = "url"
    ARXIV = "arxiv"
    MARKDOWN = "markdown"
    PDF = "pdf"
    DOCX = "docx"


class Verdict(str, Enum):
    """Final recommendation verdict."""

    ADOPT = "ADOPT"  # Overall score >= 7.5, implement as described
    ADAPT = "ADAPT"  # Overall score 5.5-7.4, implement with modifications
    DEFER = "DEFER"  # Overall score 3.5-5.4, interesting but not now
    REJECT = "REJECT"  # Overall score < 3.5 OR safety score < 4.0


class Complexity(str, Enum):
    """Complexity rating for implementation factors."""

    NONE = "NONE"  # No complexity (not applicable)
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"


class Priority(str, Enum):
    """Priority level for implementation."""

    P1 = "P1"  # Urgent
    P2 = "P2"  # Important
    P3 = "P3"  # Normal
    P4 = "P4"  # Backlog


# ─────────────────────────────────────────────────────────────────────────────
# Base Mixin
# ─────────────────────────────────────────────────────────────────────────────


class SerializableMixin:
    """Mixin providing dataclass <-> dict conversion with Enum support."""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize dataclass to dictionary."""
        result: Dict[str, Any] = {}
        for key, value in self.__dict__.items():
            if value is None:
                continue
            result[key] = self._serialize_value(value)
        return result

    def _serialize_value(self, value: Any) -> Any:
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, datetime):
            return value.isoformat()
        if hasattr(value, "to_dict"):
            return value.to_dict()
        if isinstance(value, list):
            return [self._serialize_value(item) for item in value]
        if isinstance(value, dict):
            return {k: self._serialize_value(v) for k, v in value.items()}
        return value

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


# ─────────────────────────────────────────────────────────────────────────────
# Ingestion Phase
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class PaperMetadata(SerializableMixin):
    """Metadata extracted from a research paper."""

    title: str
    authors: List[str] = field(default_factory=list)
    publication_date: Optional[str] = None
    source_url: Optional[str] = None
    arxiv_id: Optional[str] = None
    doi: Optional[str] = None
    abstract: Optional[str] = None
    keywords: List[str] = field(default_factory=list)


@dataclass
class ParsedSection(SerializableMixin):
    """A parsed section from a research paper."""

    name: str
    content: str
    level: int = 1  # Heading level (1 = H1, 2 = H2, etc.)


@dataclass
class IngestedPaper(SerializableMixin):
    """Result of ingesting a research paper from any source."""

    id: str
    source: str  # Original URL, file path, or arxiv ID
    source_type: SourceType
    raw_text: str
    metadata: PaperMetadata
    sections: List[ParsedSection] = field(default_factory=list)
    figure_captions: List[str] = field(default_factory=list)
    table_captions: List[str] = field(default_factory=list)
    word_count: int = 0
    extraction_confidence: float = 1.0  # 0-1, how confident in extraction quality
    warnings: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now())

    @staticmethod
    def generate_id() -> str:
        """Generate a unique paper ID."""
        return f"paper_{uuid4().hex[:12]}"


@dataclass
class IngestPaperRequest(SerializableMixin):
    """Request to ingest a research paper."""

    source: str  # URL, file path, or arxiv ID
    source_type: Optional[SourceType] = None  # Auto-detected if not provided
    title_override: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class IngestPaperResponse(SerializableMixin):
    """Result of paper ingestion."""

    paper_id: str
    title: str
    source_type: SourceType
    word_count: int
    section_count: int
    extraction_confidence: float
    warnings: List[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Comprehension Phase
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ClaimedResult(SerializableMixin):
    """A claimed result from the research paper."""

    metric: str
    improvement: str
    conditions: str = ""


@dataclass
class ComprehensionResult(SerializableMixin):
    """LLM-driven comprehension of a research paper."""

    # Core Understanding
    core_idea: str  # 2-3 sentence summary
    problem_addressed: str  # What problem does this solve?
    proposed_solution: str  # How do they solve it?

    # Technical Details
    key_contributions: List[str] = field(default_factory=list)  # Novel contributions
    technical_approach: str = ""  # How it works (1-2 paragraphs)
    algorithms_methods: List[str] = field(default_factory=list)  # Named algorithms

    # Claims & Results
    claimed_results: List[ClaimedResult] = field(default_factory=list)
    benchmarks_used: List[str] = field(default_factory=list)
    limitations_acknowledged: List[str] = field(default_factory=list)

    # Novelty Assessment
    novelty_score: float = 0.0  # 1-10, LLM-assessed
    novelty_rationale: str = ""
    related_work_summary: str = ""

    # Metadata
    comprehension_confidence: float = 0.0  # 0-1
    key_terms: List[str] = field(default_factory=list)
    llm_model: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now())


# ─────────────────────────────────────────────────────────────────────────────
# Evaluation Phase
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ConflictItem(SerializableMixin):
    """A conflict with the existing Amprealize approach."""

    behavior_name: str
    description: str
    severity: str = "medium"  # low, medium, high


@dataclass
class CompetitiveLandscapeItem(SerializableMixin):
    """An existing tool, framework, library, or pattern that addresses a similar problem."""

    name: str
    category: str  # "tool", "framework", "library", "pattern", "paper"
    url: Optional[str] = None
    description: str = ""
    maturity: str = "unknown"  # "experimental", "stable", "mature", "deprecated"
    overlap_description: str = ""
    differentiators: List[str] = field(default_factory=list)


@dataclass
class StructuredCon(SerializableMixin):
    """A concern or risk with severity, likelihood, and mitigation."""

    description: str
    severity: str = "medium"  # "low", "medium", "high", "critical"
    likelihood: str = "medium"  # "low", "medium", "high"
    mitigation: str = ""
    category: str = ""  # "technical", "operational", "security", "licensing"


@dataclass
class ValueProposition(SerializableMixin):
    """Structured effectiveness and value assessment."""

    effectiveness_summary: str
    key_benefits: List[str] = field(default_factory=list)
    measurable_outcomes: List[str] = field(default_factory=list)
    value_to_amprealize: str = ""


@dataclass
class EvaluationResult(SerializableMixin):
    """Brutally honest assessment of whether Amprealize should adopt this research."""

    # Scores (1-10 each)
    relevance_score: float = 0.0
    relevance_rationale: str = ""

    feasibility_score: float = 0.0
    feasibility_rationale: str = ""

    novelty_score: float = 0.0
    novelty_rationale: str = ""

    roi_score: float = 0.0
    roi_rationale: str = ""

    safety_score: float = 0.0
    safety_rationale: str = ""

    # Weighted overall (calculated)
    overall_score: float = 0.0

    # Unvarnished gut-check: plain-language, no-hedging assessment
    honest_assessment: str = ""

    # Conflict Detection
    conflicts_with_existing: List[ConflictItem] = field(default_factory=list)

    # Resource Assessment
    implementation_complexity: Complexity = Complexity.MEDIUM
    maintenance_burden: Complexity = Complexity.MEDIUM
    expertise_gap: Complexity = Complexity.MEDIUM
    estimated_effort: str = ""  # T-shirt size + justification

    # Honest Concerns (flat lists kept for backward compatibility)
    concerns: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)

    # Structured cons with severity, likelihood, and mitigation
    structured_cons: List[StructuredCon] = field(default_factory=list)

    # Benefits
    potential_benefits: List[str] = field(default_factory=list)

    # Competitive Landscape
    competitive_landscape: List[CompetitiveLandscapeItem] = field(default_factory=list)

    # Value Proposition
    value_proposition: Optional[ValueProposition] = None

    # Metadata
    llm_model: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now())

    def calculate_overall_score(self) -> float:
        """Calculate weighted overall score from individual scores."""
        weighted = (
            self.relevance_score * 0.25
            + self.feasibility_score * 0.25
            + self.novelty_score * 0.20
            + self.roi_score * 0.20
            + self.safety_score * 0.10
        )
        self.overall_score = round(weighted, 2)
        return self.overall_score


# ─────────────────────────────────────────────────────────────────────────────
# Recommendation Phase
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class AffectedComponent(SerializableMixin):
    """A component that would be affected by implementation."""

    path: str
    what_changes: str


@dataclass
class ImplementationStep(SerializableMixin):
    """A step in the implementation roadmap."""

    order: int
    description: str
    effort: str = ""  # S, M, L, XL


@dataclass
class ImplementationRoadmap(SerializableMixin):
    """Roadmap for implementing the research."""

    affected_components: List[AffectedComponent] = field(default_factory=list)
    proposed_steps: List[ImplementationStep] = field(default_factory=list)
    success_criteria: List[str] = field(default_factory=list)
    estimated_effort: str = ""  # T-shirt size + justification
    adaptations_needed: List[str] = field(default_factory=list)  # If ADAPT verdict


@dataclass
class AdoptionStrategy(SerializableMixin):
    """Recommendation for how to adopt research findings."""

    approach: str  # "use_directly", "extract_concepts", "hybrid", "build_custom"
    rationale: str
    direct_use_candidates: List[str] = field(default_factory=list)
    concepts_to_extract: List[str] = field(default_factory=list)
    integration_points: List[str] = field(default_factory=list)
    estimated_time_saved: str = ""


@dataclass
class Recommendation(SerializableMixin):
    """Final recommendation with verdict and actionable next steps."""

    verdict: Verdict
    verdict_rationale: str

    # Executive summary for human consumption
    executive_summary: str = ""

    # Only if ADOPT or ADAPT
    implementation_roadmap: Optional[ImplementationRoadmap] = None

    # Adoption strategy: use directly, extract concepts, hybrid, or build custom
    adoption_strategy: Optional[AdoptionStrategy] = None

    # Handoff
    next_agent: Optional[str] = None  # architect, engineering, etc.
    priority: Priority = Priority.P3
    blocking_dependencies: List[str] = field(default_factory=list)
    handoff_context: Dict[str, Any] = field(default_factory=dict)

    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.now())


# ─────────────────────────────────────────────────────────────────────────────
# Full Pipeline Request/Response
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class EvaluatePaperRequest(SerializableMixin):
    """Request to run full evaluation pipeline."""

    source: str  # URL, file path, or arxiv ID
    source_type: Optional[SourceType] = None
    context_documents: List[str] = field(
        default_factory=lambda: ["AGENTS.md", "PRD.md", "docs/contracts/MCP_SERVER_DESIGN.md"]
    )
    llm_model: Optional[str] = None  # Defaults to ANTHROPIC_MODEL env var or claude-opus-4-20250514
    save_to_db: bool = True


@dataclass
class EvaluatePaperResponse(SerializableMixin):
    """Complete evaluation result."""

    paper_id: str
    paper_title: str

    # Phase results (Optional when loaded from storage summary views)
    ingested_paper: Optional[IngestedPaper] = None
    comprehension: Optional[ComprehensionResult] = None
    evaluation: Optional[EvaluationResult] = None
    recommendation: Optional[Recommendation] = None

    # Metadata
    total_tokens_used: int = 0
    evaluation_duration_seconds: float = 0.0

    # Formatted output (generated on demand)
    markdown_report: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Search and Management
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class SearchPapersRequest(SerializableMixin):
    """Request to search evaluated papers."""

    query: Optional[str] = None
    verdict: Optional[Verdict] = None
    min_score: Optional[float] = None
    max_score: Optional[float] = None
    source_type: Optional[SourceType] = None
    since: Optional[datetime] = None
    limit: int = 50
    offset: int = 0


@dataclass
class PaperSummary(SerializableMixin):
    """Summary of an evaluated paper for list views."""

    paper_id: str
    title: str
    source_type: SourceType
    overall_score: float
    verdict: Verdict
    core_idea: str
    created_at: datetime


@dataclass
class SearchPapersResponse(SerializableMixin):
    """Response from paper search."""

    papers: List[PaperSummary] = field(default_factory=list)
    total_count: int = 0
    has_more: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# Verdict Calculation
# ─────────────────────────────────────────────────────────────────────────────


def calculate_verdict(
    overall_score: float,
    conflicts: List[ConflictItem],
    safety_score: float,
) -> Verdict:
    """Calculate verdict based on scores and conflicts.

    Logic:
    - Safety veto: If safety_score < 4.0, REJECT
    - Conflict handling: If > 2 conflicts and score < 8.0, DEFER
    - Score-based:
        - >= 7.5: ADOPT
        - >= 5.5: ADAPT
        - >= 3.5: DEFER
        - < 3.5: REJECT
    """
    # Safety veto
    if safety_score < 4.0:
        return Verdict.REJECT

    # Conflict handling
    if len(conflicts) > 2 and overall_score < 8.0:
        return Verdict.DEFER

    # Score-based
    if overall_score >= 7.5:
        return Verdict.ADOPT
    elif overall_score >= 5.5:
        return Verdict.ADAPT
    elif overall_score >= 3.5:
        return Verdict.DEFER
    else:
        return Verdict.REJECT
