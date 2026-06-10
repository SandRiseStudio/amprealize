"""
MCP Tool Groups and Lazy Loading Configuration

Following MCP best practices:
1. Focus on Outcomes, Not Operations - High-level tools that orchestrate multiple operations
2. Curate and Name for Discovery - 5-15 tools per active group
3. Service-Prefixed Naming - {service}_{action}_{resource} pattern

Tool groups are loaded dynamically based on context, keeping the active tool count < 128.
"""

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set


def _whiteboard_enabled() -> bool:
    """Check if the whiteboard/brainstorm feature is enabled via env var."""
    return os.getenv("AMPREALIZE_ENABLE_WHITEBOARD", "").lower() in ("true", "1", "yes")


class ToolGroupId(str, Enum):
    """Identifiers for tool groups that can be activated on demand."""

    # Always loaded (core functionality)
    CORE = "core"

    # User-activated groups (via activate_* tools)
    ANALYTICS = "analytics"
    ADMIN = "admin"
    AGENTS = "agents"
    COMPLIANCE = "compliance"
    DEVELOPMENT = "development"
    EXECUTION = "execution"

    # Advanced/specialized groups
    BCI = "bci"
    FINE_TUNING = "fine_tuning"
    GITHUB = "github"
    INFRASTRUCTURE = "infrastructure"
    BILLING = "billing"
    KNOWLEDGE_PACKS = "knowledge_packs"
    PROJECTS = "projects"
    BEHAVIORS = "behaviors"
    AUTHORIZATION = "authorization"
    WORK_ITEMS = "work_items"
    COMMUNICATION = "communication"
    WHITEBOARD = "whiteboard"
    RESEARCH = "research"
    WIKI = "wiki"


@dataclass
class ToolGroup:
    """Configuration for a group of related tools."""

    id: ToolGroupId
    name: str
    description: str
    tool_prefixes: List[str]  # Tool name prefixes to include (e.g., ["analytics.", "metrics."])
    max_tools: int = 25  # Max tools to load from this group
    priority: int = 100  # Lower = higher priority when pruning
    requires_auth: bool = True
    activation_keywords: List[str] = field(default_factory=list)  # Keywords that auto-activate this group


# Optional prefix-based core loading. Kept for future opt-in families, but the
# default core is intentionally an exact fast-path allowlist so Cursor doesn't
# ingest every mutating/admin schema at startup.
CORE_TOOL_PREFIXES: List[str] = []

# Exact tools that are ALWAYS loaded for Cursor/agent startup.
CORE_TOOLS: Set[str] = {
    # Authentication/session bootstrap
    "auth.authStatus",
    "auth.deviceInit",
    "auth.devicePoll",
    "auth.deviceLogin",
    "auth.clientCredentials",
    "auth.refresh",
    "auth.refreshToken",
    "auth.logout",

    # Active tenant/project context
    "context.getContext",
    "context.setOrg",
    "context.setProject",
    "context.clearContext",
    "orgs.list",
    "orgs.get",
    "orgs.getContext",
    "orgs.switch",
    "orgs.projects",
    "projects.list",
    "projects.get",
    "projects.switch",

    # Boards and work items: common read/start-work path
    "boards.list",
    "boards.get",
    "boards.create",
    "boards.update",
    "workItems.list",
    "workItems.get",
    "workItems.getBatch",
    "workItems.create",
    "workItems.update",

    # Behavior retrieval essentials
    "behaviors.getForTask",
    "behaviors.search",
    "behaviors.get",
    "behaviors.list",
    "behavior.analyzeAndRetrieve",

    # Wiki read/query/status essentials
    "wiki.list_pages",
    "wiki.read_page",
    "ai_learning_wiki.query",
    "ai_learning_wiki.status",
    "research_wiki.query",
    "research_wiki.status",
    "infra_wiki.query",
    "infra_wiki.status",
    "platform_wiki.query",
    "platform_wiki.status",

    # MCP self-management
    "tools.guide",
    "tools.catalog",
    "tools.listGroups",
    "tools.activateGroup",
    "tools.deactivateGroup",
    "tools.activeGroups",

    # Lightweight run discovery is commonly useful when Cursor is asked for status.
    "runs.list",
    "runs.get",

    # Action audit / replay (compact platform surface)
    "actions.create",
    "actions.list",
    "actions.get",
    "actions.replay",
    "actions.replayStatus",

    # Lightweight natural-language resource analysis
    "resources.analyze",
}

