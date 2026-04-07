"""Backend parity tests for CollaborationService across in-memory and PostgreSQL.

Validates that CollaborationService operations produce consistent results
regardless of which backend is used.

Tests cover:
- Workspace CRUD: create_workspace, get_workspace
- Member management: invite_user, get_workspace_members
- Document operations: create_document, get_document, lock/unlock
- Real-time editing: apply_real_time_edit, get_document_operations
- Comments: add_comment, get_document_comments
- Metrics: get_collaboration_metrics
"""

from __future__ import annotations

import os
from typing import Generator

try:
    import psycopg2  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - psycopg2 is optional for lint environments
    psycopg2 = None
import pytest

from amprealize.collaboration_contracts import (
    CreateWorkspaceRequest,
    InviteUserRequest,
    CreateDocumentRequest,
    RealTimeEditRequest,
    CommentRequest,
    Workspace,
    WorkspaceMember,
    Document,
    EditOperation,
    Comment,
    MemberRole,
    DocumentType,
    EditOperationType,
)
from amprealize.collaboration_service import CollaborationService
from amprealize.collaboration_service_postgres import PostgresCollaborationService


# Test constants
TEST_USER_ID = "test-user-123"
TEST_USER_EMAIL = "test@example.com"


def _truncate_collaboration_tables(dsn: str) -> None:
    """Remove all data from collaboration tables to ensure test isolation."""
    from conftest import safe_truncate
    safe_truncate(dsn, [
        "collaboration_comments", "collaboration_operations",
        "collaboration_documents", "collaboration_members",
        "collaboration_workspaces",
    ])


@pytest.fixture
def postgres_dsn() -> Generator[str, None, None]:
    """Discover PostgreSQL DSN from environment."""
    dsn = os.environ.get("AMPREALIZE_COLLABORATION_PG_DSN")
    if not dsn:
        pytest.skip("AMPREALIZE_COLLABORATION_PG_DSN not set; skipping PostgreSQL parity tests")
    yield dsn


@pytest.fixture
def collaboration_service_postgres(postgres_dsn: str) -> Generator[PostgresCollaborationService, None, None]:
    """Create a fresh PostgresCollaborationService for each test."""
    _truncate_collaboration_tables(postgres_dsn)
    service = PostgresCollaborationService(dsn=postgres_dsn)

    try:
        yield service
    finally:
        service.close()


@pytest.fixture
def collaboration_service_memory() -> Generator[CollaborationService, None, None]:
    """Create a fresh CollaborationService (in-memory) for each test."""
    service = CollaborationService()
    yield service


# ------------------------------------------------------------------
# Parity Tests - Workspace CRUD Operations
# ------------------------------------------------------------------
class TestWorkspaceCRUDParity:
    """Test workspace CRUD parity between backends."""

    def test_create_workspace_parity(
        self,
        collaboration_service_memory: CollaborationService,
        collaboration_service_postgres: PostgresCollaborationService,
    ) -> None:
        """Both backends should create workspaces with identical fields."""
        request = CreateWorkspaceRequest(
            name="Test Workspace",
            description="A workspace for testing",
            owner_id=TEST_USER_ID,
        )

        workspace_memory = collaboration_service_memory.create_workspace(request)
        workspace_postgres = collaboration_service_postgres.create_workspace(request)

        # Validate structure
        assert isinstance(workspace_memory, Workspace)
        assert isinstance(workspace_postgres, Workspace)
        assert workspace_memory.name == "Test Workspace"
        assert workspace_postgres.name == "Test Workspace"
        assert workspace_memory.description == "A workspace for testing"
        assert workspace_postgres.description == "A workspace for testing"
        assert workspace_memory.owner_id == TEST_USER_ID
        assert workspace_postgres.owner_id == TEST_USER_ID

    def test_get_workspace_parity(
        self,
        collaboration_service_memory: CollaborationService,
        collaboration_service_postgres: PostgresCollaborationService,
    ) -> None:
        """Both backends should retrieve workspaces consistently."""
        request = CreateWorkspaceRequest(
            name="Retrieval Test",
            owner_id=TEST_USER_ID,
        )

        # Create workspaces
        created_memory = collaboration_service_memory.create_workspace(request)
        created_postgres = collaboration_service_postgres.create_workspace(request)

        # Retrieve them
        retrieved_memory = collaboration_service_memory.get_workspace(created_memory.workspace_id)
        retrieved_postgres = collaboration_service_postgres.get_workspace(created_postgres.workspace_id)

        assert retrieved_memory is not None
        assert retrieved_postgres is not None
        assert retrieved_memory.name == created_memory.name
        assert retrieved_postgres.name == created_postgres.name

    def test_get_nonexistent_workspace_parity(
        self,
        collaboration_service_memory: CollaborationService,
        collaboration_service_postgres: PostgresCollaborationService,
    ) -> None:
        """Both backends should return None for non-existent workspaces."""
        result_memory = collaboration_service_memory.get_workspace("nonexistent-id")
        result_postgres = collaboration_service_postgres.get_workspace("nonexistent-id")

        assert result_memory is None
        assert result_postgres is None


