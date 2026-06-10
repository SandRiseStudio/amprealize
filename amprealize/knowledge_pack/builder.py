"""Pack Builder — runtime primer generation and overlay assembly.

Implements T1.3.1 (AMPREALIZE-301) of the Knowledge Pack Foundations epic.
Primer format follows architecture doc §6.6 (BCI Prompt Composer).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Union

from amprealize.knowledge_pack.extractor import (
    BehaviorFragment,
    DoctrineFragment,
    ExtractionResult,
    PlaybookFragment,
    SourceExtractor,
)
from amprealize.knowledge_pack.schema import (
    KnowledgePackManifest,
    OverlayFragment,
    OverlayKind,
    PackConstraints,
    PackScope,
    PackSource,
    PackSourceType,
    SourceScope,
)
from amprealize.knowledge_pack.source_registry import SourceRegistryService

logger = logging.getLogger(__name__)

# Type alias for any fragment
Fragment = Union[DoctrineFragment, BehaviorFragment, PlaybookFragment]

# ---------------------------------------------------------------------------
# Build config & artifact dataclasses
# ---------------------------------------------------------------------------


@dataclass
class PackBuildConfig:
    """Configuration for a single pack build invocation."""

    pack_id: str
    version: str
    workspace_profiles: List[str] = field(default_factory=list)
    target_surfaces: List[str] = field(default_factory=list)
    source_filter: Optional[List[str]] = None  # None = include all sources
    created_by: Optional[str] = None


@dataclass
class KnowledgePackArtifact:
    """Output of a successful pack build."""

    manifest: KnowledgePackManifest
    primer_text: str
    overlays: List[OverlayFragment]
    retrieval_metadata: Dict[str, Any]
    build_log: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "manifest": self.manifest.to_dict(),
            "primer_text": self.primer_text,
            "overlays": [o.model_dump(mode="json") for o in self.overlays],
            "retrieval_metadata": self.retrieval_metadata,
            "build_log": self.build_log,
        }


# ---------------------------------------------------------------------------
# Primer token budget
# ---------------------------------------------------------------------------

# Default max characters for the primer block.  The architecture calls for
# "compact, token-budget-aware" output; 2000 chars ≈ ~500 tokens.
_DEFAULT_PRIMER_CHAR_BUDGET = 2000

# ---------------------------------------------------------------------------
# PackBuilder
# ---------------------------------------------------------------------------


class PackBuilder:
    """Builds a Knowledge Pack artifact from registered sources.

    Orchestrates source extraction, primer generation, overlay assembly,
    and retrieval-metadata production.
    """

    def __init__(
        self,
        registry: SourceRegistryService,
        extractor: SourceExtractor,
        *,
        primer_char_budget: int = _DEFAULT_PRIMER_CHAR_BUDGET,
        quality_gate: Optional[Any] = None,
    ) -> None:
        self._registry = registry
        self._extractor = extractor
        self._primer_char_budget = primer_char_budget
        self._quality_gate = quality_gate

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self, config: PackBuildConfig) -> KnowledgePackArtifact:
        """Run the full build pipeline and return a pack artifact."""
        build_log: List[str] = []
        started = datetime.now(timezone.utc)
        build_log.append(f"Build started at {started.isoformat()}")

        # 1. Fetch registered sources --------------------------------
        sources = self._registry.list_sources()
        if config.source_filter is not None:
            allowed = set(config.source_filter)
            sources = [s for s in sources if s.ref in allowed]
        build_log.append(f"Sources resolved: {len(sources)}")

        # 2. Extract fragments ----------------------------------------
        extraction = self._extractor.extract_all(sources)
        build_log.append(
            f"Fragments extracted: {extraction.total_fragments} "
            f"(doctrine={len(extraction.doctrine_fragments)}, "
            f"behaviors={len(extraction.behavior_fragments)}, "
            f"playbooks={len(extraction.playbook_fragments)})"
        )
        if extraction.errors:
            for err in extraction.errors:
                build_log.append(f"Extraction warning: {err}")

        # 3. Generate primer text -------------------------------------
        profile = config.workspace_profiles[0] if config.workspace_profiles else ""
        primer_text = self._generate_primer(
            extraction.doctrine_fragments,
            extraction.behavior_fragments,
            extraction.playbook_fragments,
            profile=profile,
        )
        build_log.append(f"Primer generated: {len(primer_text)} chars")

        # 4. Assemble manifest ----------------------------------------
        now = datetime.now(timezone.utc)
        pack_sources = [
            PackSource(
                type=PackSourceType(s.source_type),
                ref=s.ref,
                scope=SourceScope(s.scope),
                version_hash=s.version_hash,
            )
            for s in sources
        ]

        manifest = KnowledgePackManifest(
            pack_id=config.pack_id,
            version=config.version,
            scope=PackScope.WORKSPACE,
            workspace_profiles=config.workspace_profiles,
            surfaces=config.target_surfaces,
            sources=pack_sources,
            doctrine_fragments=[
                f.fragment_id for f in extraction.doctrine_fragments
            ],
            behavior_refs=[
                f.behavior_name for f in extraction.behavior_fragments
            ],
            task_overlays=[],
            surface_overlays=[],
            constraints=PackConstraints(),
            created_at=now,
            updated_at=now,
            created_by=config.created_by,
        )

        # 5. Assemble overlays ----------------------------------------
        overlays = self._assemble_overlays(extraction, manifest)
        # Back-fill overlay IDs into manifest
        task_ids = [o.overlay_id for o in overlays if o.kind == OverlayKind.TASK]
        surface_ids = [
            o.overlay_id for o in overlays if o.kind == OverlayKind.SURFACE
        ]
        manifest.task_overlays = task_ids
        manifest.surface_overlays = surface_ids
        build_log.append(f"Overlays assembled: {len(overlays)}")

        # 6. Retrieval metadata ---------------------------------------
        retrieval_metadata = self._generate_retrieval_metadata(overlays)
        build_log.append(f"Retrieval entries: {len(retrieval_metadata.get('entries', []))}")

        finished = datetime.now(timezone.utc)
        build_log.append(f"Build finished at {finished.isoformat()}")

        return KnowledgePackArtifact(
            manifest=manifest,
            primer_text=primer_text,
            overlays=overlays,
            retrieval_metadata=retrieval_metadata,
            build_log=build_log,
        )

    def validate_build(
        self,
        artifact: KnowledgePackArtifact,
        strategy_result: Any,
        anchors_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Post-build quality gate — validate a pack artifact against thresholds.

        Args:
            artifact: The built pack artifact.
            strategy_result: StrategyComparisonResult from evaluation.
            anchors_path: Optional path to regression_anchors.json.

        Returns:
            Dict with 'passed' and 'gate_result' keys.
        """
        if self._quality_gate is None:
            return {"passed": True, "gate_result": None, "skipped": True}

        gate_result = self._quality_gate.check_pack_validation(
            strategy_result, anchors_path=anchors_path
        )
        return {
            "passed": gate_result.passed,
            "gate_result": gate_result.to_dict(),
            "skipped": False,
        }

    # ------------------------------------------------------------------
    # Primer generation — architecture §6.6
    # ------------------------------------------------------------------

    def _generate_primer(
        self,
        doctrine_fragments: List[DoctrineFragment],
        behavior_fragments: List[BehaviorFragment],
        playbook_fragments: List[PlaybookFragment],
        *,
        profile: str = "",
    ) -> str:
        """Build a compact runtime primer following the §6.6 format.

        Structure:
            Amprealize runtime context:
            - Workspace profile: <profile>
            - Active pack: <pack_id>@<version>

            Relevant behaviors:
            - <name>: <description>

            Relevant operational guidance:
            - <guidance line>

        The output is capped at ``self._primer_char_budget`` characters,
        preferring the highest-signal fragments first.
        """
        lines: List[str] = []

        # Header block
        lines.append("Amprealize runtime context:")
        if profile:
            lines.append(f"- Workspace profile: {profile}")
        lines.append("")

        # Behavior lines — sorted by name for determinism
        if behavior_fragments:
            lines.append("Relevant behaviors:")
            sorted_behaviors = sorted(
                behavior_fragments, key=lambda b: b.behavior_name
            )
            for bf in sorted_behaviors:
                summary = bf.description or bf.instruction
                # Truncate individual line to keep primer compact
                if len(summary) > 120:
                    summary = summary[:117] + "..."
                lines.append(f"- {bf.behavior_name}: {summary}")
            lines.append("")

        # Operational guidance from doctrine + playbook fragments
        guidance_lines: List[str] = []
        for df in doctrine_fragments:
            first_line = df.content.strip().split("\n")[0].strip()
            if first_line and len(first_line) > 10:
                if len(first_line) > 120:
                    first_line = first_line[:117] + "..."
                guidance_lines.append(f"- {first_line}")
        for pf in playbook_fragments:
            first_line = pf.content.strip().split("\n")[0].strip()
            if first_line and len(first_line) > 10:
                if len(first_line) > 120:
                    first_line = first_line[:117] + "..."
                guidance_lines.append(f"- {first_line}")

        if guidance_lines:
            lines.append("Relevant operational guidance:")
            lines.extend(guidance_lines)
            lines.append("")

        lines.append(
            "Please apply the relevant Amprealize guidance explicitly when it matters."
        )

        primer = "\n".join(lines)

        # Enforce budget — truncate at last complete line within budget
        if len(primer) > self._primer_char_budget:
            primer = self._truncate_to_budget(primer, self._primer_char_budget)

        return primer

    @staticmethod
    def _truncate_to_budget(text: str, budget: int) -> str:
        """Truncate *text* at the last newline within *budget* chars."""
        if len(text) <= budget:
            return text
        cut = text[:budget]
        last_nl = cut.rfind("\n")
        if last_nl > 0:
            return cut[:last_nl]
        return cut[:budget]

    # ------------------------------------------------------------------
    # Overlay assembly
    # ------------------------------------------------------------------

    def _assemble_overlays(
        self,
        extraction: ExtractionResult,
        manifest: KnowledgePackManifest,
    ) -> List[OverlayFragment]:
        """Segment extracted fragments into typed overlays.

        Creates three categories:
        - **role** overlays — one per distinct role found across fragments
        - **surface** overlays — one per target surface in the manifest
        - **task** overlays — a default "general" task overlay if any
          operational guidance exists
        """
        overlays: List[OverlayFragment] = []

        # --- Role overlays ---
        role_to_behaviors: Dict[str, List[BehaviorFragment]] = {}
        for bf in extraction.behavior_fragments:
            role = bf.role_focus.lower() if bf.role_focus else "engineer"
            role_to_behaviors.setdefault(role, []).append(bf)

        for role, bfs in sorted(role_to_behaviors.items()):
            overlay_id = f"role-{role}"
            instructions = [
                f"Follow {bf.behavior_name}: {bf.instruction[:100]}"
                for bf in bfs
            ]
            keywords = _collect_keywords(bfs)
            overlays.append(
                OverlayFragment(
                    overlay_id=overlay_id,
                    kind=OverlayKind.ROLE,
                    applies_to={"role": role},
                    instructions=instructions,
                    retrieval_keywords=keywords,
                )
            )

        # --- Surface overlays ---
        for surface in manifest.surfaces:
            overlay_id = f"surface-{surface}"
            # Gather fragments that mention this surface
            instructions: List[str] = []
            for df in extraction.doctrine_fragments:
                if surface in df.surface_applicability:
                    first = df.content.strip().split("\n")[0][:100]
                    instructions.append(first)
            for pf in extraction.playbook_fragments:
                if surface in pf.surface_applicability:
                    first = pf.content.strip().split("\n")[0][:100]
                    instructions.append(first)
            if instructions:
                overlays.append(
                    OverlayFragment(
                        overlay_id=overlay_id,
                        kind=OverlayKind.SURFACE,
                        applies_to={"surface": surface},
                        instructions=instructions,
                        retrieval_keywords=[surface],
                    )
                )

        # --- Task overlay (general operational guidance) ---
        task_instructions: List[str] = []
        for df in extraction.doctrine_fragments:
            if df.scope == "operational":
                first = df.content.strip().split("\n")[0][:100]
                task_instructions.append(first)
        for pf in extraction.playbook_fragments:
            first = pf.content.strip().split("\n")[0][:100]
            task_instructions.append(first)

        if task_instructions:
            overlays.append(
                OverlayFragment(
                    overlay_id="task-general",
                    kind=OverlayKind.TASK,
                    applies_to={"task_family": "general"},
                    instructions=task_instructions,
                    retrieval_keywords=["operational", "guidance", "general"],
                )
            )

        return overlays

    # ------------------------------------------------------------------
    # Retrieval metadata
    # ------------------------------------------------------------------

    def _generate_retrieval_metadata(
        self,
        overlays: List[OverlayFragment],
    ) -> Dict[str, Any]:
        """Produce keyword + embedding-ready text for each overlay.

        Returns a dict with:
            entries: [{overlay_id, kind, keywords, embedding_text}]
        """
        entries: List[Dict[str, Any]] = []
        for o in overlays:
            embedding_text = " ".join(o.instructions[:5])  # top 5 instructions
            entries.append(
                {
                    "overlay_id": o.overlay_id,
                    "kind": o.kind.value,
                    "keywords": o.retrieval_keywords,
                    "embedding_text": embedding_text,
                }
            )
        return {"entries": entries}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_keywords(
    fragments: List[BehaviorFragment], *, limit: int = 15
) -> List[str]:
    """Merge trigger keywords from a list of behavior fragments."""
    seen: Set[str] = set()
    result: List[str] = []
    for bf in fragments:
        for kw in bf.trigger_keywords:
            lkw = kw.lower()
            if lkw not in seen:
                seen.add(lkw)
                result.append(lkw)
                if len(result) >= limit:
                    return result
    return result
