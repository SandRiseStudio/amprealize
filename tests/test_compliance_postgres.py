"""PostgreSQL backend tests for ComplianceService.

Tests the PostgresComplianceService implementation to ensure:
- Checklist CRUD operations work correctly
- Step recording with coverage recalculation functions properly
- Validation operations return correct results
- JSONB fields are handled correctly
- Filters work as expected
"""

from __future__ import annotations

import os

try:
    import psycopg2  # type: ignore[import-not-found]
except ImportError:
    psycopg2 = None
import pytest

from amprealize.action_contracts import Actor
from amprealize.compliance_service import (
    ChecklistNotFoundError,
    ComplianceService,
    RecordStepRequest,
)


TEST_ACTOR = Actor(id="test-user", role="engineer", surface="cli")
NONEXISTENT_CHECKLIST_ID = "00000000-0000-0000-0000-000000000001"


def _truncate_compliance_tables(dsn: str) -> None:
    """Remove all data from compliance tables to ensure test isolation."""
    from conftest import safe_truncate
    safe_truncate(dsn, ["checklist_steps", "checklists"])


def _create_checklist(service, **overrides):
    """Helper to create checklists with sensible defaults."""
    payload = {
        "title": "Test Checklist",
        "description": "",
        "template_id": None,
        "milestone": None,
        "compliance_category": [],
    }
    payload.update(overrides)
    return service.create_checklist(actor=TEST_ACTOR, **payload)


def _record_step(service, checklist_id: str, *, title: str, status: str, **kwargs):
    """Helper to record steps via RecordStepRequest."""
    request = RecordStepRequest(
        checklist_id=checklist_id,
        title=title,
        status=status,
        evidence=kwargs.get("evidence"),
        behaviors_cited=kwargs.get("behaviors_cited"),
        related_run_id=kwargs.get("related_run_id"),
    )
    return service.record_step(request, actor=TEST_ACTOR)


@pytest.fixture
def postgres_dsn():
    """Discover PostgreSQL DSN from environment."""
    dsn = os.environ.get("AMPREALIZE_COMPLIANCE_PG_DSN")
    if not dsn:
        pytest.skip("AMPREALIZE_COMPLIANCE_PG_DSN not set")
    yield dsn


@pytest.fixture
def service(postgres_dsn):
    """Create a fresh ComplianceService for each test."""
    _truncate_compliance_tables(postgres_dsn)
    svc = ComplianceService(dsn=postgres_dsn)
    yield svc


def test_create_checklist(service):
    """Should create a checklist with all fields."""
    checklist = _create_checklist(
        service,
        title="PRD Compliance",
        description="Ensure PRD complete",
        template_id="template-001",
        milestone="Priority 1.2",
        compliance_category=["documentation", "requirements"],
    )

    assert checklist.title == "PRD Compliance"
    assert checklist.description == "Ensure PRD complete"
    assert checklist.template_id == "template-001"
    assert checklist.milestone == "Priority 1.2"
    assert checklist.compliance_category == ["documentation", "requirements"]
    assert checklist.coverage_score == 0.0
    assert checklist.completed_at is None
    assert len(checklist.steps) == 0


def test_get_checklist(service):
    """Should retrieve checklist with steps."""
    checklist = _create_checklist(
        service,
        title="Test Checklist",
        description="Test",
        milestone="M1",
        compliance_category=["test"],
    )

    _record_step(
        service,
        checklist.checklist_id,
        title="Step 1",
        status="COMPLETED",
        evidence={"url": "https://example.com"},
        behaviors_cited=["behavior-001"],
    )

    retrieved = service.get_checklist(checklist.checklist_id)

    assert retrieved.title == "Test Checklist"
    assert len(retrieved.steps) == 1
    assert retrieved.steps[0].title == "Step 1"
    assert retrieved.steps[0].status == "COMPLETED"
    assert retrieved.steps[0].evidence == {"url": "https://example.com"}
    assert retrieved.steps[0].behaviors_cited == ["behavior-001"]


def test_get_checklist_not_found(service):
    """Should raise ChecklistNotFoundError for missing checklist."""
    with pytest.raises(ChecklistNotFoundError):
        service.get_checklist(NONEXISTENT_CHECKLIST_ID)


def test_list_checklists(service):
    """Should list all checklists."""
    _create_checklist(service, title="Checklist 1", milestone="M1")
    _create_checklist(service, title="Checklist 2", milestone="M2")
    _create_checklist(service, title="Checklist 3", milestone="M1")

    all_checklists = service.list_checklists()
    assert len(all_checklists) == 3


def test_list_checklists_filter_milestone(service):
    """Should filter checklists by milestone."""
    _create_checklist(service, title="M1 Checklist", milestone="M1")
    _create_checklist(service, title="M2 Checklist", milestone="M2")

    m1_checklists = service.list_checklists(milestone="M1")
    assert len(m1_checklists) == 1
    assert m1_checklists[0].milestone == "M1"


