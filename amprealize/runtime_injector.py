"""RuntimeInjector — orchestrates context resolution, retrieval, and prompt composition.

This is the main entry point for behavior-conditioned prompt generation with full
runtime context awareness. Surface adapters (CLI/MCP/VS Code) invoke the injector
rather than the lower-level BCI components directly.

Part of E3 — Runtime Injection + BCI Integration (AMPREALIZE-277 / S3.3).
Architecture reference: §6.5.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from amprealize.bci_contracts import (
    BehaviorSnippet,
    CitationMode,
    ComposePromptRequest,
    PromptFormat,
    RetrievalStrategy,
    RetrieveRequest,
    RoleFocus,
)
from amprealize.runtime_context import (
    ContextResolverInput,
    RuntimeContext,
    RuntimeInjectionResult,
)

if TYPE_CHECKING:
    from amprealize.bci_service import BCIService
    from amprealize.behavior_retriever import BehaviorRetriever
    from amprealize.context_resolver import ContextResolver

logger = logging.getLogger(__name__)


class RuntimeInjector:
    """Orchestrate context resolution, behavior retrieval, and prompt composition.

    Provides a single ``inject()`` method that surface adapters call with task
    parameters.  Under the hood it:

    1. Resolves a :class:`RuntimeContext` via ContextResolver
    2. Retrieves behaviors with pack/profile/surface signals
    3. Composes an enriched prompt including overlays, primer text, and constraints
    4. Returns a :class:`RuntimeInjectionResult` containing all computed artifacts

    Parameters
    ----------
    context_resolver:
        Resolves runtime context from workspace, pack, surface signals.
    behavior_retriever:
        Retrieves candidate behaviors using semantic/keyword/hybrid search.
    bci_service:
        Composes the final prompt from behaviors + context.
    telemetry:
        Optional telemetry client for metrics emission.
    default_top_k:
        Number of behaviors to retrieve when not specified (default 5).
    default_format:
        Prompt format when not specified (default LIST).
    default_citation_mode:
        Citation mode when not specified (default EXPLICIT).
    """

    def __init__(
        self,
        *,
        context_resolver: Optional["ContextResolver"] = None,
        behavior_retriever: Optional["BehaviorRetriever"] = None,
        bci_service: Optional["BCIService"] = None,
        telemetry: Any = None,
        default_top_k: int = 5,
        default_format: PromptFormat = PromptFormat.LIST,
        default_citation_mode: CitationMode = CitationMode.EXPLICIT,
    ) -> None:
        self._context_resolver = context_resolver
        self._retriever = behavior_retriever
        self._bci = bci_service
        self._telemetry = telemetry
        self._default_top_k = default_top_k
        self._default_format = default_format
        self._default_citation_mode = default_citation_mode

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def inject(
        self,
        *,
        task_description: str,
        surface: str,
        role: Optional[str] = None,
        workspace_path: Optional[str] = None,
        org_id: Optional[str] = None,
        project_id: Optional[str] = None,
        user_id: Optional[str] = None,
        active_pack_id: Optional[str] = None,
        active_pack_version: Optional[str] = None,
        editor_context: Optional[Dict[str, Any]] = None,
        top_k: Optional[int] = None,
        strategy: RetrievalStrategy = RetrievalStrategy.HYBRID,
        prompt_format: Optional[PromptFormat] = None,
        citation_mode: Optional[CitationMode] = None,
        tags: Optional[List[str]] = None,
        phase: Optional[str] = None,
    ) -> RuntimeInjectionResult:
        """Perform full runtime injection for a task.

        This is the primary interface exposed through MCP ``bci.inject`` tool
        and CLI ``amprealize bci inject`` command.

        Parameters
        ----------
        task_description:
            The user's task or prompt text.
        surface:
            Invoking surface: "vscode", "cli", "mcp", "web", "api".
        role:
            Agent role: "Student", "Teacher", "Strategist", or None.
        workspace_path:
            Local path to workspace root for profile detection.
        org_id / project_id / user_id:
            Multi-tenancy identifiers (optional, from session).
        active_pack_id / active_pack_version:
            Explicit pack override (optional).
        editor_context:
            Rich context from editor (file path, language, selection).
        top_k:
            Number of behaviors to retrieve (default 5).
        strategy:
            Retrieval strategy (default HYBRID).
        prompt_format:
            Prompt rendering format (default LIST).
        citation_mode:
            Citation instruction mode (default EXPLICIT).
        tags:
            Filter to behaviors with matching tags.

        Returns
        -------
        RuntimeInjectionResult:
            Contains: context, composed_prompt, behaviors_injected, overlays_included, token_estimate.
        """
        t0 = time.monotonic()

        top_k = top_k or self._default_top_k
        prompt_format = prompt_format or self._default_format
        citation_mode = citation_mode or self._default_citation_mode

        # Step 1: Resolve runtime context
        ctx = self._resolve_context(
            task_description=task_description,
            surface=surface,
            role=role,
            workspace_path=workspace_path,
            org_id=org_id,
            project_id=project_id,
            user_id=user_id,
            active_pack_id=active_pack_id,
            active_pack_version=active_pack_version,
            editor_context=editor_context,
        )

        # Step 2: Retrieve behaviors with context signals
        behaviors = self._retrieve_behaviors(
            task_description=task_description,
            context=ctx,
            top_k=top_k,
            strategy=strategy,
            tags=tags,
            user_id=user_id,
            phase=phase,
        )

        # Step 3: Compose enriched prompt
        composed, overlays = self._compose_prompt(
            task_description=task_description,
            behaviors=behaviors,
            context=ctx,
            prompt_format=prompt_format,
            citation_mode=citation_mode,
        )

        elapsed_ms = (time.monotonic() - t0) * 1000
        token_estimate = len(composed) // 4  # rough ~4 chars per token

        result = RuntimeInjectionResult(
            context=ctx,
            composed_prompt=composed,
            behaviors_injected=[b.name for b in behaviors],
            overlays_included=overlays,
            token_estimate=token_estimate,
            metadata={"latency_ms": round(elapsed_ms, 1), "phase": phase},
        )

        # Emit telemetry
        self._emit_telemetry(result, elapsed_ms)

        return result

    # ------------------------------------------------------------------
    # Internal orchestration steps
    # ------------------------------------------------------------------

    def _resolve_context(
        self,
        *,
        task_description: str,
        surface: str,
        role: Optional[str],
        workspace_path: Optional[str],
        org_id: Optional[str],
        project_id: Optional[str],
        user_id: Optional[str],
        active_pack_id: Optional[str],
        active_pack_version: Optional[str],
        editor_context: Optional[Dict[str, Any]],
    ) -> RuntimeContext:
        """Resolve context via ContextResolver or build a minimal one."""
        inp = ContextResolverInput(
            task_description=task_description,
            role=role,
            surface=surface,
            workspace_path=workspace_path,
            org_id=org_id,
            project_id=project_id,
            user_id=user_id,
            active_pack_id=active_pack_id,
            active_pack_version=active_pack_version,
            editor_context=editor_context,
        )

        if self._context_resolver:
            return self._context_resolver.resolve(inp)

        # Fallback: minimal context (no resolver available)
        return RuntimeContext(
            org_id=org_id,
            project_id=project_id,
            user_id=user_id,
            active_pack_id=active_pack_id,
            active_pack_version=active_pack_version,
            role=role,
            surface=surface,
            task_description=task_description,
        )

    def _retrieve_behaviors(
        self,
        *,
        task_description: str,
        context: RuntimeContext,
        top_k: int,
        strategy: RetrievalStrategy,
        tags: Optional[List[str]],
        user_id: Optional[str],
        phase: Optional[str] = None,
    ) -> List[BehaviorSnippet]:
        """Retrieve behaviors with pack/profile/surface signals."""
        if not self._retriever:
            logger.warning("No BehaviorRetriever configured; returning empty list")
            return []

        role_focus: Optional[RoleFocus] = None
        if context.role:
            try:
                role_focus = RoleFocus(context.role.upper())
            except ValueError:
                pass

        request = RetrieveRequest(
            query=task_description,
            top_k=top_k,
            strategy=strategy,
            role_focus=role_focus,
            tags=tags,
            user_id=user_id,
            # E3 context signals
            workspace_profile=context.workspace_profile,
            active_pack_id=context.active_pack_id,
            surface=context.surface,
            task_type=context.task_type,
            pack_behavior_refs=context.recommended_behaviors,
            runtime_constraints=context.runtime_constraints,
            # E3 S3.9: phase-aware retrieval
            phase=phase,
        )

        matches = self._retriever.retrieve(request)

        # Convert BehaviorMatch → BehaviorSnippet
        snippets: List[BehaviorSnippet] = []
        for m in matches:
            snippets.append(
                BehaviorSnippet(
                    behavior_id=m.behavior_id,
                    name=m.name,
                    instruction=m.instruction,
                    version=m.version,
                    role_focus=m.role_focus,
                    citation_label=m.citation_label or m.name,
                    summary=m.description,
                )
            )
        return snippets

    def _compose_prompt(
        self,
        *,
        task_description: str,
        behaviors: List[BehaviorSnippet],
        context: RuntimeContext,
        prompt_format: PromptFormat,
        citation_mode: CitationMode,
    ) -> tuple[str, List[str]]:
        """Compose enriched prompt using BCIService."""
        if not self._bci:
            # Fallback: simple behaviors-only prompt
            lines = ["Relevant behaviors from the handbook:"]
            for b in behaviors:
                lines.append(f"- {b.citation_label or b.name}: {b.instruction}")
            lines.append("")
            lines.append(task_description)
            return "\n".join(lines), []

        request = ComposePromptRequest(
            query=task_description,
            behaviors=behaviors,
            citation_mode=citation_mode,
            format=prompt_format,
            runtime_context=asdict(context) if context else None,
            overlay_instructions=context.overlay_instructions if context else None,
            primer_text=context.primer_text if context else None,
            runtime_constraints=context.runtime_constraints if context else None,
        )

        response = self._bci.compose_prompt(request)
        return response.prompt, response.overlays_included

    # ------------------------------------------------------------------
    # Telemetry
    # ------------------------------------------------------------------

    def _emit_telemetry(self, result: RuntimeInjectionResult, latency_ms: float) -> None:
        """Emit bci.injection_completed telemetry event."""
        if not self._telemetry:
            return
        try:
            from amprealize.telemetry_events import BCIInjectionCompletedPayload, TelemetryEventType

            payload = BCIInjectionCompletedPayload(
                behaviors_count=len(result.behaviors_injected),
                token_estimate=result.token_estimate,
                latency_ms=round(latency_ms, 1),
                pack_id=result.context.active_pack_id,
                overlays_count=len(result.overlays_included),
                surface=result.context.surface,
                phase=result.metadata.get("phase"),
            )
            self._telemetry.emit_event(
                event_type=TelemetryEventType.BCI_INJECTION_COMPLETED.value,
                payload=payload.to_dict(),
            )
        except Exception:
            logger.debug("Failed to emit bci.injection_completed telemetry", exc_info=True)
