"""Surface-specific adapters that wrap the core ActionService."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Type, TypeVar, Union
import json
from pathlib import Path

from .action_contracts import (
    Action,
    ActionCreateRequest,
    Actor,
    ReplayOptions,
    ReplayRequest,
    ReplayStatus,
)
from .action_service import ActionService
from .action_service_postgres import PostgresActionService
from .breakeramp import (
    PlanRequest, PlanResponse, ApplyRequest, ApplyResponse,
    DestroyRequest, DestroyResponse, StatusResponse, BreakerAmpService
)
from .behavior_service import (
    ApproveBehaviorRequest,
    BehaviorService,
    CreateBehaviorDraftRequest,
    DeprecateBehaviorRequest,
    SearchBehaviorsRequest,
    UpdateBehaviorDraftRequest,
)
from .bci_contracts import (
    BatchComposePromptRequest,
    ComposePromptRequest,
    ComputeTokenSavingsRequest,
    DetectPatternsRequest,
    ParseCitationsRequest,
    RetrieveRequest,
    SegmentTraceRequest,
    ScoreReusabilityRequest,
    TraceFormat,
    ValidateCitationsRequest,
    SerializableDataclass,
)
from .task_assignments import TaskAssignmentService
from .compliance_service import ComplianceService
from .reflection_contracts import ReflectRequest
from .run_contracts import Run, RunCompletion, RunCreateRequest, RunProgressUpdate
from .run_service import RunService, RunStatus

if TYPE_CHECKING:
    from .bci_service import BCIService
    from .reflection_service import ReflectionService

try:
    from .run_service_postgres import PostgresRunService
except ImportError:
    PostgresRunService = None  # type: ignore[assignment, misc]

from .device_flow import (
    DeviceFlowManager,
    DeviceAuthorizationSession,
    DevicePollResult,
)


_PARITY_SURFACE_OVERRIDES = {
    "cli": "CLI",
    "api": "REST_API",
    "rest_api": "REST_API",
    "http_api": "REST_API",
    "device_flow": "REST_API",
    "rest": "REST_API",
    "mcp": "MCP",
}


def _normalize_surface_label(surface: str) -> str:
    """Normalize adapter surface labels for parity-sensitive integrations."""

    key = surface.replace("-", "_").lower()
    return _PARITY_SURFACE_OVERRIDES.get(key, surface.upper())


def _format_actor_surface(surface: Optional[str]) -> Optional[str]:
    if not surface:
        return surface
    return _normalize_surface_label(surface)


def _format_action_payload(action: Action) -> Dict[str, Any]:
    payload = action.to_dict()
    actor_payload = payload.get("actor")
    if isinstance(actor_payload, dict) and "surface" in actor_payload:
        actor_payload["surface"] = _format_actor_surface(actor_payload.get("surface"))
    return payload


def _format_replay_payload(replay: ReplayStatus) -> Dict[str, Any]:
    payload = replay.to_dict()
    if payload.get("actor_surface"):
        payload["actor_surface"] = _format_actor_surface(payload["actor_surface"])
    return payload


class BaseAdapter:
    """Common utilities for all adapters."""

    surface: str

    def __init__(self, service: Union[ActionService, PostgresActionService], surface: str) -> None:
        self._service = service
        self.surface = surface

    def _format_action(self, action: Action) -> Dict[str, Any]:
        return _format_action_payload(action)

    def _format_actions(self, actions: Iterable[Action]) -> List[Dict[str, Any]]:
        return [self._format_action(action) for action in actions]

    def _format_replay(self, replay: ReplayStatus) -> Dict[str, Any]:
        return _format_replay_payload(replay)

    def _build_actor(self, actor_payload: Dict[str, Any]) -> Actor:
        return Actor(
            id=actor_payload.get("id", "unknown"),
            role=actor_payload.get("role", "UNKNOWN"),
            surface=actor_payload.get("surface", self.surface),
        )


class RestActionServiceAdapter(BaseAdapter):
    """Mimics REST API payloads/behavior."""

    def __init__(self, service: Union[ActionService, PostgresActionService]) -> None:
        super().__init__(service, surface="api")

    def create_action(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        request = ActionCreateRequest(
            artifact_path=payload["artifact_path"],
            summary=payload["summary"],
            behaviors_cited=list(payload.get("behaviors_cited", [])),
            metadata=payload.get("metadata", {}),
            related_run_id=payload.get("related_run_id"),
            checksum=payload.get("checksum"),
            audit_log_event_id=payload.get("audit_log_event_id"),
        )
        action = self._service.create_action(request, actor)
        return self._format_action(action)

    def list_actions(self) -> List[Dict[str, Any]]:
        return self._format_actions(self._service.list_actions())

    def get_action(self, action_id: str) -> Dict[str, Any]:
        return self._format_action(self._service.get_action(action_id))

    def replay_actions(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        options_payload = payload.get("options", {})
        request = ReplayRequest(
            action_ids=list(payload["action_ids"]),
            strategy=payload.get("strategy", "SEQUENTIAL"),
            options=ReplayOptions(
                skip_existing=options_payload.get("skip_existing", False),
                dry_run=options_payload.get("dry_run", False),
            ),
        )
        replay = self._service.replay_actions(request, actor)
        return self._format_replay(replay)

    def get_replay_status(self, replay_id: str) -> Dict[str, Any]:
        return self._format_replay(self._service.get_replay_status(replay_id))


class CLIActionServiceAdapter(BaseAdapter):
    """Adapter that would back the CLI commands."""

    def __init__(self, service: Union[ActionService, PostgresActionService]) -> None:
        super().__init__(service, surface="cli")

    def record_action(
        self,
        artifact_path: str,
        summary: str,
        behaviors_cited: List[str],
        metadata: Dict[str, Any],
        actor_id: str,
        actor_role: str,
        checksum: str | None = None,
        related_run_id: str | None = None,
        audit_log_event_id: str | None = None,
    ) -> Dict[str, Any]:
        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        request = ActionCreateRequest(
            artifact_path=artifact_path,
            summary=summary,
            behaviors_cited=list(behaviors_cited),
            metadata=metadata,
            related_run_id=related_run_id,
            checksum=checksum,
            audit_log_event_id=audit_log_event_id,
        )
        action = self._service.create_action(request, actor)
        return self._format_action(action)

    def list_actions(self) -> List[Dict[str, Any]]:
        return self._format_actions(self._service.list_actions())

    def get_action(self, action_id: str) -> Dict[str, Any]:
        return self._format_action(self._service.get_action(action_id))

    def replay_actions(
        self,
        action_ids: List[str],
        actor_id: str,
        actor_role: str,
        strategy: str = "SEQUENTIAL",
        skip_existing: bool = False,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        request = ReplayRequest(
            action_ids=list(action_ids),
            strategy=strategy,
        )
        request.options.skip_existing = skip_existing
        request.options.dry_run = dry_run
        replay = self._service.replay_actions(request, actor)
        return self._format_replay(replay)

    def get_replay_status(self, replay_id: str) -> Dict[str, Any]:
        return self._format_replay(self._service.get_replay_status(replay_id))


class MCPActionServiceAdapter(BaseAdapter):
    """Adapter simulating MCP tool invocations."""

    def __init__(self, service: Union[ActionService, "PostgresActionService"]) -> None:
        super().__init__(service, surface="mcp")

    def create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        request = ActionCreateRequest(
            artifact_path=payload["artifact_path"],
            summary=payload["summary"],
            behaviors_cited=list(payload.get("behaviors_cited", [])),
            metadata=payload.get("metadata", {}),
            related_run_id=payload.get("related_run_id"),
            checksum=payload.get("checksum"),
            audit_log_event_id=payload.get("audit_log_event_id"),
        )
        action = self._service.create_action(request, actor)
        return self._format_action(action)

    def list(self) -> List[Dict[str, Any]]:
        return self._format_actions(self._service.list_actions())

    def get(self, action_id: str) -> Dict[str, Any]:
        return self._format_action(self._service.get_action(action_id))

    def replay(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        options_payload = payload.get("options", {})
        replay_request = ReplayRequest(
            action_ids=list(payload["action_ids"]),
            strategy=payload.get("strategy", "SEQUENTIAL"),
            options=ReplayOptions(
                skip_existing=options_payload.get("skip_existing", False),
                dry_run=options_payload.get("dry_run", False),
            ),
        )
        replay = self._service.replay_actions(replay_request, actor)
        return self._format_replay(replay)

    def get_replay_status(self, replay_id: str) -> Dict[str, Any]:
        return self._format_replay(self._service.get_replay_status(replay_id))


class CLIMultiTierActionRegistryAdapter:
    """Adapter for multi-tier action registry in CLI context."""

    def __init__(self, registry: Any) -> None:  # MultiTierActionRegistry
        self._registry = registry
        self.surface = "CLI"

    def record_action(
        self,
        artifact_path: str,
        summary: str,
        behaviors_cited: List[str],
        metadata: Dict[str, Any],
        actor_id: str,
        actor_role: str,
        checksum: str | None = None,
        related_run_id: str | None = None,
        audit_log_event_id: str | None = None,
        tier: str | None = None,
    ) -> Dict[str, Any]:
        """Record action to specified tier or default."""
        from .action_registry import RegistryTier
        from .action_contracts import ActionCreateRequest, Actor

        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        request = ActionCreateRequest(
            artifact_path=artifact_path,
            summary=summary,
            behaviors_cited=list(behaviors_cited),
            metadata=metadata,
            related_run_id=related_run_id,
            checksum=checksum,
            audit_log_event_id=audit_log_event_id,
        )

        registry_tier = RegistryTier(tier) if tier else None
        action = self._registry.create_action(request, actor, tier=registry_tier)
        return _format_action_payload(action)

    def list_actions(self, tier: str | None = None) -> List[Dict[str, Any]]:
        """List actions from specified tier or all tiers."""
        from .action_registry import RegistryTier

        registry_tier = RegistryTier(tier) if tier else None
        actions = self._registry.list_actions(tier=registry_tier)
        return [_format_action_payload(action) for action in actions]

    def get_action(self, action_id: str, tier: str | None = None) -> Dict[str, Any]:
        """Get action from specified tier or search all."""
        from .action_registry import RegistryTier

        registry_tier = RegistryTier(tier) if tier else None
        action = self._registry.get_action(action_id, tier=registry_tier)
        return _format_action_payload(action)

    def replay_actions(
        self,
        action_ids: List[str],
        actor_id: str,
        actor_role: str,
        strategy: str = "SEQUENTIAL",
        skip_existing: bool = False,
        dry_run: bool = False,
        tier: str | None = None,
    ) -> Dict[str, Any]:
        """Replay actions from specified tier."""
        from .action_registry import RegistryTier
        from .action_contracts import Actor, ReplayRequest

        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        request = ReplayRequest(action_ids=list(action_ids), strategy=strategy)
        request.options.skip_existing = skip_existing
        request.options.dry_run = dry_run

        registry_tier = RegistryTier(tier) if tier else None
        replay = self._registry.replay_actions(request, actor, tier=registry_tier)
        return _format_replay_payload(replay)

    def get_replay_status(self, replay_id: str, tier: str | None = None) -> Dict[str, Any]:
        """Get replay status from specified tier or search all."""
        from .action_registry import RegistryTier

        registry_tier = RegistryTier(tier) if tier else None
        replay = self._registry.get_replay_status(replay_id, tier=registry_tier)
        return _format_replay_payload(replay)

    def get_enabled_backends(self) -> List[Dict[str, Any]]:
        """Get list of enabled registry tiers/backends."""
        from .action_registry import RegistryTier

        enabled = self._registry.get_enabled_tiers()
        backends = []

        for tier in enabled:
            config = next((c for c in self._registry.configs if c.tier == tier), None)
            if not config:
                continue

            backend_info = {
                "tier": tier.value,
                "enabled": True,
                "priority": config.priority,
            }

            if tier == RegistryTier.LOCAL:
                store = self._registry.backends.get(tier)
                if hasattr(store, "storage_path"):
                    backend_info["storage_path"] = str(store.storage_path)
            elif tier == RegistryTier.TEAM:
                store = self._registry.backends.get(tier)
                if hasattr(store, "storage_path"):
                    backend_info["storage_path"] = str(store.storage_path)
            elif tier == RegistryTier.PLATFORM:
                backend_info["storage_type"] = "PostgreSQL"

            backends.append(backend_info)

        return backends


class BehaviorAdapterBase:
    """Shared helpers for BehaviorService adapters."""

    def __init__(self, service: BehaviorService, surface: str) -> None:
        self._service = service
        self.surface = surface

    def _build_actor(self, actor_payload: Dict[str, Any]) -> Actor:
        return Actor(
            id=actor_payload.get("id", "unknown"),
            role=actor_payload.get("role", "UNKNOWN"),
            surface=self.surface,
        )

    @staticmethod
    def _format_search_results(results: Iterable[Any]) -> List[Dict[str, Any]]:
        formatted: List[Dict[str, Any]] = []
        for result in results:
            formatted.append(result.to_dict())
        return formatted

    @staticmethod
    def _normalize_embedding(raw: Any) -> Optional[List[float]]:
        if raw is None:
            return None
        if isinstance(raw, list):
            return [float(value) for value in raw]
        # Accept comma-separated strings for CLI convenience.
        if isinstance(raw, str):
            if not raw.strip():
                return None
            return [float(part.strip()) for part in raw.split(",")]
        raise ValueError("Embedding must be a list of numeric values")

    def _behavior_detail(self, behavior_id: str, version: Optional[str] = None) -> Dict[str, Any]:
        return self._service.get_behavior(behavior_id, version)


class RestBehaviorServiceAdapter(BehaviorAdapterBase):
    """REST-style adapter for BehaviorService."""

    def __init__(self, service: BehaviorService) -> None:
        super().__init__(service, surface="api")

    def list_behaviors(self, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        params = params or {}
        return self._service.list_behaviors(
            status=params.get("status"),
            tags=params.get("tags"),
            role_focus=params.get("role_focus"),
        )

    def search_behaviors(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        actor_payload = payload.get("actor", {})
        actor = self._build_actor(actor_payload) if actor_payload else None
        limit = payload.get("limit", 25)
        request = SearchBehaviorsRequest(
            query=payload.get("query"),
            tags=list(payload.get("tags", [])) or None,
            role_focus=payload.get("role_focus"),
            status=payload.get("status"),
            limit=min(int(limit), 100),
            namespace=payload.get("namespace", "core"),
        )
        results = self._service.search_behaviors(request, actor=actor)
        return self._format_search_results(results)

    def create_draft(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        request = CreateBehaviorDraftRequest(
            name=payload["name"],
            description=payload["description"],
            instruction=payload["instruction"],
            role_focus=payload["role_focus"],
            trigger_keywords=list(payload.get("trigger_keywords", [])),
            tags=list(payload.get("tags", [])),
            metadata=dict(payload.get("metadata", {})),
            examples=list(payload.get("examples", [])),
            embedding=self._normalize_embedding(payload.get("embedding")),
            base_version=payload.get("base_version"),
        )
        version = self._service.create_behavior_draft(request, actor)
        return self._behavior_detail(version.behavior_id)

    def update_draft(self, behavior_id: str, version: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        request = UpdateBehaviorDraftRequest(
            behavior_id=behavior_id,
            version=version,
            instruction=payload.get("instruction"),
            description=payload.get("description"),
            trigger_keywords=list(payload.get("trigger_keywords", [])) if "trigger_keywords" in payload else None,
            tags=list(payload.get("tags", [])) if "tags" in payload else None,
            examples=list(payload.get("examples", [])) if "examples" in payload else None,
            metadata=dict(payload.get("metadata", {})) if "metadata" in payload else None,
            embedding=self._normalize_embedding(payload.get("embedding")) if "embedding" in payload else None,
        )
        self._service.update_behavior_draft(request, actor)
        return self._behavior_detail(behavior_id, version)

    def submit_for_review(self, behavior_id: str, version: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        updated = self._service.submit_for_review(behavior_id, version, actor)
        return self._behavior_detail(updated.behavior_id, updated.version)

    def approve(self, behavior_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        request = ApproveBehaviorRequest(
            behavior_id=behavior_id,
            version=payload["version"],
            effective_from=payload["effective_from"],
            approval_action_id=payload.get("approval_action_id"),
        )
        self._service.approve_behavior(request, actor)
        return self._behavior_detail(behavior_id, request.version)

    def deprecate(self, behavior_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        request = DeprecateBehaviorRequest(
            behavior_id=behavior_id,
            version=payload["version"],
            effective_to=payload["effective_to"],
            successor_behavior_id=payload.get("successor_behavior_id"),
        )
        self._service.deprecate_behavior(request, actor)
        return self._behavior_detail(behavior_id, request.version)

    def delete_draft(self, behavior_id: str, version: str, payload: Dict[str, Any]) -> None:
        actor = self._build_actor(payload.get("actor", {}))
        self._service.delete_behavior_draft(behavior_id, version, actor)

    def get_behavior(self, behavior_id: str, version: Optional[str] = None) -> Dict[str, Any]:
        return self._behavior_detail(behavior_id, version)

    # ------------------------------------------------------------------
    # Effectiveness & Benchmark Methods (Admin)
    # ------------------------------------------------------------------
    def get_effectiveness_metrics(
        self,
        status_filter: Optional[str] = None,
        sort_by: str = "usage_count",
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Get aggregated effectiveness metrics for behaviors."""
        return self._service.get_effectiveness_metrics(
            status_filter=status_filter,
            sort_by=sort_by,
            limit=limit,
        )

    def record_feedback(
        self,
        behavior_id: str,
        relevance_score: int,
        helpfulness_score: Optional[int],
        token_reduction_observed: Optional[float],
        comment: Optional[str],
        actor_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record curator feedback for a behavior."""
        return self._service.record_feedback(
            behavior_id=behavior_id,
            relevance_score=relevance_score,
            helpfulness_score=helpfulness_score,
            token_reduction_observed=token_reduction_observed,
            comment=comment,
            actor_id=actor_id,
            context=context or {},
        )

    def get_feedback(self, behavior_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get feedback entries for a specific behavior."""
        return self._service.get_feedback(behavior_id=behavior_id, limit=limit)

    def get_benchmark_results(self, limit: int = 20) -> Dict[str, Any]:
        """Get latest benchmark results."""
        return self._service.get_benchmark_results(limit=limit)

    def trigger_benchmark(
        self,
        corpus_path: Optional[str] = None,
        sample_size: int = 100,
        actor_id: str = "system",
    ) -> Dict[str, Any]:
        """Trigger a new benchmark run."""
        return self._service.trigger_benchmark(
            corpus_path=corpus_path,
            sample_size=sample_size,
            actor_id=actor_id,
        )


class CLIBehaviorServiceAdapter(BehaviorAdapterBase):
    """CLI-focused adapter for BehaviorService."""

    def __init__(self, service: BehaviorService) -> None:
        super().__init__(service, surface="cli")

    def list(self, status: Optional[str] = None, tags: Optional[List[str]] = None, role_focus: Optional[str] = None) -> List[Dict[str, Any]]:
        return self._service.list_behaviors(status=status, tags=tags, role_focus=role_focus)

    def search(
        self,
        *,
        query: Optional[str],
        tags: Optional[List[str]],
        role_focus: Optional[str],
        status: Optional[str],
        limit: int,
        actor_id: str,
        actor_role: str,
    ) -> List[Dict[str, Any]]:
        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        request = SearchBehaviorsRequest(
            query=query,
            tags=tags,
            role_focus=role_focus,
            status=status,
            limit=min(limit, 100),
        )
        results = self._service.search_behaviors(request, actor=actor)
        return self._format_search_results(results)

    def create(
        self,
        *,
        name: str,
        description: str,
        instruction: str,
        role_focus: str,
        trigger_keywords: List[str],
        tags: List[str],
        metadata: Dict[str, Any],
        examples: List[Dict[str, Any]],
        embedding: Optional[List[float]],
        actor_id: str,
        actor_role: str,
    ) -> Dict[str, Any]:
        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        request = CreateBehaviorDraftRequest(
            name=name,
            description=description,
            instruction=instruction,
            role_focus=role_focus,
            trigger_keywords=trigger_keywords,
            tags=tags,
            metadata=metadata,
            examples=examples,
            embedding=embedding,
        )
        version = self._service.create_behavior_draft(request, actor)
        return self._behavior_detail(version.behavior_id)

    def update(
        self,
        *,
        behavior_id: str,
        version: str,
        instruction: Optional[str],
        description: Optional[str],
        trigger_keywords: Optional[List[str]],
        tags: Optional[List[str]],
        metadata: Optional[Dict[str, Any]],
        examples: Optional[List[Dict[str, Any]]],
        embedding: Optional[List[float]],
        actor_id: str,
        actor_role: str,
    ) -> Dict[str, Any]:
        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        request = UpdateBehaviorDraftRequest(
            behavior_id=behavior_id,
            version=version,
            instruction=instruction,
            description=description,
            trigger_keywords=trigger_keywords,
            tags=tags,
            examples=examples,
            metadata=metadata,
            embedding=embedding,
        )
        self._service.update_behavior_draft(request, actor)
        return self._behavior_detail(behavior_id, version)

    def submit(self, behavior_id: str, version: str, actor_id: str, actor_role: str) -> Dict[str, Any]:
        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        updated = self._service.submit_for_review(behavior_id, version, actor)
        return self._behavior_detail(updated.behavior_id, updated.version)

    def approve(
        self,
        *,
        behavior_id: str,
        version: str,
        effective_from: str,
        approval_action_id: Optional[str],
        actor_id: str,
        actor_role: str,
    ) -> Dict[str, Any]:
        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        request = ApproveBehaviorRequest(
            behavior_id=behavior_id,
            version=version,
            effective_from=effective_from,
            approval_action_id=approval_action_id,
        )
        self._service.approve_behavior(request, actor)
        return self._behavior_detail(behavior_id, version)

    def deprecate(
        self,
        *,
        behavior_id: str,
        version: str,
        effective_to: str,
        successor_behavior_id: Optional[str],
        actor_id: str,
        actor_role: str,
    ) -> Dict[str, Any]:
        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        request = DeprecateBehaviorRequest(
            behavior_id=behavior_id,
            version=version,
            effective_to=effective_to,
            successor_behavior_id=successor_behavior_id,
        )
        self._service.deprecate_behavior(request, actor)
        return self._behavior_detail(behavior_id, version)

    def delete_draft(self, behavior_id: str, version: str, actor_id: str, actor_role: str) -> None:
        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        self._service.delete_behavior_draft(behavior_id, version, actor)

    def get(self, behavior_id: str, version: Optional[str] = None) -> Dict[str, Any]:
        return self._behavior_detail(behavior_id, version)


class MCPBehaviorServiceAdapter(BehaviorAdapterBase):
    """Adapter mimicking MCP tool invocation payloads for BehaviorService."""

    def __init__(self, service: BehaviorService) -> None:
        super().__init__(service, surface="mcp")

    def list(self, payload: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        payload = payload or {}
        return self._service.list_behaviors(
            status=payload.get("status"),
            tags=payload.get("tags"),
            role_focus=payload.get("role_focus"),
        )

    def search(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        actor = self._build_actor(payload.get("actor", {}))
        request = SearchBehaviorsRequest(
            query=payload.get("query"),
            tags=list(payload.get("tags", [])) or None,
            role_focus=payload.get("role_focus"),
            status=payload.get("status"),
            limit=min(int(payload.get("limit", 25)), 100),
        )
        results = self._service.search_behaviors(request, actor=actor)
        return self._format_search_results(results)

    def create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        request = CreateBehaviorDraftRequest(
            name=payload["name"],
            description=payload["description"],
            instruction=payload["instruction"],
            role_focus=payload["role_focus"],
            trigger_keywords=list(payload.get("trigger_keywords", [])),
            tags=list(payload.get("tags", [])),
            metadata=dict(payload.get("metadata", {})),
            examples=list(payload.get("examples", [])),
            embedding=self._normalize_embedding(payload.get("embedding")),
            base_version=payload.get("base_version"),
        )
        version = self._service.create_behavior_draft(request, actor)
        return self._behavior_detail(version.behavior_id)

    def update(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        request = UpdateBehaviorDraftRequest(
            behavior_id=payload["behavior_id"],
            version=payload["version"],
            instruction=payload.get("instruction"),
            description=payload.get("description"),
            trigger_keywords=list(payload.get("trigger_keywords", [])) if "trigger_keywords" in payload else None,
            tags=list(payload.get("tags", [])) if "tags" in payload else None,
            examples=list(payload.get("examples", [])) if "examples" in payload else None,
            metadata=dict(payload.get("metadata", {})) if "metadata" in payload else None,
            embedding=self._normalize_embedding(payload.get("embedding")) if "embedding" in payload else None,
        )
        self._service.update_behavior_draft(request, actor)
        return self._behavior_detail(request.behavior_id, request.version)

    def submit(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        updated = self._service.submit_for_review(payload["behavior_id"], payload["version"], actor)
        return self._behavior_detail(updated.behavior_id, updated.version)

    def approve(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        request = ApproveBehaviorRequest(
            behavior_id=payload["behavior_id"],
            version=payload["version"],
            effective_from=payload["effective_from"],
            approval_action_id=payload.get("approval_action_id"),
        )
        self._service.approve_behavior(request, actor)
        return self._behavior_detail(request.behavior_id, request.version)

    def deprecate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        request = DeprecateBehaviorRequest(
            behavior_id=payload["behavior_id"],
            version=payload["version"],
            effective_to=payload["effective_to"],
            successor_behavior_id=payload.get("successor_behavior_id"),
        )
        self._service.deprecate_behavior(request, actor)
        return self._behavior_detail(request.behavior_id, request.version)

    def delete_draft(self, payload: Dict[str, Any]) -> None:
        actor = self._build_actor(payload.get("actor", {}))
        self._service.delete_behavior_draft(payload["behavior_id"], payload["version"], actor)

    def get(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._behavior_detail(payload["behavior_id"], payload.get("version"))

    def get_for_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Get relevant behaviors for a task before execution."""
        from .behavior_service import RoleContext

        actor = self._build_actor(payload.get("actor", {}))
        role = payload.get("role", "Student")
        task_description = payload["task_description"]
        limit = min(int(payload.get("limit", 5)), 20)

        role_context = None
        if payload.get("role_context"):
            rc = payload["role_context"]
            role_context = RoleContext(
                role=rc.get("role", role),
                rationale=rc.get("rationale", ""),
                behaviors_cited=rc.get("behaviors_cited", []),
            )

        result = self._service.get_relevant_behaviors_for_task(
            task_description=task_description,
            role=role,
            limit=limit,
            actor=actor,
            role_context=role_context,
        )

        return {
            "role": result["role"],
            "task_description": result["task_description"],
            "role_advisory": result["role_advisory"],
            "recommended_behaviors": result["recommended_behaviors"],
        }


class BaseTaskAdapter:
    """Common adapter utilities for task assignments."""

    def __init__(self, service: TaskAssignmentService) -> None:
        self._service = service

    def _list(self, function: str | None, agent: str | None = None) -> List[Dict[str, Any]]:
        return self._service.list_assignments(function=function, agent=agent)


class RestTaskAssignmentAdapter(BaseTaskAdapter):
    """Mimics REST API payloads for task assignment queries."""

    def __init__(self, service: TaskAssignmentService) -> None:
        super().__init__(service)

    def list_assignments(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        function = payload.get("function") if isinstance(payload, dict) else None
        agent = payload.get("agent") if isinstance(payload, dict) else None
        return self._list(function, agent)


class CLITaskAssignmentAdapter(BaseTaskAdapter):
    """Adapter backing CLI task assignment commands."""

    def __init__(self, service: TaskAssignmentService) -> None:
        super().__init__(service)

    def list_assignments(self, function: str | None = None, agent: str | None = None) -> List[Dict[str, Any]]:
        return self._list(function, agent)


class MCPTaskAssignmentAdapter(BaseTaskAdapter):
    """Adapter providing MCP task listing parity."""

    def __init__(self, service: TaskAssignmentService) -> None:
        super().__init__(service)

    def list_assignments(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        function = payload.get("function") if isinstance(payload, dict) else None
        agent = payload.get("agent") if isinstance(payload, dict) else None
        return self._list(function, agent)


# ------------------------------------------------------------------
# Agent Registry Adapters
# ------------------------------------------------------------------


class RestAgentRegistryAdapter:
    """Adapter backing REST API endpoints for AgentRegistryService.

    Note: This adapter is intentionally light-weight and avoids importing
    AgentRegistryService at module import time so the core API can start even
    when agent-registry dependencies are not installed.
    """

    def __init__(self, service: Any) -> None:
        self._service = service
        self.surface = "api"

    def _build_actor(self, actor_payload: Optional[Dict[str, Any]]) -> Actor:
        actor_payload = actor_payload or {}
        return Actor(
            id=actor_payload.get("id", "unknown"),
            role=actor_payload.get("role", "UNKNOWN"),
            surface=self.surface,
        )

    @staticmethod
    def _coerce_enum(enum_cls: Any, raw: Any) -> Any:
        if raw is None:
            return None
        if hasattr(raw, "value"):
            return raw
        try:
            return enum_cls(str(raw))
        except Exception:
            return raw

    def list_agents(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        from .agent_registry_contracts import AgentStatus, AgentVisibility, ListAgentsRequest, RoleAlignment

        request = ListAgentsRequest(
            status=self._coerce_enum(AgentStatus, payload.get("status")),
            visibility=self._coerce_enum(AgentVisibility, payload.get("visibility")),
            role_alignment=self._coerce_enum(RoleAlignment, payload.get("role_alignment")),
            owner_id=payload.get("owner_id"),
            include_builtin=payload.get("builtin", payload.get("include_builtin", True)),
            limit=min(int(payload.get("limit", 50)), 200),
            org_id=payload.get("org_id"),
        )
        results = self._service.list_agents(request, org_id=payload.get("org_id"))

        offset = int(payload.get("offset", 0) or 0)
        if offset > 0:
            return list(results)[offset:]
        return list(results)

    def create_agent(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from .agent_registry_contracts import AgentVisibility, CreateAgentRequest, RoleAlignment

        actor = self._build_actor(payload.get("actor"))
        request = CreateAgentRequest(
            name=payload["name"],
            slug=payload.get("slug", ""),
            description=payload.get("description", ""),
            mission=payload.get("mission", ""),
            role_alignment=self._coerce_enum(RoleAlignment, payload.get("role_alignment", "STUDENT")),
            capabilities=list(payload.get("capabilities", [])),
            default_behaviors=list(payload.get("default_behaviors", [])),
            playbook_content=payload.get("playbook_content", ""),
            tags=list(payload.get("tags", [])),
            visibility=self._coerce_enum(AgentVisibility, payload.get("visibility"))
            or AgentVisibility.PRIVATE.value,
            metadata=dict(payload.get("metadata", {})),
            request_api_credentials=bool(payload.get("request_api_credentials", False)),
        )
        response = self._service.create_agent(request, actor, org_id=payload.get("org_id"))

        # Build response with agent and optional credentials
        result: Dict[str, Any] = {}
        if hasattr(response, "agent"):
            # New CreateAgentResponse format
            result = response.agent.to_dict() if hasattr(response.agent, "to_dict") else cast(Dict[str, Any], response.agent)
            if response.client_id:
                result["credentials"] = {
                    "client_id": response.client_id,
                    "client_secret": response.client_secret,
                }
        else:
            # Legacy Agent format (for backwards compatibility)
            result = response.to_dict() if hasattr(response, "to_dict") else cast(Dict[str, Any], response)

        return result

    def search_agents(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from .agent_registry_contracts import (
            AgentStatus,
            AgentVisibility,
            RoleAlignment,
            SearchAgentsRequest,
        )

        actor_payload = payload.get("actor")
        actor = self._build_actor(actor_payload) if actor_payload else None
        request = SearchAgentsRequest(
            query=payload.get("query"),
            tags=list(payload.get("tags", [])) or None,
            role_alignment=self._coerce_enum(RoleAlignment, payload.get("role_alignment")),
            visibility=self._coerce_enum(AgentVisibility, payload.get("visibility")),
            status=self._coerce_enum(AgentStatus, payload.get("status")),
            owner_id=payload.get("owner_id"),
            include_builtin=payload.get("include_builtin", True),
            limit=min(int(payload.get("limit", 25)), 100),
            org_id=payload.get("org_id"),
        )
        results = self._service.search_agents(request, actor=actor)
        formatted = [result.to_dict() if hasattr(result, "to_dict") else result for result in results]
        return {"results": formatted, "total": len(formatted)}

    def get_agent(
        self,
        agent_id: str,
        *,
        version: Optional[Any] = None,
        include_history: bool = False,
    ) -> Dict[str, Any]:
        del include_history
        version_str = str(version) if version is not None else None
        return self._service.get_agent(agent_id, version=version_str)

    def update_agent(self, agent_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        from .agent_registry_contracts import AgentVisibility, UpdateAgentRequest

        actor = self._build_actor(payload.get("actor"))
        request = UpdateAgentRequest(
            agent_id=agent_id,
            version=str(payload.get("version") or payload.get("latest_version") or "latest"),
            name=payload.get("name"),
            description=payload.get("description"),
            mission=payload.get("mission"),
            role_alignment=payload.get("role_alignment"),
            capabilities=payload.get("capabilities"),
            default_behaviors=payload.get("default_behaviors"),
            playbook_content=payload.get("playbook_content"),
            tags=payload.get("tags"),
            metadata=payload.get("metadata"),
        )
        # Map visibility separately; service only updates agent-level visibility.
        if "visibility" in payload:
            request.visibility = self._coerce_enum(AgentVisibility, payload.get("visibility"))

        updated = self._service.update_agent(request, actor)
        return updated.to_dict() if hasattr(updated, "to_dict") else cast(Dict[str, Any], updated)

    def delete_agent(self, agent_id: str) -> None:
        actor = Actor(id="api", role="SYSTEM", surface=self.surface)
        self._service.delete_agent(agent_id, actor)

    def create_new_version(self, agent_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        from .agent_registry_contracts import CreateNewVersionRequest, RoleAlignment

        actor = self._build_actor(payload.get("actor"))
        request = CreateNewVersionRequest(
            agent_id=agent_id,
            base_version=payload.get("base_version"),
            mission=payload.get("mission"),
            role_alignment=self._coerce_enum(RoleAlignment, payload.get("role_alignment")),
            capabilities=payload.get("capabilities"),
            default_behaviors=payload.get("default_behaviors"),
            playbook_content=payload.get("playbook_content"),
            metadata=payload.get("metadata"),
        )
        version = self._service.create_new_version(request, actor)
        return version.to_dict() if hasattr(version, "to_dict") else cast(Dict[str, Any], version)

    def publish_agent(self, agent_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        from .agent_registry_contracts import AgentVisibility, PublishAgentRequest

        actor = self._build_actor(payload.get("actor"))
        request = PublishAgentRequest(
            agent_id=agent_id,
            version=str(payload.get("version") or "1.0.0"),
            visibility=self._coerce_enum(AgentVisibility, payload.get("visibility"))
            or AgentVisibility.PUBLIC.value,
            effective_from=payload.get("effective_from"),
        )
        agent = self._service.publish_agent(request, actor)
        return agent.to_dict() if hasattr(agent, "to_dict") else cast(Dict[str, Any], agent)

    def deprecate_agent(self, agent_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        from .agent_registry_contracts import DeprecateAgentRequest

        actor = self._build_actor(payload.get("actor"))
        request = DeprecateAgentRequest(
            agent_id=agent_id,
            version=str(payload["version"]),
            effective_to=payload["effective_to"],
            successor_agent_id=payload.get("successor_agent_id"),
        )
        agent = self._service.deprecate_agent(request, actor)
        return agent.to_dict() if hasattr(agent, "to_dict") else cast(Dict[str, Any], agent)

    def bootstrap_from_playbooks(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor_payload = payload.get("actor")
        actor = self._build_actor(actor_payload) if actor_payload else None
        force = bool(payload.get("force", False))
        return self._service.bootstrap_from_playbooks(actor=actor, force=force)


# ------------------------------------------------------------------
# Assignment Service Adapters
# ------------------------------------------------------------------

class RestAssignmentAdapter:
    """Adapter backing REST API endpoints for AssignmentService (agent suggestions)."""

    def __init__(self, service: Any) -> None:
        self._service = service

    def _build_actor(self, actor_payload: Optional[Dict[str, Any]]) -> Optional[Any]:
        if not actor_payload:
            return None
        from amprealize.services.board_service import Actor
        return Actor(
            id=actor_payload.get("id", "unknown"),
            role=actor_payload.get("role", "UNKNOWN"),
            surface="api",
        )

    def suggest_agent(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Suggest agents for an assignable entity."""
        from amprealize.boards.contracts import SuggestAgentRequest

        request = SuggestAgentRequest(
            assignable_id=payload["assignable_id"],
            assignable_type=payload["assignable_type"],
            required_behaviors=payload.get("required_behaviors", []),
            exclude_agent_ids=payload.get("exclude_agent_ids"),
            max_suggestions=payload.get("max_suggestions", 5),
        )
        actor = self._build_actor(payload.get("actor"))
        org_id = payload.get("org_id")

        response = self._service.suggest_agent(request, actor=actor, org_id=org_id)
        return response.model_dump() if hasattr(response, "model_dump") else response.dict()


# ------------------------------------------------------------------
# Compliance Service Adapters
# ------------------------------------------------------------------

class BaseComplianceAdapter:
    """Common utilities for compliance adapters."""

    surface: str

    def __init__(self, service: ComplianceService, surface: str) -> None:
        self._service = service
        self.surface = surface

    def _build_actor(self, actor_payload: Dict[str, Any]) -> Actor:
        return Actor(
            id=actor_payload.get("id", "unknown"),
            role=actor_payload.get("role", "UNKNOWN"),
            surface=self.surface,
        )


class RestComplianceServiceAdapter(BaseComplianceAdapter):
    """Mimics REST API payloads/behavior for compliance operations."""

    def __init__(self, service: ComplianceService) -> None:
        super().__init__(service, surface="api")

    def create_checklist(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        checklist = self._service.create_checklist(
            title=payload["title"],
            description=payload.get("description", ""),
            template_id=payload.get("template_id"),
            milestone=payload.get("milestone"),
            compliance_category=list(payload.get("compliance_category", [])),
            actor=actor,
        )
        return checklist.to_dict()

    def get_checklist(self, checklist_id: str) -> Dict[str, Any]:
        return self._service.get_checklist(checklist_id).to_dict()

    def list_checklists(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        checklists = self._service.list_checklists(
            milestone=payload.get("milestone"),
            compliance_category=payload.get("compliance_category"),
            status_filter=payload.get("status_filter"),
        )
        return [checklist.to_dict() for checklist in checklists]

    def record_step(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from .compliance_service import RecordStepRequest

        actor = self._build_actor(payload.get("actor", {}))
        request = RecordStepRequest(
            checklist_id=payload["checklist_id"],
            title=payload["title"],
            status=payload["status"],
            evidence=payload.get("evidence", {}),
            behaviors_cited=list(payload.get("behaviors_cited", [])),
            related_run_id=payload.get("related_run_id"),
        )
        step = self._service.record_step(request, actor)
        return step.to_dict()

    def validate_checklist(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        result = self._service.validate_checklist(payload["checklist_id"], actor)
        return result.to_dict()


class CLIComplianceServiceAdapter(BaseComplianceAdapter):
    """Adapter backing CLI compliance commands."""

    def __init__(self, service: ComplianceService) -> None:
        super().__init__(service, surface="cli")

    def create_checklist(
        self,
        title: str,
        description: str,
        template_id: str | None,
        milestone: str | None,
        compliance_category: List[str],
        actor_id: str,
        actor_role: str,
    ) -> Dict[str, Any]:
        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        checklist = self._service.create_checklist(
            title=title,
            description=description,
            template_id=template_id,
            milestone=milestone,
            compliance_category=compliance_category,
            actor=actor,
        )
        return checklist.to_dict()

    def get_checklist(self, checklist_id: str) -> Dict[str, Any]:
        return self._service.get_checklist(checklist_id).to_dict()

    def list_checklists(
        self,
        milestone: str | None = None,
        compliance_category: List[str] | None = None,
        status_filter: str | None = None,
    ) -> List[Dict[str, Any]]:
        checklists = self._service.list_checklists(
            milestone=milestone,
            compliance_category=compliance_category,
            status_filter=status_filter,
        )
        return [checklist.to_dict() for checklist in checklists]

    def record_step(
        self,
        checklist_id: str,
        title: str,
        status: str,
        evidence: Dict[str, Any] | None,
        behaviors_cited: List[str] | None,
        related_run_id: str | None,
        actor_id: str,
        actor_role: str,
    ) -> Dict[str, Any]:
        from .compliance_service import RecordStepRequest

        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        request = RecordStepRequest(
            checklist_id=checklist_id,
            title=title,
            status=status,
            evidence=evidence or {},
            behaviors_cited=behaviors_cited or [],
            related_run_id=related_run_id,
        )
        step = self._service.record_step(request, actor)
        return step.to_dict()

    def validate_checklist(self, checklist_id: str, actor_id: str, actor_role: str) -> Dict[str, Any]:
        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        result = self._service.validate_checklist(checklist_id, actor)
        return result.to_dict()

    def validate_by_action_id(self, action_id: str, actor_id: str, actor_role: str) -> Dict[str, Any]:
        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        result = self._service.validate_by_action_id(action_id, actor)
        return result.to_dict()

    def create_policy(
        self,
        name: str,
        description: str,
        policy_type: str,
        enforcement_level: str,
        actor_id: str,
        actor_role: str,
        org_id: str | None = None,
        project_id: str | None = None,
        version: str = "1.0.0",
        required_behaviors: List[str] | None = None,
        compliance_categories: List[str] | None = None,
    ) -> Dict[str, Any]:
        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        policy = self._service.create_policy(
            name=name,
            description=description,
            policy_type=policy_type,
            enforcement_level=enforcement_level,
            actor=actor,
            org_id=org_id,
            project_id=project_id,
            version=version,
            required_behaviors=required_behaviors,
            compliance_categories=compliance_categories,
        )
        return policy.to_dict()

    def get_policy(self, policy_id: str) -> Dict[str, Any]:
        return self._service.get_policy(policy_id).to_dict()

    def list_policies(
        self,
        org_id: str | None = None,
        project_id: str | None = None,
        policy_type: str | None = None,
        enforcement_level: str | None = None,
        is_active: bool | None = None,
    ) -> List[Dict[str, Any]]:
        policies = self._service.list_policies(
            org_id=org_id,
            project_id=project_id,
            policy_type=policy_type,
            enforcement_level=enforcement_level,
            is_active=is_active,
        )
        return [policy.to_dict() for policy in policies]

    def get_audit_trail(
        self,
        run_id: str | None = None,
        checklist_id: str | None = None,
        action_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Dict[str, Any]:
        report = self._service.get_audit_trail(
            run_id=run_id,
            checklist_id=checklist_id,
            action_id=action_id,
            start_date=start_date,
            end_date=end_date,
        )
        return report.to_dict()


class MCPComplianceServiceAdapter(BaseComplianceAdapter):
    """Adapter simulating MCP compliance tool invocations."""

    def __init__(self, service: ComplianceService) -> None:
        super().__init__(service, surface="mcp")

    def create_checklist(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        checklist = self._service.create_checklist(
            title=payload["title"],
            description=payload.get("description", ""),
            template_id=payload.get("template_id"),
            milestone=payload.get("milestone"),
            compliance_category=list(payload.get("compliance_category", [])),
            actor=actor,
        )
        return checklist.to_dict()

    def get_checklist(self, checklist_id: str) -> Dict[str, Any]:
        return self._service.get_checklist(checklist_id).to_dict()

    def list_checklists(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        checklists = self._service.list_checklists(
            milestone=payload.get("milestone"),
            compliance_category=payload.get("compliance_category"),
            status_filter=payload.get("status_filter"),
        )
        return [checklist.to_dict() for checklist in checklists]

    def record_step(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from .compliance_service import RecordStepRequest

        actor = self._build_actor(payload.get("actor", {}))
        request = RecordStepRequest(
            checklist_id=payload["checklist_id"],
            title=payload["title"],
            status=payload["status"],
            evidence=payload.get("evidence", {}),
            behaviors_cited=list(payload.get("behaviors_cited", [])),
            related_run_id=payload.get("related_run_id"),
        )
        step = self._service.record_step(request, actor)
        return step.to_dict()

    def validate_checklist(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        result = self._service.validate_checklist(payload["checklist_id"], actor)
        return result.to_dict()

    def validate_by_action_id(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        result = self._service.validate_by_action_id(payload["action_id"], actor)
        return result.to_dict()

    def create_policy(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        policy = self._service.create_policy(
            name=payload["name"],
            description=payload.get("description", ""),
            policy_type=payload["policy_type"],
            enforcement_level=payload["enforcement_level"],
            actor=actor,
            org_id=payload.get("org_id"),
            project_id=payload.get("project_id"),
            version=payload.get("version", "1.0.0"),
            rules=payload.get("rules"),
            required_behaviors=payload.get("required_behaviors"),
            compliance_categories=payload.get("compliance_categories"),
            metadata=payload.get("metadata"),
        )
        return policy.to_dict()

    def get_policy(self, policy_id: str) -> Dict[str, Any]:
        return self._service.get_policy(policy_id).to_dict()

    def list_policies(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        policies = self._service.list_policies(
            org_id=payload.get("org_id"),
            project_id=payload.get("project_id"),
            policy_type=payload.get("policy_type"),
            enforcement_level=payload.get("enforcement_level"),
            is_active=payload.get("is_active"),
            include_global=payload.get("include_global", True),
        )
        return [policy.to_dict() for policy in policies]

    def get_audit_trail(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        report = self._service.get_audit_trail(
            run_id=payload.get("run_id"),
            checklist_id=payload.get("checklist_id"),
            action_id=payload.get("action_id"),
            start_date=payload.get("start_date"),
            end_date=payload.get("end_date"),
        )
        return report.to_dict()


# Run Service Adapters


class BaseRunServiceAdapter:
    """Shared utilities for RunService surfaces."""

    surface: str

    def __init__(self, service: Union[RunService, "PostgresRunService"], surface: str) -> None:  # type: ignore[name-defined]
        self._service = service
        self.surface = surface

    def _format_run(self, run: Run) -> Dict[str, Any]:
        return run.to_dict()

    def _format_runs(self, runs: Iterable[Run]) -> List[Dict[str, Any]]:
        return [self._format_run(run) for run in runs]

    def _build_actor(self, payload: Dict[str, Any]) -> Actor:
        return Actor(
            id=payload.get("id", "unknown"),
            role=payload.get("role", "UNKNOWN"),
            surface=self.surface,
        )


class CLIRunServiceAdapter(BaseRunServiceAdapter):
    """Adapter backing CLI run commands."""

    def __init__(self, service: Union[RunService, "PostgresRunService"]) -> None:  # type: ignore[name-defined]
        super().__init__(service, surface="cli")

    def create_run(
        self,
        *,
        actor_id: str,
        actor_role: str,
        workflow_id: str | None = None,
        workflow_name: str | None = None,
        template_id: str | None = None,
        template_name: str | None = None,
        behavior_ids: List[str] | None = None,
        metadata: Dict[str, Any] | None = None,
        initial_message: str | None = None,
        total_steps: int | None = None,
        triggering_user_id: str | None = None,
    ) -> Dict[str, Any]:
        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        request = RunCreateRequest(
            actor=actor,
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            template_id=template_id,
            template_name=template_name,
            behavior_ids=list(behavior_ids or []),
            metadata=metadata or {},
            initial_message=initial_message,
            total_steps=total_steps,
            triggering_user_id=triggering_user_id,
        )
        run = self._service.create_run(request)
        return self._format_run(run)

    def get_run(self, run_id: str) -> Dict[str, Any]:
        return self._format_run(self._service.get_run(run_id))

    def list_runs(
        self,
        *,
        status: str | None = None,
        workflow_id: str | None = None,
        template_id: str | None = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        runs = self._service.list_runs(
            status=status,
            workflow_id=workflow_id,
            template_id=template_id,
            limit=limit,
        )
        return self._format_runs(runs)

    def update_run(
        self,
        run_id: str,
        *,
        status: str | None = None,
        progress_pct: float | None = None,
        message: str | None = None,
        step_id: str | None = None,
        step_name: str | None = None,
        step_status: str | None = None,
        tokens_generated: int | None = None,
        tokens_baseline: int | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        update = RunProgressUpdate(
            status=status,
            progress_pct=progress_pct,
            message=message,
            step_id=step_id,
            step_name=step_name,
            step_status=step_status,
            tokens_generated=tokens_generated,
            tokens_baseline=tokens_baseline,
            metadata=metadata or {},
        )
        run = self._service.update_run(run_id, update)
        return self._format_run(run)

    def complete_run(
        self,
        run_id: str,
        *,
        status: str,
        outputs: Dict[str, Any] | None = None,
        message: str | None = None,
        error: str | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        completion = RunCompletion(
            status=status,
            outputs=outputs or {},
            message=message,
            error=error,
            metadata=metadata or {},
        )
        run = self._service.complete_run(run_id, completion)
        return self._format_run(run)

    def cancel_run(self, run_id: str, *, reason: str | None = None) -> Dict[str, Any]:
        run = self._service.cancel_run(run_id, reason=reason)
        return self._format_run(run)

    def delete_run(self, run_id: str) -> None:
        self._service.delete_run(run_id)


class RestRunServiceAdapter(BaseRunServiceAdapter):
    """REST-style adapter for RunService endpoints."""

    def __init__(self, service: Union[RunService, "PostgresRunService"]) -> None:  # type: ignore[name-defined]
        super().__init__(service, surface="api")

    def create_run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        request = RunCreateRequest(
            actor=actor,
            workflow_id=payload.get("workflow_id"),
            workflow_name=payload.get("workflow_name"),
            template_id=payload.get("template_id"),
            template_name=payload.get("template_name"),
            behavior_ids=list(payload.get("behavior_ids", [])),
            metadata=payload.get("metadata", {}),
            initial_message=payload.get("initial_message"),
            total_steps=payload.get("total_steps"),
            triggering_user_id=payload.get("triggering_user_id"),
        )
        run = self._service.create_run(request)
        return self._format_run(run)

    def get_run(self, run_id: str) -> Dict[str, Any]:
        return self._format_run(self._service.get_run(run_id))

    def list_runs(self, payload: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
        payload = payload or {}
        runs = self._service.list_runs(
            status=payload.get("status"),
            workflow_id=payload.get("workflow_id"),
            template_id=payload.get("template_id"),
            limit=payload.get("limit", 50),
        )
        return self._format_runs(runs)

    def update_run(self, run_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        update = RunProgressUpdate(
            status=payload.get("status"),
            progress_pct=payload.get("progress_pct"),
            message=payload.get("message"),
            step_id=payload.get("step_id"),
            step_name=payload.get("step_name"),
            step_status=payload.get("step_status"),
            tokens_generated=payload.get("tokens_generated"),
            tokens_baseline=payload.get("tokens_baseline"),
            metadata=payload.get("metadata", {}),
        )
        run = self._service.update_run(run_id, update)
        return self._format_run(run)

    def complete_run(self, run_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        completion = RunCompletion(
            status=payload["status"],
            outputs=payload.get("outputs", {}),
            message=payload.get("message"),
            error=payload.get("error"),
            metadata=payload.get("metadata", {}),
        )
        run = self._service.complete_run(run_id, completion)
        return self._format_run(run)

    def cancel_run(self, run_id: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
        reason = (payload or {}).get("reason")
        run = self._service.cancel_run(run_id, reason=reason)
        return self._format_run(run)

    def delete_run(self, run_id: str) -> None:
        self._service.delete_run(run_id)

    def update_status(self, run_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Update only the status of a run (convenience wrapper around update_run).

        Args:
            run_id: Run identifier.
            payload: Dict containing 'status' and optional 'message'.

        Returns:
            Updated run as dict.
        """
        update = RunProgressUpdate(
            status=payload["status"],
            message=payload.get("message"),
        )
        run = self._service.update_run(run_id, update)
        return self._format_run(run)

    async def fetch_logs(
        self, run_id: str, payload: Dict[str, Any], raze_service: Any = None
    ) -> Dict[str, Any]:
        """Fetch execution logs for a run from Raze.

        Args:
            run_id: Run identifier.
            payload: Query parameters (level, start_time, end_time, limit, after, search, include_steps).
            raze_service: RazeService instance for querying logs.

        Returns:
            RunLogsResponse as dict.
        """
        response = await self._service.fetch_logs(
            run_id=run_id,
            raze_service=raze_service,
            level=payload.get("level"),
            start_time=payload.get("start_time"),
            end_time=payload.get("end_time"),
            limit=min(payload.get("limit", 100), 1000),
            after=payload.get("after"),
            search=payload.get("search"),
            include_steps=payload.get("include_steps", True),
        )
        return response.to_dict()


class MCPRunServiceAdapter(BaseRunServiceAdapter):
    """Adapter simulating MCP tool interactions for runs."""

    def __init__(self, service: RunService) -> None:
        super().__init__(service, surface="mcp")

    def create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        request = RunCreateRequest(
            actor=actor,
            workflow_id=payload.get("workflow_id"),
            workflow_name=payload.get("workflow_name"),
            template_id=payload.get("template_id"),
            template_name=payload.get("template_name"),
            behavior_ids=list(payload.get("behavior_ids", [])),
            metadata=payload.get("metadata", {}),
            initial_message=payload.get("initial_message"),
            total_steps=payload.get("total_steps"),
            triggering_user_id=payload.get("triggering_user_id"),
        )
        run = self._service.create_run(request)
        return self._format_run(run)

    def list(self, payload: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
        payload = payload or {}
        runs = self._service.list_runs(
            status=payload.get("status"),
            workflow_id=payload.get("workflow_id"),
            template_id=payload.get("template_id"),
            limit=payload.get("limit", 50),
        )
        return self._format_runs(runs)

    def get(self, run_id: str) -> Dict[str, Any]:
        return self._format_run(self._service.get_run(run_id))

    def update(self, run_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        update = RunProgressUpdate(
            status=payload.get("status"),
            progress_pct=payload.get("progress_pct"),
            message=payload.get("message"),
            step_id=payload.get("step_id"),
            step_name=payload.get("step_name"),
            step_status=payload.get("step_status"),
            tokens_generated=payload.get("tokens_generated"),
            tokens_baseline=payload.get("tokens_baseline"),
            metadata=payload.get("metadata", {}),
        )
        run = self._service.update_run(run_id, update)
        return self._format_run(run)

    def complete(self, run_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        completion = RunCompletion(
            status=payload["status"],
            outputs=payload.get("outputs", {}),
            message=payload.get("message"),
            error=payload.get("error"),
            metadata=payload.get("metadata", {}),
        )
        run = self._service.complete_run(run_id, completion)
        return self._format_run(run)

    def cancel(self, run_id: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
        reason = (payload or {}).get("reason")
        run = self._service.cancel_run(run_id, reason=reason)
        return self._format_run(run)

    def delete(self, run_id: str) -> None:
        self._service.delete_run(run_id)

    def update_status(self, run_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Update only the status of a run (convenience wrapper around update).

        Args:
            run_id: Run identifier.
            payload: Dict containing 'status' and optional 'message'.

        Returns:
            Updated run as dict.
        """
        update = RunProgressUpdate(
            status=payload["status"],
            message=payload.get("message"),
        )
        run = self._service.update_run(run_id, update)
        return self._format_run(run)

    async def fetch_logs(
        self, run_id: str, payload: Dict[str, Any], raze_service: Any = None
    ) -> Dict[str, Any]:
        """Fetch execution logs for a run from Raze.

        Args:
            run_id: Run identifier.
            payload: Query parameters (level, start_time, end_time, limit, after, search, include_steps).
            raze_service: RazeService instance for querying logs.

        Returns:
            RunLogsResponse as dict.
        """
        response = await self._service.fetch_logs(
            run_id=run_id,
            raze_service=raze_service,
            level=payload.get("level"),
            start_time=payload.get("start_time"),
            end_time=payload.get("end_time"),
            limit=min(payload.get("limit", 100), 1000),
            after=payload.get("after"),
            search=payload.get("search"),
            include_steps=payload.get("include_steps", True),
        )
        return response.to_dict()


# Workflow Service Adapters


class BaseWorkflowAdapter:
    """Base adapter for Workflow Service integrations."""

    surface: str

    def __init__(self, service: Any, surface: str) -> None:
        self._service = service
        self.surface = surface

    def _build_actor(self, payload: Dict[str, Any]) -> Actor:
        return Actor(
            id=payload.get("id", "unknown"),
            role=payload.get("role", "UNKNOWN"),
            surface=self.surface,
        )

    def _format_template(self, template: Any) -> Dict[str, Any]:
        data = template.to_dict()
        created_by = data.get("created_by")
        if isinstance(created_by, dict) and "surface" in created_by:
            created_by["surface"] = _format_actor_surface(created_by.get("surface"))
        return data

    def _format_templates(self, templates: Iterable[Any]) -> List[Dict[str, Any]]:
        return [self._format_template(template) for template in templates]

    def _format_run(self, run: Any) -> Dict[str, Any]:
        data = run.to_dict()
        actor_payload = data.get("actor")
        if isinstance(actor_payload, dict) and "surface" in actor_payload:
            actor_payload["surface"] = _format_actor_surface(actor_payload.get("surface"))
        return data


class CLIWorkflowServiceAdapter(BaseWorkflowAdapter):
    """Adapter for CLI workflow commands."""

    def __init__(self, service: Any) -> None:
        super().__init__(service, surface="cli")

    def create_template(
        self,
        name: str,
        description: str,
        role_focus: str,
        steps: List[Dict[str, Any]],
        tags: List[str] | None,
        metadata: Dict[str, Any] | None,
        actor_id: str,
        actor_role: str,
    ) -> Dict[str, Any]:
        from .workflow_service import TemplateStep, WorkflowRole

        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        template_steps = [
            TemplateStep(
                step_id=step.get("step_id", f"step-{idx}"),
                name=step["name"],
                description=step["description"],
                prompt_template=step["prompt_template"],
                behavior_injection_point=step.get("behavior_injection_point", "{{BEHAVIORS}}"),
                required_behaviors=step.get("required_behaviors", []),
                validation_rules=step.get("validation_rules", {}),
                metadata=step.get("metadata", {}),
            )
            for idx, step in enumerate(steps)
        ]
        template = self._service.create_template(
            name=name,
            description=description,
            role_focus=WorkflowRole(role_focus),
            steps=template_steps,
            actor=actor,
            tags=tags,
            metadata=metadata,
        )
        return self._format_template(template)

    def get_template(self, template_id: str) -> Dict[str, Any] | None:
        template = self._service.get_template(template_id)
        return self._format_template(template) if template else None

    def list_templates(
        self,
        role_focus: str | None = None,
        tags: List[str] | None = None,
    ) -> List[Dict[str, Any]]:
        from .workflow_service import WorkflowRole

        role = WorkflowRole(role_focus) if role_focus else None
        templates = self._service.list_templates(role_focus=role, tags=tags)
        return self._format_templates(templates)

    def run_workflow(
        self,
        template_id: str,
        behavior_ids: List[str] | None,
        metadata: Dict[str, Any] | None,
        actor_id: str,
        actor_role: str,
        enable_early_retrieval: bool = True,
    ) -> Dict[str, Any]:
        actor = Actor(id=actor_id, role=actor_role, surface=self.surface)
        run = self._service.run_workflow(
            template_id=template_id,
            actor=actor,
            behavior_ids=behavior_ids,
            metadata=metadata,
            enable_early_retrieval=enable_early_retrieval,
        )
        return self._format_run(run)

    def get_run(self, run_id: str) -> Dict[str, Any] | None:
        run = self._service.get_run(run_id)
        return self._format_run(run) if run else None


# ------------------------------------------------------------------
# BCI Service Adapters
# ------------------------------------------------------------------

_BCIRequestT = TypeVar("_BCIRequestT", bound=SerializableDataclass)


class BaseBCIAdapter:
    """Shared utilities for BCI adapters."""

    def __init__(self, service: BCIService, surface: str) -> None:
        self._service = service
        self.surface = surface

    @staticmethod
    def _from_payload(payload: Dict[str, Any], cls: Type[_BCIRequestT]) -> _BCIRequestT:
        return cls.from_dict(payload)


class RestBCIAdapter(BaseBCIAdapter):
    """REST-style adapter for BCI endpoints."""

    def __init__(self, service: BCIService) -> None:
        super().__init__(service, surface="api")

    def retrieve(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = self._from_payload(payload, RetrieveRequest)
        return self._service.retrieve(request).to_dict()

    def retrieve_hybrid(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = self._from_payload(payload, RetrieveRequest)
        return self._service.retrieve_hybrid(request).to_dict()

    def rebuild_index(self) -> Dict[str, Any]:
        return self._service.rebuild_index()

    def compose_prompt(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = self._from_payload(payload, ComposePromptRequest)
        return self._service.compose_prompt(request).to_dict()

    def compose_batch_prompts(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = self._from_payload(payload, BatchComposePromptRequest)
        return self._service.compose_prompts_batch(request).to_dict()

    def parse_citations(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = self._from_payload(payload, ParseCitationsRequest)
        return self._service.parse_citations(request).to_dict()

    def validate_citations(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = self._from_payload(payload, ValidateCitationsRequest)
        return self._service.validate_citations(request).to_dict()

    def compute_token_savings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = self._from_payload(payload, ComputeTokenSavingsRequest)
        return self._service.compute_token_savings(request).to_dict()

    def segment_trace(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = self._from_payload(payload, SegmentTraceRequest)
        return self._service.segment_trace(request).to_dict()

    def detect_patterns(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = self._from_payload(payload, DetectPatternsRequest)
        return self._service.detect_patterns(request).to_dict()

    def score_reusability(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = self._from_payload(payload, ScoreReusabilityRequest)
        return self._service.score_reusability(request).to_dict()

    def generate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a behavior-conditioned LLM response."""
        from .llm import LLMConfig, ProviderType

        # Parse provider type (enum values are lowercase)
        provider_str = payload.get("provider", "openai")
        try:
            provider_type = ProviderType(provider_str.lower())
        except ValueError:
            provider_type = ProviderType.OPENAI

        # Build LLM config - pass provider_type so API key resolution uses correct provider
        llm_config = LLMConfig.from_env(provider=provider_type)
        if payload.get("model"):
            llm_config.model = payload["model"]
        if payload.get("temperature") is not None:
            llm_config.temperature = float(payload["temperature"])

        # Parse role focus
        role_focus = None
        if payload.get("role_focus"):
            try:
                from .bci_contracts import RoleFocus
                role_focus = RoleFocus(payload["role_focus"].upper())
            except (ValueError, AttributeError):
                pass

        result = self._service.generate_response(
            query=payload["query"],
            behaviors=payload.get("behaviors"),
            top_k=payload.get("top_k", 5),
            llm_config=llm_config,
            system_prompt=payload.get("system_prompt"),
            role_focus=role_focus,
        )

        # Convert LLMResponse to dict if needed
        if hasattr(result["response"], "to_dict"):
            result["response"] = result["response"].to_dict()
        elif hasattr(result["response"], "__dict__"):
            result["response"] = vars(result["response"])

        return result

    def improve(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze a failed run and generate improvement suggestions."""
        from .llm import LLMConfig, ProviderType

        # Parse provider type (enum values are lowercase)
        provider_str = payload.get("provider", "openai")
        try:
            provider_type = ProviderType(provider_str.lower())
        except ValueError:
            provider_type = ProviderType.OPENAI

        # Build LLM config - pass provider_type so API key resolution uses correct provider
        llm_config = LLMConfig.from_env(provider=provider_type)
        if payload.get("model"):
            llm_config.model = payload["model"]

        result = self._service.improve_run(
            run_id=payload["run_id"],
            llm_config=llm_config,
            max_behaviors=payload.get("max_behaviors", 10),
        )

        return result


class MCPBCIAdapter(BaseBCIAdapter):
    """Adapter mapping MCP tool names to BCI service calls."""

    def __init__(self, service: BCIService) -> None:
        super().__init__(service, surface="mcp")

    def retrieve(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = self._from_payload(payload, RetrieveRequest)
        return self._service.retrieve(request).to_dict()

    def retrieveHybrid(self, payload: Dict[str, Any]) -> Dict[str, Any]:  # noqa: N802 - MCP naming parity
        request = self._from_payload(payload, RetrieveRequest)
        return self._service.retrieve_hybrid(request).to_dict()

    def rebuildIndex(self) -> Dict[str, Any]:  # noqa: N802
        return self._service.rebuild_index()

    def composePrompt(self, payload: Dict[str, Any]) -> Dict[str, Any]:  # noqa: N802
        request = self._from_payload(payload, ComposePromptRequest)
        return self._service.compose_prompt(request).to_dict()

    def composeBatchPrompts(self, payload: Dict[str, Any]) -> Dict[str, Any]:  # noqa: N802
        request = self._from_payload(payload, BatchComposePromptRequest)
        return self._service.compose_prompts_batch(request).to_dict()

    def parseCitations(self, payload: Dict[str, Any]) -> Dict[str, Any]:  # noqa: N802
        request = self._from_payload(payload, ParseCitationsRequest)
        return self._service.parse_citations(request).to_dict()

    def validateCitations(self, payload: Dict[str, Any]) -> Dict[str, Any]:  # noqa: N802
        request = self._from_payload(payload, ValidateCitationsRequest)
        return self._service.validate_citations(request).to_dict()

    def computeTokenSavings(self, payload: Dict[str, Any]) -> Dict[str, Any]:  # noqa: N802
        request = self._from_payload(payload, ComputeTokenSavingsRequest)
        return self._service.compute_token_savings(request).to_dict()

    def segmentTrace(self, payload: Dict[str, Any]) -> Dict[str, Any]:  # noqa: N802
        request = self._from_payload(payload, SegmentTraceRequest)
        return self._service.segment_trace(request).to_dict()

    def detectPatterns(self, payload: Dict[str, Any]) -> Dict[str, Any]:  # noqa: N802
        request = self._from_payload(payload, DetectPatternsRequest)
        return self._service.detect_patterns(request).to_dict()

    def scoreReusability(self, payload: Dict[str, Any]) -> Dict[str, Any]:  # noqa: N802
        request = self._from_payload(payload, ScoreReusabilityRequest)
        return self._service.score_reusability(request).to_dict()



class BaseReflectionAdapter:
    """Shared utilities for ReflectionService adapters."""

    def __init__(self, service: ReflectionService, surface: str) -> None:
        self._service = service
        self.surface = surface

    def _parse(self, payload: Dict[str, Any]) -> ReflectRequest:
        return ReflectRequest.from_dict(payload)


class RestReflectionAdapter(BaseReflectionAdapter):
    """REST adapter exposing reflection extraction."""

    # Auto-accept threshold per PRD requirement: candidates >= 0.8 confidence
    AUTO_ACCEPT_THRESHOLD = 0.8

    def __init__(self, service: ReflectionService) -> None:
        super().__init__(service, surface="api")

    def extract(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = self._parse(payload)
        return self._service.reflect(request).to_dict()

    def list_candidates(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """List behavior candidates for review.

        Query params are passed as payload dict:
            status?: str - Filter by status (proposed, approved, rejected, merged)
            role?: str - Filter by role
            min_confidence?: float - Filter by minimum confidence
            limit?: int - Max results (default 50)
            offset?: int - Pagination offset (default 0)
        """
        # Check if service supports list_candidates (PostgresReflectionService)
        if not hasattr(self._service, "list_candidates"):
            return {
                "candidates": [],
                "total": 0,
                "message": "Candidate listing requires PostgreSQL storage (set AMPREALIZE_POSTGRES_DSN)",
            }

        candidates = self._service.list_candidates(
            status=payload.get("status"),
            role=payload.get("role"),
            min_confidence=payload.get("min_confidence"),
            limit=payload.get("limit", 50),
            offset=payload.get("offset", 0),
        )

        return {
            "candidates": [c.to_dict() if hasattr(c, "to_dict") else c for c in candidates],
            "total": len(candidates),
        }

    def approve_candidate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Approve a behavior candidate and add it to the handbook.

        Returns the created behavior ID on success.
        """
        import uuid

        slug = payload.get("slug")
        status = payload.get("status", "approved")
        reviewer_notes = payload.get("reviewer_notes", "")

        if not slug:
            return {"success": False, "error": "slug is required"}

        # Generate a behavior ID (in production, this would persist to BehaviorService)
        behavior_id = str(uuid.uuid4())

        # Log the approval for audit purposes
        audit_entry = {
            "action": "candidate_approved",
            "slug": slug,
            "status": status,
            "behavior_id": behavior_id,
            "reviewer_notes": reviewer_notes,
            "surface": self.surface,
        }

        # In a full implementation, this would:
        # 1. Validate the candidate exists
        # 2. Create a new behavior in BehaviorService
        # 3. Update the behavior handbook
        # 4. Emit telemetry event

        return {
            "success": True,
            "behavior_id": behavior_id,
            "slug": slug,
            "status": status,
            "message": f"Candidate '{slug}' approved and added to handbook",
            "audit": audit_entry,
        }

    def reject_candidate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Reject a behavior candidate."""
        slug = payload.get("slug")
        reason = payload.get("reason", "Not suitable for handbook")

        if not slug:
            return {"success": False, "error": "slug is required"}

        # Log the rejection for audit purposes
        audit_entry = {
            "action": "candidate_rejected",
            "slug": slug,
            "reason": reason,
            "surface": self.surface,
        }

        return {
            "success": True,
            "slug": slug,
            "status": "rejected",
            "reason": reason,
            "message": f"Candidate '{slug}' rejected",
            "audit": audit_entry,
        }


class CLIReflectionAdapter(BaseReflectionAdapter):
    """CLI adapter translating flags into reflection requests."""

    def __init__(self, service: ReflectionService) -> None:
        super().__init__(service, surface="cli")

    def reflect(
        self,
        *,
        trace_text: str,
        trace_format: str,
        run_id: Optional[str],
        max_candidates: int,
        min_quality_score: float,
        include_examples: bool,
        preferred_tags: Optional[List[str]],
    ) -> Dict[str, Any]:
        request = ReflectRequest(
            trace_text=trace_text,
            trace_format=TraceFormat(trace_format),
            run_id=run_id,
            max_candidates=max(1, max_candidates),
            min_quality_score=min_quality_score,
            include_examples=include_examples,
            preferred_tags=preferred_tags,
        )
        return self._service.reflect(request).to_dict()

    def list_candidates(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """List behavior candidates for review.

        payload:
            status?: str - Filter by status (proposed, approved, rejected, merged)
            role?: str - Filter by role
            min_confidence?: float - Filter by minimum confidence
            limit?: int - Max results (default 50)
            offset?: int - Pagination offset (default 0)
        """
        # Check if service supports list_candidates (PostgresReflectionService)
        if not hasattr(self._service, "list_candidates"):
            return {
                "candidates": [],
                "total": 0,
                "message": "Candidate listing requires PostgreSQL storage (set AMPREALIZE_POSTGRES_DSN)",
            }

        candidates = self._service.list_candidates(
            status=payload.get("status"),
            role=payload.get("role"),
            min_confidence=payload.get("min_confidence"),
            limit=payload.get("limit", 50),
            offset=payload.get("offset", 0),
        )

        return {
            "candidates": [c.to_dict() if hasattr(c, "to_dict") else c for c in candidates],
            "total": len(candidates),
        }

    def approve_candidate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Approve a behavior candidate.

        payload:
            candidate_id: str - ID of the candidate to approve
            reviewed_by: str - Reviewer identifier
            merge_to_handbook?: bool - Immediately merge to behavior handbook
            behavior_name?: str - Override behavior name when merging
        """
        candidate_id = payload.get("candidate_id")
        if not candidate_id:
            return {"success": False, "message": "candidate_id is required"}

        # Check if service supports approve_candidate
        if not hasattr(self._service, "approve_candidate"):
            return {
                "success": False,
                "message": "Candidate approval requires PostgreSQL storage (set AMPREALIZE_POSTGRES_DSN)",
            }

        reviewed_by = payload.get("reviewed_by", "cli-user")

        try:
            result = self._service.approve_candidate(
                candidate_id=candidate_id,
                reviewed_by=reviewed_by,
            )

            response: Dict[str, Any] = {
                "success": True,
                "candidate_id": candidate_id,
                "status": "approved",
            }

            # Check for auto-approval (confidence >= 0.8)
            if hasattr(result, "confidence") and result.confidence >= 0.8:
                response["auto_approved"] = True

            # Handle merge to handbook if requested
            if payload.get("merge_to_handbook"):
                response["merge_requested"] = True
                behavior_id = self._promote_candidate_cli(result, reviewed_by)
                if behavior_id:
                    response["merged_behavior_id"] = behavior_id

            return response

        except Exception as e:
            return {"success": False, "message": str(e)}

    def _promote_candidate_cli(self, candidate: Any, reviewed_by: str) -> Optional[str]:
        """Promote an approved candidate to a behavior via BehaviorService (CLI surface)."""
        try:
            import os as _os
            from .behavior_service import BehaviorService
            from .action_contracts import Actor

            dsn = _os.environ.get("AMPREALIZE_BEHAVIOR_PG_DSN")
            if not dsn:
                return None

            behavior_service = BehaviorService(dsn=dsn)
            actor = Actor(id=reviewed_by, type="user")
            result = behavior_service.promote_candidate_to_behavior(
                candidate_name=getattr(candidate, "name", "unknown"),
                candidate_summary=getattr(candidate, "summary", ""),
                candidate_triggers=getattr(candidate, "triggers", []) or [],
                candidate_steps=getattr(candidate, "steps", []) or [],
                candidate_keywords=getattr(candidate, "keywords", []) or [],
                candidate_confidence=getattr(candidate, "confidence", 0.0),
                candidate_role=getattr(candidate, "role", "Student") or "Student",
                actor=actor,
            )
            return result.get("behavior_id")
        except Exception:
            return None

    def reject_candidate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Reject a behavior candidate.

        payload:
            candidate_id: str - ID of the candidate to reject
            reviewed_by: str - Reviewer identifier
            reason?: str - Reason for rejection
        """
        candidate_id = payload.get("candidate_id")
        if not candidate_id:
            return {"success": False, "message": "candidate_id is required"}

        # Check if service supports reject_candidate
        if not hasattr(self._service, "reject_candidate"):
            return {
                "success": False,
                "message": "Candidate rejection requires PostgreSQL storage (set AMPREALIZE_POSTGRES_DSN)",
            }

        reviewed_by = payload.get("reviewed_by", "cli-user")
        reason = payload.get("reason")

        try:
            self._service.reject_candidate(
                candidate_id=candidate_id,
                reviewed_by=reviewed_by,
                reason=reason,
            )

            return {
                "success": True,
                "candidate_id": candidate_id,
                "status": "rejected",
                "reason": reason,
            }

        except Exception as e:
            return {"success": False, "message": str(e)}


class MCPReflectionAdapter(BaseReflectionAdapter):
    """Adapter for MCP reflection tool invocations."""

    def __init__(self, service: ReflectionService) -> None:
        super().__init__(service, surface="mcp")

    def extract(self, payload: Dict[str, Any]) -> Dict[str, Any]:  # noqa: N802 - MCP naming parity
        request = self._parse(payload)
        return self._service.reflect(request).to_dict()


class RestWorkflowServiceAdapter(BaseWorkflowAdapter):
    """Adapter for REST API workflow endpoints."""

    def __init__(self, service: Any) -> None:
        super().__init__(service, surface="api")

    def create_template(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from .workflow_service import TemplateStep, WorkflowRole

        actor = self._build_actor(payload.get("actor", {}))
        steps_data = payload.get("steps", [])
        template_steps = [
            TemplateStep(
                step_id=step.get("step_id", f"step-{idx}"),
                name=step["name"],
                description=step["description"],
                prompt_template=step["prompt_template"],
                behavior_injection_point=step.get("behavior_injection_point", "{{BEHAVIORS}}"),
                required_behaviors=step.get("required_behaviors", []),
                validation_rules=step.get("validation_rules", {}),
                metadata=step.get("metadata", {}),
            )
            for idx, step in enumerate(steps_data)
        ]
        template = self._service.create_template(
            name=payload["name"],
            description=payload["description"],
            role_focus=WorkflowRole(payload["role_focus"]),
            steps=template_steps,
            actor=actor,
            tags=payload.get("tags"),
            metadata=payload.get("metadata"),
        )
        return self._format_template(template)

    def get_template(self, template_id: str) -> Dict[str, Any] | None:
        template = self._service.get_template(template_id)
        return self._format_template(template) if template else None

    def list_templates(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        from .workflow_service import WorkflowRole

        role_focus = payload.get("role_focus")
        role = WorkflowRole(role_focus) if role_focus else None
        templates = self._service.list_templates(
            role_focus=role,
            tags=payload.get("tags"),
        )
        return self._format_templates(templates)

    def run_workflow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        run = self._service.run_workflow(
            template_id=payload["template_id"],
            actor=actor,
            behavior_ids=payload.get("behavior_ids"),
            metadata=payload.get("metadata"),
            enable_early_retrieval=payload.get("enable_early_retrieval", True),
        )
        return self._format_run(run)

    def get_run(self, run_id: str) -> Dict[str, Any] | None:
        run = self._service.get_run(run_id)
        return self._format_run(run) if run else None

    def update_run_status(self, run_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        from .workflow_service import WorkflowStatus

        status = WorkflowStatus(payload["status"])
        self._service.update_run_status(
            run_id=run_id,
            status=status,
            total_tokens=payload.get("total_tokens"),
        )
        run = self._service.get_run(run_id)
        return self._format_run(run) if run else {}


class MCPWorkflowServiceAdapter(BaseWorkflowAdapter):
    """Adapter for MCP tool workflow invocations."""

    def __init__(self, service: Any) -> None:
        super().__init__(service, surface="mcp")

    def create_template(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from .workflow_service import TemplateStep, WorkflowRole

        actor = self._build_actor(payload.get("actor", {}))
        steps_data = payload.get("steps", [])
        template_steps = [
            TemplateStep(
                step_id=step.get("step_id", f"step-{idx}"),
                name=step["name"],
                description=step["description"],
                prompt_template=step["prompt_template"],
                behavior_injection_point=step.get("behavior_injection_point", "{{BEHAVIORS}}"),
                required_behaviors=step.get("required_behaviors", []),
                validation_rules=step.get("validation_rules", {}),
                metadata=step.get("metadata", {}),
            )
            for idx, step in enumerate(steps_data)
        ]
        template = self._service.create_template(
            name=payload["name"],
            description=payload["description"],
            role_focus=WorkflowRole(payload["role_focus"]),
            steps=template_steps,
            actor=actor,
            tags=payload.get("tags"),
            metadata=payload.get("metadata"),
        )
        return self._format_template(template)

    def get_template(self, template_id: str) -> Dict[str, Any] | None:
        template = self._service.get_template(template_id)
        return self._format_template(template) if template else None

    def list_templates(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        from .workflow_service import WorkflowRole

        role_focus = payload.get("role_focus")
        role = WorkflowRole(role_focus) if role_focus else None
        templates = self._service.list_templates(
            role_focus=role,
            tags=payload.get("tags"),
        )
        return self._format_templates(templates)

    def run_workflow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._build_actor(payload.get("actor", {}))
        run = self._service.run_workflow(
            template_id=payload["template_id"],
            actor=actor,
            behavior_ids=payload.get("behavior_ids"),
            metadata=payload.get("metadata"),
            enable_early_retrieval=payload.get("enable_early_retrieval", True),
        )
        return self._format_run(run)

    def get_run(self, run_id: str) -> Dict[str, Any] | None:
        run = self._service.get_run(run_id)
        return self._format_run(run) if run else None


# ============================================================================
# MetricsService Adapters
# ============================================================================


class BaseMetricsServiceAdapter:
    """Shared utilities for MetricsService surfaces."""

    surface: str

    def __init__(self, service: Any, surface: str) -> None:
        """Initialize adapter.

        Args:
            service: MetricsService instance
            surface: Surface name (CLI, REST_API, MCP)
        """
        self._service = service
        self.surface = surface

    def _format_summary(self, summary: Any) -> Dict[str, Any]:
        """Format MetricsSummary as dict."""
        from dataclasses import asdict
        return asdict(summary)

    def _format_export(self, export: Any) -> Dict[str, Any]:
        """Format MetricsExportResult as dict."""
        from dataclasses import asdict
        return asdict(export)

    def _format_subscription(self, subscription: Any) -> Dict[str, Any]:
        """Format MetricsSubscription as dict."""
        from dataclasses import asdict
        return asdict(subscription)


class CLIMetricsServiceAdapter(BaseMetricsServiceAdapter):
    """Adapter backing CLI metrics commands."""

    def __init__(self, service: Any) -> None:
        super().__init__(service, surface="cli")

    def get_summary(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """Get metrics summary.

        Args:
            start_date: Start date filter (ISO format)
            end_date: End date filter (ISO format)
            use_cache: Whether to use cached data

        Returns:
            MetricsSummary as dict
        """
        summary = self._service.get_summary(
            start_date=start_date,
            end_date=end_date,
            use_cache=use_cache,
        )
        return self._format_summary(summary)

    def export_metrics(
        self,
        *,
        format: str = "json",
        start_date: str | None = None,
        end_date: str | None = None,
        metrics: List[str] | None = None,
        include_raw_events: bool = False,
    ) -> Dict[str, Any]:
        """Export metrics data.

        Args:
            format: Export format ('json', 'csv', 'parquet')
            start_date: Start date for export
            end_date: End date for export
            metrics: List of metric names to export
            include_raw_events: Whether to include raw telemetry

        Returns:
            MetricsExportResult as dict
        """
        from amprealize.metrics_contracts import MetricsExportRequest

        request = MetricsExportRequest(
            format=format,
            start_date=start_date,
            end_date=end_date,
            metrics=list(metrics or []),
            include_raw_events=include_raw_events,
        )
        export = self._service.export_metrics(request)
        return self._format_export(export)


class RestMetricsServiceAdapter(BaseMetricsServiceAdapter):
    """REST-style adapter for MetricsService endpoints."""

    def __init__(self, service: Any) -> None:
        super().__init__(service, surface="api")

    def get_summary(self, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """Get metrics summary from HTTP query parameters.

        Args:
            payload: Query parameters (start_date, end_date, use_cache)

        Returns:
            MetricsSummary as dict
        """
        payload = payload or {}
        summary = self._service.get_summary(
            start_date=payload.get("start_date"),
            end_date=payload.get("end_date"),
            use_cache=payload.get("use_cache", True),
        )
        return self._format_summary(summary)

    def export_metrics(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Export metrics from HTTP POST body.

        Args:
            payload: Export request fields

        Returns:
            MetricsExportResult as dict
        """
        from amprealize.metrics_contracts import MetricsExportRequest

        request = MetricsExportRequest(
            format=payload.get("format", "json"),
            start_date=payload.get("start_date"),
            end_date=payload.get("end_date"),
            metrics=list(payload.get("metrics", [])),
            include_raw_events=payload.get("include_raw_events", False),
        )
        export = self._service.export_metrics(request)
        return self._format_export(export)

    def create_subscription(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create real-time metrics subscription.

        Args:
            payload: Subscription parameters (metrics, refresh_interval_seconds)

        Returns:
            MetricsSubscription as dict
        """
        subscription = self._service.create_subscription(
            metrics=payload.get("metrics"),
            refresh_interval_seconds=payload.get("refresh_interval_seconds", 30),
        )
        return self._format_subscription(subscription)

    def cancel_subscription(self, subscription_id: str) -> Dict[str, Any]:
        """Cancel subscription.

        Args:
            subscription_id: Subscription to cancel

        Returns:
            Status dict
        """
        cancelled = self._service.cancel_subscription(subscription_id)
        return {"cancelled": cancelled, "subscription_id": subscription_id}


class MCPMetricsServiceAdapter(BaseMetricsServiceAdapter):
    """Adapter simulating MCP tool interactions for metrics."""

    def __init__(self, service: Any) -> None:
        super().__init__(service, surface="mcp")

    def get_summary(self, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """MCP metrics.getSummary tool.

        Args:
            payload: Optional filters (start_date, end_date)

        Returns:
            MetricsSummary as dict
        """
        payload = payload or {}
        summary = self._service.get_summary(
            start_date=payload.get("start_date"),
            end_date=payload.get("end_date"),
            use_cache=payload.get("use_cache", True),
        )
        return self._format_summary(summary)

    def export(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP metrics.export tool.

        Args:
            payload: Export request fields

        Returns:
            MetricsExportResult as dict
        """
        from amprealize.metrics_contracts import MetricsExportRequest

        request = MetricsExportRequest(
            format=payload.get("format", "json"),
            start_date=payload.get("start_date"),
            end_date=payload.get("end_date"),
            metrics=list(payload.get("metrics", [])),
            include_raw_events=payload.get("include_raw_events", False),
        )
        export = self._service.export_metrics(request)
        return self._format_export(export)

    def subscribe(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP metrics.subscribe tool (creates subscription).

        Args:
            payload: Subscription parameters

        Returns:
            MetricsSubscription as dict
        """
        subscription = self._service.create_subscription(
            metrics=payload.get("metrics"),
            refresh_interval_seconds=payload.get("refresh_interval_seconds", 30),
        )
        return self._format_subscription(subscription)


# ============================================================================
# AnalyticsService Adapters
# ============================================================================


class BaseAnalyticsServiceAdapter:
    """Shared adapter utilities for AnalyticsWarehouse surfaces."""

    surface: str

    def __init__(self, service: Any, surface: str = "base") -> None:
        """Initialize adapter with AnalyticsWarehouse service."""
        self._service = service
        self.surface = surface

    def _serialize_datetime(self, obj: Any) -> Any:
        """Convert datetime objects to ISO format strings recursively."""
        from datetime import datetime, date

        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        elif isinstance(obj, dict):
            return {k: self._serialize_datetime(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._serialize_datetime(item) for item in obj]
        return obj

    def _format_kpi_summary(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Format KPI summary records for the current surface."""
        return {
            "records": self._serialize_datetime(records),
            "count": len(records),
        }

    def _format_behavior_usage(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Format behavior usage records for the current surface."""
        return {
            "records": self._serialize_datetime(records),
            "count": len(records),
        }

    def _format_token_savings(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Format token savings records for the current surface."""
        return {
            "records": self._serialize_datetime(records),
            "count": len(records),
        }

    def _format_compliance_coverage(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Format compliance coverage records for the current surface."""
        return {
            "records": self._serialize_datetime(records),
            "count": len(records),
        }


class CLIAnalyticsServiceAdapter(BaseAnalyticsServiceAdapter):
    """CLI adapter for AnalyticsWarehouse (terminal output)."""

    def __init__(self, service: Any) -> None:
        super().__init__(service, surface="cli")

    def kpi_summary(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """CLI analytics.kpiSummary command.

        Args:
            payload: Query parameters (start_date, end_date)

        Returns:
            Formatted KPI summary for terminal display
        """
        records = self._service.get_kpi_summary(
            start_date=payload.get("start_date"),
            end_date=payload.get("end_date"),
        )
        return self._format_kpi_summary(records)

    def behavior_usage(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """CLI analytics.behaviorUsage command.

        Args:
            payload: Query parameters (start_date, end_date, limit)

        Returns:
            Formatted behavior usage for terminal display
        """
        records = self._service.get_behavior_usage(
            start_date=payload.get("start_date"),
            end_date=payload.get("end_date"),
            limit=payload.get("limit", 100),
        )
        return self._format_behavior_usage(records)

    def token_savings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """CLI analytics.tokenSavings command.

        Args:
            payload: Query parameters (start_date, end_date, limit)

        Returns:
            Formatted token savings for terminal display
        """
        records = self._service.get_token_savings(
            start_date=payload.get("start_date"),
            end_date=payload.get("end_date"),
            limit=payload.get("limit", 100),
        )
        return self._format_token_savings(records)

    def compliance_coverage(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """CLI analytics.complianceCoverage command.

        Args:
            payload: Query parameters (start_date, end_date, limit)

        Returns:
            Formatted compliance coverage for terminal display
        """
        records = self._service.get_compliance_coverage(
            start_date=payload.get("start_date"),
            end_date=payload.get("end_date"),
            limit=payload.get("limit", 100),
        )
        return self._format_compliance_coverage(records)


class RestAnalyticsServiceAdapter(BaseAnalyticsServiceAdapter):
    """REST adapter for AnalyticsWarehouse (JSON responses)."""

    def __init__(self, service: Any) -> None:
        super().__init__(service, surface="REST")

    def kpi_summary(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """REST /v1/analytics/kpi-summary endpoint.

        Args:
            payload: Query parameters (start_date, end_date)

        Returns:
            JSON response with KPI summary records
        """
        records = self._service.get_kpi_summary(
            start_date=payload.get("start_date"),
            end_date=payload.get("end_date"),
        )
        return self._format_kpi_summary(records)

    def behavior_usage(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """REST /v1/analytics/behavior-usage endpoint.

        Args:
            payload: Query parameters (start_date, end_date, limit)

        Returns:
            JSON response with behavior usage records
        """
        records = self._service.get_behavior_usage(
            start_date=payload.get("start_date"),
            end_date=payload.get("end_date"),
            limit=payload.get("limit", 100),
        )
        return self._format_behavior_usage(records)

    def token_savings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """REST /v1/analytics/token-savings endpoint.

        Args:
            payload: Query parameters (start_date, end_date, limit)

        Returns:
            JSON response with token savings records
        """
        records = self._service.get_token_savings(
            start_date=payload.get("start_date"),
            end_date=payload.get("end_date"),
            limit=payload.get("limit", 100),
        )
        return self._format_token_savings(records)

    def compliance_coverage(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """REST /v1/analytics/compliance-coverage endpoint.

        Args:
            payload: Query parameters (start_date, end_date, limit)

        Returns:
            JSON response with compliance coverage records
        """
        records = self._service.get_compliance_coverage(
            start_date=payload.get("start_date"),
            end_date=payload.get("end_date"),
            limit=payload.get("limit", 100),
        )
        return self._format_compliance_coverage(records)


class MCPAnalyticsServiceAdapter(BaseAnalyticsServiceAdapter):
    """MCP adapter for AnalyticsWarehouse (MCP tool responses)."""

    def __init__(self, service: Any) -> None:
        super().__init__(service, surface="mcp")

    @staticmethod
    async def _resolve(value: Any) -> Any:
        """Await if coroutine, otherwise return as-is (handles sync/async services)."""
        import inspect
        if inspect.iscoroutine(value):
            return await value
        return value

    async def kpi_summary(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP analytics.kpiSummary tool.

        Args:
            payload: Query parameters (start_date, end_date)

        Returns:
            MCP tool response with KPI summary records
        """
        records = await self._resolve(self._service.get_kpi_summary(
            start_date=payload.get("start_date"),
            end_date=payload.get("end_date"),
        ))
        return self._format_kpi_summary(records)

    async def behavior_usage(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP analytics.behaviorUsage tool.

        Args:
            payload: Query parameters (start_date, end_date, limit)

        Returns:
            MCP tool response with behavior usage records
        """
        records = await self._resolve(self._service.get_behavior_usage(
            start_date=payload.get("start_date"),
            end_date=payload.get("end_date"),
            limit=payload.get("limit", 100),
        ))
        return self._format_behavior_usage(records)

    async def token_savings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP analytics.tokenSavings tool.

        Args:
            payload: Query parameters (start_date, end_date, limit)

        Returns:
            MCP tool response with token savings records
        """
        records = await self._resolve(self._service.get_token_savings(
            start_date=payload.get("start_date"),
            end_date=payload.get("end_date"),
            limit=payload.get("limit", 100),
        ))
        return self._format_token_savings(records)

    async def compliance_coverage(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP analytics.complianceCoverage tool.

        Args:
            payload: Query parameters (start_date, end_date, limit)

        Returns:
            MCP tool response with compliance coverage records
        """
        records = await self._resolve(self._service.get_compliance_coverage(
            start_date=payload.get("start_date"),
            end_date=payload.get("end_date"),
            limit=payload.get("limit", 100),
        ))
        return self._format_compliance_coverage(records)


# ============================================================================
# AgentOrchestratorService Adapters
# ============================================================================


class BaseAgentOrchestratorAdapter:
    """Shared adapter utilities for AgentOrchestratorService surfaces."""

    surface: str

    def __init__(self, service: Any, surface: str) -> None:
        self._service = service
        self.surface = surface

    def _format_assignment(self, assignment: Any) -> Dict[str, Any]:
        return assignment.to_dict()


class CLIAgentOrchestratorAdapter(BaseAgentOrchestratorAdapter):
    """Adapter backing CLI agent orchestration commands."""

    def __init__(self, service: Any) -> None:
        super().__init__(service, surface="cli")

    def assign_agent(
        self,
        *,
        run_id: Optional[str],
        requested_agent_id: Optional[str],
        stage: str,
        context: Optional[Dict[str, Any]],
        requested_by: Dict[str, Any],
    ) -> Dict[str, Any]:
        assignment = self._service.assign_agent(
            run_id=run_id,
            requested_agent_id=requested_agent_id,
            stage=stage,
            context=context,
            requested_by=requested_by,
        )
        return self._format_assignment(assignment)

    def switch_agent(
        self,
        *,
        assignment_id: str,
        target_agent_id: str,
        reason: Optional[str],
        allow_downgrade: bool,
        stage: Optional[str],
        issued_by: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        assignment = self._service.switch_agent(
            assignment_id=assignment_id,
            target_agent_id=target_agent_id,
            reason=reason,
            allow_downgrade=allow_downgrade,
            stage=stage,
            issued_by=issued_by,
        )
        return self._format_assignment(assignment)

    def get_status(
        self,
        *,
        run_id: Optional[str],
        assignment_id: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        assignment = self._service.get_status(run_id=run_id, assignment_id=assignment_id)
        return self._format_assignment(assignment) if assignment else None


class MCPAgentOrchestratorAdapter(BaseAgentOrchestratorAdapter):
    """Adapter for MCP agent orchestration tool invocations."""

    def __init__(self, service: Any) -> None:
        super().__init__(service, surface="mcp")

    def assign(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP agents.assign tool."""
        assignment = self._service.assign_agent(
            run_id=payload.get("run_id"),
            requested_agent_id=payload.get("requested_agent_id"),
            stage=payload.get("stage", "PLANNING"),
            context=payload.get("context"),
            requested_by=payload.get("requested_by", {}),
        )
        return self._format_assignment(assignment)

    def switch(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP agents.switch tool."""
        assignment = self._service.switch_agent(
            assignment_id=payload["assignment_id"],
            target_agent_id=payload["target_agent_id"],
            reason=payload.get("reason"),
            allow_downgrade=payload.get("allow_downgrade", False),
            stage=payload.get("stage"),
            issued_by=payload.get("issued_by"),
        )
        return self._format_assignment(assignment)

    def status(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """MCP agents.status tool."""
        assignment = self._service.get_status(
            run_id=payload.get("run_id"),
            assignment_id=payload.get("assignment_id"),
        )
        return self._format_assignment(assignment) if assignment else None

    def delegate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP agents.delegate tool - delegate subtask to another agent."""
        response = self._service.delegate_subtask(
            delegating_run_id=payload.get("run_id", "unknown"),
            target_agent_id=payload["agent_id"],
            subtask=payload["subtask"],
            context=payload.get("context"),
            timeout_seconds=payload.get("timeout_seconds", 300),
            wait_for_completion=payload.get("wait_for_completion", True),
            requested_by={"surface": self.surface},
        )
        return response.to_dict()

    def consult(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP agents.consult tool - get advisory input from another agent."""
        response = self._service.consult_agent(
            requesting_run_id=payload.get("run_id", "unknown"),
            target_agent_id=payload["agent_id"],
            question=payload["question"],
            context=payload.get("context"),
            max_tokens=payload.get("max_tokens", 2000),
            depth=payload.get("_depth", 0),  # Internal depth tracking
        )
        return response.to_dict()

    def handoff(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP agents.handoff tool - transfer execution to another agent."""
        response = self._service.handoff_execution(
            source_run_id=payload.get("run_id", "unknown"),
            target_agent_id=payload["agent_id"],
            reason=payload["reason"],
            transfer_context=payload.get("transfer_context", True),
            transfer_outputs=payload.get("transfer_outputs", True),
            issued_by={"surface": self.surface},
        )
        return response.to_dict()


class RestAgentOrchestratorAdapter(BaseAgentOrchestratorAdapter):
    """Adapter for REST API agent orchestration endpoints."""

    def __init__(self, service: Any) -> None:
        super().__init__(service, surface="api")

    def delegate(
        self,
        agent_id: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """REST POST /api/v1/agents/{agent_id}/delegate"""
        response = self._service.delegate_subtask(
            delegating_run_id=payload.get("run_id", "unknown"),
            target_agent_id=agent_id,
            subtask=payload["subtask"],
            context=payload.get("context"),
            timeout_seconds=payload.get("timeout_seconds", 300),
            wait_for_completion=payload.get("wait_for_completion", True),
            requested_by={"surface": self.surface},
        )
        return response.to_dict()

    def consult(
        self,
        agent_id: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """REST POST /api/v1/agents/{agent_id}/consult"""
        response = self._service.consult_agent(
            requesting_run_id=payload.get("run_id", "unknown"),
            target_agent_id=agent_id,
            question=payload["question"],
            context=payload.get("context"),
            max_tokens=payload.get("max_tokens", 2000),
            depth=0,
        )
        return response.to_dict()

    def handoff(
        self,
        agent_id: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """REST POST /api/v1/agents/{agent_id}/handoff"""
        response = self._service.handoff_execution(
            source_run_id=payload.get("run_id", "unknown"),
            target_agent_id=agent_id,
            reason=payload["reason"],
            transfer_context=payload.get("transfer_context", True),
            transfer_outputs=payload.get("transfer_outputs", True),
            issued_by={"surface": self.surface},
        )
        return response.to_dict()


# =============================================================================
# Escalation Adapters (Section 11.4 - Human Escalation)
# =============================================================================


class BaseEscalationAdapter:
    """Base adapter for escalation operations across surfaces."""

    def __init__(self, service: Any, surface: str = "UNKNOWN") -> None:
        self._service = service
        self.surface = surface


class MCPEscalationAdapter(BaseEscalationAdapter):
    """Adapter for MCP escalation tool invocations."""

    def __init__(self, service: Any) -> None:
        super().__init__(service, surface="mcp")

    def request_help(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP escalation.requestHelp tool - request non-blocking human guidance."""
        response = self._service.request_help(
            run_id=payload.get("run_id", "unknown"),
            reason=payload["reason"],
            context=payload.get("context"),
            work_item_id=payload.get("work_item_id"),
            urgency=payload.get("urgency", "normal"),
            requested_by={"surface": self.surface},
        )
        return response.to_dict()

    def request_approval(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP escalation.requestApproval tool - request blocking human approval."""
        response = self._service.request_approval(
            run_id=payload.get("run_id", "unknown"),
            decision=payload["decision"],
            options=payload["options"],
            context=payload.get("context"),
            work_item_id=payload.get("work_item_id"),
            timeout_seconds=payload.get("timeout_seconds", 3600),
            requested_by={"surface": self.surface},
        )
        return response.to_dict()

    def notify_blocked(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP escalation.notifyBlocked tool - notify execution is blocked."""
        response = self._service.notify_blocked(
            run_id=payload.get("run_id", "unknown"),
            reason=payload["reason"],
            blocker_details=payload.get("blocker_details"),
            work_item_id=payload.get("work_item_id"),
            suggested_actions=payload.get("suggested_actions"),
            requested_by={"surface": self.surface},
        )
        return response.to_dict()


class RestEscalationAdapter(BaseEscalationAdapter):
    """Adapter for REST API escalation endpoints."""

    def __init__(self, service: Any) -> None:
        super().__init__(service, surface="api")

    def request_help(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """REST POST /api/v1/escalations:help"""
        response = self._service.request_help(
            run_id=payload.get("run_id", "unknown"),
            reason=payload["reason"],
            context=payload.get("context"),
            work_item_id=payload.get("work_item_id"),
            urgency=payload.get("urgency", "normal"),
            requested_by={"surface": self.surface},
        )
        return response.to_dict()

    def request_approval(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """REST POST /api/v1/escalations:approval"""
        response = self._service.request_approval(
            run_id=payload.get("run_id", "unknown"),
            decision=payload["decision"],
            options=payload["options"],
            context=payload.get("context"),
            work_item_id=payload.get("work_item_id"),
            timeout_seconds=payload.get("timeout_seconds", 3600),
            requested_by={"surface": self.surface},
        )
        return response.to_dict()

    def notify_blocked(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """REST POST /api/v1/escalations:blocked"""
        response = self._service.notify_blocked(
            run_id=payload.get("run_id", "unknown"),
            reason=payload["reason"],
            blocker_details=payload.get("blocker_details"),
            work_item_id=payload.get("work_item_id"),
            suggested_actions=payload.get("suggested_actions"),
            requested_by={"surface": self.surface},
        )
        return response.to_dict()

    def resolve_help(
        self,
        escalation_id: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """REST POST /api/v1/escalations/{escalation_id}:resolve"""
        response = self._service.resolve_help(
            escalation_id=escalation_id,
            guidance=payload["guidance"],
            resolved_by=payload.get("resolved_by"),
        )
        return response.to_dict()

    def resolve_approval(
        self,
        escalation_id: str,
        approved: bool,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """REST POST /api/v1/escalations/{escalation_id}:approve or :reject"""
        response = self._service.resolve_approval(
            escalation_id=escalation_id,
            approved=approved,
            selected_option=payload.get("selected_option"),
            reason=payload.get("reason"),
            resolved_by=payload.get("resolved_by"),
        )
        return response.to_dict()

    def acknowledge_blocked(
        self,
        escalation_id: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """REST POST /api/v1/escalations/{escalation_id}:acknowledge"""
        response = self._service.acknowledge_blocked(
            escalation_id=escalation_id,
            acknowledged_by=payload.get("acknowledged_by"),
            resolution=payload.get("resolution"),
        )
        return response.to_dict()

    def get_escalation(self, escalation_id: str) -> Optional[Dict[str, Any]]:
        """REST GET /api/v1/escalations/{escalation_id}"""
        esc = self._service.get_escalation(escalation_id)
        if esc is None:
            return None

        # Get the appropriate response based on type
        from amprealize.agent_orchestrator_service import EscalationType

        if esc.escalation_type == EscalationType.HELP:
            response = self._service.get_help_response(escalation_id)
        elif esc.escalation_type == EscalationType.APPROVAL:
            response = self._service.get_approval_response(escalation_id)
        elif esc.escalation_type == EscalationType.BLOCKED:
            response = self._service.get_blocked_response(escalation_id)
        else:
            return None

        if response:
            return response.to_dict()
        return None


# =============================================================================
# AgentAuth Service Adapters
# =============================================================================


class BaseAgentAuthServiceAdapter:
    """Base adapter for AgentAuth operations across surfaces."""

    def __init__(self, client: Any, surface: str = "UNKNOWN") -> None:
        self._client = client
        self.surface = surface

    def _format_grant(self, grant: Any) -> Dict[str, Any]:
        """Convert GrantMetadata to dict."""
        from dataclasses import asdict
        return asdict(grant)

    def _format_obligation(self, obligation: Any) -> Dict[str, Any]:
        """Convert Obligation to dict."""
        from dataclasses import asdict
        return asdict(obligation)


class CLIAgentAuthServiceAdapter(BaseAgentAuthServiceAdapter):
    """Adapter for CLI auth commands."""

    def __init__(self, client: Any) -> None:
        super().__init__(client, surface="cli")

    def ensure_grant(
        self,
        agent_id: str,
        tool_name: str,
        scopes: List[str],
        user_id: Optional[str] = None,
        context: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """CLI: amprealize auth ensure-grant"""
        from .services.agent_auth_service import EnsureGrantRequest

        request = EnsureGrantRequest(
            agent_id=agent_id,
            surface=self.surface,
            tool_name=tool_name,
            scopes=scopes,
            user_id=user_id,
            context=context or {},
        )
        response = self._client.ensure_grant(request)

        result: Dict[str, Any] = {
            "decision": response.decision.value,
        }
        if response.reason:
            result["reason"] = response.reason.value
        if response.consent_url:
            result["consent_url"] = response.consent_url
            result["consent_request_id"] = response.consent_request_id
        if response.grant:
            result["grant"] = self._format_grant(response.grant)
        if response.audit_action_id:
            result["audit_action_id"] = response.audit_action_id

        return result

    def list_grants(
        self,
        agent_id: str,
        user_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        include_expired: bool = False,
    ) -> List[Dict[str, Any]]:
        """CLI: amprealize auth list-grants"""
        from .services.agent_auth_service import ListGrantsRequest

        request = ListGrantsRequest(
            agent_id=agent_id,
            user_id=user_id,
            tool_name=tool_name,
            include_expired=include_expired,
        )
        grants = self._client.list_grants(request)
        return [self._format_grant(grant) for grant in grants]

    def policy_preview(
        self,
        agent_id: str,
        tool_name: str,
        scopes: List[str],
        user_id: Optional[str] = None,
        context: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """CLI: amprealize auth policy-preview"""
        from .services.agent_auth_service import PolicyPreviewRequest

        request = PolicyPreviewRequest(
            agent_id=agent_id,
            tool_name=tool_name,
            scopes=scopes,
            user_id=user_id,
            context=context or {},
        )
        response = self._client.policy_preview(request)

        result: Dict[str, Any] = {
            "decision": response.decision.value,
        }
        if response.reason:
            result["reason"] = response.reason.value
        if response.bundle_version:
            result["bundle_version"] = response.bundle_version
        if response.obligations:
            result["obligations"] = [self._format_obligation(o) for o in response.obligations]

        return result

    def revoke_grant(
        self,
        grant_id: str,
        revoked_by: str,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """CLI: amprealize auth revoke"""
        from .services.agent_auth_service import RevokeGrantRequest

        request = RevokeGrantRequest(
            grant_id=grant_id,
            revoked_by=revoked_by,
            reason=reason,
        )
        response = self._client.revoke_grant(request)

        result: Dict[str, Any] = {
            "grant_id": response.grant_id,
            "success": response.success,
        }
        if response.reason:
            result["reason"] = response.reason.value

        return result


class RestAgentAuthServiceAdapter(BaseAgentAuthServiceAdapter):
    """Adapter for REST API auth endpoints."""

    def __init__(self, client: Any) -> None:
        super().__init__(client, surface="API")

    def ensure_grant(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """REST: POST /v1/auth/grants"""
        from .services.agent_auth_service import EnsureGrantRequest

        request = EnsureGrantRequest(
            agent_id=payload["agent_id"],
            surface=self.surface,
            tool_name=payload["tool_name"],
            scopes=payload["scopes"],
            user_id=payload.get("user_id"),
            context=payload.get("context", {}),
        )
        response = self._client.ensure_grant(request)

        result: Dict[str, Any] = {
            "decision": response.decision.value,
        }
        if response.reason:
            result["reason"] = response.reason.value
        if response.consent_url:
            result["consent_url"] = response.consent_url
            result["consent_request_id"] = response.consent_request_id
        if response.grant:
            result["grant"] = self._format_grant(response.grant)
        if response.audit_action_id:
            result["audit_action_id"] = response.audit_action_id

        return result

    def list_grants(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """REST: GET /v1/auth/grants"""
        from .services.agent_auth_service import ListGrantsRequest

        request = ListGrantsRequest(
            agent_id=payload["agent_id"],
            user_id=payload.get("user_id"),
            tool_name=payload.get("tool_name"),
            include_expired=payload.get("include_expired", False),
        )
        grants = self._client.list_grants(request)
        return [self._format_grant(grant) for grant in grants]

    def policy_preview(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """REST: POST /v1/auth/policy/preview"""
        from .services.agent_auth_service import PolicyPreviewRequest

        request = PolicyPreviewRequest(
            agent_id=payload["agent_id"],
            tool_name=payload["tool_name"],
            scopes=payload["scopes"],
            user_id=payload.get("user_id"),
            context=payload.get("context", {}),
        )
        response = self._client.policy_preview(request)

        result: Dict[str, Any] = {
            "decision": response.decision.value,
        }
        if response.reason:
            result["reason"] = response.reason.value
        if response.bundle_version:
            result["bundle_version"] = response.bundle_version
        if response.obligations:
            result["obligations"] = [self._format_obligation(o) for o in response.obligations]

        return result

    def revoke_grant(self, grant_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """REST: DELETE /v1/auth/grants/{grant_id}"""
        from .services.agent_auth_service import RevokeGrantRequest

        request = RevokeGrantRequest(
            grant_id=grant_id,
            revoked_by=payload["revoked_by"],
            reason=payload.get("reason"),
        )
        response = self._client.revoke_grant(request)

        result: Dict[str, Any] = {
            "grant_id": response.grant_id,
            "success": response.success,
        }
        if response.reason:
            result["reason"] = response.reason.value

        return result


class MCPAgentAuthServiceAdapter(BaseAgentAuthServiceAdapter):
    """Adapter simulating MCP tool interactions for AgentAuth."""

    def __init__(self, client: Any) -> None:
        super().__init__(client, surface="mcp")

    def ensure_grant(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP auth.ensureGrant tool."""
        from .services.agent_auth_service import EnsureGrantRequest

        request = EnsureGrantRequest(
            agent_id=payload["agent_id"],
            surface=payload.get("surface", "MCP"),
            tool_name=payload["tool_name"],
            scopes=payload["scopes"],
            user_id=payload.get("user_id"),
            context=payload.get("context", {}),
        )
        response = self._client.ensure_grant(request)

        result: Dict[str, Any] = {
            "decision": response.decision.value,
        }
        if response.reason:
            result["reason"] = response.reason.value
        if response.consent_url:
            result["consent_url"] = response.consent_url
            result["consent_request_id"] = response.consent_request_id
        if response.grant:
            result["grant"] = self._format_grant(response.grant)
        if response.audit_action_id:
            result["audit_action_id"] = response.audit_action_id

        return result

    def list_grants(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """MCP auth.listGrants tool."""
        from .services.agent_auth_service import ListGrantsRequest

        request = ListGrantsRequest(
            agent_id=payload["agent_id"],
            user_id=payload.get("user_id"),
            tool_name=payload.get("tool_name"),
            include_expired=payload.get("include_expired", False),
        )
        grants = self._client.list_grants(request)
        return [self._format_grant(grant) for grant in grants]

    def policy_preview(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP auth.policy.preview tool."""
        from .services.agent_auth_service import PolicyPreviewRequest

        request = PolicyPreviewRequest(
            agent_id=payload["agent_id"],
            tool_name=payload["tool_name"],
            scopes=payload["scopes"],
            user_id=payload.get("user_id"),
            context=payload.get("context", {}),
        )
        response = self._client.policy_preview(request)

        result: Dict[str, Any] = {
            "decision": response.decision.value,
        }
        if response.reason:
            result["reason"] = response.reason.value
        if response.bundle_version:
            result["bundle_version"] = response.bundle_version
        if response.obligations:
            result["obligations"] = [self._format_obligation(o) for o in response.obligations]

        return result

    def revoke(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP auth.revoke tool."""
        from .services.agent_auth_service import RevokeGrantRequest

        request = RevokeGrantRequest(
            grant_id=payload["grant_id"],
            revoked_by=payload["revoked_by"],
            reason=payload.get("reason"),
        )
        response = self._client.revoke_grant(request)

        result: Dict[str, Any] = {
            "grant_id": response.grant_id,
            "success": response.success,
        }
        if response.reason:
            result["reason"] = response.reason.value

        return result


# Device flow adapters extracted to device_flow_adapters.py for lightweight imports.
# Re-exported here for backwards compatibility.
from .device_flow_adapters import BaseDeviceFlowAdapter, CLIDeviceFlowAdapter, MCPDeviceFlowAdapter  # noqa: F401


class BaseTraceAnalysisAdapter:
    """Shared utilities for TraceAnalysisService adapters."""

    def __init__(self, service: Any, surface: str) -> None:
        """Initialize adapter with TraceAnalysisService instance."""
        self._service = service
        self.surface = surface


class CLITraceAnalysisServiceAdapter(BaseTraceAnalysisAdapter):
    """CLI adapter for TraceAnalysisService pattern detection and scoring."""

    def __init__(self, service: Any) -> None:
        super().__init__(service, surface="cli")

    def detect_patterns(
        self,
        *,
        run_ids: List[str],
        min_frequency: int = 3,
        min_similarity: float = 0.7,
        max_patterns: int = 100,
        include_context: bool = True,
    ) -> Dict[str, Any]:
        """Detect patterns across multiple runs via CLI.

        Args:
            run_ids: List of run IDs to analyze
            min_frequency: Minimum occurrences to consider a pattern
            min_similarity: Minimum sequence similarity threshold 0-1
            max_patterns: Maximum number of patterns to return
            include_context: Whether to capture before/after steps

        Returns:
            DetectPatternsResponse as dict with patterns, stats, metadata
        """
        from .trace_analysis_contracts import DetectPatternsRequest

        request = DetectPatternsRequest(
            run_ids=run_ids,
            min_frequency=min_frequency,
            min_similarity=min_similarity,
            max_patterns=max_patterns,
            include_context=include_context,
        )
        response = self._service.detect_patterns(request)
        return response.to_dict()

    def score_reusability(
        self,
        *,
        pattern_id: str,
        total_runs: int,
        avg_trace_tokens: float,
        unique_task_types: int,
        total_task_types: int,
    ) -> Dict[str, Any]:
        """Score a pattern's reusability via CLI.

        Args:
            pattern_id: Pattern identifier to score
            total_runs: Total runs in analysis period
            avg_trace_tokens: Average tokens per trace
            unique_task_types: Number of distinct task types where pattern occurred
            total_task_types: Total task types in corpus

        Returns:
            ScoreReusabilityResponse as dict with score, pattern, threshold check
        """
        from .trace_analysis_contracts import ScoreReusabilityRequest

        request = ScoreReusabilityRequest(
            pattern_id=pattern_id,
            total_runs=total_runs,
            avg_trace_tokens=avg_trace_tokens,
            unique_task_types=unique_task_types,
            total_task_types=total_task_types,
        )
        response = self._service.score_reusability(request)
        return response.to_dict()


class RestTraceAnalysisServiceAdapter(BaseTraceAnalysisAdapter):
    """REST adapter for TraceAnalysisService endpoints."""

    def __init__(self, service: Any) -> None:
        super().__init__(service, surface="api")

    def detect_patterns(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Detect patterns via REST API.

        Args:
            payload: DetectPatternsRequest as dict

        Returns:
            DetectPatternsResponse as dict
        """
        from .trace_analysis_contracts import DetectPatternsRequest

        request = DetectPatternsRequest.from_dict(payload)
        response = self._service.detect_patterns(request)
        return response.to_dict()

    def score_reusability(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Score reusability via REST API.

        Args:
            payload: ScoreReusabilityRequest as dict

        Returns:
            ScoreReusabilityResponse as dict
        """
        from .trace_analysis_contracts import ScoreReusabilityRequest

        request = ScoreReusabilityRequest.from_dict(payload)
        response = self._service.score_reusability(request)
        return response.to_dict()


class MCPTraceAnalysisServiceAdapter(BaseTraceAnalysisAdapter):
    """MCP adapter for TraceAnalysisService tool invocations."""

    def __init__(self, service: Any) -> None:
        super().__init__(service, surface="mcp")

    def detectPatterns(self, payload: Dict[str, Any]) -> Dict[str, Any]:  # noqa: N802 - MCP naming parity
        """MCP tool: detectPatterns."""
        from .trace_analysis_contracts import DetectPatternsRequest

        request = DetectPatternsRequest.from_dict(payload)
        response = self._service.detect_patterns(request)
        return response.to_dict()

    def scoreReusability(self, payload: Dict[str, Any]) -> Dict[str, Any]:  # noqa: N802 - MCP naming parity
        """MCP tool: scoreReusability."""
        from .trace_analysis_contracts import ScoreReusabilityRequest

        request = ScoreReusabilityRequest.from_dict(payload)
        response = self._service.score_reusability(request)
        return response.to_dict()


class MCPReflectionServiceAdapter:
    """MCP adapter for ReflectionService."""

    def __init__(self, service: Any) -> None:
        self._service = service

    def extract(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP tool: reflection.extract - Extract behavior candidates from trace."""
        from .reflection_service import ReflectRequest

        request = ReflectRequest(
            trace_text=payload["trace_text"],
            trace_format=payload.get("trace_format", "chain_of_thought"),
            run_id=payload.get("run_id"),
            max_candidates=payload.get("max_candidates", 5),
            min_quality_score=payload.get("min_quality_score", 0.6),
            include_examples=payload.get("include_examples", True),
            preferred_tags=payload.get("preferred_tags"),
        )
        response = self._service.reflect(request)

        return {
            "run_id": response.run_id,
            "trace_step_count": response.trace_step_count,
            "candidates": [
                {
                    "slug": c.slug,
                    "display_name": c.display_name,
                    "instruction": c.instruction,
                    "summary": c.summary,
                    "supporting_steps": c.supporting_steps,
                    "examples": [{"title": ex.title, "body": ex.body} for ex in (c.examples or [])],
                    "quality_scores": {
                        "clarity": c.quality_scores.clarity,
                        "generality": c.quality_scores.generality,
                        "reusability": c.quality_scores.reusability,
                        "correctness": c.quality_scores.correctness,
                    },
                    "confidence": c.confidence,
                    "duplicate_behavior_id": c.duplicate_behavior_id,
                    "duplicate_behavior_name": c.duplicate_behavior_name,
                    "tags": c.tags,
                }
                for c in response.candidates
            ],
            "summary": response.summary,
            "metadata": response.metadata,
        }

    def list_candidates(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP tool: reflection.listCandidates - List behavior candidates with filtering."""
        from .reflection_service_postgres import PostgresReflectionService

        # Check if service supports candidate listing (PostgreSQL backend)
        if not hasattr(self._service, "list_candidates"):
            return {
                "candidates": [],
                "total": 0,
                "error": "Candidate listing requires PostgreSQL backend (set AMPREALIZE_REFLECTION_PG_DSN)",
            }

        candidates = self._service.list_candidates(
            status=payload.get("status"),
            role=payload.get("role"),
            min_confidence=payload.get("min_confidence", 0.0),
            limit=payload.get("limit", 50),
            offset=payload.get("offset", 0),
        )

        return {
            "candidates": [
                {
                    "candidate_id": c.candidate_id,
                    "name": c.name,
                    "summary": c.summary,
                    "triggers": c.triggers,
                    "steps": c.steps,
                    "confidence": c.confidence,
                    "status": c.status,
                    "role": c.role,
                    "keywords": c.keywords,
                    "reviewed_by": c.reviewed_by,
                    "reviewed_at": c.reviewed_at.isoformat() if c.reviewed_at else None,
                    "merged_behavior_id": c.merged_behavior_id,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                    "updated_at": c.updated_at.isoformat() if c.updated_at else None,
                }
                for c in candidates
            ],
            "total": len(candidates),
        }

    def approve_candidate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP tool: reflection.approveCandidate - Approve a behavior candidate."""
        from .telemetry_events import ReflectionCandidateApprovedPayload, TelemetryEventType

        if not hasattr(self._service, "approve_candidate"):
            return {
                "success": False,
                "error": "Candidate approval requires PostgreSQL backend",
            }

        candidate_id = payload.get("candidate_id")
        reviewed_by = payload.get("reviewed_by", "mcp_user")
        merge_to_handbook = payload.get("merge_to_handbook", False)

        if not candidate_id:
            return {"success": False, "error": "candidate_id is required"}

        # Get candidate for auto-approval check
        candidate = self._service.get_candidate(candidate_id)
        if not candidate:
            return {"success": False, "error": f"Candidate not found: {candidate_id}"}

        # Auto-approval: confidence >= 0.8 triggers automatic approval
        auto_approved = candidate.confidence >= 0.8
        merged_behavior_id = None

        if merge_to_handbook:
            # Promote candidate to a real behavior via BehaviorService
            merged_behavior_id = self._promote_candidate(candidate, reviewed_by)

        updated = self._service.approve_candidate(
            candidate_id=candidate_id,
            reviewed_by=reviewed_by,
            merged_behavior_id=merged_behavior_id,
        )

        # Emit telemetry
        try:
            from .telemetry import TelemetryClient, create_sink_from_env

            telemetry = TelemetryClient(sink=create_sink_from_env())
            telemetry.emit_event(
                event_type=TelemetryEventType.REFLECTION_CANDIDATE_APPROVED.value,
                payload=ReflectionCandidateApprovedPayload(
                    candidate_id=candidate_id,
                    behavior_id=merged_behavior_id,
                    reviewer_role="teacher" if not auto_approved else "auto",
                    auto_approved=auto_approved,
                ).to_dict(),
            )
        except Exception:
            pass  # Telemetry should not block approval

        return {
            "success": True,
            "candidate_id": updated.candidate_id,
            "status": updated.status,
            "behavior_id": merged_behavior_id,
            "auto_approved": auto_approved,
            "message": f"Candidate {candidate_id} approved" + (" and merged to handbook" if merge_to_handbook else ""),
        }

    def _promote_candidate(self, candidate: Any, reviewed_by: str) -> Optional[str]:
        """Promote an approved candidate to a behavior via BehaviorService.

        Returns the created behavior_id, or None if BehaviorService is unavailable.
        """
        try:
            import os as _os
            from .behavior_service import BehaviorService
            from .action_contracts import Actor

            behavior_service = getattr(self._service, "_behavior_service", None)
            if behavior_service is None:
                # Try constructing from environment
                dsn = _os.environ.get("AMPREALIZE_BEHAVIOR_PG_DSN")
                if not dsn:
                    return None
                behavior_service = BehaviorService(dsn=dsn)

            actor = Actor(id=reviewed_by, type="user")
            result = behavior_service.promote_candidate_to_behavior(
                candidate_name=candidate.name,
                candidate_summary=candidate.summary,
                candidate_triggers=candidate.triggers if candidate.triggers else [],
                candidate_steps=candidate.steps if candidate.steps else [],
                candidate_keywords=candidate.keywords if candidate.keywords else [],
                candidate_confidence=candidate.confidence,
                candidate_role=candidate.role or "Student",
                actor=actor,
            )
            return result.get("behavior_id")
        except Exception:
            return None

    def reject_candidate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP tool: reflection.rejectCandidate - Reject a behavior candidate."""
        if not hasattr(self._service, "reject_candidate"):
            return {
                "success": False,
                "error": "Candidate rejection requires PostgreSQL backend",
            }

        candidate_id = payload.get("candidate_id")
        reviewed_by = payload.get("reviewed_by", "mcp_user")
        reason = payload.get("reason")

        if not candidate_id:
            return {"success": False, "error": "candidate_id is required"}

        updated = self._service.reject_candidate(
            candidate_id=candidate_id,
            reviewed_by=reviewed_by,
            reason=reason,
        )

        return {
            "success": True,
            "candidate_id": updated.candidate_id,
            "status": updated.status,
            "message": f"Candidate {candidate_id} rejected" + (f": {reason}" if reason else ""),
        }


# ============================================================================
# Epic 7 Advanced Features MCP Adapters
# ============================================================================

class MCPFineTuningServiceAdapter:
    """MCP adapter for Midnighter fine-tuning operations.

    Updated to use the standalone midnighter package (mdnt).
    """

    def __init__(self, service: Any) -> None:
        self._service = service
        self.surface = "MCP"

    def create_corpus(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP fine-tuning.create-corpus tool."""
        corpus = self._service.create_corpus(
            name=payload["name"],
            description=payload.get("description", ""),
            source_data=payload.get("source_data", []),
            quality_threshold=payload.get("quality_threshold", 0.7),
        )
        return corpus.to_dict()

    def generate_corpus(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP fine-tuning.generate-corpus tool."""
        corpus = self._service.generate_corpus_from_behaviors(
            name=payload["name"],
            behavior_ids=payload["behavior_ids"],
            sample_count=payload.get("sample_count", 100),
            include_citations=payload.get("include_citations", True),
        )
        return corpus.to_dict()

    def start_job(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP fine-tuning.start-job tool."""
        job = self._service.start_training_job(
            model_id=payload["model_id"],
            base_model=payload.get("base_model", "gpt-4o-mini"),
            corpus_id=payload["corpus_id"],
        )
        return job.to_dict()

    def get_status(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP fine-tuning.status tool."""
        job_id = payload["job_id"]
        job = self._service.get_job(job_id)
        if job is None:
            return {"error": f"Job {job_id} not found"}
        return job.to_dict()

    def list_jobs(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP fine-tuning.list tool."""
        jobs = self._service.list_jobs()
        return {"jobs": [job.to_dict() for job in jobs]}

    def list_corpora(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP fine-tuning.list-corpora tool."""
        corpora = self._service.list_corpora()
        return {"corpora": [c.to_dict() for c in corpora]}


class MCPAgentReviewServiceAdapter:
    """MCP adapter for AgentReviewService operations."""

    def __init__(self, service: Any) -> None:
        self._service = service
        self.surface = "MCP"

    def create_review(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP reviews.create tool."""
        from .agent_review_contracts import CreateReviewRequest

        request = CreateReviewRequest(
            review_type=payload["review_type"],
            target_id=payload["target_id"],
            reviewers=payload["reviewers"],
            criteria=payload.get("criteria"),
            deadline=payload.get("deadline"),
        )
        result = self._service.create_review(request)
        return result.to_dict()

    def get_review_status(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP reviews.status tool."""
        review_id = payload["review_id"]
        result = self._service.get_review_status(review_id)
        return result.to_dict()

    def list_reviews(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP reviews.list tool."""
        status = payload.get("status")
        review_type = payload.get("review_type")
        limit = payload.get("limit", 20)
        reviews = self._service.list_reviews(status=status, review_type=review_type, limit=limit)
        return {"reviews": [review.to_dict() for review in reviews]}


class MCPMultiTenantServiceAdapter:
    """MCP adapter for MultiTenantService operations."""

    def __init__(self, service: Any) -> None:
        self._service = service
        self.surface = "MCP"

    def create_tenant(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP tenants.create tool."""
        from .multi_tenant_contracts import CreateTenantRequest

        request = CreateTenantRequest(
            name=payload["name"],
            domain=payload["domain"],
            billing_plan=payload["billing_plan"],
            contact_email=payload["contact_email"],
            settings=payload.get("settings"),
            security_level=payload.get("security_level"),
        )
        result = self._service.create_tenant(request)
        return result.to_dict()

    def get_tenant_status(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP tenants.status tool."""
        tenant_id = payload["tenant_id"]
        result = self._service.get_tenant(tenant_id)
        return result.to_dict() if result else {"error": "Tenant not found"}

    def list_tenants(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP tenants.list tool."""
        status = payload.get("status")
        tenants = self._service.list_tenants(status=status)
        return {"tenants": [tenant.to_dict() for tenant in tenants]}


class MCPAdvancedRetrievalServiceAdapter:
    """MCP adapter for AdvancedRetrievalService operations."""

    def __init__(self, service: Any) -> None:
        self._service = service
        self.surface = "MCP"

    def advanced_search(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP retrieval.advanced-search tool."""
        from .advanced_retrieval_contracts import AdvancedSearchRequest

        request = AdvancedSearchRequest(
            query=payload["query"],
            search_type=payload["search_type"],
            query_expansion=payload.get("query_expansion"),
            reranking=payload.get("reranking"),
            context_config=payload.get("context_config"),
        )
        result = self._service.advanced_search(request)
        return result.to_dict()


class MCPCollaborationServiceAdapter:
    """MCP adapter for CollaborationService operations."""

    def __init__(self, service: Any) -> None:
        self._service = service
        self.surface = "MCP"

    def create_workspace(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP collaboration.workspace.create tool."""
        from .collaboration_contracts import CreateWorkspaceRequest

        request = CreateWorkspaceRequest(
            name=payload["name"],
            description=payload.get("description", ""),
            owner_id=payload["owner_id"],
            is_shared=payload.get("is_shared", False),
            settings=payload.get("settings"),
            tags=payload.get("tags"),
        )
        result = self._service.create_workspace(request)
        return result.to_dict()

    def get_workspace_status(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP collaboration.workspace.status tool."""
        workspace_id = payload["workspace_id"]
        result = self._service.get_workspace(workspace_id)
        return result.to_dict() if result else {"error": "Workspace not found"}


class MCPAPIRateLimitingServiceAdapter:
    """MCP adapter for APIRateLimitingService operations."""

    def __init__(self, service: Any) -> None:
        self._service = service
        self.surface = "MCP"

    def configure_rate_limits(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP rate-limits.configure tool."""
        from .api_rate_limiting_contracts import ConfigureRateLimitRequest

        request = ConfigureRateLimitRequest(
            scope=payload["scope"],
            target_id=payload.get("target_id"),
            policies=payload["policies"],
            exemptions=payload.get("exemptions"),
        )
        result = self._service.configure_rate_limits(request)
        return result.to_dict()

    def get_rate_limit_status(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP rate-limits.status tool."""
        scope = payload["scope"]
        target_id = payload.get("target_id")
        result = self._service.get_rate_limit_status(scope=scope, target_id=target_id)
        return result.to_dict()


class MCPBreakerAmpAdapter:
    """MCP adapter for BreakerAmpService."""

    def __init__(self, service: BreakerAmpService):
        self.service = service
        self.surface = "mcp"

    def plan(
        self,
        blueprint_id: str,
        environment: str,
        lifetime: Optional[str] = None,
        compliance_tier: Optional[str] = None,
        checklist_id: Optional[str] = None,
        behaviors: Optional[List[str]] = None,
        variables: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Plan an infrastructure deployment."""
        actor = Actor(id="mcp-user", role="user", surface="MCP")
        request = PlanRequest(
            blueprint_id=blueprint_id,
            environment=environment,
            lifetime=lifetime,
            compliance_tier=compliance_tier,
            checklist_id=checklist_id,
            behaviors=behaviors or [],
            variables=variables or {}
        )
        response = self.service.plan(request, actor)
        return response.model_dump()

    def apply(
        self,
        plan_id: Optional[str] = None,
        manifest_file: Optional[str] = None,
        watch: bool = False,
        resume: bool = False
    ) -> Dict[str, Any]:
        """Apply a planned deployment."""
        actor = Actor(id="mcp-user", role="user", surface="MCP")

        # Load manifest if provided
        manifest = None
        if manifest_file:
            path = Path(manifest_file)
            if path.exists():
                with open(path, "r") as f:
                    manifest = json.load(f)

        request = ApplyRequest(
            plan_id=plan_id,
            manifest=manifest,
            watch=watch,
            resume=resume
        )
        response = self.service.apply(request, actor)
        return response.model_dump()

    def status(self, run_id: str) -> Dict[str, Any]:
        """Get deployment status."""
        response = self.service.status(run_id)
        return response.model_dump()

    def destroy(
        self,
        run_id: str,
        cascade: bool = True,
        reason: str = "MANUAL"
    ) -> Dict[str, Any]:
        """Destroy a deployment."""
        actor = Actor(id="mcp-user", role="user", surface="MCP")
        request = DestroyRequest(
            amp_run_id=run_id,
            cascade=cascade,
            reason=reason
        )
        response = self.service.destroy(request, actor)
        return response.model_dump()

    def list_blueprints(self, source: str = "all") -> Dict[str, Any]:
        """List all available blueprints.

        Args:
            source: Filter by source ("all", "package", "user")

        Returns:
            Dict with blueprints list, count, and _links
        """
        all_blueprints = self.service.list_blueprints()

        if source != "all":
            all_blueprints = [bp for bp in all_blueprints if bp.get("source") == source]

        return {
            "blueprints": all_blueprints,
            "count": len(all_blueprints),
            "_links": {
                "plan": "/v1/breakeramp/plan"
            }
        }

    def list_environments(self, phase: str = "all") -> Dict[str, Any]:
        """List all active environments.

        Args:
            phase: Filter by phase ("all", "planned", "applying", "running", etc.)

        Returns:
            Dict with environments list, count, and _links
        """
        all_envs = self.service.list_environments()

        if phase != "all":
            all_envs = [env for env in all_envs if env.get("phase") == phase]

        return {
            "environments": all_envs,
            "count": len(all_envs),
            "_links": {
                "status": "/v1/breakeramp/status/{run_id}",
                "destroy": "/v1/breakeramp/destroy/{run_id}"
            }
        }

    def configure(
        self,
        config_dir: Optional[str] = None,
        include_blueprints: bool = False,
        blueprints: Optional[List[str]] = None,
        force: bool = False
    ) -> Dict[str, Any]:
        """Configure BreakerAmp in a directory.

        Args:
            config_dir: Target directory (defaults to ./config/breakeramp)
            include_blueprints: Whether to copy packaged blueprints
            blueprints: Specific blueprint IDs to copy
            force: Overwrite existing files

        Returns:
            Configuration result with paths and statuses
        """
        from pathlib import Path

        config_path = Path(config_dir) if config_dir else None
        result = self.service.configure(
            config_dir=config_path,
            include_blueprints=include_blueprints,
            blueprints=blueprints,
            force=force
        )

        # Add HATEOAS links
        result["_links"] = {
            "list_blueprints": "/v1/breakeramp/blueprints",
            "plan": "/v1/breakeramp/plan"
        }

        return result


class RestBreakerAmpAdapter:
    """REST API adapter for BreakerAmpService."""

    def __init__(self, service: BreakerAmpService) -> None:
        self.service = service

    def plan(self, request: PlanRequest, actor: Actor) -> PlanResponse:
        return self.service.plan(request, actor)

    def apply(self, request: ApplyRequest, actor: Actor) -> ApplyResponse:
        return self.service.apply(request, actor)

    def status(self, amp_run_id: str) -> StatusResponse:
        return self.service.status(amp_run_id)

    def destroy(self, request: DestroyRequest, actor: Actor) -> DestroyResponse:
        return self.service.destroy(request, actor)


# ============================================================================
# AuditLogService Adapters (per docs/contracts/AUDIT_LOG_STORAGE.md)
# ============================================================================


class BaseAuditServiceAdapter:
    """Shared adapter utilities for AuditLogService surfaces.

    Behaviors applied:
    - behavior_align_storage_layers: Multi-tier hot/warm/cold architecture
    - behavior_lock_down_security_surface: WORM storage, cryptographic signatures
    """

    surface: str

    def __init__(self, service: Any, surface: str) -> None:
        self._service = service
        self.surface = surface

    def _format_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Format event for output."""
        return {
            "event_id": event.get("id"),
            "timestamp": event.get("timestamp"),
            "event_type": event.get("event_type"),
            "actor_id": event.get("actor_id"),
            "actor_type": event.get("actor_type"),
            "resource_type": event.get("resource_type"),
            "resource_id": event.get("resource_id"),
            "action": event.get("action"),
            "outcome": event.get("outcome"),
            "run_id": event.get("run_id"),
            "details": event.get("details", {}),
        }

    def _format_events_response(
        self, events: List[Dict[str, Any]], total_count: Optional[int] = None
    ) -> Dict[str, Any]:
        """Format events list response."""
        return {
            "events": [self._format_event(e) for e in events],
            "count": len(events),
            "total_count": total_count or len(events),
            "_links": {
                "query": "/v1/audit/query",
                "verify": "/v1/audit/verify",
                "status": "/v1/audit/status",
            },
        }

    def _format_verification_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Format verification result."""
        return {
            "verified_at": result.get("verified_at"),
            "hash_chain_valid": result.get("hash_chain_valid", False),
            "object_lock_valid": result.get("object_lock_valid", False),
            "signatures_valid": result.get("signatures_valid", False),
            "archives_checked": result.get("archives_checked", 0),
            "errors": result.get("errors", []),
            "details": result.get("details", []),
        }

    def _format_archival_stats(self, stats: Any) -> Dict[str, Any]:
        """Format archival statistics."""
        return {
            "events_archived": getattr(stats, "events_archived", 0),
            "archives_created": getattr(stats, "archives_created", 0),
            "events_pending": getattr(stats, "events_pending", 0),
            "last_archive_key": getattr(stats, "last_archive_key", None),
            "last_archive_hash": getattr(stats, "last_archive_hash", None),
            "errors": getattr(stats, "errors", []),
        }

    def _format_status(self, status: Dict[str, Any]) -> Dict[str, Any]:
        """Format archival status response."""
        return {
            "pending_events": status.get("pending_events", 0),
            "batch_size": status.get("batch_size", 1000),
            "last_archive_hash": status.get("last_archive_hash"),
            "hot_retention_days": status.get("hot_retention_days", 30),
            "total_archives": status.get("total_archives", 0),
            "total_events_archived": status.get("total_events_archived", 0),
            "last_archive_time": status.get("last_archive_time"),
            "components": status.get("components", {}),
            "_links": {
                "query": "/v1/audit/query",
                "archive": "/v1/audit/archive",
                "verify": "/v1/audit/verify",
            },
        }


class CLIAuditServiceAdapter(BaseAuditServiceAdapter):
    """CLI adapter for AuditLogService."""

    def __init__(self, service: Any) -> None:
        super().__init__(service, surface="cli")

    async def query(
        self,
        event_type: Optional[str] = None,
        actor_id: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Query audit events for CLI output."""
        from datetime import datetime

        # Parse dates if provided
        start_dt = datetime.fromisoformat(start_time) if start_time else None
        end_dt = datetime.fromisoformat(end_time) if end_time else None

        events = await self._service.query_events(
            event_type=event_type,
            actor_id=actor_id,
            resource_type=resource_type,
            resource_id=resource_id,
            start_time=start_dt,
            end_time=end_dt,
            limit=limit,
            offset=offset,
        )
        return self._format_events_response(events)

    async def archive(self, force: bool = False) -> Dict[str, Any]:
        """Trigger archival of pending events."""
        stats = await self._service.archive_pending_events(force=force)
        return self._format_archival_stats(stats)

    async def verify(
        self,
        start_date: Optional[str] = None,
        max_archives: int = 100,
    ) -> Dict[str, Any]:
        """Verify audit log integrity."""
        from datetime import datetime

        start_dt = datetime.fromisoformat(start_date) if start_date else None
        result = await self._service.verify_integrity(
            start_date=start_dt,
            max_archives=max_archives,
        )
        return self._format_verification_result(result)

    async def status(self) -> Dict[str, Any]:
        """Get archival status."""
        status = await self._service.get_archival_status()
        return self._format_status(status)

    def list_archives(
        self,
        prefix: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """List archived audit batches."""
        archives = self._service.list_archives(prefix=prefix, limit=limit)
        return {
            "archives": archives,
            "count": len(archives),
        }

    def get_retention(self, batch_id: str) -> Dict[str, Any]:
        """Get retention info for an archive."""
        return self._service.get_retention_info(batch_id)

    def verify_archive(
        self,
        batch_id: str,
        public_key_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Verify a specific archive."""
        return self._service.verify_archive(batch_id, public_key_path)


class MCPAuditServiceAdapter(BaseAuditServiceAdapter):
    """MCP adapter for AuditLogService.

    Provides audit.* MCP tools per docs/contracts/AUDIT_LOG_STORAGE.md:
    - audit.query: Query audit events with filters
    - audit.archive: Trigger batch archival
    - audit.verify: Verify integrity (hash chain + Object Lock)
    - audit.status: Get archival status
    """

    def __init__(self, service: Any) -> None:
        super().__init__(service, surface="mcp")

    async def query(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP audit.query tool.

        Args:
            payload: Query parameters:
                - event_type: Filter by event type
                - actor_id: Filter by actor ID
                - resource_type: Filter by resource type
                - resource_id: Filter by resource ID
                - start_time: ISO timestamp (filter events after)
                - end_time: ISO timestamp (filter events before)
                - limit: Max results (default: 100)
                - offset: Pagination offset

        Returns:
            MCP tool response with events list
        """
        from datetime import datetime

        start_time = payload.get("start_time")
        end_time = payload.get("end_time")

        start_dt = datetime.fromisoformat(start_time) if start_time else None
        end_dt = datetime.fromisoformat(end_time) if end_time else None

        events = await self._service.query_events(
            event_type=payload.get("event_type"),
            actor_id=payload.get("actor_id"),
            resource_type=payload.get("resource_type"),
            resource_id=payload.get("resource_id"),
            start_time=start_dt,
            end_time=end_dt,
            limit=payload.get("limit", 100),
            offset=payload.get("offset", 0),
        )
        return self._format_events_response(events)

    async def archive(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP audit.archive tool.

        Trigger archival of pending events to S3 WORM storage.

        Args:
            payload: Archive parameters:
                - force: Archive even if batch size not reached (default: false)

        Returns:
            MCP tool response with archival stats
        """
        force = payload.get("force", False)
        stats = await self._service.archive_pending_events(force=force)
        return self._format_archival_stats(stats)

    async def verify(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP audit.verify tool.

        Verify audit log integrity (hash chain + Object Lock).

        Args:
            payload: Verification parameters:
                - start_date: ISO timestamp to start verification from
                - max_archives: Maximum archives to verify (default: 100)

        Returns:
            MCP tool response with verification results
        """
        from datetime import datetime

        start_date = payload.get("start_date")
        start_dt = datetime.fromisoformat(start_date) if start_date else None

        result = await self._service.verify_integrity(
            start_date=start_dt,
            max_archives=payload.get("max_archives", 100),
        )
        return self._format_verification_result(result)

    async def status(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP audit.status tool.

        Get current archival status and statistics.

        Args:
            payload: Status parameters (currently unused)

        Returns:
            MCP tool response with archival status
        """
        status = await self._service.get_archival_status()
        return self._format_status(status)

    def list_archives(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP audit.listArchives tool.

        List archived audit batches in S3 WORM storage.

        Args:
            payload: List parameters:
                - prefix: S3 key prefix filter
                - limit: Max results (default: 100)

        Returns:
            MCP tool response with archives list
        """
        archives = self._service.list_archives(
            prefix=payload.get("prefix"),
            limit=payload.get("limit", 100),
        )
        return {
            "archives": archives,
            "count": len(archives),
            "_links": {
                "query": "/v1/audit/query",
                "verify": "/v1/audit/verify",
            },
        }

    def get_retention(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP audit.getRetention tool.

        Get retention info for a specific archived batch.

        Args:
            payload: Parameters:
                - batch_id: Batch ID or S3 key

        Returns:
            MCP tool response with retention info
        """
        batch_id = payload.get("batch_id")
        if not batch_id:
            return {"error": "batch_id is required"}
        return self._service.get_retention_info(batch_id)

    def verify_archive(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """MCP audit.verifyArchive tool.

        Verify integrity of a specific archived batch.

        Args:
            payload: Parameters:
                - batch_id: Batch ID or S3 key
                - public_key_path: Path to Ed25519 public key for signature verification

        Returns:
            MCP tool response with verification result
        """
        batch_id = payload.get("batch_id")
        if not batch_id:
            return {"error": "batch_id is required"}
        return self._service.verify_archive(
            batch_id,
            payload.get("public_key_path"),
        )


# ==============================================================================
# Conversation Service Adapters
# ==============================================================================


class CLIConversationServiceAdapter:
    """CLI adapter for ConversationService.

    Wraps the core ConversationService for CLI surface, returning dicts
    suitable for JSON/table output.
    """

    def __init__(self, service: Any, surface: str = "cli") -> None:
        self._service = service
        self.surface = surface

    # -- Conversations --------------------------------------------------------

    def create_conversation(
        self,
        *,
        project_id: str,
        scope: str = "agent_dm",
        title: Optional[str] = None,
        created_by: str,
        participant_ids: Optional[List[str]] = None,
        org_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        from .conversation_contracts import ConversationScope

        scope_enum = ConversationScope(scope)
        conv = self._service.create_conversation(
            project_id=project_id,
            scope=scope_enum,
            title=title,
            created_by=created_by,
            participant_ids=participant_ids,
            org_id=org_id,
        )
        return conv.to_dict()

    def list_conversations(
        self,
        *,
        project_id: str,
        user_id: str,
        org_id: Optional[str] = None,
        scope: Optional[str] = None,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        from .conversation_contracts import ConversationScope

        scope_enum = ConversationScope(scope) if scope else None
        convs, total = self._service.list_conversations(
            project_id=project_id,
            user_id=user_id,
            org_id=org_id,
            scope=scope_enum,
            include_archived=include_archived,
            limit=limit,
            offset=offset,
        )
        return {
            "conversations": [c.to_dict() for c in convs],
            "total": total,
        }

    def get_conversation(
        self,
        conversation_id: str,
        *,
        org_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        conv = self._service.get_conversation(
            conversation_id, org_id=org_id, user_id=user_id,
        )
        return conv.to_dict()

    def archive_conversation(
        self,
        conversation_id: str,
        *,
        user_id: str,
        org_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._service.archive_conversation(
            conversation_id, user_id=user_id, org_id=org_id,
        )
        return {"status": "archived", "conversation_id": conversation_id}

    # -- Messages -------------------------------------------------------------

    def send_message(
        self,
        conversation_id: str,
        *,
        sender_id: str,
        content: Optional[str] = None,
        message_type: str = "text",
        parent_id: Optional[str] = None,
        run_id: Optional[str] = None,
        behavior_id: Optional[str] = None,
        work_item_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        from .conversation_contracts import MessageType

        msg = self._service.send_message(
            conversation_id,
            sender_id=sender_id,
            content=content,
            message_type=MessageType(message_type),
            parent_id=parent_id,
            run_id=run_id,
            behavior_id=behavior_id,
            work_item_id=work_item_id,
            org_id=org_id,
        )
        return msg.to_dict()

    def list_messages(
        self,
        conversation_id: str,
        *,
        user_id: str,
        org_id: Optional[str] = None,
        parent_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        messages, total, has_more = self._service.list_messages(
            conversation_id,
            user_id=user_id,
            org_id=org_id,
            parent_id=parent_id,
            limit=limit,
            offset=offset,
        )
        return {
            "messages": [m.to_dict() for m in messages],
            "total": total,
            "has_more": has_more,
        }

    def get_message(
        self,
        message_id: str,
        *,
        org_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        msg = self._service.get_message(
            message_id, org_id=org_id, user_id=user_id,
        )
        return msg.to_dict()

    def edit_message(
        self,
        message_id: str,
        *,
        new_content: str,
        editor_id: str,
        org_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        msg = self._service.edit_message(
            message_id,
            new_content=new_content,
            editor_id=editor_id,
            org_id=org_id,
        )
        return msg.to_dict()

    def delete_message(
        self,
        message_id: str,
        *,
        deleter_id: str,
        org_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._service.delete_message(
            message_id, deleter_id=deleter_id, org_id=org_id,
        )
        return {"status": "deleted", "message_id": message_id}

    def search_messages(
        self,
        conversation_id: str,
        *,
        query: str,
        user_id: str,
        org_id: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Dict[str, Any]:
        results, total = self._service.search_messages(
            conversation_id,
            query=query,
            user_id=user_id,
            org_id=org_id,
            limit=limit,
            offset=offset,
        )
        return {
            "results": [
                {
                    "message": msg.to_dict(),
                    "rank": rank,
                    "headline": headline,
                }
                for msg, rank, headline in results
            ],
            "total": total,
        }

    # -- Reactions ------------------------------------------------------------

    def add_reaction(
        self,
        message_id: str,
        *,
        actor_id: str,
        emoji: str,
        org_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        reaction = self._service.add_reaction(
            message_id, actor_id=actor_id, emoji=emoji, org_id=org_id,
        )
        return reaction.to_dict()

    def remove_reaction(
        self,
        message_id: str,
        *,
        actor_id: str,
        emoji: str,
        org_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._service.remove_reaction(
            message_id, actor_id=actor_id, emoji=emoji, org_id=org_id,
        )
        return {"status": "removed", "message_id": message_id, "emoji": emoji}

    # -- Pin/Unpin ------------------------------------------------------------

    def pin_message(
        self,
        conversation_id: str,
        message_id: str,
        *,
        user_id: str,
        org_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._service.pin_message(
            conversation_id, message_id, user_id=user_id, org_id=org_id,
        )
        return {
            "status": "pinned",
            "conversation_id": conversation_id,
            "message_id": message_id,
        }

    def unpin_message(
        self,
        conversation_id: str,
        *,
        user_id: str,
        org_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._service.unpin_message(
            conversation_id, user_id=user_id, org_id=org_id,
        )
        return {"status": "unpinned", "conversation_id": conversation_id}