def test_list_checklists_filter_category(service):
    """Should filter checklists by compliance category."""
    _create_checklist(
        service,
        title="Doc Checklist",
        compliance_category=["documentation"],
    )
    _create_checklist(
        service,
        title="Security Checklist",
        compliance_category=["security"],
    )

    doc_checklists = service.list_checklists(compliance_category=["documentation"])
    assert len(doc_checklists) == 1
    assert "documentation" in doc_checklists[0].compliance_category


def test_list_checklists_filter_status_completed(service):
    """Should filter checklists by COMPLETED status."""
    c1 = _create_checklist(service, title="Active")
    c2 = _create_checklist(service, title="Completed")

    # Complete c2 by adding a terminal step
    _record_step(service, c2.checklist_id, title="Final Step", status="COMPLETED")

    completed = service.list_checklists(status_filter="COMPLETED")
    assert len(completed) == 1
    assert completed[0].completed_at is not None


def test_list_checklists_filter_status_active(service):
    """Should filter checklists by ACTIVE status."""
    c1 = _create_checklist(service, title="Active")
    c2 = _create_checklist(service, title="Completed")

    _record_step(service, c2.checklist_id, title="Step", status="COMPLETED")

    active = service.list_checklists(status_filter="ACTIVE")
    assert len(active) == 1
    assert active[0].completed_at is None


def test_record_step(service):
    """Should record a step with all fields."""
    checklist = _create_checklist(service, title="Test")

    step = _record_step(
        service,
        checklist.checklist_id,
        title="Step 1",
        status="IN_PROGRESS",
        evidence={"file": "test.py"},
        behaviors_cited=["behavior-001"],
        related_run_id="run-123",
    )

    assert step.title == "Step 1"
    assert step.status == "IN_PROGRESS"
    assert step.evidence == {"file": "test.py"}
    assert step.behaviors_cited == ["behavior-001"]
    assert step.related_run_id == "run-123"


def test_record_step_coverage_calculation(service):
    """Should calculate coverage correctly."""
    checklist = _create_checklist(service, title="Test")

    # 2 terminal (COMPLETED + SKIPPED) out of 3 total = 0.666...
    _record_step(service, checklist.checklist_id, title="Step 1", status="COMPLETED")
    _record_step(service, checklist.checklist_id, title="Step 2", status="SKIPPED")
    _record_step(service, checklist.checklist_id, title="Step 3", status="PENDING")

    retrieved = service.get_checklist(checklist.checklist_id)
    assert abs(retrieved.coverage_score - 0.6666) < 0.01


def test_record_step_auto_completion(service):
    """Should auto-complete checklist when all steps terminal."""
    checklist = _create_checklist(service, title="Test")

    _record_step(service, checklist.checklist_id, title="Step 1", status="COMPLETED")
    _record_step(service, checklist.checklist_id, title="Step 2", status="COMPLETED")

    retrieved = service.get_checklist(checklist.checklist_id)
    assert retrieved.completed_at is not None
    assert retrieved.coverage_score == 1.0


def test_validate_checklist(service):
    """Should validate checklist and return correct results."""
    checklist = _create_checklist(service, title="Test")

    _record_step(service, checklist.checklist_id, title="Completed", status="COMPLETED")
    _record_step(service, checklist.checklist_id, title="Failed", status="FAILED")
    _record_step(service, checklist.checklist_id, title="Pending", status="PENDING")
    _record_step(service, checklist.checklist_id, title="Skipped", status="SKIPPED")

    result = service.validate_checklist(checklist.checklist_id, TEST_ACTOR).to_dict()

    assert result["valid"] is False
    assert abs(result["coverage_score"] - 0.5) < 0.01  # 2 terminal / 4 total
    assert result["missing_steps"] == ["Pending"]
    assert result["failed_steps"] == ["Failed"]
    assert result["warnings"] == ["Step 'Skipped' was skipped without completion."]


def test_validate_checklist_all_completed(service):
    """Should return valid=True when all steps COMPLETED."""
    checklist = _create_checklist(service, title="Test")

    _record_step(service, checklist.checklist_id, title="Step 1", status="COMPLETED")
    _record_step(service, checklist.checklist_id, title="Step 2", status="COMPLETED")

    result = service.validate_checklist(checklist.checklist_id, TEST_ACTOR).to_dict()

    assert result["valid"] is True
    assert result["coverage_score"] == 1.0
    assert result["missing_steps"] == []
    assert result["failed_steps"] == []
    assert result["warnings"] == []


def test_validate_checklist_not_found(service):
    """Should raise ChecklistNotFoundError when validating missing checklist."""
    with pytest.raises(ChecklistNotFoundError):
        service.validate_checklist(NONEXISTENT_CHECKLIST_ID, TEST_ACTOR)
