"""MCP tool handlers for BCIService (Behavior-Conditioned Inference)."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from ...bci_service import BCIService
from ...bci_contracts import (
    BatchComposeItem,
    BatchComposePromptRequest,
    BehaviorSnippet,
    CitationMode,
    ComposePromptRequest,
    ComputeTokenSavingsRequest,
    DetectPatternsRequest,
    ParseCitationsRequest,
    PatternCandidate,
    PrependedBehavior,
    PromptFormat,
    RetrieveRequest,
    RetrievalStrategy,
    RoleFocus,
    ScoreDimension,
    ScoreDimensionName,
    ScoreReusabilityRequest,
    SegmentTraceRequest,
    TraceFormat,
    TraceInput,
    ValidateCitationsRequest,
)
from ...llm import LLMConfig, ProviderType


def _parse_retrieval_strategy(value: Optional[str], *, default: RetrievalStrategy = RetrievalStrategy.HYBRID) -> RetrievalStrategy:
    if value is None:
        return default
    normalized = value.strip().lower()
    alias_map = {
        "semantic": RetrievalStrategy.EMBEDDING,
        "embedding": RetrievalStrategy.EMBEDDING,
        "keyword": RetrievalStrategy.KEYWORD,
        "hybrid": RetrievalStrategy.HYBRID,
    }
    if normalized in alias_map:
        return alias_map[normalized]
    try:
        return RetrievalStrategy(normalized)
    except ValueError:
        return default


def _parse_role_focus(value: Optional[str]) -> Optional[RoleFocus]:
    if value is None:
        return None
    normalized = value.strip().upper()
    try:
        return RoleFocus(normalized)
    except ValueError:
        return None


def _parse_prompt_format(value: Optional[str]) -> PromptFormat:
    if value is None:
        return PromptFormat.LIST
    normalized = value.strip().lower()
    alias_map = {
        "markdown": PromptFormat.LIST,
        "list": PromptFormat.LIST,
        "plain": PromptFormat.PROSE,
        "text": PromptFormat.PROSE,
        "prose": PromptFormat.PROSE,
        "json": PromptFormat.STRUCTURED,
        "structured": PromptFormat.STRUCTURED,
    }
    return alias_map.get(normalized, PromptFormat.LIST)


def _parse_citation_mode(value: Optional[str]) -> CitationMode:
    if value is None:
        return CitationMode.EXPLICIT
    normalized = value.strip().lower()
    alias_map = {
        "explicit": CitationMode.EXPLICIT,
        "implicit": CitationMode.IMPLICIT,
        "inline": CitationMode.INLINE,
    }
    return alias_map.get(normalized, CitationMode.EXPLICIT)


def _parse_trace_format(value: Optional[str]) -> TraceFormat:
    if value is None:
        return TraceFormat.CHAIN_OF_THOUGHT
    normalized = value.strip().lower()
    alias_map = {
        "text": TraceFormat.CHAIN_OF_THOUGHT,
        "chain_of_thought": TraceFormat.CHAIN_OF_THOUGHT,
        "json": TraceFormat.JSON_STEPS,
        "json_steps": TraceFormat.JSON_STEPS,
        "structured_json": TraceFormat.JSON_STEPS,
        "structured_log": TraceFormat.JSON_STEPS,
        "markdown": TraceFormat.PLAN_MARKDOWN,
        "plan": TraceFormat.PLAN_MARKDOWN,
        "plan_markdown": TraceFormat.PLAN_MARKDOWN,
    }
    if normalized in alias_map:
        return alias_map[normalized]
    try:
        return TraceFormat(normalized)
    except ValueError:
        return TraceFormat.CHAIN_OF_THOUGHT


def _build_retrieve_request(
    arguments: Dict[str, Any],
    *,
    strategy_override: Optional[RetrievalStrategy] = None,
) -> RetrieveRequest:
    query = arguments["task"]
    strategy = strategy_override or _parse_retrieval_strategy(arguments.get("strategy"))
    return RetrieveRequest(
        query=query,
        top_k=arguments.get("top_k", 5),
        strategy=strategy,
        role_focus=_parse_role_focus(arguments.get("role_focus")),
        tags=arguments.get("tags"),
        include_metadata=arguments.get("include_metadata", False),
        trace_context=arguments.get("trace_context"),
        user_id=arguments.get("user_id"),
    )


def _convert_behavior_snippets(raw_behaviors: Optional[Iterable[Any]]) -> List[BehaviorSnippet]:
    if not raw_behaviors:
        return []
    snippets: List[BehaviorSnippet] = []
    for item in raw_behaviors:
        if isinstance(item, str):
            snippets.append(
                BehaviorSnippet(
                    behavior_id=item,
                    name=item,
                    instruction="",
                )
            )
            continue
        if isinstance(item, dict):
            snippets.append(
                BehaviorSnippet(
                    behavior_id=item.get("behavior_id")
                    or item.get("id")
                    or item.get("name")
                    or "behavior_placeholder",
                    name=item.get("name") or item.get("behavior_name") or (item.get("behavior_id") or "behavior"),
                    instruction=item.get("instruction") or item.get("description") or "",
                    version=item.get("version"),
                    role_focus=_parse_role_focus(item.get("role_focus")),
                    citation_label=item.get("citation_label"),
                    summary=item.get("summary"),
                )
            )
    return snippets


def _resolve_behaviors_for_prompt(service: BCIService, arguments: Dict[str, Any]) -> List[BehaviorSnippet]:
    snippets = _convert_behavior_snippets(arguments.get("behaviors"))
    if snippets:
        return snippets
    try:
        retrieve_request = _build_retrieve_request(arguments)
    except KeyError:
        return []
    response = service.retrieve(retrieve_request)
    resolved: List[BehaviorSnippet] = []
    for match in response.results:
        resolved.append(
            BehaviorSnippet(
                behavior_id=match.behavior_id,
                name=match.name,
                instruction=match.instruction,
                role_focus=match.role_focus,
                version=match.version,
                citation_label=match.citation_label,
                summary=match.description,
            )
        )
    return resolved


def _ensure_behaviors(behaviors: List[BehaviorSnippet], task: str) -> List[BehaviorSnippet]:
    if behaviors:
        return behaviors
    placeholder = BehaviorSnippet(
        behavior_id=f"behavior_{abs(hash(task)) % 10000}",
        name="behavior_task_context",
        instruction=f"Break the task '{task}' into clear, auditable steps.",
    )
    return [placeholder]


def _build_batch_items(
    service: BCIService,
    tasks: List[str],
    base_arguments: Dict[str, Any],
) -> List[BatchComposeItem]:
    items: List[BatchComposeItem] = []
    citation_mode = _parse_citation_mode(base_arguments.get("citation_mode"))
    prompt_format = _parse_prompt_format(base_arguments.get("format"))
    for task in tasks:
        task_arguments = dict(base_arguments)
        task_arguments["task"] = task
        resolved = _resolve_behaviors_for_prompt(service, task_arguments)
        behaviors = _ensure_behaviors(resolved, task)
        items.append(
            BatchComposeItem(
                query=task,
                behaviors=behaviors,
                citation_mode=citation_mode,
                format=prompt_format,
            )
        )
    return items


def _build_trace_inputs(traces: Iterable[Any]) -> List[TraceInput]:
    inputs: List[TraceInput] = []
    for trace in traces:
        if isinstance(trace, str):
            inputs.append(TraceInput(trace_text=trace))
        elif isinstance(trace, dict):
            inputs.append(
                TraceInput(
                    trace_text=trace.get("trace") or trace.get("text") or "",
                    format=_parse_trace_format(trace.get("format")),
                )
            )
    return inputs


def _build_prepended_behaviors(citations: Iterable[str]) -> List[PrependedBehavior]:
    return [PrependedBehavior(behavior_name=name) for name in citations]


def _build_dimension_overrides(dimensions: Optional[Iterable[Dict[str, Any]]]) -> Optional[List[ScoreDimension]]:
    if not dimensions:
        return None
    overrides: List[ScoreDimension] = []
    for entry in dimensions:
        name_value = entry.get("name")
        if name_value is None:
            continue
        try:
            name = ScoreDimensionName(name_value)
        except ValueError:
            continue
        overrides.append(
            ScoreDimension(
                name=name,
                weight=float(entry.get("weight", 0.25)),
                score=float(entry.get("score", 0.5)),
                rationale=entry.get("rationale"),
            )
        )
    return overrides or None


def _serialize_behavior_match(match: Any) -> Dict[str, Any]:
    return {
        "behavior_name": match.name,
        "behavior_id": match.behavior_id,
        "score": match.score,
        "snippet": match.instruction,
        "metadata": match.metadata,
        "role_focus": match.role_focus.value if match.role_focus else None,
        "citation_label": match.citation_label,
        "tags": match.tags,
    }


def bci_retrieve(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Retrieve relevant behaviors for a task via configured strategy."""

    service = BCIService()
    request = _build_retrieve_request(arguments)
    response = service.retrieve(request)
    requested_strategy = arguments.get("strategy")
    strategy_value = requested_strategy or response.strategy_used.value
    return {
        "behaviors": [_serialize_behavior_match(match) for match in response.results],
        "retrieval_time_ms": response.latency_ms or 0.0,
        "strategy": strategy_value,
        "metadata": response.metadata,
    }