DEFAULT_STARTUP_TOOL_GROUPS: Set[ToolGroupId] = set()


def get_startup_tool_groups(env: Optional[Dict[str, str]] = None) -> Set[ToolGroupId]:
    """Return extra groups to load at MCP startup.

    Core includes the high-frequency Cursor agent fast path. Specialized
    groups stay lazy by default, but power users can opt in with:

        AMPREALIZE_MCP_STARTUP_GROUPS=analytics,execution
    """
    runtime_env = env or os.environ
    raw = runtime_env.get("AMPREALIZE_MCP_STARTUP_GROUPS")
    if raw is None:
        return set(DEFAULT_STARTUP_TOOL_GROUPS)

    normalized = raw.strip().lower()
    if normalized in {"", "none", "false", "0", "off"}:
        return set()

    groups: Set[ToolGroupId] = set()
    for part in raw.replace(";", ",").split(","):
        value = part.strip().lower()
        if not value:
            continue
        try:
            groups.add(ToolGroupId(value))
        except ValueError:
            continue
    return groups


STARTUP_TOOL_GROUPS: Set[ToolGroupId] = get_startup_tool_groups()

# Tool group definitions
TOOL_GROUPS: Dict[ToolGroupId, ToolGroup] = {
    ToolGroupId.CORE: ToolGroup(
        id=ToolGroupId.CORE,
        name="Core",
        description="Cursor agent fast path: auth, context, lightweight project/work-item discovery, behavior retrieval, wiki reads, and MCP self-management",
        tool_prefixes=CORE_TOOL_PREFIXES,
        max_tools=60,
        priority=0,
        requires_auth=False,
        activation_keywords=["start", "login", "behavior", "project", "context", "work", "wiki", "board", "org"],
    ),

    ToolGroupId.PROJECTS: ToolGroup(
        id=ToolGroupId.PROJECTS,
        name="Projects & Organizations",
        description="Organizations, projects, membership, invitations, and active context selection",
        tool_prefixes=["projects.", "project.", "orgs.", "context."],
        max_tools=35,
        priority=15,
        activation_keywords=["project", "organization", "org", "tenant", "member", "invite", "context", "switch"],
    ),

    ToolGroupId.BEHAVIORS: ToolGroup(
        id=ToolGroupId.BEHAVIORS,
        name="Behavior Management",
        description="Create, update, submit, approve, and retrieve behaviors and behavior-guided prompts",
        tool_prefixes=["behaviors.", "behavior."],
        max_tools=15,
        priority=20,
        activation_keywords=["behavior", "behaviors", "handbook", "proposal", "approve behavior"],
    ),

    ToolGroupId.AUTHORIZATION: ToolGroup(
        id=ToolGroupId.AUTHORIZATION,
        name="Authentication & Consent",
        description="Auth sessions, AgentAuth grants, policy previews, and consent decisions",
        tool_prefixes=["auth.", "consent."],
        max_tools=25,
        priority=25,
        requires_auth=False,
        activation_keywords=["auth", "login", "consent", "grant", "token", "permission", "policy"],
    ),

    ToolGroupId.WORK_ITEMS: ToolGroup(
        id=ToolGroupId.WORK_ITEMS,
        name="Boards & Work Items",
        description="Boards, columns, labels, comments, assignments, and work item planning/execution metadata",
        tool_prefixes=["boards.", "board.", "columns.", "workItems.", "workItem."],
        max_tools=35,
        priority=30,
        activation_keywords=["work item", "workitem", "board", "column", "label", "comment", "gws", "planner"],
    ),

    ToolGroupId.EXECUTION: ToolGroup(
        id=ToolGroupId.EXECUTION,
        name="Execution & Workflows",
        description="Runs, workflows, actions, and execution control",
        tool_prefixes=["runs.", "workflow.", "actions.", "executionConnector."],
        max_tools=25,
        priority=35,
        activation_keywords=["run", "workflow", "execute", "execution", "action", "replay", "status"],
    ),

    ToolGroupId.WIKI: ToolGroup(
        id=ToolGroupId.WIKI,
        name="Wiki",
        description="Manage LLM-maintained wikis for research, infra, platform, and AI-learning domains",
        tool_prefixes=["wiki.", "research_wiki.", "infra_wiki.", "platform_wiki.", "ai_learning_wiki."],
        max_tools=22,
        priority=37,
        activation_keywords=["wiki", "ingest", "lint", "learning path", "explain concept", "infra docs", "platform docs"],
    ),

    ToolGroupId.RESEARCH: ToolGroup(
        id=ToolGroupId.RESEARCH,
        name="AI Research",
        description="Evaluate research papers/articles through the 4-phase pipeline and retrieve past evaluations",
        tool_prefixes=["research."],
        max_tools=10,
        priority=38,
        activation_keywords=["research", "paper", "evaluate", "arxiv", "article", "study"],
    ),

    ToolGroupId.COMMUNICATION: ToolGroup(
        id=ToolGroupId.COMMUNICATION,
        name="Collaboration & Messaging",
        description="Workspace collaboration, conversations, and message operations",
        tool_prefixes=["collaboration.", "conversations.", "messages."],
        max_tools=15,
        priority=39,
        activation_keywords=["conversation", "message", "chat", "thread", "reaction", "collaboration", "workspace"],
    ),

    ToolGroupId.COMPLIANCE: ToolGroup(
        id=ToolGroupId.COMPLIANCE,
        name="Compliance & Audit",
        description="Policy management, audit trails, compliance validation, and security scanning",
        tool_prefixes=["compliance.", "compliance/", "audit.", "security."],
        max_tools=22,
        priority=40,
        activation_keywords=["compliance", "audit", "policy", "security", "scan", "validate"],
    ),

    ToolGroupId.KNOWLEDGE_PACKS: ToolGroup(
        id=ToolGroupId.KNOWLEDGE_PACKS,
        name="Knowledge Packs",
        description="Build, validate, inspect, bootstrap, and roll back knowledge packs for context injection",
        tool_prefixes=["knowledgePacks.", "pack."],
        max_tools=10,
        priority=42,
        activation_keywords=["knowledge pack", "pack", "overlay", "primer", "context injection", "bootstrap pack"],
    ),

    ToolGroupId.BCI: ToolGroup(
        id=ToolGroupId.BCI,
        name="Behavior-Conditioned Inference",
        description="BCI prompt composition, pattern detection, reflection, retrieval, and token optimization",
        tool_prefixes=["bci.", "patterns.", "reflection.", "retrieval."],
        max_tools=22,
        priority=45,
        activation_keywords=["bci", "prompt", "pattern", "token", "compose", "retrieve", "reflection"],
    ),

    ToolGroupId.ANALYTICS: ToolGroup(
        id=ToolGroupId.ANALYTICS,
        name="Analytics & Metrics",
        description="Cost analysis, performance metrics, ROI tracking, and telemetry dashboards",
        tool_prefixes=["analytics.", "metrics.", "telemetry.", "traces."],
        max_tools=18,
        priority=50,
        activation_keywords=[
            "cost",
            "metrics",
            "analytics",
            "roi",
            "performance",
            "dashboard",
            "trend",
            "telemetry",
            "trace",
            "span",
            "observability",
        ],
    ),

    ToolGroupId.INFRASTRUCTURE: ToolGroup(
        id=ToolGroupId.INFRASTRUCTURE,
        name="Infrastructure & Environments",
        description="BreakerAmp blueprints, environment management, Raze logging, and bootstrap operations",
        tool_prefixes=["breakeramp.", "raze.", "bootstrap."],
        max_tools=20,
        priority=55,
        activation_keywords=["environment", "blueprint", "container", "deploy", "log", "raze", "bootstrap"],
    ),

    ToolGroupId.DEVELOPMENT: ToolGroup(
        id=ToolGroupId.DEVELOPMENT,
        name="Development Tools",
        description="File operations, GitHub integration, and code management",
        tool_prefixes=["files.", "github."],
        max_tools=10,
        priority=60,
        activation_keywords=["file", "github", "commit", "branch", "diff", "pr", "pull request"],
    ),

    ToolGroupId.GITHUB: ToolGroup(
        id=ToolGroupId.GITHUB,
        name="GitHub Integration",
        description="GitHub repository operations, commits, and pull requests",
        tool_prefixes=["github."],
        max_tools=10,
        priority=70,
        activation_keywords=["github", "commit", "pull request", "branch", "repository"],
    ),

    ToolGroupId.ADMIN: ToolGroup(
        id=ToolGroupId.ADMIN,
        name="Administration",
        description="Billing, rate limits, tenants, flags, and system configuration",
        tool_prefixes=[
            "billing.", "config.", "flags.", "tenants.",
            "ratelimit.", "rate-limits.", "mcp-rate-limits.", "ratelimit_",
        ],
        max_tools=25,
        priority=80,
        activation_keywords=["billing", "subscription", "rate limit", "tenant", "admin", "configure", "feature flag"],
    ),

    ToolGroupId.BILLING: ToolGroup(
        id=ToolGroupId.BILLING,
        name="Billing & Subscription",
        description="Subscription management, invoices, and usage tracking",
        tool_prefixes=["billing."],
        max_tools=10,
        priority=85,
        activation_keywords=["billing", "subscription", "invoice", "payment", "plan"],
    ),

    ToolGroupId.FINE_TUNING: ToolGroup(
        id=ToolGroupId.FINE_TUNING,
        name="Fine-Tuning & Reviews",
        description="Model fine-tuning, behavior reviews, and training data management",
        tool_prefixes=["fine-tuning.", "reviews."],
        max_tools=10,
        priority=90,
        activation_keywords=["fine-tune", "fine tuning", "training", "review"],
    ),

    ToolGroupId.AGENTS: ToolGroup(
        id=ToolGroupId.AGENTS,
        name="Agent Management",
        description="Agent registry, performance monitoring, task assignment, and orchestration",
        tool_prefixes=["agents.", "agentRegistry.", "agentPerformance.", "tasks.", "escalation."],
        max_tools=40,
        priority=95,
        activation_keywords=["agent", "assign", "delegate", "performance", "handoff", "escalate"],
    ),
}

