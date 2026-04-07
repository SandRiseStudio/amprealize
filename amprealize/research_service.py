"""Research Service for AI research evaluation pipeline.

This service provides a standardized pipeline for evaluating AI research papers
for potential integration into Amprealize.

Pipeline Phases:
1. Ingest: Accept research from URL, markdown, PDF
2. Comprehend: LLM-driven deep analysis
3. Evaluate: Assess fit, feasibility, and value for Amprealize
4. Recommend: Generate verdict and implementation roadmap

Usage:
    service = ResearchService()
    result = service.evaluate_paper(
        EvaluatePaperRequest(source="path/to/paper.md")
    )
    print(result.recommendation.verdict)

See RESEARCH_SERVICE_CONTRACT.md for full specification.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from amprealize.services.board_service import BoardService
    from amprealize.multi_tenant.board_contracts import CreateWorkItemRequest

from amprealize.research_contracts import (
    AdoptionStrategy,
    AffectedComponent,
    ClaimedResult,
    CompetitiveLandscapeItem,
    Complexity,
    ComprehensionResult,
    ConflictItem,
    EvaluatePaperRequest,
    EvaluatePaperResponse,
    EvaluationResult,
    ImplementationRoadmap,
    ImplementationStep,
    IngestedPaper,
    IngestPaperRequest,
    IngestPaperResponse,
    PaperSummary,
    Priority,
    StructuredCon,
    ValueProposition,
    Recommendation,
    SearchPapersRequest,
    SearchPapersResponse,
    SourceType,
    Verdict,
    calculate_verdict,
)
from amprealize.storage.research_storage_postgres import ResearchStoragePostgres
from amprealize.research.prompts import (
    COMPREHENSION_SYSTEM_PROMPT,
    COMPREHENSION_USER_PROMPT,
    EVALUATION_SYSTEM_PROMPT,
    EVALUATION_USER_PROMPT,
    RECOMMENDATION_SYSTEM_PROMPT,
    RECOMMENDATION_USER_PROMPT,
    format_comprehension_prompt,
    format_evaluation_prompt,
    format_recommendation_prompt,
)
from amprealize.research.codebase_analyzer import CodebaseAnalyzer
from amprealize.research.ingesters import (
    BaseIngester,
    MarkdownIngester,
    URLIngester,
    PDFIngester,
)

logger = logging.getLogger(__name__)


# Type for progress callback
ProgressCallback = Optional[Callable[[str, str, Optional[float]], None]]


class ProgressTracker:
    """Clean progress tracker for CLI output.

    - In TTY: Updates spinner in-place using carriage return
    - Non-TTY: Only prints phase starts and completions (minimal output)
    """

    SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.start_time = time.perf_counter()
        self.phase_start_time = None
        self.current_phase = None
        self.current_progress = 0.0
        self.spinner_idx = 0
        self._is_tty = None
        self._phase_printed = set()  # Track which phases we've printed start for

    def _is_interactive(self) -> bool:
        """Check if stderr is an interactive terminal."""
        if self._is_tty is None:
            import sys
            self._is_tty = hasattr(sys.stderr, 'isatty') and sys.stderr.isatty()
        return self._is_tty

    def _elapsed(self) -> str:
        """Get total elapsed time string."""
        elapsed = time.perf_counter() - self.start_time
        if elapsed < 60:
            return f"{elapsed:.1f}s"
        else:
            mins = int(elapsed // 60)
            secs = elapsed % 60
            return f"{mins}m {secs:.0f}s"

    def _phase_elapsed(self) -> str:
        """Get phase elapsed time string."""
        if self.phase_start_time is None:
            return "0.0s"
        elapsed = time.perf_counter() - self.phase_start_time
        return f"{elapsed:.1f}s"

    def _spinner(self) -> str:
        """Get next spinner frame."""
        frame = self.SPINNER_FRAMES[self.spinner_idx % len(self.SPINNER_FRAMES)]
        self.spinner_idx += 1
        return frame

    def _render_progress_bar(self, progress: float, width: int = 30) -> str:
        """Render a progress bar."""
        filled = int(progress * width)
        bar = "█" * filled + "░" * (width - filled)
        return f"[{bar}] {progress:5.1%}"

    def __call__(self, phase: str, message: str, progress: Optional[float] = None) -> None:
        """Handle progress callback."""
        if not self.verbose:
            return

        import sys

        # Track phase timing
        is_new_phase = phase != self.current_phase
        if is_new_phase:
            self.current_phase = phase
            self.phase_start_time = time.perf_counter()

        # Update progress
        if progress is not None:
            self.current_progress = progress

        # Determine if this is a completion message (starts with ✓ or ✅)
        is_complete = message.startswith("✓") or message.startswith("✅")

        elapsed_str = f"[{self._elapsed()}]"
        progress_bar = self._render_progress_bar(self.current_progress)

        if is_complete:
            # Clear line if TTY, then print completion
            if self._is_interactive():
                sys.stderr.write("\r\033[K")

            line = f"\033[32m{elapsed_str}\033[0m [{phase}] {message} {progress_bar}"
            sys.stderr.write(f"{line}\n")
            sys.stderr.flush()
        else:
            # For in-progress updates
            spinner = self._spinner()
            phase_time = f"({self._phase_elapsed()})"
            msg = message[:50]  # Truncate for display

            if self._is_interactive():
                # TTY: Update in-place with carriage return
                line = f"\033[33m{elapsed_str}\033[0m [{phase}] {spinner} {msg} {phase_time} {progress_bar}"
                sys.stderr.write(f"\r\033[K{line}")
                sys.stderr.flush()
            else:
                # Non-TTY: Only print once per phase (when phase starts)
                if phase not in self._phase_printed:
                    self._phase_printed.add(phase)
                    line = f"{elapsed_str} [{phase}] {spinner} {msg}..."
                    sys.stderr.write(f"{line}\n")
                    sys.stderr.flush()


def default_progress_callback(phase: str, message: str, progress: Optional[float] = None) -> None:
    """Default progress callback that prints to stderr."""
    import sys
    if progress is not None:
        print(f"[{phase}] {message} ({progress:.0%})", file=sys.stderr)
    else:
        print(f"[{phase}] {message}", file=sys.stderr)


class ResearchService:
    """Service for evaluating AI research papers.

    Provides a standardized pipeline for:
    1. Ingesting papers from various sources (URL, markdown, PDF)
    2. LLM-driven comprehension and analysis
    3. Evaluation against Amprealize fit criteria
    4. Recommendation generation with implementation roadmaps
    """

    DEFAULT_MODEL = "claude-opus-4-20250514"

    def __init__(
        self,
        db_path: Optional[str] = None,
        llm_model: Optional[str] = None,
        context_dir: Optional[str] = None,
        board_service: Optional["BoardService"] = None,
        project_id: Optional[str] = None,
        pool: Optional[Any] = None,
    ):
        """Initialize ResearchService.

        Args:
            db_path: Path to SQLite database. Defaults to ~/.amprealize/research.db
            llm_model: Default LLM model to use for analysis.
                       Defaults to ANTHROPIC_MODEL env var or claude-opus-4-20250514.
            context_dir: Directory containing context documents (AGENTS.md, PRD.md, etc.)
                         Defaults to current working directory.
            board_service: Optional BoardService for creating work items on ADOPT/ADAPT verdicts.
            project_id: Project ID for work item creation. Required if board_service provided.
            pool: Optional PostgresPool for multi-tenant storage. When provided,
                  uses ResearchStoragePostgres instead of SQLite.
        """
        self.db_path = db_path or (
            str(Path.home() / ".amprealize" / "research.db") if not pool else None
        )
        self.llm_model = llm_model or os.environ.get("ANTHROPIC_MODEL", self.DEFAULT_MODEL)
        self.context_dir = Path(context_dir) if context_dir else Path.cwd()

        # PostgreSQL multi-tenant storage pool
        self._pool = pool

        # Initialize ingesters
        self._ingesters: List[BaseIngester] = [
            MarkdownIngester(),
            URLIngester(),
            PDFIngester(),
        ]

        # Initialize codebase analyzer for dynamic context
        self._codebase_analyzer = CodebaseAnalyzer(
            project_root=self.context_dir,
            cache_ttl=300,  # 5 minute cache
        )

        # Optional board service for handoff work items
        self._board_service = board_service
        self._project_id = project_id

        # Lazy-load storage and LLM
        self._storage = None
        self._llm_provider = None

    @property
    def storage(self):
        """Access the storage layer (lazy-loaded)."""
        return self._get_storage()

    def _get_storage(self):
        """Lazy-load storage layer.

        Returns ResearchStoragePostgres when a pool is configured,
        otherwise falls back to the SQLite ResearchStorage.
        """
        if self._storage is None:
            if self._pool is not None:
                self._storage = ResearchStoragePostgres(self._pool)
            else:
                self._storage = ResearchStorage(self.db_path)
        return self._storage

    def _get_llm_provider(self):
        """Lazy-load LLM client."""
        if self._llm_provider is None:
            from amprealize.llm import LLMClient, LLMConfig, ProviderType

            # Determine provider from model name
            if "claude" in self.llm_model.lower():
                provider_type = ProviderType.ANTHROPIC
                api_key = os.environ.get("ANTHROPIC_API_KEY")
            else:
                provider_type = ProviderType.OPENAI
                api_key = os.environ.get("OPENAI_API_KEY")

            config = LLMConfig(
                provider=provider_type,
                model=self.llm_model,
                api_key=api_key,
                max_tokens=4096,
                temperature=0.3,
            )
            self._llm_provider = LLMClient(config)

        return self._llm_provider

    def _detect_source_type(self, source: str) -> SourceType:
        """Auto-detect source type from the source string."""
        if source.startswith("http://") or source.startswith("https://"):
            if ".pdf" in source.lower():
                return SourceType.PDF
            if "arxiv.org" in source.lower():
                return SourceType.ARXIV
            return SourceType.URL

        path = Path(source)
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return SourceType.PDF
        if suffix in (".md", ".markdown", ".txt"):
            return SourceType.MARKDOWN
        if suffix in (".doc", ".docx"):
            return SourceType.DOCX

        # Default to markdown for unknown
        return SourceType.MARKDOWN

    def _get_ingester(self, source: str, source_type: Optional[SourceType] = None) -> BaseIngester:
        """Get appropriate ingester for the source."""
        for ingester in self._ingesters:
            if ingester.can_handle(source):
                return ingester

        # Default to markdown ingester
        return self._ingesters[0]

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 1: Ingest
    # ─────────────────────────────────────────────────────────────────────────

    def ingest_paper(
        self,
        request: IngestPaperRequest,
    ) -> IngestedPaper:
        """Ingest a research paper from various sources.

        Args:
            request: Ingestion request with source and options

        Returns:
            IngestedPaper with parsed content
        """
        logger.info(f"Ingesting paper from: {request.source}")

        # Detect source type if not provided
        source_type = request.source_type or self._detect_source_type(request.source)

        # Get appropriate ingester
        ingester = self._get_ingester(request.source, source_type)

        # Ingest the paper
        paper = ingester.ingest(request.source, request.title_override)

        logger.info(
            f"Ingested paper: {paper.metadata.title} "
            f"({paper.word_count} words, {len(paper.sections)} sections)"
        )

        return paper

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 2: Comprehend
    # ─────────────────────────────────────────────────────────────────────────

    def comprehend_paper(
        self,
        paper: IngestedPaper,
        llm_model: Optional[str] = None,
    ) -> ComprehensionResult:
        """Run LLM-driven comprehension on a paper.

        Args:
            paper: Ingested paper to analyze
            llm_model: Optional model override

        Returns:
            ComprehensionResult with structured analysis
        """
        logger.info(f"Comprehending paper: {paper.metadata.title}")

        client = self._get_llm_provider()

        # Load agent playbook for expertise context
        agent_playbook = self._load_context_doc("amprealize/agents/playbooks/AGENT_AI_RESEARCH.md", max_chars=3000)
        if agent_playbook and "[not found]" not in agent_playbook.lower():
            agent_playbook_section = f"\n**Agent Playbook (your operational guidelines):**\n{agent_playbook}"
        else:
            agent_playbook_section = ""

        # Inject playbook into system prompt
        system_prompt = COMPREHENSION_SYSTEM_PROMPT.format(agent_playbook=agent_playbook_section)

        # Format prompt
        user_prompt = format_comprehension_prompt(paper.raw_text)

        # Call LLM
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        response = client.call(messages, model=llm_model or self.llm_model, max_tokens=4096, temperature=0.3)

        # Parse JSON response
        try:
            data = json.loads(response.content)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse comprehension response: {e}")
            # Try to extract JSON from response
            data = self._extract_json(response.content)

        # Build ComprehensionResult
        claimed_results = [
            ClaimedResult(
                metric=r.get("metric", ""),
                improvement=r.get("improvement", ""),
                conditions=r.get("conditions", ""),
            )
            for r in data.get("claimed_results", [])
        ]

        result = ComprehensionResult(
            core_idea=data.get("core_idea", ""),
            problem_addressed=data.get("problem_addressed", ""),
            proposed_solution=data.get("proposed_solution", ""),
            key_contributions=data.get("key_contributions", []),
            technical_approach=data.get("technical_approach", ""),
            algorithms_methods=data.get("algorithms_methods", []),
            claimed_results=claimed_results,
            benchmarks_used=data.get("benchmarks_used", []),
            limitations_acknowledged=data.get("limitations_acknowledged", []),
            novelty_score=float(data.get("novelty_score", 5.0)),
            novelty_rationale=data.get("novelty_rationale", ""),
            related_work_summary=data.get("related_work_summary", ""),
            comprehension_confidence=float(data.get("comprehension_confidence", 0.5)),
            key_terms=data.get("key_terms", []),
            llm_model=llm_model or self.llm_model,
        )

        logger.info(
            f"Comprehension complete. Novelty score: {result.novelty_score}/10, "
            f"Confidence: {result.comprehension_confidence:.0%}"
        )

        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 3: Evaluate
    # ─────────────────────────────────────────────────────────────────────────

    def evaluate_paper(
        self,
        comprehension: ComprehensionResult,
        llm_model: Optional[str] = None,
    ) -> EvaluationResult:
        """Evaluate paper fit for Amprealize.

        Args:
            comprehension: Comprehension result to evaluate
            llm_model: Optional model override

        Returns:
            EvaluationResult with scores and analysis
        """
        logger.info("Evaluating paper fit for Amprealize")

        client = self._get_llm_provider()

        # Load context documents
        architecture_context = self._load_context_doc("docs/contracts/MCP_SERVER_DESIGN.md")
        behaviors_context = self._load_context_doc("AGENTS.md")
        product_context = self._load_context_doc("PRD.md")

        # Get dynamic codebase context
        codebase_context = self._get_codebase_context()

        # Load agent playbook for expertise context
        agent_playbook = self._load_context_doc("amprealize/agents/playbooks/AGENT_AI_RESEARCH.md", max_chars=5000)
        if agent_playbook:
            agent_playbook_section = f"\n**Agent Playbook (your operational guidelines):**\n{agent_playbook}"
        else:
            agent_playbook_section = ""

        # Inject playbook and codebase context into system prompt
        system_prompt = EVALUATION_SYSTEM_PROMPT.format(
            agent_playbook=agent_playbook_section,
            codebase_context=codebase_context,
        )

        # Brutal honesty directive appended to every evaluation
        system_prompt += (
            "\n\n## CRITICAL: Brutal Honesty Requirement\n"
            "You MUST be ruthlessly honest in this evaluation. Do NOT sugarcoat. "
            "If an existing library already solves this problem, say so and name it. "
            "If the research is repackaging old ideas, call it out. "
            "If simpler approaches achieve 80% of the gains at 20% of the complexity, flag that. "
            "If the right answer is 'just pip install X,' say that. "
            "If this is academic vaporware that won't survive production, say that. "
            "Include an 'honest_assessment' field in your JSON: 2-3 sentences of plain-language, "
            "no-hedging gut check -- what you'd tell a colleague over coffee. "
            "The team prefers an honest REJECT now over discovering problems after weeks of work."
        )

        # Format prompt
        user_prompt = format_evaluation_prompt(
            comprehension_summary=comprehension.to_json(),
            architecture_context=architecture_context,
            behaviors_context=behaviors_context,
            product_context=product_context,
        )

        # Call LLM
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        response = client.call(messages, model=llm_model or self.llm_model, max_tokens=4096, temperature=0.3)

        # Parse JSON response
        try:
            data = json.loads(response.content)
        except json.JSONDecodeError:
            data = self._extract_json(response.content)

        # Build conflicts
        conflicts = [
            ConflictItem(
                behavior_name=c.get("behavior_name", ""),
                description=c.get("description", ""),
                severity=c.get("severity", "medium"),
            )
            for c in data.get("conflicts_with_existing", [])
        ]

        # Build competitive landscape
        competitive_landscape = [
            CompetitiveLandscapeItem(
                name=item.get("name", ""),
                category=item.get("category", "tool"),
                url=item.get("url"),
                description=item.get("description", ""),
                maturity=item.get("maturity", "unknown"),
                overlap_description=item.get("overlap_description", ""),
                differentiators=item.get("differentiators", []),
            )
            for item in data.get("competitive_landscape", [])
        ]

        # Build structured cons
        structured_cons = [
            StructuredCon(
                description=con.get("description", ""),
                severity=con.get("severity", "medium"),
                likelihood=con.get("likelihood", "medium"),
                mitigation=con.get("mitigation", ""),
                category=con.get("category", ""),
            )
            for con in data.get("structured_cons", [])
        ]

        # Build value proposition
        vp_data = data.get("value_proposition")
        value_proposition = None
        if vp_data and isinstance(vp_data, dict):
            value_proposition = ValueProposition(
                effectiveness_summary=vp_data.get("effectiveness_summary", ""),
                key_benefits=vp_data.get("key_benefits", []),
                measurable_outcomes=vp_data.get("measurable_outcomes", []),
                value_to_amprealize=vp_data.get("value_to_amprealize", ""),
            )

        # Build EvaluationResult
        result = EvaluationResult(
            relevance_score=float(data.get("relevance_score", 5.0)),
            relevance_rationale=data.get("relevance_rationale", ""),
            feasibility_score=float(data.get("feasibility_score", 5.0)),
            feasibility_rationale=data.get("feasibility_rationale", ""),
            novelty_score=float(data.get("novelty_score", 5.0)),
            novelty_rationale=data.get("novelty_rationale", ""),
            roi_score=float(data.get("roi_score", 5.0)),
            roi_rationale=data.get("roi_rationale", ""),
            safety_score=float(data.get("safety_score", 8.0)),
            safety_rationale=data.get("safety_rationale", ""),
            honest_assessment=data.get("honest_assessment", ""),
            conflicts_with_existing=conflicts,
            implementation_complexity=Complexity(
                data.get("implementation_complexity", "MEDIUM")
            ),
            maintenance_burden=Complexity(
                data.get("maintenance_burden", "MEDIUM")
            ),
            expertise_gap=Complexity(
                data.get("expertise_gap", "MEDIUM")
            ),
            estimated_effort=data.get("estimated_effort", "M - Moderate effort"),
            concerns=data.get("concerns", []),
            risks=data.get("risks", []),
            structured_cons=structured_cons,
            potential_benefits=data.get("potential_benefits", []),
            competitive_landscape=competitive_landscape,
            value_proposition=value_proposition,
            llm_model=llm_model or self.llm_model,
        )

        # Calculate overall score
        result.calculate_overall_score()

        logger.info(
            f"Evaluation complete. Overall score: {result.overall_score:.2f}/10"
        )

        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 4: Recommend
    # ─────────────────────────────────────────────────────────────────────────

    def recommend(
        self,
        paper_title: str,
        comprehension: ComprehensionResult,
        evaluation: EvaluationResult,
        llm_model: Optional[str] = None,
    ) -> Recommendation:
        """Generate final recommendation with verdict and roadmap.

        Args:
            paper_title: Title of the paper
            comprehension: Comprehension result
            evaluation: Evaluation result
            llm_model: Optional model override

        Returns:
            Recommendation with verdict and implementation roadmap
        """
        logger.info("Generating recommendation")

        client = self._get_llm_provider()

        # Get dynamic codebase context for accurate roadmap generation
        codebase_context = self._get_codebase_context()

        # Load agent playbook for expertise context
        agent_playbook = self._load_context_doc("amprealize/agents/playbooks/AGENT_AI_RESEARCH.md", max_chars=3000)
        if agent_playbook and "[not found]" not in agent_playbook.lower():
            agent_playbook_section = f"\n**Agent Playbook (your operational guidelines):**\n{agent_playbook}"
        else:
            agent_playbook_section = ""

        # Inject playbook and codebase context into system prompt
        system_prompt = RECOMMENDATION_SYSTEM_PROMPT.format(
            agent_playbook=agent_playbook_section,
            codebase_context=codebase_context,
        )

        # Brutal honesty directive appended to every recommendation
        system_prompt += (
            "\n\n## CRITICAL: Brutal Honesty Requirement\n"
            "Be ruthlessly honest in this recommendation. "
            "Default to 'use_directly' when an existing tool/library already solves the problem well. "
            "The burden of proof is on 'build_custom' to justify why existing solutions won't work. "
            "If the honest recommendation is REJECT, say so without hedging. "
            "Include an unvarnished executive_summary that tells the truth plainly."
        )

        # Format conflicts for prompt
        conflicts_str = "\n".join(
            f"- {c.behavior_name}: {c.description}"
            for c in evaluation.conflicts_with_existing
        ) if evaluation.conflicts_with_existing else "None identified"

        # Format prompt
        user_prompt = format_recommendation_prompt(
            paper_title=paper_title,
            core_idea=comprehension.core_idea,
            relevance_score=evaluation.relevance_score,
            feasibility_score=evaluation.feasibility_score,
            novelty_score=evaluation.novelty_score,
            roi_score=evaluation.roi_score,
            safety_score=evaluation.safety_score,
            overall_score=evaluation.overall_score,
            concerns=evaluation.concerns,
            risks=evaluation.risks,
            benefits=evaluation.potential_benefits,
            conflicts=[
                f"{c.behavior_name}: {c.description}"
                for c in evaluation.conflicts_with_existing
            ],
        )

        # Call LLM
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        response = client.call(messages, model=llm_model or self.llm_model, max_tokens=4096, temperature=0.3)

        # Parse JSON response
        try:
            data = json.loads(response.content)
        except json.JSONDecodeError:
            data = self._extract_json(response.content)

        # Calculate verdict (can override LLM if needed)
        verdict = calculate_verdict(
            evaluation.overall_score,
            evaluation.conflicts_with_existing,
            evaluation.safety_score,
        )

        # Build implementation roadmap if applicable
        roadmap = None
        if verdict in (Verdict.ADOPT, Verdict.ADAPT) and data.get("implementation_roadmap"):
            rm_data = data["implementation_roadmap"]
            roadmap = ImplementationRoadmap(
                affected_components=[
                    AffectedComponent(
                        path=c.get("path", ""),
                        what_changes=c.get("what_changes", ""),
                    )
                    for c in rm_data.get("affected_components", [])
                ],
                proposed_steps=[
                    ImplementationStep(
                        order=s.get("order", i),
                        description=s.get("description", ""),
                        effort=s.get("effort", "M"),
                    )
                    for i, s in enumerate(rm_data.get("proposed_steps", []), 1)
                ],
                success_criteria=rm_data.get("success_criteria", []),
                estimated_effort=rm_data.get("estimated_effort", ""),
                adaptations_needed=rm_data.get("adaptations_needed", []),
            )

        # Build adoption strategy if present
        adoption_strategy = None
        as_data = data.get("adoption_strategy")
        if as_data and isinstance(as_data, dict):
            adoption_strategy = AdoptionStrategy(
                approach=as_data.get("approach", "build_custom"),
                rationale=as_data.get("rationale", ""),
                direct_use_candidates=as_data.get("direct_use_candidates", []),
                concepts_to_extract=as_data.get("concepts_to_extract", []),
                integration_points=as_data.get("integration_points", []),
                estimated_time_saved=as_data.get("estimated_time_saved", ""),
            )

        result = Recommendation(
            verdict=verdict,
            verdict_rationale=data.get("verdict_rationale", ""),
            executive_summary=data.get("executive_summary", ""),
            implementation_roadmap=roadmap,
            adoption_strategy=adoption_strategy,
            next_agent=data.get("next_agent"),
            priority=Priority(data.get("priority", "P3")),
            blocking_dependencies=data.get("blocking_dependencies", []),
            handoff_context=data.get("handoff_context", {}),
        )

        logger.info(f"Recommendation: {result.verdict.value}")

        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Full Pipeline
    # ─────────────────────────────────────────────────────────────────────────

    def evaluate(
        self,
        request: EvaluatePaperRequest,
        progress_callback: ProgressCallback = None,
        *,
        owner_id: Optional[str] = None,
        org_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> EvaluatePaperResponse:
        """Run full evaluation pipeline on a paper.

        This is the main entry point for evaluating research papers.

        Args:
            request: Evaluation request with source and options
            progress_callback: Optional callback for progress updates.
                               Signature: (phase: str, message: str, progress: Optional[float]) -> None
                               Or pass a ProgressTracker instance for rich output.

        Returns:
            Complete evaluation response with all phases
        """
        # Use ProgressTracker for rich output if no callback provided
        if progress_callback is None:
            progress = ProgressTracker(verbose=True)
        else:
            progress = progress_callback

        start_time = time.perf_counter()
        total_tokens = 0

        # Truncate long source paths for display
        source_display = request.source
        if len(source_display) > 60:
            source_display = "..." + source_display[-57:]

        logger.info(f"Starting full evaluation pipeline for: {request.source}")
        progress("Pipeline", f"🚀 Starting evaluation: {source_display}", 0.0)

        # Phase 1: Ingest
        progress("Ingest", "📄 Loading and parsing content...", 0.05)
        paper = self.ingest_paper(
            IngestPaperRequest(
                source=request.source,
                source_type=request.source_type,
            )
        )

        # Show ingestion details
        sections_info = f", {len(paper.sections)} section(s)" if paper.sections else ""
        progress("Ingest", f"✓ Loaded: {paper.metadata.title} ({paper.word_count:,} words{sections_info})", 0.1)

        # Phase 2: Comprehend
        progress("Comprehend", f"🧠 Analyzing with LLM ({self.llm_model})...", 0.15)

        comprehension = self.comprehend_paper(paper, request.llm_model)

        contributions_count = len(comprehension.key_contributions)
        results_count = len(comprehension.claimed_results)
        progress(
            "Comprehend",
            f"✓ Analyzed: novelty {comprehension.novelty_score}/10, "
            f"{contributions_count} contributions, {results_count} results",
            0.40
        )

        # Phase 3a: Analyze codebase structure
        progress("Codebase", "🔍 Analyzing codebase structure...", 0.42)

        # Trigger codebase analysis to warm cache and get stats
        snapshot = self._codebase_analyzer.get_structural_index()
        progress(
            "Codebase",
            f"✓ Indexed: {len(snapshot.services)} services, {len(snapshot.behaviors)} behaviors, "
            f"{len(snapshot.mcp_tools)} MCP tools, {len(snapshot.db_tables)} tables",
            0.45
        )

        # Phase 3b: Evaluate
        progress("Evaluate", "🎯 Scoring against Amprealize fit criteria...", 0.47)

        evaluation = self.evaluate_paper(comprehension, request.llm_model)

        # Show evaluation breakdown
        progress(
            "Evaluate",
            f"✓ Scored: relevance={evaluation.relevance_score:.1f}, "
            f"feasibility={evaluation.feasibility_score:.1f}, "
            f"overall={evaluation.overall_score:.1f}/10",
            0.65
        )

        # Phase 4: Recommend
        progress("Recommend", "📋 Generating verdict & implementation roadmap...", 0.70)

        recommendation = self.recommend(
            paper.metadata.title,
            comprehension,
            evaluation,
            request.llm_model,
        )

        # Show recommendation details
        roadmap_steps = len(recommendation.implementation_roadmap.proposed_steps) if recommendation.implementation_roadmap else 0
        progress(
            "Recommend",
            f"✓ Verdict: {recommendation.verdict.value} "
            f"(priority: {recommendation.priority.value}, {roadmap_steps} implementation steps)",
            0.85
        )

        duration = time.perf_counter() - start_time

        # Generate markdown report
        progress("Report", "📝 Rendering markdown report...", 0.88)
        from amprealize.research.report import render_report
        report = render_report(paper, comprehension, evaluation, recommendation)
        report_lines = len(report.split('\n'))
        progress("Report", f"✓ Generated report ({report_lines} lines)", 0.92)

        # Save to database if requested
        if request.save_to_db:
            progress("Save", "💾 Persisting to database & saving report...", 0.95)
            storage = self._get_storage()

            if isinstance(storage, ResearchStoragePostgres):
                storage.save_evaluation(
                    paper, comprehension, evaluation, recommendation,
                    owner_id=owner_id,
                    org_id=org_id,
                    project_id=project_id,
                )
                report_id = storage.save_report(
                    paper.id, report, title=paper.metadata.title,
                    owner_id=owner_id,
                    org_id=org_id,
                )
                user_path = f"report:{report_id}"
            else:
                storage.save_evaluation(paper, comprehension, evaluation, recommendation)
                user_path = storage.save_report(paper.id, report, title=paper.metadata.title)
                storage.update_research_index()

            progress("Save", f"✓ Saved: {paper.id[:12]}... → {user_path}", 0.98)

        # Create handoff work item for actionable verdicts (ADOPT/ADAPT)
        work_item_id = None
        if recommendation.verdict in (Verdict.ADOPT, Verdict.ADAPT):
            if self._board_service and self._project_id:
                progress("Handoff", "📋 Creating work item for next agent...", 0.99)
                work_item_id = self._create_handoff_work_item(
                    paper.id,
                    paper.metadata.title,
                    recommendation,
                    evaluation,
                )
                if work_item_id:
                    next_agent = recommendation.next_agent or "architect"
                    progress("Handoff", f"✓ Created work item → {next_agent} agent", 0.995)

        # Final summary
        verdict_emoji = {
            Verdict.ADOPT: "🎉",
            Verdict.ADAPT: "🔧",
            Verdict.DEFER: "⏳",
            Verdict.REJECT: "❌",
        }.get(recommendation.verdict, "✅")

        progress(
            "Pipeline",
            f"✅ Complete in {duration:.1f}s → {verdict_emoji} {recommendation.verdict.value} "
            f"(score: {evaluation.overall_score:.1f}/10)",
            1.0
        )

        logger.info(
            f"Evaluation complete in {duration:.1f}s. "
            f"Verdict: {recommendation.verdict.value}"
        )

        return EvaluatePaperResponse(
            paper_id=paper.id,
            paper_title=paper.metadata.title,
            ingested_paper=paper,
            comprehension=comprehension,
            evaluation=evaluation,
            recommendation=recommendation,
            total_tokens_used=total_tokens,
            evaluation_duration_seconds=duration,
            markdown_report=report,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Search and Management
    # ─────────────────────────────────────────────────────────────────────────

    def search_papers(
        self,
        request: SearchPapersRequest,
        *,
        owner_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> SearchPapersResponse:
        """Search evaluated papers."""
        storage = self._get_storage()
        if isinstance(storage, ResearchStoragePostgres):
            raw = storage.search_papers(
                query=getattr(request, 'query', None),
                verdict=request.verdict.value if request.verdict else None,
                min_score=request.min_score,
                max_score=getattr(request, 'max_score', None),
                source_type=request.source_type.value if request.source_type else None,
                limit=request.limit,
                offset=request.offset,
                owner_id=owner_id,
                org_id=org_id,
            )
            papers = [
                PaperSummary(
                    paper_id=p["paper_id"],
                    title=p["title"],
                    source_type=SourceType(p["source_type"]) if p.get("source_type") else SourceType.URL,
                    overall_score=p.get("overall_score", 0),
                    verdict=Verdict(p["verdict"]) if p.get("verdict") else Verdict.DEFER,
                    core_idea=p.get("core_idea", ""),
                    created_at=datetime.fromisoformat(p["created_at"]) if p.get("created_at") else datetime.now(),
                )
                for p in raw.get("papers", [])
            ]
            return SearchPapersResponse(
                papers=papers,
                total_count=raw.get("total_count", len(papers)),
                has_more=raw.get("has_more", False),
            )
        return storage.search_papers(request)

    def get_paper(
        self,
        paper_id: str,
        *,
        owner_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> Optional[EvaluatePaperResponse]:
        """Get full evaluation for a paper by ID."""
        storage = self._get_storage()
        if isinstance(storage, ResearchStoragePostgres):
            raw = storage.get_paper(
                paper_id,
                owner_id=owner_id,
                org_id=org_id,
            )
            if raw is None:
                return None

            # Build lightweight contract objects from the flat row data
            recommendation = None
            if raw.get("verdict"):
                roadmap_data = json.loads(raw["implementation_roadmap"]) if raw.get("implementation_roadmap") else None
                roadmap = None
                if roadmap_data:
                    roadmap = ImplementationRoadmap(
                        affected_components=roadmap_data.get("affected_components", []),
                        proposed_steps=roadmap_data.get("proposed_steps", []),
                        success_criteria=roadmap_data.get("success_criteria", []),
                        estimated_effort=roadmap_data.get("estimated_effort", ""),
                    )
                recommendation = Recommendation(
                    verdict=Verdict(raw["verdict"]),
                    verdict_rationale=raw.get("verdict_rationale", ""),
                    implementation_roadmap=roadmap,
                    next_agent=raw.get("next_agent"),
                    priority=Priority(raw["priority"]) if raw.get("priority") else Priority.P3,
                    blocking_dependencies=json.loads(raw["blocking_dependencies"]) if raw.get("blocking_dependencies") else [],
                )

            evaluation_obj = None
            if raw.get("overall_score") is not None:
                evaluation_obj = EvaluationResult(
                    relevance_score=raw.get("relevance_score", 0),
                    relevance_rationale="",
                    feasibility_score=raw.get("feasibility_score", 0),
                    feasibility_rationale="",
                    novelty_score=raw.get("novelty_score", 0),
                    novelty_rationale="",
                    roi_score=raw.get("roi_score", 0),
                    roi_rationale="",
                    safety_score=raw.get("safety_score", 0),
                    safety_rationale="",
                    overall_score=raw.get("overall_score", 0),
                    conflicts_with_existing=[],
                    implementation_complexity=Complexity(raw["implementation_complexity"]) if raw.get("implementation_complexity") else Complexity.MEDIUM,
                    maintenance_burden=Complexity(raw["maintenance_burden"]) if raw.get("maintenance_burden") else Complexity.MEDIUM,
                    expertise_gap=Complexity.MEDIUM,
                    estimated_effort=raw.get("estimated_effort", ""),
                    concerns=json.loads(raw["concerns"]) if raw.get("concerns") else [],
                    risks=json.loads(raw["risks"]) if raw.get("risks") else [],
                    potential_benefits=json.loads(raw["potential_benefits"]) if raw.get("potential_benefits") else [],
                )

            return EvaluatePaperResponse(
                paper_id=raw["paper_id"],
                paper_title=raw.get("title", ""),
                recommendation=recommendation,
                evaluation=evaluation_obj,
                markdown_report=raw.get("markdown_report", ""),
            )
        return storage.get_paper(paper_id)

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _load_context_doc(self, filename: str, max_chars: int = 10000) -> str:
        """Load a context document for evaluation.

        Args:
            filename: Name of file to load
            max_chars: Maximum characters to include (to avoid token limits)

        Returns:
            Document content, truncated if necessary
        """
        # Try multiple locations
        locations = [
            self.context_dir / filename,
            self.context_dir / "docs" / filename,
            self.context_dir / "docs" / "contracts" / filename,
            self.context_dir / "docs" / "agents" / filename,
            self.context_dir / "amprealize" / "agents" / "playbooks" / filename,
            Path.cwd() / filename,
            Path.cwd() / "docs" / filename,
            Path.cwd() / "docs" / "contracts" / filename,
            Path.cwd() / "docs" / "agents" / filename,
            Path.cwd() / "amprealize" / "agents" / "playbooks" / filename,
        ]

        for path in locations:
            if path.exists():
                content = path.read_text()
                if len(content) > max_chars:
                    content = content[:max_chars] + "\n\n[... truncated for brevity ...]"
                return content

        logger.warning(f"Context document not found: {filename}")
        return f"[{filename} not found]"

    def _get_codebase_context(self) -> str:
        """Get dynamic codebase context from CodebaseAnalyzer.

        Returns:
            Formatted codebase structure string for LLM context.
            Falls back gracefully if analyzer fails.
        """
        try:
            snapshot = self._codebase_analyzer.get_structural_index()
            context = snapshot.to_context_string()

            if not context.strip():
                return "[Codebase analysis returned empty - using static docs only]"

            logger.debug(
                "Codebase context generated",
                char_count=len(context),
                services=len(snapshot.services),
                behaviors=len(snapshot.behaviors),
            )
            return context

        except Exception as e:
            logger.warning(f"Failed to generate codebase context: {e}")
            return "[Codebase analysis unavailable - using static docs only]"

    def deep_dive_file(
        self,
        file_path: str,
        start_line: int = 1,
        end_line: Optional[int] = None,
    ) -> str:
        """Read specific file contents for detailed analysis.

        Used when LLM requests [DEEP_DIVE: path:L10-L50] for more context.

        Args:
            file_path: Path relative to project root.
            start_line: Starting line (1-indexed).
            end_line: Ending line (inclusive). None for entire file.

        Returns:
            File contents or error message.
        """
        return self._codebase_analyzer.deep_dive(file_path, start_line, end_line)

    def _extract_json(self, text: str) -> Dict[str, Any]:
        """Try to extract JSON from text that may have extra content."""
        import re

        # Try to find JSON in the text
        patterns = [
            r"```json\s*([\s\S]*?)\s*```",  # Markdown code block
            r"```\s*([\s\S]*?)\s*```",  # Generic code block
            r"\{[\s\S]*\}",  # Raw JSON object
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    json_str = match.group(1) if "```" in pattern else match.group(0)
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    continue

        # Return empty dict if nothing found
        logger.error("Could not extract JSON from LLM response")
        return {}

    def _create_handoff_work_item(
        self,
        paper_id: str,
        paper_title: str,
        recommendation: "Recommendation",
        evaluation: "EvaluationResult",
    ) -> Optional[str]:
        """Create a work item for handoff to the next agent on ADOPT/ADAPT verdicts.

        Args:
            paper_id: The research paper ID
            paper_title: Title of the paper
            recommendation: The recommendation with verdict and next_agent
            evaluation: The evaluation result with scores

        Returns:
            work_item_id if created, None otherwise
        """
        # Only create work items for actionable verdicts
        if recommendation.verdict not in (Verdict.ADOPT, Verdict.ADAPT):
            logger.debug(f"No work item created for verdict: {recommendation.verdict.value}")
            return None

        # Need board service and project ID
        if not self._board_service or not self._project_id:
            logger.info(
                "Board service not configured - skipping work item creation. "
                "Set board_service and project_id to enable handoff work items."
            )
            return None

        try:
            # Import here to avoid circular dependencies
            from amprealize.multi_tenant.board_contracts import (
                CreateWorkItemRequest,
                WorkItemType,
                WorkItemPriority,
            )
            from amprealize.action_contracts import Actor

            # Map recommendation priority to work item priority
            priority_map = {
                Priority.P1: WorkItemPriority.CRITICAL,
                Priority.P2: WorkItemPriority.HIGH,
                Priority.P3: WorkItemPriority.MEDIUM,
                Priority.P4: WorkItemPriority.LOW,
            }
            priority = priority_map.get(recommendation.priority, WorkItemPriority.MEDIUM)

            # Determine next agent (default to architect)
            next_agent = recommendation.next_agent or "architect"

            # Build description with key info
            description = f"""## Research Handoff: {recommendation.verdict.value}

