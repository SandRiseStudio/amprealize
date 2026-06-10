"""Tool Executor - Executes tool calls with permission enforcement.

Handles execution of MCP tools called by agents during work item execution.
Enforces write scope, internet access, and other permission policies.

See WORK_ITEM_EXECUTION_PLAN.md for full specification.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Union

from .execution_observability import (
    ExecutionObservabilityContext,
    sanitize_observability_payload,
)
from .telemetry import TelemetryClient
from .run_contracts import RunProgressUpdate
from .run_reliability import (
    circuit_metadata_delta,
    circuit_open_until,
    compute_open_until,
    dependency_key_for_tool,
    resolve_outbound_effective,
)
from .work_item_execution_contracts import (
    ExecutionPolicy,
    InternetAccessPolicy,
    PendingFileChange,
    PRExecutionContext,
    ToolCall,
    ToolResult,
    WriteScope,
)


logger = logging.getLogger(__name__)


def _now_iso() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


async def _research_evaluate_handler(
    source: str,
    source_type: Optional[str] = None,
    context_documents: Optional[List[str]] = None,
    _executor_context: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Handler for research_evaluate tool — bridges to ResearchService."""
    from amprealize.research_service import ResearchService
    from amprealize.research_contracts import EvaluatePaperRequest, SourceType

    # Build service with Postgres pool when DSN is available
    pool = None
    try:
        from amprealize.utils.dsn import apply_host_overrides
        dsn = apply_host_overrides(
            os.environ.get("AMPREALIZE_RESEARCH_PG_DSN") or os.environ.get("AMPREALIZE_PG_DSN"),
            "RESEARCH",
        )
        if dsn:
            from amprealize.storage.postgres_pool import PostgresPool
            pool = PostgresPool(dsn, "research")
    except Exception:
        pass  # Fall back to SQLite

    service = ResearchService(pool=pool)

    # Extract execution identity from executor context
    ctx = _executor_context or {}
    gh = ctx.get("github_context") or {}
    owner_id = gh.get("user_id")
    org_id = gh.get("org_id")
    project_id = gh.get("project_id")

    request = EvaluatePaperRequest(source=source)
    if source_type:
        try:
            request.source_type = SourceType(source_type.upper())
        except (ValueError, KeyError):
            pass
    if context_documents:
        request.context_documents = context_documents
    body_md = kwargs.get("body_markdown")
    if body_md and str(body_md).strip():
        request.body_markdown = str(body_md).strip()

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: service.evaluate(
            request, owner_id=owner_id, org_id=org_id, project_id=project_id
        ),
    )

    verdict_str = result.recommendation.verdict.value if result.recommendation else "unknown"
    score = result.evaluation.overall_score if result.evaluation else 0.0

    return {
        "success": True,
        "paper_id": result.paper_id,
        "title": result.paper_title,
        "verdict": verdict_str,
        "verdict_rationale": result.recommendation.verdict_rationale if result.recommendation else None,
        "overall_score": score,
        "core_idea": result.comprehension.core_idea if result.comprehension else None,
        "next_agent": result.recommendation.next_agent if result.recommendation else None,
        "priority": result.recommendation.priority.value if result.recommendation else None,
        # Full markdown report for rich rendering in ExecutionTimeline
        "text": result.markdown_report or "",
        # Short summary for collapsed step preview
        "content_preview": f"\U0001f4c4 {result.paper_title} \u2014 Verdict: {verdict_str} (Score: {score:.1f}/5.0)",
    }


