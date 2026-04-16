"""Work Item Execution Contracts - Data models for agent-executed work items.

Defines data models for the Work Item Execution system per WORK_ITEM_EXECUTION_PLAN.md:
- Execution policies for agents (phase gates, internet access, write scope, model policy)
- Model catalog and credential resolution
- Execution requests and responses

Integration points:
- WorkItemExecutionService: Orchestrates work item execution
- AgentExecutionLoop: Phase-by-phase execution loop
- AgentLLMClient: LLM abstraction for agent execution
- RunService: Execution tracking
- TaskCycleService: GEP phase state machine
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


# =============================================================================
# Enums
# =============================================================================


class GatePolicyType(str, Enum):
    """Phase gate enforcement types for execution policy."""
    NONE = "none"       # Auto-progress without notification
    SOFT = "soft"       # Auto-progress with notification
    STRICT = "strict"   # Requires explicit human approval


class InternetAccessPolicy(str, Enum):
    """Internet access policy for agent execution."""
    INHERIT = "inherit"     # Inherit from org/project settings
    ENABLED = "enabled"     # Internet access enabled
    DISABLED = "disabled"   # Internet access disabled


class WriteScope(str, Enum):
    """Write target scope for agent execution."""
    READ_ONLY = "read_only"     # No writes allowed
    INHERIT = "inherit"         # Inherit from project settings
    LOCAL_ONLY = "local_only"   # Edit local files only
    PR_ONLY = "pr_only"         # Create branch + commit + PR only
    LOCAL_AND_PR = "local_and_pr"  # Both local changes + open PR


class ExecutionState(str, Enum):
    """State of a work item execution."""
    PENDING = "pending"         # Execution created but not started
    RUNNING = "running"         # Currently executing
    PAUSED = "paused"           # Paused (awaiting human input)
    COMPLETED = "completed"     # Successfully completed
    FAILED = "failed"           # Failed with error
    CANCELLED = "cancelled"     # Cancelled by user


class AgentExecutionMode(str, Enum):
    """High-level execution mode controlling the GEP phase flow.

    GEP (default):
        Full 8-phase Guided Execution Protocol. Best for work-item-driven tasks
        requiring planning, architecture, testing, and verification.
        Flow: PLANNING → ARCHITECTING → EXECUTING → TESTING → VERIFYING → COMPLETING

    SESSION:
        Lightweight conversational mode for ad-hoc agent interactions.
        Skips heavy phases, uses SOFT gates only. Best for exploratory tasks,
        quick code edits, research, and interactive conversations.
        Flow: PLANNING → EXECUTING → COMPLETING
    """
    GEP = "gep"
    SESSION = "session"


class ToolPermissionLevel(str, Enum):
    """Per-tool permission level for fine-grained access control.

    Inspired by Claude Managed Agents' tool permission model.

    ALWAYS_ALLOW:
        Tool executes without confirmation. Default for read-only tools.

    REQUIRE_CONFIRMATION:
        Tool requires explicit user confirmation before execution.
        In automated contexts, treated as allowed with audit logging.

    DENY:
        Tool is completely blocked from execution.
    """
    ALWAYS_ALLOW = "always_allow"
    REQUIRE_CONFIRMATION = "require_confirmation"
    DENY = "deny"


# Default per-tool permissions for Session Mode
SESSION_MODE_TOOL_PERMISSIONS: Dict[str, ToolPermissionLevel] = {
    # Read-only tools — always allow
    "read_file": ToolPermissionLevel.ALWAYS_ALLOW,
    "list_directory": ToolPermissionLevel.ALWAYS_ALLOW,
    "search_files": ToolPermissionLevel.ALWAYS_ALLOW,
    "fetch_url": ToolPermissionLevel.ALWAYS_ALLOW,
    "search_web": ToolPermissionLevel.ALWAYS_ALLOW,
    "research_evaluate": ToolPermissionLevel.ALWAYS_ALLOW,
    # Write tools — require confirmation
    "write_file": ToolPermissionLevel.REQUIRE_CONFIRMATION,
    "edit_file": ToolPermissionLevel.REQUIRE_CONFIRMATION,
    "delete_file": ToolPermissionLevel.REQUIRE_CONFIRMATION,
    # Terminal — require confirmation
    "run_in_terminal": ToolPermissionLevel.REQUIRE_CONFIRMATION,
}


class LLMProvider(str, Enum):
    """Supported LLM providers."""
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    OPENROUTER = "openrouter"
    LOCAL = "local"


# =============================================================================
# Model Catalog
# =============================================================================


@dataclass
class ModelDefinition:
    """Definition of an LLM model in the catalog."""
    model_id: str                      # e.g., "claude-opus-4-5" (internal ID)
    api_name: str                      # e.g., "claude-sonnet-4-20250514" (actual API model name)
    provider: LLMProvider
    display_name: str
    supports_tool_calls: bool = True
    context_limit: int = 200000        # Max context window tokens
    max_output_tokens: int = 16384
    output_limit: int = 16384          # Alias for max_output_tokens (used by adapters)
    input_price_per_m: float = 0.0     # USD per 1M input tokens
    output_price_per_m: float = 0.0    # USD per 1M output tokens
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "api_name": self.api_name,
            "provider": self.provider.value,
            "display_name": self.display_name,
            "supports_tool_calls": self.supports_tool_calls,
            "context_limit": self.context_limit,
            "max_output_tokens": self.max_output_tokens,
            "input_price_per_m": self.input_price_per_m,
            "output_price_per_m": self.output_price_per_m,
            "metadata": self.metadata,
        }


# Model Catalog - Static definitions of supported models
MODEL_CATALOG: Dict[str, ModelDefinition] = {
    "claude-opus-4-6": ModelDefinition(
        model_id="claude-opus-4-6",
        api_name="claude-opus-4-20260201",  # Actual Anthropic API model name
        provider=LLMProvider.ANTHROPIC,
        display_name="Claude Opus 4.6",
        supports_tool_calls=True,
        context_limit=200000,
        max_output_tokens=32768,
        output_limit=32768,
        input_price_per_m=15.0,
        output_price_per_m=75.0,
    ),
    "claude-opus-4-5": ModelDefinition(
        model_id="claude-opus-4-5",
        api_name="claude-opus-4-20250514",  # Actual Anthropic API model name
        provider=LLMProvider.ANTHROPIC,
        display_name="Claude Opus 4.5",
        supports_tool_calls=True,
        context_limit=200000,
        max_output_tokens=32768,
        output_limit=32768,
        input_price_per_m=15.0,
        output_price_per_m=75.0,
    ),
    "claude-sonnet-4-5": ModelDefinition(
        model_id="claude-sonnet-4-5",
        api_name="claude-sonnet-4-20250514",  # Actual Anthropic API model name
        provider=LLMProvider.ANTHROPIC,
        display_name="Claude Sonnet 4.5",
        supports_tool_calls=True,
        context_limit=200000,
        max_output_tokens=16384,
        output_limit=16384,
        input_price_per_m=3.0,
        output_price_per_m=15.0,
    ),
    "gpt-5-2": ModelDefinition(
        model_id="gpt-5-2",
        api_name="gpt-4o",  # Use gpt-4o as placeholder until GPT-5.2 is available
        provider=LLMProvider.OPENAI,
        display_name="GPT-5.2",
        supports_tool_calls=True,
        context_limit=128000,
        max_output_tokens=16384,
        output_limit=16384,
        input_price_per_m=10.0,
        output_price_per_m=30.0,
    ),
    "gpt-4o": ModelDefinition(
        model_id="gpt-4o",
        api_name="gpt-4o",  # Actual OpenAI API model name
        provider=LLMProvider.OPENAI,
        display_name="GPT-4o",
        supports_tool_calls=True,
        context_limit=128000,
        max_output_tokens=16384,
        output_limit=16384,
        input_price_per_m=2.5,
        output_price_per_m=10.0,
    ),
    "claude-3-5-sonnet": ModelDefinition(
        model_id="claude-3-5-sonnet",
        api_name="claude-3-5-sonnet-20241022",  # Actual Anthropic API model name
        provider=LLMProvider.ANTHROPIC,
        display_name="Claude 3.5 Sonnet",
        supports_tool_calls=True,
        context_limit=200000,
        max_output_tokens=8192,
        output_limit=8192,
        input_price_per_m=3.0,
        output_price_per_m=15.0,
    ),
}


def get_model(model_id: str) -> Optional[ModelDefinition]:
    """Get a model from the catalog by ID."""
    return MODEL_CATALOG.get(model_id)


def list_models() -> List[ModelDefinition]:
    """List all models in the catalog."""
    return list(MODEL_CATALOG.values())


# =============================================================================
# Execution Policy
# =============================================================================


@dataclass
class ModelPolicy:
    """Model policy for agent execution."""
    preferred_model_id: str = "claude-opus-4-6"
    fallback_model_ids: List[str] = field(default_factory=lambda: ["claude-sonnet-4-5", "gpt-4o"])
    allow_mid_run_switching: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "preferred_model_id": self.preferred_model_id,
            "fallback_model_ids": self.fallback_model_ids,
            "allow_mid_run_switching": self.allow_mid_run_switching,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelPolicy":
        return cls(
            preferred_model_id=data.get("preferred_model_id", "claude-opus-4-6"),
            fallback_model_ids=data.get("fallback_model_ids", ["gpt-4o"]),
            allow_mid_run_switching=data.get("allow_mid_run_switching", True),
        )


@dataclass
class ExecutionPolicy:
    """Configurable execution policy for an agent.

    Defines how an agent executes work items, including:
    - Phase gates: which GEP phases require human approval
    - Internet access: whether the agent can access the web
    - Write scope: where the agent can write (local, PR, both)
    - Model policy: preferred models and fallback options
    - Timeouts and iteration limits
    """
    # Phase gates (GEP phase -> gate type)
    phase_gates: Dict[str, GatePolicyType] = field(default_factory=lambda: {
        "planning": GatePolicyType.NONE,
        "clarifying": GatePolicyType.SOFT,
        "architecting": GatePolicyType.STRICT,
        "executing": GatePolicyType.NONE,
        "testing": GatePolicyType.SOFT,
        "fixing": GatePolicyType.SOFT,
        "verifying": GatePolicyType.STRICT,
        "completing": GatePolicyType.STRICT,
    })

    # Access policies
    internet_access: InternetAccessPolicy = InternetAccessPolicy.INHERIT
    write_scope: WriteScope = WriteScope.INHERIT

    # Model selection
    model_policy: ModelPolicy = field(default_factory=ModelPolicy)

    # Limits
    max_test_iterations: int = 10          # Max TESTING→FIXING loops
    max_total_steps: int = 100             # Max steps in a single run
    phase_timeout_minutes: int = 60        # Max time per phase
    total_timeout_minutes: int = 480       # Max total execution time (8 hours)

    # Phase skipping (agent-specific)
    skip_phases: Set[str] = field(default_factory=set)  # Phases to skip (e.g., {"testing", "fixing"})

    # Workspace provisioning (controls whether to provision isolated workspace)
    require_workspace: bool = True  # False for read-only research tasks

    # Per-tool permission policies (tool_name -> permission level)
    # Tools not listed default to ALWAYS_ALLOW in GEP and REQUIRE_CONFIRMATION in SESSION
    tool_permissions: Dict[str, "ToolPermissionLevel"] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "phase_gates": {k: v.value for k, v in self.phase_gates.items()},
            "internet_access": self.internet_access.value,
            "write_scope": self.write_scope.value,
            "model_policy": self.model_policy.to_dict(),
            "max_test_iterations": self.max_test_iterations,
            "max_total_steps": self.max_total_steps,
            "phase_timeout_minutes": self.phase_timeout_minutes,
            "total_timeout_minutes": self.total_timeout_minutes,
            "skip_phases": list(self.skip_phases),
            "require_workspace": self.require_workspace,
            "tool_permissions": {k: v.value for k, v in self.tool_permissions.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionPolicy":
        phase_gates = {}
        for k, v in data.get("phase_gates", {}).items():
            phase_gates[k] = GatePolicyType(v) if isinstance(v, str) else v

        tool_permissions = {}
        for k, v in data.get("tool_permissions", {}).items():
            tool_permissions[k] = ToolPermissionLevel(v) if isinstance(v, str) else v

        return cls(
            phase_gates=phase_gates or cls().phase_gates,
            internet_access=InternetAccessPolicy(data.get("internet_access", "inherit")),
            write_scope=WriteScope(data.get("write_scope", "inherit")),
            model_policy=ModelPolicy.from_dict(data.get("model_policy", {})),
            max_test_iterations=data.get("max_test_iterations", 10),
            max_total_steps=data.get("max_total_steps", 100),
            phase_timeout_minutes=data.get("phase_timeout_minutes", 60),
            total_timeout_minutes=data.get("total_timeout_minutes", 480),
            skip_phases=set(data.get("skip_phases", [])),
            require_workspace=data.get("require_workspace", True),
            tool_permissions=tool_permissions,
        )

    @classmethod
    def fully_autonomous(cls) -> "ExecutionPolicy":
        """Create a fully autonomous execution policy (no human gates)."""
        return cls(
            phase_gates={
                "planning": GatePolicyType.NONE,
                "clarifying": GatePolicyType.NONE,
                "architecting": GatePolicyType.NONE,
                "executing": GatePolicyType.NONE,
                "testing": GatePolicyType.NONE,
                "fixing": GatePolicyType.NONE,
                "verifying": GatePolicyType.NONE,
                "completing": GatePolicyType.NONE,
            }
        )

    @classmethod
    def for_research_agent(cls) -> "ExecutionPolicy":
        """Create execution policy for research agents.

        Research agents skip TESTING/FIXING/VERIFYING phases since they produce
        analysis and recommendations, not code that needs testing.

        They use the local project directory (no isolated workspace) since
        research tasks only READ files and don't execute/build code.
        """
        return cls(
            phase_gates={
                "planning": GatePolicyType.NONE,
                "clarifying": GatePolicyType.NONE,
                "architecting": GatePolicyType.NONE,
                "executing": GatePolicyType.NONE,
                "testing": GatePolicyType.NONE,
                "fixing": GatePolicyType.NONE,
                "verifying": GatePolicyType.NONE,
                "completing": GatePolicyType.NONE,
            },
            skip_phases={"testing", "fixing", "verifying"},
            internet_access=InternetAccessPolicy.ENABLED,  # Research agents need web access
            write_scope=WriteScope.READ_ONLY,  # Research agents don't write code
            require_workspace=False,  # Use local project directory (no container)
        )

    @classmethod
    def for_architect_agent(cls) -> "ExecutionPolicy":
        """Create execution policy for architect agents.

        Architect agents skip TESTING/FIXING phases since they produce ADRs
        and architectural documents, not executable code.
        """
        return cls(
            phase_gates={
                "planning": GatePolicyType.NONE,
                "clarifying": GatePolicyType.SOFT,  # May need clarification
                "architecting": GatePolicyType.NONE,
                "executing": GatePolicyType.NONE,
                "testing": GatePolicyType.NONE,
                "fixing": GatePolicyType.NONE,
                "verifying": GatePolicyType.SOFT,  # Review before completing
                "completing": GatePolicyType.NONE,
            },
            skip_phases={"testing", "fixing"},
        )

    @classmethod
    def for_engineering_agent(cls) -> "ExecutionPolicy":
        """Create execution policy for engineering agents.

        Engineering agents run all phases including TESTING/FIXING.
        """
        return cls(
            phase_gates={
                "planning": GatePolicyType.NONE,
                "clarifying": GatePolicyType.SOFT,
                "architecting": GatePolicyType.SOFT,
                "executing": GatePolicyType.NONE,
                "testing": GatePolicyType.NONE,
                "fixing": GatePolicyType.NONE,
                "verifying": GatePolicyType.STRICT,  # Require verification review
                "completing": GatePolicyType.NONE,
            },
            skip_phases=set(),  # Run all phases
        )

    @classmethod
    def for_session_mode(cls) -> "ExecutionPolicy":
        """Create execution policy for Session Mode (lightweight agent loop).

        Session Mode skips heavy GEP phases (CLARIFYING, ARCHITECTING,
        TESTING, FIXING, VERIFYING) for a fast PLANNING → EXECUTING →
        COMPLETING flow. All gates are SOFT (notify-only, never block).

        Best for:
        - Ad-hoc conversational tasks
        - Quick code edits and exploratory research
        - Interactive agent sessions via MCP/CLI/Web Console
        """
        return cls(
            phase_gates={
                "planning": GatePolicyType.SOFT,
                "clarifying": GatePolicyType.NONE,
                "architecting": GatePolicyType.NONE,
                "executing": GatePolicyType.SOFT,
                "testing": GatePolicyType.NONE,
                "fixing": GatePolicyType.NONE,
                "verifying": GatePolicyType.NONE,
                "completing": GatePolicyType.SOFT,
            },
            skip_phases={"clarifying", "architecting", "testing", "fixing", "verifying"},
            internet_access=InternetAccessPolicy.ENABLED,
            require_workspace=False,  # Use local context, no isolated container
            tool_permissions=dict(SESSION_MODE_TOOL_PERMISSIONS),
        )


# =============================================================================
# Credential Store
# =============================================================================


@dataclass
class ModelCredential:
    """Credential for accessing an LLM provider."""
    credential_id: str
    provider: LLMProvider
    api_key: str                       # Encrypted/masked in responses
    scope: str                         # "platform", "org:<id>", "project:<id>"
    scope_id: Optional[str] = None     # Org or project ID
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    is_byok: bool = False              # Bring Your Own Key
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self, mask_key: bool = True) -> Dict[str, Any]:
        return {
            "credential_id": self.credential_id,
            "provider": self.provider.value,
            "api_key": "****" if mask_key else self.api_key,
            "scope": self.scope,
            "scope_id": self.scope_id,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "is_byok": self.is_byok,
            "metadata": self.metadata,
        }


@dataclass
class AvailableModel:
    """A model that is available for use in a project."""
    model: ModelDefinition
    credential_source: str             # "platform", "org", "project"
    credential_id: str
    is_byok: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model": self.model.to_dict(),
            "credential_source": self.credential_source,
            "credential_id": self.credential_id,
            "is_byok": self.is_byok,
        }


# =============================================================================
# Request/Response Types
# =============================================================================


@dataclass
class ExecuteWorkItemRequest:
    """Request to execute a work item."""
    work_item_id: str
    user_id: str                       # User triggering execution
    org_id: Optional[str] = None
    project_id: Optional[str] = None

    # Actor surface (where execution was initiated from)
    actor_surface: str = "api"         # "web", "api", "cli", "vscode", "mcp"

    # Optional overrides
    model_id: Optional[str] = None     # Override agent's preferred model
    execution_policy: Optional[ExecutionPolicy] = None  # Override agent's policy
    agent_execution_mode: Optional[AgentExecutionMode] = None  # GEP (default) or SESSION
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecuteWorkItemResponse:
    """Response from executing a work item."""
    run_id: str
    cycle_id: str
    work_item_id: str
    agent_id: str
    model_id: str
    status: ExecutionState
    phase: str
    created_at: str
    message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "cycle_id": self.cycle_id,
            "work_item_id": self.work_item_id,
            "agent_id": self.agent_id,
            "model_id": self.model_id,
            "status": self.status.value,
            "phase": self.phase,
            "created_at": self.created_at,
            "message": self.message,
        }


@dataclass
class ExecutionStatusResponse:
    """Status of a work item execution."""
    run_id: str
    cycle_id: str
    work_item_id: str
    status: ExecutionState
    phase: str
    progress_pct: float
    current_step: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    model_id: Optional[str] = None
    step_count: int = 0
    pending_clarifications: Optional[List[Dict[str, Any]]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "cycle_id": self.cycle_id,
            "work_item_id": self.work_item_id,
            "status": self.status.value,
            "phase": self.phase,
            "progress_pct": self.progress_pct,
            "current_step": self.current_step,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "model_id": self.model_id,
            "step_count": self.step_count,
            "pending_clarifications": self.pending_clarifications,
        }


@dataclass
class WorkItemComment:
    """Comment on a work item (used for execution summaries)."""
    comment_id: str
    work_item_id: str
    author_id: str                     # User or agent ID
    author_type: str                   # "user" or "agent"
    content: str
    created_at: str
    run_id: Optional[str] = None       # Link to execution run
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "comment_id": self.comment_id,
            "work_item_id": self.work_item_id,
            "author_id": self.author_id,
            "author_type": self.author_type,
            "content": self.content,
            "created_at": self.created_at,
            "run_id": self.run_id,
            "metadata": self.metadata,
        }


# =============================================================================
# Agent LLM Response Types
# =============================================================================


@dataclass
class ToolCall:
    """A tool call requested by the agent."""
    tool_name: str
    tool_args: Dict[str, Any]
    call_id: str = field(default_factory=lambda: f"call-{uuid.uuid4().hex[:12]}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "call_id": self.call_id,
        }


@dataclass
class ClarificationQuestion:
    """A clarification question from the agent."""
    question_id: str
    question: str
    context: Optional[str] = None
    required: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question_id": self.question_id,
            "question": self.question,
            "context": self.context,
            "required": self.required,
        }


@dataclass
class AgentResponse:
    """Response from the agent LLM during execution."""
    text_output: str
    tool_calls: List[ToolCall] = field(default_factory=list)
    clarification_questions: List[ClarificationQuestion] = field(default_factory=list)

    # Status flags
    needs_clarification: bool = False
    is_blocked: bool = False
    should_stop: bool = False

    # Phase transition suggestion
    suggested_next_phase: Optional[str] = None
    phase_complete: bool = False

    # Metadata
    model_id: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text_output": self.text_output,
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
            "clarification_questions": [cq.to_dict() for cq in self.clarification_questions],
            "needs_clarification": self.needs_clarification,
            "is_blocked": self.is_blocked,
            "should_stop": self.should_stop,
            "suggested_next_phase": self.suggested_next_phase,
            "phase_complete": self.phase_complete,
            "model_id": self.model_id,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd,
        }


@dataclass
class ToolResult:
    """Result from executing a tool call."""
    call_id: str
    tool_name: str
    success: bool
    output: Any
    error: Optional[str] = None
    duration_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


# =============================================================================
# Execution Step Types
# =============================================================================


class ExecutionStepType(str, Enum):
    """Types of execution steps for logging."""
    PHASE_START = "phase_start"
    PHASE_END = "phase_end"
    PHASE_TRANSITION = "phase_transition"
    LLM_REQUEST = "llm_request"
    LLM_RESPONSE = "llm_response"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    CLARIFICATION_SENT = "clarification_sent"
    CLARIFICATION_RECEIVED = "clarification_received"
    FILE_CHANGE = "file_change"
    PR_CREATED = "pr_created"
    ERROR = "error"
    GATE_WAITING = "gate_waiting"
    GATE_APPROVED = "gate_approved"
    MODEL_SWITCH = "model_switch"


@dataclass
class ExecutionStep:
    """A step in the execution log."""
    step_id: str
    step_type: ExecutionStepType
    phase: str
    timestamp: str
    content: Dict[str, Any]

    # Optional fields
    model_id: Optional[str] = None
    tool_name: Optional[str] = None
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "step_type": self.step_type.value,
            "phase": self.phase,
            "timestamp": self.timestamp,
            "content": self.content,
            "model_id": self.model_id,
            "tool_name": self.tool_name,
            "duration_ms": self.duration_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd,
        }


# =============================================================================
# PR Execution Context
# =============================================================================


class PRCommitStrategy(str, Enum):
    """Strategy for committing file changes during PR execution."""
    SINGLE_COMMIT = "single_commit"         # One commit at completion (cleaner history)
    PER_PHASE = "per_phase"                  # Commit after each phase (for long runs)
    MANUAL = "manual"                        # Agent explicitly triggers commits


@dataclass
class PendingFileChange:
    """A file change pending commit to PR branch.

    Accumulates file changes during execution before committing to GitHub.
    """
    path: str
    content: str
    action: str  # "create", "update", "delete"
    phase: str  # GEP phase where change was made
    timestamp: str
    original_content: Optional[str] = None  # For generating diffs
    encoding: str = "utf-8"  # "utf-8" or "base64"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "action": self.action,
            "phase": self.phase,
            "timestamp": self.timestamp,
            "has_original": self.original_content is not None,
            "encoding": self.encoding,
        }


@dataclass
class PRExecutionContext:
    """Context for PR-mode execution.

    Tracks branch state, accumulated file changes, and PR status
    throughout the execution lifecycle.
    """
    work_item_id: str
    run_id: str
    branch_name: str  # amprealize/work-item-{id}-{timestamp}
    repo: str  # owner/repo
    base_branch: str  # main or detected default branch
    project_id: Optional[str] = None
    org_id: Optional[str] = None

    # State tracking
    pending_changes: List[PendingFileChange] = field(default_factory=list)
    branch_created: bool = False
    pr_number: Optional[int] = None
    pr_url: Optional[str] = None
    commit_count: int = 0
    last_commit_sha: Optional[str] = None

    # Configuration
    commit_strategy: PRCommitStrategy = PRCommitStrategy.SINGLE_COMMIT
    draft_pr: bool = False  # Create as draft PR
    labels: List[str] = field(default_factory=list)

    def add_file_change(
        self,
        path: str,
        content: str,
        action: str,
        phase: str,
        original_content: Optional[str] = None,
        encoding: str = "utf-8",
    ) -> None:
        """Add a file change to pending changes.

        Merges with existing change for same path if present.
        """
        # Check if we already have a change for this path
        for existing in self.pending_changes:
            if existing.path == path:
                # Update existing change
                existing.content = content
                existing.action = action
                existing.phase = phase
                existing.timestamp = datetime.now(timezone.utc).isoformat()
                if original_content and not existing.original_content:
                    existing.original_content = original_content
                return

        # Add new change
        self.pending_changes.append(PendingFileChange(
            path=path,
            content=content,
            action=action,
            phase=phase,
            timestamp=datetime.now(timezone.utc).isoformat(),
            original_content=original_content,
            encoding=encoding,
        ))

    def has_pending_changes(self) -> bool:
        """Check if there are uncommitted changes."""
        return len(self.pending_changes) > 0

    def clear_pending_changes(self) -> List[PendingFileChange]:
        """Clear and return pending changes after commit."""
        changes = self.pending_changes
        self.pending_changes = []
        return changes

    def get_changes_summary(self) -> Dict[str, int]:
        """Get summary of pending changes by action type."""
        summary: Dict[str, int] = {"create": 0, "update": 0, "delete": 0}
        for change in self.pending_changes:
            if change.action in summary:
                summary[change.action] += 1
        return summary

    def to_dict(self) -> Dict[str, Any]:
        return {
            "work_item_id": self.work_item_id,
            "run_id": self.run_id,
            "branch_name": self.branch_name,
            "repo": self.repo,
            "base_branch": self.base_branch,
            "project_id": self.project_id,
            "org_id": self.org_id,
            "pending_changes_count": len(self.pending_changes),
            "branch_created": self.branch_created,
            "pr_number": self.pr_number,
            "pr_url": self.pr_url,
            "commit_count": self.commit_count,
            "last_commit_sha": self.last_commit_sha,
            "commit_strategy": self.commit_strategy.value,
            "draft_pr": self.draft_pr,
            "labels": self.labels,
        }


def generate_pr_branch_name(work_item_id: str) -> str:
    """Generate branch name for PR-mode execution.

    Format: amprealize/work-item-{id}-{timestamp}
    Example: amprealize/work-item-a1b2c3d4-20260114T153045Z

    Uses timestamp to ensure uniqueness across multiple executions.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # Truncate work_item_id if too long (branches have length limits)
    short_id = work_item_id[:12] if len(work_item_id) > 12 else work_item_id
    return f"amprealize/work-item-{short_id}-{timestamp}"