**Paper:** {paper_title}
**Paper ID:** {paper_id}
**Overall Score:** {evaluation.overall_score:.1f}/10
"""

            # Add executive summary if available
            if recommendation.executive_summary:
                description += f"\n### Executive Summary\n{recommendation.executive_summary}\n"

            description += f"""
### Evaluation Summary
- Relevance: {evaluation.relevance_score:.1f}/10
- Feasibility: {evaluation.feasibility_score:.1f}/10
- Novelty: {evaluation.novelty_score:.1f}/10
- ROI: {evaluation.roi_score:.1f}/10
- Safety: {evaluation.safety_score:.1f}/10

### Verdict Rationale
{recommendation.verdict_rationale}
"""

            # Add honest assessment if available (the unvarnished gut-check)
            if evaluation.honest_assessment:
                description += f"\n### Honest Assessment\n> {evaluation.honest_assessment}\n"

            # Add value proposition if available
            if evaluation.value_proposition:
                vp = evaluation.value_proposition
                description += "\n### Effectiveness & Value\n"
                description += f"**Effectiveness:** {vp.effectiveness_summary}\n\n"
                if vp.key_benefits:
                    description += "**Key Benefits:**\n"
                    for b in vp.key_benefits:
                        description += f"- {b}\n"
                if vp.measurable_outcomes:
                    description += "\n**Measurable Outcomes:**\n"
                    for m in vp.measurable_outcomes:
                        description += f"- {m}\n"
                if vp.value_to_amprealize:
                    description += f"\n**Value to Amprealize:** {vp.value_to_amprealize}\n"

            # Add competitive landscape if available
            if evaluation.competitive_landscape:
                description += "\n### Competitive Landscape\n"
                description += "| Name | Type | Maturity | Overlap | Differentiators |\n"
                description += "| --- | --- | --- | --- | --- |\n"
                for item in evaluation.competitive_landscape:
                    name_col = f"[{item.name}]({item.url})" if item.url else item.name
                    diffs = "; ".join(item.differentiators) if item.differentiators else "—"
                    description += f"| {name_col} | {item.category} | {item.maturity} | {item.overlap_description} | {diffs} |\n"

            # Add structured cons if available
            if evaluation.structured_cons:
                description += "\n### Potential Cons\n"
                for con in evaluation.structured_cons:
                    description += f"- **{con.description}** (severity: {con.severity}, likelihood: {con.likelihood})"
                    if con.category:
                        description += f" [{con.category}]"
                    if con.mitigation:
                        description += f"\n  Mitigation: {con.mitigation}"
                    description += "\n"

            # Add adoption strategy if available
            if recommendation.adoption_strategy:
                strat = recommendation.adoption_strategy
                description += f"\n### Adoption Strategy\n"
                description += f"**Approach:** {strat.approach}\n"
                description += f"**Rationale:** {strat.rationale}\n"
                if strat.direct_use_candidates:
                    description += "**Direct-use candidates:** " + ", ".join(strat.direct_use_candidates) + "\n"
                if strat.concepts_to_extract:
                    description += "**Concepts to extract:** " + ", ".join(strat.concepts_to_extract) + "\n"
                if strat.integration_points:
                    description += "**Integration points:** " + ", ".join(strat.integration_points) + "\n"
                if strat.estimated_time_saved:
                    description += f"**Estimated time saved:** {strat.estimated_time_saved}\n"

            # Add roadmap if available
            if recommendation.implementation_roadmap:
                roadmap = recommendation.implementation_roadmap
                if roadmap.proposed_steps:
                    description += "\n### Proposed Implementation Steps\n"
                    for step in roadmap.proposed_steps:
                        description += f"{step.order}. {step.description} ({step.effort})\n"

            description += """
