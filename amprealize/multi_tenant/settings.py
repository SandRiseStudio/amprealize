"""Settings service — enterprise feature (partial).

ExecutionMode enum and surface constants are OSS (used by work_item_execution_service).
SettingsService, OrgSettings, and other Pydantic models are enterprise-only.

Full implementation available in amprealize-enterprise package.
Install: pip install amprealize-enterprise
"""

from enum import Enum


# =============================================================================
# OSS: Execution mode types (used by work_item_execution_service)
# =============================================================================

class ExecutionMode(str, Enum):
    """Execution mode for work item processing."""
    LOCAL = "local"
    GITHUB_PR = "github_pr"
    LOCAL_AND_PR = "local_and_pr"


# Surfaces that support local file operations
LOCAL_CAPABLE_SURFACES = frozenset({"cli", "vscode", "mcp", "codespaces", "gitpod"})

# Surfaces that do NOT support local file operations
REMOTE_ONLY_SURFACES = frozenset({"web", "api"})


# =============================================================================
# Enterprise: Settings service and models
# =============================================================================

try:
    from amprealize_enterprise.multi_tenant.settings import (
        SettingsService,
        OrgSettings,
        ProjectSettings,
        BrandingSettings,
        NotificationSettings,
        SecuritySettings,
        IntegrationSettings,
        WorkflowSettings,
        AgentSettings,
        UpdateBrandingRequest,
        UpdateNotificationRequest,
        UpdateSecurityRequest,
        UpdateWorkflowRequest,
    )
except ImportError:
    SettingsService = None
    OrgSettings = None
    ProjectSettings = None
    BrandingSettings = None
    NotificationSettings = None
    SecuritySettings = None
    IntegrationSettings = None
    WorkflowSettings = None
    AgentSettings = None
    UpdateBrandingRequest = None
    UpdateNotificationRequest = None
    UpdateSecurityRequest = None
    UpdateWorkflowRequest = None

__all__ = [
    "ExecutionMode",
    "LOCAL_CAPABLE_SURFACES",
    "REMOTE_ONLY_SURFACES",
    "SettingsService",
    "OrgSettings",
    "ProjectSettings",
    "BrandingSettings",
    "NotificationSettings",
    "SecuritySettings",
    "IntegrationSettings",
    "WorkflowSettings",
    "AgentSettings",
    "UpdateBrandingRequest",
    "UpdateNotificationRequest",
    "UpdateSecurityRequest",
    "UpdateWorkflowRequest",
]