async def _resource_analyze_handler(
    query: str,
    resource_type: Optional[str] = None,
    intent: Optional[str] = None,
    _executor_context: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Handler for resource_analyze tool — shared platform resource analysis."""
    from amprealize.resource_analysis import ResourceAnalysisService

    ctx = _executor_context or {}
    service = ctx.get("resource_analysis_service") or ResourceAnalysisService()
    inventory_provider = ctx.get("resource_analysis_inventory_provider")
    gh = ctx.get("github_context") or {}
    inventory = kwargs.get("inventory")
    if inventory is None and inventory_provider is not None:
        inventory = inventory_provider(
            query=query,
            resource_type=resource_type,
            intent=intent,
            user_id=gh.get("user_id"),
            org_id=gh.get("org_id"),
            project_id=gh.get("project_id"),
        )
        if hasattr(inventory, "__await__"):
            inventory = await inventory

    answer = await service.answer(
        query=query,
        inventory=inventory if isinstance(inventory, dict) else None,
        user_id=str(gh.get("user_id") or ""),
        org_id=gh.get("org_id"),
        project_id=gh.get("project_id"),
    )
    if answer is None:
        return {
            "success": False,
            "message": "No supported resource analysis query was detected.",
            "query": query,
        }
    return {
        "success": True,
        "content": answer.content,
        "answer_type": answer.answer_type,
        "query_plan": answer.query_plan.to_dict(),
        "rows": answer.source_rows,
        "structured_payload": answer.structured_payload,
        "trace_steps": answer.trace_steps,
        "metadata": answer.metadata,
    }


def _short_id(prefix: str) -> str:
    """Generate a short prefixed ID."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class ToolCategory(str, Enum):
    """Categories of tools for permission grouping."""
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    NETWORK = "network"
    FILESYSTEM = "filesystem"
    GIT = "git"
    BROWSER = "browser"
    SEARCH = "search"


@dataclass
class ToolDefinition:
    """Definition of an available tool."""
    name: str
    description: str
    input_schema: Dict[str, Any]
    category: ToolCategory
    requires_internet: bool = False
    is_write_operation: bool = False
    allowed_patterns: List[str] = field(default_factory=list)  # For filesystem tools
    handler: Optional[Callable[..., Any]] = None

    def to_schema_dict(self) -> Dict[str, Any]:
        """Convert to schema dict for LLM tool calling."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class ToolPermissionError(Exception):
    """Raised when a tool call violates permissions."""

    def __init__(
        self,
        tool_name: str,
        reason: str,
        policy: Optional[str] = None,
    ) -> None:
        self.tool_name = tool_name
        self.reason = reason
        self.policy = policy
        super().__init__(f"Permission denied for {tool_name}: {reason}")


class ToolExecutionError(Exception):
    """Raised when a tool execution fails."""

    def __init__(
        self,
        tool_name: str,
        error: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.tool_name = tool_name
        self.error = error
        self.details = details or {}
        super().__init__(f"Tool {tool_name} failed: {error}")


def _is_retryable_transport_message(text: str) -> bool:
    t = text.lower()
    return any(
        k in t
        for k in (
            "timeout",
            "timed out",
            "connection",
            "temporarily",
            "503",
            "502",
            "500",
            "429",
            "rate limit",
            "econnreset",
            "broken pipe",
        )
    )


class ToolRegistry:
    """Registry of available tools and their definitions."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolDefinition] = {}
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """Register default MCP tools."""
        # File reading tools
        self.register(ToolDefinition(
            name="read_file",
            description="Read contents of a file at the given path",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file to read"},
                    "start_line": {"type": "integer", "description": "Starting line number (1-indexed)"},
                    "end_line": {"type": "integer", "description": "Ending line number (1-indexed)"},
                },
                "required": ["path"],
            },
            category=ToolCategory.READ,
            is_write_operation=False,
        ))

        # File writing tools
        self.register(ToolDefinition(
            name="write_file",
            description="Write content to a file at the given path",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file to write"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
            },
            category=ToolCategory.WRITE,
            is_write_operation=True,
        ))

        self.register(ToolDefinition(
            name="edit_file",
            description="Edit a file by replacing content",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file to edit"},
                    "old_content": {"type": "string", "description": "Content to replace"},
                    "new_content": {"type": "string", "description": "Replacement content"},
                },
                "required": ["path", "old_content", "new_content"],
            },
            category=ToolCategory.WRITE,
            is_write_operation=True,
        ))

        # Search tools
        self.register(ToolDefinition(
            name="grep_search",
            description="Search for pattern in files",
            input_schema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Pattern to search for"},
                    "path": {"type": "string", "description": "Path to search in"},
                    "include": {"type": "string", "description": "File pattern to include"},
                },
                "required": ["pattern"],
            },
            category=ToolCategory.SEARCH,
            is_write_operation=False,
        ))

        self.register(ToolDefinition(
            name="file_search",
            description="Search for files by name pattern",
            input_schema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "File name pattern"},
                    "path": {"type": "string", "description": "Path to search in"},
                },
                "required": ["pattern"],
            },
            category=ToolCategory.SEARCH,
            is_write_operation=False,
        ))

        self.register(ToolDefinition(
            name="semantic_search",
            description="Semantic search for code or documentation",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
            category=ToolCategory.SEARCH,
            is_write_operation=False,
        ))

        self.register(ToolDefinition(
            name="resource_analyze",
            description=(
                "Answer read-only natural-language questions about accessible "
                "Amprealize resources such as projects, boards, work items, "
                "agents, runs, behaviors, wiki pages, users, orgs, and settings."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural-language resource question to answer",
                    },
                    "resource_type": {
                        "type": "string",
                        "description": "Optional resource hint, e.g. work_items, runs, boards",
                    },
                    "intent": {
                        "type": "string",
                        "description": "Optional intent hint, e.g. count, list, group, summarize",
                    },
                },
                "required": ["query"],
            },
            category=ToolCategory.READ,
            is_write_operation=False,
            handler=_resource_analyze_handler,
        ))

        # Directory tools
        self.register(ToolDefinition(
            name="list_dir",
            description="List contents of a directory",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to directory"},
                },
                "required": ["path"],
            },
            category=ToolCategory.READ,
            is_write_operation=False,
        ))

        # Enhanced filesystem tools for workspace exploration
        self.register(ToolDefinition(
            name="get_repo_structure",
            description="Get a tree view of the repository structure, useful for understanding codebase layout",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Root path to start from (default: workspace root)"},
                    "max_depth": {"type": "integer", "description": "Maximum depth to traverse (default: 3)"},
                    "include_hidden": {"type": "boolean", "description": "Include hidden files/directories (default: false)"},
                },
            },
            category=ToolCategory.READ,
            is_write_operation=False,
        ))

        self.register(ToolDefinition(
            name="find_files",
            description="Find files matching a pattern, similar to 'find' command",
            input_schema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern to match (e.g., '*.py', '**/test_*.py')"},
                    "path": {"type": "string", "description": "Directory to search in (default: workspace root)"},
                    "max_results": {"type": "integer", "description": "Maximum number of results (default: 100)"},
                },
                "required": ["pattern"],
            },
            category=ToolCategory.SEARCH,
            is_write_operation=False,
        ))

        self.register(ToolDefinition(
            name="get_file_info",
            description="Get metadata about a file (size, type, modification time)",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file"},
                },
                "required": ["path"],
            },
            category=ToolCategory.READ,
            is_write_operation=False,
        ))

        # Terminal tools
        self.register(ToolDefinition(
            name="run_in_terminal",
            description="Run a command in the terminal",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command to run"},
                    "cwd": {"type": "string", "description": "Working directory"},
                },
                "required": ["command"],
            },
            category=ToolCategory.EXECUTE,
            is_write_operation=True,
        ))

        # Git tools
        self.register(ToolDefinition(
            name="git_status",
            description="Get git status",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Repository path"},
                },
            },
            category=ToolCategory.GIT,
            is_write_operation=False,
        ))

        self.register(ToolDefinition(
            name="git_diff",
            description="Get git diff",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Repository path"},
                    "staged": {"type": "boolean", "description": "Show staged changes"},
                },
            },
            category=ToolCategory.GIT,
            is_write_operation=False,
        ))

        self.register(ToolDefinition(
            name="git_commit",
            description="Create a git commit",
            input_schema={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Commit message"},
                    "path": {"type": "string", "description": "Repository path"},
                },
                "required": ["message"],
            },
            category=ToolCategory.GIT,
            is_write_operation=True,
        ))

        # Web tools
        self.register(ToolDefinition(
            name="fetch_url",
            description="Fetch content from a URL",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to fetch"},
                },
                "required": ["url"],
            },
            category=ToolCategory.NETWORK,
            requires_internet=True,
            is_write_operation=False,
        ))

        # GitHub API tools - fallback when local workspace isn't available
        self.register(ToolDefinition(
            name="github_read_file",
            description="Read a file from GitHub repository via API (use when local workspace unavailable)",
            input_schema={
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Repository in owner/repo format"},
                    "path": {"type": "string", "description": "Path to file in repository"},
                    "ref": {"type": "string", "description": "Branch, tag, or commit SHA (default: default branch)"},
                },
                "required": ["repo", "path"],
            },
            category=ToolCategory.NETWORK,
            requires_internet=True,
            is_write_operation=False,
        ))

        self.register(ToolDefinition(
            name="github_list_directory",
            description="List contents of a directory in GitHub repository via API",
            input_schema={
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Repository in owner/repo format"},
                    "path": {"type": "string", "description": "Path to directory (empty for root)"},
                    "ref": {"type": "string", "description": "Branch, tag, or commit SHA (default: default branch)"},
                },
                "required": ["repo"],
            },
            category=ToolCategory.NETWORK,
            requires_internet=True,
            is_write_operation=False,
        ))

        self.register(ToolDefinition(
            name="github_search_code",
            description="Search for code in a GitHub repository",
            input_schema={
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Repository in owner/repo format"},
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "description": "Maximum results (default: 20)"},
                },
                "required": ["repo", "query"],
            },
            category=ToolCategory.NETWORK,
            requires_internet=True,
            is_write_operation=False,
        ))

        # Research tools - for AI research agent work item execution
        self.register(ToolDefinition(
            name="research_evaluate",
            description="Evaluate a research paper or article through the 4-phase AI research pipeline (Ingest → Comprehend → Evaluate → Recommend). Returns structured verdict with implementation roadmap.",
            input_schema={
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "URL, file path, or arXiv ID of the paper to evaluate"},
                    "source_type": {"type": "string", "enum": ["url", "arxiv", "markdown", "pdf", "docx"], "description": "Type of source (auto-detected if not specified)"},
                    "context_documents": {"type": "array", "items": {"type": "string"}, "description": "Additional context document paths"},
                },
                "required": ["source"],
            },
            category=ToolCategory.NETWORK,
            requires_internet=True,
            is_write_operation=False,
            handler=_research_evaluate_handler,
        ))

    def register(self, tool: ToolDefinition) -> None:
        """Register a tool definition."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[ToolDefinition]:
        """Get a tool definition by name."""
        return self._tools.get(name)

    def list_all(self) -> List[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def list_by_category(self, category: ToolCategory) -> List[str]:
        """List tool names by category."""
        return [
            name for name, tool in self._tools.items()
            if tool.category == category
        ]

    def get_schemas(self, names: Optional[List[str]] = None) -> Dict[str, Any]:
        """Get schemas for specified tools (or all if none specified)."""
        tools_to_include = names or list(self._tools.keys())
        return {
            name: self._tools[name].to_schema_dict()
            for name in tools_to_include
            if name in self._tools
        }


class PermissionChecker:
    """Checks tool permissions against execution policy."""

    def __init__(
        self,
        policy: ExecutionPolicy,
        registry: ToolRegistry,
    ) -> None:
        self._policy = policy
        self._registry = registry

    def check_permission(self, tool: ToolCall) -> None:
        """Check if a tool call is permitted.

        Raises ToolPermissionError if not permitted.
        """
        tool_def = self._registry.get(tool.tool_name)
        if not tool_def:
            logger.warning(f"Tool '{tool.tool_name}' not found in registry. Available tools: {self._registry.list_all()}")
            raise ToolPermissionError(
                tool_name=tool.tool_name,
                reason="Unknown tool",
            )

        # Check internet access
        if tool_def.requires_internet:
            if self._policy.internet_access == InternetAccessPolicy.DISABLED:
                raise ToolPermissionError(
                    tool_name=tool.tool_name,
                    reason="Internet access denied",
                    policy=f"internet_access={self._policy.internet_access.value}",
                )

        # Check write scope
        if tool_def.is_write_operation:
            if self._policy.write_scope == WriteScope.READ_ONLY:
                raise ToolPermissionError(
                    tool_name=tool.tool_name,
                    reason="Write operations not permitted",
                    policy=f"write_scope={self._policy.write_scope.value}",
                )

            # Check if path is within allowed scope
            if "path" in tool.tool_args:
                self._check_write_path(tool.tool_name, tool.tool_args["path"])

    def _check_write_path(self, tool_name: str, path: str) -> None:
        """Check if a write path is within allowed scope."""
        import os

        # Get allowed directories from policy
        allowed_dirs = self._policy.allowed_write_directories or []

        # For LOCAL_ONLY, LOCAL_AND_PR, check if path is within allowed directories
        if self._policy.write_scope in (WriteScope.LOCAL_ONLY, WriteScope.LOCAL_AND_PR):
            if not allowed_dirs:
                return  # No restrictions if no dirs specified

            abs_path = os.path.abspath(path)
            for allowed_dir in allowed_dirs:
                if abs_path.startswith(os.path.abspath(allowed_dir)):
                    return

            raise ToolPermissionError(
                tool_name=tool_name,
                reason=f"Path {path} outside allowed directories",
                policy=f"write_scope={self._policy.write_scope.value}, allowed={allowed_dirs}",
            )

        # PR_ONLY mode - writes will be captured for PR, not written locally
        elif self._policy.write_scope == WriteScope.PR_ONLY:
            # Allow the write - it will be intercepted and added to PR
            return

    def filter_available_tools(
        self,
        requested: Optional[List[str]] = None,
    ) -> List[str]:
        """Filter tools based on policy permissions.

        Returns list of tool names that are available given the policy.
        """
        all_tools = requested or self._registry.list_all()
        available = []

        for tool_name in all_tools:
            tool_def = self._registry.get(tool_name)
            if not tool_def:
                continue

            # Skip tools requiring internet if not allowed
            if tool_def.requires_internet:
                if self._policy.internet_access == InternetAccessPolicy.DISABLED:
                    continue

            # Skip write tools if not allowed
            if tool_def.is_write_operation:
                if self._policy.write_scope == WriteScope.READ_ONLY:
                    continue

            available.append(tool_name)

        return available


class ToolExecutor:
    """Executes tool calls with permission enforcement.

    Handles:
    - Permission checking against execution policy
    - Actual tool execution (via MCP or local handlers)
    - PR mode file change interception
    - Result formatting and error handling
    - Execution logging and metrics
    - Container-based execution for isolated agent workspaces
    """

    def __init__(
        self,
        policy: ExecutionPolicy,
        *,
        registry: Optional[ToolRegistry] = None,
        mcp_client: Optional[Any] = None,
        telemetry: Optional[TelemetryClient] = None,
        project_root: Optional[str] = None,
        pr_context: Optional[PRExecutionContext] = None,
        current_phase: Optional[str] = None,
        github_service: Optional[Any] = None,
        github_context: Optional[Dict[str, Any]] = None,
        resource_analysis_service: Optional[Any] = None,
        resource_analysis_inventory_provider: Optional[Any] = None,
        workspace_info: Optional[Any] = None,  # WorkspaceInfo for container exec
        workspace_manager: Optional[Any] = None,  # AmprealizeWorkspaceClient (workspace-agent)
        observability_context: Optional[ExecutionObservabilityContext] = None,
        connector_delegate: Optional[Any] = None,
        run_service: Optional[Any] = None,
        run_id: Optional[str] = None,
    ) -> None:
        """Initialize ToolExecutor.

        Args:
            policy: Execution policy for permission checks
            registry: Tool registry (defaults to standard registry)
            mcp_client: MCP client for remote tool execution
            telemetry: Telemetry client for metrics
            project_root: Project root directory for path resolution
            pr_context: PR execution context for file change accumulation
            current_phase: Current GEP phase (for PR change tracking)
            github_service: GitHubService for GitHub API fallback tools
            github_context: Context for GitHub API (repo, project_id, org_id, user_id)
            workspace_info: WorkspaceInfo for container-based execution
            workspace_manager: AmprealizeWorkspaceClient for workspace operations (via gRPC)
            connector_delegate: Optional object with async ``invoke(tool_name, tool_args) -> str``
                for local connector hybrid runs (see ``ConnectorToolDelegate``).
            run_service: Optional RunService for circuit-breaker persistence and metadata reads.
            run_id: Optional run id (work-item execution) for breaker/checkpoint correlation.
        """
        self._policy = policy
        self._registry = registry or ToolRegistry()
        self._mcp_client = mcp_client
        self._telemetry = telemetry or TelemetryClient.noop()
        self._project_root = project_root
        self._pr_context = pr_context
        self._current_phase = current_phase or "unknown"
        self._github_service = github_service
        self._workspace_info = workspace_info
        self._workspace_manager = workspace_manager
        self._github_context = github_context or {}
        self._resource_analysis_service = resource_analysis_service
        self._resource_analysis_inventory_provider = resource_analysis_inventory_provider
        self._observability_context = observability_context
        self._connector_delegate = connector_delegate
        self._run_service = run_service
        self._run_id = run_id

        self._permission_checker = PermissionChecker(policy, self._registry)

        # Execution history
        self._execution_history: List[ToolResult] = []

        # Consecutive transport failures per dependency key (this executor lifetime)
        self._transport_fail_streak: Dict[str, int] = {}

    def set_pr_context(self, pr_context: Optional[PRExecutionContext]) -> None:
        """Set the PR execution context for file change accumulation."""
        self._pr_context = pr_context

    def set_current_phase(self, phase: str) -> None:
        """Set the current GEP phase for change tracking."""
        self._current_phase = phase

    def set_observability_context(
        self,
        context: Optional[ExecutionObservabilityContext],
    ) -> None:
        """Set shared execution correlation context for emitted tool events."""
        self._observability_context = context

    def _is_pr_mode(self) -> bool:
        """Check if we're in PR mode (should intercept file writes)."""
        return (
            self._pr_context is not None and
            self._policy.write_scope in (WriteScope.PR_ONLY, WriteScope.LOCAL_AND_PR)
        )

    def _should_write_locally(self) -> bool:
        """Check if we should also write files locally."""
        return self._policy.write_scope in (WriteScope.LOCAL_ONLY, WriteScope.LOCAL_AND_PR)

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        """Execute a tool call with outbound reliability (timeout, retries, breaker)."""
        import time

        start_time = time.time()
        self._emit_tool_event(
            "execution.tool.started",
            tool_call,
            {
                "phase": self._current_phase,
                "inputs": tool_call.tool_args,
            },
        )

        try:
            self._permission_checker.check_permission(tool_call)
        except ToolPermissionError as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            result = ToolResult(
                call_id=tool_call.call_id,
                tool_name=tool_call.tool_name,
                output="",
                success=False,
                error=str(e),
                duration_ms=elapsed_ms,
            )
            logger.warning("Permission denied: %s", e)
            self._telemetry.emit_event(
                event_type="tool.permission_denied",
                payload={
                    "tool_name": tool_call.tool_name,
                    "reason": e.reason,
                    "policy": e.policy,
                },
            )
            self._emit_tool_event(
                "execution.tool.denied",
                tool_call,
                {
                    "phase": self._current_phase,
                    "success": False,
                    "elapsed_ms": elapsed_ms,
                    "reason": e.reason,
                    "policy": e.policy,
                    "error": str(e),
                },
            )
            self._emit_tool_performance_event(
                tool_call,
                "denied",
                elapsed_ms,
                error_class=type(e).__name__,
                reason=e.reason,
            )
            self._execution_history.append(result)
            return result

        dep_key = dependency_key_for_tool(tool_call.tool_name, tool_call.tool_args)
        eff = resolve_outbound_effective(
            self._policy.outbound_reliability,
            tool_name=tool_call.tool_name,
            dependency_key=dep_key,
        )

        if self._run_service and self._run_id:
            try:
                run = self._run_service.get_run(self._run_id)
                ou = circuit_open_until(run, dep_key)
                if ou:
                    elapsed_ms = int((time.time() - start_time) * 1000)
                    msg = f"Circuit open for {dep_key} until {ou}"
                    result = ToolResult(
                        call_id=tool_call.call_id,
                        tool_name=tool_call.tool_name,
                        output="",
                        success=False,
                        error=msg,
                        duration_ms=elapsed_ms,
                    )
                    self._emit_tool_event(
                        "execution.tool.failed",
                        tool_call,
                        {
                            "phase": self._current_phase,
                            "success": False,
                            "elapsed_ms": elapsed_ms,
                            "error": msg,
                            "error_class": "CircuitOpen",
                        },
                    )
                    self._emit_tool_performance_event(
                        tool_call,
                        "failed",
                        elapsed_ms,
                        error_class="CircuitOpen",
                    )
                    self._execution_history.append(result)
                    return result
            except Exception:
                pass

        max_attempts = max(1, int(eff["max_retries"]) + 1)
        last_exc: Optional[BaseException] = None
        streak = self._transport_fail_streak.get(dep_key, 0)

        for attempt in range(max_attempts):
            try:
                output = await asyncio.wait_for(
                    self._execute_tool(tool_call),
                    timeout=float(eff["timeout_seconds"]),
                )
                self._transport_fail_streak[dep_key] = 0
                self._clear_circuit_breaker_state(dep_key)
                elapsed_ms = int((time.time() - start_time) * 1000)
                result = ToolResult(
                    call_id=tool_call.call_id,
                    tool_name=tool_call.tool_name,
                    output=output,
                    success=True,
                    duration_ms=elapsed_ms,
                )
                self._telemetry.emit_event(
                    event_type="tool.executed",
                    payload={
                        "tool_name": tool_call.tool_name,
                        "success": True,
                        "elapsed_ms": elapsed_ms,
                    },
                )
                self._emit_tool_event(
                    "execution.tool.completed",
                    tool_call,
                    {
                        "phase": self._current_phase,
                        "success": True,
                        "elapsed_ms": elapsed_ms,
                        "output_preview": str(output)[:512] if output is not None else None,
                    },
                )
                self._emit_tool_performance_event(tool_call, "completed", elapsed_ms)
                self._emit_tool_outcome_event(tool_call, output)
                self._execution_history.append(result)
                return result
            except asyncio.TimeoutError:
                last_exc = ToolExecutionError(
                    tool_call.tool_name,
                    f"timeout after {eff['timeout_seconds']}s",
                )
            except ToolExecutionError as exc:
                last_exc = exc
                if not _is_retryable_transport_message(exc.error):
                    break
            except Exception as exc:
                last_exc = exc
                if not _is_retryable_transport_message(str(exc)):
                    break

            streak = int(self._transport_fail_streak.get(dep_key, 0)) + 1
            self._transport_fail_streak[dep_key] = streak

            if attempt < max_attempts - 1:
                delay = min(60.0, (0.5 * (2**attempt)) + random.uniform(0, 0.2))
                await asyncio.sleep(delay)

        elapsed_ms = int((time.time() - start_time) * 1000)
        err_text = str(last_exc) if last_exc else "tool failed"
        if isinstance(last_exc, ToolExecutionError):
            err_detail = last_exc.error
            err_class = type(last_exc).__name__
        else:
            err_detail = err_text
            err_class = type(last_exc).__name__ if last_exc else "ToolExecutionError"

        self._telemetry.emit_event(
            event_type="tool.retry_exhausted",
            payload={
                "run_id": self._run_id,
                "tool_name": tool_call.tool_name,
                "dependency_key": dep_key,
                "attempts": max_attempts,
                "error_class": err_class,
            },
            run_id=self._run_id,
        )

        thr = eff.get("circuit_failure_threshold")
        if thr is not None and streak >= int(thr):
            self._open_circuit_breaker(dep_key, eff, streak)

        result = ToolResult(
            call_id=tool_call.call_id,
            tool_name=tool_call.tool_name,
            output="",
            success=False,
            error=err_detail,
            duration_ms=elapsed_ms,
        )
        logger.error("Tool execution failed after retries: %s", err_detail)
        self._telemetry.emit_event(
            event_type="tool.execution_failed",
            payload={
                "tool_name": tool_call.tool_name,
                "error": err_detail,
            },
        )
        self._emit_tool_event(
            "execution.tool.failed",
            tool_call,
            {
                "phase": self._current_phase,
                "success": False,
                "elapsed_ms": elapsed_ms,
                "error": err_detail,
                "error_class": err_class,
            },
        )
        self._emit_tool_performance_event(
            tool_call,
            "failed",
            elapsed_ms,
            error_class=err_class,
        )
        self._execution_history.append(result)
        return result

    def _open_circuit_breaker(self, dep_key: str, eff: Dict[str, Any], streak: int) -> None:
        if not (self._run_service and self._run_id):
            return
        try:
            run = self._run_service.get_run(self._run_id)
            open_until = compute_open_until(float(eff["circuit_open_seconds"]))
            delta = circuit_metadata_delta(
                run,
                dependency_key=dep_key,
                failures=streak,
                open_until=open_until,
            )
            self._run_service.update_run(self._run_id, RunProgressUpdate(metadata=delta))
            self._telemetry.emit_event(
                event_type="circuit_breaker.opened",
                payload={
                    "run_id": self._run_id,
                    "dependency_key": dep_key,
                    "open_until": open_until,
                    "failure_threshold": eff.get("circuit_failure_threshold"),
                },
                run_id=self._run_id,
            )
        except Exception as exc:
            logger.warning("Could not persist circuit breaker state: %s", exc)

    def _clear_circuit_breaker_state(self, dep_key: str) -> None:
        if not (self._run_service and self._run_id):
            return
        try:
            run = self._run_service.get_run(self._run_id)
            circuits = dict(run.metadata.get("reliability_circuits") or {})
            if dep_key not in circuits:
                return
            circuits.pop(dep_key, None)
            self._run_service.update_run(
                self._run_id,
                RunProgressUpdate(metadata={"reliability_circuits": circuits}),
            )
            self._telemetry.emit_event(
                event_type="circuit_breaker.closed",
                payload={"run_id": self._run_id, "dependency_key": dep_key},
                run_id=self._run_id,
            )
        except Exception:
            pass

    def _emit_tool_event(
        self,
        event_type: str,
        tool_call: ToolCall,
        payload: Dict[str, Any],
    ) -> None:
        context_payload = (
            self._observability_context.to_metadata()
            if self._observability_context
            else {}
        )
        self._telemetry.emit_event(
            event_type=event_type,
            payload=sanitize_observability_payload({
                "tool_name": tool_call.tool_name,
                "call_id": tool_call.call_id,
                **payload,
                **context_payload,
            }),
            run_id=(
                self._observability_context.run_id
                if self._observability_context
                else None
            ),
        )

    def _emit_tool_performance_event(
        self,
        tool_call: ToolCall,
        status: str,
        elapsed_ms: int,
        *,
        error_class: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        """Emit analytics-friendly tool performance separate from outcomes."""
        self._emit_tool_event(
            "execution.tool.performance",
            tool_call,
            {
                "phase": self._current_phase,
                "status": status,
                "elapsed_ms": elapsed_ms,
                "error_class": error_class,
                "reason": reason,
            },
        )

    def _emit_tool_outcome_event(self, tool_call: ToolCall, output: Any) -> None:
        outcome = self._extract_tool_outcome(output)
        if not outcome:
            return
        self._emit_tool_event(
            "execution.tool.business_outcome",
            tool_call,
            {
                "phase": self._current_phase,
                **outcome,
            },
        )

    @staticmethod
    def _extract_tool_outcome(output: Any) -> Dict[str, Any]:
        """Return a bounded business outcome summary when a tool creates/links resources."""
        if isinstance(output, str):
            try:
                output = json.loads(output)
            except json.JSONDecodeError:
                return {}
        if not isinstance(output, dict):
            return {}
        result = output.get("result") if isinstance(output.get("result"), dict) else output
        resource_type = (
            result.get("resource_type")
            or result.get("type")
            or output.get("answer_type")
            or output.get("action_type")
        )
        resource_id = (
            result.get("resource_id")
            or result.get("item_id")
            or result.get("work_item_id")
            or result.get("project_id")
            or result.get("board_id")
            or result.get("run_id")
            or result.get("id")
        )
        if not resource_type and not resource_id:
            return {}
        return {
            "outcome_type": "resource",
            "resource_type": resource_type,
            "resource_id": resource_id,
            "outcome_ref": (
                f"{resource_type}:{resource_id}"
                if resource_type and resource_id
                else resource_id
            ),
            "success": bool(output.get("success", True)),
        }

    async def execute_batch(
        self,
        tool_calls: List[ToolCall],
        parallel: bool = False,
    ) -> List[ToolResult]:
        """Execute multiple tool calls.

        Args:
            tool_calls: List of tool calls to execute
            parallel: If True, execute in parallel (where safe)

        Returns:
            List of ToolResults
        """
        if parallel:
            # Execute in parallel (be careful with dependencies)
            tasks = [self.execute(tc) for tc in tool_calls]
            return await asyncio.gather(*tasks)
        else:
            # Execute sequentially
            results = []
            for tc in tool_calls:
                result = await self.execute(tc)
                results.append(result)
            return results

    async def _execute_tool(self, tool_call: ToolCall) -> str:
        """Execute a tool and return its output.

        This method dispatches to the appropriate handler:
        - MCP client for remote tools
        - Local handlers for built-in tools
        """
        tool_def = self._registry.get(tool_call.tool_name)
        if not tool_def:
            raise ToolExecutionError(
                tool_name=tool_call.tool_name,
                error="Unknown tool",
            )

        # Check for custom handler
        if tool_def.handler:
            try:
                # Inject executor context so handlers can access pool, identity, etc.
                handler_args = dict(tool_call.tool_args)
                handler_args["_executor_context"] = {
                    "github_context": self._github_context,
                    "project_root": self._project_root,
                    "resource_analysis_service": self._resource_analysis_service,
                    "resource_analysis_inventory_provider": self._resource_analysis_inventory_provider,
                }
                result = await tool_def.handler(**handler_args)
                return json.dumps(result) if not isinstance(result, str) else result
            except Exception as e:
                raise ToolExecutionError(
                    tool_name=tool_call.tool_name,
                    error=str(e),
                )

        # Use MCP client if available
        if self._mcp_client:
            try:
                result = await self._mcp_client.call_tool(
                    tool_call.tool_name,
                    tool_call.tool_args,
                )
                return result
            except Exception as e:
                raise ToolExecutionError(
                    tool_name=tool_call.tool_name,
                    error=f"MCP call failed: {e}",
                )

        # Fall back to local implementation
        return await self._execute_locally(tool_call)

    async def _execute_locally(self, tool_call: ToolCall) -> str:
        """Execute a tool locally (fallback when no MCP client)."""
        import os

        tool_name = tool_call.tool_name
        inputs = tool_call.tool_args

        # Implement basic tools locally
        if tool_name == "read_file":
            path = inputs.get("path", "")
            start_line = inputs.get("start_line")
            end_line = inputs.get("end_line")

            if self._connector_delegate is not None:
                return await self._connector_delegate.invoke(
                    "read_file",
                    {"path": path, "start_line": start_line, "end_line": end_line},
                )

            # Use container execution if workspace is container-based
            if self._workspace_info and self._workspace_info.use_container_exec and self._workspace_manager:
                try:
                    import asyncio
                    loop = asyncio.get_event_loop()
                    content = loop.run_until_complete(
                        self._workspace_manager.read_file_in_workspace(
                            self._workspace_info.run_id,
                            path,
                            start_line=start_line,
                            end_line=end_line,
                        )
                    )
                    return content
                except Exception as e:
                    raise ToolExecutionError(tool_name, str(e))
            else:
                # Local execution fallback
                if self._project_root:
                    path = os.path.join(self._project_root, path)

                try:
                    with open(path, "r") as f:
                        content = f.read()

                    # Handle line ranges
                    if start_line or end_line:
                        lines = content.split("\n")
                        start = (start_line or 1) - 1
                        end = end_line or len(lines)
                        content = "\n".join(lines[start:end])

                    return content
                except FileNotFoundError:
                    raise ToolExecutionError(tool_name, f"File not found: {path}")
                except Exception as e:
                    raise ToolExecutionError(tool_name, str(e))

        elif tool_name == "write_file":
            path = inputs.get("path", "")
            content = inputs.get("content", "")
            relative_path = path  # Keep original for PR context

            result_parts = []

            # Intercept for PR mode - accumulate changes to PR context
            if self._is_pr_mode() and self._pr_context is not None:
                from datetime import datetime, timezone
                from amprealize.work_item_execution_contracts import PendingFileChange

                # Add to PR context for later commit
                file_change = PendingFileChange(
                    path=relative_path,
                    content=content,
                    action="create",  # write_file always creates/overwrites
                    phase=self._current_phase,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
                self._pr_context.pending_changes.append(file_change)
                result_parts.append(f"Staged {len(content)} characters for PR commit: {relative_path}")

            if self._connector_delegate is not None:
                result_parts.append(
                    await self._connector_delegate.invoke("write_file", dict(inputs))
                )
                if not result_parts:
                    raise ToolExecutionError(tool_name, "Write operation blocked by policy")
                return " | ".join(result_parts)

            # Write locally if policy allows
            if self._should_write_locally():
                # Use container execution if workspace is container-based
                if self._workspace_info and self._workspace_info.use_container_exec and self._workspace_manager:
                    try:
                        import asyncio
                        loop = asyncio.get_event_loop()
                        loop.run_until_complete(
                            self._workspace_manager.write_file_in_workspace(
                                self._workspace_info.run_id,
                                path,
                                content,
                            )
                        )
                        result_parts.append(f"Wrote {len(content)} characters to {path} (container)")
                    except Exception as e:
                        raise ToolExecutionError(tool_name, str(e))
                else:
                    # Local execution fallback
                    if self._project_root:
                        path = os.path.join(self._project_root, path)
                    try:
                        # Create directory if needed
                        os.makedirs(os.path.dirname(path), exist_ok=True)
                        with open(path, "w") as f:
                            f.write(content)
                        result_parts.append(f"Wrote {len(content)} characters to {path}")
                    except Exception as e:
                        raise ToolExecutionError(tool_name, str(e))

            if not result_parts:
                # This shouldn't happen - either PR mode or local write should be active
                raise ToolExecutionError(tool_name, "Write operation blocked by policy")

            return " | ".join(result_parts)

        elif tool_name == "list_dir":
            path = inputs.get("path", ".")

            if self._connector_delegate is not None:
                return await self._connector_delegate.invoke("list_dir", dict(inputs))

            # Use container execution if workspace is container-based
            if self._workspace_info and self._workspace_info.use_container_exec and self._workspace_manager:
                try:
                    import asyncio
                    loop = asyncio.get_event_loop()
                    entries = loop.run_until_complete(
                        self._workspace_manager.list_dir_in_workspace(
                            self._workspace_info.run_id,
                            path,
                        )
                    )
                    return json.dumps(entries)
                except Exception as e:
                    raise ToolExecutionError(tool_name, str(e))
            else:
                # Local execution fallback
                if self._project_root:
                    path = os.path.join(self._project_root, path)

                try:
                    entries = os.listdir(path)
                    return json.dumps(entries)
                except Exception as e:
                    raise ToolExecutionError(tool_name, str(e))

        elif tool_name == "get_repo_structure":
            # Get tree view of repository structure
            from pathlib import Path

            root_path = inputs.get("path", ".")
            max_depth = inputs.get("max_depth", 3)
            include_hidden = inputs.get("include_hidden", False)

            if self._project_root:
                root_path = os.path.join(self._project_root, root_path)

            try:
                def build_tree(path: Path, depth: int = 0, prefix: str = "") -> List[str]:
                    if depth > max_depth:
                        return [f"{prefix}..."]

                    lines = []
                    try:
                        entries = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
                    except PermissionError:
                        return [f"{prefix}[Permission Denied]"]

                    # Filter hidden files if needed
                    if not include_hidden:
                        entries = [e for e in entries if not e.name.startswith('.')]

                    # Skip common large directories
                    skip_dirs = {'node_modules', '__pycache__', '.git', 'venv', '.venv', 'dist', 'build'}

                    for i, entry in enumerate(entries):
                        is_last = i == len(entries) - 1
                        connector = "└── " if is_last else "├── "

                        if entry.is_dir():
                            if entry.name in skip_dirs:
                                lines.append(f"{prefix}{connector}{entry.name}/ [skipped]")
                            else:
                                lines.append(f"{prefix}{connector}{entry.name}/")
                                extension = "    " if is_last else "│   "
                                lines.extend(build_tree(entry, depth + 1, prefix + extension))
                        else:
                            lines.append(f"{prefix}{connector}{entry.name}")

                    return lines

                root = Path(root_path)
                if not root.exists():
                    raise ToolExecutionError(tool_name, f"Path not found: {root_path}")

                tree_lines = [f"{root.name}/"] + build_tree(root)
                return "\n".join(tree_lines)

            except Exception as e:
                raise ToolExecutionError(tool_name, str(e))

        elif tool_name == "find_files":
            # Find files matching a pattern
            import fnmatch
            from pathlib import Path

            pattern = inputs.get("pattern", "*")
            search_path = inputs.get("path", ".")
            max_results = inputs.get("max_results", 100)

            if self._project_root:
                search_path = os.path.join(self._project_root, search_path)

            try:
                root = Path(search_path)
                if not root.exists():
                    raise ToolExecutionError(tool_name, f"Path not found: {search_path}")

                results = []
                # Use glob for pattern matching
                if "**" in pattern:
                    # Recursive glob
                    matches = root.glob(pattern)
                else:
                    # Non-recursive, check if pattern has path separator
                    if "/" in pattern or "\\" in pattern:
                        matches = root.glob(pattern)
                    else:
                        matches = root.rglob(pattern)

                for match in matches:
                    if len(results) >= max_results:
                        break
                    # Return relative path from project root
                    try:
                        rel_path = match.relative_to(root)
                    except ValueError:
                        rel_path = match
                    results.append(str(rel_path))

                return json.dumps(results)

            except Exception as e:
                raise ToolExecutionError(tool_name, str(e))

        elif tool_name == "get_file_info":
            # Get file metadata
            from pathlib import Path
            from datetime import datetime

            file_path = inputs.get("path", "")
            if self._project_root:
                file_path = os.path.join(self._project_root, file_path)

            try:
                path = Path(file_path)
                if not path.exists():
                    raise ToolExecutionError(tool_name, f"File not found: {file_path}")

                stat = path.stat()
                info = {
                    "name": path.name,
                    "path": str(path),
                    "size": stat.st_size,
                    "is_file": path.is_file(),
                    "is_dir": path.is_dir(),
                    "extension": path.suffix,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                }

                # Add line count for text files
                if path.is_file() and path.suffix in {'.py', '.js', '.ts', '.tsx', '.jsx', '.md', '.txt', '.yaml', '.yml', '.json', '.html', '.css'}:
                    try:
                        with open(path, 'r') as f:
                            info["line_count"] = sum(1 for _ in f)
                    except:
                        pass

                return json.dumps(info)

            except Exception as e:
                raise ToolExecutionError(tool_name, str(e))

        elif tool_name == "edit_file":
            if self._connector_delegate is not None:
                return await self._connector_delegate.invoke("edit_file", dict(inputs))
            raise ToolExecutionError(
                tool_name,
                "edit_file requires an MCP server or local connector delegate",
            )

        elif tool_name == "run_in_terminal":
            if self._connector_delegate is not None:
                return await self._connector_delegate.invoke("run_in_terminal", dict(inputs))

            command = inputs.get("command", "")
            cwd = inputs.get("cwd", self._project_root)

            try:
                # Use container execution if workspace is container-based
                if self._workspace_info and self._workspace_info.use_container_exec and self._workspace_manager:
                    import asyncio
                    # Get the event loop and run the async method
                    loop = asyncio.get_event_loop()
                    output, exit_code = loop.run_until_complete(
                        self._workspace_manager.exec_in_workspace(
                            self._workspace_info.run_id,
                            command,
                            cwd=cwd,
                            timeout=60,
                        )
                    )
                    if exit_code != 0:
                        output += f"\nError (exit {exit_code})"
                    return output
                else:
                    # Local execution fallback
                    result = subprocess.run(
                        command,
                        shell=True,
                        cwd=cwd,
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                    output = result.stdout
                    if result.returncode != 0:
                        output += f"\nError (exit {result.returncode}): {result.stderr}"
                    return output
            except subprocess.TimeoutExpired:
                raise ToolExecutionError(tool_name, "Command timed out after 60s")
            except Exception as e:
                raise ToolExecutionError(tool_name, str(e))

        # =========================================================================
        # GitHub API Tools - Fallback when local workspace isn't available
        # =========================================================================
        elif tool_name == "github_read_file":
            # Read file from GitHub via API
            repo = inputs.get("repo", self._github_context.get("repo", ""))
            path = inputs.get("path", "")
            ref = inputs.get("ref")

            if not repo:
                raise ToolExecutionError(tool_name, "Repository not specified")
            if not path:
                raise ToolExecutionError(tool_name, "Path not specified")

            try:
                content = self._github_read_file_api(repo, path, ref)
                return content
            except Exception as e:
                raise ToolExecutionError(tool_name, str(e))

        elif tool_name == "github_list_directory":
            # List directory contents from GitHub via API
            repo = inputs.get("repo", self._github_context.get("repo", ""))
            path = inputs.get("path", "")
            ref = inputs.get("ref")

            if not repo:
                raise ToolExecutionError(tool_name, "Repository not specified")

            try:
                contents = self._github_list_directory_api(repo, path, ref)
                return json.dumps(contents)
            except Exception as e:
                raise ToolExecutionError(tool_name, str(e))

        elif tool_name == "github_search_code":
            # Search code in GitHub via API
            repo = inputs.get("repo", self._github_context.get("repo", ""))
            query = inputs.get("query", "")
            max_results = inputs.get("max_results", 20)

            if not repo:
                raise ToolExecutionError(tool_name, "Repository not specified")
            if not query:
                raise ToolExecutionError(tool_name, "Query not specified")

            try:
                results = self._github_search_code_api(repo, query, max_results)
                return json.dumps(results)
            except Exception as e:
                raise ToolExecutionError(tool_name, str(e))

        else:
            raise ToolExecutionError(
                tool_name=tool_name,
                error="No local implementation available",
            )

    def _github_read_file_api(
        self,
        repo: str,
        path: str,
        ref: Optional[str] = None,
    ) -> str:
        """Read a file from GitHub via the API.

        Uses GitHubService if available, otherwise falls back to direct API call.
        """
        import base64
        import urllib.request
        import urllib.error

        # Try GitHubService first
        if self._github_service:
            try:
                token_info = self._github_service.get_resolved_token(
                    project_id=self._github_context.get("project_id"),
                    org_id=self._github_context.get("org_id"),
                    user_id=self._github_context.get("user_id"),
                )
                token = token_info.token if token_info else None
            except:
                token = None
        else:
            token = self._github_context.get("token")

        # Build API URL
        url = f"https://api.github.com/repos/{repo}/contents/{path}"
        if ref:
            url += f"?ref={ref}"

        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Amprealize-Agent",
        }
        if token:
            headers["Authorization"] = f"token {token}"

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode())

                if data.get("type") != "file":
                    raise ToolExecutionError(
                        "github_read_file",
                        f"Path is not a file: {path}"
                    )

                # Decode base64 content
                content = base64.b64decode(data.get("content", "")).decode("utf-8")
                return content

        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ToolExecutionError("github_read_file", f"File not found: {path}")
            raise ToolExecutionError("github_read_file", f"GitHub API error: {e}")

    def _github_list_directory_api(
        self,
        repo: str,
        path: str = "",
        ref: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List directory contents from GitHub via the API."""
        import urllib.request
        import urllib.error

        # Get token
        if self._github_service:
            try:
                token_info = self._github_service.get_resolved_token(
                    project_id=self._github_context.get("project_id"),
                    org_id=self._github_context.get("org_id"),
                    user_id=self._github_context.get("user_id"),
                )
                token = token_info.token if token_info else None
            except:
                token = None
        else:
            token = self._github_context.get("token")

        # Build API URL
        url = f"https://api.github.com/repos/{repo}/contents/{path}"
        if ref:
            url += f"?ref={ref}"

        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Amprealize-Agent",
        }
        if token:
            headers["Authorization"] = f"token {token}"

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode())

                # Format output
                if isinstance(data, list):
                    return [
                        {
                            "name": item.get("name"),
                            "type": item.get("type"),
                            "path": item.get("path"),
                            "size": item.get("size"),
                        }
                        for item in data
                    ]
                else:
                    # Single file, not a directory
                    return [{
                        "name": data.get("name"),
                        "type": data.get("type"),
                        "path": data.get("path"),
                        "size": data.get("size"),
                    }]

        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ToolExecutionError("github_list_directory", f"Path not found: {path}")
            raise ToolExecutionError("github_list_directory", f"GitHub API error: {e}")

    def _github_search_code_api(
        self,
        repo: str,
        query: str,
        max_results: int = 20,
    ) -> List[Dict[str, Any]]:
        """Search code in GitHub via the API."""
        import urllib.request
        import urllib.error
        import urllib.parse

        # Get token
        if self._github_service:
            try:
                token_info = self._github_service.get_resolved_token(
                    project_id=self._github_context.get("project_id"),
                    org_id=self._github_context.get("org_id"),
                    user_id=self._github_context.get("user_id"),
                )
                token = token_info.token if token_info else None
            except:
                token = None
        else:
            token = self._github_context.get("token")

        # Build search query
        search_query = f"{query} repo:{repo}"
        encoded_query = urllib.parse.quote(search_query)
        url = f"https://api.github.com/search/code?q={encoded_query}&per_page={max_results}"

        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Amprealize-Agent",
        }
        if token:
            headers["Authorization"] = f"token {token}"

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode())

                return [
                    {
                        "name": item.get("name"),
                        "path": item.get("path"),
                        "repository": item.get("repository", {}).get("full_name"),
                        "url": item.get("html_url"),
                    }
                    for item in data.get("items", [])
                ]

        except urllib.error.HTTPError as e:
            raise ToolExecutionError("github_search_code", f"GitHub API error: {e}")

    def get_available_tools(self) -> List[str]:
        """Get list of tools available given the current policy."""
        return self._permission_checker.filter_available_tools()

    def get_tool_schemas(
        self,
        tools: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Get schemas for available tools."""
        available = tools or self.get_available_tools()
        return self._registry.get_schemas(available)

    def get_execution_history(self) -> List[ToolResult]:
        """Get history of tool executions."""
        return list(self._execution_history)

    def update_policy(self, policy: ExecutionPolicy) -> None:
        """Update the execution policy."""
        self._policy = policy
        self._permission_checker = PermissionChecker(policy, self._registry)


# Factory function
def create_tool_executor(
    policy: ExecutionPolicy,
    *,
    mcp_client: Optional[Any] = None,
    project_root: Optional[str] = None,
) -> ToolExecutor:
    """Create a ToolExecutor with standard configuration."""
    return ToolExecutor(
        policy=policy,
        mcp_client=mcp_client,
        project_root=project_root,
    )
