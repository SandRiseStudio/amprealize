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


# Core tools that are ALWAYS loaded (essential for basic operation)
# These follow the "Ruthless Curation" principle - only the most essential tools
CORE_TOOLS: Set[str] = {
    # Authentication (required for everything)
    "auth.deviceInit",
    "auth.devicePoll",
    "auth.deviceLogin",
    "auth.authStatus",
    "auth.refreshToken",
    "auth.logout",

    # Essential behavior tools (core to Amprealize value)
    "behaviors.getForTask",
    "behaviors.get",
    "behaviors.list",
    "behaviors.create",
    "behaviors.search",
    "behaviors.update",
    "behaviors.submit",
    "behaviors.approve",
    "behaviors.deprecate",
    "behaviors.deleteDraft",

    # Project/Org basics
    "projects.list",
    "projects.get",
    "projects.create",
    "orgs.list",
    "orgs.get",

    # Work items basics
    "workItems.list",
    "workItems.get",
    "workItems.create",
    "workItems.update",
    "workItems.delete",
    "workItems.execute",

    # Board basics (discover boards for work item placement)
    "boards.list",
    "boards.get",

    # Runs basics
    "runs.list",
    "runs.get",
    "runs.create",

    # Whiteboard + brainstorm basics (conditionally included when feature is enabled)
    # See _whiteboard_enabled() — tools are added dynamically below.

    # Context management
    "context.getContext",
    "context.setOrg",
    "context.setProject",

    # Research tools
    "research.evaluate",
    "research.get",
    "research.search",
    "research.list",

    # Wiki tools (query, status, and CRUD always available)
    "research_wiki.query",
    "research_wiki.status",
    "research_wiki.ingest",
    "infra_wiki.query",
    "infra_wiki.status",
    "infra_wiki.ingest",
    "ai_learning_wiki.query",
    "ai_learning_wiki.explain",
    "ai_learning_wiki.status",
    "ai_learning_wiki.ingest",
    "ai_learning_wiki.path",
    "wiki.create_page",
    "wiki.read_page",
    "wiki.update_page",
    "wiki.delete_page",
    "wiki.list_pages",

    # Tool group activation (meta-tools)
    "tools.listGroups",
    "tools.activateGroup",
    "tools.deactivateGroup",
    "tools.activeGroups",
}

# Conditionally include whiteboard + brainstorm tools when the feature is enabled
if _whiteboard_enabled():
    CORE_TOOLS |= {
        "whiteboard.createRoom",
        "whiteboard.readCanvas",
        "whiteboard.addShape",
        "whiteboard.annotate",
        "brainstorm.openWhiteboard",
        "brainstorm.addIdea",
        "brainstorm.summarizeBoard",
        "brainstorm.closeSession",
    }


