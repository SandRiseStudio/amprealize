"""Behavior-Conditioned Inference service stubs leveraging BCI contracts."""

from __future__ import annotations

import json
import logging
import math
import re
import statistics
from collections import Counter
from dataclasses import asdict
from time import perf_counter
from typing import Any, Dict, Iterable, List, Optional

from .behavior_retriever import BehaviorRetriever
from .behavior_service import BehaviorService, SearchBehaviorsRequest
from .telemetry import TelemetryClient
from .llm import (
    LLMClient,
    LLMConfig,
    LLMResponse,
    LLMError,
    TokenBudgetError,
)
from .bci_contracts import (
    BatchComposePromptRequest,
    BatchComposePromptResponse,
    BatchComposeResult,
    BehaviorMatch,
    BehaviorSnippet,
    Citation,
    CitationMode,
    CitationType,
    ComposePromptRequest,
    ComposePromptResponse,
    ComputeTokenSavingsRequest,
    ComputeTokenSavingsResponse,
    DetectPatternsRequest,
    DetectPatternsResponse,
    Pattern,
    PatternCandidate,
    PromptFormat,
    RetrieveRequest,
    RetrieveResponse,
    RetrievalStrategy,
    RoleFocus,
    ScoreDimension,
    ScoreDimensionName,
    ScoreReusabilityRequest,
    ScoreReusabilityResponse,
    SegmentTraceRequest,
    SegmentTraceResponse,
    TraceFormat,
    TraceInput,
    TraceStep,
    ValidateCitationsRequest,
    ValidateCitationsResponse,
    ParseCitationsRequest,
    ParseCitationsResponse,
    PrependedBehavior,
)

_DEFAULT_PROMPT_INSTRUCTION = (
    "When solving the task below, reference these behaviors by name when you apply them."
)
_DEFAULT_SCORE_WEIGHTS = (
    (ScoreDimensionName.CLARITY, 0.30),
    (ScoreDimensionName.GENERALITY, 0.30),
    (ScoreDimensionName.REUSABILITY, 0.25),
    (ScoreDimensionName.CORRECTNESS, 0.15),
)
_DEFAULT_CITATION_PATTERNS: List[str] = [
    r"(behavior_[a-zA-Z0-9_]+)",
    r"\((behavior_[a-zA-Z0-9_]+)\)",
    r"\[(behavior_[a-zA-Z0-9_]+)\]",
]


def _safe_role_focus(value: Optional[str]) -> Optional[RoleFocus]:
    if value is None:
        return None
    try:
        return RoleFocus(value)
    except ValueError:
        return None


logger = logging.getLogger(__name__)


