"""Unit tests for CLI conversation commands.

Tests the argparse parsing, dispatch, and output formatting
without requiring a PostgreSQL backend by mocking the adapter.
"""
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from amprealize import cli

pytestmark = [pytest.mark.unit]


# =============================================================================
# Fixtures
# =============================================================================

def _make_conversation(
    conv_id: str = "conv-001",
    project_id: str = "proj-001",
    title: str = "Test Conversation",
    scope: str = "agent_dm",
    created_by: str = "local-cli",
) -> dict:
    return {
        "id": conv_id,
        "project_id": project_id,
        "org_id": None,
        "scope": scope,
        "title": title,
        "created_by": created_by,
        "pinned_message_id": None,
        "is_archived": False,
        "metadata": {},
        "created_at": "2025-01-15T10:00:00",
        "updated_at": "2025-01-15T10:00:00",
        "participant_count": 1,
        "unread_count": 0,
    }


def _make_message(
    msg_id: str = "msg-001",
    conv_id: str = "conv-001",
    sender_id: str = "local-cli",
    content: str = "Hello world",
) -> dict:
    return {
        "id": msg_id,
        "conversation_id": conv_id,
        "sender_id": sender_id,
        "sender_type": "user",
        "content": content,
        "message_type": "text",
        "structured_payload": None,
        "parent_id": None,
        "run_id": None,
        "behavior_id": None,
        "work_item_id": None,
        "is_edited": False,
        "edited_at": None,
        "is_deleted": False,
        "deleted_at": None,
        "metadata": {},
        "created_at": "2025-01-15T10:01:00",
        "reactions": [],
        "reply_count": 0,
    }


