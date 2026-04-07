"""Runtime context contract for domain-expertise injection.

Defines the ContextEnvelope (``RuntimeContext``) that carries workspace profile,
active knowledge pack, role, surface, task signals, and resolved overlays
through the BCI pipeline.  See architecture doc §6.4.

Part of E3 — Runtime Injection + BCI Integration (AMPREALIZE-277).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from amprealize.bci_contracts import SerializableDataclass


# ---------------------------------------------------------------------------
# Resolver Input
# ---------------------------------------------------------------------------


@dataclass
class ContextResolverInput(SerializableDataclass):
    """Input fed into :class:`ContextResolver` to produce a :class:`RuntimeContext`.

    Callers populate whichever fields are available — all are optional so that
    each surface (CLI, MCP, VS Code) can contribute what it knows.
    """

    surface: str = "cli"
    task_description: Optional[str] = None
    role: Optional[str] = None
    workspace_path: Optional[str] = None
    org_id: Optional[str] = None
    project_id: Optional[str] = None
    user_id: Optional[str] = None
    active_pack_id: Optional[str] = None
    active_pack_version: Optional[str] = None
    editor_context: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# RuntimeContext (the "Context Envelope")
# ---------------------------------------------------------------------------


@dataclass
class RuntimeContext(SerializableDataclass):
    """Normalized runtime context resolved by :class:`ContextResolver`.

    This is the single object that flows through the entire runtime injection
    pipeline:  Context Resolver → Behavior Retriever → BCI Composer → Surface
    Adapter → Citation Validator → Telemetry.

    All fields are optional so the system degrades gracefully when signals are
    unavailable (e.g. no workspace path in an MCP call).
    """

    # Workspace / tenant
    workspace_profile: Optional[str] = None
    org_id: Optional[str] = None
    project_id: Optional[str] = None
    user_id: Optional[str] = None

    # Knowledge pack
    active_pack_id: Optional[str] = None
    active_pack_version: Optional[str] = None

    # Task / role / surface
    role: Optional[str] = None
    surface: str = "cli"
    task_description: Optional[str] = None
    task_type: Optional[str] = None  # TaskFamily value

    # Resolved guidance
    recommended_behaviors: List[str] = field(default_factory=list)
    recommended_overlays: List[str] = field(default_factory=list)
    overlay_instructions: List[str] = field(default_factory=list)
    runtime_constraints: List[str] = field(default_factory=list)
    primer_text: Optional[str] = None

    # Pack enforcement flags (copied from PackConstraints if active)
    strict_role_declaration: bool = False
    strict_behavior_citation: bool = False
    mandatory_overlays: List[str] = field(default_factory=list)

    # Extensible metadata
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# RuntimeInjectionResult
# ---------------------------------------------------------------------------


@dataclass
class RuntimeInjectionResult(SerializableDataclass):
    """Output of :meth:`RuntimeInjector.inject`.

    Carries the resolved context, retrieved behaviors, the fully composed
    prompt block, and metadata for downstream citation validation.
    """

    context: Optional[RuntimeContext] = None
    composed_prompt: str = ""
    behaviors_injected: List[Dict[str, Any]] = field(default_factory=list)
    overlays_included: List[str] = field(default_factory=list)
    token_estimate: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


__all__ = [
    "ContextResolverInput",
    "RuntimeContext",
    "RuntimeInjectionResult",
]
