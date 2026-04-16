"""Feature Definition models — structured output of the NewFeature agent.

These models formalize the Feature Definition document so it can be
consumed programmatically (e.g., by WorkItemPlanner, Plan agent, or
future automation).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# =============================================================================
# Enums
# =============================================================================


class Edition(str, Enum):
    """Amprealize distribution editions."""
    OSS = "oss"
    ENTERPRISE_STARTER = "enterprise_starter"
    ENTERPRISE_PREMIUM = "enterprise_premium"


class OSSStubPattern(str, Enum):
    """Stub patterns for enterprise-only features in the OSS codebase."""
    NONE_ASSIGNMENT = "none_assignment"
    NOOP_DATACLASS = "noop_dataclass"
    RAISE_ON_CALL = "raise_on_call"
    EMPTY_CONSTANTS = "empty_constants"
    CONDITIONAL_BLOCK = "conditional_block"


class FeatureFlagStrategy(str, Enum):
    """How the feature rolls out."""
    FULL_LAUNCH = "full_launch"
    BOOLEAN_FLAG = "boolean_flag"
    PERCENTAGE_ROLLOUT = "percentage_rollout"
    USER_LIST = "user_list"
    NO_FLAG = "no_flag"


class Surface(str, Enum):
    """Amprealize product surfaces."""
    MCP = "mcp"
    REST_API = "api"
    CLI = "cli"
    WEB_CONSOLE = "web"
    VSCODE_EXTENSION = "vscode"


class ServiceImpactType(str, Enum):
    """How a service is affected."""
    NEW = "new"
    MODIFIED = "modified"
    DEPENDS = "depends"


class DataChangeType(str, Enum):
    """Type of data model change."""
    NEW_TABLE = "new_table"
    ALTER_TABLE = "alter_table"
    NEW_INDEX = "new_index"
    DROP = "drop"


class AuthLevel(str, Enum):
    """Authentication/authorization level."""
    PUBLIC = "public"
    AUTHENTICATED = "authenticated"
    PROJECT_SCOPED = "project_scoped"
    ORG_SCOPED = "org_scoped"
    ADMIN_ONLY = "admin_only"


class SecurityClassification(str, Enum):
    """Data sensitivity classification."""
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class AgentRole(str, Enum):
    """Primary role for this feature."""
    STUDENT = "student"
    TEACHER = "teacher"
    STRATEGIST = "strategist"


# =============================================================================
# Data classes
# =============================================================================


@dataclass
class SurfaceCoverage:
    """Coverage plan for a single surface."""
    surface: Surface
    day_one: bool = False
    follow_up: bool = False
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "surface": self.surface.value,
            "day_one": self.day_one,
            "follow_up": self.follow_up,
            "notes": self.notes,
        }


@dataclass
class ServiceImpact:
    """Impact on an existing or new service."""
    service: str
    impact_type: ServiceImpactType
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "service": self.service,
            "impact_type": self.impact_type.value,
            "description": self.description,
        }


@dataclass
class DataModelChange:
    """A planned change to the data model."""
    table: str
    change_type: DataChangeType
    migration_name: str = ""
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "table": self.table,
            "change_type": self.change_type.value,
            "migration_name": self.migration_name,
            "description": self.description,
        }


@dataclass
class ConfigItem:
    """A new configuration entry."""
    name: str
    purpose: str = ""
    default: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "purpose": self.purpose,
            "default": self.default,
        }


@dataclass
class BehavioralContext:
    """Behavioral context for the feature."""
    existing_behaviors: List[str] = field(default_factory=list)
    new_behaviors: List[str] = field(default_factory=list)
    primary_role: AgentRole = AgentRole.STUDENT
    agents_md_updates: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "existing_behaviors": self.existing_behaviors,
            "new_behaviors": self.new_behaviors,
            "primary_role": self.primary_role.value,
            "agents_md_updates": self.agents_md_updates,
        }


@dataclass
class SecurityProfile:
    """Security and compliance profile."""
    auth_level: AuthLevel = AuthLevel.AUTHENTICATED
    new_permissions: List[str] = field(default_factory=list)
    audit_logging: List[str] = field(default_factory=list)
    data_sensitivity: SecurityClassification = SecurityClassification.INTERNAL
    rate_limiting: str = "Default"
    compliance_items: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "auth_level": self.auth_level.value,
            "new_permissions": self.new_permissions,
            "audit_logging": self.audit_logging,
            "data_sensitivity": self.data_sensitivity.value,
            "rate_limiting": self.rate_limiting,
            "compliance_items": self.compliance_items,
        }


@dataclass
class TestingRequirements:
    """Testing strategy for the feature."""
    parity_surfaces: List[Surface] = field(default_factory=list)
    unit_coverage_target: int = 90
    integration_tests: List[str] = field(default_factory=list)
    performance_benchmarks: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parity_surfaces": [s.value for s in self.parity_surfaces],
            "unit_coverage_target": self.unit_coverage_target,
            "integration_tests": self.integration_tests,
            "performance_benchmarks": self.performance_benchmarks,
        }


@dataclass
class FeatureDefinition:
    """Complete Feature Definition — the primary output of the NewFeature agent.

    Usage:
        definition = FeatureDefinition(
            feature_name="Behavior Versioning Diff View",
            summary="Shows side-by-side diff of behavior version changes",
            edition=Edition.OSS,
            surface_coverage=[
                SurfaceCoverage(surface=Surface.WEB_CONSOLE, day_one=True),
                SurfaceCoverage(surface=Surface.REST_API, day_one=True),
            ],
        )
    """
    feature_name: str
    summary: str
    edition: Edition = Edition.OSS
    feature_flag: Optional[str] = None
    flag_strategy: FeatureFlagStrategy = FeatureFlagStrategy.NO_FLAG
    starter_cap: Optional[str] = None
    oss_stub_pattern: Optional[OSSStubPattern] = None

    surface_coverage: List[SurfaceCoverage] = field(default_factory=list)
    services_impacted: List[ServiceImpact] = field(default_factory=list)
    data_model_changes: List[DataModelChange] = field(default_factory=list)
    config_items: List[ConfigItem] = field(default_factory=list)
    new_service_needed: bool = False
    new_service_name: Optional[str] = None

    behavioral_context: BehavioralContext = field(default_factory=BehavioralContext)
    security: SecurityProfile = field(default_factory=SecurityProfile)
    testing: TestingRequirements = field(default_factory=TestingRequirements)

    depends_on: List[str] = field(default_factory=list)
    impacts: List[str] = field(default_factory=list)
    breaking_changes: bool = False
    migration_path: str = ""

    acceptance_criteria: List[str] = field(default_factory=list)
    metrics: List[Dict[str, str]] = field(default_factory=list)
    documentation_updates: List[str] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for JSON output or MCP tool responses."""
        return {
            "version": "1.0",
            "feature_name": self.feature_name,
            "summary": self.summary,
            "distribution": {
                "edition": self.edition.value,
                "feature_flag": self.feature_flag,
                "flag_strategy": self.flag_strategy.value,
                "starter_cap": self.starter_cap,
                "oss_stub_pattern": (
                    self.oss_stub_pattern.value if self.oss_stub_pattern else None
                ),
            },
            "surface_coverage": [s.to_dict() for s in self.surface_coverage],
            "services_impacted": [s.to_dict() for s in self.services_impacted],
            "data_model_changes": [d.to_dict() for d in self.data_model_changes],
            "config_items": [c.to_dict() for c in self.config_items],
            "new_service": {
                "needed": self.new_service_needed,
                "name": self.new_service_name,
            },
            "behavioral_context": self.behavioral_context.to_dict(),
            "security": self.security.to_dict(),
            "feature_interactions": {
                "depends_on": self.depends_on,
                "impacts": self.impacts,
                "breaking_changes": self.breaking_changes,
                "migration_path": self.migration_path,
            },
            "acceptance_criteria": self.acceptance_criteria,
            "metrics": self.metrics,
            "testing": self.testing.to_dict(),
            "documentation_updates": self.documentation_updates,
            "open_questions": self.open_questions,
        }
