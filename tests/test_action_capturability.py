"""Unit tests for action capturability service."""

import pytest

from amprealize.action_capturability import (
    ActionCapturabilityService,
    ActionType,
    ActionCapability,
)

pytestmark = pytest.mark.unit


def test_all_action_types_registered():
    """Test that all action types have capability entries."""
    service = ActionCapturabilityService()

    # All action types should be registered
    for action_type in ActionType:
        capability = service.get_capability(action_type)
        assert capability is not None
        assert capability.action_type == action_type


def test_validate_action_metadata_valid():
    """Test validation of valid action metadata."""
    service = ActionCapturabilityService()

    # Valid file edit action
    is_valid, errors = service.validate_action_metadata(
        ActionType.FILE_EDIT,
        {"file_path": "test.py", "summary": "Updated test"},
    )
    assert is_valid
    assert len(errors) == 0


def test_validate_action_metadata_missing_required():
    """Test validation catches missing required metadata."""
    service = ActionCapturabilityService()

    # Missing required 'summary' field
    is_valid, errors = service.validate_action_metadata(
        ActionType.FILE_EDIT,
        {"file_path": "test.py"},
    )
    assert not is_valid
    assert any("summary" in error.lower() for error in errors)


def test_validate_action_metadata_empty_required():
    """Test validation catches empty required metadata."""
    service = ActionCapturabilityService()

    # Empty summary
    is_valid, errors = service.validate_action_metadata(
        ActionType.FILE_CREATE,
        {"file_path": "new.py", "summary": ""},
    )
    assert not is_valid
    assert any("summary" in error.lower() for error in errors)


def test_record_uncaptured_action():
    """Test recording uncaptured actions."""
    service = ActionCapturabilityService()

    service.record_uncaptured_action(
        action_type="custom_action",
        context="test_context",
        reason="No capture hook available",
    )

    assert len(service._uncaptured_actions) == 1
    assert service._uncaptured_actions[0]["action_type"] == "custom_action"


def test_generate_capturability_report():
    """Test generating capturability report."""
    service = ActionCapturabilityService()

    report = service.generate_capturability_report()

    assert report.total_action_types > 0
    assert report.capturable_count > 0
    assert report.coverage_percentage > 0
    assert len(report.action_capabilities) == report.total_action_types

    # All currently defined types should be capturable
    assert report.capturable_count == report.total_action_types
    assert report.coverage_percentage == 100.0


def test_report_meets_prd_target():
    """Test that coverage meets PRD 95% target."""
    service = ActionCapturabilityService()

    report = service.generate_capturability_report()

    # Should meet or exceed 95% coverage
    assert report.coverage_percentage >= 95.0

    # Should not have recommendations about low coverage
    coverage_warnings = [
        r for r in report.recommendations
        if "below PRD target" in r
    ]
    assert len(coverage_warnings) == 0


def test_register_new_action_type():
    """Test registering a new action type."""
    service = ActionCapturabilityService()

    # Define a new action type (simulated)
    class CustomActionType(str):
        TEST_ACTION = "test_action"

    new_capability = ActionCapability(
        action_type=ActionType.FILE_EDIT,  # Reuse enum for test
        capturable=True,
        required_metadata=["test_field"],
    )

    initial_count = len(service._capabilities)
    service.register_action_type(ActionType.FILE_EDIT, new_capability)

    # Count should remain same (override) or increase (new)
    assert len(service._capabilities) >= initial_count


def test_get_all_capturable_types():
    """Test getting all capturable action types."""
    service = ActionCapturabilityService()

    capturable_types = service.get_all_capturable_types()

    assert len(capturable_types) > 0
    assert all(isinstance(t, ActionType) for t in capturable_types)

    # All types should be capturable in current implementation
    assert len(capturable_types) == len(ActionType)


def test_get_required_metadata_for_type():
    """Test getting required metadata for action types."""
    service = ActionCapturabilityService()

    # File edit should have required metadata
    required = service.get_required_metadata_for_type(ActionType.FILE_EDIT)
    assert "file_path" in required
    assert "summary" in required

    # Command execution should have required metadata
    required = service.get_required_metadata_for_type(ActionType.COMMAND_EXECUTION)
    assert "command" in required
    assert "summary" in required


def test_secret_rotation_has_security_notes():
    """Test that secret rotation has appropriate security notes."""
    service = ActionCapturabilityService()

    capability = service.get_capability(ActionType.SECRET_ROTATION)

    assert capability.capturable
    assert capability.notes  # Should have security notes
    assert "security" in capability.notes.lower() or "audit" in capability.notes.lower()

    # Should have validation rule about not logging secrets
    validation_rules_text = " ".join(capability.validation_rules).lower()
    assert "secret" in validation_rules_text or "log" in validation_rules_text


def test_compliance_check_validation():
    """Test compliance check action validation."""
    service = ActionCapturabilityService()

    # Valid compliance check
    is_valid, errors = service.validate_action_metadata(
        ActionType.COMPLIANCE_CHECK,
        {
            "checklist_id": "checklist-001",
            "summary": "Ran security checklist",
        },
    )
    assert is_valid
    assert len(errors) == 0

    # Missing checklist_id
    is_valid, errors = service.validate_action_metadata(
        ActionType.COMPLIANCE_CHECK,
        {"summary": "Ran security checklist"},
    )
    assert not is_valid
    assert any("checklist_id" in error.lower() for error in errors)


def test_report_tracks_uncaptured_actions():
    """Test that report includes uncaptured actions."""
    service = ActionCapturabilityService()

    # Record some uncaptured actions
    service.record_uncaptured_action("type1", "context1", "reason1")
    service.record_uncaptured_action("type2", "context2", "reason2")

    report = service.generate_capturability_report()

    assert len(report.uncaptured_actions) == 2
    assert any(a["action_type"] == "type1" for a in report.uncaptured_actions)

    # Should have recommendations about uncaptured actions
    uncaptured_recs = [
        r for r in report.recommendations
        if "uncaptured" in r.lower()
    ]
    assert len(uncaptured_recs) > 0


def test_action_types_cover_key_workflows():
    """Test that registered action types cover key platform workflows."""
    service = ActionCapturabilityService()

    # Key workflows that must be capturable
    key_types = [
        ActionType.FILE_EDIT,
        ActionType.FILE_CREATE,
        ActionType.COMMAND_EXECUTION,
        ActionType.BEHAVIOR_CREATION,
        ActionType.WORKFLOW_EXECUTION,
        ActionType.COMPLIANCE_CHECK,
        ActionType.SECRET_ROTATION,
        ActionType.DOCUMENTATION_UPDATE,
    ]

    for action_type in key_types:
        capability = service.get_capability(action_type)
        assert capability.capturable, f"{action_type.value} must be capturable"
        assert len(capability.required_metadata) > 0, f"{action_type.value} needs required metadata"