def _run_cli(args: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    exit_code = cli.main(args)
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


# =============================================================================
# Conversation list
# =============================================================================


@patch("amprealize.cli._get_conversation_adapter")
def test_conversation_list_json(mock_get_adapter, capsys):
    adapter = MagicMock()
    adapter.list_conversations.return_value = {
        "conversations": [_make_conversation()],
        "total": 1,
    }
    mock_get_adapter.return_value = adapter

    code, out, err = _run_cli(
        ["conversation", "list", "--project-id", "proj-001", "--format", "json"],
        capsys,
    )
    assert code == 0
    data = json.loads(out)
    assert data["total"] == 1
    assert data["conversations"][0]["id"] == "conv-001"


@patch("amprealize.cli._get_conversation_adapter")
def test_conversation_list_table(mock_get_adapter, capsys):
    adapter = MagicMock()
    adapter.list_conversations.return_value = {
        "conversations": [_make_conversation()],
        "total": 1,
    }
    mock_get_adapter.return_value = adapter

    code, out, err = _run_cli(
        ["conversation", "list", "--project-id", "proj-001"],
        capsys,
    )
    assert code == 0
    assert "conv-001" in out
    assert "Test Conversation" in out


@patch("amprealize.cli._get_conversation_adapter")
def test_conversation_list_empty(mock_get_adapter, capsys):
    adapter = MagicMock()
    adapter.list_conversations.return_value = {
        "conversations": [],
        "total": 0,
    }
    mock_get_adapter.return_value = adapter

    code, out, err = _run_cli(
        ["conversation", "list", "--project-id", "proj-001"],
        capsys,
    )
    assert code == 0
    assert "No conversations found" in out


# =============================================================================
# Conversation get
# =============================================================================


@patch("amprealize.cli._get_conversation_adapter")
def test_conversation_get_json(mock_get_adapter, capsys):
    adapter = MagicMock()
    adapter.get_conversation.return_value = _make_conversation()
    mock_get_adapter.return_value = adapter

    code, out, err = _run_cli(
        ["conversation", "get", "conv-001", "--format", "json"],
        capsys,
    )
    assert code == 0
    data = json.loads(out)
    assert data["id"] == "conv-001"


@patch("amprealize.cli._get_conversation_adapter")
def test_conversation_get_table(mock_get_adapter, capsys):
    adapter = MagicMock()
    adapter.get_conversation.return_value = _make_conversation()
    mock_get_adapter.return_value = adapter

    code, out, err = _run_cli(["conversation", "get", "conv-001"], capsys)
    assert code == 0
    assert "Conversation: conv-001" in out
    assert "Test Conversation" in out


@patch("amprealize.cli._get_conversation_adapter")
def test_conversation_get_not_found(mock_get_adapter, capsys):
    adapter = MagicMock()
    adapter.get_conversation.side_effect = Exception("Conversation conv-999 not found")
    mock_get_adapter.return_value = adapter

    code, out, err = _run_cli(["conversation", "get", "conv-999"], capsys)
    assert code == 1
    assert "Error:" in err
    assert "not found" in err


# =============================================================================
# Conversation create
# =============================================================================


@patch("amprealize.cli._get_conversation_adapter")
def test_conversation_create_json(mock_get_adapter, capsys):
    adapter = MagicMock()
    adapter.create_conversation.return_value = _make_conversation(
        title="My DM", scope="agent_dm",
    )
    mock_get_adapter.return_value = adapter

    code, out, err = _run_cli(
        [
            "conversation", "create",
            "--project-id", "proj-001",
            "--title", "My DM",
            "--format", "json",
        ],
        capsys,
    )
    assert code == 0
    data = json.loads(out)
    assert data["title"] == "My DM"
    assert data["scope"] == "agent_dm"


@patch("amprealize.cli._get_conversation_adapter")
def test_conversation_create_with_participants(mock_get_adapter, capsys):
    adapter = MagicMock()
    adapter.create_conversation.return_value = _make_conversation(
        title="Team Chat", scope="project_room",
    )
    mock_get_adapter.return_value = adapter

    code, out, err = _run_cli(
        [
            "conversation", "create",
            "--project-id", "proj-001",
            "--scope", "project_room",
            "--title", "Team Chat",
            "--participants", "user-a", "user-b",
            "--format", "json",
        ],
        capsys,
    )
    assert code == 0
    # Verify participants were passed
    call_kwargs = adapter.create_conversation.call_args[1]
    assert call_kwargs["participant_ids"] == ["user-a", "user-b"]


# =============================================================================
# Conversation archive
# =============================================================================


@patch("amprealize.cli._get_conversation_adapter")
def test_conversation_archive_default_json(mock_get_adapter, capsys):
    """archive defaults to json format."""
    adapter = MagicMock()
    adapter.archive_conversation.return_value = {
        "status": "archived",
        "conversation_id": "conv-001",
    }
    mock_get_adapter.return_value = adapter

    code, out, err = _run_cli(
        ["conversation", "archive", "conv-001"],
        capsys,
    )
    assert code == 0
    data = json.loads(out)
    assert data["status"] == "archived"


@patch("amprealize.cli._get_conversation_adapter")
def test_conversation_archive_table(mock_get_adapter, capsys):
    """archive --format table prints short confirmation."""
    adapter = MagicMock()
    adapter.archive_conversation.return_value = {
        "status": "archived",
        "conversation_id": "conv-001",
    }
    mock_get_adapter.return_value = adapter

    code, out, err = _run_cli(
        ["conversation", "archive", "conv-001", "--format", "table"],
        capsys,
    )
    assert code == 0
    assert "conv-001 archived" in out


# =============================================================================
# Conversation send
# =============================================================================


@patch("amprealize.cli._get_conversation_adapter")
def test_conversation_send_json(mock_get_adapter, capsys):
    adapter = MagicMock()
    adapter.send_message.return_value = _make_message(content="Hello!")
    mock_get_adapter.return_value = adapter

    code, out, err = _run_cli(
        ["conversation", "send", "conv-001", "Hello!", "--format", "json"],
        capsys,
    )
    assert code == 0
    data = json.loads(out)
    assert data["content"] == "Hello!"  # from fixture
    assert data["conversation_id"] == "conv-001"


@patch("amprealize.cli._get_conversation_adapter")
def test_conversation_send_table(mock_get_adapter, capsys):
    adapter = MagicMock()
    adapter.send_message.return_value = _make_message(content="Test msg")
    mock_get_adapter.return_value = adapter

    code, out, err = _run_cli(
        ["conversation", "send", "conv-001", "Test msg"],
        capsys,
    )
    assert code == 0
    assert "Message: msg-001" in out


@patch("amprealize.cli._get_conversation_adapter")
def test_conversation_send_with_options(mock_get_adapter, capsys):
    adapter = MagicMock()
    adapter.send_message.return_value = _make_message()
    mock_get_adapter.return_value = adapter

    code, out, err = _run_cli(
        [
            "conversation", "send", "conv-001", "blocker!",
            "--type", "blocker_card",
            "--parent-id", "msg-parent",
            "--run-id", "run-001",
            "--behavior-id", "beh-001",
            "--work-item-id", "wi-001",
            "--format", "json",
        ],
        capsys,
    )
    assert code == 0
    call_kwargs = adapter.send_message.call_args[1]
    assert call_kwargs["message_type"] == "blocker_card"
    assert call_kwargs["parent_id"] == "msg-parent"
    assert call_kwargs["run_id"] == "run-001"


# =============================================================================
# Conversation messages
# =============================================================================


@patch("amprealize.cli._get_conversation_adapter")
def test_conversation_messages_json(mock_get_adapter, capsys):
    adapter = MagicMock()
    adapter.list_messages.return_value = {
        "messages": [_make_message(), _make_message(msg_id="msg-002", content="Reply")],
        "total": 2,
        "has_more": False,
    }
    mock_get_adapter.return_value = adapter

    code, out, err = _run_cli(
        ["conversation", "messages", "conv-001", "--format", "json"],
        capsys,
    )
    assert code == 0
    data = json.loads(out)
    assert data["total"] == 2
    assert len(data["messages"]) == 2


@patch("amprealize.cli._get_conversation_adapter")
def test_conversation_messages_table(mock_get_adapter, capsys):
    adapter = MagicMock()
    adapter.list_messages.return_value = {
        "messages": [_make_message()],
        "total": 1,
        "has_more": False,
    }
    mock_get_adapter.return_value = adapter

    code, out, err = _run_cli(
        ["conversation", "messages", "conv-001"],
        capsys,
    )
    assert code == 0
    assert "msg-001" in out
    assert "Hello world" in out


# =============================================================================
# Conversation search
# =============================================================================


@patch("amprealize.cli._get_conversation_adapter")
def test_conversation_search_json(mock_get_adapter, capsys):
    adapter = MagicMock()
    adapter.search_messages.return_value = {
        "results": [
            {
                "message": _make_message(),
                "rank": 0.95,
                "headline": "Hello **world**",
            }
        ],
        "total": 1,
    }
    mock_get_adapter.return_value = adapter

    code, out, err = _run_cli(
        ["conversation", "search", "conv-001", "hello", "--format", "json"],
        capsys,
    )
    assert code == 0
    data = json.loads(out)
    assert data["total"] == 1
    assert data["results"][0]["rank"] == 0.95


@patch("amprealize.cli._get_conversation_adapter")
def test_conversation_search_table(mock_get_adapter, capsys):
    adapter = MagicMock()
    adapter.search_messages.return_value = {
        "results": [
            {
                "message": _make_message(),
                "rank": 0.95,
                "headline": "Hello world",
            }
        ],
        "total": 1,
    }
    mock_get_adapter.return_value = adapter

    code, out, err = _run_cli(
        ["conversation", "search", "conv-001", "hello"],
        capsys,
    )
    assert code == 0
    assert "0.950" in out


# =============================================================================
# Conversation react
# =============================================================================


@patch("amprealize.cli._get_conversation_adapter")
def test_conversation_react_add(mock_get_adapter, capsys):
    adapter = MagicMock()
    adapter.add_reaction.return_value = {
        "id": "react-001",
        "message_id": "msg-001",
        "actor_id": "local-cli",
        "actor_type": "user",
        "emoji": "thumbsup",
        "created_at": "2025-01-15T10:02:00",
    }
    mock_get_adapter.return_value = adapter

    code, out, err = _run_cli(
        ["conversation", "react", "msg-001", "thumbsup"],
        capsys,
    )
    assert code == 0
    data = json.loads(out)
    assert data["emoji"] == "thumbsup"


@patch("amprealize.cli._get_conversation_adapter")
def test_conversation_react_remove(mock_get_adapter, capsys):
    adapter = MagicMock()
    adapter.remove_reaction.return_value = {
        "status": "removed",
        "message_id": "msg-001",
        "emoji": "thumbsup",
    }
    mock_get_adapter.return_value = adapter

    code, out, err = _run_cli(
        ["conversation", "react", "msg-001", "thumbsup", "--remove"],
        capsys,
    )
    assert code == 0
    data = json.loads(out)
    assert data["status"] == "removed"


# =============================================================================
# Conversation edit
# =============================================================================


@patch("amprealize.cli._get_conversation_adapter")
def test_conversation_edit_json(mock_get_adapter, capsys):
    adapter = MagicMock()
    msg = _make_message(content="Updated content")
    msg["is_edited"] = True
    msg["edited_at"] = "2025-01-15T10:03:00"
    adapter.edit_message.return_value = msg
    mock_get_adapter.return_value = adapter

    code, out, err = _run_cli(
        ["conversation", "edit", "msg-001", "Updated content", "--format", "json"],
        capsys,
    )
    assert code == 0
    data = json.loads(out)
    assert data["is_edited"] is True


@patch("amprealize.cli._get_conversation_adapter")
def test_conversation_edit_table(mock_get_adapter, capsys):
    adapter = MagicMock()
    msg = _make_message(content="Edited msg")
    msg["is_edited"] = True
    msg["edited_at"] = "2025-01-15T10:03:00"
    adapter.edit_message.return_value = msg
    mock_get_adapter.return_value = adapter

    code, out, err = _run_cli(
        ["conversation", "edit", "msg-001", "Edited msg"],
        capsys,
    )
    assert code == 0
    # _render_message_detail shows "Edited:" line when is_edited=True
    assert "Edited:" in out
    assert "Message: msg-001" in out


# =============================================================================
# Conversation delete
# =============================================================================


@patch("amprealize.cli._get_conversation_adapter")
def test_conversation_delete_default_json(mock_get_adapter, capsys):
    """delete defaults to json format."""
    adapter = MagicMock()
    adapter.delete_message.return_value = {
        "status": "deleted",
        "message_id": "msg-001",
    }
    mock_get_adapter.return_value = adapter

    code, out, err = _run_cli(
        ["conversation", "delete", "msg-001"],
        capsys,
    )
    assert code == 0
    data = json.loads(out)
    assert data["status"] == "deleted"


@patch("amprealize.cli._get_conversation_adapter")
def test_conversation_delete_table(mock_get_adapter, capsys):
    """delete --format table prints short confirmation."""
    adapter = MagicMock()
    adapter.delete_message.return_value = {
        "status": "deleted",
        "message_id": "msg-001",
    }
    mock_get_adapter.return_value = adapter

    code, out, err = _run_cli(
        ["conversation", "delete", "msg-001", "--format", "table"],
        capsys,
    )
    assert code == 0
    assert "msg-001 deleted" in out


@patch("amprealize.cli._get_conversation_adapter")
def test_conversation_delete_error(mock_get_adapter, capsys):
    adapter = MagicMock()
    adapter.delete_message.side_effect = Exception("Message msg-999 not found")
    mock_get_adapter.return_value = adapter

    code, out, err = _run_cli(
        ["conversation", "delete", "msg-999"],
        capsys,
    )
    assert code == 1
    assert "Error:" in err
    assert "not found" in err


# =============================================================================
# Error handling
# =============================================================================


@patch("amprealize.cli._get_conversation_adapter")
def test_conversation_send_error(mock_get_adapter, capsys):
    adapter = MagicMock()
    adapter.send_message.side_effect = Exception("Not a participant")
    mock_get_adapter.return_value = adapter

    code, out, err = _run_cli(
        ["conversation", "send", "conv-001", "test"],
        capsys,
    )
    assert code == 1
    assert "Error:" in err
    assert "Not a participant" in err


# =============================================================================
# Argparse validation
# =============================================================================


def test_conversation_no_subcommand(capsys):
    """Running 'amprealize conversation' without subcommand should exit 1 and show help."""
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["conversation"])
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    # parser.print_help() outputs the usage/help text
    assert "conversation" in captured.out