# Tool group definitions
TOOL_GROUPS: Dict[ToolGroupId, ToolGroup] = {
    ToolGroupId.CORE: ToolGroup(
        id=ToolGroupId.CORE,
        name="Core",
        description="Essential Amprealize tools always available",
        tool_prefixes=[
            "auth.", "behaviors.", "projects.", "orgs.", "workItems.", "runs.", "context.", "boards.",
        ] + (["whiteboard.", "brainstorm."] if _whiteboard_enabled() else []),
        max_tools=80,  # Must be >= len(CORE_TOOLS); bumped for wiki CRUD + brainstorm/whiteboard tools
        priority=0,  # Highest priority
        requires_auth=False,  # Auth tools don't require auth
        activation_keywords=[
            "start", "login", "behavior", "project", "work",
        ] + (["whiteboard", "brainstorm"] if _whiteboard_enabled() else []),
    ),

    ToolGroupId.ANALYTICS: ToolGroup(
        id=ToolGroupId.ANALYTICS,
        name="Analytics & Metrics",
        description="Cost analysis, performance metrics, ROI tracking, and telemetry dashboards",
        tool_prefixes=["analytics.", "metrics.", "telemetry."],
        max_tools=15,
        priority=50,
        activation_keywords=["cost", "metrics", "analytics", "roi", "performance", "dashboard", "trend"],
    ),

    ToolGroupId.ADMIN: ToolGroup(
        id=ToolGroupId.ADMIN,
        name="Administration",
        description="Billing, rate limits, tenants, and system configuration",
        tool_prefixes=["billing.", "ratelimit.", "rate-limits.", "mcp-rate-limits.", "tenants.", "config."],
        max_tools=20,
        priority=80,
        activation_keywords=["billing", "subscription", "rate limit", "tenant", "admin", "configure"],
    ),

    ToolGroupId.AGENTS: ToolGroup(
        id=ToolGroupId.AGENTS,
        name="Agent Management",
        description="Agent registry, performance monitoring, task assignment, and orchestration",
        tool_prefixes=["agents.", "agentRegistry.", "agentPerformance.", "tasks.", "escalation."],
        max_tools=30,
        priority=30,
        activation_keywords=["agent", "assign", "delegate", "performance", "handoff", "escalate"],
    ),

    ToolGroupId.COMPLIANCE: ToolGroup(
        id=ToolGroupId.COMPLIANCE,
        name="Compliance & Audit",
        description="Policy management, audit trails, compliance validation, and security scanning",
        tool_prefixes=["compliance.", "audit.", "security."],
        max_tools=20,
        priority=40,
        activation_keywords=["compliance", "audit", "policy", "security", "scan", "validate"],
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

    ToolGroupId.EXECUTION: ToolGroup(
        id=ToolGroupId.EXECUTION,
        name="Execution & Workflows",
        description="Workflow management, board operations, and execution control",
        tool_prefixes=[
            "workflow.", "boards.", "board.", "actions.", "consent.",
        ] + (["whiteboard.", "brainstorm."] if _whiteboard_enabled() else []),
        max_tools=35,
        priority=35,
        activation_keywords=[
            "workflow", "board", "execute", "action", "consent", "replay",
        ] + (["whiteboard", "brainstorm", "canvas", "sticky note", "ideation"] if _whiteboard_enabled() else []),
    ),

    ToolGroupId.BCI: ToolGroup(
        id=ToolGroupId.BCI,
        name="Behavior-Conditioned Inference",
        description="BCI prompt composition, pattern detection, and token optimization",
        tool_prefixes=["bci.", "patterns.", "reflection.", "retrieval."],
        max_tools=20,
        priority=45,
        activation_keywords=["bci", "prompt", "pattern", "token", "compose", "retrieve", "reflection"],
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

    ToolGroupId.GITHUB: ToolGroup(
        id=ToolGroupId.GITHUB,
        name="GitHub Integration",
        description="GitHub repository operations, commits, and pull requests",
        tool_prefixes=["github."],
        max_tools=10,
        priority=70,
        activation_keywords=["github", "commit", "pull request", "branch", "repository"],
    ),

    ToolGroupId.INFRASTRUCTURE: ToolGroup(
        id=ToolGroupId.INFRASTRUCTURE,
        name="Infrastructure & Environments",
        description="BreakerAmp blueprints, environment management, and logging",
        tool_prefixes=["breakeramp.", "raze."],
        max_tools=15,
        priority=55,
        activation_keywords=["environment", "blueprint", "container", "deploy", "log", "raze"],
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

    ToolGroupId.KNOWLEDGE_PACKS: ToolGroup(
        id=ToolGroupId.KNOWLEDGE_PACKS,
        name="Knowledge Packs",
        description="Build, validate, inspect, and manage knowledge packs for context injection",
        tool_prefixes=["knowledgePacks."],
        max_tools=10,
        priority=42,
        activation_keywords=["knowledge pack", "pack", "overlay", "primer", "context injection"],
    ),

    ToolGroupId.RESEARCH: ToolGroup(
        id=ToolGroupId.RESEARCH,
        name="AI Research",
        description="Evaluate research papers/articles through 4-phase pipeline, search and retrieve past evaluations",
        tool_prefixes=["research."],
        max_tools=10,
        priority=38,
        activation_keywords=["research", "paper", "evaluate", "arxiv", "article", "study"],
    ),

    ToolGroupId.WIKI: ToolGroup(
        id=ToolGroupId.WIKI,
        name="Wiki",
        description="Manage LLM-maintained wikis: ingest, query, lint, and status for research, infra, and AI-learning domains",
        tool_prefixes=["wiki.", "research_wiki.", "infra_wiki.", "ai_learning_wiki."],
        max_tools=19,
        priority=37,
        activation_keywords=["wiki", "ingest", "lint", "learning path", "explain concept", "infra docs"],
    ),
}


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
    for group_id, group in TOOL_GROUPS.items():
        for prefix in group.tool_prefixes:
            if tool_name.startswith(prefix):
                return group_id
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