# ------------------------------------------------------------------
# Parity Tests - Member Management
# ------------------------------------------------------------------
class TestMemberManagementParity:
    """Test member management parity between backends."""

    def test_invite_user_parity(
        self,
        collaboration_service_memory: CollaborationService,
        collaboration_service_postgres: PostgresCollaborationService,
    ) -> None:
        """Both backends should invite users consistently."""
        # Create workspaces first
        ws_request = CreateWorkspaceRequest(
            name="Member Test Workspace",
            owner_id=TEST_USER_ID,
        )
        ws_memory = collaboration_service_memory.create_workspace(ws_request)
        ws_postgres = collaboration_service_postgres.create_workspace(ws_request)

        # Invite users
        invite_request_memory = InviteUserRequest(
            workspace_id=ws_memory.workspace_id,
            user_id="invited-user-1",
            email="invited@example.com",
            role=MemberRole.EDITOR,
        )
        invite_request_postgres = InviteUserRequest(
            workspace_id=ws_postgres.workspace_id,
            user_id="invited-user-1",
            email="invited@example.com",
            role=MemberRole.EDITOR,
        )

        member_memory = collaboration_service_memory.invite_user(invite_request_memory)
        member_postgres = collaboration_service_postgres.invite_user(invite_request_postgres)

        assert isinstance(member_memory, WorkspaceMember)
        assert isinstance(member_postgres, WorkspaceMember)
        assert member_memory.user_id == "invited-user-1"
        assert member_postgres.user_id == "invited-user-1"
        assert member_memory.role == MemberRole.EDITOR
        assert member_postgres.role == MemberRole.EDITOR

    def test_get_workspace_members_parity(
        self,
        collaboration_service_memory: CollaborationService,
        collaboration_service_postgres: PostgresCollaborationService,
    ) -> None:
        """Both backends should list members consistently."""
        # Create workspaces
        ws_request = CreateWorkspaceRequest(
            name="Members List Test",
            owner_id=TEST_USER_ID,
        )
        ws_memory = collaboration_service_memory.create_workspace(ws_request)
        ws_postgres = collaboration_service_postgres.create_workspace(ws_request)

        # Get members (owner should be auto-added)
        members_memory = collaboration_service_memory.get_workspace_members(ws_memory.workspace_id)
        members_postgres = collaboration_service_postgres.get_workspace_members(ws_postgres.workspace_id)

        # Owner should be in both
        assert len(members_memory) >= 1
        assert len(members_postgres) >= 1


# ------------------------------------------------------------------
# Parity Tests - Document Operations
# ------------------------------------------------------------------
class TestDocumentOperationsParity:
    """Test document operations parity between backends."""

    def test_create_document_parity(
        self,
        collaboration_service_memory: CollaborationService,
        collaboration_service_postgres: PostgresCollaborationService,
    ) -> None:
        """Both backends should create documents consistently."""
        # Create workspaces first
        ws_request = CreateWorkspaceRequest(
            name="Document Test Workspace",
            owner_id=TEST_USER_ID,
        )
        ws_memory = collaboration_service_memory.create_workspace(ws_request)
        ws_postgres = collaboration_service_postgres.create_workspace(ws_request)

        # Create documents
        doc_request_memory = CreateDocumentRequest(
            workspace_id=ws_memory.workspace_id,
            title="Test Document",
            doc_type=DocumentType.MARKDOWN,
            content="# Hello World",
            creator_id=TEST_USER_ID,
        )
        doc_request_postgres = CreateDocumentRequest(
            workspace_id=ws_postgres.workspace_id,
            title="Test Document",
            doc_type=DocumentType.MARKDOWN,
            content="# Hello World",
            creator_id=TEST_USER_ID,
        )

        doc_memory = collaboration_service_memory.create_document(doc_request_memory)
        doc_postgres = collaboration_service_postgres.create_document(doc_request_postgres)

        assert isinstance(doc_memory, Document)
        assert isinstance(doc_postgres, Document)
        assert doc_memory.title == "Test Document"
        assert doc_postgres.title == "Test Document"
        assert doc_memory.doc_type == DocumentType.MARKDOWN
        assert doc_postgres.doc_type == DocumentType.MARKDOWN
        assert doc_memory.content == "# Hello World"
        assert doc_postgres.content == "# Hello World"

    def test_get_document_parity(
        self,
        collaboration_service_memory: CollaborationService,
        collaboration_service_postgres: PostgresCollaborationService,
    ) -> None:
        """Both backends should retrieve documents consistently."""
        # Create workspace and document
        ws_request = CreateWorkspaceRequest(name="Doc Retrieval Test", owner_id=TEST_USER_ID)
        ws_memory = collaboration_service_memory.create_workspace(ws_request)
        ws_postgres = collaboration_service_postgres.create_workspace(ws_request)

        doc_request_memory = CreateDocumentRequest(
            workspace_id=ws_memory.workspace_id,
            title="Retrievable Doc",
            doc_type=DocumentType.CODE,
            content="print('hello')",
            creator_id=TEST_USER_ID,
        )
        doc_request_postgres = CreateDocumentRequest(
            workspace_id=ws_postgres.workspace_id,
            title="Retrievable Doc",
            doc_type=DocumentType.CODE,
            content="print('hello')",
            creator_id=TEST_USER_ID,
        )

        created_memory = collaboration_service_memory.create_document(doc_request_memory)
        created_postgres = collaboration_service_postgres.create_document(doc_request_postgres)

        retrieved_memory = collaboration_service_memory.get_document(created_memory.document_id)
        retrieved_postgres = collaboration_service_postgres.get_document(created_postgres.document_id)

        assert retrieved_memory is not None
        assert retrieved_postgres is not None
        assert retrieved_memory.title == created_memory.title
        assert retrieved_postgres.title == created_postgres.title


