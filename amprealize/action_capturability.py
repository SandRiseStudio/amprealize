"""Action capturability validation service.

Ensures all platform actions can be recorded and tracked for reproducibility.
Implements the capturability requirements from docs/contracts/ACTION_REGISTRY_SPEC.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from .telemetry import TelemetryClient


class ActionType(str, Enum):
    """Categories of platform actions."""
    FILE_EDIT = "file_edit"
    FILE_CREATE = "file_create"
    FILE_DELETE = "file_delete"
    COMMAND_EXECUTION = "command_execution"
    API_CALL = "api_call"
    BEHAVIOR_CREATION = "behavior_creation"
    WORKFLOW_EXECUTION = "workflow_execution"
    COMPLIANCE_CHECK = "compliance_check"
    CONFIG_CHANGE = "config_change"
    DEPLOYMENT = "deployment"
    SECRET_ROTATION = "secret_rotation"
    DOCUMENTATION_UPDATE = "documentation_update"


@dataclass
class ActionCapability:
    """Describes whether and how an action type can be captured."""
    action_type: ActionType
    capturable: bool
    required_metadata: List[str] = field(default_factory=list)
    optional_metadata: List[str] = field(default_factory=list)
    validation_rules: List[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class CapturabilityReport:
    """Report of action capturability across the platform."""
    total_action_types: int
    capturable_count: int
    non_capturable_count: int
    coverage_percentage: float
    action_capabilities: Dict[ActionType, ActionCapability]
    uncaptured_actions: List[Dict[str, str]] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


class ActionCapturabilityService:
    """Service to validate and track action capturability.

    Ensures the platform meets the 95% compliance coverage target from PRD.md.
    """

    def __init__(self, telemetry: Optional[TelemetryClient] = None):
        self._telemetry = telemetry or TelemetryClient.noop()
        self._capabilities = self._initialize_capabilities()
        self._uncaptured_actions: List[Dict[str, str]] = []

    def _initialize_capabilities(self) -> Dict[ActionType, ActionCapability]:
        """Initialize the registry of action capabilities."""
        return {
            ActionType.FILE_EDIT: ActionCapability(
                action_type=ActionType.FILE_EDIT,
                capturable=True,
                required_metadata=["file_path", "summary"],
                optional_metadata=["behaviors_cited", "diff", "checksum"],
                validation_rules=["file_path must be relative to repo root"],
            ),
            ActionType.FILE_CREATE: ActionCapability(
                action_type=ActionType.FILE_CREATE,
                capturable=True,
                required_metadata=["file_path", "summary"],
                optional_metadata=["behaviors_cited", "content_preview", "checksum"],
                validation_rules=["file_path must not already exist"],
            ),
            ActionType.FILE_DELETE: ActionCapability(
                action_type=ActionType.FILE_DELETE,
                capturable=True,
                required_metadata=["file_path", "summary", "reason"],
                optional_metadata=["behaviors_cited", "backup_location"],
                validation_rules=["reason required for audit trail"],
            ),
            ActionType.COMMAND_EXECUTION: ActionCapability(
                action_type=ActionType.COMMAND_EXECUTION,
                capturable=True,
                required_metadata=["command", "summary"],
                optional_metadata=["behaviors_cited", "exit_code", "output_preview", "working_dir"],
                validation_rules=["sanitize secrets from command string"],
            ),
            ActionType.API_CALL: ActionCapability(
                action_type=ActionType.API_CALL,
                capturable=True,
                required_metadata=["endpoint", "method", "summary"],
                optional_metadata=["behaviors_cited", "status_code", "response_preview"],
                validation_rules=["redact auth tokens from metadata"],
            ),
            ActionType.BEHAVIOR_CREATION: ActionCapability(
                action_type=ActionType.BEHAVIOR_CREATION,
                capturable=True,
                required_metadata=["behavior_name", "summary"],
                optional_metadata=["behaviors_cited", "role_focus", "trigger_keywords"],
                validation_rules=["behavior_name must be unique"],
            ),
            ActionType.WORKFLOW_EXECUTION: ActionCapability(
                action_type=ActionType.WORKFLOW_EXECUTION,
                capturable=True,
                required_metadata=["workflow_id", "summary"],
                optional_metadata=["behaviors_cited", "run_id", "status", "duration_ms"],
                validation_rules=["run_id must link to RunService"],
            ),
            ActionType.COMPLIANCE_CHECK: ActionCapability(
                action_type=ActionType.COMPLIANCE_CHECK,
                capturable=True,
                required_metadata=["checklist_id", "summary"],
                optional_metadata=["behaviors_cited", "validation_results", "missing_steps"],
                validation_rules=["must reference valid checklist"],
            ),
            ActionType.CONFIG_CHANGE: ActionCapability(
                action_type=ActionType.CONFIG_CHANGE,
                capturable=True,
                required_metadata=["config_key", "summary"],
                optional_metadata=["behaviors_cited", "old_value", "new_value", "environment"],
                validation_rules=["redact sensitive config values"],
            ),
            ActionType.DEPLOYMENT: ActionCapability(
                action_type=ActionType.DEPLOYMENT,
                capturable=True,
                required_metadata=["deployment_target", "version", "summary"],
                optional_metadata=["behaviors_cited", "commit_sha", "rollback_plan"],
                validation_rules=["version must be semver or git sha"],
            ),
            ActionType.SECRET_ROTATION: ActionCapability(
                action_type=ActionType.SECRET_ROTATION,
                capturable=True,
                required_metadata=["secret_id", "summary"],
                optional_metadata=["behaviors_cited", "rotation_timestamp", "expiry"],
                validation_rules=["never log actual secret values"],
                notes="Critical for security audit trail",
            ),
            ActionType.DOCUMENTATION_UPDATE: ActionCapability(
                action_type=ActionType.DOCUMENTATION_UPDATE,
                capturable=True,
                required_metadata=["artifact_path", "summary"],
                optional_metadata=["behaviors_cited", "sections_changed", "related_actions"],
                validation_rules=["artifact_path must be .md file"],
            ),
        }

    def get_capability(self, action_type: ActionType) -> ActionCapability:
        """Get capability information for an action type."""
        return self._capabilities.get(action_type, ActionCapability(
            action_type=action_type,
            capturable=False,
            notes="Action type not registered in capturability service",
        ))

    def validate_action_metadata(
        self,
        action_type: ActionType,
        metadata: Dict[str, Any],
    ) -> tuple[bool, List[str]]:
        """Validate that action metadata meets requirements.

        Returns:
            (is_valid, list_of_errors)
        """
        capability = self.get_capability(action_type)
        errors = []

        if not capability.capturable:
            errors.append(f"Action type {action_type.value} is not capturable")
            return False, errors

        # Check required metadata
        for required_key in capability.required_metadata:
            if required_key not in metadata or not metadata[required_key]:
                errors.append(f"Missing required metadata: {required_key}")

        return len(errors) == 0, errors

    def record_uncaptured_action(
        self,
        action_type: str,
        context: str,
        reason: str,
    ) -> None:
        """Record an action that could not be captured.

        Emits telemetry for monitoring compliance coverage.
        """
        entry = {
            "action_type": action_type,
            "context": context,
            "reason": reason,
        }
        self._uncaptured_actions.append(entry)

        self._telemetry.emit_event(
            event_type="action_not_captured",
            payload=entry,
            actor={"id": "system", "role": "SYSTEM", "surface": "PLATFORM"},
        )

    def generate_capturability_report(self) -> CapturabilityReport:
        """Generate comprehensive capturability report."""
        total = len(self._capabilities)
        capturable = sum(1 for cap in self._capabilities.values() if cap.capturable)
        non_capturable = total - capturable
        coverage_pct = (capturable / total * 100) if total > 0 else 0

        recommendations = []

        # Check against PRD target
        if coverage_pct < 95.0:
            recommendations.append(
                f"Coverage ({coverage_pct:.1f}%) below PRD target of 95%. "
                f"Register {int((0.95 * total) - capturable)} more action types."
            )

        # Check for uncaptured actions
        if self._uncaptured_actions:
            unique_types = {a["action_type"] for a in self._uncaptured_actions}
            recommendations.append(
                f"Found {len(self._uncaptured_actions)} uncaptured action attempts "
                f"across {len(unique_types)} action types. Review and add capture hooks."
            )

        # Check for action types missing validation rules
        missing_validation = [
            cap.action_type.value
            for cap in self._capabilities.values()
            if cap.capturable and not cap.validation_rules
        ]
        if missing_validation:
            recommendations.append(
                f"Action types without validation rules: {', '.join(missing_validation)}"
            )

        report = CapturabilityReport(
            total_action_types=total,
            capturable_count=capturable,
            non_capturable_count=non_capturable,
            coverage_percentage=coverage_pct,
            action_capabilities=self._capabilities.copy(),
            uncaptured_actions=self._uncaptured_actions.copy(),
            recommendations=recommendations,
        )

        # Emit telemetry
        self._telemetry.emit_event(
            event_type="capturability_report_generated",
            payload={
                "total_action_types": total,
                "capturable_count": capturable,
                "coverage_percentage": coverage_pct,
                "uncaptured_actions_count": len(self._uncaptured_actions),
                "recommendations_count": len(recommendations),
            },
            actor={"id": "system", "role": "SYSTEM", "surface": "PLATFORM"},
        )

        return report

    def register_action_type(
        self,
        action_type: ActionType,
        capability: ActionCapability,
    ) -> None:
        """Register a new action type capability (for extensibility)."""
        self._capabilities[action_type] = capability

        self._telemetry.emit_event(
            event_type="action_type_registered",
            payload={
                "action_type": action_type.value,
                "capturable": capability.capturable,
                "required_metadata_count": len(capability.required_metadata),
            },
            actor={"id": "system", "role": "SYSTEM", "surface": "PLATFORM"},
        )

    def get_all_capturable_types(self) -> List[ActionType]:
        """Get list of all capturable action types."""
        return [
            action_type
            for action_type, capability in self._capabilities.items()
            if capability.capturable
        ]

    def get_required_metadata_for_type(self, action_type: ActionType) -> List[str]:
        """Get required metadata fields for an action type."""
        capability = self.get_capability(action_type)
        return capability.required_metadata if capability.capturable else []