class BCIService:
    """High-level BCI orchestration helpers used across adapters."""

    def __init__(
        self,
        *,
        behavior_service: Optional[BehaviorService] = None,
        telemetry: Optional[TelemetryClient] = None,
        behavior_retriever: Optional[BehaviorRetriever] = None,
    ) -> None:
        self._telemetry = telemetry or TelemetryClient.noop()
        self._behavior_service = behavior_service
        self._retriever = behavior_retriever
        if self._retriever is None and behavior_service is not None:
            self._retriever = BehaviorRetriever(
                behavior_service=behavior_service,
                telemetry=self._telemetry,
            )

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    def retrieve(self, request: RetrieveRequest) -> RetrieveResponse:
        start = perf_counter()
        matches = self._retrieve_matches(request)
        latency_ms = (perf_counter() - start) * 1000.0
        response = RetrieveResponse(
            query=request.query,
            results=matches,
            strategy_used=request.strategy,
            latency_ms=round(latency_ms, 3),
            metadata={
                "behavior_count": len(matches),
                "include_metadata": request.include_metadata,
                "trace_context_present": bool(request.trace_context),
                "retriever_mode": self._retriever.mode if self._retriever else "legacy",
            },
        )
        self._telemetry.emit_event(
            event_type="bci.retrieve",
            payload={
                "query_length": len(request.query or ""),
                "strategy": request.strategy.value,
                "top_k": request.top_k,
                "result_count": len(matches),
            },
        )
        return response

    def _retrieve_matches(self, request: RetrieveRequest) -> List[BehaviorMatch]:
        if self._retriever is not None:
            try:
                return self._retriever.retrieve(request)
            except Exception as exc:  # pragma: no cover - defensive fallback
                logger.warning("BehaviorRetriever failed, falling back to keyword search. Error: %s", exc)

        if self._behavior_service is None:
            return []

        search_limit = max(request.top_k, 1) * (2 if request.strategy == RetrievalStrategy.HYBRID else 1)
        search_request = SearchBehaviorsRequest(
            query=request.query,
            tags=request.tags,
            role_focus=request.role_focus.value if request.role_focus else None,
            status="APPROVED",
            limit=search_limit,
            namespace=request.namespace,
        )
        results = self._behavior_service.search_behaviors(search_request)
        matches: List[BehaviorMatch] = []
        for result in results[: request.top_k]:
            metadata = result.active_version.metadata if request.include_metadata else None
            citation_label = metadata.get("citation_label") if metadata else None
            breakdown = None
            if request.strategy == RetrievalStrategy.HYBRID:
                breakdown = {
                    "embedding": request.embedding_weight,
                    "keyword": request.keyword_weight,
                }
            elif request.strategy == RetrievalStrategy.EMBEDDING:
                breakdown = {"embedding": 1.0}
            elif request.strategy == RetrievalStrategy.KEYWORD:
                breakdown = {"keyword": 1.0}

            match = BehaviorMatch(
                behavior_id=result.behavior.behavior_id,
                name=result.behavior.name,
                instruction=result.active_version.instruction,
                version=result.active_version.version,
                score=float(result.score),
                description=result.behavior.description,
                role_focus=_safe_role_focus(result.active_version.role_focus),
                tags=list(result.behavior.tags),
                strategy_breakdown=breakdown,
                citation_label=citation_label or result.behavior.name,
                metadata=metadata,
            )
            matches.append(match)
        return matches

    # ------------------------------------------------------------------
    # Prompt composition
    # ------------------------------------------------------------------
    def compose_prompt(self, request: ComposePromptRequest) -> ComposePromptResponse:
        behaviors = self._trim_behaviors(request.behaviors, request.max_behaviors)
        instruction = request.citation_instruction or _DEFAULT_PROMPT_INSTRUCTION

        # E3 Runtime Injection: compose enriched prompt when context is available
        if request.runtime_context or request.overlay_instructions or request.primer_text:
            prompt = self._render_enriched_prompt(
                query=request.query,
                behaviors=behaviors,
                prompt_format=request.format,
                instruction=instruction,
                runtime_context=request.runtime_context,
                overlay_instructions=request.overlay_instructions,
                primer_text=request.primer_text,
                runtime_constraints=request.runtime_constraints,
            )
            overlays_included = (
                request.runtime_context.get("recommended_overlays", [])
                if request.runtime_context
                else []
            )
        else:
            prompt = self._render_prompt(request.query, behaviors, request.format, instruction)
            overlays_included = []

        metadata = {
            "citation_mode": request.citation_mode.value,
            "format": request.format.value,
            "citation_instruction": instruction,
        }
        self._telemetry.emit_event(
            event_type="bci.compose_prompt",
            payload={
                "behaviors": len(behaviors),
                "format": request.format.value,
                "citation_mode": request.citation_mode.value,
                "has_runtime_context": request.runtime_context is not None,
                "overlays_count": len(overlays_included),
            },
        )
        return ComposePromptResponse(
            prompt=prompt,
            behaviors=behaviors,
            metadata=metadata,
            overlays_included=overlays_included,
        )

    def compose_prompts_batch(self, request: BatchComposePromptRequest) -> BatchComposePromptResponse:
        items: List[BatchComposeResult] = []
        for item in request.items:
            snippet_mode = item.citation_mode or CitationMode.EXPLICIT
            snippet_format = item.format or PromptFormat.LIST
            compose_request = ComposePromptRequest(
                query=item.query,
                behaviors=item.behaviors,
                citation_mode=snippet_mode,
                format=snippet_format,
            )
            response = self.compose_prompt(compose_request)
            items.append(BatchComposeResult(query=item.query, prompt=response.prompt, behaviors=response.behaviors))
        return BatchComposePromptResponse(items=items)

    @staticmethod
    def _trim_behaviors(behaviors: List[BehaviorSnippet], limit: Optional[int]) -> List[BehaviorSnippet]:
        if limit is None:
            return behaviors
        return behaviors[:limit]

    @staticmethod
    def _render_prompt(
        query: str,
        behaviors: List[BehaviorSnippet],
        prompt_format: PromptFormat,
        instruction: str,
    ) -> str:
        if prompt_format is PromptFormat.LIST:
            lines = ["Relevant behaviors from the handbook:"]
            for snippet in behaviors:
                label = snippet.citation_label or snippet.name
                lines.append(f"- {label}: {snippet.instruction}")
            lines.extend(["", instruction, "", "Task:", query])
            return "\n".join(lines)
        if prompt_format is PromptFormat.PROSE:
            entries = [
                f"{snippet.citation_label or snippet.name} instructs: {snippet.instruction}"
                for snippet in behaviors
            ]
            prose = " ".join(entries)
            return f"{prose}\n\n{instruction}\n\nTask:\n{query}"
        # Structured fallback (JSON payload)
        payload = {
            "instruction": instruction,
            "behaviors": [asdict(snippet) for snippet in behaviors],
            "task": query,
        }
        return json.dumps(payload, indent=2)

    @staticmethod
    def _render_enriched_prompt(
        *,
        query: str,
        behaviors: List[BehaviorSnippet],
        prompt_format: PromptFormat,
        instruction: str,
        runtime_context: Optional[Dict[str, Any]] = None,
        overlay_instructions: Optional[List[str]] = None,
        primer_text: Optional[str] = None,
        runtime_constraints: Optional[List[str]] = None,
    ) -> str:
        """Render a prompt enriched with runtime context, overlays, and primer.

        E3 Runtime Injection (AMPREALIZE-289 / T3.3.1).
        Falls back to LIST format structure when enriched context is present,
        since the richer block benefits from structured sections.
        """
        sections: List[str] = []

        # 1. Runtime context header
        if runtime_context:
            ctx_parts = ["## Amprealize Runtime Context"]
            profile = runtime_context.get("workspace_profile", "unknown")
            surface = runtime_context.get("surface", "unknown")
            role = runtime_context.get("role", "unspecified")
            ctx_parts.append(f"**Workspace**: {profile} | **Surface**: {surface} | **Role**: {role}")
            pack_id = runtime_context.get("active_pack_id")
            pack_ver = runtime_context.get("active_pack_version")
            if pack_id:
                pack_label = f"{pack_id}@{pack_ver}" if pack_ver else pack_id
                ctx_parts.append(f"**Active Pack**: {pack_label}")
            sections.append("\n".join(ctx_parts))

        # 2. Behaviors
        if behaviors:
            lines = ["## Relevant Behaviors"]
            for snippet in behaviors:
                label = snippet.citation_label or snippet.name
                lines.append(f"- {label}: {snippet.instruction}")
            sections.append("\n".join(lines))

        # 3. Primer / operational guidance
        guidance_parts: List[str] = []
        if primer_text:
            guidance_parts.append(primer_text)
        if overlay_instructions:
            guidance_parts.extend(overlay_instructions)
        if guidance_parts:
            sections.append("## Operational Guidance\n" + "\n\n".join(guidance_parts))

        # 4. Constraints
        if runtime_constraints:
            constraint_lines = ["## Constraints"]
            for c in runtime_constraints:
                constraint_lines.append(f"- {c}")
            sections.append("\n".join(constraint_lines))

        # 5. Instruction + task
        sections.append(instruction)
        sections.append(f"Task:\n{query}")

        return "\n\n".join(sections)

    # ------------------------------------------------------------------
    # Citation parsing & validation
    # ------------------------------------------------------------------
    def parse_citations(self, request: ParseCitationsRequest) -> ParseCitationsResponse:
        patterns: List[str] = list(_DEFAULT_CITATION_PATTERNS)
        if request.patterns:
            patterns.extend(request.patterns)
        text = request.output_text
        citations: List[Citation] = []
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                label = match.group(1) if match.lastindex else match.group(0)
                citations.append(
                    Citation(
                        text=match.group(0),
                        type=CitationType.EXPLICIT,
                        start_index=match.start(),
                        end_index=match.end(),
                        behavior_name=label,
                        confidence=0.8,
                    )
                )
        # Deduplicate citations by span
        unique: Dict[tuple[int, int], Citation] = {}
        for citation in citations:
            key = (citation.start_index, citation.end_index)
            unique.setdefault(key, citation)
        return ParseCitationsResponse(citations=list(unique.values()))

    def validate_citations(self, request: ValidateCitationsRequest) -> ValidateCitationsResponse:
        parsed = self.parse_citations(ParseCitationsRequest(output_text=request.output_text))
        prepended = {behavior.behavior_name.lower(): behavior for behavior in request.prepended_behaviors}
        valid: List[Citation] = []
        invalid: List[Citation] = []
        warnings: List[str] = []

        for citation in parsed.citations:
            normalized = (citation.behavior_name or citation.text).lower()
            match = prepended.get(normalized)
            if match:
                citation.behavior_id = match.behavior_id
                valid.append(citation)
            else:
                if request.allow_unlisted_behaviors:
                    warnings.append(f"Citation '{citation.text}' not in prepended list")
                else:
                    invalid.append(citation)

        cited_names = { (citation.behavior_name or "").lower() for citation in valid }
        missing = [
            behavior.behavior_name
            for behavior in request.prepended_behaviors
            if behavior.behavior_name.lower() not in cited_names
        ]
        total_citations = len(parsed.citations)
        denom = max(len(request.prepended_behaviors), 1)
        compliance_rate = len(valid) / denom
        is_compliant = (
            len(valid) >= request.minimum_citations
            and (not invalid or request.allow_unlisted_behaviors)
        )
        return ValidateCitationsResponse(
            total_citations=total_citations,
            valid_citations=valid,
            invalid_citations=invalid,
            compliance_rate=round(compliance_rate, 3),
            is_compliant=is_compliant,
            missing_behaviors=missing,
            warnings=warnings,
        )

    def compute_token_savings(self, request: ComputeTokenSavingsRequest) -> ComputeTokenSavingsResponse:
        savings = max(request.baseline_tokens - request.bci_tokens, -request.baseline_tokens)
        pct = 0.0
        if request.baseline_tokens > 0:
            pct = savings / request.baseline_tokens
        return ComputeTokenSavingsResponse(token_savings=savings, token_savings_pct=round(pct, 4))

    # ------------------------------------------------------------------
    # Trace operations
    # ------------------------------------------------------------------
    def segment_trace(self, request: SegmentTraceRequest) -> SegmentTraceResponse:
        if request.format == TraceFormat.JSON_STEPS:
            try:
                parsed = json.loads(request.trace_text)
                steps = [
                    TraceStep(index=index, text=item.get("text", json.dumps(item)), metadata={k: v for k, v in item.items() if k != "text"})
                    for index, item in enumerate(parsed)
                ]
                return SegmentTraceResponse(steps=steps)
            except json.JSONDecodeError:
                pass  # Fall back to manual parsing
        if request.format == TraceFormat.PLAN_MARKDOWN:
            lines = [line.strip("- ") for line in request.trace_text.splitlines() if line.strip()]
        else:
            lines = [line.strip() for line in request.trace_text.splitlines() if line.strip()]
        steps = [TraceStep(index=i, text=line) for i, line in enumerate(lines)]
        return SegmentTraceResponse(steps=steps)

    def detect_patterns(self, request: DetectPatternsRequest) -> DetectPatternsResponse:
        counter: Counter[str] = Counter()
        window = request.window_size or 1
        segmented: List[List[TraceStep]] = []
        for trace in request.traces:
            formatted = trace.format or TraceFormat.CHAIN_OF_THOUGHT
            segment = self.segment_trace(
                SegmentTraceRequest(trace_text=trace.trace_text, format=formatted)
            )
            segmented.append(segment.steps)
            texts = [step.text for step in segment.steps]
            for slice_start in range(len(texts)):
                slice_end = slice_start + window
                if slice_end > len(texts):
                    break
                snippet = " | ".join(texts[slice_start:slice_end])
                counter[snippet] += 1
        patterns: List[Pattern] = []
        for idx, (snippet, occurrences) in enumerate(counter.most_common()):
            if occurrences < request.min_occurrences:
                continue
            pattern = Pattern(
                pattern_id=f"pattern-{idx+1:03d}",
                description=snippet,
                occurrence_count=occurrences,
                candidate_behavior=PatternCandidate(
                    name=f"Candidate {idx+1}",
                    instruction=snippet.split(" | ")[0],
                    supporting_traces=[trace.trace_text[:100] for trace in request.traces[:5]],
                ),
            )
            patterns.append(pattern)
        latency_ms = 5.0 + len(request.traces) * 0.25
        return DetectPatternsResponse(patterns=patterns, total_traces=len(request.traces), latency_ms=latency_ms)

    def score_reusability(self, request: ScoreReusabilityRequest) -> ScoreReusabilityResponse:
        dimensions = self._resolve_dimensions(request)
        score = sum(d.weight * d.score for d in dimensions) * 100.0
        return ScoreReusabilityResponse(score=round(score, 2), dimensions=dimensions)

    def _resolve_dimensions(self, request: ScoreReusabilityRequest) -> List[ScoreDimension]:
        if request.override_weights:
            return request.override_weights

        supporting = request.candidate_behavior.supporting_traces
        evidence_count = len(supporting) if supporting else 0
        inferred_scores = {
            ScoreDimensionName.CLARITY: 0.8,
            ScoreDimensionName.GENERALITY: min(1.0, evidence_count / 3.0 if evidence_count else 0.6),
            ScoreDimensionName.REUSABILITY: 0.75 if evidence_count >= 2 else 0.5,
            ScoreDimensionName.CORRECTNESS: 0.9,
        }
        dimensions = [
            ScoreDimension(name=name, weight=weight, score=inferred_scores.get(name, 0.5))
            for name, weight in _DEFAULT_SCORE_WEIGHTS
        ]
        return dimensions

    # ------------------------------------------------------------------
    # MCP helpers (alias for clarity)
    # ------------------------------------------------------------------
    def retrieve_hybrid(self, request: RetrieveRequest) -> RetrieveResponse:
        hybrid_request = RetrieveRequest(
            query=request.query,
            top_k=request.top_k,
            strategy=RetrievalStrategy.HYBRID,
            role_focus=request.role_focus,
            tags=request.tags,
            include_metadata=request.include_metadata,
            embedding_weight=request.embedding_weight,
            keyword_weight=request.keyword_weight,
            trace_context=request.trace_context,
        )
        return self.retrieve(hybrid_request)

    def rebuild_index(self) -> Dict[str, Any]:
        if self._retriever is None:
            payload = {"status": "unsupported", "reason": "behavior retriever not configured"}
            self._telemetry.emit_event(event_type="bci.rebuild_index", payload=payload)
            return payload

        result = self._retriever.rebuild_index()
        telemetry_payload = {
            "mode": result.get("mode"),
            "status": result.get("status"),
            "behavior_count": result.get("behavior_count"),
        }
        self._telemetry.emit_event(event_type="bci.rebuild_index", payload=telemetry_payload)
        return result

    # ------------------------------------------------------------------
    # LLM Generation with BCI
    # ------------------------------------------------------------------
    def generate_response(
        self,
        query: str,
        *,
        behaviors: Optional[List[str]] = None,
        top_k: int = 5,
        llm_config: Optional[LLMConfig] = None,
        system_prompt: Optional[str] = None,
        role_focus: Optional[RoleFocus] = None,
    ) -> Dict[str, Any]:
        """Generate a behavior-conditioned LLM response.

        Args:
            query: The user query/task to solve.
            behaviors: Optional explicit behavior names to use. If not provided, retrieves top_k.
            top_k: Number of behaviors to retrieve if behaviors not provided.
            llm_config: Optional LLM configuration. If not provided, loads from environment.
            system_prompt: Optional custom system prompt. If not provided, uses default.
            role_focus: Optional role focus for behavior retrieval.

        Returns:
            Dict with:
                - response: LLMResponse with generated content
                - behaviors_used: List of behavior names prepended to prompt
                - token_savings: Dict with input_saved, output_saved, total_saved
                - latency_ms: Generation latency
        """
        start = perf_counter()

        # Retrieve behaviors if not explicitly provided
        behavior_snippets: List[BehaviorSnippet] = []
        if behaviors is None:
            retrieve_req = RetrieveRequest(
                query=query,
                top_k=top_k,
                strategy=RetrievalStrategy.HYBRID,
                role_focus=role_focus,
            )
            retrieve_resp = self.retrieve(retrieve_req)
            behavior_snippets = [
                BehaviorSnippet(
                    behavior_id=match.behavior_id,
                    name=match.name,
                    instruction=match.instruction,
                    role_focus=match.role_focus,
                )
                for match in retrieve_resp.results
            ]
        else:
            # Convert behavior names to snippets
            for behavior_name in behaviors:
                try:
                    if self._behavior_service:
                        behavior_data = self._behavior_service.get_behavior(behavior_name)
                        if behavior_data:
                            behavior_snippets.append(
                                BehaviorSnippet(
                                    behavior_id=behavior_data.get("id", behavior_name),
                                    name=behavior_name,
                                    instruction=behavior_data.get("instruction", ""),
                                )
                            )
                        else:
                            # BehaviorService returned None - use fallback
                            behavior_snippets.append(
                                BehaviorSnippet(
                                    behavior_id=behavior_name,
                                    name=behavior_name,
                                    instruction=f"Follow the {behavior_name} behavior pattern.",
                                )
                            )
                    else:
                        # No BehaviorService available - use fallback
                        behavior_snippets.append(
                            BehaviorSnippet(
                                behavior_id=behavior_name,
                                name=behavior_name,
                                instruction=f"Follow the {behavior_name} behavior pattern.",
                            )
                        )
                except Exception as exc:
                    # Skip behaviors that can't be loaded, but use fallback
                    logger.warning(f"Failed to load behavior {behavior_name}: {exc}")
                    behavior_snippets.append(
                        BehaviorSnippet(
                            behavior_id=behavior_name,
                            name=behavior_name,
                            instruction=f"Follow the {behavior_name} behavior pattern.",
                        )
                    )

        # Compose BCI prompt
        compose_req = ComposePromptRequest(
            query=query,
            behaviors=behavior_snippets,
            citation_instruction=system_prompt,
            format=PromptFormat.LIST,
        )
        compose_resp = self.compose_prompt(compose_req)

        # Get LLM client
        client = LLMClient(llm_config)

        # Build messages
        messages = [
            {"role": "system", "content": compose_resp.prompt},
            {"role": "user", "content": query},
        ]

        # Generate response (may raise TokenBudgetError)
        try:
            llm_resp: LLMResponse = client.call(messages)
        except TokenBudgetError as exc:
            # Log the budget violation and re-raise with context
            self._telemetry.emit_event(
                event_type="bci.generate_response.budget_exceeded",
                payload={
                    "query_length": len(query),
                    "behaviors_count": len(behavior_snippets),
                    "budget": exc.budget,
                    "estimated_tokens": exc.estimated_tokens,
                    "provider": str(exc.provider) if exc.provider else "unknown",
                },
            )
            raise
        except LLMError as exc:
            # Log provider errors for debugging
            self._telemetry.emit_event(
                event_type="bci.generate_response.error",
                payload={
                    "query_length": len(query),
                    "behaviors_count": len(behavior_snippets),
                    "error_type": type(exc).__name__,
                    "provider": str(exc.provider) if exc.provider else "unknown",
                },
            )
            raise

        latency_ms = (perf_counter() - start) * 1000.0

        # Compute token savings (baseline = no behaviors prepended)
        baseline_prompt_tokens = len(query.split())  # Rough estimate
        actual_input_tokens = llm_resp.input_tokens
        input_saved = max(0, actual_input_tokens - baseline_prompt_tokens)

        # Get behavior names for telemetry
        behavior_names = [b.name for b in behavior_snippets]

        # Emit telemetry to Raze with token budget and cost info
        telemetry_payload = {
            "query_length": len(query),
            "behaviors_count": len(behavior_snippets),
            "behaviors": behavior_names,
            "provider": str(llm_resp.provider),
            "model": llm_resp.model,
            "input_tokens": llm_resp.input_tokens,
            "output_tokens": llm_resp.output_tokens,
            "total_tokens": llm_resp.input_tokens + llm_resp.output_tokens,
            "token_savings_input": input_saved,
            "latency_ms": latency_ms,
            "llm_latency_ms": llm_resp.latency_ms,
            "finish_reason": llm_resp.finish_reason,
            # Cost estimation (USD)
            "estimated_cost_usd": llm_resp.cost_usd,
        }
        self._telemetry.emit_event(event_type="bci.generate_response", payload=telemetry_payload)

        return {
            "response": llm_resp,
            "behaviors_used": behavior_snippets,
            "token_savings": {
                "input_saved": input_saved,
                "output_saved": 0,  # Hard to estimate without baseline
                "total_saved": input_saved,
            },
            "cost": {
                "total_usd": llm_resp.cost_usd,
            },
            "latency_ms": latency_ms,
        }

    def improve_run(
        self,
        run_id: str,
        *,
        llm_config: Optional[LLMConfig] = None,
        max_behaviors: int = 10,
    ) -> Dict[str, Any]:
        """Analyze a failed run and generate improvement suggestions using BCI.

        Uses TraceAnalysisService to extract patterns from failed run,
        retrieves relevant behaviors, and generates actionable suggestions.

        Args:
            run_id: The run ID to analyze.
            llm_config: Optional LLM configuration.
            max_behaviors: Maximum behaviors to extract from trace.

        Returns:
            Dict with:
                - run_id: The analyzed run ID
                - patterns: List of detected patterns
                - suggestions: List of improvement suggestions
                - behaviors_extracted: List of behavior names extracted
                - latency_ms: Analysis latency
        """
        import os
        from .trace_analysis_service import TraceAnalysisService
        from .utils.dsn import apply_host_overrides

        start = perf_counter()

        # Get run details - prefer PostgreSQL when DSN is available
        dsn = apply_host_overrides(os.environ.get("AMPREALIZE_RUN_PG_DSN"), "RUN")
        if dsn:
            from .run_service_postgres import PostgresRunService
            run_service = PostgresRunService(dsn=dsn)
        else:
            from .run_service import RunService
            run_service = RunService()
        run = run_service.get_run(run_id)
        if run is None:
            raise ValueError(f"Run not found: {run_id}")

        # Analyze trace using TraceAnalysisService
        trace_service = TraceAnalysisService(
            behavior_service=self._behavior_service,
            telemetry=self._telemetry,
        )

        # Detect patterns in failed run
        detect_req = DetectPatternsRequest(
            trace=TraceInput(content=json.dumps(run), format=TraceFormat.JSON),
            min_frequency=1,  # Low threshold for single run analysis
        )
        detect_resp = self.detect_patterns(detect_req)

        # Score reusability of detected patterns
        score_req = ScoreReusabilityRequest(
            candidates=[
                PatternCandidate(
                    name=f"pattern_{i}",
                    description=pattern.description,
                    example=pattern.example_usage,
                )
                for i, pattern in enumerate(detect_resp.patterns)
            ]
        )
        score_resp = self.score_reusability(score_req)

        # Extract top behaviors based on reusability scores
        top_patterns = sorted(
            zip(detect_resp.patterns, score_resp.scores),
            key=lambda x: x[1].overall_score,
            reverse=True,
        )[:max_behaviors]

        # Generate improvement suggestions using BCI
        improvement_query = f"""Analyze this failed run and provide specific improvement suggestions.

Run ID: {run_id}
Status: {run.get('status', 'unknown')}

Detected Patterns:
{chr(10).join(f"- {p.description}" for p, _ in top_patterns)}

Provide:
1. Root cause analysis
2. Specific code changes needed
3. Preventive measures for future runs
"""

        # Use detected patterns as behavior hints
        behavior_hints = [f"pattern_{i}" for i, (_, _) in enumerate(top_patterns)]

        generate_result = self.generate_response(
            query=improvement_query,
            behaviors=behavior_hints,
            llm_config=llm_config,
            role_focus=RoleFocus.STRATEGIST,  # Strategist for root cause analysis
        )

        latency_ms = (perf_counter() - start) * 1000.0

        # Emit telemetry
        telemetry_payload = {
            "run_id": run_id,
            "patterns_detected": len(detect_resp.patterns),
            "behaviors_extracted": len(behavior_hints),
            "latency_ms": latency_ms,
        }
        self._telemetry.emit_event(event_type="bci.improve_run", payload=telemetry_payload)

        return {
            "run_id": run_id,
            "patterns": [
                {"description": p.description, "frequency": p.frequency, "score": s.overall_score}
                for p, s in top_patterns
            ],
            "suggestions": generate_result["response"].content,
            "behaviors_extracted": behavior_hints,
            "latency_ms": latency_ms,
        }


__all__ = ["BCIService"]
