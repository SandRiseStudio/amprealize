"""Cross-surface parity tests for the Conversation/Messaging system.

Validates that REST API, MCP tools, and CLI all expose the same set of
operations with consistent field naming and parameter constraints.

AMPREALIZE-601: Write parity tests for all conversation surfaces.
"""
import json
import os
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]


# =============================================================================
# Paths
# =============================================================================

MCP_TOOLS_DIR = Path(__file__).resolve().parent.parent / "mcp" / "tools"


# =============================================================================
# Canonical enums from conversation_contracts.py
# =============================================================================

CANONICAL_SCOPES = {"project_room", "agent_dm"}

CANONICAL_MESSAGE_TYPES = {
    "text",
    "status_card",
    "blocker_card",
    "progress_card",
    "code_block",
    "run_summary",
    "system",
}

MAX_PAGE_SIZE = 100  # ConversationService.MAX_PAGE_SIZE


# =============================================================================
# Helpers
# =============================================================================

def _load_mcp_schema(tool_name: str) -> dict:
    """Load and return an MCP tool JSON schema."""
    path = MCP_TOOLS_DIR / f"{tool_name}.json"
    assert path.exists(), f"MCP schema not found: {path}"
    return json.loads(path.read_text())


# =============================================================================
# 1. Operation coverage parity
# =============================================================================

# Operations expected across all three surfaces.
# Format: (operation, rest_exists, mcp_tool_name, cli_subcommand)
CORE_OPERATIONS = [
    ("create_conversation", True, "conversations.create", "create"),
    ("list_conversations", True, "conversations.list", "list"),
    ("get_conversation", True, "conversations.get", "get"),
    ("archive_conversation", True, "conversations.archive", "archive"),
    ("send_message", True, "messages.send", "send"),
    ("list_messages", True, "messages.list", "messages"),
    ("get_message", True, "messages.get", "get-message"),
    ("edit_message", True, "messages.edit", "edit"),
    ("delete_message", True, "messages.delete", "delete"),
    ("search_messages", True, "messages.search", "search"),
    ("add_reaction", True, "messages.addReaction", "react"),
    ("remove_reaction", True, "messages.removeReaction", "react --remove"),
]


class TestOperationCoverage:
    """Ensure all three surfaces expose the same core operations."""

    @pytest.mark.parametrize("op,rest,mcp_tool,cli_cmd", CORE_OPERATIONS)
    def test_mcp_schema_exists(self, op, rest, mcp_tool, cli_cmd):
        """Every core operation has an MCP tool schema file."""
        path = MCP_TOOLS_DIR / f"{mcp_tool}.json"
        assert path.exists(), f"Missing MCP schema for {op}: expected {path.name}"

    @pytest.mark.parametrize("op,rest,mcp_tool,cli_cmd", CORE_OPERATIONS)
    def test_mcp_handler_registered(self, op, rest, mcp_tool, cli_cmd):
        """Every core operation has a handler in the conversation_handlers registry."""
        from mcp.handlers.conversation_handlers import (
            CONVERSATION_HANDLERS,
            MESSAGE_HANDLERS,
        )
        all_handlers = {**CONVERSATION_HANDLERS, **MESSAGE_HANDLERS}
        assert mcp_tool in all_handlers, (
            f"MCP tool '{mcp_tool}' not in handler registry for operation '{op}'"
        )

    @pytest.mark.parametrize("op,rest,mcp_tool,cli_cmd", CORE_OPERATIONS)
    def test_cli_adapter_method_exists(self, op, rest, mcp_tool, cli_cmd):
        """Every core operation has a corresponding adapter method."""
        from amprealize.adapters import CLIConversationServiceAdapter
        # Map operation to adapter method name
        method_map = {
            "create_conversation": "create_conversation",
            "list_conversations": "list_conversations",
            "get_conversation": "get_conversation",
            "archive_conversation": "archive_conversation",
            "send_message": "send_message",
            "list_messages": "list_messages",
            "get_message": "get_message",
            "edit_message": "edit_message",
            "delete_message": "delete_message",
            "search_messages": "search_messages",
            "add_reaction": "add_reaction",
            "remove_reaction": "remove_reaction",
        }
        method_name = method_map[op]
        assert hasattr(CLIConversationServiceAdapter, method_name), (
            f"CLIConversationServiceAdapter missing method '{method_name}' for operation '{op}'"
        )


# =============================================================================
# 2. Enum parity – MCP schemas match canonical enums
# =============================================================================

class TestEnumParity:
    """MCP schema enum values must match conversation_contracts enums."""

    def test_scope_enum_matches(self):
        schema = _load_mcp_schema("conversations.create")
        schema_scopes = set(
            schema["inputSchema"]["properties"]["scope"]["enum"]
        )
        assert schema_scopes == CANONICAL_SCOPES, (
            f"MCP scope enum {schema_scopes} != canonical {CANONICAL_SCOPES}"
        )

    def test_message_type_enum_matches(self):
        schema = _load_mcp_schema("messages.send")
        schema_types = set(
            schema["inputSchema"]["properties"]["message_type"]["enum"]
        )
        assert schema_types == CANONICAL_MESSAGE_TYPES, (
            f"MCP message_type enum {schema_types} != canonical {CANONICAL_MESSAGE_TYPES}"
        )