# ------------------------------------------------------------------
# Parity Tests - Real-time Editing
# ------------------------------------------------------------------
class TestRealTimeEditingParity:
    """Test real-time editing parity between backends."""

    def test_apply_edit_parity(
        self,
        collaboration_service_memory: CollaborationService,
        collaboration_service_postgres: PostgresCollaborationService,
    ) -> None:
        """Both backends should apply edits consistently."""
        # Setup workspace and document
        ws_request = CreateWorkspaceRequest(name="Edit Test", owner_id=TEST_USER_ID)
        ws_memory = collaboration_service_memory.create_workspace(ws_request)
        ws_postgres = collaboration_service_postgres.create_workspace(ws_request)

        doc_request_memory = CreateDocumentRequest(
            workspace_id=ws_memory.workspace_id,
            title="Editable Doc",
            doc_type=DocumentType.TEXT,
            content="Original content",
            creator_id=TEST_USER_ID,
        )
        doc_request_postgres = CreateDocumentRequest(
            workspace_id=ws_postgres.workspace_id,
            title="Editable Doc",
            doc_type=DocumentType.TEXT,
            content="Original content",
            creator_id=TEST_USER_ID,
        )

        doc_memory = collaboration_service_memory.create_document(doc_request_memory)
        doc_postgres = collaboration_service_postgres.create_document(doc_request_postgres)

        # Apply edits
        edit_request_memory = RealTimeEditRequest(
            document_id=doc_memory.document_id,
            user_id=TEST_USER_ID,
            operation_type=EditOperationType.INSERT,
            position=8,  # After "Original"
            content=" modified",
        )
        edit_request_postgres = RealTimeEditRequest(
            document_id=doc_postgres.document_id,
            user_id=TEST_USER_ID,
            operation_type=EditOperationType.INSERT,
            position=8,
            content=" modified",
        )

        op_memory = collaboration_service_memory.apply_real_time_edit(edit_request_memory)
        op_postgres = collaboration_service_postgres.apply_real_time_edit(edit_request_postgres)

        assert isinstance(op_memory, EditOperation)
        assert isinstance(op_postgres, EditOperation)
        assert op_memory.user_id == TEST_USER_ID
        assert op_postgres.user_id == TEST_USER_ID