# =============================================================================
# Get-message, Pin, Unpin
# =============================================================================


@patch("amprealize.cli._get_conversation_adapter")
def test_conversation_get_message(mock_get_adapter, capsys):
    adapter = MagicMock()
    adapter.get_message.return_value = _make_message()
    mock_get_adapter.return_value = adapter

    code, out, err = _run_cli(
        ["conversation", "get-message", "msg-001"],
        capsys,
    )
    assert code == 0
    data = json.loads(out)
    assert data["id"] == "msg-001"
    adapter.get_message.assert_called_once_with(
        "msg-001", user_id="local-cli", org_id=None,
    )


@patch("amprealize.cli._get_conversation_adapter")
def test_conversation_get_message_error(mock_get_adapter, capsys):
    adapter = MagicMock()
    adapter.get_message.side_effect = Exception("Message not found")
    mock_get_adapter.return_value = adapter

    code, out, err = _run_cli(
        ["conversation", "get-message", "msg-999"],
        capsys,
    )
    assert code == 1
    assert "Error:" in err
    assert "Message not found" in err


@patch("amprealize.cli._get_conversation_adapter")
def test_conversation_pin(mock_get_adapter, capsys):
    adapter = MagicMock()
    adapter.pin_message.return_value = {
        "status": "pinned",
        "conversation_id": "conv-001",
        "message_id": "msg-001",
    }
    mock_get_adapter.return_value = adapter

    code, out, err = _run_cli(
        ["conversation", "pin", "conv-001", "msg-001"],
        capsys,
    )
    assert code == 0
    data = json.loads(out)
    assert data["status"] == "pinned"
    assert data["message_id"] == "msg-001"
    adapter.pin_message.assert_called_once_with(
        "conv-001", "msg-001", user_id="local-cli", org_id=None,
    )


