"""Settings — backward-compat shim + enterprise stubs.

OSS settings (ExecutionMode, surface constants) moved to amprealize.projects.settings.
Enterprise stubs (SettingsService, OrgSettings, etc.) remain here.
"""

# Re-export OSS settings from canonical location
from amprealize.projects.settings import ExecutionMode, LOCAL_CAPABLE_SURFACES, REMOTE_ONLY_SURFACES  # noqa: F401


# Enterprise: Settings service and models (stubs — enterprise fork provides real impls)

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