### Next Steps
Review the full research report and produce:
1. Architecture Decision Record (ADR)
2. Implementation work items
3. Affected component analysis
"""

            # Build metadata with enriched context
            work_item_metadata = {
                "paper_id": paper_id,
                "research_verdict": recommendation.verdict.value,
                "overall_score": evaluation.overall_score,
                "next_agent": next_agent,
                "source": "research_service",
            }
            if recommendation.adoption_strategy:
                work_item_metadata["adoption_approach"] = recommendation.adoption_strategy.approach
            if recommendation.handoff_context:
                work_item_metadata["handoff_context"] = recommendation.handoff_context

            # Create the work item request
            request = CreateWorkItemRequest(
                item_type=WorkItemType.STORY,
                project_id=self._project_id,
                title=f"[Research → {next_agent.title()}] {paper_title[:80]}",
                description=description,
                priority=priority,
                labels=["research-handoff", next_agent, recommendation.verdict.value.lower()],
                metadata=work_item_metadata,
            )

            # Create actor for the research agent
            actor = Actor(id="research-agent", role="STUDENT", surface="cli")

            # Get the first board for this project
            boards = self._board_service.list_boards(project_id=self._project_id)
            if not boards:
                logger.warning(f"No boards found for project {self._project_id}")
                return None

            # Use the first/default board
            request.board_id = boards[0].board_id

            # Get first column for new work items
            columns = self._board_service.list_columns(boards[0].board_id)
            if columns:
                request.column_id = columns[0].column_id

            # Create the work item
            work_item = self._board_service.create_work_item(request, actor)

            logger.info(
                f"Created handoff work item: {work_item.item_id} "
                f"(verdict={recommendation.verdict.value}, next_agent={next_agent})"
            )
            return work_item.item_id

        except Exception as e:
            logger.error(f"Failed to create handoff work item: {e}")
            return None


# ─────────────────────────────────────────────────────────────────────────────
# Storage Layer (SQLite MVP)
# ─────────────────────────────────────────────────────────────────────────────


class ResearchStorage:
    """SQLite storage for research evaluations."""

    def __init__(self, db_path: str = None):
        if db_path is None:
            from pathlib import Path
            db_path = str(Path.home() / ".amprealize" / "research.db")
        self.db_path = db_path
        self._ensure_db()

    def _ensure_db(self):
        """Ensure database and tables exist."""
        import sqlite3
        from pathlib import Path

        # Ensure directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS research_papers (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    authors TEXT,
                    source_url TEXT,
                    source_type TEXT NOT NULL,
                    arxiv_id TEXT,
                    publication_date TEXT,
                    raw_text TEXT NOT NULL,
                    sections TEXT,
                    metadata TEXT,
                    created_at TEXT NOT NULL,
                    created_by TEXT
                );

                CREATE TABLE IF NOT EXISTS comprehensions (
                    id TEXT PRIMARY KEY,
                    paper_id TEXT NOT NULL REFERENCES research_papers(id),
                    core_idea TEXT NOT NULL,
                    problem_addressed TEXT,
                    proposed_solution TEXT,
                    key_contributions TEXT,
                    technical_approach TEXT,
                    claimed_results TEXT,
                    novelty_score REAL,
                    novelty_rationale TEXT,
                    comprehension_confidence REAL,
                    key_terms TEXT,
                    llm_model TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS evaluations (
                    id TEXT PRIMARY KEY,
                    paper_id TEXT NOT NULL REFERENCES research_papers(id),
                    comprehension_id TEXT NOT NULL REFERENCES comprehensions(id),
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
                    honest_assessment TEXT,
                    conflicts TEXT,
                    implementation_complexity TEXT,
                    maintenance_burden TEXT,
                    expertise_gap TEXT,
                    estimated_effort TEXT,
                    concerns TEXT,
                    risks TEXT,
                    potential_benefits TEXT,
                    structured_cons TEXT,
                    competitive_landscape TEXT,
                    value_proposition TEXT,
                    llm_model TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS recommendations (
                    id TEXT PRIMARY KEY,
                    paper_id TEXT NOT NULL REFERENCES research_papers(id),
                    evaluation_id TEXT NOT NULL REFERENCES evaluations(id),
                    verdict TEXT NOT NULL,
                    verdict_rationale TEXT,
                    executive_summary TEXT,
                    implementation_roadmap TEXT,
                    adoption_strategy TEXT,
                    next_agent TEXT,
                    priority TEXT,
                    blocking_dependencies TEXT,
                    handoff_context TEXT,
                    created_at TEXT NOT NULL,
                    created_by TEXT
                );

                -- Store full markdown reports for retrieval by other agents
                CREATE TABLE IF NOT EXISTS research_reports (
                    id TEXT PRIMARY KEY,
                    paper_id TEXT NOT NULL REFERENCES research_papers(id),
                    report_markdown TEXT NOT NULL,
                    report_file_path TEXT,
                    word_count INTEGER,
                    created_at TEXT NOT NULL,
                    accessed_by TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_reports_paper_id ON research_reports(paper_id);
                CREATE INDEX IF NOT EXISTS idx_papers_source_type ON research_papers(source_type);
                CREATE INDEX IF NOT EXISTS idx_papers_created_at ON research_papers(created_at);
                CREATE INDEX IF NOT EXISTS idx_evaluations_overall_score ON evaluations(overall_score);
                CREATE INDEX IF NOT EXISTS idx_recommendations_verdict ON recommendations(verdict);
            """)
            conn.commit()
        finally:
            conn.close()

    def save_evaluation(
        self,
        paper: IngestedPaper,
        comprehension: ComprehensionResult,
        evaluation: EvaluationResult,
        recommendation: Recommendation,
    ) -> None:
        """Save complete evaluation to database."""
        import sqlite3
        from uuid import uuid4

        conn = sqlite3.connect(self.db_path)
        try:
            now = datetime.now().isoformat()

            # Save paper
            conn.execute(
                """
                INSERT OR REPLACE INTO research_papers
                (id, title, authors, source_url, source_type, arxiv_id,
                 publication_date, raw_text, sections, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    now,
                ),
            )

            # Save comprehension
            comp_id = f"comp_{uuid4().hex[:12]}"
            conn.execute(
                """
                INSERT INTO comprehensions
                (id, paper_id, core_idea, problem_addressed, proposed_solution,
                 key_contributions, technical_approach, claimed_results,
                 novelty_score, novelty_rationale, comprehension_confidence,
                 key_terms, llm_model, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

            # Save evaluation
            eval_id = f"eval_{uuid4().hex[:12]}"
            conn.execute(
                """
                INSERT INTO evaluations
                (id, paper_id, comprehension_id, relevance_score, relevance_rationale,
                 feasibility_score, feasibility_rationale, novelty_score, novelty_rationale,
                 roi_score, roi_rationale, safety_score, safety_rationale, overall_score,
                 honest_assessment,
                 conflicts, implementation_complexity, maintenance_burden, expertise_gap,
                 estimated_effort, concerns, risks, potential_benefits,
                 structured_cons, competitive_landscape, value_proposition,
                 llm_model, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

            # Save recommendation
            rec_id = f"rec_{uuid4().hex[:12]}"
            conn.execute(
                """
                INSERT INTO recommendations
                (id, paper_id, evaluation_id, verdict, verdict_rationale, executive_summary,
                 implementation_roadmap, adoption_strategy, next_agent, priority,
                 blocking_dependencies, handoff_context, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec_id,
                    paper.id,
                    eval_id,
                    recommendation.verdict.value,
                    recommendation.verdict_rationale,
                    recommendation.executive_summary,
                    json.dumps(recommendation.implementation_roadmap.to_dict())
                        if recommendation.implementation_roadmap else None,
                    json.dumps(recommendation.adoption_strategy.to_dict())
                        if recommendation.adoption_strategy else None,
                    recommendation.next_agent,
                    recommendation.priority.value,
                    json.dumps(recommendation.blocking_dependencies),
                    json.dumps(recommendation.handoff_context)
                        if recommendation.handoff_context else None,
                    now,
                ),
            )

            conn.commit()
            logger.info(f"Saved evaluation for paper {paper.id}")

        finally:
            conn.close()

    def save_report(
        self,
        paper_id: str,
        report_markdown: str,
        title: Optional[str] = None,
    ) -> str:
        """Save the full markdown report to database and file system.

        This makes the report accessible to other agents for retrieval.
        Reports are saved to:
        1. ~/.amprealize/research/reports/ (user data directory)
        2. SQLite research_reports table (source of truth)

        Args:
            paper_id: ID of the paper this report is for
            report_markdown: Full markdown report content
            title: Optional title for the report filename

        Returns:
            Path to the saved report file.
        """
        import sqlite3
        import re
        from uuid import uuid4
        from pathlib import Path

        # Create a safe filename from title or paper_id
        if title:
            # Sanitize title for filename: lowercase, replace spaces with underscores, remove special chars
            safe_name = re.sub(r'[^\w\s-]', '', title.lower())
            safe_name = re.sub(r'[\s]+', '_', safe_name)
            safe_name = safe_name[:80]  # Limit length
            safe_filename = f"{safe_name}_{paper_id[:8]}.md"
        else:
            safe_filename = f"{paper_id}_report.md"

        # 1. Save to user data directory (~/.amprealize/research/reports/)
        user_reports_dir = Path(self.db_path).parent / "research" / "reports"
        user_reports_dir.mkdir(parents=True, exist_ok=True)
        user_report_path = user_reports_dir / safe_filename
        user_report_path.write_text(report_markdown, encoding="utf-8")

        # Save to database
        conn = sqlite3.connect(self.db_path)
        try:
            now = datetime.now().isoformat()
            report_id = f"report_{uuid4().hex[:12]}"
            word_count = len(report_markdown.split())

            conn.execute(
                """
                INSERT OR REPLACE INTO research_reports
                (id, paper_id, report_markdown, report_file_path, word_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    report_id,
                    paper_id,
                    report_markdown,
                    str(user_report_path),
                    word_count,
                    now,
                ),
            )
            conn.commit()
            logger.info(f"Saved report for paper {paper_id} to {user_report_path}")

        finally:
            conn.close()

        return str(user_report_path)

    def get_report(self, paper_id: str) -> Optional[str]:
        """Retrieve the full markdown report for a paper.

        This allows other agents to access evaluation context.

        Args:
            paper_id: ID of the paper to get report for

        Returns:
            Markdown report content, or None if not found
        """
        import sqlite3

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                "SELECT report_markdown FROM research_reports WHERE paper_id = ?",
                (paper_id,),
            )
            row = cursor.fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def list_reports(self, limit: int = 20) -> List[Dict[str, Any]]:
        """List available research reports.

        Returns summary info about available reports for agent discovery.

        Args:
            limit: Maximum number of reports to return

        Returns:
            List of report summaries with paper_id, title, verdict, created_at
        """
        import sqlite3

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                """
                SELECT rr.paper_id, p.title, r.verdict, e.overall_score,
                       rr.word_count, rr.report_file_path, rr.created_at
                FROM research_reports rr
                JOIN research_papers p ON p.id = rr.paper_id
                JOIN recommendations r ON r.paper_id = rr.paper_id
                JOIN evaluations e ON e.paper_id = rr.paper_id
                ORDER BY rr.created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            return [
                {
                    "paper_id": row[0],
                    "title": row[1],
                    "verdict": row[2],
                    "overall_score": row[3],
                    "word_count": row[4],
                    "file_path": row[5],
                    "created_at": row[6],
                }
                for row in rows
            ]
        finally:
            conn.close()

    def update_research_index(self) -> Optional[str]:
        """Regenerate the RESEARCH_INDEX.md file with all evaluated papers.

        This index provides a prioritized view of all research evaluations
        for easy reference and reprioritization over time.

        Returns:
            Path to the index file, or None if project dir not found
        """
        import sqlite3
        from pathlib import Path
        from datetime import datetime

        conn = sqlite3.connect(self.db_path)
        try:
            # Get all papers with their evaluations, grouped by verdict
            cursor = conn.execute(
                """
                SELECT p.id, p.title, p.source_url, p.source_type,
                       LENGTH(p.raw_text) / 5 as word_count,
                       r.verdict, r.priority, e.overall_score, e.relevance_score,
                       e.feasibility_score, e.novelty_score, e.roi_score, e.safety_score,
                       c.core_idea, rr.report_file_path, p.created_at
                FROM research_papers p
                JOIN recommendations r ON r.paper_id = p.id
                JOIN evaluations e ON e.paper_id = p.id
                LEFT JOIN comprehensions c ON c.paper_id = p.id
                LEFT JOIN research_reports rr ON rr.paper_id = p.id
                ORDER BY
                    CASE r.verdict
                        WHEN 'ADOPT' THEN 1
                        WHEN 'ADAPT' THEN 2
                        WHEN 'DEFER' THEN 3
                        WHEN 'REJECT' THEN 4
                    END,
                    CASE r.priority
                        WHEN 'P1' THEN 1
                        WHEN 'P2' THEN 2
                        WHEN 'P3' THEN 3
                        WHEN 'P4' THEN 4
                    END,
                    e.overall_score DESC
                """,
            )
            rows = cursor.fetchall()
        finally:
            conn.close()

        if not rows:
            return None

        # Build the index markdown
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        lines = [
            "# Research Evaluation Index",
            "",
            f"**Last Updated**: {now}",
            f"**Total Papers Evaluated**: {len(rows)}",
            "",
            "---",
            "",
            "## Summary by Verdict",
            "",
        ]

        # Count by verdict
        verdict_counts = {}
        verdict_papers = {"ADOPT": [], "ADAPT": [], "DEFER": [], "REJECT": []}

        for row in rows:
            verdict = row[5]
            verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
            verdict_papers[verdict].append(row)

        verdict_emoji = {"ADOPT": "🎉", "ADAPT": "🔧", "DEFER": "⏳", "REJECT": "❌"}

        for verdict in ["ADOPT", "ADAPT", "DEFER", "REJECT"]:
            count = verdict_counts.get(verdict, 0)
            emoji = verdict_emoji[verdict]
            lines.append(f"- **{emoji} {verdict}**: {count} paper(s)")

        lines.extend([
            "",
            "---",
            "",
        ])

        # Detail sections by verdict
        for verdict in ["ADOPT", "ADAPT", "DEFER", "REJECT"]:
            papers = verdict_papers.get(verdict, [])
            if not papers:
                continue

            emoji = verdict_emoji[verdict]
            lines.extend([
                f"## {emoji} {verdict}",
                "",
            ])

            for row in papers:
                paper_id = row[0]
                title = row[1] or "Untitled"
                source = row[2] or ""
                source_type = row[3] or "unknown"
                word_count = row[4] or 0
                priority = row[6] or "P3"
                overall = row[7] or 0
                relevance = row[8] or 0
                feasibility = row[9] or 0
                novelty = row[10] or 0
                roi = row[11] or 0
                safety = row[12] or 0
                report_path = row[14] or ""
                created_at = row[15] or ""

                # Extract just filename from report path
                report_file = Path(report_path).name if report_path else f"{paper_id}_report.md"

                # Truncate source for display
                source_display = source[:60] + "..." if len(source) > 60 else source

                lines.extend([
                    f"### {title}",
                    "",
                    f"| Field | Value |",
                    f"|-------|-------|",
                    f"| **Paper ID** | `{paper_id}` |",
                    f"| **Priority** | {priority} |",
                    f"| **Overall Score** | {overall:.1f}/10 |",
                    f"| **Source** | {source_type}: {source_display} |",
                    f"| **Words** | {word_count:,} |",
                    f"| **Evaluated** | {created_at[:10] if created_at else 'Unknown'} |",
                    f"| **Report** | [{report_file}]({report_file}) |",
                    "",
                    f"**Scores**: Relevance {relevance:.1f} | Feasibility {feasibility:.1f} | Novelty {novelty:.1f} | ROI {roi:.1f} | Safety {safety:.1f}",
                    "",
                ])

        # Add usage section
        lines.extend([
            "---",
            "",
            "## Usage",
            "",
            "### Reprioritization",
            "",
            "To reprioritize papers, consider:",
            "1. **Business context changes** - Has Amprealize's roadmap shifted?",
            "2. **New research** - Does newer work supersede older evaluations?",
            "3. **Resource availability** - Can we now tackle previously deferred work?",
            "4. **Dependency changes** - Are blockers resolved?",
            "",
            "### CLI Commands",
            "",
            "```bash",
            "# List all evaluated papers",
            "amprealize research list",
            "",
            "# Get full report for a paper",
            "amprealize research get <paper_id>",
            "",
            "# Re-evaluate a paper with updated context",
            "amprealize research evaluate <source>",
            "```",
            "",
            "---",
            "",
            "*Index generated by Amprealize Research Service*",
        ])

        index_content = "\n".join(lines)

        # Save to user data directory
        try:
            from pathlib import Path
            reports_dir = Path(self.db_path).parent / "research" / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            index_path = reports_dir / "RESEARCH_INDEX.md"
            index_path.write_text(index_content, encoding="utf-8")
            logger.info(f"Updated research index: {index_path}")
            return str(index_path)
        except Exception as e:
            logger.warning(f"Could not update research index: {e}")

        return None

    def search_papers(self, request: SearchPapersRequest) -> SearchPapersResponse:
        """Search evaluated papers."""
        import sqlite3

        conn = sqlite3.connect(self.db_path)
        try:
            query = """
                SELECT p.id, p.title, p.source_type, e.overall_score, r.verdict,
                       c.core_idea, p.created_at
                FROM research_papers p
                JOIN evaluations e ON e.paper_id = p.id
                JOIN recommendations r ON r.paper_id = p.id
                JOIN comprehensions c ON c.paper_id = p.id
                WHERE 1=1
            """
            params: List[Any] = []

            if request.verdict:
                query += " AND r.verdict = ?"
                params.append(request.verdict.value)

            if request.min_score is not None:
                query += " AND e.overall_score >= ?"
                params.append(request.min_score)

            if request.source_type:
                query += " AND p.source_type = ?"
                params.append(request.source_type.value)

            if request.since:
                query += " AND p.created_at >= ?"
                params.append(request.since.isoformat())

            query += " ORDER BY p.created_at DESC"
            query += f" LIMIT {request.limit} OFFSET {request.offset}"

            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

            papers = [
                PaperSummary(
                    paper_id=row[0],
                    title=row[1],
                    source_type=SourceType(row[2]),
                    overall_score=row[3],
                    verdict=Verdict(row[4]),
                    core_idea=row[5],
                    created_at=datetime.fromisoformat(row[6]),
                )
                for row in rows
            ]

            # Get total count
            count_query = """
                SELECT COUNT(*) FROM research_papers p
                JOIN recommendations r ON r.paper_id = p.id
                WHERE 1=1
            """
            count_params: List[Any] = []
            if request.verdict:
                count_query += " AND r.verdict = ?"
                count_params.append(request.verdict.value)

            cursor = conn.execute(count_query, count_params)
            total_count = cursor.fetchone()[0]

            return SearchPapersResponse(
                papers=papers,
                total_count=total_count,
                has_more=request.offset + len(papers) < total_count,
            )

        finally:
            conn.close()

    def get_paper(self, paper_id: str) -> Optional[EvaluatePaperResponse]:
        """Get full evaluation for a paper."""
        import sqlite3

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.cursor()

            # Get paper
            cur.execute("SELECT * FROM research_papers WHERE id = ?", (paper_id,))
            paper_row = cur.fetchone()
            if not paper_row:
                return None

            # Get comprehension
            cur.execute("SELECT * FROM comprehensions WHERE paper_id = ?", (paper_id,))
            comp_row = cur.fetchone()
            if not comp_row:
                return None

            # Get evaluation
            cur.execute("SELECT * FROM evaluations WHERE paper_id = ?", (paper_id,))
            eval_row = cur.fetchone()
            if not eval_row:
                return None

            # Get recommendation
            cur.execute("SELECT * FROM recommendations WHERE paper_id = ?", (paper_id,))
            rec_row = cur.fetchone()
            if not rec_row:
                return None

            # Reconstruct objects
            from amprealize.research_contracts import (
                AdoptionStrategy,
                IngestedPaper, PaperMetadata, ParsedSection,
                ComprehensionResult, ClaimedResult,
                CompetitiveLandscapeItem, StructuredCon, ValueProposition,
                EvaluationResult, ConflictItem, Complexity,
                Recommendation, ImplementationRoadmap, SourceType, Verdict, Priority,
                EvaluatePaperResponse,
            )

            # Build PaperMetadata
            metadata_dict = json.loads(paper_row["metadata"]) if paper_row["metadata"] else {}
            metadata = PaperMetadata(
                title=paper_row["title"],
                authors=json.loads(paper_row["authors"]) if paper_row["authors"] else [],
                source_url=paper_row["source_url"],
                arxiv_id=paper_row["arxiv_id"],
                publication_date=paper_row["publication_date"],
                abstract=metadata_dict.get("abstract", ""),
                keywords=metadata_dict.get("keywords", []),
            )

            # Build sections
            sections_data = json.loads(paper_row["sections"]) if paper_row["sections"] else []
            sections = [
                ParsedSection(
                    name=s.get("name", s.get("title", "")),
                    content=s.get("content", ""),
                    level=s.get("level", 1),
                )
                for s in sections_data
            ]

            # Build IngestedPaper
            paper = IngestedPaper(
                id=paper_row["id"],
                source=paper_row["source_url"] or "",
                source_type=SourceType(paper_row["source_type"]),
                metadata=metadata,
                raw_text=paper_row["raw_text"] or "",
                sections=sections,
                word_count=len((paper_row["raw_text"] or "").split()),
            )

            # Build ClaimedResults
            claimed_results_data = json.loads(comp_row["claimed_results"]) if comp_row["claimed_results"] else []
            claimed_results = [
                ClaimedResult(
                    metric=r.get("metric", r.get("claim", "")),
                    improvement=r.get("improvement", r.get("evidence", "")),
                    conditions=r.get("conditions", ""),
                )
                for r in claimed_results_data
            ]

            # Build ComprehensionResult
            comprehension = ComprehensionResult(
                core_idea=comp_row["core_idea"],
                problem_addressed=comp_row["problem_addressed"],
                proposed_solution=comp_row["proposed_solution"],
                key_contributions=json.loads(comp_row["key_contributions"]) if comp_row["key_contributions"] else [],
                technical_approach=comp_row["technical_approach"],
                claimed_results=claimed_results,
                novelty_score=comp_row["novelty_score"],
                novelty_rationale=comp_row["novelty_rationale"],
                comprehension_confidence=comp_row["comprehension_confidence"],
                key_terms=json.loads(comp_row["key_terms"]) if comp_row["key_terms"] else [],
                llm_model=comp_row["llm_model"],
            )

            # Build Conflicts
            conflicts_data = json.loads(eval_row["conflicts"]) if eval_row["conflicts"] else []
            conflicts = [
                ConflictItem(
                    behavior_name=c.get("behavior_name", c.get("component", "")),
                    description=c.get("description", ""),
                    severity=c.get("severity", "low"),
                )
                for c in conflicts_data
            ]

            # Reconstruct structured_cons from stored JSON (column may not exist in older DBs)
            stored_structured_cons = []
            try:
                sc_data = json.loads(eval_row["structured_cons"]) if eval_row["structured_cons"] else []
                stored_structured_cons = [
                    StructuredCon(
                        description=sc.get("description", ""),
                        severity=sc.get("severity", "medium"),
                        likelihood=sc.get("likelihood", "medium"),
                        mitigation=sc.get("mitigation", ""),
                        category=sc.get("category", ""),
                    )
                    for sc in sc_data
                ]
            except (KeyError, IndexError):
                pass

            # Reconstruct competitive_landscape from stored JSON
            stored_landscape = []
            try:
                cl_data = json.loads(eval_row["competitive_landscape"]) if eval_row["competitive_landscape"] else []
                stored_landscape = [
                    CompetitiveLandscapeItem(
                        name=item.get("name", ""),
                        category=item.get("category", "tool"),
                        url=item.get("url"),
                        description=item.get("description", ""),
                        maturity=item.get("maturity", "unknown"),
                        overlap_description=item.get("overlap_description", ""),
                        differentiators=item.get("differentiators", []),
                    )
                    for item in cl_data
                ]
            except (KeyError, IndexError):
                pass

            # Reconstruct value_proposition from stored JSON
            stored_vp = None
            try:
                vp_data = json.loads(eval_row["value_proposition"]) if eval_row["value_proposition"] else None
                if vp_data and isinstance(vp_data, dict):
                    stored_vp = ValueProposition(
                        effectiveness_summary=vp_data.get("effectiveness_summary", ""),
                        key_benefits=vp_data.get("key_benefits", []),
                        measurable_outcomes=vp_data.get("measurable_outcomes", []),
                        value_to_amprealize=vp_data.get("value_to_amprealize", ""),
                    )
            except (KeyError, IndexError):
                pass

            # Reconstruct honest_assessment (column may not exist in older DBs)
            stored_honest_assessment = ""
            try:
                stored_honest_assessment = eval_row["honest_assessment"] or ""
            except (KeyError, IndexError):
                pass

            # Build EvaluationResult
            evaluation = EvaluationResult(
                relevance_score=eval_row["relevance_score"],
                relevance_rationale=eval_row["relevance_rationale"],
                feasibility_score=eval_row["feasibility_score"],
                feasibility_rationale=eval_row["feasibility_rationale"],
                novelty_score=eval_row["novelty_score"],
                novelty_rationale=eval_row["novelty_rationale"],
                roi_score=eval_row["roi_score"],
                roi_rationale=eval_row["roi_rationale"],
                safety_score=eval_row["safety_score"],
                safety_rationale=eval_row["safety_rationale"],
                overall_score=eval_row["overall_score"],
                honest_assessment=stored_honest_assessment,
                conflicts_with_existing=conflicts,
                implementation_complexity=Complexity(eval_row["implementation_complexity"]),
                maintenance_burden=Complexity(eval_row["maintenance_burden"]),
                expertise_gap=Complexity(eval_row["expertise_gap"]),
                estimated_effort=eval_row["estimated_effort"],
                concerns=json.loads(eval_row["concerns"]) if eval_row["concerns"] else [],
                risks=json.loads(eval_row["risks"]) if eval_row["risks"] else [],
                structured_cons=stored_structured_cons,
                potential_benefits=json.loads(eval_row["potential_benefits"]) if eval_row["potential_benefits"] else [],
                competitive_landscape=stored_landscape,
                value_proposition=stored_vp,
                llm_model=eval_row["llm_model"],
            )

            # Build ImplementationRoadmap if present
            roadmap_data = json.loads(rec_row["implementation_roadmap"]) if rec_row["implementation_roadmap"] else None
            roadmap = None
            if roadmap_data:
                roadmap = ImplementationRoadmap(
                    affected_components=roadmap_data.get("affected_components", []),
                    proposed_steps=roadmap_data.get("proposed_steps", []),
                    success_criteria=roadmap_data.get("success_criteria", []),
                    estimated_effort=roadmap_data.get("estimated_effort", ""),
                )

            # Reconstruct adoption_strategy from stored JSON
            stored_adoption = None
            try:
                as_data = json.loads(rec_row["adoption_strategy"]) if rec_row["adoption_strategy"] else None
                if as_data and isinstance(as_data, dict):
                    stored_adoption = AdoptionStrategy(
                        approach=as_data.get("approach", "build_custom"),
                        rationale=as_data.get("rationale", ""),
                        direct_use_candidates=as_data.get("direct_use_candidates", []),
                        concepts_to_extract=as_data.get("concepts_to_extract", []),
                        integration_points=as_data.get("integration_points", []),
                        estimated_time_saved=as_data.get("estimated_time_saved", ""),
                    )
            except (KeyError, IndexError):
                pass

            # Reconstruct handoff_context from stored JSON
            stored_handoff_ctx: Dict[str, Any] = {}
            try:
                stored_handoff_ctx = json.loads(rec_row["handoff_context"]) if rec_row["handoff_context"] else {}
            except (KeyError, IndexError):
                pass

            # Reconstruct executive_summary
            stored_exec_summary = ""
            try:
                stored_exec_summary = rec_row["executive_summary"] or ""
            except (KeyError, IndexError):
                pass

            # Build Recommendation
            recommendation = Recommendation(
                verdict=Verdict(rec_row["verdict"]),
                verdict_rationale=rec_row["verdict_rationale"],
                executive_summary=stored_exec_summary,
                implementation_roadmap=roadmap,
                adoption_strategy=stored_adoption,
                next_agent=rec_row["next_agent"],
                priority=Priority(rec_row["priority"]) if rec_row["priority"] else Priority.P3,
                blocking_dependencies=json.loads(rec_row["blocking_dependencies"]) if rec_row["blocking_dependencies"] else [],
                handoff_context=stored_handoff_ctx,
            )

            # Build final response
            return EvaluatePaperResponse(
                paper_id=paper_id,
                paper_title=paper.metadata.title,
                ingested_paper=paper,
                comprehension=comprehension,
                evaluation=evaluation,
                recommendation=recommendation,
            )

        finally:
            conn.close()