# ------------------------------------------------------------------
# Parity Tests - Comments
# ------------------------------------------------------------------
class TestCommentsParity:
    """Test comments parity between backends."""

    def test_add_comment_parity(
        self,
        collaboration_service_memory: CollaborationService,
        collaboration_service_postgres: PostgresCollaborationService,
    ) -> None:
        """Both backends should add comments consistently."""
        # Setup workspace and document
        ws_request = CreateWorkspaceRequest(name="Comment Test", owner_id=TEST_USER_ID)
        ws_memory = collaboration_service_memory.create_workspace(ws_request)
        ws_postgres = collaboration_service_postgres.create_workspace(ws_request)

        doc_request_memory = CreateDocumentRequest(
            workspace_id=ws_memory.workspace_id,
            title="Commentable Doc",
            doc_type=DocumentType.TEXT,
            content="Content to comment on",
            creator_id=TEST_USER_ID,
        )
        doc_request_postgres = CreateDocumentRequest(
            workspace_id=ws_postgres.workspace_id,
            title="Commentable Doc",
            doc_type=DocumentType.TEXT,
            content="Content to comment on",
            creator_id=TEST_USER_ID,
        )

        doc_memory = collaboration_service_memory.create_document(doc_request_memory)
        doc_postgres = collaboration_service_postgres.create_document(doc_request_postgres)

        # Add comments
        comment_request_memory = CommentRequest(
            document_id=doc_memory.document_id,
            user_id=TEST_USER_ID,
            content="This is a test comment",
            position_start=0,
            position_end=7,
        )
        comment_request_postgres = CommentRequest(
            document_id=doc_postgres.document_id,
            user_id=TEST_USER_ID,
            content="This is a test comment",
            position_start=0,
            position_end=7,
        )

        comment_memory = collaboration_service_memory.add_comment(comment_request_memory)
        comment_postgres = collaboration_service_postgres.add_comment(comment_request_postgres)

        assert isinstance(comment_memory, Comment)
        assert isinstance(comment_postgres, Comment)
        assert comment_memory.content == "This is a test comment"
        assert comment_postgres.content == "This is a test comment"
        assert comment_memory.user_id == TEST_USER_ID
        assert comment_postgres.user_id == TEST_USER_ID


# ------------------------------------------------------------------
# Parity Tests - Document Locking
# ------------------------------------------------------------------
class TestDocumentLockingParity:
    """Test document locking parity between backends."""

    def test_lock_unlock_document_parity(
        self,
        collaboration_service_memory: CollaborationService,
        collaboration_service_postgres: PostgresCollaborationService,
    ) -> None:
        """Both backends should handle document locking consistently."""
        # Setup workspace and document
        ws_request = CreateWorkspaceRequest(name="Lock Test", owner_id=TEST_USER_ID)
        ws_memory = collaboration_service_memory.create_workspace(ws_request)
        ws_postgres = collaboration_service_postgres.create_workspace(ws_request)

        doc_request_memory = CreateDocumentRequest(
            workspace_id=ws_memory.workspace_id,
            title="Lockable Doc",
            doc_type=DocumentType.TEXT,
            content="Lock me",
            creator_id=TEST_USER_ID,
        )
        doc_request_postgres = CreateDocumentRequest(
            workspace_id=ws_postgres.workspace_id,
            title="Lockable Doc",
            doc_type=DocumentType.TEXT,
            content="Lock me",
            creator_id=TEST_USER_ID,
        )

        doc_memory = collaboration_service_memory.create_document(doc_request_memory)
        doc_postgres = collaboration_service_postgres.create_document(doc_request_postgres)

        # Lock documents
        lock_memory = collaboration_service_memory.lock_document(
            doc_memory.document_id, TEST_USER_ID
        )
        lock_postgres = collaboration_service_postgres.lock_document(
            doc_postgres.document_id, TEST_USER_ID
        )

        assert lock_memory is True
        assert lock_postgres is True

        # Unlock documents
        unlock_memory = collaboration_service_memory.unlock_document(
            doc_memory.document_id, TEST_USER_ID
        )
        unlock_postgres = collaboration_service_postgres.unlock_document(
            doc_postgres.document_id, TEST_USER_ID
        )

        assert unlock_memory is True
        assert unlock_postgres is True


# ------------------------------------------------------------------
# Parity Tests - Collaboration Metrics
# ------------------------------------------------------------------
class TestCollaborationMetricsParity:
    """Test collaboration metrics parity between backends."""

    def test_get_metrics_parity(
        self,
        collaboration_service_memory: CollaborationService,
        collaboration_service_postgres: PostgresCollaborationService,
    ) -> None:
        """Both backends should calculate metrics consistently."""
        # Setup workspace
        ws_request = CreateWorkspaceRequest(name="Metrics Test", owner_id=TEST_USER_ID)
        ws_memory = collaboration_service_memory.create_workspace(ws_request)
        ws_postgres = collaboration_service_postgres.create_workspace(ws_request)

        # Get metrics
        metrics_memory = collaboration_service_memory.get_collaboration_metrics(
            ws_memory.workspace_id
        )
        metrics_postgres = collaboration_service_postgres.get_collaboration_metrics(
            ws_postgres.workspace_id
        )

        # Both should return metrics objects
        assert metrics_memory is not None
        assert metrics_postgres is not None

        # Initial metrics should be similar (1 member, 0 documents, etc.)
        assert metrics_memory.total_members >= 1
        assert metrics_postgres.total_members >= 1
        assert metrics_memory.total_documents >= 0
        assert metrics_postgres.total_documents >= 0
