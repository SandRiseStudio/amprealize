"""Unit tests for display-ID parsing and resolution logic.

Tests verify:
- parse_display_id() correctly parses slug-number patterns
- parse_display_id() rejects internal type prefixes, UUIDs, bare numbers
- resolve_work_item_id() dispatches to correct resolution path
"""
import uuid
import pytest

from amprealize.services.board_service import AuthorNotFoundError, BoardService, parse_display_id

pytestmark = pytest.mark.unit

# =============================================================================
# parse_display_id()
# =============================================================================


class TestParseDisplayId:
    """Tests for the parse_display_id utility function."""

    def test_simple_slug_number(self):
        assert parse_display_id("myproject-42") == ("myproject", 42)

    def test_slug_with_hyphens(self):
        assert parse_display_id("my-cool-project-7") == ("my-cool-project", 7)

    def test_single_char_slug(self):
        assert parse_display_id("a-1") == ("a", 1)

    def test_large_number(self):
        assert parse_display_id("proj-99999") == ("proj", 99999)

    def test_rejects_internal_type_epic(self):
        assert parse_display_id("epic-123") is None

    def test_rejects_internal_type_story(self):
        assert parse_display_id("story-5") is None

    def test_rejects_internal_type_goal(self):
        assert parse_display_id("goal-123") is None

    def test_rejects_internal_type_feature(self):
        assert parse_display_id("feature-5") is None

    def test_rejects_internal_type_task(self):
        assert parse_display_id("task-1") is None

    def test_rejects_internal_type_bug(self):
        assert parse_display_id("bug-99") is None

    def test_rejects_uuid(self):
        val = str(uuid.uuid4())
        assert parse_display_id(val) is None

    def test_rejects_bare_number(self):
        assert parse_display_id("42") is None

    def test_rejects_empty_string(self):
        assert parse_display_id("") is None

    def test_rejects_leading_zero_number(self):
        # "proj-042" — number part starts with 0, regex requires [1-9]
        assert parse_display_id("proj-042") is None

    def test_rejects_zero(self):
        assert parse_display_id("proj-0") is None

    def test_rejects_no_number(self):
        assert parse_display_id("proj-") is None

    def test_rejects_slug_starting_with_digit(self):
        assert parse_display_id("1project-42") is None

    def test_rejects_uppercase(self):
        # Regex requires lowercase
        assert parse_display_id("MyProject-42") is None

    def test_rejects_internal_short_id_format(self):
        # Internal short IDs like "task-a1b2c3d4e5f6" have hex suffix
        # These would be rejected because "task" is a reserved prefix
        assert parse_display_id("task-a1b2c3d4e5f6") is None

    def test_non_reserved_prefix_with_digits(self):
        # "myteam-42" is a valid display ID (myteam is not a reserved prefix)
        assert parse_display_id("myteam-42") == ("myteam", 42)

    def test_rejects_trailing_spaces(self):
        assert parse_display_id("proj-42 ") is None

    def test_rejects_leading_spaces(self):
        assert parse_display_id(" proj-42") is None


class _FakeCursor:
    def __init__(self, row):
        self.row = row
        self.executed: list[str] = []
        self.params: list[object] = []
        self.description = [("id",)]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def execute(self, query, params=None):
        self.executed.append(query)
        self.params.append(params)

    def fetchone(self):
        return self.row

    def fetchall(self):
        return []


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


class _FakePool:
    def __init__(self, row):
        self.cursor = _FakeCursor(row)
        self.connection = _FakeConnection(self.cursor)

    def set_tenant_context(self, conn, org_id, user_id):
        return None

    def run_query(self, *, executor, **kwargs):
        return executor(self.connection)


def test_display_id_resolution_uses_auth_projects_table():
    pool = _FakePool(("item-1",))
    service = BoardService(pool=pool)

    assert service._resolve_by_slug_and_number("guideai", 1051) == "item-1"
    assert "JOIN auth.projects p ON p.project_id = wi.project_id" in pool.cursor.executed[0]


def test_project_slug_lookup_uses_auth_projects_table():
    pool = _FakePool(("guideai",))
    service = BoardService(pool=pool)

    assert service._get_project_slug("project-1") == "guideai"
    assert "FROM auth.projects WHERE project_id = %s" in pool.cursor.executed[0]


def test_validate_user_author_uses_auth_users_id_or_email():
    pool = _FakePool((1,))
    service = BoardService(pool=pool)

    assert service.validate_author("nick.sanders.a@gmail.com", "user") is True
    assert "FROM auth.users WHERE id = %s OR email = %s" in pool.cursor.executed[0]


def test_validate_user_author_rejects_unknown_user():
    pool = _FakePool(None)
    service = BoardService(pool=pool)

    with pytest.raises(AuthorNotFoundError):
        service.validate_author("missing@example.com", "user")


def test_validate_agent_author_allows_runtime_mcp_agent_identity():
    pool = _FakePool(None)
    service = BoardService(pool=pool)

    assert service.validate_author("system", "agent") is True
    assert "FROM execution.agents WHERE agent_id = %s" in pool.cursor.executed[0]


def test_batch_lookup_casts_ids_to_uuid_array():
    pool = _FakePool(None)
    service = BoardService(pool=pool)

    result = service.get_work_items_batch(["362d561c-1e28-4a5f-8d4f-000000000001"])

    assert result == []
    assert "WHERE id = ANY(%s::uuid[])" in pool.cursor.executed[0]
    assert pool.cursor.params[0] == (["362d561c-1e28-4a5f-8d4f-000000000001"],)
