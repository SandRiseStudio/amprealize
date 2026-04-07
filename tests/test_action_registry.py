"""Unit tests for multi-tier action registry."""

import json
import tempfile
from pathlib import Path

import pytest

from amprealize.action_registry import (
    LocalJSONActionStore,
    MultiTierActionRegistry,
    RegistryConfig,
    RegistryTier,
    create_multi_tier_registry_from_env,
)
from amprealize.action_contracts import ActionCreateRequest, Actor

# Mark all tests as unit tests that don't require infrastructure
pytestmark = pytest.mark.unit


@pytest.fixture
def temp_storage_dir():
    """Create a temporary directory for local storage tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_local_json_store_create_and_list(temp_storage_dir):
    """Test creating and listing actions in local JSON storage."""
    store = LocalJSONActionStore(storage_path=temp_storage_dir)

    request = ActionCreateRequest(
        artifact_path="test.md",
        summary="Test action",
        behaviors_cited=["behavior_test"],
        metadata={"test": "data"},
    )
    actor = Actor(id="test-user", role="STRATEGIST", surface="CLI")

    # Create action
    action = store.create_action(request, actor)
    assert action.artifact_path == "test.md"
    assert action.summary == "Test action"
    assert action.behaviors_cited == ["behavior_test"]

    # List actions
    actions = store.list_actions()
    assert len(actions) == 1
    assert actions[0].action_id == action.action_id

    # Verify JSONL persistence
    actions_file = temp_storage_dir / "actions.jsonl"
    assert actions_file.exists()

    with actions_file.open("r") as f:
        lines = f.readlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["artifact_path"] == "test.md"


def test_local_json_store_get_action(temp_storage_dir):
    """Test retrieving specific action by ID."""
    store = LocalJSONActionStore(storage_path=temp_storage_dir)

    request = ActionCreateRequest(
        artifact_path="doc.md",
        summary="Get test",
        behaviors_cited=[],
        metadata={},
    )
    actor = Actor(id="test-user", role="TEACHER", surface="CLI")

    created_action = store.create_action(request, actor)

    # Retrieve by ID
    retrieved_action = store.get_action(created_action.action_id)
    assert retrieved_action.action_id == created_action.action_id
    assert retrieved_action.artifact_path == "doc.md"

    # Try to get non-existent action
    from amprealize.action_service import ActionNotFoundError
    with pytest.raises(ActionNotFoundError):
        store.get_action("non-existent-id")


def test_local_json_store_hydrates_actor_dataclass(temp_storage_dir):
    """Ensure cached JSON actions rebuild Actor dataclasses for replays."""
    store = LocalJSONActionStore(storage_path=temp_storage_dir)

    payload = {
        "action_id": "1234",
        "timestamp": "2024-10-20T12:00:00+00:00",
        "actor": {"id": "cached", "role": "TEACHER", "surface": "CLI"},
        "artifact_path": "cached.md",
        "summary": "Cached action",
        "behaviors_cited": ["behavior_cached"],
        "metadata": {"key": "value"},
        "related_run_id": None,
        "audit_log_event_id": None,
        "checksum": "abc",
        "replay_status": "NOT_STARTED",
    }

    with (temp_storage_dir / "actions.jsonl").open("w", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")

    actions = store.list_actions()
    assert len(actions) == 1
    hydrated = actions[0]
    assert isinstance(hydrated.actor, Actor)
    assert hydrated.actor.id == "cached"
    assert hydrated.actor.surface == "cli"


def test_multi_tier_registry_single_tier(temp_storage_dir):
    """Test multi-tier registry with only local tier enabled."""
    configs = [
        RegistryConfig(
            tier=RegistryTier.LOCAL,
            enabled=True,
            storage_path=str(temp_storage_dir),
            priority=1,
        ),
        RegistryConfig(
            tier=RegistryTier.TEAM,
            enabled=False,
            priority=2,
        ),
        RegistryConfig(
            tier=RegistryTier.PLATFORM,
            enabled=False,
            priority=3,
        ),
    ]

    registry = MultiTierActionRegistry(configs)

    # Verify only local tier is enabled
    enabled = registry.get_enabled_tiers()
    assert enabled == [RegistryTier.LOCAL]

    # Create action
    request = ActionCreateRequest(
        artifact_path="multi.md",
        summary="Multi-tier test",
        behaviors_cited=["behavior_multi"],
        metadata={},
    )
    actor = Actor(id="test-user", role="STUDENT", surface="CLI")

    action = registry.create_action(request, actor)
    assert action.artifact_path == "multi.md"

    # List actions
    actions = registry.list_actions()
    assert len(actions) == 1

    # Get action
    retrieved = registry.get_action(action.action_id)
    assert retrieved.action_id == action.action_id


def test_multi_tier_registry_tier_priority(temp_storage_dir):
    """Test action resolution across multiple tiers."""
    local_dir = temp_storage_dir / "local"
    team_dir = temp_storage_dir / "team"
    local_dir.mkdir()
    team_dir.mkdir()

    configs = [
        RegistryConfig(
            tier=RegistryTier.LOCAL,
            enabled=True,
            storage_path=str(local_dir),
            priority=1,  # Highest priority
        ),
        RegistryConfig(
            tier=RegistryTier.TEAM,
            enabled=True,
            storage_path=str(team_dir),
            priority=2,
        ),
    ]

    registry = MultiTierActionRegistry(configs)

    # Create action in local tier
    request1 = ActionCreateRequest(
        artifact_path="local.md",
        summary="Local action",
        behaviors_cited=[],
        metadata={},
    )
    actor = Actor(id="test-user", role="STRATEGIST", surface="CLI")
    action1 = registry.create_action(request1, actor, tier=RegistryTier.LOCAL)

    # Create action in team tier
    request2 = ActionCreateRequest(
        artifact_path="team.md",
        summary="Team action",
        behaviors_cited=[],
        metadata={},
    )
    action2 = registry.create_action(request2, actor, tier=RegistryTier.TEAM)

    # List all actions (should aggregate from both tiers)
    all_actions = registry.list_actions()
    assert len(all_actions) == 2
    action_paths = {a.artifact_path for a in all_actions}
    assert action_paths == {"local.md", "team.md"}

    # List actions from specific tier
    local_actions = registry.list_actions(tier=RegistryTier.LOCAL)
    assert len(local_actions) == 1
    assert local_actions[0].artifact_path == "local.md"

    team_actions = registry.list_actions(tier=RegistryTier.TEAM)
    assert len(team_actions) == 1
    assert team_actions[0].artifact_path == "team.md"


def test_multi_tier_registry_default_write_tier(temp_storage_dir):
    """Test that actions write to highest priority tier by default."""
    local_dir = temp_storage_dir / "local"
    team_dir = temp_storage_dir / "team"
    local_dir.mkdir()
    team_dir.mkdir()

    configs = [
        RegistryConfig(
            tier=RegistryTier.LOCAL,
            enabled=True,
            storage_path=str(local_dir),
            priority=1,  # Highest priority - default write target
        ),
        RegistryConfig(
            tier=RegistryTier.TEAM,
            enabled=True,
            storage_path=str(team_dir),
            priority=2,
        ),
    ]

    registry = MultiTierActionRegistry(configs)

    # Create action without specifying tier (should go to LOCAL)
    request = ActionCreateRequest(
        artifact_path="default.md",
        summary="Default tier action",
        behaviors_cited=[],
        metadata={},
    )
    actor = Actor(id="test-user", role="STRATEGIST", surface="CLI")
    action = registry.create_action(request, actor)

    # Verify it was written to local tier
    local_actions = registry.list_actions(tier=RegistryTier.LOCAL)
    assert len(local_actions) == 1
    assert local_actions[0].action_id == action.action_id

    # Verify it's not in team tier
    team_actions = registry.list_actions(tier=RegistryTier.TEAM)
    assert len(team_actions) == 0


def test_create_multi_tier_registry_from_env_defaults(monkeypatch, temp_storage_dir):
    """Test environment-based registry creation with defaults."""
    # Set environment variables
    monkeypatch.setenv("AMPREALIZE_ACTION_LOCAL_ENABLED", "true")
    monkeypatch.setenv("AMPREALIZE_ACTION_LOCAL_PATH", str(temp_storage_dir))
    monkeypatch.setenv("AMPREALIZE_ACTION_TEAM_ENABLED", "false")
    monkeypatch.setenv("AMPREALIZE_ACTION_PLATFORM_ENABLED", "false")

    registry = create_multi_tier_registry_from_env()

    # Verify only local tier is enabled
    enabled = registry.get_enabled_tiers()
    assert RegistryTier.LOCAL in enabled
    assert RegistryTier.TEAM not in enabled
    assert RegistryTier.PLATFORM not in enabled


def test_multi_tier_registry_action_not_found(temp_storage_dir):
    """Test error handling when action is not found in any tier."""
    configs = [
        RegistryConfig(
            tier=RegistryTier.LOCAL,
            enabled=True,
            storage_path=str(temp_storage_dir),
            priority=1,
        ),
    ]

    registry = MultiTierActionRegistry(configs)

    from amprealize.action_service import ActionNotFoundError
    with pytest.raises(ActionNotFoundError, match="not found in any registry tier"):
        registry.get_action("non-existent-id")


def test_registry_tier_enum_values():
    """Test RegistryTier enum has expected values."""
    assert RegistryTier.LOCAL.value == "local"
    assert RegistryTier.TEAM.value == "team"
    assert RegistryTier.PLATFORM.value == "platform"

    # Test string conversion
    assert RegistryTier("local") == RegistryTier.LOCAL
    assert RegistryTier("team") == RegistryTier.TEAM
    assert RegistryTier("platform") == RegistryTier.PLATFORM
