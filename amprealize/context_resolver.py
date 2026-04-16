"""Context Resolver — assembles a :class:`RuntimeContext` from available signals.

Merges workspace profile detection, active knowledge pack lookup, task
classification, overlay selection, and primer resolution into a single
deterministic :class:`RuntimeContext` object.

Part of E3 — Runtime Injection + BCI Integration (AMPREALIZE-277 / S3.1).
Architecture reference: §6.4.
"""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from amprealize.runtime_context import ContextResolverInput, RuntimeContext

if TYPE_CHECKING:
    from amprealize.bootstrap.detector import WorkspaceDetector
    from amprealize.knowledge_pack.activation_service import ActivationService
    from amprealize.knowledge_pack.overlay_rules import OverlayClassifier
    from amprealize.knowledge_pack.storage import KnowledgePackStorage

logger = logging.getLogger(__name__)

# Default TTL for cached contexts (seconds).
_DEFAULT_CACHE_TTL = 300


class ContextResolver:
    """Resolves a :class:`RuntimeContext` from available signals.

    Parameters
    ----------
    workspace_detector:
        Detects workspace profile from filesystem signals.
    activation_service:
        Looks up the active knowledge pack for a workspace.
    overlay_classifier:
        Classifies task family / surface / role from text.
    telemetry:
        Optional telemetry client for emitting ``runtime_context.resolved``.
    cache_ttl:
        Seconds to cache resolved contexts (0 to disable).
    """

    def __init__(
        self,
        *,
        workspace_detector: Optional["WorkspaceDetector"] = None,
        activation_service: Optional["ActivationService"] = None,
        overlay_classifier: Optional["OverlayClassifier"] = None,
        pack_storage: Optional["KnowledgePackStorage"] = None,
        telemetry: Any = None,
        cache_ttl: int = _DEFAULT_CACHE_TTL,
    ) -> None:
        self._detector = workspace_detector
        self._activation = activation_service
        self._classifier = overlay_classifier
        self._pack_storage = pack_storage
        self._telemetry = telemetry
        self._cache_ttl = cache_ttl
        # In-memory TTL cache: key → (RuntimeContext, expiry_ts)
        self._cache: Dict[str, Tuple[RuntimeContext, float]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, inp: ContextResolverInput) -> RuntimeContext:
        """Resolve a :class:`RuntimeContext` from the given input.

        The resolver performs best-effort assembly — any signal that is
        unavailable is simply skipped (all RuntimeContext fields are optional).
        """
        t0 = time.monotonic()

        # Check cache
        cache_key = self._cache_key(inp)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        # 1. Detect workspace profile
        workspace_profile = self._detect_profile(inp.workspace_path)

        # 2. Look up active pack
        pack_id, pack_version, pack_meta = self._resolve_pack(
            inp, workspace_profile
        )

        # 3. Classify task type
        task_type = self._classify_task(inp.task_description)

        # 4. Select overlays from pack
        overlay_ids, overlay_instructions = self._select_overlays(
            pack_meta, task_type, inp.surface
        )

        # 5. Resolve primer text
        primer_text = self._resolve_primer(pack_meta)

        # 6. Extract runtime constraints
        constraints = self._extract_constraints(pack_meta, overlay_instructions)

        # 7. Extract pack enforcement flags
        strict_role, strict_cite, mandatory_overlays = self._enforcement_flags(
            pack_meta
        )

        # 8. Recommended behavior IDs from pack
        recommended_behaviors = self._pack_behavior_refs(pack_meta)

        ctx = RuntimeContext(
            workspace_profile=workspace_profile,
            org_id=inp.org_id,
            project_id=inp.project_id,
            user_id=inp.user_id,
            active_pack_id=pack_id,
            active_pack_version=pack_version,
            role=inp.role,
            surface=inp.surface,
            task_description=inp.task_description,
            task_type=task_type,
            recommended_behaviors=recommended_behaviors,
            recommended_overlays=overlay_ids,
            overlay_instructions=overlay_instructions,
            runtime_constraints=constraints,
            primer_text=primer_text,
            strict_role_declaration=strict_role,
            strict_behavior_citation=strict_cite,
            mandatory_overlays=mandatory_overlays,
        )

        # Cache the resolved context
        self._cache_put(cache_key, ctx)

        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.debug(
            "runtime_context.resolved in %.1fms profile=%s pack=%s task_type=%s",
            elapsed_ms,
            workspace_profile,
            pack_id,
            task_type,
        )
        if self._telemetry:
            try:
                self._telemetry.emit(
                    "runtime_context.resolved",
                    {
                        "workspace_profile": workspace_profile,
                        "active_pack_id": pack_id,
                        "surface": inp.surface,
                        "task_type": task_type,
                        "latency_ms": round(elapsed_ms, 1),
                    },
                )
            except Exception:
                logger.debug("Failed to emit runtime_context.resolved telemetry", exc_info=True)

        return ctx

    def invalidate(self, workspace_path: Optional[str] = None) -> int:
        """Invalidate cached contexts.

        Parameters
        ----------
        workspace_path:
            If given, only invalidate entries matching this workspace.
            If ``None``, flush the entire cache.

        Returns
        -------
        int:
            Number of entries evicted.
        """
        if workspace_path is None:
            count = len(self._cache)
            self._cache.clear()
            return count

        evicted = 0
        prefix = f"ws:{workspace_path}|"
        keys_to_remove = [k for k in self._cache if k.startswith(prefix)]
        for k in keys_to_remove:
            del self._cache[k]
            evicted += 1
        return evicted

    # ------------------------------------------------------------------
    # Internals — each step is isolated for testability
    # ------------------------------------------------------------------

    def _detect_profile(self, workspace_path: Optional[str]) -> Optional[str]:
        """Run workspace detection if a detector and path are available."""
        if not workspace_path or not self._detector:
            return None
        try:
            result = self._detector.detect(Path(workspace_path))
            return result.profile.value
        except Exception:
            logger.debug("Workspace detection failed", exc_info=True)
            return None

    def _resolve_pack(
        self,
        inp: ContextResolverInput,
        workspace_profile: Optional[str],
    ) -> Tuple[Optional[str], Optional[str], Optional[Dict[str, Any]]]:
        """Look up the active knowledge pack.

        Returns ``(pack_id, pack_version, pack_manifest_dict)`` or
        ``(None, None, None)`` when unavailable.
        """
        pack_id = inp.active_pack_id
        pack_version = inp.active_pack_version

        if not pack_id and self._activation and inp.workspace_path:
            try:
                activation = self._activation.get_active_pack(inp.workspace_path)
                if activation:
                    pack_id = activation.pack_id
                    pack_version = activation.pack_version
            except Exception:
                logger.debug("Active pack lookup failed", exc_info=True)

        if not pack_id:
            return None, None, None

        # Load manifest metadata (if activation service can provide it)
        pack_meta = self._load_pack_manifest(pack_id, pack_version)
        return pack_id, pack_version, pack_meta

    def _load_pack_manifest(
        self, pack_id: str, version: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Load pack manifest dict from storage.

        Returns the stored manifest JSON (including ``_primer_text`` under
        the ``primer_text`` key for downstream consumption).  Falls back
        to ``None`` when storage is unavailable or the pack isn't found.
        """
        if not self._pack_storage:
            return None
        try:
            data = self._pack_storage.get_manifest_for_runtime(pack_id, version)
            if data is None:
                return None
            # Promote _primer_text → primer_text for downstream consumers
            if "_primer_text" in data and "primer_text" not in data:
                data["primer_text"] = data["_primer_text"]
            return data
        except Exception:
            logger.debug("Failed to load pack manifest %s", pack_id, exc_info=True)
            return None

    def _classify_task(self, task_description: Optional[str]) -> Optional[str]:
        """Classify the task description into a TaskFamily value."""
        if not task_description or not self._classifier:
            return None
        try:
            family = self._classifier.classify_task(task_description)
            return family.value
        except Exception:
            logger.debug("Task classification failed", exc_info=True)
            return None

    def _select_overlays(
        self,
        pack_meta: Optional[Dict[str, Any]],
        task_type: Optional[str],
        surface: str,
    ) -> Tuple[List[str], List[str]]:
        """Select overlay IDs and instruction text from the pack manifest.

        Returns ``(overlay_ids, overlay_instruction_texts)``.
        """
        if not pack_meta:
            return [], []

        task_overlays = pack_meta.get("task_overlays", [])
        surface_overlays = pack_meta.get("surface_overlays", [])

        # For now, return all overlay IDs — refinement to filter by task_type
        # and surface will be added when pack manifest storage is wired.
        overlay_ids = task_overlays + surface_overlays
        return overlay_ids, []

    def _resolve_primer(
        self, pack_meta: Optional[Dict[str, Any]]
    ) -> Optional[str]:
        """Extract primer text from a pack manifest, if available."""
        if not pack_meta:
            return None
        return pack_meta.get("primer_text")

    def _extract_constraints(
        self,
        pack_meta: Optional[Dict[str, Any]],
        overlay_instructions: List[str],
    ) -> List[str]:
        """Merge runtime constraints from pack + overlay instructions."""
        constraints: List[str] = []
        if pack_meta:
            pack_constraints = pack_meta.get("constraints", {})
            if pack_constraints.get("mandatory_overlays"):
                constraints.append(
                    "Mandatory overlays must be cited: "
                    + ", ".join(pack_constraints["mandatory_overlays"])
                )
        return constraints

    def _enforcement_flags(
        self, pack_meta: Optional[Dict[str, Any]]
    ) -> Tuple[bool, bool, List[str]]:
        """Extract pack enforcement flags (strict modes)."""
        if not pack_meta:
            return False, False, []
        c = pack_meta.get("constraints", {})
        return (
            c.get("strict_role_declaration", False),
            c.get("strict_behavior_citation", False),
            c.get("mandatory_overlays", []),
        )

    def _pack_behavior_refs(
        self, pack_meta: Optional[Dict[str, Any]]
    ) -> List[str]:
        """Return behavior references from the active pack."""
        if not pack_meta:
            return []
        return pack_meta.get("behavior_refs", [])

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _cache_key(self, inp: ContextResolverInput) -> str:
        """Build a deterministic cache key from resolver input."""
        parts = (
            f"ws:{inp.workspace_path or ''}|"
            f"pack:{inp.active_pack_id or ''}|"
            f"surf:{inp.surface}|"
            f"role:{inp.role or ''}|"
            f"task:{(inp.task_description or '')[:200]}"
        )
        return hashlib.sha256(parts.encode()).hexdigest()[:24]

    def _cache_get(self, key: str) -> Optional[RuntimeContext]:
        """Return cached context if present and not expired."""
        if self._cache_ttl <= 0:
            return None
        entry = self._cache.get(key)
        if entry is None:
            return None
        ctx, expiry = entry
        if time.monotonic() > expiry:
            del self._cache[key]
            return None
        return ctx

    def _cache_put(self, key: str, ctx: RuntimeContext) -> None:
        """Store a context in the cache with TTL."""
        if self._cache_ttl <= 0:
            return
        self._cache[key] = (ctx, time.monotonic() + self._cache_ttl)
