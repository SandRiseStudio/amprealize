"""Unit tests for action replay executor."""

import pytest
from pathlib import Path

from amprealize.action_replay_executor import ActionReplayExecutor, ExecutionStatus
from amprealize.action_contracts import Action, Actor

pytestmark = pytest.mark.unit


def test_executor_initialization():
    """Test executor can be initialized."""
    executor = ActionReplayExecutor()
    assert executor is not None
    assert executor._max_workers == 4


def test_dry_run_command_execution():
    """Test dry run validation for command execution."""
    executor = ActionReplayExecutor()

    action = Action(
        action_id="test-1",
        timestamp="2025-11-05T12:00:00Z",
        actor=Actor(id="test-user", role="STUDENT", surface="CLI"),
        artifact_path="test.sh",
        summary="Run test command",
        behaviors_cited=["behavior_test"],
        metadata={"command": "echo 'hello'", "action_type": "command_execution"},
    )

    result = executor._dry_run_action(action)

    assert result.status == ExecutionStatus.SUCCEEDED
    assert "DRY RUN" in result.output
    assert "echo 'hello'" in result.output
    assert result.metadata["dry_run"] is True


def test_dry_run_file_operation():
    """Test dry run validation for file operations."""
    executor = ActionReplayExecutor()

    action = Action(
        action_id="test-2",
        timestamp="2025-11-05T12:00:00Z",
        actor=Actor(id="test-user", role="STUDENT", surface="CLI"),
        artifact_path="test.py",
        summary="Create test file",
        behaviors_cited=["behavior_test"],
        metadata={"file_path": "test.py", "action_type": "file_create"},
    )

    result = executor._dry_run_action(action)

    assert result.status == ExecutionStatus.SUCCEEDED
    assert "test.py" in result.output


def test_dry_run_missing_metadata():
    """Test dry run catches missing required metadata."""
    executor = ActionReplayExecutor()

    action = Action(
        action_id="test-3",
        timestamp="2025-11-05T12:00:00Z",
        actor=Actor(id="test-user", role="STUDENT", surface="CLI"),
        artifact_path="test.sh",
        summary="Run command without metadata",
        behaviors_cited=["behavior_test"],
        metadata={"action_type": "command_execution"},  # Missing 'command'
    )

    result = executor._dry_run_action(action)

    assert result.status == ExecutionStatus.FAILED
    assert result.error is not None
    assert "Missing required metadata: command" in result.error


def test_execute_command_success(tmp_path):
    """Test successful command execution."""
    executor = ActionReplayExecutor()

    # Create a simple command that creates a file
    test_file = tmp_path / "output.txt"
    command = f"echo 'test output' > {test_file}"

    action = Action(
        action_id="test-4",
        timestamp="2025-11-05T12:00:00Z",
        actor=Actor(id="test-user", role="STUDENT", surface="CLI"),
        artifact_path="test.sh",
        summary="Create output file",
        behaviors_cited=["behavior_test"],
        metadata={"command": command, "action_type": "command_execution"},
    )

    result = executor._execute_action(action)

    assert result.status == ExecutionStatus.SUCCEEDED
    assert test_file.exists()
    assert test_file.read_text().strip() == "test output"


def test_execute_command_failure():
    """Test command execution failure."""
    executor = ActionReplayExecutor()

    action = Action(
        action_id="test-5",
        timestamp="2025-11-05T12:00:00Z",
        actor=Actor(id="test-user", role="STUDENT", surface="CLI"),
        artifact_path="test.sh",
        summary="Run failing command",
        behaviors_cited=["behavior_test"],
        metadata={"command": "exit 1", "action_type": "command_execution"},
    )

    result = executor._execute_action(action)

    assert result.status == ExecutionStatus.FAILED
    assert result.error is not None


def test_execute_file_create(tmp_path):
    """Test file creation execution."""
    executor = ActionReplayExecutor()

    test_file = tmp_path / "new_file.txt"
    content = "Hello, World!"

    action = Action(
        action_id="test-6",
        timestamp="2025-11-05T12:00:00Z",
        actor=Actor(id="test-user", role="STUDENT", surface="CLI"),
        artifact_path=str(test_file),
        summary="Create new file",
        behaviors_cited=["behavior_test"],
        metadata={
            "file_path": str(test_file),
            "content": content,
            "action_type": "file_create",
        },
    )

    result = executor._execute_action(action)

    assert result.status == ExecutionStatus.SUCCEEDED
    assert test_file.exists()
    assert test_file.read_text() == content