def bci_retrieve_hybrid(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Retrieve behaviors using an explicit hybrid strategy."""

    service = BCIService()
    request = _build_retrieve_request(arguments, strategy_override=RetrievalStrategy.HYBRID)
    response = service.retrieve(request)
    return {
        "behaviors": [_serialize_behavior_match(match) for match in response.results],
        "retrieval_time_ms": response.latency_ms or 0.0,
        "strategy": "hybrid",
        "metadata": response.metadata,
    }


def bci_compose_prompt(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Compose a behavior-conditioned prompt for a single task."""

    service = BCIService()
    resolved_behaviors = _resolve_behaviors_for_prompt(service, arguments)
    behaviors = _ensure_behaviors(resolved_behaviors, arguments["task"])
    request = ComposePromptRequest(
        query=arguments["task"],
        behaviors=behaviors,
        citation_mode=_parse_citation_mode(arguments.get("citation_mode")),
        format=_parse_prompt_format(arguments.get("format")),
        citation_instruction=arguments.get("instruction"),
        max_behaviors=arguments.get("top_k"),
    )
    response = service.compose_prompt(request)
    requested_format = arguments.get("format") or request.format.value
    total_input_tokens = len(response.prompt.split()) + sum(len(b.instruction.split()) for b in response.behaviors)
    return {
        "prompt": response.prompt,
        "behaviors_used": [
            {
                "behavior_name": b.name,
                "instruction": b.instruction,
                "behavior_id": b.behavior_id,
            }
            for b in response.behaviors
        ],
        "total_input_tokens": total_input_tokens,
        "format": requested_format,
        "citation_mode": request.citation_mode.value,
    }


def bci_compose_prompts_batch(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Compose prompts for multiple tasks in batch mode."""

    service = BCIService()
    tasks = arguments["tasks"]
    top_k = arguments.get("top_k")
    base_args = dict(arguments)
    items = _build_batch_items(service, tasks, base_args)
    request = BatchComposePromptRequest(items=items)
    response = service.compose_prompts_batch(request)
    results_payload: List[Dict[str, Any]] = []
    total_behaviors = 0
    for item_response in response.items:
        total_behaviors += len(item_response.behaviors)
        total_tokens = len(item_response.prompt.split()) + sum(len(b.instruction.split()) for b in item_response.behaviors)
        results_payload.append(
            {
                "task": item_response.query,
                "prompt": item_response.prompt,
                "behaviors_used": [
                    {
                        "behavior_name": snippet.name,
                        "instruction": snippet.instruction,
                        "behavior_id": snippet.behavior_id,
                    }
                    for snippet in item_response.behaviors
                ],
                "total_input_tokens": total_tokens,
            }
        )
    avg_retrieval_time_ms = 0.0
    if response.items:
        avg_retrieval_time_ms = 25.0  # Stubbed latency estimate pending telemetry hookup
    return {
        "results": results_payload,
        "total_behaviors_retrieved": total_behaviors,
        "avg_retrieval_time_ms": avg_retrieval_time_ms,
        "top_k": top_k,
    }


def bci_parse_citations(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse behavior citations from a model's output text.

    Args:
        output_text (str): The model output to parse
        patterns (list, optional): Regex patterns for citation detection
        mode (str, optional): Citation mode (inline/explicit/auto, default: auto)

    Returns:
        Dict with 'citations' list containing found behavior references
    """
    service = BCIService()
    request = ParseCitationsRequest(
        output_text=arguments["output_text"],
        patterns=arguments.get("patterns"),
    )
    response = service.parse_citations(request)
    unique_behaviors = {
        citation.behavior_name or citation.text
        for citation in response.citations
    }
    return {
        "citations": [
            {
                "behavior_name": citation.behavior_name or citation.text,
                "text": citation.text,
                "type": citation.type.value,
                "start_index": citation.start_index,
                "end_index": citation.end_index,
            }
            for citation in response.citations
        ],
        "total_citations": len(response.citations),
        "unique_behaviors": len(unique_behaviors),
    }


def bci_validate_citations(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate that cited behaviors exist in the handbook.

    Args:
        citations (list): List of behavior names to validate
        output_text (str, optional): Full output text (will parse if citations not provided)

    Returns:
        Dict with validation results including valid/invalid/missing behaviors
    """
    citations = arguments.get("citations", [])
    output_text = arguments.get("output_text")
    if output_text is None:
        output_text = " ".join(f"[{citation}]" for citation in citations)
    prepended = _build_prepended_behaviors(citations)
    service = BCIService()
    request = ValidateCitationsRequest(
        output_text=output_text,
        prepended_behaviors=prepended,
        minimum_citations=arguments.get("minimum_citations", 1),
        allow_unlisted_behaviors=arguments.get("allow_unlisted_behaviors", False),
    )
    response = service.validate_citations(request)
    valid_names = [citation.behavior_name or citation.text for citation in response.valid_citations]
    invalid_names = [citation.behavior_name or citation.text for citation in response.invalid_citations]
    total_checked = len(citations)
    validation_rate = (len(valid_names) / total_checked) if total_checked else 0.0
    return {
        "valid_citations": valid_names,
        "invalid_citations": invalid_names,
        "missing_behaviors": response.missing_behaviors,
        "validation_rate": round(validation_rate * 100.0, 2),
        "total_checked": total_checked,
        "warnings": response.warnings,
    }


def bci_compute_token_savings(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute token savings from using behavior-conditioned inference.

    Args:
        baseline_tokens (int): Token count without behaviors
        bci_tokens (int): Token count with behavior conditioning
        num_tasks (int, optional): Number of tasks analyzed (default: 1)

    Returns:
        Dict with savings percentage, absolute savings, and efficiency metrics
    """
    service = BCIService()
    baseline = int(arguments["baseline_tokens"])
    bci_tokens = int(arguments["bci_tokens"])
    request = ComputeTokenSavingsRequest(
        baseline_tokens=baseline,
        bci_tokens=bci_tokens,
    )
    response = service.compute_token_savings(request)
    absolute_savings = baseline - bci_tokens
    efficiency_ratio = (baseline / max(bci_tokens, 1)) if bci_tokens else 0.0
    return {
        "savings_percentage": round(response.token_savings_pct * 100.0, 2),
        "absolute_savings": response.token_savings,
        "efficiency_ratio": round(efficiency_ratio, 4),
        "baseline_tokens": baseline,
        "bci_tokens": bci_tokens,
    }


def bci_segment_trace(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Segment a reasoning trace into discrete steps for analysis.

    Args:
        trace (str or dict): The trace to segment (text or structured format)
        format (str, optional): Trace format (text/json/markdown, default: text)
        min_step_tokens (int, optional): Minimum tokens per step (default: 10)

    Returns:
        Dict with 'steps' list containing segmented trace steps with metadata
    """
    service = BCIService()
    trace_text = arguments.get("trace") or arguments.get("trace_text")
    if trace_text is None:
        raise KeyError("trace")
    request = SegmentTraceRequest(
        trace_text=trace_text,
        format=_parse_trace_format(arguments.get("format")),
        language=arguments.get("language"),
    )
    response = service.segment_trace(request)
    total_tokens = sum(len(step.text.split()) for step in response.steps)
    total_steps = len(response.steps)
    avg_tokens = (total_tokens / total_steps) if total_steps else 0.0
    return {
        "steps": [
            {
                "step_index": step.index,
                "content": step.text,
                "metadata": step.metadata,
            }
            for step in response.steps
        ],
        "total_steps": total_steps,
        "total_tokens": total_tokens,
        "avg_tokens_per_step": round(avg_tokens, 2),
    }


def bci_detect_patterns(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Detect reusable reasoning patterns in traces for behavior extraction.

    Args:
        traces (list): List of trace texts to analyze
        min_frequency (int, optional): Minimum pattern occurrence (default: 2)
        min_score (float, optional): Minimum reusability score (default: 0.5)

    Returns:
        Dict with 'patterns' list containing detected reusable patterns
    """
    traces_arg = arguments["traces"]
    trace_inputs = _build_trace_inputs(traces_arg)
    service = BCIService()
    request = DetectPatternsRequest(
        traces=trace_inputs,
        min_occurrences=arguments.get("min_frequency", 2),
        window_size=arguments.get("window_size"),
    )
    response = service.detect_patterns(request)
    patterns_payload: List[Dict[str, Any]] = []
    for pattern in response.patterns:
        candidate = pattern.candidate_behavior
        patterns_payload.append(
            {
                "pattern_id": pattern.pattern_id,
                "description": pattern.description,
                "frequency": pattern.occurrence_count,
                "suggested_behavior_name": candidate.name if candidate else None,
                "candidate_behavior": candidate.to_dict() if isinstance(candidate, PatternCandidate) else None,
            }
        )
    return {
        "patterns": patterns_payload,
        "total_patterns": len(response.patterns),
        "total_traces_analyzed": response.total_traces,
        "latency_ms": response.latency_ms,
    }


def bci_score_reusability(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Score a behavior's reusability across multiple dimensions.

    Args:
        behavior_name (str): Name of the behavior to score
        behavior_instruction (str): The behavior's instruction text
        dimensions (list, optional): Score dimensions to evaluate
        example_traces (list, optional): Example traces using the behavior

    Returns:
        Dict with dimension scores, overall score, and recommendations
    """
    service = BCIService()
    candidate = PatternCandidate(
        name=arguments.get("behavior_name"),
        instruction=arguments.get("behavior_instruction"),
        supporting_traces=arguments.get("example_traces", []),
    )
    overrides = _build_dimension_overrides(arguments.get("dimensions"))
    request = ScoreReusabilityRequest(
        candidate_behavior=candidate,
        override_weights=overrides,
    )
    response = service.score_reusability(request)
    overall_score = response.score
    recommendations = []
    if overall_score < 70:
        recommendations.append("Add more supporting traces to boost confidence.")
    if overall_score < 50:
        recommendations.append("Clarify instructions to improve clarity.")
    is_reusable = overall_score >= 60
    return {
        "overall_score": overall_score,
        "dimension_scores": [
            {
                "name": dimension.name.value,
                "score": dimension.score,
                "weight": dimension.weight,
                "rationale": dimension.rationale,
            }
            for dimension in response.dimensions
        ],
        "recommendations": recommendations or ["Keep referencing this behavior for continuous improvement."],
        "is_reusable": is_reusable,
    }


def bci_rebuild_index(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Rebuild the behavior retrieval index from the current handbook.

    Args:
        None

    Returns:
        Dict with rebuild status, indexed behaviors count, and timing
    """
    service = BCIService()
    result = service.rebuild_index()
    return result


def _parse_provider_type(value: Optional[str]) -> ProviderType:
    """Parse provider type from string value, with fallback to environment."""
    if value is None:
        return ProviderType.OPENAI  # Default
    normalized = value.strip().lower()
    alias_map = {
        "openai": ProviderType.OPENAI,
        "anthropic": ProviderType.ANTHROPIC,
        "claude": ProviderType.ANTHROPIC,
        "openrouter": ProviderType.OPENROUTER,
        "ollama": ProviderType.OLLAMA,
        "together": ProviderType.TOGETHER,
        "togetherai": ProviderType.TOGETHER,
        "groq": ProviderType.GROQ,
        "fireworks": ProviderType.FIREWORKS,
        # google, cohere, azure_openai not currently supported as providers
    }
    if normalized in alias_map:
        return alias_map[normalized]
    try:
        return ProviderType(normalized.upper())
    except ValueError:
        return ProviderType.OPENAI


def _build_llm_config(arguments: Dict[str, Any]) -> LLMConfig:
    """Build LLMConfig from MCP tool arguments."""
    provider = _parse_provider_type(arguments.get("provider"))
    model = arguments.get("model")
    temperature = arguments.get("temperature")

    # Build config from environment, then override with explicit args
    config = LLMConfig.from_env()
    config.provider = provider
    if model:
        config.model = model
    if temperature is not None:
        config.temperature = float(temperature)

    return config


def bci_generate(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate a behavior-conditioned response using an LLM.

    Args:
        query (str): The task or question to answer
        behaviors (list, optional): Specific behaviors to use (IDs or names)
        top_k (int, optional): Number of behaviors to retrieve if not specified
        provider (str, optional): LLM provider (openai/anthropic/openrouter/ollama/together/groq/fireworks)
        model (str, optional): Model name
        temperature (float, optional): Sampling temperature
        role_focus (str, optional): Role focus (STUDENT/TEACHER/STRATEGIST)

    Returns:
        Dict with response text, behaviors_used, token_savings, and latency_ms
    """
    service = BCIService()
    llm_config = _build_llm_config(arguments)

    # Parse role focus
    role_focus = _parse_role_focus(arguments.get("role_focus"))

    # Get behaviors - either explicit or retrieve
    behavior_ids = arguments.get("behaviors")
    top_k = arguments.get("top_k", 5)

    # Call BCIService.generate_response
    result = service.generate_response(
        query=arguments["query"],
        llm_config=llm_config,
        behavior_ids=behavior_ids,
        top_k=top_k,
        role_focus=role_focus,
    )

    # Convert dataclass to dict
    return {
        "response": result.response_text,
        "behaviors_used": [
            {
                "behavior_id": b.behavior_id,
                "behavior_name": b.name,
                "instruction": b.instruction,
            }
            for b in result.behaviors_used
        ],
        "token_savings": {
            "baseline_tokens": result.baseline_tokens,
            "bci_tokens": result.bci_tokens,
            "savings_pct": round(result.token_savings_pct, 2),
        },
        "latency_ms": result.latency_ms,
    }


def bci_improve(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyze a failed run and suggest improvements using extracted patterns.

    Args:
        run_id (str): The run ID to analyze
        provider (str, optional): LLM provider for generating suggestions
        model (str, optional): Model name
        max_behaviors (int, optional): Maximum behaviors to extract from patterns

    Returns:
        Dict with patterns detected, improvement suggestions, behaviors_extracted, and latency_ms
    """
    service = BCIService()
    llm_config = _build_llm_config(arguments)

    max_behaviors = arguments.get("max_behaviors", 10)

    # Call BCIService.improve_run
    result = service.improve_run(
        run_id=arguments["run_id"],
        llm_config=llm_config,
        max_behaviors=max_behaviors,
    )

    # Convert dataclass to dict
    return {
        "patterns": [
            {
                "pattern_id": p.pattern_id,
                "description": p.description,
                "frequency": p.occurrence_count,
            }
            for p in result.patterns
        ],
        "suggestions": result.suggestions,
        "behaviors_extracted": [
            {
                "behavior_name": b.name,
                "instruction": b.instruction,
                "reusability_score": b.reusability_score,
            }
            for b in result.behaviors_extracted
        ],
        "latency_ms": result.latency_ms,
    }


def bci_inject(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Full runtime injection: resolve context, retrieve behaviors, and compose enriched prompt.

    E3 Runtime Injection (AMPREALIZE-277 / T3.3.3).

    This is the primary interface for behavior-conditioned prompt generation with
    full runtime context awareness (pack, profile, surface, overlays, primer).

    Args:
        task (str): The task or prompt description
        surface (str, optional): Invoking surface ("vscode", "cli", "mcp", "web", "api")
        role (str, optional): Agent role ("Student", "Teacher", "Strategist")
        workspace_path (str, optional): Local workspace path for profile detection
        org_id (str, optional): Organization ID from session
        project_id (str, optional): Project ID from session
        user_id (str, optional): User ID from session
        active_pack_id (str, optional): Explicit pack override
        active_pack_version (str, optional): Explicit pack version
        editor_context (dict, optional): Rich context from editor (file, lang, selection)
        top_k (int, optional): Number of behaviors to retrieve (default 5)
        strategy (str, optional): Retrieval strategy ("hybrid", "embedding", "keyword")
        format (str, optional): Prompt format ("list", "prose", "structured")
        citation_mode (str, optional): Citation mode ("explicit", "implicit", "inline")
        tags (list, optional): Filter behaviors by tags

    Returns:
        Dict with:
          - composed_prompt: The enriched prompt ready for an LLM
          - behaviors_injected: List of behavior names used
          - overlays_included: List of overlay IDs applied
          - context: The resolved RuntimeContext (workspace_profile, pack, etc.)
          - token_estimate: Rough token count
          - latency_ms: Processing time in ms
    """
    # Lazy import to avoid circular dependencies during module load
    from ...runtime_injector import RuntimeInjector
    from ...telemetry import TelemetryClient, create_sink_from_env

    telemetry = TelemetryClient(
        sink=create_sink_from_env(),
        default_actor={"id": arguments.get("user_id", "system"), "role": "SYSTEM", "surface": arguments.get("surface", "mcp")},
    )

    # TODO: Wire real services from MCPServiceProvider in a future pass.
    # For now, instantiate injector with lazy service creation.
    injector = RuntimeInjector(telemetry=telemetry)

    result = injector.inject(
        task_description=arguments["task"],
        surface=arguments.get("surface", "mcp"),
        role=arguments.get("role"),
        workspace_path=arguments.get("workspace_path"),
        org_id=arguments.get("org_id"),
        project_id=arguments.get("project_id"),
        user_id=arguments.get("user_id"),
        active_pack_id=arguments.get("active_pack_id"),
        active_pack_version=arguments.get("active_pack_version"),
        editor_context=arguments.get("editor_context"),
        top_k=arguments.get("top_k", 5),
        strategy=_parse_retrieval_strategy(arguments.get("strategy")),
        prompt_format=_parse_prompt_format(arguments.get("format")),
        citation_mode=_parse_citation_mode(arguments.get("citation_mode")),
        tags=arguments.get("tags"),
        phase=arguments.get("phase"),
    )

    # Serialize RuntimeContext to dict for JSON response
    context_dict = {
        "workspace_profile": result.context.workspace_profile,
        "active_pack_id": result.context.active_pack_id,
        "active_pack_version": result.context.active_pack_version,
        "role": result.context.role,
        "surface": result.context.surface,
        "task_type": result.context.task_type,
        "org_id": result.context.org_id,
        "project_id": result.context.project_id,
        "user_id": result.context.user_id,
    }

    return {
        "composed_prompt": result.composed_prompt,
        "behaviors_injected": result.behaviors_injected,
        "overlays_included": result.overlays_included,
        "context": context_dict,
        "token_estimate": result.token_estimate,
        "latency_ms": result.metadata.get("latency_ms", 0.0),
    }