if _whiteboard_enabled():
    TOOL_GROUPS[ToolGroupId.WHITEBOARD] = ToolGroup(
        id=ToolGroupId.WHITEBOARD,
        name="Brainstorm & Whiteboard",
        description="Brainstorm sessions, whiteboard rooms, canvas annotations, and snapshots",
        tool_prefixes=["brainstorm.", "whiteboard."],
        max_tools=15,
        priority=36,
        activation_keywords=["whiteboard", "brainstorm", "canvas", "sticky note", "ideation", "snapshot"],
    )


# High-level outcome-focused tools that replace multiple low-level operations
# Following "Focus on Outcomes, Not Operations" principle
OUTCOME_TOOLS: Dict[str, Dict] = {
    "project.setupComplete": {
        "description": "Set up a complete project with board and team members in one operation",
        "replaces": ["projects.create", "boards.create", "projects.addMember"],
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Project name"},
                "description": {"type": "string", "description": "Project description"},
                "org_id": {"type": "string", "description": "Organization ID"},
                "board_name": {"type": "string", "description": "Default board name (defaults to 'Main Board')"},
                "member_emails": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Email addresses of team members to invite"
                },
            },
            "required": ["name", "org_id"],
        },
    },

    "behavior.analyzeAndRetrieve": {
        "description": "Analyze a task, retrieve relevant behaviors, and get recommendations in one call",
        "replaces": ["behaviors.getForTask", "bci.retrieve", "bci.composePrompt"],
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_description": {"type": "string", "description": "Natural language task description"},
                "role": {
                    "type": "string",
                    "enum": ["Student", "Teacher", "Strategist"],
                    "description": "Agent role for context-appropriate behaviors",
                    "default": "Student",
                },
                "include_prompt": {
                    "type": "boolean",
                    "description": "Whether to compose a BCI prompt",
                    "default": True,
                },
            },
            "required": ["task_description"],
        },
    },

    "workItem.executeWithTracking": {
        "description": "Execute a work item with full progress tracking and automatic status updates",
        "replaces": ["workItems.execute", "runs.updateProgress", "runs.updateStatus", "workItems.moveToColumn"],
        "inputSchema": {
            "type": "object",
            "properties": {
                "work_item_id": {"type": "string", "description": "Work item ID to execute"},
                "agent_id": {"type": "string", "description": "Optional agent ID override"},
                "notify_on_complete": {
                    "type": "boolean",
                    "description": "Whether to send notification on completion",
                    "default": True,
                },
            },
            "required": ["work_item_id"],
        },
    },

    "analytics.fullReport": {
        "description": "Generate a comprehensive analytics report including costs, performance, and ROI",
        "replaces": ["analytics.costByService", "analytics.roiSummary", "analytics.kpiSummary", "analytics.topExpensive"],
        "inputSchema": {
            "type": "object",
            "properties": {
                "org_id": {"type": "string", "description": "Organization ID"},
                "period_days": {
                    "type": "integer",
                    "description": "Number of days to analyze",
                    "default": 30,
                },
                "include_trends": {
                    "type": "boolean",
                    "description": "Include trend analysis",
                    "default": True,
                },
            },
            "required": [],
        },
    },

    "compliance.fullValidation": {
        "description": "Perform comprehensive compliance validation including policies, checklists, and audit trail",
        "replaces": ["compliance.validateByAction", "compliance.validateChecklist", "compliance.auditTrail"],
        "inputSchema": {
            "type": "object",
            "properties": {
                "action_id": {"type": "string", "description": "Action ID to validate"},
                "policy_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific policy IDs to check (empty = all applicable)",
                },
                "generate_audit_trail": {
                    "type": "boolean",
                    "description": "Whether to generate audit trail entry",
                    "default": True,
                },
            },
            "required": ["action_id"],
        },
    },
}


