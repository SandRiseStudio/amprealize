"""Multi-tier action registry for local, team, and platform action storage.

Implements the multi-tier architecture described in docs/contracts/ACTION_REGISTRY_SPEC.md:
- Local tier: JSON storage in ~/.amprealize/actions/ for developer-specific actions
- Team tier: Shared storage (filesystem/cloud) for team-wide actions
- Platform tier: PostgreSQL for platform-wide, WORM-compliant actions

Resolution order: local → team → platform (configurable)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from .action_contracts import Action, ActionCreateRequest, Actor, ReplayRequest, ReplayStatus
from .action_service import ActionService, ActionNotFoundError, ReplayNotFoundError
from .action_service_postgres import PostgresActionService
from .telemetry import TelemetryClient


class RegistryTier(str, Enum):
    """Registry tier identifiers."""
    LOCAL = "local"
    TEAM = "team"
    PLATFORM = "platform"


@dataclass
class RegistryConfig:
    """Configuration for a registry tier."""
    tier: RegistryTier
    enabled: bool
    storage_path: Optional[str] = None  # For local/team JSON storage
    dsn: Optional[str] = None  # For PostgreSQL platform storage
    priority: int = 0  # Lower number = higher priority in resolution order


class ActionStorageBackend(Protocol):
    """Protocol for action storage implementations."""

    def create_action(self, request: ActionCreateRequest, actor: Actor) -> Action:
        """Create and store an action."""
        ...

    def list_actions(self) -> List[Action]:
        """List all actions."""
        ...

    def get_action(self, action_id: str) -> Action:
        """Retrieve a specific action."""
        ...

    def replay_actions(self, request: ReplayRequest, actor: Actor) -> ReplayStatus:
        """Replay a set of actions."""
        ...

    def get_replay_status(self, replay_id: str) -> ReplayStatus:
        """Get replay job status."""
        ...


class LocalJSONActionStore:
    """Local JSON-based action storage for developer-specific actions."""

    def __init__(self, storage_path: Optional[Path] = None, telemetry: Optional[TelemetryClient] = None):
        self.storage_path = storage_path or Path.home() / ".amprealize" / "actions"
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.actions_file = self.storage_path / "actions.jsonl"
        self.replays_file = self.storage_path / "replays.jsonl"
        self._telemetry = telemetry or TelemetryClient.noop()

    def create_action(self, request: ActionCreateRequest, actor: Actor) -> Action:
        """Create action and append to JSONL file."""
        # Delegate to in-memory service for action creation
        service = ActionService(telemetry=self._telemetry)
        action = service.create_action(request, actor)

        # Persist to JSONL
        with self.actions_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(action.to_dict()) + "\n")

        return action

    def list_actions(self) -> List[Action]:
        """Load all actions from JSONL file."""
        if not self.actions_file.exists():
            return []

        actions = []
        with self.actions_file.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    actions.append(self._dict_to_action(data))
        return actions

    def get_action(self, action_id: str) -> Action:
        """Find action by ID in JSONL file."""
        for action in self.list_actions():
            if action.action_id == action_id:
                return action
        raise ActionNotFoundError(f"Action '{action_id}' not found in local registry")

    def replay_actions(self, request: ReplayRequest, actor: Actor) -> ReplayStatus:
        """Replay actions using in-memory service."""
        service = ActionService(telemetry=self._telemetry)
        # Load actions into service
        for action in self.list_actions():
            if action.action_id in request.action_ids:
                service._actions[action.action_id] = action

        replay = service.replay_actions(request, actor)

        # Persist replay status
        with self.replays_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(replay.to_dict()) + "\n")

        return replay

    def get_replay_status(self, replay_id: str) -> ReplayStatus:
        """Find replay status in JSONL file."""
        if not self.replays_file.exists():
            raise ReplayNotFoundError(f"Replay '{replay_id}' not found")

        with self.replays_file.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    if data.get("replay_id") == replay_id:
                        return self._dict_to_replay_status(data)

        raise ReplayNotFoundError(f"Replay '{replay_id}' not found in local registry")

    @staticmethod
    def _dict_to_action(data: Dict[str, Any]) -> Action:
        """Convert dictionary to Action object."""
        return Action.from_dict(data)

    @staticmethod
    def _dict_to_replay_status(data: Dict[str, Any]) -> ReplayStatus:
        """Convert dictionary to ReplayStatus object."""
        return ReplayStatus(
            replay_id=data["replay_id"],
            status=data["status"],
            progress=data.get("progress", 0.0),
            logs=data.get("logs", []),
            failed_action_ids=data.get("failed_action_ids", []),
            action_ids=data.get("action_ids", []),
            completed_action_ids=data.get("completed_action_ids", []),
            audit_log_event_id=data.get("audit_log_event_id"),
            strategy=data.get("strategy", "SEQUENTIAL"),
            created_at=data.get("created_at"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            actor_id=data.get("actor_id"),
            actor_role=data.get("actor_role"),
            actor_surface=data.get("actor_surface"),
        )


class MultiTierActionRegistry:
    """Multi-tier action registry with configurable resolution order."""

    def __init__(self, configs: List[RegistryConfig], telemetry: Optional[TelemetryClient] = None):
        self.configs = sorted(configs, key=lambda c: c.priority)
        self.backends: Dict[RegistryTier, ActionStorageBackend] = {}
        self._telemetry = telemetry or TelemetryClient.noop()
        self._initialize_backends()

    def _initialize_backends(self) -> None:
        """Initialize storage backends for enabled tiers."""
        for config in self.configs:
            if not config.enabled:
                continue

            if config.tier == RegistryTier.LOCAL:
                storage_path = Path(config.storage_path) if config.storage_path else None
                self.backends[config.tier] = LocalJSONActionStore(storage_path, self._telemetry)

            elif config.tier == RegistryTier.TEAM:
                # Team tier uses shared JSON storage
                if config.storage_path:
                    storage_path = Path(config.storage_path)
                    self.backends[config.tier] = LocalJSONActionStore(storage_path, self._telemetry)

            elif config.tier == RegistryTier.PLATFORM:
                # Platform tier uses PostgreSQL
                if config.dsn:
                    self.backends[config.tier] = PostgresActionService(dsn=config.dsn, telemetry=self._telemetry)
                else:
                    # Fallback to in-memory for testing
                    self.backends[config.tier] = ActionService(telemetry=self._telemetry)

    def create_action(
        self,
        request: ActionCreateRequest,
        actor: Actor,
        tier: Optional[RegistryTier] = None,
    ) -> Action:
        """Create action in specified tier (default: first enabled tier)."""
        target_tier = tier or self._get_default_write_tier()
        backend = self.backends.get(target_tier)

        if not backend:
            raise ValueError(f"Registry tier '{target_tier}' is not enabled or configured")

        action = backend.create_action(request, actor)

        self._telemetry.emit_event(
            event_type="action_created_in_tier",
            payload={
                "tier": target_tier.value,
                "action_id": action.action_id,
                "artifact_path": action.artifact_path,
            },
            actor={"id": actor.id, "role": actor.role, "surface": actor.surface},
            action_id=action.action_id,
        )

        return action

    def list_actions(self, tier: Optional[RegistryTier] = None) -> List[Action]:
        """List actions from specified tier or all tiers."""
        if tier:
            backend = self.backends.get(tier)
            if not backend:
                return []
            return backend.list_actions()

        # Aggregate from all tiers
        all_actions = []
        seen_ids = set()

        for config in self.configs:
            if config.tier not in self.backends:
                continue

            backend = self.backends[config.tier]
            for action in backend.list_actions():
                if action.action_id not in seen_ids:
                    all_actions.append(action)
                    seen_ids.add(action.action_id)

        return all_actions

    def get_action(self, action_id: str, tier: Optional[RegistryTier] = None) -> Action:
        """Get action from specified tier or search all tiers."""
        if tier:
            backend = self.backends.get(tier)
            if not backend:
                raise ActionNotFoundError(f"Registry tier '{tier}' is not enabled")
            return backend.get_action(action_id)

        # Search all tiers in priority order
        for config in self.configs:
            if config.tier not in self.backends:
                continue

            try:
                backend = self.backends[config.tier]
                return backend.get_action(action_id)
            except ActionNotFoundError:
                continue

        raise ActionNotFoundError(f"Action '{action_id}' not found in any registry tier")

    def replay_actions(
        self,
        request: ReplayRequest,
        actor: Actor,
        tier: Optional[RegistryTier] = None,
    ) -> ReplayStatus:
        """Replay actions from specified tier."""
        target_tier = tier or self._get_default_write_tier()
        backend = self.backends.get(target_tier)

        if not backend:
            raise ValueError(f"Registry tier '{target_tier}' is not enabled")

        return backend.replay_actions(request, actor)

    def get_replay_status(self, replay_id: str, tier: Optional[RegistryTier] = None) -> ReplayStatus:
        """Get replay status from specified tier or search all tiers."""
        if tier:
            backend = self.backends.get(tier)
            if not backend:
                raise ReplayNotFoundError(f"Registry tier '{tier}' is not enabled")
            return backend.get_replay_status(replay_id)

        # Search all tiers
        for config in self.configs:
            if config.tier not in self.backends:
                continue

            try:
                backend = self.backends[config.tier]
                return backend.get_replay_status(replay_id)
            except ReplayNotFoundError:
                continue

        raise ReplayNotFoundError(f"Replay '{replay_id}' not found in any registry tier")

    def get_enabled_tiers(self) -> List[RegistryTier]:
        """Return list of enabled registry tiers."""
        return [config.tier for config in self.configs if config.enabled]

    def _get_default_write_tier(self) -> RegistryTier:
        """Get the default tier for write operations (highest priority enabled tier)."""
        for config in self.configs:
            if config.enabled and config.tier in self.backends:
                return config.tier
        raise ValueError("No enabled registry tiers configured")


def create_multi_tier_registry_from_env(telemetry: Optional[TelemetryClient] = None) -> MultiTierActionRegistry:
    """Create multi-tier registry from environment variables.

    Environment variables:
    - AMPREALIZE_ACTION_LOCAL_ENABLED=true|false (default: true)
    - AMPREALIZE_ACTION_LOCAL_PATH=/path/to/local/actions (default: ~/.amprealize/actions)
    - AMPREALIZE_ACTION_TEAM_ENABLED=true|false (default: false)
    - AMPREALIZE_ACTION_TEAM_PATH=/path/to/team/actions
    - AMPREALIZE_ACTION_PLATFORM_ENABLED=true|false (default: true if DSN set)
    - AMPREALIZE_ACTION_PLATFORM_DSN=postgresql://... (default: from AMPREALIZE_ACTIONS_PG_DSN)
    """
    configs = []

    # Local tier (highest priority by default)
    local_enabled = os.environ.get("AMPREALIZE_ACTION_LOCAL_ENABLED", "true").lower() == "true"
    local_path = os.environ.get("AMPREALIZE_ACTION_LOCAL_PATH")
    configs.append(RegistryConfig(
        tier=RegistryTier.LOCAL,
        enabled=local_enabled,
        storage_path=local_path,
        priority=1,
    ))

    # Team tier
    team_enabled = os.environ.get("AMPREALIZE_ACTION_TEAM_ENABLED", "false").lower() == "true"
    team_path = os.environ.get("AMPREALIZE_ACTION_TEAM_PATH")
    configs.append(RegistryConfig(
        tier=RegistryTier.TEAM,
        enabled=team_enabled and bool(team_path),
        storage_path=team_path,
        priority=2,
    ))

    # Platform tier (lowest priority)
    platform_dsn = os.environ.get("AMPREALIZE_ACTION_PLATFORM_DSN") or os.environ.get("AMPREALIZE_ACTIONS_PG_DSN")
    platform_enabled = os.environ.get("AMPREALIZE_ACTION_PLATFORM_ENABLED", str(bool(platform_dsn))).lower() == "true"
    configs.append(RegistryConfig(
        tier=RegistryTier.PLATFORM,
        enabled=platform_enabled,
        dsn=platform_dsn,
        priority=3,
    ))

    return MultiTierActionRegistry(configs, telemetry)