def test_sequential_execution():
    """Test sequential execution of multiple actions."""
    executor = ActionReplayExecutor()

    actions = [
        Action(
            action_id=f"test-seq-{i}",
            timestamp="2025-11-05T12:00:00Z",
            actor=Actor(id="test-user", role="STUDENT", surface="CLI"),
            artifact_path=f"test{i}.py",
            summary=f"Test action {i}",
            behaviors_cited=["behavior_test"],
            metadata={"action_type": "generic"},
        )
        for i in range(3)
    ]

    succeeded, failed, results = executor.execute_sequential(
        actions=actions,
        dry_run=True,
    )

    assert len(results) == 3
    assert all(r.status == ExecutionStatus.SUCCEEDED for r in results)
    # In dry run, validation passes count as succeeded
    assert len(succeeded) == 3
    assert len(failed) == 0


def test_parallel_execution():
    """Test parallel execution of multiple actions."""
    executor = ActionReplayExecutor()

    actions = [
        Action(
            action_id=f"test-par-{i}",
            timestamp="2025-11-05T12:00:00Z",
            actor=Actor(id="test-user", role="STUDENT", surface="CLI"),
            artifact_path=f"test{i}.py",
            summary=f"Test action {i}",
            behaviors_cited=["behavior_test"],
            metadata={"action_type": "generic"},
        )
        for i in range(5)
    ]

    succeeded, failed, results = executor.execute_parallel(
        actions=actions,
        dry_run=True,
    )

    assert len(results) == 5
    assert all(r.status == ExecutionStatus.SUCCEEDED for r in results)


def test_skip_existing():
    """Test skip_existing option."""
    executor = ActionReplayExecutor()

    actions = [
        Action(
            action_id="test-skip-1",
            timestamp="2025-11-05T12:00:00Z",
            actor=Actor(id="test-user", role="STUDENT", surface="CLI"),
            artifact_path="test1.py",
            summary="Already succeeded",
            behaviors_cited=["behavior_test"],
            metadata={"action_type": "generic"},
            replay_status="SUCCEEDED",
        ),
        Action(
            action_id="test-skip-2",
            timestamp="2025-11-05T12:00:00Z",
            actor=Actor(id="test-user", role="STUDENT", surface="CLI"),
            artifact_path="test2.py",
            summary="Not yet executed",
            behaviors_cited=["behavior_test"],
            metadata={"action_type": "generic"},
        ),
    ]

    succeeded, failed, results = executor.execute_sequential(
        actions=actions,
        skip_existing=True,
        dry_run=True,
    )

    assert len(results) == 2
    assert results[0].status == ExecutionStatus.SKIPPED
    assert results[1].status == ExecutionStatus.SUCCEEDED


def test_infer_action_type():
    """Test action type inference."""
    executor = ActionReplayExecutor()

    # Test command inference
    action = Action(
        action_id="test",
        timestamp="2025-11-05T12:00:00Z",
        actor=Actor(id="test-user", role="STUDENT", surface="CLI"),
        artifact_path="test.sh",
        summary="Test",
        behaviors_cited=["test"],
        metadata={"command": "echo test"},
    )
    assert executor._infer_action_type(action) == "command_execution"

    # Test file create inference
    action = Action(
        action_id="test",
        timestamp="2025-11-05T12:00:00Z",
        actor=Actor(id="test-user", role="STUDENT", surface="CLI"),
        artifact_path="test.py",
        summary="Created new file",
        behaviors_cited=["test"],
        metadata={},
    )
    assert executor._infer_action_type(action) == "file_create"

    # Test file delete inference
    action = Action(
        action_id="test",
        timestamp="2025-11-05T12:00:00Z",
        actor=Actor(id="test-user", role="STUDENT", surface="CLI"),
        artifact_path="test.py",
        summary="Deleted file",
        behaviors_cited=["test"],
        metadata={},
    )
    assert executor._infer_action_type(action) == "file_delete"