@patch("amprealize.cli._get_conversation_adapter")
def test_conversation_pin_error(mock_get_adapter, capsys):
    adapter = MagicMock()
    adapter.pin_message.side_effect = Exception("Access denied")
    mock_get_adapter.return_value = adapter

    code, out, err = _run_cli(
        ["conversation", "pin", "conv-001", "msg-001"],
        capsys,
    )
    assert code == 1
    assert "Error:" in err


@patch("amprealize.cli._get_conversation_adapter")
def test_conversation_unpin(mock_get_adapter, capsys):
    adapter = MagicMock()
    adapter.unpin_message.return_value = {
        "status": "unpinned",
        "conversation_id": "conv-001",
    }
    mock_get_adapter.return_value = adapter

    code, out, err = _run_cli(
        ["conversation", "unpin", "conv-001"],
        capsys,
    )
    assert code == 0
    data = json.loads(out)
    assert data["status"] == "unpinned"
    adapter.unpin_message.assert_called_once_with(
        "conv-001", user_id="local-cli", org_id=None,
    )


@patch("amprealize.cli._get_conversation_adapter")
def test_conversation_unpin_error(mock_get_adapter, capsys):
    adapter = MagicMock()
    adapter.unpin_message.side_effect = Exception("Access denied")
    mock_get_adapter.return_value = adapter

    code, out, err = _run_cli(
        ["conversation", "unpin", "conv-001"],
        capsys,
    )
    assert code == 1
    assert "Error:" in err