def get_tools_for_group(group_id: ToolGroupId) -> List[str]:
    """Get list of tool prefixes for a specific group."""
    group = TOOL_GROUPS.get(group_id)
    if not group:
        return []
    return group.tool_prefixes


def match_tool_to_group(tool_name: str) -> Optional[ToolGroupId]:
    """Determine which group a tool belongs to based on its name prefix."""
    # Prefer the domain-specific group over CORE. CORE is an activation
    # surface, not the canonical catalog classification for auth/projects/
    # work-items/behaviors/wiki tools.
    for group_id, group in TOOL_GROUPS.items():
        if group_id == ToolGroupId.CORE:
            continue
        for prefix in group.tool_prefixes:
            if tool_name.startswith(prefix):
                return group_id
    if tool_name in CORE_TOOLS or any(tool_name.startswith(prefix) for prefix in CORE_TOOL_PREFIXES):
        return ToolGroupId.CORE
    return None


def suggest_groups_for_query(query: str) -> List[ToolGroupId]:
    """Suggest relevant tool groups based on a natural language query."""
    query_lower = query.lower()
    suggestions = []

    for group_id, group in TOOL_GROUPS.items():
        for keyword in group.activation_keywords:
            if keyword in query_lower:
                suggestions.append(group_id)
                break

    return suggestions


def get_max_tools_budget() -> int:
    """Get the maximum number of tools to expose at once (model constraint)."""
    return 120  # Leave headroom below 128 limit


def calculate_tool_allocation(active_groups: Set[ToolGroupId]) -> Dict[ToolGroupId, int]:
    """Calculate how many tools each active group should contribute.

    Ensures total stays below budget while respecting priorities.
    """
    budget = get_max_tools_budget()

    # Always include core
    active = {ToolGroupId.CORE} | active_groups

    # Sort by priority (lower = higher priority)
    sorted_groups = sorted(
        [TOOL_GROUPS[g] for g in active if g in TOOL_GROUPS],
        key=lambda g: g.priority
    )

    allocation: Dict[ToolGroupId, int] = {}
    remaining = budget

    for group in sorted_groups:
        # Allocate up to max_tools or remaining budget
        alloc = min(group.max_tools, remaining)
        allocation[group.id] = alloc
        remaining -= alloc

        if remaining <= 0:
            break

    return allocation