# =============================================================================
# 3. Pagination limit parity
# =============================================================================

class TestPaginationParity:
    """Pagination limits in MCP schemas must not exceed service MAX_PAGE_SIZE."""

    @pytest.mark.parametrize("tool_name", [
        "messages.list",
        "conversations.list",
        "messages.search",
    ])
    def test_limit_maximum_within_service_cap(self, tool_name):
        schema = _load_mcp_schema(tool_name)
        props = schema["inputSchema"]["properties"]
        if "limit" in props:
            max_val = props["limit"].get("maximum")
            if max_val is not None:
                assert max_val <= MAX_PAGE_SIZE, (
                    f"{tool_name} limit maximum {max_val} exceeds "
                    f"service MAX_PAGE_SIZE {MAX_PAGE_SIZE}"
                )


# =============================================================================
# 4. Search result field naming parity
# =============================================================================

class TestSearchFieldParity:
    """All surfaces must use consistent field names for search results."""

    def test_mcp_search_handler_uses_rank_headline(self):
        """MCP search handler returns 'rank' and 'headline' fields."""
        import inspect
        from mcp.handlers.conversation_handlers import handle_search_messages
        source = inspect.getsource(handle_search_messages)
        assert '"rank"' in source, "MCP search handler should use 'rank' field"
        assert '"headline"' in source, "MCP search handler should use 'headline' field"
        assert '"score"' not in source, "MCP search handler should not use 'score' field"
        assert '"highlight"' not in source, "MCP search handler should not use 'highlight' field"

    def test_cli_adapter_uses_rank_headline(self):
        """CLI adapter search_messages returns 'rank' and 'headline' fields."""
        import inspect
        from amprealize.adapters import CLIConversationServiceAdapter
        source = inspect.getsource(CLIConversationServiceAdapter.search_messages)
        assert '"rank"' in source, "CLI adapter should use 'rank' field"
        assert '"headline"' in source, "CLI adapter should use 'headline' field"
        assert '"score"' not in source, "CLI adapter should not use 'score' field"
        assert '"highlight"' not in source, "CLI adapter should not use 'highlight' field"

    def test_rest_model_uses_rank_headline(self):
        """REST SearchResult Pydantic model uses 'rank' and 'headline' fields."""
        from amprealize.conversation_contracts import SearchResult
        field_names = set(SearchResult.model_fields.keys())
        assert "rank" in field_names, "SearchResult model should have 'rank' field"
        assert "headline" in field_names, "SearchResult model should have 'headline' field"
        assert "score" not in field_names, "SearchResult model should not have 'score' field"
        assert "highlight" not in field_names, "SearchResult model should not have 'highlight' field"


# =============================================================================
# 5. Pin/unpin operation parity
# =============================================================================

class TestPinUnpinParity:
    """Pin/unpin must be available on REST and CLI surfaces."""

    def test_cli_adapter_has_pin_methods(self):
        from amprealize.adapters import CLIConversationServiceAdapter
        assert hasattr(CLIConversationServiceAdapter, "pin_message")
        assert hasattr(CLIConversationServiceAdapter, "unpin_message")

    def test_service_has_pin_methods(self):
        from amprealize.services.conversation_service import ConversationService
        assert hasattr(ConversationService, "pin_message")
        assert hasattr(ConversationService, "unpin_message")


# =============================================================================
# 6. MCP schema structural consistency
# =============================================================================

class TestMcpSchemaStructure:
    """All MCP tool schemas follow the same structural pattern."""

    @pytest.mark.parametrize("tool_name", [
        "conversations.create",
        "conversations.list",
        "conversations.get",
        "conversations.archive",
        "messages.send",
        "messages.list",
        "messages.get",
        "messages.edit",
        "messages.delete",
        "messages.search",
        "messages.addReaction",
        "messages.removeReaction",
    ])
    def test_schema_has_required_fields(self, tool_name):
        schema = _load_mcp_schema(tool_name)
        assert "name" in schema, f"{tool_name} missing 'name'"
        assert "description" in schema, f"{tool_name} missing 'description'"
        assert "inputSchema" in schema, f"{tool_name} missing 'inputSchema'"
        assert schema["name"] == tool_name

    @pytest.mark.parametrize("tool_name", [
        "conversations.create",
        "conversations.list",
        "conversations.get",
        "conversations.archive",
        "messages.send",
        "messages.list",
        "messages.get",
        "messages.edit",
        "messages.delete",
        "messages.search",
        "messages.addReaction",
        "messages.removeReaction",
    ])
    def test_schema_input_is_object(self, tool_name):
        schema = _load_mcp_schema(tool_name)
        assert schema["inputSchema"]["type"] == "object"
        assert "properties" in schema["inputSchema"]
