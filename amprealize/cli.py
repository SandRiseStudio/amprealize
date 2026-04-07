"""Amprealize CLI providing secret scanning and ActionService parity commands."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import webbrowser
import yaml
from pathlib import Path
from datetime import datetime, timezone, date, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from amprealize.action_service import ActionService
from amprealize.adapters import (
    CLIAgentAuthServiceAdapter,
    CLIAgentOrchestratorAdapter,
    CLIConversationServiceAdapter,
    CLITaskAssignmentAdapter,
    CLIActionServiceAdapter,
    CLIBehaviorServiceAdapter,
    CLIComplianceServiceAdapter,
    CLIMetricsServiceAdapter,
    CLIReflectionAdapter,
    CLIRunServiceAdapter,
    CLIWorkflowServiceAdapter,
)
from amprealize.agent_auth import AgentAuthClient
from amprealize.device_flow import (
    DeviceAuthorizationStatus,
    DeviceFlowManager,
    DeviceFlowError,
    DeviceCodeExpiredError,
    DeviceCodeNotFoundError,
    RefreshTokenExpiredError,
    RefreshTokenNotFoundError,
    UserCodeNotFoundError,
)
from amprealize.analytics import TelemetryKPIProjector, TelemetryProjection
from amprealize.bci_service import BCIService
from amprealize.bci_contracts import (
    BehaviorSnippet,
    CitationMode,
    ComposePromptRequest,
    PromptFormat,
    PrependedBehavior,
    RetrieveRequest,
    RetrievalStrategy,
    RoleFocus,
    ValidateCitationsRequest,
)
from amprealize.behavior_retriever import BehaviorRetriever
from amprealize.compliance_service import ComplianceService
from amprealize.behavior_service import BehaviorService
from amprealize.agent_orchestrator_service import AgentOrchestratorService
from amprealize.metrics_service import MetricsService
from amprealize.reflection_service import ReflectionService
from amprealize.reflection_service_postgres import PostgresReflectionService
from amprealize.reflection_contracts import TraceFormat
from amprealize.run_service import RunService
from amprealize.task_assignments import TaskAssignmentService
from amprealize.telemetry import TelemetryClient, create_sink_from_env, FileTelemetrySink, KafkaTelemetrySink
from amprealize.workflow_service import WorkflowService
from amprealize.utils.dsn import apply_host_overrides
from amprealize.mcp_env import collect_mcp_client_env, merge_mcp_runtime_env
from amprealize.auth_tokens import (
    AuthTokenBundle,
    TokenStore,
    TokenStoreError,
    get_default_token_store,
)
from amprealize.breakeramp import BandwidthEnforcer

DEFAULT_OUTPUT = Path("security/scan_reports/latest.json")
DEFAULT_ACTOR_ID = "local-cli"
DEFAULT_ACTOR_ROLE = "STRATEGIST"
DEFAULT_TELEMETRY_EVENTS_PATH = Path.home() / ".amprealize" / "telemetry" / "events.jsonl"
BREAKERAMP_SNAPSHOT_DIR = Path.home() / ".amprealize" / "breakeramp" / "snapshots"

_ACTION_SERVICE: ActionService | None = None
_ACTION_ADAPTER: CLIActionServiceAdapter | None = None
_TASK_SERVICE: TaskAssignmentService | None = None
_TASK_ADAPTER: CLITaskAssignmentAdapter | None = None
_COMPLIANCE_SERVICE: ComplianceService | None = None
_COMPLIANCE_ADAPTER: CLIComplianceServiceAdapter | None = None
_BEHAVIOR_SERVICE: BehaviorService | None = None
_BEHAVIOR_ADAPTER: CLIBehaviorServiceAdapter | None = None
_WORKFLOW_SERVICE: WorkflowService | None = None
_WORKFLOW_ADAPTER: CLIWorkflowServiceAdapter | None = None
_RUN_SERVICE: RunService | None = None
_RUN_ADAPTER: CLIRunServiceAdapter | None = None
_METRICS_SERVICE: MetricsService | None = None
_METRICS_ADAPTER: CLIMetricsServiceAdapter | None = None
_AGENT_AUTH_CLIENT: AgentAuthClient | None = None
_AGENT_AUTH_ADAPTER: CLIAgentAuthServiceAdapter | None = None
_BCI_SERVICE: BCIService | None = None
_BEHAVIOR_RETRIEVER: BehaviorRetriever | None = None
_REFLECTION_SERVICE: ReflectionService | None = None
_REFLECTION_ADAPTER: CLIReflectionAdapter | None = None
_DEVICE_FLOW_MANAGER: DeviceFlowManager | None = None
_TOKEN_STORE: TokenStore | None = None
_AGENT_ORCHESTRATOR_SERVICE: AgentOrchestratorService | None = None
_AGENT_ORCHESTRATOR_ADAPTER: CLIAgentOrchestratorAdapter | None = None
_CONVERSATION_SERVICE: Any = None
_CONVERSATION_ADAPTER: CLIConversationServiceAdapter | None = None


def _create_telemetry_client(default_actor: Dict[str, str]) -> TelemetryClient:
    sink = create_sink_from_env(default_path=DEFAULT_TELEMETRY_EVENTS_PATH)
    return TelemetryClient(sink=sink, default_actor=default_actor)


def _build_cli_actor(actor_id: str, actor_role: str) -> "Actor":
    """Build the canonical CLI actor used for telemetry-aware service calls."""

    from amprealize.action_contracts import Actor

    return Actor(id=actor_id, role=actor_role, surface="cli")


def _find_local_agents_md(start: Optional[Path] = None) -> Path:
    """Find the nearest AGENTS.md, falling back to the bundled starter template."""

    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        path = candidate / "AGENTS.md"
        if path.exists():
            return path
    return Path(__file__).parent / "templates" / "AGENTS.md.starter"


def _parse_behaviors_from_markdown(markdown_text: str) -> List[Dict[str, Any]]:
    """Parse behavior definitions from an AGENTS-style markdown document."""

    pattern = re.compile(
        r"### `(behavior_\w+)`\s*\n"
        r"- \*\*When\*\*:\s*(.+?)\n"
        r"- \*\*Steps\*\*:\s*\n"
        r"((?:\s+\d+\.\s+.+?\n)+)",
        re.MULTILINE,
    )
    behaviors: List[Dict[str, Any]] = []

    for match in pattern.finditer(markdown_text):
        name = match.group(1)
        when_clause = match.group(2).strip()
        steps_raw = match.group(3)

        steps: List[str] = []
        for step_match in re.finditer(
            r"\d+\.\s+(.+?)(?=\n\s+\d+\.|\n\n|\Z)",
            steps_raw,
            re.DOTALL,
        ):
            steps.append(re.sub(r"\s+", " ", step_match.group(1).strip()))

        keywords = sorted(
            {
                token
                for token in re.findall(r"[a-z0-9_]+", f"{name} {when_clause}".lower())
                if len(token) > 2
                and token not in {"behavior", "when", "with", "from", "that", "this"}
            }
        )

        behaviors.append(
            {
                "name": name,
                "description": f"Trigger: {when_clause}",
                "instruction": "Steps:\n" + "\n".join(
                    f"{index}. {step}" for index, step in enumerate(steps, start=1)
                ),
                "role_focus": "Student",
                "trigger_keywords": keywords,
                "score": 0.0,
                "confidence_score": None,
            }
        )

    return behaviors


def _score_local_behavior(task_description: str, behavior: Dict[str, Any]) -> float:
    """Score a local handbook behavior against the task using token overlap."""

    query_tokens = {
        token
        for token in re.findall(r"[a-z0-9_]+", task_description.lower())
        if len(token) > 2
    }
    if not query_tokens:
        return 0.0

    haystack = " ".join(
        [
            behavior["name"],
            behavior["description"],
            behavior["instruction"],
            " ".join(behavior["trigger_keywords"]),
        ]
    ).lower()
    haystack_tokens = {
        token for token in re.findall(r"[a-z0-9_]+", haystack) if len(token) > 2
    }
    if not haystack_tokens:
        return 0.0

    matches = sum(1 for token in query_tokens if token in haystack_tokens)
    return matches / len(query_tokens)


def _get_local_behaviors_for_task(
    task_description: str,
    role: str,
    limit: int,
) -> Dict[str, Any]:
    """Return behavior guidance from the local handbook without database access."""

    from amprealize.behavior_service import BehaviorService

    agents_path = _find_local_agents_md()
    behaviors = _parse_behaviors_from_markdown(agents_path.read_text(encoding="utf-8"))
    scored: List[Dict[str, Any]] = []

    for behavior in behaviors:
        scored_behavior = dict(behavior)
        scored_behavior["score"] = _score_local_behavior(task_description, behavior)
        if task_description and scored_behavior["score"] == 0.0:
            continue
        scored.append(scored_behavior)

    scored.sort(key=lambda item: item["score"], reverse=True)
    recommended = scored[:limit]

    return {
        "behaviors": recommended,
        "recommended_behaviors": recommended,
        "role_advisory": BehaviorService._get_role_advisory(BehaviorService, role, recommended),
        "role": role,
        "task_description": task_description,
        "source": "local_handbook_fallback",
        "agents_path": str(agents_path),
    }


def _should_use_local_behavior_fallback(exc: Exception) -> bool:
    """Return True when the behavior backend is unavailable and CLI should fall back."""

    message = str(exc).lower()
    markers = (
        "connection to server at",
        "connection refused",
        "could not connect",
        "operation not permitted",
        "temporary failure in name resolution",
        "redis",
    )
    return any(marker in message for marker in markers)


def _behavior_backend_is_reachable() -> bool:
    """Check whether a configured behavior Postgres backend is reachable from the CLI."""

    from amprealize.utils.dsn import build_dsn_from_components, apply_host_overrides

    dsn = (
        os.getenv("AMPREALIZE_BEHAVIOR_PG_DSN")
        or build_dsn_from_components("BEHAVIOR")
        or os.getenv("DATABASE_URL")
    )
    if not dsn:
        return False

    parsed = urlparse(apply_host_overrides(dsn, "BEHAVIOR") or dsn)
    host = parsed.hostname
    port = parsed.port or 5432
    if not host:
        return False

    try:
        with socket.create_connection((host, port), timeout=0.2):
            return True
    except OSError:
        return False


def _collect_mcp_env(workspace_root: Optional[Path] = None) -> Dict[str, str]:
    """Collect the small client env shim needed to launch the MCP server."""

    _ = workspace_root
    return collect_mcp_client_env(os.environ)


def _repo_mcp_launcher_path(workspace_root: Path) -> Path:
    return workspace_root / "scripts" / "start_amprealize_mcp.py"


def _use_repo_mcp_launcher(workspace_root: Path) -> bool:
    """True when the monorepo launcher script is present (clone / editable dev)."""

    return _repo_mcp_launcher_path(workspace_root).is_file()


def _build_mcp_server_base_config(
    workspace_root: Optional[Path] = None,
    python_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the shared stdio launch config used across MCP clients."""

    root = (workspace_root or Path.cwd()).resolve()
    resolved_python = python_path or (
        shutil.which("python3") or shutil.which("python") or sys.executable
    )
    if _use_repo_mcp_launcher(root):
        args: List[str] = [str(Path("scripts") / "start_amprealize_mcp.py")]
    else:
        args = ["-m", "amprealize.mcp_server"]
    config: Dict[str, Any] = {
        "command": resolved_python,
        "args": args,
        "cwd": str(root),
    }
    env = _collect_mcp_env(root)
    if env:
        config["env"] = env
    return config


def _build_cursor_mcp_config(
    workspace_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Build Cursor-specific MCP config using ${workspaceFolder} interpolation.

    Cursor does not support ``cwd`` in its MCP config.  It requires
    ``type: "stdio"`` and resolves ``${workspaceFolder}`` to the directory
    containing ``.cursor/mcp.json``.
    """

    root = (workspace_root or Path.cwd()).resolve()
    venv_unix = root / ".venv" / "bin" / "python"
    venv_win = root / ".venv" / "Scripts" / "python.exe"
    if venv_unix.exists():
        command = "${workspaceFolder}/.venv/bin/python"
    elif venv_win.exists():
        command = "${workspaceFolder}/.venv/Scripts/python.exe"
    else:
        command = "python3" if os.name != "nt" else "python"

    if _use_repo_mcp_launcher(root):
        mcp_args = ["${workspaceFolder}/scripts/start_amprealize_mcp.py"]
    else:
        mcp_args = ["-m", "amprealize.mcp_server"]

    config: Dict[str, Any] = {
        "type": "stdio",
        "command": command,
        "args": mcp_args,
        "env": {"PYTHONUNBUFFERED": "1"},
    }
    env_file = root / ".env"
    if env_file.exists():
        config["envFile"] = "${workspaceFolder}/.env"
    return config


def _build_ide_mcp_configs(
    workspace_root: Optional[Path] = None,
    python_path: Optional[str] = None,
) -> List[Tuple[str, Dict[str, Any]]]:
    """Build portable IDE MCP configs that launch via the shared workspace script."""

    base = _build_mcp_server_base_config(workspace_root=workspace_root, python_path=python_path)

    vscode_config = {"servers": {"amprealize": {"type": "stdio", **base}}}
    claude_config = {"mcpServers": {"amprealize": dict(base)}}
    cursor_config = {"mcpServers": {"amprealize": _build_cursor_mcp_config(workspace_root)}}

    return [
        (".vscode/mcp.json", vscode_config),
        (".claude/mcp.json", claude_config),
        (".cursor/mcp.json", cursor_config),
    ]


def _build_codex_mcp_server_config(
    workspace_root: Optional[Path] = None,
    python_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the Amprealize MCP server entry for Codex config.toml.

    Uses absolute paths for command and args since Codex does not support
    variable interpolation like ``${workspaceFolder}``.  Prefers the repo
    ``.venv`` python to avoid re-exec overhead.
    """

    root = (workspace_root or Path.cwd()).resolve()
    venv_unix = root / ".venv" / "bin" / "python"
    venv_win = root / ".venv" / "Scripts" / "python.exe"
    if venv_unix.exists():
        resolved_python = str(venv_unix)
    elif venv_win.exists():
        resolved_python = str(venv_win)
    else:
        resolved_python = python_path or (
            shutil.which("python3") or shutil.which("python") or sys.executable
        )
    if _use_repo_mcp_launcher(root):
        codex_args = [str(root / "scripts" / "start_amprealize_mcp.py")]
    else:
        codex_args = ["-m", "amprealize.mcp_server"]

    return {
        "enabled": True,
        "required": False,
        "command": resolved_python,
        "args": codex_args,
        "cwd": str(root),
        "startup_timeout_sec": 20,
        "tool_timeout_sec": 120,
        "env": collect_mcp_client_env(os.environ),
    }


def _render_toml_value(value: Any) -> str:
    """Render a small TOML value subset used by the Codex MCP config writer."""

    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, list):
        return "[" + ", ".join(_render_toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(
            f"{key} = {_render_toml_value(item)}" for key, item in value.items()
        ) + " }"
    raise TypeError(f"Unsupported TOML value type: {type(value)!r}")


def _render_codex_mcp_server_block(
    server_name: str,
    config: Dict[str, Any],
) -> str:
    """Render a `[mcp_servers.<name>]` block for Codex config.toml."""

    ordered_keys = [
        "enabled",
        "required",
        "command",
        "args",
        "cwd",
        "startup_timeout_sec",
        "tool_timeout_sec",
        "env",
    ]
    lines = [f"[mcp_servers.{server_name}]"]
    for key in ordered_keys:
        if key in config:
            lines.append(f"{key} = {_render_toml_value(config[key])}")
    return "\n".join(lines) + "\n"


def _upsert_codex_mcp_server_config(
    config_path: Path,
    server_name: str = "amprealize",
    workspace_root: Optional[Path] = None,
    python_path: Optional[str] = None,
) -> str:
    """Create or update the Amprealize MCP server block in Codex config.toml."""

    block = _render_codex_mcp_server_block(
        server_name,
        _build_codex_mcp_server_config(workspace_root=workspace_root, python_path=python_path),
    )
    header = f"[mcp_servers.{server_name}]"
    pattern = re.compile(
        rf"(?ms)^\[{re.escape(f'mcp_servers.{server_name}')}\]\n.*?(?=^\[|\Z)"
    )

    config_path.parent.mkdir(parents=True, exist_ok=True)
    if not config_path.exists():
        config_path.write_text(block, encoding="utf-8")
        return "created"

    contents = config_path.read_text(encoding="utf-8")
    match = pattern.search(contents)
    if match:
        existing_block = match.group(0)
        if existing_block.rstrip() + "\n" == block:
            return "unchanged"
        updated = contents[: match.start()] + block + contents[match.end() :]
        config_path.write_text(updated.rstrip() + "\n", encoding="utf-8")
        return "updated"

    separator = ""
    if contents and not contents.endswith("\n"):
        separator = "\n\n"
    elif contents and not contents.endswith("\n\n"):
        separator = "\n"

    config_path.write_text(contents + separator + block, encoding="utf-8")
    return "updated"


def _frame_mcp_message(message: Dict[str, Any]) -> bytes:
    """Encode an MCP JSON-RPC message with Content-Length framing."""

    body = json.dumps(message).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


def _read_framed_mcp_message(stream: Any) -> Dict[str, Any]:
    """Read a single Content-Length framed MCP response."""

    headers: Dict[str, str] = {}
    while True:
        line = stream.readline()
        if line == b"":
            raise RuntimeError("MCP server closed stdout before returning a response")
        if line in (b"\r\n", b"\n"):
            break
        key, _, value = line.decode("utf-8").partition(":")
        if not value:
            raise RuntimeError(f"Malformed MCP header line: {line!r}")
        headers[key.strip().lower()] = value.strip()

    content_length = headers.get("content-length")
    if not content_length:
        raise RuntimeError("MCP response missing Content-Length header")

    body = stream.read(int(content_length))
    if not body:
        raise RuntimeError("MCP response body was empty")
    return json.loads(body)


def _run_mcp_smoke_test(timeout: float = 10.0) -> Dict[str, Any]:
    """Start the MCP server, run initialize + tools/list, and return summary data."""

    repo_root = Path.cwd().resolve()
    env = merge_mcp_runtime_env(repo_root, os.environ)
    launcher = repo_root / "scripts" / "start_amprealize_mcp.py"
    if launcher.is_file():
        mcp_argv = [sys.executable, str(launcher)]
    else:
        mcp_argv = [sys.executable, "-m", "amprealize.mcp_server"]

    proc = subprocess.Popen(  # noqa: S603
        mcp_argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=str(repo_root),
    )

    assert proc.stdin is not None
    assert proc.stdout is not None

    try:
        proc.stdin.write(
            _frame_mcp_message(
                {
                    "jsonrpc": "2.0",
                    "id": "init",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "amprealize-cli", "version": "0.1"},
                    },
                }
            )
        )
        proc.stdin.write(
            _frame_mcp_message(
                {
                    "jsonrpc": "2.0",
                    "id": "tools",
                    "method": "tools/list",
                }
            )
        )
        proc.stdin.flush()

        responses: Dict[str, Dict[str, Any]] = {}
        started_at = time.time()
        while len(responses) < 2:
            if time.time() - started_at > timeout:
                raise RuntimeError(
                    f"Timed out after {timeout:.1f}s waiting for MCP smoke-test responses"
                )
            response = _read_framed_mcp_message(proc.stdout)
            response_id = response.get("id")
            if response_id:
                responses[str(response_id)] = response

        init_response = responses["init"]
        tools_response = responses["tools"]
        if init_response.get("error"):
            raise RuntimeError(f"initialize failed: {init_response['error']}")
        if tools_response.get("error"):
            raise RuntimeError(f"tools/list failed: {tools_response['error']}")

        tools = tools_response.get("result", {}).get("tools", [])
        if not tools:
            raise RuntimeError("tools/list succeeded but returned zero tools")

        return {
            "protocol_version": init_response.get("result", {}).get("protocolVersion"),
            "server_name": init_response.get("result", {}).get("serverInfo", {}).get("name"),
            "tool_count": len(tools),
            "sample_tools": [tool.get("name") for tool in tools[:5]],
        }
    finally:
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            proc.kill()
            proc.wait(timeout=2)


def _get_action_adapter() -> CLIActionServiceAdapter:
    global _ACTION_SERVICE, _ACTION_ADAPTER
    if _ACTION_SERVICE is None:
        _ACTION_SERVICE = ActionService()
    if _ACTION_ADAPTER is None:
        _ACTION_ADAPTER = CLIActionServiceAdapter(_ACTION_SERVICE)
    return _ACTION_ADAPTER


def _reset_action_state_for_testing() -> None:
    """Reinitialize service singletons used by CLI commands (test helper)."""

    global _ACTION_SERVICE, _ACTION_ADAPTER
    global _TASK_SERVICE, _TASK_ADAPTER
    global _COMPLIANCE_SERVICE, _COMPLIANCE_ADAPTER
    global _BEHAVIOR_SERVICE, _BEHAVIOR_ADAPTER
    global _WORKFLOW_SERVICE, _WORKFLOW_ADAPTER
    global _RUN_SERVICE, _RUN_ADAPTER
    global _METRICS_SERVICE, _METRICS_ADAPTER
    global _AGENT_AUTH_CLIENT, _AGENT_AUTH_ADAPTER
    global _BCI_SERVICE, _BEHAVIOR_RETRIEVER
    global _REFLECTION_SERVICE, _REFLECTION_ADAPTER
    global _DEVICE_FLOW_MANAGER, _TOKEN_STORE
    global _AGENT_ORCHESTRATOR_SERVICE, _AGENT_ORCHESTRATOR_ADAPTER

    _ACTION_SERVICE = ActionService()
    _ACTION_ADAPTER = CLIActionServiceAdapter(_ACTION_SERVICE)
    _TASK_SERVICE = None
    _TASK_ADAPTER = None
    _COMPLIANCE_SERVICE = None
    _COMPLIANCE_ADAPTER = None
    _BEHAVIOR_SERVICE = None
    _BEHAVIOR_ADAPTER = None
    _WORKFLOW_SERVICE = None
    _WORKFLOW_ADAPTER = None
    _RUN_SERVICE = None
    _RUN_ADAPTER = None
    _METRICS_SERVICE = None
    _METRICS_ADAPTER = None
    _AGENT_AUTH_CLIENT = None
    _AGENT_AUTH_ADAPTER = None
    _BCI_SERVICE = None
    _BEHAVIOR_RETRIEVER = None
    _REFLECTION_SERVICE = None
    _REFLECTION_ADAPTER = None
    _DEVICE_FLOW_MANAGER = None
    _TOKEN_STORE = None
    _AGENT_ORCHESTRATOR_SERVICE = None
    _AGENT_ORCHESTRATOR_ADAPTER = None


def _get_task_adapter() -> CLITaskAssignmentAdapter:
    global _TASK_SERVICE, _TASK_ADAPTER
    if _TASK_SERVICE is None:
        _TASK_SERVICE = TaskAssignmentService()
    if _TASK_ADAPTER is None:
        _TASK_ADAPTER = CLITaskAssignmentAdapter(_TASK_SERVICE)
    return _TASK_ADAPTER


def _get_compliance_adapter() -> CLIComplianceServiceAdapter:
    global _COMPLIANCE_SERVICE, _COMPLIANCE_ADAPTER
    if _COMPLIANCE_SERVICE is None:
        _COMPLIANCE_SERVICE = ComplianceService()
    if _COMPLIANCE_ADAPTER is None:
        _COMPLIANCE_ADAPTER = CLIComplianceServiceAdapter(_COMPLIANCE_SERVICE)
    return _COMPLIANCE_ADAPTER


def _get_behavior_adapter() -> CLIBehaviorServiceAdapter:
    global _BEHAVIOR_SERVICE, _BEHAVIOR_ADAPTER
    if _BEHAVIOR_SERVICE is None:
        _BEHAVIOR_SERVICE = BehaviorService()
    if _BEHAVIOR_ADAPTER is None:
        _BEHAVIOR_ADAPTER = CLIBehaviorServiceAdapter(_BEHAVIOR_SERVICE)
    return _BEHAVIOR_ADAPTER


def _get_workflow_adapter() -> CLIWorkflowServiceAdapter:
    global _WORKFLOW_SERVICE, _WORKFLOW_ADAPTER, _BEHAVIOR_SERVICE
    if _BEHAVIOR_SERVICE is None:
        _BEHAVIOR_SERVICE = BehaviorService()
    if _WORKFLOW_SERVICE is None:
        # WorkflowService now uses PostgreSQL DSN from environment
        _WORKFLOW_SERVICE = WorkflowService(dsn=None, behavior_service=_BEHAVIOR_SERVICE)
    if _WORKFLOW_ADAPTER is None:
        _WORKFLOW_ADAPTER = CLIWorkflowServiceAdapter(_WORKFLOW_SERVICE)
    return _WORKFLOW_ADAPTER


def _get_bci_service() -> BCIService:
    """Get or create BCIService singleton with BehaviorRetriever."""
    global _BCI_SERVICE, _BEHAVIOR_RETRIEVER, _BEHAVIOR_SERVICE
    if _BEHAVIOR_SERVICE is None:
        _BEHAVIOR_SERVICE = BehaviorService()
    if _BEHAVIOR_RETRIEVER is None:
        _BEHAVIOR_RETRIEVER = BehaviorRetriever(behavior_service=_BEHAVIOR_SERVICE)
    if _BCI_SERVICE is None:
        _BCI_SERVICE = BCIService(
            behavior_service=_BEHAVIOR_SERVICE,
            behavior_retriever=_BEHAVIOR_RETRIEVER,
        )
    return _BCI_SERVICE


def _get_reflection_adapter() -> CLIReflectionAdapter:
    """Get or create CLIReflectionAdapter singleton.

    Uses PostgreSQL backend when AMPREALIZE_REFLECTION_PG_DSN is set,
    otherwise falls back to in-memory implementation.
    """
    global _REFLECTION_SERVICE, _REFLECTION_ADAPTER, _BEHAVIOR_SERVICE, _BCI_SERVICE
    if _BEHAVIOR_SERVICE is None:
        _BEHAVIOR_SERVICE = BehaviorService()
    if _BCI_SERVICE is None:
        _BCI_SERVICE = BCIService(behavior_service=_BEHAVIOR_SERVICE)
    if _REFLECTION_SERVICE is None:
        dsn = apply_host_overrides(os.environ.get("AMPREALIZE_REFLECTION_PG_DSN"), "REFLECTION")
        if dsn:
            _REFLECTION_SERVICE = PostgresReflectionService(
                dsn=dsn,
                behavior_service=_BEHAVIOR_SERVICE,
                bci_service=_BCI_SERVICE,
            )
        else:
            _REFLECTION_SERVICE = ReflectionService(
                behavior_service=_BEHAVIOR_SERVICE,
                bci_service=_BCI_SERVICE,
            )
    if _REFLECTION_ADAPTER is None:
        _REFLECTION_ADAPTER = CLIReflectionAdapter(_REFLECTION_SERVICE)
    return _REFLECTION_ADAPTER


def _get_run_adapter() -> CLIRunServiceAdapter:
    """Get or create CLIRunServiceAdapter singleton.

    Uses PostgreSQL backend when AMPREALIZE_RUN_PG_DSN is set,
    otherwise falls back to SQLite (not recommended for production).
    """
    global _RUN_SERVICE, _RUN_ADAPTER
    if _RUN_SERVICE is None:
        dsn = apply_host_overrides(os.environ.get("AMPREALIZE_RUN_PG_DSN"), "RUN")
        if dsn:
            from amprealize.run_service_postgres import PostgresRunService
            _RUN_SERVICE = PostgresRunService(dsn=dsn)
        else:
            import warnings
            warnings.warn(
                "AMPREALIZE_RUN_PG_DSN not set - using SQLite RunService (not recommended for production)",
                UserWarning,
                stacklevel=2,
            )
            _RUN_SERVICE = RunService()
    if _RUN_ADAPTER is None:
        _RUN_ADAPTER = CLIRunServiceAdapter(_RUN_SERVICE)
    return _RUN_ADAPTER


def _get_metrics_adapter() -> CLIMetricsServiceAdapter:
    """Get or create CLIMetricsServiceAdapter singleton."""
    global _METRICS_SERVICE, _METRICS_ADAPTER
    if _METRICS_SERVICE is None:
        _METRICS_SERVICE = MetricsService()
    if _METRICS_ADAPTER is None:
        _METRICS_ADAPTER = CLIMetricsServiceAdapter(_METRICS_SERVICE)
    return _METRICS_ADAPTER


def _get_agent_auth_adapter() -> CLIAgentAuthServiceAdapter:
    """Get or create CLIAgentAuthServiceAdapter singleton."""
    global _AGENT_AUTH_CLIENT, _AGENT_AUTH_ADAPTER
    if _AGENT_AUTH_CLIENT is None:
        _AGENT_AUTH_CLIENT = AgentAuthClient()
    if _AGENT_AUTH_ADAPTER is None:
        _AGENT_AUTH_ADAPTER = CLIAgentAuthServiceAdapter(_AGENT_AUTH_CLIENT)
    return _AGENT_AUTH_ADAPTER


def _get_device_flow_manager() -> DeviceFlowManager:
    """Return the shared device flow manager instance."""

    global _DEVICE_FLOW_MANAGER
    if _DEVICE_FLOW_MANAGER is None:
        telemetry = _create_telemetry_client(
            {
                "id": DEFAULT_ACTOR_ID,
                "role": DEFAULT_ACTOR_ROLE,
                "surface": "CLI",
            }
        )
        _DEVICE_FLOW_MANAGER = DeviceFlowManager(telemetry=telemetry)
    return _DEVICE_FLOW_MANAGER


def _get_agent_orchestrator_adapter() -> CLIAgentOrchestratorAdapter:
    """Get or create CLIAgentOrchestratorAdapter singleton."""

    global _AGENT_ORCHESTRATOR_SERVICE, _AGENT_ORCHESTRATOR_ADAPTER
    if _AGENT_ORCHESTRATOR_SERVICE is None:
        _AGENT_ORCHESTRATOR_SERVICE = AgentOrchestratorService()
    if _AGENT_ORCHESTRATOR_ADAPTER is None:
        _AGENT_ORCHESTRATOR_ADAPTER = CLIAgentOrchestratorAdapter(_AGENT_ORCHESTRATOR_SERVICE)
    return _AGENT_ORCHESTRATOR_ADAPTER


def _get_conversation_adapter() -> CLIConversationServiceAdapter:
    """Get or create CLIConversationServiceAdapter singleton."""

    global _CONVERSATION_SERVICE, _CONVERSATION_ADAPTER
    if _CONVERSATION_SERVICE is None:
        from amprealize.services.conversation_service import ConversationService
        _CONVERSATION_SERVICE = ConversationService()
    if _CONVERSATION_ADAPTER is None:
        _CONVERSATION_ADAPTER = CLIConversationServiceAdapter(_CONVERSATION_SERVICE)
    return _CONVERSATION_ADAPTER


def _get_token_store(*, allow_plaintext: Optional[bool] = None) -> TokenStore:
    """Lazily construct the token store used by CLI auth commands."""

    global _TOKEN_STORE
    if _TOKEN_STORE is None:
        _TOKEN_STORE = get_default_token_store(allow_plaintext=allow_plaintext)
    return _TOKEN_STORE


def _normalize_user_code(user_code: str) -> str:
    """Normalise user code input (case-insensitive, remove separators)."""

    alphanumeric = "".join(ch for ch in user_code if ch.isalnum())
    if not alphanumeric:
        raise ValueError("user_code must contain letters or numbers")
    upper = alphanumeric.upper()
    if len(upper) >= 8:
        midpoint = len(upper) // 2
        return f"{upper[:midpoint]}-{upper[midpoint:]}"
    return upper


# ---------------------------------------------------------------------------
# Module gating for CLI commands
# ---------------------------------------------------------------------------

# Maps CLI command names to the module registry CLI group(s) they require.
# Commands NOT listed here are always available (platform/core).
_CLI_COMMAND_MODULE_MAP: dict[str, tuple[str, ...]] = {
    "behaviors": ("behavior",),
    "compliance": ("behavior",),    # compliance checks behavior adherence
    "bci": ("bci",),
    "agents": ("agent",),
    "workflow": ("agent",),
    "run": ("run",),               # run management belongs to agents module
    "reflection": ("reflection",),
}


def _check_cli_module_enabled(command_name: str) -> str | None:
    """Check if a CLI command's module is enabled.

    Returns:
        ``None`` if the command is allowed (module enabled or no config yet),
        otherwise an error message string.
    """
    required_groups = _CLI_COMMAND_MODULE_MAP.get(command_name)
    if not required_groups:
        return None  # Not module-gated

    try:
        from amprealize.config.loader import get_config
        from amprealize.module_registry import get_enabled_cli_groups

        enabled = get_enabled_cli_groups(get_config().modules)
    except Exception:
        return None  # No config yet -- allow everything (e.g. first run)

    # Command is allowed if ANY of its required groups is enabled
    if any(g in enabled for g in required_groups):
        return None

    return (
        f"The '{command_name}' command requires a module that is not enabled.\n"
        f"Run 'amprealize config set modules.<module> true' to enable it,\n"
        f"or re-run 'amprealize init' to reconfigure modules."
    )


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="amprealize", description="Amprealize developer tooling")
    subparsers = parser.add_subparsers(dest="command")

    scan_parser = subparsers.add_parser(
        "scan-secrets",
        help="Run repo-wide secret scan via gitleaks and emit a structured report",
    )
    scan_parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format for findings",
    )
    scan_parser.add_argument(
        "--fail-on-findings",
        action="store_true",
        help="Return a non-zero exit code when findings are detected",
    )
    scan_parser.add_argument(
        "--output",
        type=str,
        help="Path to save the JSON report (defaults to security/scan_reports/latest.json)",
    )

    record_parser = subparsers.add_parser(
        "record-action",
        help="Record an action via ActionService and emit the stored payload",
    )
    record_parser.add_argument("--artifact", dest="artifact_path", required=True, help="Artifact path impacted")
    record_parser.add_argument("--summary", required=True, help="Human readable summary (<=160 chars)")
    record_parser.add_argument(
        "--behavior",
        dest="behaviors",
        action="append",
        required=True,
        help="Behavior identifier referenced by the action (repeat for multiple)",
    )
    record_parser.add_argument(
        "--metadata",
        dest="metadata_items",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Inline metadata key=value pairs (repeatable)",
    )
    record_parser.add_argument(
        "--metadata-file",
        dest="metadata_file",
        type=str,
        help="Path to a JSON file containing additional metadata (dict)",
    )
    record_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier (defaults to local-cli)")
    record_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role such as STRATEGIST")
    record_parser.add_argument("--related-run-id", help="Optional RunService identifier")
    record_parser.add_argument("--audit-log-event-id", help="Optional audit log event identifier")
    record_parser.add_argument("--checksum", help="Optional checksum override (SHA-256)")
    record_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format for the recorded action",
    )

    list_parser = subparsers.add_parser(
        "list-actions",
        help="List recorded actions across the current CLI session",
    )
    list_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    get_parser = subparsers.add_parser(
        "get-action",
        help="Retrieve a single action by ID",
    )
    get_parser.add_argument("action_id", help="Identifier returned by record-action or list-actions")
    get_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    replay_parser = subparsers.add_parser(
        "replay-actions",
        help="Trigger a replay job for one or more recorded actions",
    )
    replay_parser.add_argument("action_ids", nargs="+", help="Action identifiers to replay")
    replay_parser.add_argument(
        "--strategy",
        choices=("SEQUENTIAL", "PARALLEL"),
        default="SEQUENTIAL",
        help="Replay scheduling strategy",
    )
    replay_parser.add_argument("--skip-existing", action="store_true", help="Skip actions already replayed successfully")
    replay_parser.add_argument("--dry-run", action="store_true", help="Plan replay without executing commands")
    replay_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    replay_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    replay_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format for the replay status",
    )

    status_parser = subparsers.add_parser(
        "replay-status",
        help="Fetch the status of a previously triggered replay job",
    )
    status_parser.add_argument("replay_id", help="Identifier returned by replay-actions")
    status_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    dr_parser = subparsers.add_parser(
        "dr",
        help="Disaster recovery commands (backup, restore, status, failover)",
    )
    dr_parser.add_argument(
        "dr_args",
        nargs=argparse.REMAINDER,
        default=[],
        help="Arguments forwarded to the DR CLI (prefix with '--' to stop argparse parsing)",
    )

    tasks_parser = subparsers.add_parser(
        "tasks",
        help="List outstanding task assignments filtered by function",
    )
    tasks_parser.add_argument(
        "--function",
        dest="function",
        help="Filter tasks by function (engineering, dx, devops, product, pm, copywriting, compliance)",
    )
    tasks_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format for the task assignments",
    )

    # Behavior subcommands
    behaviors_parser = subparsers.add_parser(
        "behaviors",
        help="Manage handbook behaviors and lifecycle",
    )
    behaviors_subparsers = behaviors_parser.add_subparsers(dest="behaviors_command")

    behaviors_create_parser = behaviors_subparsers.add_parser(
        "create",
        help="Create a new behavior draft",
    )
    behaviors_create_parser.add_argument("--name", required=True, help="Behavior name (unique)")
    behaviors_create_parser.add_argument("--description", required=True, help="Short description")
    behaviors_create_parser.add_argument("--instruction", required=True, help="Behavior instruction text")
    behaviors_create_parser.add_argument(
        "--role",
        dest="role_focus",
        required=True,
        choices=["STRATEGIST", "TEACHER", "STUDENT", "MULTI_ROLE"],
        help="Primary role this behavior targets",
    )
    behaviors_create_parser.add_argument(
        "--tag",
        dest="tags",
        action="append",
        default=[],
        help="Tag to apply (repeatable)",
    )
    behaviors_create_parser.add_argument(
        "--keyword",
        dest="keywords",
        action="append",
        default=[],
        help="Trigger keyword hint (repeatable)",
    )
    behaviors_create_parser.add_argument(
        "--metadata",
        dest="metadata_items",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Metadata key/value (repeatable)",
    )
    behaviors_create_parser.add_argument("--metadata-file", help="Path to JSON file with metadata object")
    behaviors_create_parser.add_argument(
        "--examples-file",
        help="Path to JSON file with example objects [{\"title\":..., \"body\":...}]",
    )
    behaviors_create_parser.add_argument(
        "--embedding",
        help="Comma-separated embedding vector (optional, length <= 1024)",
    )
    behaviors_create_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    behaviors_create_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    behaviors_create_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    behaviors_list_parser = behaviors_subparsers.add_parser(
        "list",
        help="List behaviors",
    )
    behaviors_list_parser.add_argument("--status", help="Filter by behavior status")
    behaviors_list_parser.add_argument(
        "--tag",
        dest="tags",
        action="append",
        default=[],
        help="Filter by tag (repeatable)",
    )
    behaviors_list_parser.add_argument("--role", dest="role_focus", help="Filter by role focus")
    behaviors_list_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format",
    )

    behaviors_search_parser = behaviors_subparsers.add_parser(
        "search",
        help="Search behaviors using lexical filters",
    )
    behaviors_search_parser.add_argument("--query", help="Search query")
    behaviors_search_parser.add_argument(
        "--tag",
        dest="tags",
        action="append",
        default=[],
        help="Filter by tag (repeatable)",
    )
    behaviors_search_parser.add_argument("--role", dest="role_focus", help="Filter by role focus")
    behaviors_search_parser.add_argument("--status", help="Filter by status")
    behaviors_search_parser.add_argument("--limit", type=int, default=25, help="Max results (<= 100)")
    behaviors_search_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    behaviors_search_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    behaviors_search_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format",
    )

    behaviors_get_parser = behaviors_subparsers.add_parser(
        "get",
        help="Retrieve a behavior with version history",
    )
    behaviors_get_parser.add_argument("behavior_id", help="Behavior identifier")
    behaviors_get_parser.add_argument("--version", help="Specific version to fetch")
    behaviors_get_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    behaviors_update_parser = behaviors_subparsers.add_parser(
        "update",
        help="Update a draft or in-review behavior version",
    )
    behaviors_update_parser.add_argument("behavior_id", help="Behavior identifier")
    behaviors_update_parser.add_argument("--version", required=True, help="Version to update")
    behaviors_update_parser.add_argument("--instruction", help="New instruction text")
    behaviors_update_parser.add_argument("--description", help="Updated description")
    behaviors_update_parser.add_argument(
        "--tag",
        dest="tags",
        action="append",
        help="Replace tags (repeatable)",
    )
    behaviors_update_parser.add_argument(
        "--keyword",
        dest="keywords",
        action="append",
        help="Replace trigger keywords (repeatable)",
    )
    behaviors_update_parser.add_argument(
        "--metadata",
        dest="metadata_items",
        action="append",
        metavar="KEY=VALUE",
        help="Replace metadata entries (repeatable)",
    )
    behaviors_update_parser.add_argument("--metadata-file", help="Path to JSON metadata object")
    behaviors_update_parser.add_argument("--examples-file", help="Path to JSON examples array")
    behaviors_update_parser.add_argument("--embedding", help="Comma-separated embedding vector")
    behaviors_update_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    behaviors_update_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    behaviors_update_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    behaviors_submit_parser = behaviors_subparsers.add_parser(
        "submit",
        help="Submit a draft for review",
    )
    behaviors_submit_parser.add_argument("behavior_id", help="Behavior identifier")
    behaviors_submit_parser.add_argument("--version", required=True, help="Version to submit")
    behaviors_submit_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    behaviors_submit_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    behaviors_submit_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    behaviors_approve_parser = behaviors_subparsers.add_parser(
        "approve",
        help="Approve a behavior version",
    )
    behaviors_approve_parser.add_argument("behavior_id", help="Behavior identifier")
    behaviors_approve_parser.add_argument("--version", required=True, help="Version to approve")
    behaviors_approve_parser.add_argument(
        "--effective-from",
        dest="effective_from",
        required=True,
        help="ISO timestamp when approval becomes active",
    )
    behaviors_approve_parser.add_argument("--approval-action", dest="approval_action_id", help="Action log ID")
    behaviors_approve_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    behaviors_approve_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    behaviors_approve_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    behaviors_deprecate_parser = behaviors_subparsers.add_parser(
        "deprecate",
        help="Deprecate an approved behavior version",
    )
    behaviors_deprecate_parser.add_argument("behavior_id", help="Behavior identifier")
    behaviors_deprecate_parser.add_argument("--version", required=True, help="Version to deprecate")
    behaviors_deprecate_parser.add_argument(
        "--effective-to",
        dest="effective_to",
        required=True,
        help="ISO timestamp when version is retired",
    )
    behaviors_deprecate_parser.add_argument(
        "--successor",
        dest="successor_behavior_id",
        help="Optional successor behavior identifier",
    )
    behaviors_deprecate_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    behaviors_deprecate_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    behaviors_deprecate_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    behaviors_delete_parser = behaviors_subparsers.add_parser(
        "delete-draft",
        help="Delete a draft behavior version",
    )
    behaviors_delete_parser.add_argument("behavior_id", help="Behavior identifier")
    behaviors_delete_parser.add_argument("--version", required=True, help="Draft version to delete")
    behaviors_delete_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    behaviors_delete_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")

    # Propose: create behavior from observed pattern with confidence scoring
    behaviors_propose_parser = behaviors_subparsers.add_parser(
        "propose",
        help="Propose a new behavior from observed patterns (triggers auto-approval if confidence >= 0.8)",
    )
    behaviors_propose_parser.add_argument("--name", required=True, help="Behavior name (must follow behavior_<verb>_<noun> pattern)")
    behaviors_propose_parser.add_argument("--description", required=True, help="Short description of the behavior")
    behaviors_propose_parser.add_argument("--instruction", required=True, help="Detailed instruction text")
    behaviors_propose_parser.add_argument(
        "--role",
        dest="role_focus",
        required=True,
        choices=["STRATEGIST", "TEACHER", "STUDENT"],
        help="Primary role this behavior targets",
    )
    behaviors_propose_parser.add_argument(
        "--confidence",
        dest="confidence_score",
        type=float,
        default=0.0,
        help="Confidence score 0.0-1.0 (>= 0.8 with 3+ validations triggers auto-approval)",
    )
    behaviors_propose_parser.add_argument(
        "--validation",
        dest="historical_validations",
        action="append",
        default=[],
        help="Run ID that validated this pattern (repeatable, need 3+ for auto-approval)",
    )
    behaviors_propose_parser.add_argument(
        "--keyword",
        dest="keywords",
        action="append",
        default=[],
        help="Trigger keyword hint (repeatable)",
    )
    behaviors_propose_parser.add_argument(
        "--tag",
        dest="tags",
        action="append",
        default=[],
        help="Tag to apply (repeatable)",
    )
    behaviors_propose_parser.add_argument("--pattern-id", help="TraceAnalysisService pattern ID that triggered proposal")
    behaviors_propose_parser.add_argument("--rationale", help="Rationale for why this behavior should exist")
    behaviors_propose_parser.add_argument(
        "--proposed-by-role",
        default="Strategist",
        choices=["Student", "Teacher", "Strategist"],
        help="Role of the agent proposing this behavior",
    )
    behaviors_propose_parser.add_argument("--metadata-file", help="Path to JSON file with metadata object")
    behaviors_propose_parser.add_argument("--examples-file", help="Path to JSON file with example objects")
    behaviors_propose_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    behaviors_propose_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    behaviors_propose_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    # Get-for-task: retrieve relevant behaviors for a task description
    behaviors_get_for_task_parser = behaviors_subparsers.add_parser(
        "get-for-task",
        help="Get relevant behaviors for a task (use before starting any task)",
    )
    behaviors_get_for_task_parser.add_argument("task_description", help="Natural language task description")
    behaviors_get_for_task_parser.add_argument(
        "--role",
        default="Student",
        choices=["Student", "Teacher", "Strategist", "any"],
        help="Agent's current role (for role-specific advisory)",
    )
    behaviors_get_for_task_parser.add_argument("--limit", type=int, default=5, help="Maximum behaviors to return")
    behaviors_get_for_task_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    behaviors_get_for_task_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    behaviors_get_for_task_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format",
    )

    # Compliance subcommands
    compliance_parser = subparsers.add_parser(
        "compliance",
        help="Manage compliance checklists and steps",
    )
    compliance_subparsers = compliance_parser.add_subparsers(dest="compliance_command")

    compliance_create_parser = compliance_subparsers.add_parser(
        "create-checklist",
        help="Create a new compliance checklist",
    )
    compliance_create_parser.add_argument("--title", required=True, help="Checklist title")
    compliance_create_parser.add_argument("--description", default="", help="Checklist description")
    compliance_create_parser.add_argument("--template-id", help="Template identifier")
    compliance_create_parser.add_argument("--milestone", help="Milestone label (e.g., Milestone 1)")
    compliance_create_parser.add_argument(
        "--category",
        dest="compliance_category",
        action="append",
        required=True,
        help="Compliance category (repeatable: SOC2, GDPR, Internal)",
    )
    compliance_create_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    compliance_create_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    compliance_create_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    compliance_record_parser = compliance_subparsers.add_parser(
        "record-step",
        help="Record a checklist step with evidence",
    )
    compliance_record_parser.add_argument("--checklist-id", required=True, help="Checklist identifier")
    compliance_record_parser.add_argument("--title", required=True, help="Step title")
    compliance_record_parser.add_argument(
        "--status",
        required=True,
        choices=("PENDING", "IN_PROGRESS", "COMPLETED", "FAILED", "SKIPPED"),
        help="Step status",
    )
    compliance_record_parser.add_argument(
        "--evidence",
        dest="evidence_items",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Evidence metadata key=value pairs (repeatable)",
    )
    compliance_record_parser.add_argument(
        "--behavior",
        dest="behaviors_cited",
        action="append",
        default=[],
        help="Behavior identifier referenced (repeatable)",
    )
    compliance_record_parser.add_argument("--related-run-id", help="Optional RunService identifier")
    compliance_record_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    compliance_record_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    compliance_record_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    compliance_list_parser = compliance_subparsers.add_parser(
        "list",
        help="List compliance checklists",
    )
    compliance_list_parser.add_argument("--milestone", help="Filter by milestone")
    compliance_list_parser.add_argument(
        "--category",
        dest="compliance_category",
        action="append",
        help="Filter by compliance category (repeatable)",
    )
    compliance_list_parser.add_argument(
        "--status",
        choices=("ACTIVE", "COMPLETED", "FAILED"),
        help="Filter by checklist status",
    )
    compliance_list_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    compliance_get_parser = compliance_subparsers.add_parser(
        "get",
        help="Retrieve a single checklist by ID",
    )
    compliance_get_parser.add_argument("checklist_id", help="Checklist identifier")
    compliance_get_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    compliance_validate_parser = compliance_subparsers.add_parser(
        "validate",
        help="Validate a checklist and calculate coverage",
    )
    compliance_validate_parser.add_argument("checklist_id", nargs="?", help="Checklist identifier")
    compliance_validate_parser.add_argument("--action-id", help="Validate by action identifier (alternative to checklist_id)")
    compliance_validate_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    compliance_validate_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    compliance_validate_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    # Compliance policies subcommands
    compliance_policies_parser = compliance_subparsers.add_parser(
        "policies",
        help="Manage compliance policies",
    )
    compliance_policies_subparsers = compliance_policies_parser.add_subparsers(dest="policies_command")

    policies_list_parser = compliance_policies_subparsers.add_parser(
        "list",
        help="List compliance policies",
    )
    policies_list_parser.add_argument("--org-id", help="Filter by organization ID")
    policies_list_parser.add_argument("--project-id", help="Filter by project ID")
    policies_list_parser.add_argument(
        "--type",
        dest="policy_type",
        choices=("AUDIT", "SECURITY", "COMPLIANCE", "GOVERNANCE", "CUSTOM"),
        help="Filter by policy type",
    )
    policies_list_parser.add_argument(
        "--enforcement",
        dest="enforcement_level",
        choices=("ADVISORY", "WARNING", "BLOCKING"),
        help="Filter by enforcement level",
    )
    policies_list_parser.add_argument(
        "--active-only",
        action="store_true",
        default=False,
        help="Only show active policies",
    )
    policies_list_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format",
    )

    policies_create_parser = compliance_policies_subparsers.add_parser(
        "create",
        help="Create a new compliance policy",
    )
    policies_create_parser.add_argument("--name", required=True, help="Policy name")
    policies_create_parser.add_argument("--description", required=True, help="Policy description")
    policies_create_parser.add_argument(
        "--type",
        dest="policy_type",
        required=True,
        choices=("AUDIT", "SECURITY", "COMPLIANCE", "GOVERNANCE", "CUSTOM"),
        help="Policy type",
    )
    policies_create_parser.add_argument(
        "--enforcement",
        dest="enforcement_level",
        required=True,
        choices=("ADVISORY", "WARNING", "BLOCKING"),
        help="Enforcement level",
    )
    policies_create_parser.add_argument("--org-id", help="Organization ID (for org/project scope)")
    policies_create_parser.add_argument("--project-id", help="Project ID (requires --org-id)")
    policies_create_parser.add_argument("--version", default="1.0.0", help="Policy version")
    policies_create_parser.add_argument(
        "--behavior",
        dest="required_behaviors",
        action="append",
        default=[],
        help="Required behavior ID (repeatable)",
    )
    policies_create_parser.add_argument(
        "--category",
        dest="compliance_categories",
        action="append",
        default=[],
        help="Compliance category (SOC2, GDPR, etc., repeatable)",
    )
    policies_create_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    policies_create_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    policies_create_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    policies_get_parser = compliance_policies_subparsers.add_parser(
        "get",
        help="Retrieve a single policy by ID",
    )
    policies_get_parser.add_argument("policy_id", help="Policy identifier")
    policies_get_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    # Compliance audit subcommand
    compliance_audit_parser = compliance_subparsers.add_parser(
        "audit",
        help="Generate audit trail report",
    )
    compliance_audit_parser.add_argument("--run-id", help="Filter by run ID")
    compliance_audit_parser.add_argument("--checklist-id", help="Filter by checklist ID")
    compliance_audit_parser.add_argument("--action-id", help="Filter by action ID")
    compliance_audit_parser.add_argument("--start-date", help="Filter entries after this ISO timestamp")
    compliance_audit_parser.add_argument("--end-date", help="Filter entries before this ISO timestamp")
    compliance_audit_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format",
    )

    # Workflow subcommands
    workflow_parser = subparsers.add_parser(
        "workflow",
        help="Manage workflow templates and runs",
    )
    workflow_subparsers = workflow_parser.add_subparsers(dest="workflow_command")

    workflow_create_parser = workflow_subparsers.add_parser(
        "create-template",
        help="Create a new workflow template",
    )
    workflow_create_parser.add_argument("--name", required=True, help="Template name")
    workflow_create_parser.add_argument("--description", required=True, help="Template description")
    workflow_create_parser.add_argument(
        "--role",
        dest="role_focus",
        required=True,
        choices=["STRATEGIST", "TEACHER", "STUDENT", "MULTI_ROLE"],
        help="Primary role for this workflow",
    )
    workflow_create_parser.add_argument(
        "--steps-file",
        required=True,
        help="Path to JSON file with step definitions array",
    )
    workflow_create_parser.add_argument(
        "--tag",
        dest="tags",
        action="append",
        default=[],
        help="Tag to apply (repeatable)",
    )
    workflow_create_parser.add_argument("--metadata-file", help="Path to JSON metadata object")
    workflow_create_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    workflow_create_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    workflow_create_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    workflow_list_parser = workflow_subparsers.add_parser(
        "list-templates",
        help="List workflow templates",
    )
    workflow_list_parser.add_argument("--role", dest="role_focus", help="Filter by role focus")
    workflow_list_parser.add_argument(
        "--tag",
        dest="tags",
        action="append",
        default=[],
        help="Filter by tag (repeatable)",
    )
    workflow_list_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format",
    )

    workflow_get_parser = workflow_subparsers.add_parser(
        "get-template",
        help="Retrieve a workflow template by ID",
    )
    workflow_get_parser.add_argument("template_id", help="Template identifier")
    workflow_get_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    workflow_run_parser = workflow_subparsers.add_parser(
        "run",
        help="Execute a workflow template",
    )
    workflow_run_parser.add_argument("template_id", help="Workflow template identifier")
    workflow_run_parser.add_argument(
        "--behavior",
        dest="behavior_ids",
        action="append",
        default=[],
        help="Behavior ID to attach (repeatable)",
    )
    workflow_run_parser.add_argument(
        "--no-early-retrieval",
        dest="no_early_retrieval",
        action="store_true",
        default=False,
        help="Disable Early Knowledge Alignment (EKA) - don't retrieve behaviors before planning",
    )
    workflow_run_parser.add_argument("--metadata-file", help="Path to JSON metadata object")
    workflow_run_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    workflow_run_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    workflow_run_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    workflow_status_parser = workflow_subparsers.add_parser(
        "status",
        help="Check the status of a workflow run",
    )
    workflow_status_parser.add_argument("run_id", help="Run identifier")
    workflow_status_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    # Run subcommands
    run_parser = subparsers.add_parser(
        "run",
        help="Manage workflow execution runs",
    )
    run_subparsers = run_parser.add_subparsers(dest="run_command")

    run_create_parser = run_subparsers.add_parser(
        "create",
        help="Create a new run",
    )
    run_create_parser.add_argument("--workflow-id", help="Workflow identifier")
    run_create_parser.add_argument("--workflow-name", help="Workflow name")
    run_create_parser.add_argument("--template-id", help="Template identifier")
    run_create_parser.add_argument("--template-name", help="Template name")
    run_create_parser.add_argument(
        "--behavior",
        dest="behavior_ids",
        action="append",
        default=[],
        help="Behavior ID to use (repeatable)",
    )
    run_create_parser.add_argument(
        "--no-early-retrieval",
        dest="no_early_retrieval",
        action="store_true",
        default=False,
        help="Disable Early Knowledge Alignment (EKA) - don't retrieve behaviors before planning",
    )
    run_create_parser.add_argument("--metadata-file", help="Path to JSON metadata object")
    run_create_parser.add_argument("--message", help="Initial message/description")
    run_create_parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    run_create_parser.add_argument("--actor-role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    run_create_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    run_get_parser = run_subparsers.add_parser(
        "get",
        help="Get run details by ID",
    )
    run_get_parser.add_argument("run_id", help="Run identifier")
    run_get_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    run_list_parser = run_subparsers.add_parser(
        "list",
        help="List runs with optional filters",
    )
    run_list_parser.add_argument("--status", help="Filter by status (PENDING/RUNNING/COMPLETED/FAILED/CANCELLED)")
    run_list_parser.add_argument("--workflow-id", help="Filter by workflow ID")
    run_list_parser.add_argument("--template-id", help="Filter by template ID")
    run_list_parser.add_argument("--limit", type=int, default=50, help="Maximum number of runs to return")
    run_list_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format",
    )

    run_complete_parser = run_subparsers.add_parser(
        "complete",
        help="Complete a run with final status",
    )
    run_complete_parser.add_argument("run_id", help="Run identifier")
    run_complete_parser.add_argument(
        "--status",
        required=True,
        choices=["COMPLETED", "FAILED"],
        help="Final run status",
    )
    run_complete_parser.add_argument("--outputs-file", help="Path to JSON outputs object")
    run_complete_parser.add_argument("--message", help="Completion message")
    run_complete_parser.add_argument("--error", help="Error message (for FAILED status)")
    run_complete_parser.add_argument("--metadata-file", help="Path to JSON metadata updates")
    run_complete_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    run_cancel_parser = run_subparsers.add_parser(
        "cancel",
        help="Cancel a running job",
    )
    run_cancel_parser.add_argument("run_id", help="Run identifier")
    run_cancel_parser.add_argument("--reason", help="Cancellation reason")
    run_cancel_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    # breakeramp
    amp_parser = subparsers.add_parser(
        "breakeramp",
        help="Infrastructure orchestration and plan management",
    )
    amp_subparsers = amp_parser.add_subparsers(dest="breakeramp_command")
    amp_subparsers.required = True

    # breakeramp plan
    amp_plan_parser = amp_subparsers.add_parser(
        "plan",
        help="Generate an execution plan from a blueprint",
    )
    amp_plan_parser.add_argument(
        "--blueprint-id",
        dest="blueprint_id",
        required=True,
        help="ID of the blueprint to plan",
    )
    amp_plan_parser.add_argument(
        "--environment",
        dest="environment",
        default="development",
        help="Target environment (development, staging, production)",
    )
    amp_plan_parser.add_argument(
        "--lifetime",
        dest="lifetime",
        default="90m",
        help="Lifetime of the environment (ISO8601 duration)",
    )
    amp_plan_parser.add_argument(
        "--compliance-tier",
        dest="compliance_tier",
        default="dev",
        choices=["dev", "prod-sim", "pci-sandbox"],
        help="Compliance tier for the environment",
    )
    amp_plan_parser.add_argument(
        "--checklist-id",
        dest="checklist_id",
        help="Compliance checklist ID to link evidence to",
    )
    amp_plan_parser.add_argument(
        "--behavior",
        dest="behaviors",
        action="append",
        default=[],
        help="Behaviors to include in the plan",
    )
    amp_plan_parser.add_argument(
        "--var",
        dest="variables",
        action="append",
        default=[],
        help="Variables in key=value format",
    )
    amp_plan_parser.add_argument(
        "--module",
        dest="active_modules",
        action="append",
        help="Module to activate (repeatable). If specified, only services in these modules are included.",
    )
    amp_plan_parser.add_argument(
        "--force-podman",
        dest="force_podman",
        action="store_true",
        default=False,
        help="Suppress warnings if a Podman VM is detected",
    )
    amp_plan_parser.add_argument(
        "--env-file",
        dest="env_file",
        help="Path to an BreakerAmp environment manifest (overrides AMPREALIZE_ENV_FILE)",
    )
    amp_plan_parser.add_argument(
        "--output",
        choices=("summary", "json"),
        help="Output format (default: summary when interactive, json when piped)",
    )
    amp_plan_parser.add_argument(
        "--actor-id",
        dest="actor_id",
        default=DEFAULT_ACTOR_ID,
        help="Actor identifier (defaults to local-cli)",
    )
    amp_plan_parser.add_argument(
        "--actor-role",
        dest="actor_role",
        default=DEFAULT_ACTOR_ROLE,
        help="Actor role (defaults to STRATEGIST)",
    )

    # breakeramp apply
    amp_apply_parser = amp_subparsers.add_parser(
        "apply",
        help="Apply a plan or manifest to create resources",
    )
    amp_apply_parser.add_argument(
        "--plan-id",
        dest="plan_id",
        help="ID of the plan to apply",
    )
    amp_apply_parser.add_argument(
        "--manifest",
        dest="manifest_file",
        help="Path to a manifest file to apply",
    )
    amp_apply_parser.add_argument(
        "--watch",
        dest="watch",
        action="store_true",
        default=True,
        help="Watch progress until completion",
    )
    amp_apply_parser.add_argument(
        "--resume",
        dest="resume",
        action="store_true",
        default=False,
        help="Resume a paused or failed apply",
    )
    amp_apply_parser.add_argument(
        "--force-podman",
        dest="force_podman",
        action="store_true",
        default=False,
        help="Suppress warnings if a Podman VM is detected",
    )
    amp_apply_parser.add_argument(
        "--skip-resource-check",
        dest="skip_resource_check",
        action="store_true",
        default=False,
        help="Skip pre-flight resource health check",
    )
    amp_apply_parser.add_argument(
        "--min-disk-gb",
        dest="min_disk_gb",
        type=float,
        default=5.0,
        help="Minimum disk space in GB required for apply (default: 5.0)",
    )
    amp_apply_parser.add_argument(
        "--min-memory-mb",
        dest="min_memory_mb",
        type=float,
        default=1024.0,
        help="Minimum memory in MB required for apply (default: 1024)",
    )
    amp_apply_parser.add_argument(
        "--auto-cleanup",
        dest="auto_cleanup",
        action="store_true",
        default=False,
        help="Automatically clean up unused resources when disk/memory is critical",
    )
    amp_apply_parser.add_argument(
        "--auto-cleanup-aggressive",
        dest="auto_cleanup_aggressive",
        action="store_true",
        default=False,
        help="Start with aggressive cleanup (networks, pods, logs) instead of standard",
    )
    amp_apply_parser.add_argument(
        "--auto-cleanup-volumes",
        dest="auto_cleanup_include_volumes",
        action="store_true",
        default=False,
        help="Include volumes in auto-cleanup (WARNING: may lose data)",
    )
    amp_apply_parser.add_argument(
        "--auto-cleanup-retries",
        dest="auto_cleanup_max_retries",
        type=int,
        default=3,
        help="Max cleanup+recheck cycles per tier before escalating (default: 3)",
    )
    amp_apply_parser.add_argument(
        "--allow-host-resource-warning",
        dest="allow_host_resource_warning",
        action="store_true",
        default=False,
        help="Allow proceeding when host disk is low but VM is healthy (warns but continues)",
    )
    amp_apply_parser.add_argument(
        "--proactive-cleanup",
        dest="proactive_cleanup",
        action="store_true",
        default=False,
        help="Run cleanup BEFORE resource check to maximize available resources (prevents memory exhaustion)",
    )
    amp_apply_parser.add_argument(
        "--blueprint-aware-memory",
        dest="blueprint_aware_memory_check",
        action="store_true",
        default=True,
        help="Use blueprint memory estimates instead of fixed threshold (default: enabled)",
    )
    amp_apply_parser.add_argument(
        "--no-blueprint-aware-memory",
        dest="blueprint_aware_memory_check",
        action="store_false",
        help="Disable blueprint-aware memory checking (use fixed threshold instead)",
    )
    amp_apply_parser.add_argument(
        "--memory-safety-margin-mb",
        dest="memory_safety_margin_mb",
        type=float,
        default=512.0,
        help="Extra memory to require beyond blueprint estimate (default: 512 MB)",
    )
    amp_apply_parser.add_argument(
        "--auto-resolve-stale",
        dest="auto_resolve_stale",
        action="store_true",
        default=True,
        help="Automatically remove stale/exited/dead containers before apply (default: enabled)",
    )
    amp_apply_parser.add_argument(
        "--no-auto-resolve-stale",
        dest="auto_resolve_stale",
        action="store_false",
        help="Disable auto-resolve of stale containers",
    )
    amp_apply_parser.add_argument(
        "--auto-resolve-conflicts",
        dest="auto_resolve_conflicts",
        action="store_true",
        default=True,
        help="Automatically resolve port conflicts (stop conflicting containers/processes) (default: enabled)",
    )
    amp_apply_parser.add_argument(
        "--no-auto-resolve-conflicts",
        dest="auto_resolve_conflicts",
        action="store_false",
        help="Disable auto-resolve of port conflicts",
    )
    amp_apply_parser.add_argument(
        "--stale-max-age-hours",
        dest="stale_max_age_hours",
        type=float,
        default=0.0,
        help="Max age for stale container cleanup in hours (0 = all stale, -1 = skip age check)",
    )
    amp_apply_parser.add_argument(
        "--env-file",
        dest="env_file",
        help="Path to an BreakerAmp environment manifest (overrides AMPREALIZE_ENV_FILE)",
    )
    amp_apply_parser.add_argument(
        "--output",
        choices=("summary", "json"),
        help="Output format (default: summary when interactive, json when piped)",
    )
    amp_apply_parser.add_argument(
        "--actor-id",
        dest="actor_id",
        default=DEFAULT_ACTOR_ID,
        help="Actor identifier (defaults to local-cli)",
    )
    amp_apply_parser.add_argument(
        "--actor-role",
        dest="actor_role",
        default=DEFAULT_ACTOR_ROLE,
        help="Actor role (defaults to STRATEGIST)",
    )

    # breakeramp status
    amp_status_parser = amp_subparsers.add_parser(
        "status",
        help="Check status of an breakeramp run",
    )
    amp_status_parser.add_argument(
        "--run-id",
        dest="amp_run_id",
        required=True,
        help="BreakerAmp run ID",
    )
    amp_status_parser.add_argument(
        "--output",
        choices=("summary", "json"),
        help="Output format (default: summary when interactive, json when piped)",
    )

    # breakeramp destroy
    amp_destroy_parser = amp_subparsers.add_parser(
        "destroy",
        help="Destroy resources from an breakeramp run",
    )
    amp_destroy_parser.add_argument(
        "--run-id",
        dest="amp_run_id",
        required=True,
        help="BreakerAmp run ID",
    )
    amp_destroy_parser.add_argument(
        "--cascade",
        dest="cascade",
        action="store_true",
        default=True,
        help="Cascade destroy dependent resources",
    )
    amp_destroy_parser.add_argument(
        "--reason",
        dest="reason",
        default="MANUAL",
        choices=["POST_TEST", "FAILED", "ABANDONED", "MANUAL"],
        help="Reason for destruction",
    )
    amp_destroy_parser.add_argument(
        "--force-podman",
        dest="force_podman",
        action="store_true",
        default=False,
        help="Suppress warnings if a Podman VM is detected",
    )
    amp_destroy_parser.add_argument(
        "--cleanup-after-destroy",
        dest="cleanup_after_destroy",
        action="store_true",
        default=True,
        help="Run resource cleanup after destroying containers (default: enabled)",
    )
    amp_destroy_parser.add_argument(
        "--no-cleanup-after-destroy",
        dest="cleanup_after_destroy",
        action="store_false",
        help="Skip post-destroy resource cleanup",
    )
    amp_destroy_parser.add_argument(
        "--cleanup-aggressive",
        dest="cleanup_aggressive",
        action="store_true",
        default=True,
        help="Use aggressive cleanup including dangling images/cache (default: enabled)",
    )
    amp_destroy_parser.add_argument(
        "--no-cleanup-aggressive",
        dest="cleanup_aggressive",
        action="store_false",
        help="Use standard cleanup (containers only)",
    )
    amp_destroy_parser.add_argument(
        "--cleanup-volumes",
        dest="cleanup_include_volumes",
        action="store_true",
        default=False,
        help="Include volumes in cleanup (WARNING: may lose data)",
    )
    amp_destroy_parser.add_argument(
        "--env-file",
        dest="env_file",
        help="Path to an BreakerAmp environment manifest (overrides AMPREALIZE_ENV_FILE)",
    )
    amp_destroy_parser.add_argument(
        "--output",
        choices=("summary", "json"),
        help="Output format (default: summary when interactive, json when piped)",
    )
    amp_destroy_parser.add_argument(
        "--actor-id",
        dest="actor_id",
        default=DEFAULT_ACTOR_ID,
        help="Actor identifier (defaults to local-cli)",
    )
    amp_destroy_parser.add_argument(
        "--actor-role",
        dest="actor_role",
        default=DEFAULT_ACTOR_ROLE,
        help="Actor role (defaults to STRATEGIST)",
    )

    # breakeramp bootstrap
    amp_bootstrap_parser = amp_subparsers.add_parser(
        "bootstrap",
        help="Scaffold BreakerAmp config files into the current workspace",
    )
    amp_bootstrap_parser.add_argument(
        "--directory",
        dest="bootstrap_directory",
        default=".",
        help="Directory where config/breakeramp files should be created",
    )
    amp_bootstrap_parser.add_argument(
        "--include-blueprints",
        dest="include_blueprints",
        action="store_true",
        default=False,
        help="Copy packaged blueprint samples into config/breakeramp/blueprints",
    )
    amp_bootstrap_parser.add_argument(
        "--blueprint",
        dest="blueprints",
        action="append",
        default=[],
        help="Specific blueprint IDs to copy (defaults to all when --include-blueprints is set)",
    )
    amp_bootstrap_parser.add_argument(
        "--env-template",
        dest="env_template",
        help="Path to a custom environments.yaml template to copy",
    )
    amp_bootstrap_parser.add_argument(
        "--force",
        dest="force",
        action="store_true",
        default=False,
        help="Overwrite existing files if they already exist",
    )

    # breakeramp machine - Podman machine management
    amp_machine_parser = amp_subparsers.add_parser(
        "machine",
        help="Manage Podman machines (macOS/Windows)",
    )
    amp_machine_subparsers = amp_machine_parser.add_subparsers(dest="machine_command")

    # breakeramp machine list
    amp_machine_list_parser = amp_machine_subparsers.add_parser(
        "list",
        help="List all Podman machines",
    )
    amp_machine_list_parser.add_argument(
        "--output",
        choices=("table", "json"),
        default="table",
        help="Output format (default: table)",
    )

    # breakeramp machine start
    amp_machine_start_parser = amp_machine_subparsers.add_parser(
        "start",
        help="Start a Podman machine",
    )
    amp_machine_start_parser.add_argument(
        "name",
        nargs="?",
        help="Machine name (defaults to amprealize-ci or first available)",
    )

    # breakeramp machine stop
    amp_machine_stop_parser = amp_machine_subparsers.add_parser(
        "stop",
        help="Stop a Podman machine",
    )
    amp_machine_stop_parser.add_argument(
        "name",
        nargs="?",
        help="Machine name (defaults to amprealize-ci or current running machine)",
    )
    amp_machine_stop_parser.add_argument(
        "--all",
        dest="stop_all",
        action="store_true",
        default=False,
        help="Stop all running Podman machines",
    )

    # breakeramp machine ensure
    amp_machine_ensure_parser = amp_machine_subparsers.add_parser(
        "ensure",
        help="Ensure a Podman machine is running (start if needed, create if missing)",
    )
    amp_machine_ensure_parser.add_argument(
        "name",
        nargs="?",
        default="amprealize-ci",
        help="Machine name (default: amprealize-ci)",
    )
    amp_machine_ensure_parser.add_argument(
        "--cpus",
        type=int,
        default=2,
        help="Number of CPUs for new machine (default: 2)",
    )
    amp_machine_ensure_parser.add_argument(
        "--memory",
        type=int,
        default=4096,
        help="Memory in MB for new machine (default: 4096)",
    )
    amp_machine_ensure_parser.add_argument(
        "--disk",
        type=int,
        default=100,
        help="Disk size in GB for new machine (default: 100)",
    )

    # breakeramp machine status
    amp_machine_status_parser = amp_machine_subparsers.add_parser(
        "status",
        help="Show status of a Podman machine",
    )
    amp_machine_status_parser.add_argument(
        "name",
        nargs="?",
        help="Machine name (defaults to amprealize-ci or first available)",
    )
    amp_machine_status_parser.add_argument(
        "--output",
        choices=("table", "json"),
        default="table",
        help="Output format (default: table)",
    )

    # breakeramp machine resources
    amp_machine_resources_parser = amp_machine_subparsers.add_parser(
        "resources",
        help="Show resource usage for host and Podman machines",
    )
    amp_machine_resources_parser.add_argument(
        "--output",
        choices=("table", "json"),
        default="table",
        help="Output format (default: table)",
    )
    amp_machine_resources_parser.add_argument(
        "--check",
        action="store_true",
        help="Check resource health against minimum requirements",
    )
    amp_machine_resources_parser.add_argument(
        "--min-disk-gb",
        type=float,
        default=5.0,
        help="Minimum free disk space in GB (default: 5.0)",
    )
    amp_machine_resources_parser.add_argument(
        "--min-memory-mb",
        type=float,
        default=1024.0,
        help="Minimum free memory in MB (default: 1024)",
    )

    # breakeramp machine cleanup
    amp_machine_cleanup_parser = amp_machine_subparsers.add_parser(
        "cleanup",
        help="Clean up unused resources (containers, images, cache) to free disk space",
    )
    amp_machine_cleanup_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be cleaned without actually removing anything",
    )
    amp_machine_cleanup_parser.add_argument(
        "--include-volumes",
        action="store_true",
        help="Also remove unused volumes (CAUTION: may delete data)",
    )
    amp_machine_cleanup_parser.add_argument(
        "--include-networks",
        action="store_true",
        help="Also remove unused networks",
    )
    amp_machine_cleanup_parser.add_argument(
        "--include-pods",
        action="store_true",
        help="Also remove stopped pods",
    )
    amp_machine_cleanup_parser.add_argument(
        "--include-logs",
        action="store_true",
        help="Also clear container logs",
    )
    amp_machine_cleanup_parser.add_argument(
        "--aggressive",
        action="store_true",
        help="Enable ALL cleanup options (includes volumes - use with caution)",
    )
    amp_machine_cleanup_parser.add_argument(
        "--skip-containers",
        action="store_true",
        help="Skip removing stopped containers",
    )
    amp_machine_cleanup_parser.add_argument(
        "--skip-images",
        action="store_true",
        help="Skip removing unused images",
    )
    amp_machine_cleanup_parser.add_argument(
        "--skip-cache",
        action="store_true",
        help="Skip clearing build cache",
    )
    amp_machine_cleanup_parser.add_argument(
        "--output",
        choices=("table", "json"),
        default="table",
        help="Output format (default: table)",
    )

    # breakeramp cleanup - Direct container cleanup without machine management
    amp_cleanup_parser = amp_subparsers.add_parser(
        "cleanup",
        help="Clean up stale/orphaned containers and free resources",
    )
    amp_cleanup_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be cleaned without actually removing anything",
    )
    amp_cleanup_parser.add_argument(
        "--stale",
        action="store_true",
        default=True,
        help="Remove stale containers (exited, dead, created) [default: True]",
    )
    amp_cleanup_parser.add_argument(
        "--no-stale",
        dest="stale",
        action="store_false",
        help="Skip stale container cleanup",
    )
    amp_cleanup_parser.add_argument(
        "--orphans",
        action="store_true",
        default=True,
        help="Remove orphaned BreakerAmp containers [default: True]",
    )
    amp_cleanup_parser.add_argument(
        "--no-orphans",
        dest="orphans",
        action="store_false",
        help="Skip orphaned container cleanup",
    )
    amp_cleanup_parser.add_argument(
        "--max-age-hours",
        type=float,
        default=None,
        help="Only remove stale containers older than N hours (default: any age)",
    )
    amp_cleanup_parser.add_argument(
        "--all-non-running",
        action="store_true",
        default=False,
        help="Remove ALL non-running containers (not just stale statuses)",
    )
    amp_cleanup_parser.add_argument(
        "--force-podman",
        action="store_true",
        default=False,
        help="Suppress warnings if a Podman VM is detected",
    )
    amp_cleanup_parser.add_argument(
        "--output",
        choices=("table", "json"),
        default="table",
        help="Output format (default: table)",
    )

    # ── Auth commands ───────────────────────────────────────────────────────────
    auth_parser = subparsers.add_parser(
        "auth",
        help="Authentication and consent management commands",
    )
    auth_subparsers = auth_parser.add_subparsers(dest="auth_command")

    # auth login (device flow)
    auth_login_parser = auth_subparsers.add_parser(
        "login",
        help="Authenticate via device flow",
    )
    auth_login_parser.add_argument(
        "--provider",
        choices=("github", "google", "internal"),
        default="internal",
        help="OAuth provider to use (default: internal)",
    )
    auth_login_parser.add_argument(
        "--scopes",
        nargs="+",
        default=["behaviors.read", "behaviors.write"],
        help="Scopes to request (default: behaviors.read behaviors.write)",
    )
    auth_login_parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Timeout in seconds for device flow (default: 300)",
    )
    auth_login_parser.add_argument(
        "--client-id",
        dest="client_id",
        default="amprealize-cli",
        help="Client ID for the device flow (default: amprealize-cli)",
    )
    auth_login_parser.add_argument(
        "--open-browser",
        dest="open_browser",
        action="store_true",
        default=True,
        help="Automatically open browser for verification (default: true)",
    )
    auth_login_parser.add_argument(
        "--no-browser",
        dest="open_browser",
        action="store_false",
        help="Do not automatically open browser",
    )
    auth_login_parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        default=False,
        help="Suppress progress output",
    )
    auth_login_parser.add_argument(
        "--allow-plaintext",
        dest="allow_plaintext",
        action="store_true",
        default=False,
        help="Allow storing tokens in plaintext (insecure)",
    )

    # auth register (internal auth only)
    auth_register_parser = auth_subparsers.add_parser(
        "register",
        help="Register a new user account (internal auth only)",
    )
    auth_register_parser.add_argument(
        "--username",
        help="Username for registration (prompts if not provided)",
    )
    auth_register_parser.add_argument(
        "--password",
        help="Password for registration (prompts if not provided)",
    )
    auth_register_parser.add_argument(
        "--email",
        help="Email for registration (optional)",
    )
    auth_register_parser.add_argument(
        "--allow-plaintext",
        dest="allow_plaintext",
        action="store_true",
        default=False,
        help="Allow storing tokens in plaintext (insecure)",
    )
    auth_register_parser.add_argument(
        "--api-url",
        dest="api_url",
        default=None,
        help="Gateway URL (default: $AMPREALIZE_GATEWAY_URL or http://localhost:8080)",
    )

    # auth status
    auth_status_parser = auth_subparsers.add_parser(
        "status",
        help="Show current authentication status",
    )
    auth_status_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format",
    )
    auth_status_parser.add_argument(
        "--allow-plaintext",
        dest="allow_plaintext",
        action="store_true",
        default=False,
        help="Allow storing tokens in plaintext (insecure)",
    )

    # auth logout
    auth_logout_parser = auth_subparsers.add_parser(
        "logout",
        help="Clear stored authentication tokens",
    )
    auth_logout_parser.add_argument(
        "--allow-plaintext",
        dest="allow_plaintext",
        action="store_true",
        default=False,
        help="Allow storing tokens in plaintext (insecure)",
    )

    # auth refresh
    auth_refresh_parser = auth_subparsers.add_parser(
        "refresh",
        help="Refresh the access token using stored refresh token",
    )
    auth_refresh_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format",
    )
    auth_refresh_parser.add_argument(
        "--allow-plaintext",
        dest="allow_plaintext",
        action="store_true",
        default=False,
        help="Allow storing tokens in plaintext (insecure)",
    )

    # auth ensure-grant
    auth_ensure_grant_parser = auth_subparsers.add_parser(
        "ensure-grant",
        help="Ensure a valid grant exists for the specified scopes",
    )
    auth_ensure_grant_parser.add_argument(
        "--scopes",
        nargs="+",
        required=True,
        help="Scopes to request grant for",
    )
    auth_ensure_grant_parser.add_argument(
        "--actor-id",
        default=DEFAULT_ACTOR_ID,
        help="Actor ID for the grant",
    )
    auth_ensure_grant_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format",
    )

    # auth list-grants
    auth_list_grants_parser = auth_subparsers.add_parser(
        "list-grants",
        help="List all active grants for the current user",
    )
    auth_list_grants_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format",
    )

    # auth policy-preview
    auth_policy_preview_parser = auth_subparsers.add_parser(
        "policy-preview",
        help="Preview policy decision for a scope without granting",
    )
    auth_policy_preview_parser.add_argument(
        "--scopes",
        nargs="+",
        required=True,
        help="Scopes to preview",
    )
    auth_policy_preview_parser.add_argument(
        "--actor-id",
        default=DEFAULT_ACTOR_ID,
        help="Actor ID for the preview",
    )
    auth_policy_preview_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format",
    )

    # auth revoke
    auth_revoke_parser = auth_subparsers.add_parser(
        "revoke",
        help="Revoke an active grant",
    )
    auth_revoke_parser.add_argument(
        "grant_id",
        help="Grant ID to revoke",
    )
    auth_revoke_parser.add_argument(
        "--reason",
        default="user_request",
        help="Reason for revocation",
    )

    # auth consent-lookup
    auth_consent_lookup_parser = auth_subparsers.add_parser(
        "consent-lookup",
        help="Look up consent request details by user code",
    )
    auth_consent_lookup_parser.add_argument(
        "user_code",
        help="User code from the consent prompt (e.g., ABCD-1234)",
    )
    auth_consent_lookup_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format",
    )

    # auth consent-approve
    auth_consent_approve_parser = auth_subparsers.add_parser(
        "consent-approve",
        help="Approve a consent request",
    )
    auth_consent_approve_parser.add_argument(
        "user_code",
        help="User code from the consent prompt (e.g., ABCD-1234)",
    )
    auth_consent_approve_parser.add_argument(
        "--actor-id",
        default=DEFAULT_ACTOR_ID,
        help="Actor ID approving the consent",
    )
    auth_consent_approve_parser.add_argument(
        "--roles",
        nargs="+",
        help="Roles to grant with consent (optional)",
    )
    auth_consent_approve_parser.add_argument(
        "--mfa-verified",
        action="store_true",
        default=False,
        help="Indicate MFA was verified for this approval",
    )

    # auth consent-deny
    auth_consent_deny_parser = auth_subparsers.add_parser(
        "consent-deny",
        help="Deny a consent request",
    )
    auth_consent_deny_parser.add_argument(
        "user_code",
        help="User code from the consent prompt (e.g., ABCD-1234)",
    )
    auth_consent_deny_parser.add_argument(
        "--actor-id",
        default=DEFAULT_ACTOR_ID,
        help="Actor ID denying the consent",
    )
    auth_consent_deny_parser.add_argument(
        "--reason",
        default="user_denied",
        help="Reason for denial",
    )

    # ── BCI commands ────────────────────────────────────────────────────────────
    bci_parser = subparsers.add_parser(
        "bci",
        help="Behavior-Conditioned Inference commands",
    )
    bci_subparsers = bci_parser.add_subparsers(dest="bci_command")

    # bci rebuild-index
    bci_rebuild_parser = bci_subparsers.add_parser(
        "rebuild-index",
        help="Rebuild the behavior retrieval index",
    )

    # bci retrieve
    bci_retrieve_parser = bci_subparsers.add_parser(
        "retrieve",
        help="Retrieve relevant behaviors for a query",
    )
    bci_retrieve_parser.add_argument("query", help="The query to retrieve behaviors for")
    bci_retrieve_parser.add_argument("--top-k", type=int, default=5, help="Number of behaviors to retrieve")
    bci_retrieve_parser.add_argument(
        "--strategy",
        choices=["semantic", "keyword", "hybrid"],
        default="hybrid",
        help="Retrieval strategy",
    )
    bci_retrieve_parser.add_argument(
        "--role",
        choices=["student", "teacher", "strategist"],
        help="Filter by role focus",
    )

    # bci compose-prompt
    bci_compose_parser = bci_subparsers.add_parser(
        "compose-prompt",
        help="Compose a BCI prompt with retrieved behaviors",
    )
    bci_compose_parser.add_argument("query", help="The user query")
    bci_compose_parser.add_argument(
        "--behaviors",
        nargs="+",
        help="Explicit behavior names to include",
    )
    bci_compose_parser.add_argument("--top-k", type=int, default=5, help="Number of behaviors to retrieve")
    bci_compose_parser.add_argument(
        "--format",
        choices=["simple", "detailed", "json"],
        default="simple",
        help="Prompt format",
    )

    # bci validate-citations
    bci_validate_parser = bci_subparsers.add_parser(
        "validate-citations",
        help="Validate behavior citations in a response",
    )
    bci_validate_parser.add_argument("response", help="The response text to validate")
    bci_validate_parser.add_argument(
        "--mode",
        choices=["strict", "lenient", "fuzzy"],
        default="strict",
        help="Citation validation mode",
    )

    # bci generate
    bci_generate_parser = bci_subparsers.add_parser(
        "generate",
        help="Generate a behavior-conditioned LLM response",
    )
    bci_generate_parser.add_argument("query", help="The query to generate a response for")
    bci_generate_parser.add_argument(
        "--behaviors",
        nargs="+",
        help="Explicit behavior names to use (default: auto-retrieve)",
    )
    bci_generate_parser.add_argument("--top-k", type=int, default=5, help="Number of behaviors to retrieve")
    bci_generate_parser.add_argument(
        "--provider",
        choices=["openai", "anthropic", "openrouter", "ollama", "together", "groq", "fireworks", "test"],
        help="LLM provider (default: from environment)",
    )
    bci_generate_parser.add_argument("--model", help="Model name (default: provider default)")
    bci_generate_parser.add_argument("--temperature", type=float, help="Sampling temperature")
    bci_generate_parser.add_argument(
        "--role",
        choices=["student", "teacher", "strategist"],
        help="Role focus for behavior retrieval",
    )
    bci_generate_parser.add_argument("--output", "-o", help="Output file path (default: stdout)")

    # bci improve
    bci_improve_parser = bci_subparsers.add_parser(
        "improve",
        help="Analyze a failed run and generate improvement suggestions",
    )
    bci_improve_parser.add_argument("run_id", help="The run ID to analyze")
    bci_improve_parser.add_argument(
        "--provider",
        choices=["openai", "anthropic", "openrouter", "ollama", "together", "groq", "fireworks", "test"],
        help="LLM provider (default: from environment)",
    )
    bci_improve_parser.add_argument("--model", help="Model name (default: provider default)")
    bci_improve_parser.add_argument("--max-behaviors", type=int, default=10, help="Max behaviors to extract")
    bci_improve_parser.add_argument("--output", "-o", help="Output file path (default: stdout)")

    # bci inject — E3 Runtime Injection command
    bci_inject_parser = bci_subparsers.add_parser(
        "inject",
        help="Full runtime injection: resolve context, retrieve behaviors, compose enriched prompt",
    )
    bci_inject_parser.add_argument("task", help="Task or prompt description")
    bci_inject_parser.add_argument("--surface", default="cli", help="Invoking surface (cli, mcp, vscode, web, api)")
    bci_inject_parser.add_argument("--role", choices=["Student", "Teacher", "Strategist"], help="Agent role")
    bci_inject_parser.add_argument("--workspace-path", help="Workspace path for profile detection")
    bci_inject_parser.add_argument("--pack-id", help="Active pack ID override")
    bci_inject_parser.add_argument("--pack-version", help="Active pack version override")
    bci_inject_parser.add_argument("--top-k", type=int, default=5, help="Number of behaviors to retrieve")
    bci_inject_parser.add_argument(
        "--strategy", choices=["hybrid", "embedding", "keyword"], default="hybrid", help="Retrieval strategy"
    )
    bci_inject_parser.add_argument(
        "--format", choices=["list", "prose", "structured"], default="list", help="Prompt format"
    )
    bci_inject_parser.add_argument(
        "--citation-mode", choices=["explicit", "implicit", "inline"], default="explicit", help="Citation mode"
    )
    bci_inject_parser.add_argument("--tags", nargs="*", help="Filter behaviors by tags")
    bci_inject_parser.add_argument("--json", action="store_true", help="Output as JSON")
    bci_inject_parser.add_argument("--output", "-o", help="Output file path (default: stdout)")

    # ── Audit log commands ──────────────────────────────────────────────────────
    audit_parser = subparsers.add_parser(
        "audit",
        help="Audit log WORM storage commands",
    )
    audit_subparsers = audit_parser.add_subparsers(dest="audit_command")

    # audit verify
    audit_verify_parser = audit_subparsers.add_parser(
        "verify",
        help="Verify integrity of an archived audit batch",
    )
    audit_verify_parser.add_argument(
        "--batch-id",
        required=True,
        help="Batch ID to verify",
    )
    audit_verify_parser.add_argument(
        "--public-key",
        help="Path to public key file for signature verification (optional)",
    )
    audit_verify_parser.add_argument(
        "--output",
        choices=("summary", "json"),
        help="Output format (default: summary when interactive, json when piped)",
    )

    # audit list
    audit_list_parser = audit_subparsers.add_parser(
        "list",
        help="List archived audit batches",
    )
    audit_list_parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of batches to list (default: 100)",
    )
    audit_list_parser.add_argument(
        "--prefix",
        help="S3 key prefix to filter batches",
    )
    audit_list_parser.add_argument(
        "--output",
        choices=("summary", "json"),
        help="Output format (default: summary when interactive, json when piped)",
    )

    # audit retention
    audit_retention_parser = audit_subparsers.add_parser(
        "retention",
        help="Check retention info for an archived batch",
    )
    audit_retention_parser.add_argument(
        "--batch-id",
        required=True,
        help="Batch ID to check retention for",
    )
    audit_retention_parser.add_argument(
        "--output",
        choices=("summary", "json"),
        help="Output format (default: summary when interactive, json when piped)",
    )

    # ── Analytics commands ──────────────────────────────────────────────────────
    analytics_parser = subparsers.add_parser(
        "analytics",
        help="Analytics warehouse queries and cost optimization",
    )
    analytics_subparsers = analytics_parser.add_subparsers(dest="analytics_command")

    # analytics project
    analytics_project_parser = analytics_subparsers.add_parser(
        "project",
        help="Project raw telemetry data to analytics warehouse",
    )
    analytics_project_parser.add_argument(
        "--start-date",
        dest="start_date",
        help="Start date for projection (YYYY-MM-DD)",
    )
    analytics_project_parser.add_argument(
        "--end-date",
        dest="end_date",
        help="End date for projection (YYYY-MM-DD)",
    )
    analytics_project_parser.add_argument(
        "--output",
        choices=("summary", "json"),
        default="summary",
        help="Output format",
    )

    # analytics kpi-summary
    analytics_kpi_parser = analytics_subparsers.add_parser(
        "kpi-summary",
        help="Query KPI summary from DuckDB analytics warehouse",
    )
    analytics_kpi_parser.add_argument("--start-date", dest="start_date", help="Start date (YYYY-MM-DD)")
    analytics_kpi_parser.add_argument("--end-date", dest="end_date", help="End date (YYYY-MM-DD)")
    analytics_kpi_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")

    # analytics project-kpi
    analytics_project_kpi_parser = analytics_subparsers.add_parser(
        "project-kpi",
        help="Project telemetry events from JSONL file into KPI facts and summary",
    )
    analytics_project_kpi_parser.add_argument(
        "--input",
        dest="input_file",
        required=True,
        help="Path to JSONL file containing telemetry events",
    )
    analytics_project_kpi_parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format (default: table)",
    )
    analytics_project_kpi_parser.add_argument(
        "--facts-output",
        dest="facts_output",
        help="Optional path to write full projection JSON",
    )

    # analytics behavior-usage
    analytics_behavior_parser = analytics_subparsers.add_parser(
        "behavior-usage",
        help="Query behavior usage facts from analytics warehouse",
    )
    analytics_behavior_parser.add_argument("--start-date", dest="start_date", help="Start date (YYYY-MM-DD)")
    analytics_behavior_parser.add_argument("--end-date", dest="end_date", help="End date (YYYY-MM-DD)")
    analytics_behavior_parser.add_argument("--limit", type=int, default=50, help="Max records to return")
    analytics_behavior_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")

    # analytics token-savings
    analytics_tokens_parser = analytics_subparsers.add_parser(
        "token-savings",
        help="Query token savings facts from analytics warehouse",
    )
    analytics_tokens_parser.add_argument("--start-date", dest="start_date", help="Start date (YYYY-MM-DD)")
    analytics_tokens_parser.add_argument("--end-date", dest="end_date", help="End date (YYYY-MM-DD)")
    analytics_tokens_parser.add_argument("--limit", type=int, default=50, help="Max records to return")
    analytics_tokens_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")

    # analytics compliance-coverage
    analytics_compliance_parser = analytics_subparsers.add_parser(
        "compliance-coverage",
        help="Query compliance coverage facts from analytics warehouse",
    )
    analytics_compliance_parser.add_argument("--start-date", dest="start_date", help="Start date (YYYY-MM-DD)")
    analytics_compliance_parser.add_argument("--end-date", dest="end_date", help="End date (YYYY-MM-DD)")
    analytics_compliance_parser.add_argument("--limit", type=int, default=50, help="Max records to return")
    analytics_compliance_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")

    # analytics cost-by-service
    analytics_cost_service_parser = analytics_subparsers.add_parser(
        "cost-by-service",
        help="Query cost breakdown by service from analytics warehouse",
    )
    analytics_cost_service_parser.add_argument("--start-date", dest="start_date", help="Start date (YYYY-MM-DD)")
    analytics_cost_service_parser.add_argument("--end-date", dest="end_date", help="End date (YYYY-MM-DD)")
    analytics_cost_service_parser.add_argument("--service", dest="service_name", help="Filter by service name")
    analytics_cost_service_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")

    # analytics cost-per-run
    analytics_cost_run_parser = analytics_subparsers.add_parser(
        "cost-per-run",
        help="Query cost breakdown by run from analytics warehouse",
    )
    analytics_cost_run_parser.add_argument("--start-date", dest="start_date", help="Start date (YYYY-MM-DD)")
    analytics_cost_run_parser.add_argument("--end-date", dest="end_date", help="End date (YYYY-MM-DD)")
    analytics_cost_run_parser.add_argument("--template", dest="template_id", help="Filter by template ID")
    analytics_cost_run_parser.add_argument("--limit", type=int, default=50, help="Max records to return")
    analytics_cost_run_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")

    # analytics roi-summary
    analytics_roi_parser = analytics_subparsers.add_parser(
        "roi-summary",
        help="Query ROI analysis summary from analytics warehouse",
    )
    analytics_roi_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")

    # analytics daily-costs
    analytics_daily_parser = analytics_subparsers.add_parser(
        "daily-costs",
        help="Query daily cost summary for budget tracking",
    )
    analytics_daily_parser.add_argument("--start-date", dest="start_date", help="Start date (YYYY-MM-DD)")
    analytics_daily_parser.add_argument("--end-date", dest="end_date", help="End date (YYYY-MM-DD)")
    analytics_daily_parser.add_argument("--limit", type=int, default=30, help="Max records to return")
    analytics_daily_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")

    # analytics top-expensive
    analytics_expensive_parser = analytics_subparsers.add_parser(
        "top-expensive",
        help="Query top expensive workflows from analytics warehouse",
    )
    analytics_expensive_parser.add_argument("--limit", type=int, default=10, help="Number of workflows to return")
    analytics_expensive_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")

    # ── Telemetry commands ──────────────────────────────────────────────────────
    telemetry_parser = subparsers.add_parser(
        "telemetry",
        help="Emit telemetry events",
    )
    telemetry_subparsers = telemetry_parser.add_subparsers(dest="telemetry_command")

    telemetry_emit_parser = telemetry_subparsers.add_parser(
        "emit",
        help="Emit a telemetry event",
    )
    telemetry_emit_parser.add_argument("--event-type", dest="event_type", required=True, help="Event type")
    telemetry_emit_parser.add_argument("--payload", default="{}", help="JSON event payload")
    telemetry_emit_parser.add_argument("--actor-id", dest="actor_id", default=DEFAULT_ACTOR_ID, help="Actor identifier")
    telemetry_emit_parser.add_argument("--actor-role", dest="actor_role", default=DEFAULT_ACTOR_ROLE, help="Actor role")
    telemetry_emit_parser.add_argument("--actor-surface", dest="actor_surface", default="cli", help="Actor surface")
    telemetry_emit_parser.add_argument("--run-id", dest="run_id", help="Run ID")
    telemetry_emit_parser.add_argument("--action-id", dest="action_id", help="Action ID")
    telemetry_emit_parser.add_argument("--session-id", dest="session_id", help="Session ID")
    telemetry_emit_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")
    telemetry_emit_parser.add_argument("--sink", choices=("file", "kafka"), default="file", help="Telemetry sink type")
    telemetry_emit_parser.add_argument("--telemetry-path", dest="telemetry_path", help="Output file path for file sink")
    telemetry_emit_parser.add_argument("--kafka-servers", dest="kafka_servers", help="Kafka bootstrap servers (or use KAFKA_BOOTSTRAP_SERVERS env)")

    # telemetry query
    telemetry_query_parser = telemetry_subparsers.add_parser(
        "query",
        help="Query telemetry events with filters",
    )
    telemetry_query_parser.add_argument("--event-type", dest="event_type", help="Filter by event type")
    telemetry_query_parser.add_argument("--from", dest="start_date", help="Start date (ISO format or relative e.g. '7d')")
    telemetry_query_parser.add_argument("--to", dest="end_date", help="End date (ISO format)")
    telemetry_query_parser.add_argument("--run-id", dest="run_id", help="Filter by run ID")
    telemetry_query_parser.add_argument("--action-id", dest="action_id", help="Filter by action ID")
    telemetry_query_parser.add_argument("--session-id", dest="session_id", help="Filter by session ID")
    telemetry_query_parser.add_argument("--actor-surface", dest="actor_surface", help="Filter by actor surface")
    telemetry_query_parser.add_argument("--level", choices=("TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"), help="Minimum log level")
    telemetry_query_parser.add_argument("--search", help="Full-text search in message")
    telemetry_query_parser.add_argument("--limit", type=int, default=100, help="Maximum events to return")
    telemetry_query_parser.add_argument("--offset", type=int, default=0, help="Pagination offset")
    telemetry_query_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")

    # telemetry dashboard
    telemetry_dashboard_parser = telemetry_subparsers.add_parser(
        "dashboard",
        help="Display telemetry dashboard with KPIs and token accounting",
    )
    telemetry_dashboard_parser.add_argument("--run-id", dest="run_id", help="Drill down to specific run ID for token details")
    telemetry_dashboard_parser.add_argument("--from", dest="start_date", help="Start date for daily summary")
    telemetry_dashboard_parser.add_argument("--to", dest="end_date", help="End date for daily summary")
    telemetry_dashboard_parser.add_argument("--watch", action="store_true", help="Enable live refresh (5s interval)")
    telemetry_dashboard_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")

    # ── Agents commands ─────────────────────────────────────────────────────────
    agents_parser = subparsers.add_parser(
        "agents",
        help="Agent management commands",
    )
    agents_subparsers = agents_parser.add_subparsers(dest="agents_command")

    # agents assign
    agents_assign_parser = agents_subparsers.add_parser(
        "assign",
        help="Assign an agent to a run",
    )
    agents_assign_parser.add_argument("--run-id", dest="run_id", help="Run ID to assign agent to")
    agents_assign_parser.add_argument("--agent-id", dest="agent_id", help="Explicit agent ID to assign")
    agents_assign_parser.add_argument("--stage", default="PLANNING", help="Assignment stage (default: PLANNING)")
    agents_assign_parser.add_argument("--context", help="JSON context for heuristic selection")
    agents_assign_parser.add_argument("--context-file", dest="context_file", help="Path to JSON file with context")
    agents_assign_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")

    # agents status
    agents_status_parser = agents_subparsers.add_parser(
        "status",
        help="Get status of an agent assignment",
    )
    agents_status_parser.add_argument("--run-id", dest="run_id", help="Run ID to check status")
    agents_status_parser.add_argument("--assignment-id", dest="assignment_id", help="Assignment ID to check status")
    agents_status_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")

    # agents switch
    agents_switch_parser = agents_subparsers.add_parser(
        "switch",
        help="Switch to a different agent",
    )
    agents_switch_parser.add_argument("assignment_id", help="Assignment ID to modify")
    agents_switch_parser.add_argument("--target-agent-id", dest="target_agent_id", required=True, help="Target agent ID")
    agents_switch_parser.add_argument("--reason", help="Reason for switch")
    agents_switch_parser.add_argument("--stage", help="New stage after switch")
    agents_switch_parser.add_argument("--allow-downgrade", dest="allow_downgrade", action="store_true", help="Allow switching to lower tier agent")
    agents_switch_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")

    # ── Metrics commands ────────────────────────────────────────────────────────
    metrics_parser = subparsers.add_parser(
        "metrics",
        help="Query and export metrics",
    )
    metrics_subparsers = metrics_parser.add_subparsers(dest="metrics_command")

    metrics_summary_parser = metrics_subparsers.add_parser(
        "summary",
        help="Get metrics summary",
    )
    metrics_summary_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")

    metrics_export_parser = metrics_subparsers.add_parser(
        "export",
        help="Export metrics to file",
    )
    metrics_export_parser.add_argument("--output", "-o", required=True, help="Output file path")
    metrics_export_parser.add_argument("--format", choices=("json", "csv"), default="json", help="Export format")

    bandwidth_check_parser = subparsers.add_parser(
        "bandwidth-check",
        help="Check current bandwidth usage against environment limits",
    )
    bandwidth_check_parser.add_argument(
        "--environment",
        default="dev",
        help="Environment to check against (default: dev)",
    )

    # ── Reflection command ──────────────────────────────────────────────────────
    reflection_parser = subparsers.add_parser(
        "reflection",
        help="Analyze traces, manage behavior candidates, and review queue",
    )
    reflection_subparsers = reflection_parser.add_subparsers(dest="reflection_command")

    # reflection extract
    reflection_extract_parser = reflection_subparsers.add_parser(
        "extract",
        help="Analyze traces and propose reusable behavior candidates",
    )
    trace_input_group = reflection_extract_parser.add_mutually_exclusive_group()
    trace_input_group.add_argument(
        "--trace",
        dest="trace_text",
        help="Trace text to analyze (chain-of-thought steps)",
    )
    trace_input_group.add_argument(
        "--trace-file",
        dest="trace_file",
        help="Path to file containing trace text",
    )
    reflection_extract_parser.add_argument(
        "--trace-format",
        dest="trace_format",
        choices=["chain_of_thought", "structured", "free_form"],
        default="chain_of_thought",
        help="Format of the trace text (default: chain_of_thought)",
    )
    reflection_extract_parser.add_argument(
        "--run-id",
        dest="run_id",
        help="Run ID to associate with reflection results",
    )
    reflection_extract_parser.add_argument(
        "--min-score",
        dest="min_score",
        type=float,
        default=0.6,
        help="Minimum quality score for candidate behaviors (0.0-1.0, default: 0.6)",
    )
    reflection_extract_parser.add_argument(
        "--max-candidates",
        dest="max_candidates",
        type=int,
        default=5,
        help="Maximum number of behavior candidates to return (default: 5)",
    )
    reflection_extract_parser.add_argument(
        "--no-examples",
        dest="no_examples",
        action="store_true",
        help="Exclude examples from candidate output",
    )
    reflection_extract_parser.add_argument(
        "--tags",
        nargs="+",
        help="Preferred tags to assign to candidates",
    )
    reflection_extract_parser.add_argument(
        "--output",
        choices=["json", "table"],
        default="json",
        help="Output format (default: json)",
    )

    # reflection list - list behavior candidates for review
    reflection_list_parser = reflection_subparsers.add_parser(
        "list",
        help="List behavior candidates for review",
    )
    reflection_list_parser.add_argument(
        "--status",
        choices=["proposed", "approved", "rejected", "merged"],
        help="Filter by candidate status",
    )
    reflection_list_parser.add_argument(
        "--role",
        choices=["Student", "Teacher", "Metacognitive Strategist"],
        help="Filter by role",
    )
    reflection_list_parser.add_argument(
        "--min-confidence",
        dest="min_confidence",
        type=float,
        help="Filter by minimum confidence score (0.0-1.0)",
    )
    reflection_list_parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of results (default: 50)",
    )
    reflection_list_parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Pagination offset (default: 0)",
    )
    reflection_list_parser.add_argument(
        "--output",
        choices=["json", "table"],
        default="table",
        help="Output format (default: table)",
    )

    # reflection approve - approve a behavior candidate
    reflection_approve_parser = reflection_subparsers.add_parser(
        "approve",
        help="Approve a behavior candidate",
    )
    reflection_approve_parser.add_argument(
        "candidate_id",
        help="ID of the candidate to approve",
    )
    reflection_approve_parser.add_argument(
        "--reviewer",
        dest="reviewed_by",
        default=DEFAULT_ACTOR_ID,
        help=f"Reviewer identifier (default: {DEFAULT_ACTOR_ID})",
    )
    reflection_approve_parser.add_argument(
        "--merge",
        dest="merge_to_handbook",
        action="store_true",
        help="Immediately merge to behavior handbook",
    )
    reflection_approve_parser.add_argument(
        "--behavior-name",
        dest="behavior_name",
        help="Override behavior name when merging",
    )
    reflection_approve_parser.add_argument(
        "--output",
        choices=["json", "table"],
        default="json",
        help="Output format (default: json)",
    )

    # reflection reject - reject a behavior candidate
    reflection_reject_parser = reflection_subparsers.add_parser(
        "reject",
        help="Reject a behavior candidate",
    )
    reflection_reject_parser.add_argument(
        "candidate_id",
        help="ID of the candidate to reject",
    )
    reflection_reject_parser.add_argument(
        "--reviewer",
        dest="reviewed_by",
        default=DEFAULT_ACTOR_ID,
        help=f"Reviewer identifier (default: {DEFAULT_ACTOR_ID})",
    )
    reflection_reject_parser.add_argument(
        "--reason",
        help="Reason for rejection",
    )
    reflection_reject_parser.add_argument(
        "--output",
        choices=["json", "table"],
        default="json",
        help="Output format (default: json)",
    )

    # ── Database migration commands ─────────────────────────────────────────────
    migrate_parser = subparsers.add_parser(
        "migrate",
        help="Apply PostgreSQL schema migrations",
    )
    migrate_subparsers = migrate_parser.add_subparsers(dest="migrate_command")

    migrate_apply_parser = migrate_subparsers.add_parser(
        "apply",
        help="Apply pending schema migrations",
    )
    migrate_apply_parser.add_argument(
        "--service",
        choices=["all", "reflection", "collaboration", "behavior", "workflow", "action", "run", "metrics", "compliance"],
        default="all",
        help="Service to migrate (default: all)",
    )
    migrate_apply_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show which migrations would be applied without executing",
    )

    migrate_status_parser = migrate_subparsers.add_parser(
        "status",
        help="Check migration status for all services",
    )
    migrate_status_parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format",
    )

    # ── Research evaluation commands ────────────────────────────────────────────
    research_parser = subparsers.add_parser(
        "research",
        help="AI research evaluation pipeline - evaluate papers/articles for Amprealize integration",
    )
    research_subparsers = research_parser.add_subparsers(dest="research_command")

    research_evaluate_parser = research_subparsers.add_parser(
        "evaluate",
        help="Evaluate a research paper or article for Amprealize integration",
    )
    research_evaluate_parser.add_argument(
        "source",
        help="Source to evaluate: URL, file path (.md/.pdf/.doc), or arXiv ID",
    )
    research_evaluate_parser.add_argument(
        "--title",
        help="Override paper title (auto-extracted if not specified)",
    )
    research_evaluate_parser.add_argument(
        "--model",
        default=None,
        help="LLM model to use (default: ANTHROPIC_MODEL env var or claude-opus-4-20250514)",
    )
    research_evaluate_parser.add_argument(
        "--output",
        help="Path to save markdown report (defaults to stdout)",
    )
    research_evaluate_parser.add_argument(
        "--phase",
        choices=["comprehend", "evaluate", "recommend", "full"],
        default="full",
        help="Run specific phase only or full pipeline (default: full)",
    )
    research_evaluate_parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    research_evaluate_parser.add_argument(
        "--no-save",
        action="store_true",
        help="Skip saving evaluation to database",
    )

    research_list_parser = research_subparsers.add_parser(
        "list",
        help="List previously evaluated papers",
    )
    research_list_parser.add_argument(
        "--verdict",
        choices=["ADOPT", "ADAPT", "DEFER", "REJECT"],
        help="Filter by verdict",
    )
    research_list_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of results (default: 20)",
    )
    research_list_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format (default: table)",
    )

    research_get_parser = research_subparsers.add_parser(
        "get",
        help="Get details of a previously evaluated paper",
    )
    research_get_parser.add_argument(
        "paper_id",
        help="Paper ID to retrieve",
    )
    research_get_parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format (default: markdown)",
    )

    research_export_parser = research_subparsers.add_parser(
        "export",
        help="Export evaluations to file",
    )
    research_export_parser.add_argument(
        "output",
        help="Output file path (.md or .json)",
    )
    research_export_parser.add_argument(
        "--verdict",
        choices=["ADOPT", "ADAPT", "DEFER", "REJECT"],
        help="Filter by verdict",
    )
    research_export_parser.add_argument(
        "--since",
        help="Only include evaluations since date (YYYY-MM-DD)",
    )

    # research index - regenerate the research index
    research_index_parser = research_subparsers.add_parser(
        "index",
        help="Regenerate the RESEARCH_INDEX.md file",
    )

    # research handoff - create work items from ADOPT/ADAPT evaluations
    research_handoff_parser = research_subparsers.add_parser(
        "handoff",
        help="Create handoff work items for ADOPT/ADAPT evaluations to the next agent",
    )
    research_handoff_parser.add_argument(
        "paper_id",
        nargs="?",
        help="Paper ID to create handoff for (or 'all' for pending handoffs)",
    )
    research_handoff_parser.add_argument(
        "--project-id",
        help="Project ID to create work items in (required)",
    )
    research_handoff_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be created without actually creating",
    )

    # ── Architect agent commands ────────────────────────────────────────────────
    architect_parser = subparsers.add_parser(
        "architect",
        help="Architect agent - design systems and create ADRs from research handoffs",
    )
    architect_subparsers = architect_parser.add_subparsers(dest="architect_command")

    architect_pickup_parser = architect_subparsers.add_parser(
        "pickup",
        help="Find and process work items assigned to the architect agent",
    )
    architect_pickup_parser.add_argument(
        "work_item_id",
        nargs="?",
        help="Specific work item ID to process (or omit to find pending items)",
    )
    architect_pickup_parser.add_argument(
        "--project-id",
        help="Project ID to search for work items",
    )
    architect_pickup_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be processed without executing",
    )
    architect_pickup_parser.add_argument(
        "--output",
        help="Directory to save ADR output (default: docs/adr/)",
    )

    architect_list_parser = architect_subparsers.add_parser(
        "list",
        help="List pending work items for the architect agent",
    )
    architect_list_parser.add_argument(
        "--project-id",
        help="Project ID to search for work items",
    )
    architect_list_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format (default: table)",
    )

    # ------------------------------------------------------------------
    # work-item subcommand group
    # ------------------------------------------------------------------
    wi_parser = subparsers.add_parser(
        "work-item",
        help="Work item execution commands (execute, status, clarify, approve-gate)",
    )
    wi_subparsers = wi_parser.add_subparsers(dest="wi_command")

    # work-item execute
    wi_execute_parser = wi_subparsers.add_parser(
        "execute",
        help="Start execution of a work item using its assigned agent",
    )
    wi_execute_parser.add_argument("item_id", help="Work item ID or display ID (e.g. 'myproject-42')")
    wi_execute_parser.add_argument("--project-id", required=True, help="Project ID")
    wi_execute_parser.add_argument("--org-id", help="Organization ID")
    wi_execute_parser.add_argument("--model", help="Model override")
    wi_execute_parser.add_argument(
        "--callback-url",
        help="Webhook URL for gate event notifications",
    )
    wi_execute_parser.add_argument(
        "--watch",
        action="store_true",
        help="Watch execution events via SSE stream after starting",
    )
    wi_execute_parser.add_argument("--format", choices=["table", "json"], default="table")

    # work-item status
    wi_status_parser = wi_subparsers.add_parser(
        "status",
        help="Get execution status of a work item",
    )
    wi_status_parser.add_argument("item_id", help="Work item ID or display ID (e.g. 'myproject-42')")
    wi_status_parser.add_argument("--project-id", required=True, help="Project ID")
    wi_status_parser.add_argument("--org-id", help="Organization ID")
    wi_status_parser.add_argument("--format", choices=["table", "json"], default="table")

    # work-item clarify
    wi_clarify_parser = wi_subparsers.add_parser(
        "clarify",
        help="Provide a clarification response for a paused execution",
    )
    wi_clarify_parser.add_argument("item_id", help="Work item ID or display ID (e.g. 'myproject-42')")
    wi_clarify_parser.add_argument("--project-id", required=True, help="Project ID")
    wi_clarify_parser.add_argument("--org-id", help="Organization ID")
    wi_clarify_parser.add_argument(
        "--clarification-id", required=True, help="ID of the clarification question",
    )
    wi_clarify_parser.add_argument(
        "--response", required=True, help="Clarification response text",
    )

    # work-item approve-gate
    wi_approve_parser = wi_subparsers.add_parser(
        "approve-gate",
        help="Approve a strict gate and resume execution",
    )
    wi_approve_parser.add_argument("item_id", help="Work item ID or display ID (e.g. 'myproject-42')")
    wi_approve_parser.add_argument("--project-id", required=True, help="Project ID")
    wi_approve_parser.add_argument("--org-id", help="Organization ID")
    wi_approve_parser.add_argument("--phase", help="Phase gate to approve")
    wi_approve_parser.add_argument("--notes", help="Approval notes/feedback")

    # ── config ─────────────────────────────────────────────────────────────
    config_parser = subparsers.add_parser(
        "config",
        help="Show or update local Amprealize configuration (~/.amprealize/config.yaml)",
    )
    config_subparsers = config_parser.add_subparsers(dest="config_command")

    config_show_parser = config_subparsers.add_parser(
        "show",
        help="Display resolved configuration",
    )
    config_show_parser.add_argument(
        "--format",
        choices=("yaml", "json"),
        default="yaml",
        help="Output format (default: yaml)",
    )

    config_set_parser = config_subparsers.add_parser(
        "set",
        help="Set a config value in ~/.amprealize/config.yaml",
    )
    config_set_parser.add_argument(
        "key",
        help="Dot-separated config key, e.g. storage.backend",
    )
    config_set_parser.add_argument(
        "value",
        help="Value to set",
    )

    config_subparsers.add_parser(
        "path",
        help="Print path to user config file",
    )

    # ── context ────────────────────────────────────────────────────────────
    context_parser = subparsers.add_parser(
        "context",
        help="Manage named contexts (like kubectl context)",
    )
    context_subparsers = context_parser.add_subparsers(dest="context_command")

    context_subparsers.add_parser(
        "current",
        help="Show the active context",
    )

    context_list_parser = context_subparsers.add_parser(
        "list",
        help="List all available contexts with status",
    )
    context_list_parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format (default: table)",
    )

    context_use_parser = context_subparsers.add_parser(
        "use",
        help="Switch to a named context",
    )
    context_use_parser.add_argument(
        "name",
        help="Name of the context to switch to",
    )

    context_add_parser = context_subparsers.add_parser(
        "add",
        help="Create a new named context",
    )
    context_add_parser.add_argument(
        "name",
        help="Unique name for the new context",
    )
    context_add_parser.add_argument(
        "--backend",
        choices=("postgres", "sqlite", "memory"),
        default="sqlite",
        help="Storage backend type (default: sqlite)",
    )
    context_add_parser.add_argument(
        "--dsn",
        help="PostgreSQL DSN (required for postgres backend)",
    )
    context_add_parser.add_argument(
        "--sqlite-path",
        help="SQLite file path (optional, has sensible default)",
    )

    context_remove_parser = context_subparsers.add_parser(
        "remove",
        help="Remove a named context",
    )
    context_remove_parser.add_argument(
        "name",
        help="Name of the context to remove",
    )

    # ── items ──────────────────────────────────────────────────────────────
    items_parser = subparsers.add_parser(
        "items",
        help="Manage work items across contexts",
    )
    items_subparsers = items_parser.add_subparsers(dest="items_command")

    items_migrate_parser = items_subparsers.add_parser(
        "migrate",
        help="Migrate work items from one context to another",
    )
    items_migrate_parser.add_argument(
        "source",
        help="Source context name",
    )
    items_migrate_parser.add_argument(
        "target",
        help="Target context name",
    )
    items_migrate_parser.add_argument(
        "--filter",
        metavar="EXPR",
        help="Filter expression: type=story,status=in_progress,labels=bug|urgent",
    )
    items_migrate_parser.add_argument(
        "--project",
        metavar="ID",
        help="Filter by project ID",
    )
    items_migrate_parser.add_argument(
        "--board",
        metavar="ID",
        help="Filter by board ID",
    )
    items_migrate_parser.add_argument(
        "--type",
        choices=("epic", "story", "task", "bug"),
        help="Filter by item type",
    )
    items_migrate_parser.add_argument(
        "--status",
        help="Filter by status (e.g., in_progress, done)",
    )
    items_migrate_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview migration without making changes",
    )
    items_migrate_parser.add_argument(
        "--on-conflict",
        choices=("skip", "overwrite", "rename", "fail"),
        default="skip",
        help="How to handle conflicts (default: skip)",
    )
    items_migrate_parser.add_argument(
        "--org",
        metavar="ORG_ID",
        help="Organization ID for multi-tenant isolation",
    )
    items_migrate_parser.add_argument(
        "--no-boards",
        action="store_true",
        help="Skip migrating boards (will lose board associations)",
    )
    items_migrate_parser.add_argument(
        "--output",
        "-o",
        metavar="FILE",
        help="Save migration report to JSON file",
    )
    items_migrate_parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip confirmation prompt",
    )
    items_migrate_parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress progress output",
    )

    # ── db ─────────────────────────────────────────────────────────────────
    db_parser = subparsers.add_parser(
        "db",
        help="Local SQLite database management",
    )
    db_subparsers = db_parser.add_subparsers(dest="db_command")

    db_subparsers.add_parser(
        "migrate",
        help="Apply pending SQLite migrations",
    )

    db_subparsers.add_parser(
        "status",
        help="Show applied and pending migrations",
    )

    # ── knowledge-pack ─────────────────────────────────────────────────────
    kp_parser = subparsers.add_parser(
        "knowledge-pack",
        help="Build, validate, inspect, and manage knowledge packs",
    )
    kp_subparsers = kp_parser.add_subparsers(dest="knowledge_pack_command")

    kp_build_parser = kp_subparsers.add_parser(
        "build",
        help="Build a knowledge pack from registered sources",
    )
    kp_build_parser.add_argument(
        "--pack-id",
        help="Pack identifier (default: derived from project config)",
    )
    kp_build_parser.add_argument(
        "--version",
        help="Explicit version string e.g. '1.0.0' (default: auto-generated)",
    )
    kp_build_parser.add_argument(
        "--profile",
        default="solo-dev",
        choices=["solo-dev", "amprealize-platform", "custom"],
        help="Target profile with budget/overlay rules (default: solo-dev)",
    )
    kp_build_parser.add_argument(
        "--primer-template",
        help="Path to custom primer template file",
    )
    kp_build_parser.add_argument(
        "--token-budget",
        type=int,
        help="Override default token budget for pack",
    )
    kp_build_parser.add_argument(
        "--output-dir",
        help="Directory to write built pack artifacts",
    )
    kp_build_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format",
    )

    kp_validate_parser = kp_subparsers.add_parser(
        "validate",
        help="Validate a knowledge pack manifest file",
    )
    kp_validate_parser.add_argument(
        "manifest_path",
        metavar="MANIFEST_PATH",
        help="Path to the manifest JSON file to validate",
    )
    kp_validate_parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on warnings as well as errors",
    )
    kp_validate_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format",
    )

    kp_inspect_parser = kp_subparsers.add_parser(
        "inspect",
        help="Inspect an existing knowledge pack",
    )
    kp_inspect_parser.add_argument(
        "--pack-id",
        help="Pack identifier to inspect",
    )
    kp_inspect_parser.add_argument(
        "--version",
        help="Specific version to inspect (default: latest)",
    )
    kp_inspect_parser.add_argument(
        "--show-sources",
        action="store_true",
        help="Include source provenance details",
    )
    kp_inspect_parser.add_argument(
        "--show-overlays",
        action="store_true",
        help="Include overlay breakdown by task/surface/role",
    )
    kp_inspect_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format",
    )

    kp_list_parser = kp_subparsers.add_parser(
        "list",
        help="List all available knowledge packs",
    )
    kp_list_parser.add_argument(
        "--pack-id",
        help="Filter by pack identifier",
    )
    kp_list_parser.add_argument(
        "--limit",
        type=int,
        default=25,
        help="Maximum number of results (default: 25)",
    )
    kp_list_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format",
    )

    # ── pack (bootstrap / rollback) ────────────────────────────────────────
    pack_parser = subparsers.add_parser(
        "pack",
        help="Bootstrap or rollback knowledge packs for existing workspaces",
    )
    pack_subparsers = pack_parser.add_subparsers(dest="pack_command")

    pack_bootstrap_parser = pack_subparsers.add_parser(
        "bootstrap",
        help="Bootstrap a knowledge pack from an existing workspace",
    )
    pack_bootstrap_parser.add_argument(
        "--workspace",
        default=".",
        help="Workspace root path (default: current directory)",
    )
    pack_bootstrap_parser.add_argument(
        "--profile",
        choices=["solo-dev", "amprealize-platform", "team-collab",
                 "extension-dev", "api-backend", "compliance-sensitive"],
        default=None,
        help="Override detected workspace profile",
    )
    pack_bootstrap_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing AGENTS.md and config files",
    )
    pack_bootstrap_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format",
    )

    pack_rollback_parser = pack_subparsers.add_parser(
        "rollback",
        help="Deactivate the active pack and restore pre-pack behaviour",
    )
    pack_rollback_parser.add_argument(
        "--workspace",
        default=".",
        help="Workspace root path (default: current directory)",
    )
    pack_rollback_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format",
    )

    pack_status_parser = pack_subparsers.add_parser(
        "status",
        help="Show workspace storage and pack activation status",
    )
    pack_status_parser.add_argument(
        "--workspace",
        default=".",
        help="Workspace root path (default: current directory)",
    )
    pack_status_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format",
    )

    # ── init ───────────────────────────────────────────────────────────────
    init_parser = subparsers.add_parser(
        "init",
        help="Scaffold a new Amprealize project in the current directory",
    )
    init_parser.add_argument(
        "--name",
        default=None,
        help="Project name (default: current directory name). Skips interactive prompt.",
    )
    init_parser.add_argument(
        "--storage",
        choices=["sqlite", "postgres"],
        default=None,
        help="Storage backend (default: sqlite). Skips interactive prompt.",
    )
    init_parser.add_argument(
        "--auth",
        choices=["local", "cloud"],
        default=None,
        help="Auth mode (default: local). Skips interactive prompt.",
    )
    init_parser.add_argument(
        "--template",
        choices=["full", "minimal"],
        default="full",
        help="Scaffolding template (default: full)",
    )
    init_parser.add_argument(
        "--non-interactive",
        action="store_true",
        default=False,
        help="Skip all prompts, use defaults or provided flags",
    )
    init_parser.add_argument(
        "--profile",
        choices=[
            "solo-dev",
            "amprealize-platform",
            "team-collab",
            "extension-dev",
            "api-backend",
            "compliance-sensitive",
        ],
        default=None,
        help="Workspace profile to use (skips auto-detection)",
    )
    init_parser.add_argument(
        "--detect-only",
        action="store_true",
        default=False,
        help="Run workspace detection and print result without scaffolding",
    )
    init_parser.add_argument(
        "--skip-pack",
        action="store_true",
        default=False,
        help="Skip knowledge-pack activation during init",
    )
    init_parser.add_argument(
        "--modules",
        default=None,
        help=(
            "Module preset or comma-separated module names. "
            "Presets: goals, goals-agents, goals-behaviors, full. "
            "Modules: goals,agents,behaviors. Skips interactive prompt."
        ),
    )
    init_parser.add_argument(
        "--deployment",
        choices=["local", "cloud", "hybrid"],
        default=None,
        help="Deployment mode (default: local). Skips interactive prompt.",
    )

    # ── bootstrap ──────────────────────────────────────────────────────────
    # MCP-parity commands for workspace profiling
    bootstrap_parser = subparsers.add_parser(
        "bootstrap",
        help="Workspace profiling and initialization commands",
    )
    bootstrap_subparsers = bootstrap_parser.add_subparsers(dest="bootstrap_command")

    # bootstrap detect
    bootstrap_detect_parser = bootstrap_subparsers.add_parser(
        "detect",
        help="Detect workspace profile by analyzing project structure",
    )
    bootstrap_detect_parser.add_argument(
        "--path",
        default=".",
        help="Path to workspace (default: current directory)",
    )
    bootstrap_detect_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format (default: table)",
    )

    # bootstrap status
    bootstrap_status_parser = bootstrap_subparsers.add_parser(
        "status",
        help="Show bootstrap status for workspace",
    )
    bootstrap_status_parser.add_argument(
        "--path",
        default=".",
        help="Path to workspace (default: current directory)",
    )
    bootstrap_status_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format (default: table)",
    )

    # bootstrap init (alias for amprealize init with bootstrap focus)
    bootstrap_init_parser = bootstrap_subparsers.add_parser(
        "init",
        help="Initialize workspace with Amprealize (alias for amprealize init)",
    )
    bootstrap_init_parser.add_argument(
        "--path",
        default=".",
        help="Path to workspace (default: current directory)",
    )
    bootstrap_init_parser.add_argument(
        "--profile",
        choices=[
            "solo-dev",
            "amprealize-platform",
            "team-collab",
            "extension-dev",
            "api-backend",
            "compliance-sensitive",
        ],
        default=None,
        help="Override auto-detected profile",
    )
    bootstrap_init_parser.add_argument(
        "--skip-primer",
        action="store_true",
        default=False,
        help="Skip AGENTS.md generation",
    )
    bootstrap_init_parser.add_argument(
        "--skip-pack",
        action="store_true",
        default=False,
        help="Skip knowledge pack activation",
    )
    bootstrap_init_parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Overwrite existing files",
    )
    bootstrap_init_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format (default: table)",
    )

    # ── flags ──────────────────────────────────────────────────────────────
    flags_parser = subparsers.add_parser(
        "flags",
        help="Feature flag management (list, get, set)",
    )
    flags_subparsers = flags_parser.add_subparsers(dest="flags_command")

    # flags list
    flags_list_parser = flags_subparsers.add_parser(
        "list",
        help="List all registered feature flags",
    )
    flags_list_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")

    # flags get
    flags_get_parser = flags_subparsers.add_parser(
        "get",
        help="Get a single feature flag by name",
    )
    flags_get_parser.add_argument("flag_name", help="Dotted flag name (e.g. feature.auto_reflection)")
    flags_get_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")

    # flags set
    flags_set_parser = flags_subparsers.add_parser(
        "set",
        help="Update a feature flag's state",
    )
    flags_set_parser.add_argument("flag_name", help="Dotted flag name")
    flags_set_parser.add_argument("--enabled", type=lambda v: v.lower() in ("true", "1", "yes"), help="Enable/disable")
    flags_set_parser.add_argument("--percentage", type=int, help="Rollout percentage (0-100)")
    flags_set_parser.add_argument("--user-list", nargs="*", help="User allowlist")
    flags_set_parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format")

    # ── mcp-server ─────────────────────────────────────────────────────────
    mcp_parser = subparsers.add_parser(
        "mcp-server",
        help="Start the Amprealize MCP server",
    )
    mcp_parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default=None,
        help="Transport mode (default: from config, fallback stdio)",
    )
    mcp_parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port for SSE transport (default: 8765)",
    )
    mcp_parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=None,
        help="Override log level",
    )
    mcp_subparsers = mcp_parser.add_subparsers(dest="mcp_command")
    mcp_subparsers.add_parser(
        "init",
        help="Generate MCP configuration for IDEs and Codex",
    )
    mcp_doctor_parser = mcp_subparsers.add_parser(
        "doctor",
        help="Smoke-test MCP startup with initialize + tools/list",
    )
    mcp_doctor_parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Timeout in seconds for the MCP smoke test (default: 10)",
    )

    # ── open ────────────────────────────────────────────────────────────────
    open_parser = subparsers.add_parser(
        "open",
        help="Launch the Amprealize dashboard in your browser",
    )
    open_parser.add_argument(
        "page",
        nargs="?",
        default=None,
        choices=["behaviors", "runs", "boards", "settings"],
        help="Deep-link to a specific dashboard page",
    )
    open_parser.add_argument(
        "--no-browser",
        action="store_true",
        default=False,
        help="Start server but don't open the browser (just print URL)",
    )
    open_parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Override server port (default: from config, fallback 8765)",
    )
    open_parser.add_argument(
        "--stop",
        action="store_true",
        default=False,
        help="Stop a running Amprealize server",
    )

    # ── amprealize infra (provider-agnostic infrastructure management) ────
    infra_parser = subparsers.add_parser(
        "infra",
        help="Manage local infrastructure (breakeramp, docker-compose, or external)",
    )
    infra_parser.add_argument(
        "--provider",
        choices=["auto", "breakeramp", "docker-compose", "external", "none"],
        default=None,
        help="Override infrastructure provider (default: from config or auto-detect)",
    )
    infra_sub = infra_parser.add_subparsers(dest="infra_action")

    infra_up = infra_sub.add_parser("up", help="Start infrastructure services")
    infra_up.add_argument(
        "--profile",
        choices=["minimal", "standard", "full"],
        default="standard",
        help="Service profile (default: standard)",
    )

    infra_sub.add_parser("down", help="Stop infrastructure services")
    infra_sub.add_parser("status", help="List active environments and their state")
    infra_sub.add_parser("resources", help="Show resource utilisation (memory, disk, CPU)")
    infra_sub.add_parser("reset", help="Destroy and recreate all infrastructure (destructive)")
    infra_sub.add_parser("configure", help="Interactively select infrastructure provider")

    # ── conversation ───────────────────────────────────────────────────────
    conversation_parser = subparsers.add_parser(
        "conversation",
        help="Manage conversations and messages",
    )
    conv_subparsers = conversation_parser.add_subparsers(dest="conversation_command")

    # conversation list
    conv_list_parser = conv_subparsers.add_parser(
        "list", help="List conversations in a project",
    )
    conv_list_parser.add_argument("--project-id", required=True, help="Project ID")
    conv_list_parser.add_argument("--user-id", default=DEFAULT_ACTOR_ID, help="User ID")
    conv_list_parser.add_argument("--org-id", default=None, help="Organization ID")
    conv_list_parser.add_argument(
        "--scope", choices=["project_room", "agent_dm"], default=None,
        help="Filter by conversation scope",
    )
    conv_list_parser.add_argument(
        "--include-archived", action="store_true", default=False,
        help="Include archived conversations",
    )
    conv_list_parser.add_argument("--limit", type=int, default=50, help="Max results")
    conv_list_parser.add_argument("--offset", type=int, default=0, help="Offset for pagination")
    conv_list_parser.add_argument(
        "--format", choices=["table", "json"], default="table", help="Output format",
    )

    # conversation get
    conv_get_parser = conv_subparsers.add_parser(
        "get", help="Get conversation details",
    )
    conv_get_parser.add_argument("conversation_id", help="Conversation ID")
    conv_get_parser.add_argument("--user-id", default=DEFAULT_ACTOR_ID, help="User ID")
    conv_get_parser.add_argument("--org-id", default=None, help="Organization ID")
    conv_get_parser.add_argument(
        "--format", choices=["table", "json"], default="table", help="Output format",
    )

    # conversation create
    conv_create_parser = conv_subparsers.add_parser(
        "create", help="Create a new conversation",
    )
    conv_create_parser.add_argument("--project-id", required=True, help="Project ID")
    conv_create_parser.add_argument(
        "--scope", choices=["project_room", "agent_dm"], default="agent_dm",
        help="Conversation scope",
    )
    conv_create_parser.add_argument("--title", default=None, help="Conversation title")
    conv_create_parser.add_argument("--user-id", default=DEFAULT_ACTOR_ID, help="Creator user ID")
    conv_create_parser.add_argument(
        "--participants", nargs="*", default=None,
        help="Additional participant IDs",
    )
    conv_create_parser.add_argument("--org-id", default=None, help="Organization ID")
    conv_create_parser.add_argument(
        "--format", choices=["table", "json"], default="table", help="Output format",
    )

    # conversation archive
    conv_archive_parser = conv_subparsers.add_parser(
        "archive", help="Archive a conversation",
    )
    conv_archive_parser.add_argument("conversation_id", help="Conversation ID")
    conv_archive_parser.add_argument("--user-id", default=DEFAULT_ACTOR_ID, help="User ID")
    conv_archive_parser.add_argument("--org-id", default=None, help="Organization ID")
    conv_archive_parser.add_argument(
        "--format", choices=["table", "json"], default="json", help="Output format",
    )

    # conversation send
    conv_send_parser = conv_subparsers.add_parser(
        "send", help="Send a message to a conversation",
    )
    conv_send_parser.add_argument("conversation_id", help="Conversation ID")
    conv_send_parser.add_argument("content", help="Message content")
    conv_send_parser.add_argument("--user-id", default=DEFAULT_ACTOR_ID, help="Sender user ID")
    conv_send_parser.add_argument(
        "--type", dest="message_type", default="text",
        choices=["text", "status_card", "blocker_card", "progress_card", "code_block", "run_summary", "system"],
        help="Message type",
    )
    conv_send_parser.add_argument("--parent-id", default=None, help="Parent message ID (thread reply)")
    conv_send_parser.add_argument("--run-id", default=None, help="Associated run ID")
    conv_send_parser.add_argument("--behavior-id", default=None, help="Associated behavior ID")
    conv_send_parser.add_argument("--work-item-id", default=None, help="Associated work item ID")
    conv_send_parser.add_argument("--org-id", default=None, help="Organization ID")
    conv_send_parser.add_argument(
        "--format", choices=["table", "json"], default="table", help="Output format",
    )

    # conversation messages
    conv_messages_parser = conv_subparsers.add_parser(
        "messages", help="List messages in a conversation",
    )
    conv_messages_parser.add_argument("conversation_id", help="Conversation ID")
    conv_messages_parser.add_argument("--user-id", default=DEFAULT_ACTOR_ID, help="User ID")
    conv_messages_parser.add_argument("--org-id", default=None, help="Organization ID")
    conv_messages_parser.add_argument("--parent-id", default=None, help="Filter by parent (thread)")
    conv_messages_parser.add_argument("--limit", type=int, default=50, help="Max results")
    conv_messages_parser.add_argument("--offset", type=int, default=0, help="Offset for pagination")
    conv_messages_parser.add_argument(
        "--format", choices=["table", "json"], default="table", help="Output format",
    )

    # conversation search
    conv_search_parser = conv_subparsers.add_parser(
        "search", help="Search messages in a conversation",
    )
    conv_search_parser.add_argument("conversation_id", help="Conversation ID")
    conv_search_parser.add_argument("query", help="Search query text")
    conv_search_parser.add_argument("--user-id", default=DEFAULT_ACTOR_ID, help="User ID")
    conv_search_parser.add_argument("--org-id", default=None, help="Organization ID")
    conv_search_parser.add_argument("--limit", type=int, default=20, help="Max results")
    conv_search_parser.add_argument("--offset", type=int, default=0, help="Offset for pagination")
    conv_search_parser.add_argument(
        "--format", choices=["table", "json"], default="table", help="Output format",
    )

    # conversation react
    conv_react_parser = conv_subparsers.add_parser(
        "react", help="Add or remove a reaction on a message",
    )
    conv_react_parser.add_argument("message_id", help="Message ID")
    conv_react_parser.add_argument("emoji", help="Emoji to react with (e.g. thumbsup, heart)")
    conv_react_parser.add_argument("--user-id", default=DEFAULT_ACTOR_ID, help="User ID")
    conv_react_parser.add_argument("--org-id", default=None, help="Organization ID")
    conv_react_parser.add_argument(
        "--remove", action="store_true", default=False,
        help="Remove the reaction instead of adding",
    )
    conv_react_parser.add_argument(
        "--format", choices=["table", "json"], default="json", help="Output format",
    )

    # conversation edit
    conv_edit_parser = conv_subparsers.add_parser(
        "edit", help="Edit a message (within 5-minute window)",
    )
    conv_edit_parser.add_argument("message_id", help="Message ID to edit")
    conv_edit_parser.add_argument("content", help="New message content")
    conv_edit_parser.add_argument("--user-id", default=DEFAULT_ACTOR_ID, help="Editor user ID")
    conv_edit_parser.add_argument("--org-id", default=None, help="Organization ID")
    conv_edit_parser.add_argument(
        "--format", choices=["table", "json"], default="table", help="Output format",
    )

    # conversation delete
    conv_delete_parser = conv_subparsers.add_parser(
        "delete", help="Delete a message",
    )
    conv_delete_parser.add_argument("message_id", help="Message ID to delete")
    conv_delete_parser.add_argument("--user-id", default=DEFAULT_ACTOR_ID, help="Deleter user ID")
    conv_delete_parser.add_argument("--org-id", default=None, help="Organization ID")
    conv_delete_parser.add_argument(
        "--format", choices=["table", "json"], default="json", help="Output format",
    )

    # conversation get-message
    conv_getmsg_parser = conv_subparsers.add_parser(
        "get-message", help="Get a single message by ID",
    )
    conv_getmsg_parser.add_argument("message_id", help="Message ID")
    conv_getmsg_parser.add_argument("--user-id", default=DEFAULT_ACTOR_ID, help="User ID")
    conv_getmsg_parser.add_argument("--org-id", default=None, help="Organization ID")
    conv_getmsg_parser.add_argument(
        "--format", choices=["table", "json"], default="json", help="Output format",
    )

    # conversation pin
    conv_pin_parser = conv_subparsers.add_parser(
        "pin", help="Pin a message in a conversation",
    )
    conv_pin_parser.add_argument("conversation_id", help="Conversation ID")
    conv_pin_parser.add_argument("message_id", help="Message ID to pin")
    conv_pin_parser.add_argument("--user-id", default=DEFAULT_ACTOR_ID, help="User ID (owner/admin)")
    conv_pin_parser.add_argument("--org-id", default=None, help="Organization ID")
    conv_pin_parser.add_argument(
        "--format", choices=["table", "json"], default="json", help="Output format",
    )

    # conversation unpin
    conv_unpin_parser = conv_subparsers.add_parser(
        "unpin", help="Unpin the pinned message in a conversation",
    )
    conv_unpin_parser.add_argument("conversation_id", help="Conversation ID")
    conv_unpin_parser.add_argument("--user-id", default=DEFAULT_ACTOR_ID, help="User ID (owner/admin)")
    conv_unpin_parser.add_argument("--org-id", default=None, help="Organization ID")
    conv_unpin_parser.add_argument(
        "--format", choices=["table", "json"], default="json", help="Output format",
    )

    # ── doctor ─────────────────────────────────────────────────────────────
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Run diagnostics to verify Amprealize installation health",
    )
    doctor_parser.add_argument(
        "--fix",
        action="store_true",
        default=False,
        help="Attempt to automatically fix detected issues",
    )
    doctor_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="Show detailed check output",
    )
    doctor_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output results as JSON",
    )

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        parser.exit(1)
    if args.command == "behaviors" and not getattr(args, "behaviors_command", None):
        behaviors_parser.print_help()
        parser.exit(1)
    if args.command == "compliance" and not getattr(args, "compliance_command", None):
        compliance_parser.print_help()
        parser.exit(1)
    if args.command == "workflow" and not getattr(args, "workflow_command", None):
        workflow_parser.print_help()
        parser.exit(1)
    if args.command == "agents" and not getattr(args, "agents_command", None):
        agents_parser.print_help()
        parser.exit(1)
    if args.command == "telemetry" and not getattr(args, "telemetry_command", None):
        telemetry_parser.print_help()
        parser.exit(1)
    if args.command == "analytics" and not getattr(args, "analytics_command", None):
        analytics_parser.print_help()
        parser.exit(1)
    if args.command == "bci" and not getattr(args, "bci_command", None):
        bci_parser.print_help()
        parser.exit(1)
    if args.command == "breakeramp" and not getattr(args, "breakeramp_command", None):
        amp_parser.print_help()
        parser.exit(1)
    if args.command == "audit" and not getattr(args, "audit_command", None):
        audit_parser.print_help()
        parser.exit(1)
    if args.command == "auth" and not getattr(args, "auth_command", None):
        auth_parser.print_help()
        parser.exit(1)
    if args.command == "migrate" and not getattr(args, "migrate_command", None):
        migrate_parser.print_help()
        parser.exit(1)
    if args.command == "research" and not getattr(args, "research_command", None):
        research_parser.print_help()
        parser.exit(1)
    if args.command == "architect" and not getattr(args, "architect_command", None):
        architect_parser.print_help()
        parser.exit(1)
    if args.command == "work-item" and not getattr(args, "wi_command", None):
        wi_parser.print_help()
        parser.exit(1)
    if args.command == "config" and not getattr(args, "config_command", None):
        config_parser.print_help()
        parser.exit(1)
    if args.command == "context" and not getattr(args, "context_command", None):
        context_parser.print_help()
        parser.exit(1)
    if args.command == "db" and not getattr(args, "db_command", None):
        db_parser.print_help()
        parser.exit(1)
    if args.command == "knowledge-pack" and not getattr(args, "knowledge_pack_command", None):
        kp_parser.print_help()
        parser.exit(1)
    if args.command == "pack" and not getattr(args, "pack_command", None):
        pack_parser.print_help()
        parser.exit(1)
    if args.command == "flags" and not getattr(args, "flags_command", None):
        flags_parser.print_help()
        parser.exit(1)
    if args.command == "conversation" and not getattr(args, "conversation_command", None):
        conversation_parser.print_help()
        parser.exit(1)
    # mcp-server has no required subcommand — bare invocation starts the server
    return args


def _load_metadata(items: List[str], metadata_file: Optional[str]) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {}

    if metadata_file:
        path = Path(metadata_file).expanduser().resolve()
        if not path.exists():
            raise ValueError(f"Metadata file not found: {path}")
        raw = path.read_text(encoding="utf-8")
        loaded = json.loads(raw) if raw.strip() else {}
        if not isinstance(loaded, dict):
            raise ValueError("Metadata file must contain a JSON object")
        metadata.update(loaded)

    for entry in items:
        if "=" not in entry:
            raise ValueError(f"Invalid metadata entry '{entry}'. Use KEY=VALUE format.")
        key, value = entry.split("=", 1)
        metadata[key] = value

    return metadata


def _load_agent_context(context_json: Optional[str], context_file: Optional[str]) -> Optional[Dict[str, Any]]:
    """Load agent assignment context from direct JSON or a JSON file."""

    if context_json and context_file:
        raise ValueError("Provide either --context or --context-file, not both")

    payload: Any = None
    if context_file:
        payload = _load_json_file(context_file)
    elif context_json:
        try:
            payload = json.loads(context_json)
        except json.JSONDecodeError as exc:
            raise ValueError("Context must be valid JSON") from exc

    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("Context must be a JSON object")
    return payload


def _parse_embedding_arg(raw: Optional[str]) -> Optional[List[float]]:
    if raw is None or raw.strip() == "":
        return None
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if not parts:
        return None
    try:
        return [float(part) for part in parts]
    except ValueError as exc:  # pragma: no cover - defensive validation
        raise ValueError("Embedding must contain numeric values") from exc


def _load_examples(path: Optional[str]) -> List[Dict[str, Any]]:
    if not path:
        return []
    file_path = Path(path).expanduser().resolve()
    if not file_path.exists():
        raise ValueError(f"Examples file not found: {file_path}")
    raw = file_path.read_text(encoding="utf-8")
    if not raw.strip():
        return []
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("Examples file must contain a JSON array")
    normalized: List[Dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("Each example must be an object with keys like title/body")
        normalized.append(dict(item))
    return normalized


def _render_actions_table(actions: List[Dict[str, Any]]) -> None:
    if not actions:
        print("No actions recorded yet.")
        return

    headers = ["Action ID", "Summary", "Artifact", "Replay"]
    widths = [len(header) for header in headers]
    rows: List[List[str]] = []

    for action in actions:
        row = [
            action["action_id"],
            action["summary"],
            action["artifact_path"],
            action.get("replay_status", "UNKNOWN"),
        ]
        rows.append(row)
        widths = [max(width, len(value)) for width, value in zip(widths, row)]

    fmt = " | ".join(f"{{:<{width}}}" for width in widths)
    separator = "-+-".join("-" * width for width in widths)

    print(fmt.format(*headers))
    print(separator)
    for row in rows:
        print(fmt.format(*row))


def _render_behaviors_table(entries: List[Dict[str, Any]]) -> None:
    if not entries:
        print("No behaviors found.")
        return

    headers = ["Behavior ID", "Name", "Status", "Latest", "Role", "Tags"]
    widths = [len(header) for header in headers]
    rows: List[List[str]] = []

    for entry in entries:
        behavior = entry["behavior"]
        active = entry.get("active_version") or {}
        row = [
            behavior["behavior_id"],
            behavior["name"],
            behavior.get("status", "UNKNOWN"),
            behavior.get("latest_version", "-"),
            active.get("role_focus", "-"),
            ", ".join(behavior.get("tags", [])) or "-",
        ]
        rows.append(row)
        widths = [max(width, len(value)) for width, value in zip(widths, row)]

    fmt = " | ".join(f"{{:<{width}}}" for width in widths)
    separator = "-+-".join("-" * width for width in widths)

    print(fmt.format(*headers))
    print(separator)
    for row in rows:
        print(fmt.format(*row))


def _render_behavior_search_results(results: List[Dict[str, Any]]) -> None:
    if not results:
        print("No behaviors matched the query.")
        return

    headers = ["Score", "Behavior ID", "Name", "Status", "Role", "Tags"]
    widths = [len(header) for header in headers]
    rows: List[List[str]] = []

    for result in results:
        behavior = result["behavior"]
        active = result.get("active_version") or {}
        row = [
            f"{result.get('score', 0.0):.2f}",
            behavior["behavior_id"],
            behavior["name"],
            behavior.get("status", "UNKNOWN"),
            active.get("role_focus", "-"),
            ", ".join(behavior.get("tags", [])) or "-",
        ]
        rows.append(row)
        widths = [max(width, len(value)) for width, value in zip(widths, row)]

    fmt = " | ".join(f"{{:<{width}}}" for width in widths)
    separator = "-+-".join("-" * width for width in widths)

    print(fmt.format(*headers))
    print(separator)
    for row in rows:
        print(fmt.format(*row))


def _render_behavior_detail(detail: Dict[str, Any]) -> None:
    behavior = detail.get("behavior", {})
    versions = detail.get("versions", [])

    print(f"Behavior: {behavior.get('name', 'unknown')} ({behavior.get('behavior_id', '-')})")
    print(f"Status: {behavior.get('status', '-')}, Latest: {behavior.get('latest_version', '-')}")
    print(f"Tags: {', '.join(behavior.get('tags', [])) or '-'}")
    print(f"Created: {behavior.get('created_at', '-')}, Updated: {behavior.get('updated_at', '-')}")
    print()
    if not versions:
        print("No versions available.")
        return

    headers = ["Version", "Status", "Role", "Effective From", "Effective To"]
    widths = [len(header) for header in headers]
    rows: List[List[str]] = []
    for version in versions:
        row = [
            version.get("version", "-"),
            version.get("status", "-"),
            version.get("role_focus", "-"),
            version.get("effective_from", "-"),
            version.get("effective_to", "-") or "-",
        ]
        rows.append(row)
        widths = [max(width, len(value)) for width, value in zip(widths, row)]

    fmt = " | ".join(f"{{:<{width}}}" for width in widths)
    separator = "-+-".join("-" * width for width in widths)

    print(fmt.format(*headers))
    print(separator)
    for row in rows:
        print(fmt.format(*row))


def _command_behaviors_create(args: argparse.Namespace) -> int:
    adapter = _get_behavior_adapter()
    try:
        metadata = _load_metadata(args.metadata_items or [], args.metadata_file)
        examples = _load_examples(args.examples_file)
        embedding = _parse_embedding_arg(args.embedding)
        result = adapter.create(
            name=args.name,
            description=args.description,
            instruction=args.instruction,
            role_focus=args.role_focus,
            trigger_keywords=args.keywords or [],
            tags=args.tags or [],
            metadata=metadata,
            examples=examples,
            embedding=embedding,
            actor_id=args.actor_id,
            actor_role=args.actor_role,
        )
    except Exception as exc:  # pragma: no cover - CLI surface area
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_behavior_detail(result)
    else:
        _print_json(result)
    return 0


def _command_behaviors_list(args: argparse.Namespace) -> int:
    adapter = _get_behavior_adapter()
    try:
        results = adapter.list(
            status=args.status,
            tags=args.tags or None,
            role_focus=args.role_focus,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        _print_json(results)
    else:
        _render_behaviors_table(results)
    return 0


def _command_behaviors_search(args: argparse.Namespace) -> int:
    adapter = _get_behavior_adapter()
    try:
        results = adapter.search(
            query=args.query,
            tags=args.tags or None,
            role_focus=args.role_focus,
            status=args.status,
            limit=args.limit,
            actor_id=args.actor_id,
            actor_role=args.actor_role,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        _print_json(results)
    else:
        _render_behavior_search_results(results)
    return 0


def _command_behaviors_get(args: argparse.Namespace) -> int:
    adapter = _get_behavior_adapter()
    try:
        result = adapter.get(args.behavior_id, args.version)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
                             _render_behavior_detail(result)
    else:
        _print_json(result)
    return 0


def _command_behaviors_update(args: argparse.Namespace) -> int:
    adapter = _get_behavior_adapter()
    try:
        metadata = None
        if args.metadata_items or args.metadata_file:
            metadata = _load_metadata(args.metadata_items or [], args.metadata_file)
        examples = None
        if args.examples_file:
            examples = _load_examples(args.examples_file)
        embedding = _parse_embedding_arg(args.embedding) if args.embedding is not None else None
        result = adapter.update(
            behavior_id=args.behavior_id,
            version=args.version,
            instruction=args.instruction,
            description=args.description,
            trigger_keywords=args.keywords,
            tags=args.tags,
            metadata=metadata,
            examples=examples,
            embedding=embedding,
            actor_id=args.actor_id,
            actor_role=args.actor_role,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_behavior_detail(result)
    else:
        _print_json(result)
    return 0


def _command_behaviors_submit(args: argparse.Namespace) -> int:
    adapter = _get_behavior_adapter()
    try:
        result = adapter.submit(
            args.behavior_id,
            args.version,
            args.actor_id,
            args.actor_role,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_behavior_detail(result)
    else:
        _print_json(result)
    return 0


def _command_behaviors_approve(args: argparse.Namespace) -> int:
    adapter = _get_behavior_adapter()
    try:
        result = adapter.approve(
            behavior_id=args.behavior_id,
            version=args.version,
            effective_from=args.effective_from,
            approval_action_id=args.approval_action_id,
            actor_id=args.actor_id,
            actor_role=args.actor_role,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_behavior_detail(result)
    else:
        _print_json(result)
    return 0


def _command_behaviors_deprecate(args: argparse.Namespace) -> int:
    adapter = _get_behavior_adapter()
    try:
        result = adapter.deprecate(
            behavior_id=args.behavior_id,
            version=args.version,
            effective_to=args.effective_to,
            successor_behavior_id=args.successor_behavior_id,
            actor_id=args.actor_id,
            actor_role=args.actor_role,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_behavior_detail(result)
    else:
        _print_json(result)
    return 0


def _command_behaviors_delete_draft(args: argparse.Namespace) -> int:
    adapter = _get_behavior_adapter()
    try:
        adapter.delete_draft(args.behavior_id, args.version, args.actor_id, args.actor_role)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if getattr(args, "format", None) == "json":
        _print_json({"status": "deleted", "behavior_id": args.behavior_id, "version": args.version})
    else:
        print(f"Deleted draft version {args.version} for behavior {args.behavior_id}")
    return 0


def _command_behaviors_propose(args: argparse.Namespace) -> int:
    """Propose a new behavior from observed patterns.

    Implements the behavior proposal workflow from AGENTS.md:
    - Phase 2 (PROPOSE): Strategist drafts behavior
    - Auto-approval if confidence >= 0.8 and 3+ validations
    - Otherwise, creates draft for Teacher review
    """
    from amprealize.behavior_service import (
        BehaviorService,
        ProposeBehaviorRequest,
        RoleContext,
    )
    try:
        # Load optional metadata and examples
        metadata = _load_metadata([], args.metadata_file) if args.metadata_file else {}
        examples = _load_examples(args.examples_file) if args.examples_file else []

        # Build proposal request
        request = ProposeBehaviorRequest(
            name=args.name,
            description=args.description,
            instruction=args.instruction,
            role_focus=args.role_focus,
            trigger_keywords=args.keywords or [],
            tags=args.tags or [],
            examples=examples,
            metadata=metadata,
            confidence_score=args.confidence_score,
            historical_validations=args.historical_validations or [],
            pattern_id=args.pattern_id,
            proposed_by_role=args.proposed_by_role,
            rationale=args.rationale,
        )

        # Build role context for telemetry (optional but emphasized)
        role_context = RoleContext(
            role=args.proposed_by_role,
            rationale=f"Proposing behavior: {args.name}",
            behaviors_cited=["behavior_curate_behavior_handbook"],
        )

        actor = _build_cli_actor(args.actor_id, args.actor_role)

        # Get service and propose
        service = BehaviorService()
        result = service.propose_behavior(request, actor, role_context)

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        _print_json(result)
    else:
        # Table format with color indicators
        if result.get("auto_approved"):
            print(f"✅ Behavior auto-approved: {result['behavior_id']}")
            print(f"   Confidence: {result['confidence_score']:.2f}")
            print(f"   Status: APPROVED")
        else:
            print(f"📋 Behavior proposed for Teacher review: {result['behavior_id']}")
            print(f"   Confidence: {result['confidence_score']:.2f}")
            print(f"   Status: DRAFT (needs Teacher validation)")
            print(f"   Message: {result['message']}")
    return 0


def _command_behaviors_get_for_task(args: argparse.Namespace) -> int:
    """Get relevant behaviors for a task before execution.

    This is the primary command agents should use at the start of any task
    to retrieve applicable behaviors. Returns role-specific advisory.
    """
    from amprealize.behavior_service import BehaviorService, RoleContext
    try:
        actor = _build_cli_actor(args.actor_id, args.actor_role)

        # Build role context for telemetry
        role_context = RoleContext(
            role=args.role,
            rationale=f"Retrieving behaviors for task: {args.task_description[:50]}...",
        )

        if _behavior_backend_is_reachable():
            service = BehaviorService()
            result = service.get_relevant_behaviors_for_task(
                task_description=args.task_description,
                role=args.role,
                limit=args.limit,
                actor=actor,
                role_context=role_context,
            )
        else:
            result = _get_local_behaviors_for_task(
                task_description=args.task_description,
                role=args.role,
                limit=args.limit,
            )
    except Exception as exc:
        if not _should_use_local_behavior_fallback(exc):
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        result = _get_local_behaviors_for_task(
            task_description=args.task_description,
            role=args.role,
            limit=args.limit,
        )
        result["backend_error"] = str(exc)

    if args.format == "json":
        # Serialize behaviors for JSON output
        output = {
            "role": result["role"],
            "task_description": result["task_description"],
            "role_advisory": result["role_advisory"],
            "recommended_behaviors": result["recommended_behaviors"],
        }
        if result.get("source"):
            output["source"] = result["source"]
            output["agents_path"] = result.get("agents_path")
        if result.get("backend_error"):
            output["backend_error"] = result["backend_error"]
        _print_json(output)
    else:
        # Table format with advisory
        if result.get("source") == "local_handbook_fallback":
            print(
                f"Using local handbook fallback from {result['agents_path']}.",
                file=sys.stderr,
            )
        print(f"\n{result['role_advisory']}\n")
        print("=" * 60)

        if not result["recommended_behaviors"]:
            print("No matching behaviors found.")
        else:
            for i, behavior in enumerate(result["recommended_behaviors"], 1):
                print(f"\n{i}. {behavior['name']}")
                print(f"   Role: {behavior['role_focus']} | Score: {behavior['score']:.2f}")
                if behavior.get('confidence_score'):
                    print(f"   Confidence: {behavior['confidence_score']:.2f}")
                print(f"   Keywords: {', '.join(behavior['trigger_keywords'][:5])}")
                # Truncate instruction for display
                instruction = behavior['instruction'][:100]
                if len(behavior['instruction']) > 100:
                    instruction += "..."
                print(f"   Instruction: {instruction}")

        print("\n" + "=" * 60)
        print("Cite these behaviors in your work output as: Following `behavior_name` (Role)...")
    return 0


def _render_replay_table(payload: Dict[str, Any]) -> None:
    headers = ["Replay ID", "Status", "Progress", "Failed Count"]
    progress = f"{payload.get('progress', 0):.2f}"
    failed = payload.get("failed_action_ids", [])
    row = [payload.get("replay_id", "?"), payload.get("status", "UNKNOWN"), progress, str(len(failed))]
    widths = [max(len(header), len(value)) for header, value in zip(headers, row)]
    fmt = " | ".join(f"{{:<{width}}}" for width in widths)
    separator = "-+-".join("-" * width for width in widths)
    print(fmt.format(*headers))
    print(separator)
    print(fmt.format(*row))


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=_json_default))


def _serialize_model(payload: Any) -> Any:
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    if hasattr(payload, "dict"):
        return payload.dict()
    if isinstance(payload, list):
        return [_serialize_model(item) for item in payload]
    if isinstance(payload, dict):
        return {key: _serialize_model(value) for key, value in payload.items()}
    return payload


def _ensure_breakeramp_snapshot_dir() -> Path:
    BREAKERAMP_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    return BREAKERAMP_SNAPSHOT_DIR


def _save_breakeramp_snapshot(command: str, payload: Any) -> Path:
    directory = _ensure_breakeramp_snapshot_dir()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    filename = f"{timestamp}-{command}.json"
    path = directory / filename
    path.write_text(json.dumps(payload, indent=2, default=_json_default), encoding="utf-8")
    return path


def _notify_snapshot_location(path: Path) -> None:
    print(f"[breakeramp] Snapshot saved to {path}", file=sys.stderr)


def _resolve_output_format(preferred: Optional[str]) -> str:
    if preferred:
        return preferred
    return "summary" if sys.stdout.isatty() else "json"


def _render_breakeramp_plan_summary(resp: Dict[str, Any], snapshot_path: Path) -> None:
    manifest = resp.get("signed_manifest") or {}
    services = manifest.get("services") or {}
    service_names = list(services.keys())
    estimates = resp.get("environment_estimates") or {}
    modules: Dict[str, int] = {}
    for spec in services.values():
        module = spec.get("module") or "default"
        modules[module] = modules.get(module, 0) + 1

    print("BreakerAmp Plan ready")
    print(f"  Plan ID      : {resp.get('plan_id', 'unknown')}")
    print(f"  Run ID       : {resp.get('amp_run_id', 'unknown')}")
    if manifest.get("blueprint_id"):
        print(f"  Blueprint    : {manifest['blueprint_id']}")
    if service_names:
        print(f"  Services     : {len(service_names)} ({', '.join(service_names[:5])}{'…' if len(service_names) > 5 else ''})")
    if modules:
        module_parts = [f"{name}×{count}" for name, count in sorted(modules.items())]
        print(f"  Modules      : {', '.join(module_parts)}")
    if estimates:
        print("  Estimates    :")
        cost = estimates.get("cost_estimate")
        boot = estimates.get("expected_boot_duration_s")
        memory = estimates.get("memory_footprint_mb")
        bandwidth = estimates.get("bandwidth_mbps")
        print(f"    • Cost          : ${cost:.2f}" if isinstance(cost, (int, float)) else f"    • Cost          : {cost}")
        if memory is not None:
            print(f"    • Memory        : {memory} MB")
        if bandwidth is not None:
            print(f"    • Bandwidth     : {bandwidth} Mbps")
        if boot is not None:
            print(f"    • Boot Duration : {boot}s")
        if estimates.get("region"):
            print(f"    • Region        : {estimates['region']}")
    print(f"  Snapshot     : {snapshot_path}")


def _render_breakeramp_apply_summary(resp: Dict[str, Any], snapshot_path: Path, *, watched: bool) -> None:
    heading = "BreakerAmp Apply results" if watched else "BreakerAmp Apply requested"
    print(heading)
    print(f"  Run ID       : {resp.get('amp_run_id', 'unknown')}")
    if resp.get("action_id"):
        print(f"  Action ID    : {resp['action_id']}")
    outputs = resp.get("environment_outputs") or {}
    if outputs:
        keys = ", ".join(list(outputs.keys())[:5])
        print(f"  Env Outputs  : {keys}{'…' if len(outputs) > 5 else ''}")
    if resp.get("status_stream_url"):
        print(f"  Status Stream: {resp['status_stream_url']}")
    print(f"  Snapshot     : {snapshot_path}")


def _render_breakeramp_status_summary(status: Dict[str, Any], snapshot_path: Path, *, include_events: int = 0) -> None:
    print("BreakerAmp Status")
    print(f"  Run ID       : {status.get('amp_run_id', 'unknown')}")
    print(f"  Phase        : {status.get('phase', 'UNKNOWN')}")
    progress = status.get("progress_pct")
    if progress is not None:
        print(f"  Progress     : {progress}%")
    checks = status.get("checks") or []
    if checks:
        print("  Health Checks:")
        for check in checks:
            print(f"    • {check.get('name', 'unknown')}: {check.get('status', 'UNKNOWN')} (last probe {check.get('last_probe', 'n/a')})")
    telemetry = status.get("telemetry") or {}
    if telemetry:
        print("  Telemetry    :")
        for key, value in telemetry.items():
            print(f"    • {key.replace('_', ' ').title()}: {value}")
    if include_events:
        print(f"  Events       : {include_events} captured")
    if status.get("environment_outputs_path"):
        print(f"  Outputs File : {status['environment_outputs_path']}")
    print(f"  Snapshot     : {snapshot_path}")


def _render_breakeramp_destroy_summary(resp: Dict[str, Any], snapshot_path: Path) -> None:
    print("BreakerAmp Destroy")
    print(f"  Action ID    : {resp.get('action_id', 'unknown')}")
    report = resp.get("teardown_report") or []
    if report:
        print("  Resources    :")
        for line in report[:10]:
            print(f"    • {line}")
        if len(report) > 10:
            print(f"    • … {len(report) - 10} additional entries")
    print(f"  Snapshot     : {snapshot_path}")


def _render_breakeramp_event(event: Dict[str, Any]) -> None:
    timestamp = event.get("timestamp", "?")
    status = event.get("status", "UNKNOWN")
    message = event.get("message", "")
    print(f"[{timestamp}] {status:<12} {message}")
    details = event.get("details")
    if details:
        print(f"    {json.dumps(details, sort_keys=True, default=_json_default)}")


def _render_tasks_table(tasks: List[Dict[str, Any]]) -> None:
    if not tasks:
        print("No tasks matched the provided filters.")
        return

    headers = ["Task", "Milestone", "Function", "Agent"]
    widths = [len(header) for header in headers]
    rows: List[List[str]] = []

    for task in tasks:
        row = [
            task.get("title", "?"),
            task.get("milestone", "?"),
            task.get("function", "?"),
            task.get("primary_agent", "?"),
        ]
        rows.append(row)
        widths = [max(width, len(value)) for width, value in zip(widths, row)]

    fmt = " | ".join(f"{{:<{width}}}" for width in widths)
    separator = "-+-".join("-" * width for width in widths)
    print(fmt.format(*headers))
    print(separator)
    for row in rows:
        print(fmt.format(*row))


def _render_checklist_table(checklists: List[Dict[str, Any]]) -> None:
    if not checklists:
        print("No checklists found.")
        return

    headers = ["Checklist ID", "Title", "Milestone", "Coverage"]
    widths = [len(header) for header in headers]
    rows: List[List[str]] = []

    for checklist in checklists:
        row = [
            checklist["checklist_id"][:8],
            checklist["title"],
            checklist.get("milestone", "-"),
            f"{checklist['coverage_score']:.1%}",
        ]
        rows.append(row)
        widths = [max(width, len(value)) for width, value in zip(widths, row)]

    fmt = " | ".join(f"{{:<{width}}}" for width in widths)
    separator = "-+-".join("-" * width for width in widths)
    print(fmt.format(*headers))
    print(separator)
    for row in rows:
        print(fmt.format(*row))


def _render_step_table(steps: List[Dict[str, Any]]) -> None:
    if not steps:
        print("No steps found.")
        return

    headers = ["Step ID", "Title", "Status"]
    widths = [len(header) for header in headers]
    rows: List[List[str]] = []

    for step in steps:
        row = [
            step["step_id"][:8],
            step["title"],
            step["status"],
        ]
        rows.append(row)
        widths = [max(width, len(value)) for width, value in zip(widths, row)]

    fmt = " | ".join(f"{{:<{width}}}" for width in widths)
    separator = "-+-".join("-" * width for width in widths)
    print(fmt.format(*headers))
    print(separator)
    for row in rows:
        print(fmt.format(*row))


def _render_validation_table(result: Dict[str, Any]) -> None:
    headers = ["Checklist ID", "Valid", "Coverage", "Failed", "Missing"]
    row = [
        result["checklist_id"][:8],
        "✅" if result["valid"] else "❌",
        f"{result['coverage_score']:.1%}",
        str(len(result.get("failed_steps", []))),
        str(len(result.get("missing_steps", []))),
    ]
    widths = [max(len(header), len(value)) for header, value in zip(headers, row)]
    fmt = " | ".join(f"{{:<{width}}}" for width in widths)
    separator = "-+-".join("-" * width for width in widths)
    print(fmt.format(*headers))
    print(separator)
    print(fmt.format(*row))

    if result.get("warnings"):
        print("\nWarnings:")
        for warning in result["warnings"]:
            print(f"  - {warning}")
    if result.get("failed_steps"):
        print("\nFailed Steps:")
        for step in result["failed_steps"]:
            print(f"  - {step}")
    if result.get("missing_steps"):
        print("\nMissing Steps:")
        for step in result["missing_steps"]:
            print(f"  - {step}")


def _command_record_action(args: argparse.Namespace) -> int:
    adapter = _get_action_adapter()
    try:
        metadata = _load_metadata(args.metadata_items or [], args.metadata_file)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    action = adapter.record_action(
        artifact_path=args.artifact_path,
        summary=args.summary,
        behaviors_cited=args.behaviors,
        metadata=metadata,
        actor_id=args.actor_id,
        actor_role=args.actor_role,
        checksum=args.checksum,
        related_run_id=args.related_run_id,
        audit_log_event_id=args.audit_log_event_id,
    )

    if args.format == "table":
        _render_actions_table([action])
    else:
        _print_json(action)
    return 0


def _command_list_actions(args: argparse.Namespace) -> int:
    adapter = _get_action_adapter()
    actions = adapter.list_actions()
    if args.format == "table":
        _render_actions_table(actions)
    else:
        _print_json(actions)
    return 0


def _command_get_action(args: argparse.Namespace) -> int:
    adapter = _get_action_adapter()
    try:
        action = adapter.get_action(args.action_id)
    except Exception as exc:  # pragma: no cover - delegating to caller message
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.format == "table":
        _render_actions_table([action])
    else:
        _print_json(action)
    return 0


def _command_replay_actions(args: argparse.Namespace) -> int:
    adapter = _get_action_adapter()
    try:
        replay = adapter.replay_actions(
            action_ids=list(args.action_ids),
            actor_id=args.actor_id,
            actor_role=args.actor_role,
            strategy=args.strategy,
            skip_existing=args.skip_existing,
            dry_run=args.dry_run,
        )
    except Exception as exc:  # pragma: no cover - defensive guard
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_replay_table(replay)
    else:
        _print_json(replay)
    return 0


def _command_replay_status(args: argparse.Namespace) -> int:
    adapter = _get_action_adapter()
    try:
        replay = adapter.get_replay_status(args.replay_id)
    except Exception as exc:  # pragma: no cover - defensive guard
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_replay_table(replay)
    else:
        _print_json(replay)
    return 0


def _command_dr(args: argparse.Namespace) -> int:
    """Delegate 'amprealize dr' subcommands to the Click-based DR CLI."""

    try:
        from amprealize import cli_dr
    except ImportError as exc:  # pragma: no cover - import guard
        print(f"Error: DR commands unavailable ({exc})", file=sys.stderr)
        return 1

    forwarded_args = list(args.dr_args or [])

    try:
        result = cli_dr.dr_group.main(
            args=forwarded_args,
            prog_name="amprealize dr",
            standalone_mode=False,
        )
    except SystemExit as exc:  # Click uses SystemExit for return codes
        return int(exc.code or 0)
    except Exception as exc:  # pragma: no cover - defensive logging
        print(f"DR command failed: {exc}", file=sys.stderr)
        return 1

    return int(result or 0)


def _command_list_tasks(args: argparse.Namespace) -> int:
    adapter = _get_task_adapter()
    try:
        tasks = adapter.list_assignments(function=args.function)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if args.format == "table":
        _render_tasks_table(tasks)
    else:
        _print_json(tasks)
    return 0


def _command_telemetry_emit(args: argparse.Namespace) -> int:
    try:
        payload_raw = args.payload or "{}"
        payload_obj = json.loads(payload_raw)
        if not isinstance(payload_obj, dict):
            raise ValueError("Payload must be a JSON object")
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    surface = args.actor_surface.replace("-", "_").lower()
    actor = {
        "id": args.actor_id,
        "role": args.actor_role,
        "surface": surface,
    }

    # Determine sink based on --sink argument
    sink_type = getattr(args, "sink", "file")

    if sink_type == "kafka":
        # Kafka sink requires bootstrap servers
        kafka_servers = getattr(args, "kafka_servers", None) or os.environ.get("KAFKA_BOOTSTRAP_SERVERS")
        if not kafka_servers:
            print("Error: Kafka sink requires --kafka-servers or KAFKA_BOOTSTRAP_SERVERS environment variable", file=sys.stderr)
            return 2

        kafka_topic = os.environ.get("KAFKA_TOPIC_TELEMETRY_EVENTS", "telemetry.events")
        sink = KafkaTelemetrySink(bootstrap_servers=kafka_servers, topic=kafka_topic)
    else:
        # File sink
        telemetry_path = getattr(args, "telemetry_path", None)
        if telemetry_path:
            sink = FileTelemetrySink(path=Path(telemetry_path))
        else:
            # Use default from environment or in-memory fallback
            sink = create_sink_from_env()

    telemetry = TelemetryClient(sink=sink, default_actor=actor)

    event = telemetry.emit_event(
        event_type=args.event_type,
        payload=payload_obj,
        actor=actor,
        run_id=args.run_id,
        action_id=args.action_id,
        session_id=args.session_id,
    )

    # For file sink with custom path, output JSON for test validation
    if sink_type == "file" and getattr(args, "telemetry_path", None):
        print(json.dumps(event.to_dict(), indent=2))
    elif args.format == "json":
        print(json.dumps(event.to_dict(), indent=2))
    else:
        print(
            f"{event.timestamp} {event.event_type} actor={event.actor['id']} surface={event.actor['surface']}"
        )
    return 0


def _parse_relative_date(date_str: str) -> datetime:
    """Parse relative date strings like '7d', '24h', '30m' or ISO dates."""
    if not date_str:
        return datetime.now(timezone.utc)

    # Try relative format first (e.g., "7d", "24h", "30m")
    relative_pattern = r"^(\d+)([dhms])$"
    import re
    match = re.match(relative_pattern, date_str.lower())
    if match:
        value = int(match.group(1))
        unit = match.group(2)
        delta_map = {"d": timedelta(days=value), "h": timedelta(hours=value),
                     "m": timedelta(minutes=value), "s": timedelta(seconds=value)}
        return datetime.now(timezone.utc) - delta_map[unit]

    # Try ISO format
    try:
        # Handle date-only format
        if len(date_str) == 10:
            return datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"Invalid date format: {date_str}. Use ISO format or relative (e.g., 7d, 24h, 30m)")


def _command_telemetry_query(args: argparse.Namespace) -> int:
    """Query telemetry logs using RazeService."""
    try:
        from raze import RazeService
        from raze.sinks import InMemorySink
    except ImportError:
        # Try TimescaleDB sink if available
        try:
            from raze import RazeService
            from raze.sinks import TimescaleDBSink
        except ImportError:
            print("Error: Raze package not installed. Install with: pip install raze", file=sys.stderr)
            return 1

    # Parse date range
    try:
        start_time = _parse_relative_date(args.from_date) if args.from_date else datetime.now(timezone.utc) - timedelta(days=7)
        end_time = _parse_relative_date(args.to_date) if args.to_date else datetime.now(timezone.utc)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    # Build query params
    query_params = {
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "limit": args.limit,
        "offset": args.offset,
    }

    # Add optional filters
    if args.event_type:
        query_params["event_type"] = args.event_type
    if args.run_id:
        query_params["run_id"] = args.run_id
    if args.action_id:
        query_params["action_id"] = args.action_id
    if args.session_id:
        query_params["session_id"] = args.session_id
    if args.actor_surface:
        query_params["actor_surface"] = args.actor_surface.replace("-", "_").lower()
    if args.level:
        query_params["level"] = args.level.upper()
    if args.search:
        query_params["search"] = args.search

    # Initialize RazeService - try TimescaleDB first, fall back to file-based
    try:
        import os
        dsn = os.environ.get("RAZE_DSN") or os.environ.get("TIMESCALEDB_DSN")
        if dsn:
            from raze.sinks import TimescaleDBSink
            sink = TimescaleDBSink(dsn=dsn)
        else:
            # Fall back to JSONL file if available
            log_path = Path(os.environ.get("RAZE_LOG_PATH", ".amprealize/logs/raze.jsonl"))
            if log_path.exists():
                from raze.sinks import JSONLSink
                sink = JSONLSink(path=str(log_path))
            else:
                from raze.sinks import InMemorySink
                sink = InMemorySink()

        service = RazeService(sink=sink)
        result = service.query(**query_params)
        logs = result.logs if hasattr(result, 'logs') else result
    except Exception as exc:
        print(f"Error querying logs: {exc}", file=sys.stderr)
        return 1

    # Output results
    if args.format == "json":
        output = {
            "query": query_params,
            "count": len(logs) if isinstance(logs, list) else 0,
            "logs": [log.to_dict() if hasattr(log, 'to_dict') else log for log in logs] if logs else [],
        }
        print(json.dumps(output, indent=2, default=str))
    else:
        if not logs:
            print("No logs found matching query.")
            return 0

        print(f"\nTelemetry Logs ({len(logs)} results)")
        print("=" * 100)
        print(f"{'Timestamp':<25} {'Level':<8} {'Service':<15} {'Message':<50}")
        print("-" * 100)
        for log in logs[:args.limit]:
            log_dict = log.to_dict() if hasattr(log, 'to_dict') else log
            ts = str(log_dict.get('timestamp', 'N/A'))[:24]
            level = log_dict.get('level', 'INFO')[:7]
            service = log_dict.get('service', 'unknown')[:14]
            msg = log_dict.get('message', '')[:49]
            print(f"{ts:<25} {level:<8} {service:<15} {msg:<50}")

        if len(logs) > args.limit:
            print(f"\n... and {len(logs) - args.limit} more (use --limit to see more)")

    return 0


def _command_telemetry_dashboard(args: argparse.Namespace) -> int:
    """Display telemetry dashboard with KPIs and token accounting."""
    from .analytics.warehouse import AnalyticsWarehouse

    # Parse date range
    try:
        start_date = args.from_date if args.from_date else (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        end_date = args.to_date if args.to_date else datetime.now(timezone.utc).strftime("%Y-%m-%d")
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    def _fetch_and_display():
        """Fetch dashboard data and display it."""
        warehouse = AnalyticsWarehouse()

        # If specific run_id provided, show drill-down view
        if args.run_id:
            return _display_run_drilldown(warehouse, args.run_id, args.format)

        # Otherwise show summary dashboard
        try:
            kpi_summary = warehouse.get_kpi_summary(start_date=start_date, end_date=end_date)
            token_savings = warehouse.get_token_savings(start_date=start_date, end_date=end_date, limit=10)
            daily_costs = warehouse.get_daily_cost_summary(start_date=start_date, end_date=end_date)
        except Exception as exc:
            print(f"Error querying warehouse: {exc}", file=sys.stderr)
            return 1

        if args.format == "json":
            output = {
                "period": {"start": start_date, "end": end_date},
                "kpi_summary": kpi_summary,
                "token_savings": token_savings,
                "daily_costs": daily_costs,
            }
            print(json.dumps(output, indent=2, default=str))
        else:
            _display_dashboard_table(kpi_summary, token_savings, daily_costs, start_date, end_date)

        return 0

    # Watch mode with 5-second polling
    if args.watch:
        try:
            print("Dashboard watch mode (Ctrl+C to exit, refreshes every 5s)")
            print()
            while True:
                # Clear screen for fresh display
                print("\033[2J\033[H", end="")
                print(f"Last updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
                print()
                result = _fetch_and_display()
                if result != 0:
                    return result
                import time
                time.sleep(5)
        except KeyboardInterrupt:
            print("\nWatch mode stopped.")
            return 0
    else:
        return _fetch_and_display()


def _display_run_drilldown(warehouse, run_id: str, fmt: str) -> int:
    """Display detailed token accounting for a specific run."""
    try:
        # Get run-specific data
        token_data = warehouse.get_token_savings(run_id=run_id, limit=1)
        cost_data = warehouse.get_cost_per_run(run_id=run_id)
    except Exception as exc:
        print(f"Error querying run details: {exc}", file=sys.stderr)
        return 1

    if fmt == "json":
        output = {
            "run_id": run_id,
            "token_savings": token_data,
            "cost_breakdown": cost_data,
        }
        print(json.dumps(output, indent=2, default=str))
    else:
        print(f"\nRun Detail: {run_id}")
        print("=" * 80)

        if token_data:
            record = token_data[0] if token_data else {}
            print("\nToken Accounting")
            print("-" * 40)
            print(f"  Baseline Tokens:  {record.get('baseline_tokens', 0):>12,}")
            print(f"  Actual Tokens:    {record.get('actual_tokens', 0):>12,}")
            print(f"  Tokens Saved:     {record.get('tokens_saved', 0):>12,}")
            print(f"  Savings Rate:     {record.get('savings_rate_pct', 0):>11.1f}%")
        else:
            print("\nNo token data found for this run.")

        if cost_data:
            print("\nCost Breakdown")
            print("-" * 40)
            for item in cost_data:
                service = item.get('service', 'unknown')
                cost = item.get('cost_usd', 0)
                print(f"  {service:<20} ${cost:>10.4f}")
        else:
            print("\nNo cost data found for this run.")

    return 0


def _display_dashboard_table(kpi_summary, token_savings, daily_costs, start_date, end_date):
    """Display formatted dashboard tables."""
    print(f"\n📊 Telemetry Dashboard ({start_date} to {end_date})")
    print("=" * 80)

    # KPI Summary Section
    print("\n📈 KPI Summary")
    print("-" * 40)
    if kpi_summary:
        latest = kpi_summary[-1] if kpi_summary else {}
        print(f"  Behavior Reuse Rate:   {latest.get('reuse_rate_pct', 0):>6.1f}% (Target: 70%)")
        print(f"  Token Savings Rate:    {latest.get('avg_savings_rate_pct', 0):>6.1f}% (Target: 30%)")
        print(f"  Task Completion Rate:  {latest.get('completion_rate_pct', 0):>6.1f}% (Target: 80%)")
        print(f"  Compliance Coverage:   {latest.get('avg_coverage_rate_pct', 0):>6.1f}% (Target: 95%)")
    else:
        print("  No KPI data available for this period.")

    # Token Savings Section
    print("\n💰 Token Savings (Top 10 Runs)")
    print("-" * 70)
    if token_savings:
        print(f"  {'Run ID':<36} {'Saved':>12} {'Rate':>8}")
        print(f"  {'-'*36} {'-'*12} {'-'*8}")
        total_saved = 0
        for record in token_savings[:10]:
            run_id = record.get('run_id', 'N/A')[:35]
            saved = record.get('tokens_saved', 0)
            rate = record.get('savings_rate_pct', 0)
            total_saved += saved
            print(f"  {run_id:<36} {saved:>12,} {rate:>7.1f}%")
        print(f"  {'Total':<36} {total_saved:>12,}")
    else:
        print("  No token savings data available for this period.")

    # Daily Costs Section
    print("\n📅 Daily Cost Summary")
    print("-" * 50)
    if daily_costs:
        print(f"  {'Date':<12} {'Runs':>8} {'Cost (USD)':>12}")
        print(f"  {'-'*12} {'-'*8} {'-'*12}")
        total_cost = 0
        for record in daily_costs:
            day = record.get('summary_date', 'N/A')[:10]
            runs = record.get('total_runs', 0)
            cost = record.get('total_cost_usd', 0)
            total_cost += cost
            print(f"  {day:<12} {runs:>8} ${cost:>11.2f}")
        print(f"  {'Total':<12} {'':<8} ${total_cost:>11.2f}")
    else:
        print("  No cost data available for this period.")

    print()


def _load_telemetry_events(path: Path) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for index, line in enumerate(handle, start=1):
            raw = line.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {index}: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"Event on line {index} must be a JSON object")
            events.append(payload)
    return events


def _projection_to_dict(projection: TelemetryProjection) -> Dict[str, Any]:
    return {
        "summary": projection.summary,
        "fact_behavior_usage": projection.fact_behavior_usage,
        "fact_token_savings": projection.fact_token_savings,
        "fact_execution_status": projection.fact_execution_status,
        "fact_compliance_steps": projection.fact_compliance_steps,
    }


def _render_projection_table(projection: TelemetryProjection) -> None:
    summary = projection.summary or {}

    def _fmt(value: Any) -> str:
        if value is None:
            return "-"
        if isinstance(value, float):
            return f"{value:.2f}"
        return str(value)

    rows = [
        ("Total runs", summary.get("total_runs")),
        ("Runs with behaviors", summary.get("runs_with_behaviors")),
        ("Behavior reuse %", summary.get("behavior_reuse_pct")),
        ("Average token savings %", summary.get("average_token_savings_pct")),
        ("Completed runs", summary.get("completed_runs")),
        ("Terminal runs", summary.get("terminal_runs")),
        ("Task completion rate %", summary.get("task_completion_rate_pct")),
        ("Compliance coverage %", summary.get("average_compliance_coverage_pct")),
    ]

    label_width = max(len(label) for label, _ in rows)
    print("PRD KPI Summary")
    print("-" * (label_width + 20))
    for label, value in rows:
        print(f"{label:<{label_width}} : {_fmt(value)}")

    fact_rows = [
        ("fact_behavior_usage", len(projection.fact_behavior_usage)),
        ("fact_token_savings", len(projection.fact_token_savings)),
        ("fact_execution_status", len(projection.fact_execution_status)),
        ("fact_compliance_steps", len(projection.fact_compliance_steps)),
    ]

    fact_width = max(len(label) for label, _ in fact_rows)
    print()
    print("Fact row counts")
    print("-" * (fact_width + 12))
    for label, count in fact_rows:
        print(f"{label:<{fact_width}} : {count}")


# ── Agents command handlers ─────────────────────────────────────────────────────

_agent_orchestrator_service: Optional[AgentOrchestratorService] = None


def _get_agent_orchestrator_adapter() -> CLIAgentOrchestratorAdapter:
    """Get or create an AgentOrchestratorService adapter."""
    global _agent_orchestrator_service
    if _agent_orchestrator_service is None:
        _agent_orchestrator_service = AgentOrchestratorService()
    return CLIAgentOrchestratorAdapter(_agent_orchestrator_service)


def _command_agents_assign(args: argparse.Namespace) -> int:
    """Assign an agent to a run."""
    adapter = _get_agent_orchestrator_adapter()

    # Parse context from --context or --context-file
    context: Optional[Dict[str, Any]] = None
    if args.context:
        try:
            context = json.loads(args.context)
        except json.JSONDecodeError as exc:
            print(f"Error: Invalid JSON in --context: {exc}", file=sys.stderr)
            return 1
    elif args.context_file:
        context_path = Path(args.context_file).expanduser().resolve()
        if not context_path.exists():
            print(f"Error: Context file not found: {context_path}", file=sys.stderr)
            return 1
        try:
            context = json.loads(context_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"Error: Invalid JSON in context file: {exc}", file=sys.stderr)
            return 1

    requested_by = {
        "actor_id": "cli-user",
        "actor_role": "STRATEGIST",
        "actor_surface": "cli",
    }

    try:
        result = adapter.assign_agent(
            run_id=args.run_id,
            requested_agent_id=getattr(args, "agent_id", None),
            stage=args.stage,
            context=context,
            requested_by=requested_by,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        _render_agent_assignment_table(result)
    return 0


def _command_agents_status(args: argparse.Namespace) -> int:
    """Get status of an agent assignment."""
    if not args.run_id and not args.assignment_id:
        print("Error: Provide --assignment-id or --run-id to lookup status", file=sys.stderr)
        return 2

    adapter = _get_agent_orchestrator_adapter()

    try:
        result = adapter.get_status(
            run_id=args.run_id,
            assignment_id=args.assignment_id,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if result is None:
        print("Error: Assignment not found", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        _render_agent_assignment_table(result)
    return 0


def _command_agents_switch(args: argparse.Namespace) -> int:
    """Switch to a different agent."""
    adapter = _get_agent_orchestrator_adapter()

    issued_by = {
        "actor_id": "cli-user",
        "actor_role": "STRATEGIST",
        "actor_surface": "cli",
    }

    try:
        result = adapter.switch_agent(
            assignment_id=args.assignment_id,
            target_agent_id=args.target_agent_id,
            reason=getattr(args, "reason", None),
            allow_downgrade=getattr(args, "allow_downgrade", False),
            stage=getattr(args, "stage", None),
            issued_by=issued_by,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        _render_agent_assignment_table(result)
    return 0


def _render_agent_assignment_table(assignment: Dict[str, Any]) -> None:
    """Render an agent assignment as a formatted table."""
    print("\n📋 Agent Assignment")
    print("=" * 60)
    print(f"  Assignment ID:  {assignment.get('assignment_id', 'N/A')}")
    print(f"  Run ID:         {assignment.get('run_id', 'N/A')}")
    print(f"  Stage:          {assignment.get('stage', 'N/A')}")
    print(f"  Timestamp:      {assignment.get('timestamp', 'N/A')}")

    active_agent = assignment.get("active_agent", {})
    print(f"\n🤖 Active Agent")
    print("-" * 60)
    print(f"  Agent ID:       {active_agent.get('agent_id', 'N/A')}")
    print(f"  Display Name:   {active_agent.get('display_name', 'N/A')}")
    print(f"  Tier:           {active_agent.get('tier', 'N/A')}")

    heuristics = assignment.get("heuristics_applied", {})
    if heuristics:
        print(f"\n📊 Heuristics Applied")
        print("-" * 60)
        print(f"  Selected Agent: {heuristics.get('selected_agent_id', 'N/A')}")
        print(f"  Requested:      {heuristics.get('requested_agent_id', 'N/A')}")
        print(f"  Task Type:      {heuristics.get('task_type', 'N/A')}")
        print(f"  Severity:       {heuristics.get('severity', 'N/A')}")

    history = assignment.get("history", [])
    if history:
        print(f"\n📜 History ({len(history)} event(s))")
        print("-" * 60)
        for event in history:
            print(f"  • {event.get('from_agent_id', 'N/A')} → {event.get('to_agent_id', 'N/A')}")
            print(f"    Trigger: {event.get('trigger', 'N/A')}")
            trigger_details = event.get("trigger_details", {})
            if trigger_details.get("reason"):
                print(f"    Reason: {trigger_details.get('reason')}")
    print()


def _command_analytics_project(args: argparse.Namespace) -> int:
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        print(f"Error: Telemetry input not found: {input_path}", file=sys.stderr)
        return 2

    try:
        events = _load_telemetry_events(input_path)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    projector = TelemetryKPIProjector()
    projection = projector.project(events)

    if args.facts_output:
        output_path = Path(args.facts_output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(_projection_to_dict(projection), indent=2)
        output_path.write_text(payload, encoding="utf-8")
        print(f"Projection JSON written to {output_path}", file=sys.stderr)

    if args.format == "json":
        print(json.dumps(_projection_to_dict(projection), indent=2))
    else:
        _render_projection_table(projection)
    return 0


def _command_analytics_kpi_summary(args: argparse.Namespace) -> int:
    """Query KPI summary from DuckDB analytics warehouse."""
    from .analytics.warehouse import AnalyticsWarehouse

    warehouse = AnalyticsWarehouse()
    try:
        records = warehouse.get_kpi_summary(
            start_date=args.start_date,
            end_date=args.end_date,
        )
    except Exception as exc:
        print(f"Error querying warehouse: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps({"records": records, "count": len(records)}, indent=2))
    else:
        if not records:
            print("No KPI summary records found.")
            return 0

        print("\nKPI Summary")
        print("=" * 80)
        for record in records:
            print(f"Period: {record.get('summary_date', 'N/A')}")
            print(f"  Behavior Reuse Rate: {record.get('reuse_rate_pct', 0):.1f}% (Target: 70%)")
            print(f"  Token Savings Rate: {record.get('avg_savings_rate_pct', 0):.1f}% (Target: 30%)")
            print(f"  Task Completion Rate: {record.get('completion_rate_pct', 0):.1f}% (Target: 80%)")
            print(f"  Compliance Coverage: {record.get('avg_coverage_rate_pct', 0):.1f}% (Target: 95%)")
            print()
    return 0


def _command_analytics_project_kpi(args: argparse.Namespace) -> int:
    """Project telemetry events from JSONL file into KPI facts and summary."""
    import dataclasses
    from pathlib import Path

    from .analytics.telemetry_kpi_projector import TelemetryKPIProjector

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"Telemetry input not found: {input_path}", file=sys.stderr)
        return 2

    # Parse JSONL events
    events: list[dict] = []
    with input_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))

    # Project events to facts
    projector = TelemetryKPIProjector()
    projection = projector.project(events)

    # Convert projection to dict for serialization
    projection_dict = dataclasses.asdict(projection)

    # Write facts output if requested
    if args.facts_output:
        facts_path = Path(args.facts_output)
        facts_path.write_text(json.dumps(projection_dict, indent=2), encoding="utf-8")
        print(f"Projection JSON written to {facts_path}", file=sys.stderr)

    # Output format
    if args.format == "json":
        print(json.dumps(projection_dict, indent=2))
    else:
        summary = projection.summary
        print("\nPRD KPI Summary")
        print("=" * 80)
        print(f"  Total Runs: {summary.get('total_runs', 0)}")
        print(f"  Runs with Behaviors: {summary.get('runs_with_behaviors', 0)}")
        reuse_pct = summary.get('behavior_reuse_pct')
        print(f"  Behavior Reuse Rate: {reuse_pct:.1f}% (Target: 70%)" if reuse_pct is not None else "  Behavior Reuse Rate: N/A")
        savings_pct = summary.get('average_token_savings_pct')
        print(f"  Average Token Savings: {savings_pct:.1f}% (Target: 30%)" if savings_pct is not None else "  Average Token Savings: N/A")
        completion_pct = summary.get('task_completion_rate_pct')
        print(f"  Task Completion Rate: {completion_pct:.1f}% (Target: 80%)" if completion_pct is not None else "  Task Completion Rate: N/A")
        coverage_pct = summary.get('average_compliance_coverage_pct')
        print(f"  Compliance Coverage: {coverage_pct:.1f}% (Target: 95%)" if coverage_pct is not None else "  Compliance Coverage: N/A")
        print()
        print("Fact row counts:")
        print(f"  fact_behavior_usage: {len(projection.fact_behavior_usage)}")
        print(f"  fact_token_savings: {len(projection.fact_token_savings)}")
        print(f"  fact_execution_status: {len(projection.fact_execution_status)}")
        print(f"  fact_compliance_steps: {len(projection.fact_compliance_steps)}")
        print(f"  fact_resource_usage: {len(projection.fact_resource_usage)}")
        print(f"  fact_cost_allocation: {len(projection.fact_cost_allocation)}")

    return 0


def _command_analytics_behavior_usage(args: argparse.Namespace) -> int:
    """Query behavior usage facts from analytics warehouse."""
    from .analytics.warehouse import AnalyticsWarehouse

    warehouse = AnalyticsWarehouse()
    try:
        records = warehouse.get_behavior_usage(
            start_date=args.start_date,
            end_date=args.end_date,
            limit=args.limit,
        )
    except Exception as exc:
        print(f"Error querying warehouse: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps({"records": records, "count": len(records)}, indent=2))
    else:
        if not records:
            print("No behavior usage records found.")
            return 0

        print(f"\nBehavior Usage (Top {len(records)})")
        print("=" * 80)
        print(f"{'Run ID':<40} {'Behaviors':>10} {'Timestamp':<20}")
        print("-" * 80)
        for record in records:
            run_id = record.get('run_id', 'N/A')[:38]
            behavior_count = record.get('behavior_count', 0)
            timestamp = record.get('timestamp', 'N/A')[:19]
            print(f"{run_id:<40} {behavior_count:>10} {timestamp:<20}")
        print(f"\nTotal: {len(records)} record(s)")
    return 0


def _command_analytics_token_savings(args: argparse.Namespace) -> int:
    """Query token savings facts from analytics warehouse."""
    from .analytics.warehouse import AnalyticsWarehouse

    warehouse = AnalyticsWarehouse()
    try:
        records = warehouse.get_token_savings(
            start_date=args.start_date,
            end_date=args.end_date,
            limit=args.limit,
        )
    except Exception as exc:
        print(f"Error querying warehouse: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps({"records": records, "count": len(records)}, indent=2))
    else:
        if not records:
            print("No token savings records found.")
            return 0

        print(f"\nToken Savings (Top {len(records)})")
        print("=" * 80)
        print(f"{'Run ID':<40} {'Savings %':>12} {'Tokens Saved':>15}")
        print("-" * 80)
        for record in records:
            run_id = record.get('run_id', 'N/A')[:38]
            savings_pct = record.get('savings_rate_pct', 0)
            tokens_saved = record.get('tokens_saved', 0)
            print(f"{run_id:<40} {savings_pct:>11.1f}% {tokens_saved:>15,}")
        print(f"\nTotal: {len(records)} record(s)")
    return 0


def _command_analytics_compliance_coverage(args: argparse.Namespace) -> int:
    """Query compliance coverage facts from analytics warehouse."""
    from .analytics.warehouse import AnalyticsWarehouse

    warehouse = AnalyticsWarehouse()
    try:
        records = warehouse.get_compliance_coverage(
            start_date=args.start_date,
            end_date=args.end_date,
            limit=args.limit,
        )
    except Exception as exc:
        print(f"Error querying warehouse: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps({"records": records, "count": len(records)}, indent=2))
    else:
        if not records:
            print("No compliance coverage records found.")
            return 0

        print(f"\nCompliance Coverage (Top {len(records)})")
        print("=" * 80)
        print(f"{'Checklist ID':<40} {'Coverage %':>12} {'Steps Done/Total':<20}")
        print("-" * 80)
        for record in records:
            checklist_id = record.get('checklist_id', 'N/A')[:38]
            coverage_pct = record.get('coverage_rate_pct', 0)
            steps_completed = record.get('steps_completed', 0)
            steps_total = record.get('steps_total', 0)
            print(f"{checklist_id:<40} {coverage_pct:>11.1f}% {steps_completed}/{steps_total:<15}")
        print(f"\nTotal: {len(records)} record(s)")
    return 0


def _command_analytics_cost_by_service(args: argparse.Namespace) -> int:
    """Query cost breakdown by service from analytics warehouse."""
    from .analytics.warehouse import AnalyticsWarehouse

    warehouse = AnalyticsWarehouse()
    try:
        records = warehouse.get_cost_by_service(
            start_date=args.start_date,
            end_date=args.end_date,
            service_name=getattr(args, 'service_name', None),
        )
    except Exception as exc:
        print(f"Error querying warehouse: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps({"records": records, "count": len(records)}, indent=2))
    else:
        if not records:
            print("No cost records found.")
            return 0

        print("\nCost by Service")
        print("=" * 80)
        print(f"{'Service':<30} {'Total Cost':>15} {'Total Tokens':>15} {'Avg Cost/Run':>15}")
        print("-" * 80)
        total_cost = 0.0
        for record in records:
            service = record.get('service_name', 'N/A')[:28]
            cost = record.get('total_cost_usd', 0)
            tokens = record.get('total_tokens', 0)
            avg_cost = record.get('avg_cost_per_run', 0)
            total_cost += cost
            print(f"{service:<30} ${cost:>14.4f} {tokens:>15,} ${avg_cost:>14.4f}")
        print("-" * 80)
        print(f"{'TOTAL':<30} ${total_cost:>14.4f}")
    return 0


def _command_analytics_cost_per_run(args: argparse.Namespace) -> int:
    """Query cost breakdown per run from analytics warehouse."""
    from .analytics.warehouse import AnalyticsWarehouse

    warehouse = AnalyticsWarehouse()
    try:
        records = warehouse.get_cost_per_run(
            start_date=args.start_date,
            end_date=args.end_date,
            template_id=getattr(args, 'template_id', None),
            limit=args.limit,
        )
    except Exception as exc:
        print(f"Error querying warehouse: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps({"records": records, "count": len(records)}, indent=2))
    else:
        if not records:
            print("No cost records found.")
            return 0

        print(f"\nCost per Run (Top {len(records)})")
        print("=" * 100)
        print(f"{'Run ID':<38} {'Template':<25} {'Cost':>12} {'Tokens':>12} {'Started':<15}")
        print("-" * 100)
        for record in records:
            run_id = record.get('run_id', 'N/A')[:36]
            template = (record.get('template_id') or 'N/A')[:23]
            cost = record.get('total_cost_usd', 0)
            tokens = record.get('total_tokens', 0)
            started = (record.get('started_at') or 'N/A')[:13]
            print(f"{run_id:<38} {template:<25} ${cost:>11.4f} {tokens:>12,} {started:<15}")
        print(f"\nTotal: {len(records)} record(s)")
    return 0


def _command_analytics_roi_summary(args: argparse.Namespace) -> int:
    """Query ROI analysis summary from analytics warehouse."""
    from .analytics.warehouse import AnalyticsWarehouse
    from .config import get_settings

    settings = get_settings()
    warehouse = AnalyticsWarehouse()
    try:
        record = warehouse.get_roi_summary()
    except Exception as exc:
        print(f"Error querying warehouse: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps({"roi": record, "budget_threshold_usd": settings.cost.daily_budget_usd}, indent=2))
    else:
        if not record:
            print("No ROI data available.")
            return 0

        print("\nROI Analysis Summary")
        print("=" * 60)
        total_cost = record.get('total_cost_usd', 0)
        total_saved = record.get('total_tokens_saved', 0)
        cost_per_save = record.get('cost_per_token_saved', 0)
        efficiency = record.get('efficiency_score', 0)
        budget = settings.cost.daily_budget_usd

        print(f"  Total Cost (USD):        ${total_cost:,.4f}")
        print(f"  Total Tokens Saved:      {total_saved:,}")
        print(f"  Cost per Token Saved:    ${cost_per_save:.6f}")
        print(f"  Efficiency Score:        {efficiency:.2f}")
        print(f"  Daily Budget Threshold:  ${budget:.2f}")
        print()

        # Budget status indicator
        if total_cost > budget:
            print(f"  ⚠️  OVER BUDGET by ${total_cost - budget:.2f}")
        else:
            print(f"  ✅ Within budget (${budget - total_cost:.2f} remaining)")
    return 0


def _command_analytics_daily_costs(args: argparse.Namespace) -> int:
    """Query daily cost summary for budget tracking."""
    from .analytics.warehouse import AnalyticsWarehouse
    from .config import get_settings

    settings = get_settings()
    warehouse = AnalyticsWarehouse()
    try:
        records = warehouse.get_daily_cost_summary(
            start_date=args.start_date,
            end_date=args.end_date,
            limit=args.limit,
        )
    except Exception as exc:
        print(f"Error querying warehouse: {exc}", file=sys.stderr)
        return 1

    budget = settings.cost.daily_budget_usd

    if args.format == "json":
        print(json.dumps({
            "records": records,
            "count": len(records),
            "budget_threshold_usd": budget
        }, indent=2))
    else:
        if not records:
            print("No daily cost records found.")
            return 0

        print(f"\nDaily Cost Summary (Budget: ${budget:.2f}/day)")
        print("=" * 80)
        print(f"{'Date':<12} {'Daily Cost':>12} {'Total Tokens':>15} {'Runs':>8} {'Status':<10}")
        print("-" * 80)
        for record in records:
            date = str(record.get('cost_date', 'N/A'))[:10]
            cost = record.get('daily_cost_usd', 0)
            tokens = record.get('daily_tokens', 0)
            runs = record.get('run_count', 0)
            status = "⚠️ OVER" if cost > budget else "✅ OK"
            print(f"{date:<12} ${cost:>11.4f} {tokens:>15,} {runs:>8} {status:<10}")
        print(f"\nTotal: {len(records)} day(s)")
    return 0


def _command_analytics_top_expensive(args: argparse.Namespace) -> int:
    """Query top expensive workflows from analytics warehouse."""
    from .analytics.warehouse import AnalyticsWarehouse

    warehouse = AnalyticsWarehouse()
    try:
        records = warehouse.get_top_expensive_workflows(limit=args.limit)
    except Exception as exc:
        print(f"Error querying warehouse: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps({"records": records, "count": len(records)}, indent=2))
    else:
        if not records:
            print("No workflow cost records found.")
            return 0

        print(f"\nTop {len(records)} Expensive Workflows")
        print("=" * 90)
        print(f"{'Template ID':<35} {'Total Cost':>12} {'Total Tokens':>15} {'Avg Cost/Run':>15}")
        print("-" * 90)
        for record in records:
            template = (record.get('template_id') or 'ad-hoc')[:33]
            cost = record.get('total_cost_usd', 0)
            tokens = record.get('total_tokens', 0)
            avg = record.get('avg_cost_per_run', 0)
            print(f"{template:<35} ${cost:>11.4f} {tokens:>15,} ${avg:>14.4f}")
        print(f"\nTotal: {len(records)} workflow(s)")
    return 0


def _command_metrics_summary(args: argparse.Namespace) -> int:
    """Display real-time metrics summary with PRD KPI targets."""
    adapter = _get_metrics_adapter()



    use_cache = not args.no_cache
    try:
        result = adapter.get_summary(
            start_date=args.start_date,
            end_date=args.end_date,
            use_cache=use_cache,
        )
    except Exception as exc:
        print(f"Error retrieving metrics summary: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        _render_metrics_summary_table(result)
    return 0


def _command_metrics_export(args: argparse.Namespace) -> int:
    """Export metrics data to file or stdout."""
    adapter = _get_metrics_adapter()

    try:
        result = adapter.export_metrics(
            format=args.export_format,
            start_date=args.start_date,
            end_date=args.end_date,
            metrics=args.metrics if args.metrics else None,
            include_raw_events=args.include_raw_events,
        )
    except Exception as exc:
        print(f"Error exporting metrics: {exc}", file=sys.stderr)
        return 1

    # Write exported data to file or stdout
    if args.output_file:
        output_path = Path(args.output_file).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if result.get("data"):
            # Inline data export
            if args.export_format == "json":
                output_path.write_text(json.dumps(result["data"], indent=2), encoding="utf-8")
            elif args.export_format == "csv":
                output_path.write_text(result["data"], encoding="utf-8")
            print(f"Exported {result.get('row_count', 0)} rows to {output_path}", file=sys.stderr)
        elif result.get("file_path"):
            # File-based export
            print(f"Export available at: {result['file_path']}", file=sys.stderr)
    else:
        # stdout export
        if result.get("data"):
            if args.export_format == "json":
                print(json.dumps(result["data"], indent=2))
            else:
                print(result["data"])

    # Display export metadata
    if args.output_format == "json":
        print(json.dumps(result, indent=2), file=sys.stderr if args.output_file else sys.stdout)
    else:
        if not args.output_file:
            print("=" * 60)
        print(f"Export ID         : {result.get('export_id', 'N/A')}", file=sys.stderr if args.output_file else sys.stdout)
        print(f"Rows              : {result.get('row_count', 0)}", file=sys.stderr if args.output_file else sys.stdout)
        print(f"Size (bytes)      : {result.get('size_bytes', 0)}", file=sys.stderr if args.output_file else sys.stdout)
    return 0


def _render_metrics_summary_table(summary: Dict[str, Any]) -> None:
    """Render metrics summary in table format with PRD targets."""
    print("Amprealize Metrics Summary")
    print("=" * 80)
    print(f"Snapshot Time     : {summary.get('snapshot_time', 'N/A')}")
    print(f"Cache Status      : {'HIT' if summary.get('cache_hit') else 'MISS'}")
    if summary.get("cache_age_seconds") is not None:
        print(f"Cache Age         : {summary['cache_age_seconds']}s")
    print()

    # PRD KPI Metrics with targets
    print("PRD Key Performance Indicators")
    print("-" * 80)

    kpis = [
        ("Behavior Reuse Rate", summary.get("behavior_reuse_pct", 0.0), 70.0),
        ("Token Savings Rate", summary.get("average_token_savings_pct", 0.0), 30.0),
        ("Task Completion Rate", summary.get("task_completion_rate_pct", 0.0), 80.0),
        ("Compliance Coverage", summary.get("average_compliance_coverage_pct", 0.0), 95.0),
    ]

    for metric_name, actual, target in kpis:
        status = "✓" if actual >= target else "✗"
        print(f"{metric_name:30} : {actual:6.2f}% (target: {target:6.2f}%) {status}")

    print()
    print("Activity Counters")
    print("-" * 80)
    print(f"Total Behaviors   : {summary.get('total_behaviors', 0)}")
    print(f"Active Runs       : {summary.get('active_runs', 0)}")
    print(f"Completed Runs    : {summary.get('completed_runs', 0)}")
    print(f"Failed Runs       : {summary.get('failed_runs', 0)}")
    print(f"Total Actions     : {summary.get('total_actions', 0)}")
    print(f"Compliance Checks : {summary.get('compliance_checks', 0)}")
    print(f"Telemetry Events  : {summary.get('telemetry_events', 0)}")


# =============================================================================
# AgentAuth CLI Commands
# =============================================================================


def _command_auth_ensure_grant(args: argparse.Namespace) -> int:
    """Handle 'amprealize auth ensure-grant' command."""
    adapter = _get_agent_auth_adapter()

    # Parse context key=value pairs
    context = {}
    if args.context:
        for ctx_pair in args.context:
            if "=" in ctx_pair:
                key, value = ctx_pair.split("=", 1)
                context[key] = value

    result = adapter.ensure_grant(
        agent_id=args.agent_id,
        tool_name=args.tool_name,
        scopes=args.scopes,
        user_id=args.user_id,
        context=context if context else None,
    )

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print("AgentAuth Grant Request")
        print("=" * 80)
        print(f"Decision          : {result['decision']}")
        if "reason" in result:
            print(f"Reason            : {result['reason']}")
        if "consent_url" in result:
            print(f"\nConsent Required:")
            print(f"  URL             : {result['consent_url']}")
            print(f"  Request ID      : {result['consent_request_id']}")
        if "grant" in result:
            grant = result["grant"]
            print(f"\nGrant Details:")
            print(f"  Grant ID        : {grant['grant_id']}")
            print(f"  Agent ID        : {grant['agent_id']}")
            print(f"  Tool Name       : {grant['tool_name']}")
            print(f"  Scopes          : {', '.join(grant['scopes'])}")
            print(f"  Expires         : {grant['expires_at']}")
            print(f"  Provider        : {grant['provider']}")
            if grant.get("obligations"):
                print(f"  Obligations     : {len(grant['obligations'])} obligation(s)")
        if "audit_action_id" in result:
            print(f"\nAudit Action ID   : {result['audit_action_id']}")

    return 0


def _command_auth_list_grants(args: argparse.Namespace) -> int:
    """Handle 'amprealize auth list-grants' command."""
    adapter = _get_agent_auth_adapter()

    grants = adapter.list_grants(
        agent_id=args.agent_id,
        user_id=args.user_id,
        tool_name=args.tool_name,
        include_expired=args.include_expired,
    )

    if args.format == "json":
        print(json.dumps(grants, indent=2))
    else:
        if not grants:
            print("No grants found.")
            return 0

        print(f"AgentAuth Grants ({len(grants)} found)")
        print("=" * 80)
        for i, grant in enumerate(grants, 1):
            print(f"\n{i}. Grant ID: {grant['grant_id']}")
            print(f"   Agent       : {grant['agent_id']}")
            if grant.get("user_id"):
                print(f"   User        : {grant['user_id']}")
            print(f"   Tool        : {grant['tool_name']}")
            print(f"   Scopes      : {', '.join(grant['scopes'])}")
            print(f"   Issued      : {grant['issued_at']}")
            print(f"   Expires     : {grant['expires_at']}")
            print(f"   Provider    : {grant['provider']}")
            if grant.get("obligations"):
                print(f"   Obligations : {len(grant['obligations'])} obligation(s)")

    return 0


def _command_auth_policy_preview(args: argparse.Namespace) -> int:
    """Handle 'amprealize auth policy-preview' command."""
    adapter = _get_agent_auth_adapter()

    # Parse context key=value pairs
    context = {}
    if args.context:
        for ctx_pair in args.context:
            if "=" in ctx_pair:
                key, value = ctx_pair.split("=", 1)
                context[key] = value

    result = adapter.policy_preview(
        agent_id=args.agent_id,
        tool_name=args.tool_name,
        scopes=args.scopes,
        user_id=args.user_id,
        context=context if context else None,
    )

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print("AgentAuth Policy Preview")
        print("=" * 80)
        print(f"Decision          : {result['decision']}")
        if "reason" in result:
            print(f"Reason            : {result['reason']}")
        if "bundle_version" in result:
            print(f"Bundle Version    : {result['bundle_version']}")
        if "obligations" in result and result["obligations"]:
            print(f"\nObligations ({len(result['obligations'])}):")
            for obl in result["obligations"]:
                attrs_str = ", ".join(f"{k}={v}" for k, v in obl['attributes'].items())
                print(f"  - {obl['type']}: {attrs_str}")

    return 0


def _command_auth_revoke(args: argparse.Namespace) -> int:
    """Handle 'amprealize auth revoke' command."""
    adapter = _get_agent_auth_adapter()

    result = adapter.revoke_grant(
        grant_id=args.grant_id,
        revoked_by=args.revoked_by,
        reason=args.reason,
    )

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print("AgentAuth Grant Revocation")
        print("=" * 80)
        print(f"Grant ID          : {result['grant_id']}")
        print(f"Success           : {'✓ Yes' if result['success'] else '✗ No'}")
        if "reason" in result:
            print(f"Reason            : {result['reason']}")

    return 0


# ==============================================================================
# DEPRECATED: Internal Auth Functions (Kept for backward compatibility)
# These functions are deprecated as of 2026-01-09. Use OAuth instead.
# ==============================================================================


def _get_internal_auth_api_url() -> str:
    """[DEPRECATED] Get the internal auth API base URL."""
    return os.getenv("AMPREALIZE_GATEWAY_URL", "http://localhost:8080")


def _internal_auth_register(
    username: str,
    password: str,
    email: Optional[str] = None,
    api_url: Optional[str] = None,
) -> Dict[str, Any]:
    """[DEPRECATED] Register a user with the internal auth API.

    This function is deprecated. Use OAuth authentication instead.
    """
    raise ValueError(
        "Internal authentication has been deprecated. "
        "Please use OAuth authentication via --provider=github or --provider=google"
    )


def _internal_auth_login(
    username: str,
    password: str,
    api_url: Optional[str] = None,
) -> Dict[str, Any]:
    """[DEPRECATED] Login a user with the internal auth API.

    This function is deprecated. Use OAuth authentication instead.
    """
    raise ValueError(
        "Internal authentication has been deprecated. "
        "Please use OAuth authentication via --provider=github or --provider=google"
    )


def _save_internal_tokens(
    tokens: Dict[str, Any],
    allow_plaintext: bool = False,
) -> Path:
    """[DEPRECATED] Save internal auth tokens to provider-specific file.

    This function is deprecated. Use OAuth authentication instead.
    """
    raise ValueError(
        "Internal authentication has been deprecated. "
        "Please use OAuth authentication via --provider=github or --provider=google"
    )


def _command_auth_register(args: argparse.Namespace) -> int:
    """[DEPRECATED] Register a new user with internal authentication.

    Internal authentication (username/password) has been deprecated.
    Please use OAuth authentication instead.
    """
    print("Error: Internal user registration has been deprecated.", file=sys.stderr)
    print("", file=sys.stderr)
    print("Please use OAuth authentication instead:", file=sys.stderr)
    print("  amprealize auth login --provider=github", file=sys.stderr)
    print("  amprealize auth login --provider=google", file=sys.stderr)
    return 1


def _command_auth_login(args: argparse.Namespace) -> int:
    """Perform login and cache issued tokens.

    Uses OAuth device flow with github or google providers.
    Internal auth (username/password) has been deprecated.
    """
    # Check provider - internal auth is deprecated
    provider = getattr(args, "provider", "github")
    if provider == "internal":
        return _command_auth_login_internal(args)

    # Device flow for github/google
    manager = _get_device_flow_manager()
    try:
        store = _get_token_store(allow_plaintext=args.allow_plaintext)
    except TokenStoreError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    scopes = args.scopes or ["actions.read"]
    metadata = {
        "hostname": platform.node(),
        "platform": sys.platform,
        "shell": os.environ.get("SHELL", "unknown"),
        "term": os.environ.get("TERM", "unknown"),
    }

    try:
        session = manager.start_authorization(
            client_id=args.client_id,
            scopes=scopes,
            surface="CLI",
            metadata=metadata,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Amprealize Device Authorization")
    print("=" * 80)
    print(f"Requested Scopes  : {', '.join(scopes)}")
    print(f"Verification URL  : {session.verification_uri}")
    print(f"User Code         : {session.user_code}")
    print(f"Expires In        : {session.expires_in()}s")
    print("\nVisit the URL above and enter the code to approve access.")

    if args.open_browser:
        try:
            webbrowser.open(session.verification_uri_complete)
            print("Opened verification URL in your default browser.")
        except webbrowser.Error as exc:
            print(f"Warning: unable to open browser automatically ({exc}).", file=sys.stderr)

    deadline = time.monotonic() + args.timeout if args.timeout else None
    try:
        while True:
            if deadline and time.monotonic() >= deadline:
                print("\nTimed out waiting for approval.", file=sys.stderr)
                return 2

            result = manager.poll_device_code(session.device_code)
            status = result.status
            if status is DeviceAuthorizationStatus.PENDING:
                if not args.quiet:
                    remaining = result.expires_in if result.expires_in is not None else session.expires_in()
                    retry_after = result.retry_after or session.poll_interval
                    print(
                        f"Waiting for approval... {remaining}s remaining (poll in {retry_after}s)",
                        end="\r",
                        flush=True,
                    )
                time.sleep(result.retry_after or session.poll_interval)
                continue

            print("\n", end="")
            if status is DeviceAuthorizationStatus.DENIED:
                reason = result.denied_reason or "No reason provided"
                print(f"Consent denied: {reason}", file=sys.stderr)
                return 3
            if status is DeviceAuthorizationStatus.EXPIRED:
                print("Device code expired before approval.", file=sys.stderr)
                return 2

            tokens = result.tokens
            assert tokens is not None, "Approved state must include tokens"
            issued_at = datetime.now(timezone.utc)
            bundle = AuthTokenBundle(
                access_token=tokens.access_token,
                refresh_token=tokens.refresh_token,
                token_type=tokens.token_type,
                scopes=result.scopes or scopes,
                client_id=result.client_id or args.client_id,
                issued_at=issued_at,
                expires_at=tokens.access_token_expires_at,
                refresh_expires_at=tokens.refresh_token_expires_at,
            )
            try:
                store.save(bundle)
            except TokenStoreError as exc:
                print(f"Warning: failed to persist tokens ({exc}).", file=sys.stderr)
                return 4

            print("Login successful!")
            print(f"Access token valid until : {bundle.expires_at.isoformat()}")
            print(f"Refresh token valid until: {bundle.refresh_expires_at.isoformat()}")
            return 0
    except KeyboardInterrupt:
        print("\nLogin cancelled by user.")
        return 130


def _command_auth_login_internal(args: argparse.Namespace) -> int:
    """[DEPRECATED] Perform internal auth login with username/password.

    Internal authentication has been deprecated. Please use OAuth instead.
    """
    print("Error: Internal authentication (username/password) has been deprecated.", file=sys.stderr)
    print("", file=sys.stderr)
    print("Please use OAuth authentication instead:", file=sys.stderr)
    print("  amprealize auth login --provider=github", file=sys.stderr)
    print("  amprealize auth login --provider=google", file=sys.stderr)
    return 1


def _command_auth_status(args: argparse.Namespace) -> int:
    """Display cached token status."""

    try:
        store = _get_token_store(allow_plaintext=args.allow_plaintext)
    except TokenStoreError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    try:
        bundle = store.load()
    except TokenStoreError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if bundle is None:
        print("No cached tokens found. Run 'amprealize auth login' to authenticate.")
        return 0

    payload = {
        "client_id": bundle.client_id,
        "scopes": bundle.scopes,
        "issued_at": bundle.issued_at.isoformat(),
        "expires_at": bundle.expires_at.isoformat(),
        "refresh_expires_at": bundle.refresh_expires_at.isoformat(),
        "access_expires_in": bundle.access_expires_in(),
        "refresh_expires_in": bundle.refresh_expires_in(),
    }

    if args.format == "json":
        _print_json(payload)
    else:
        print("Cached Authentication Tokens")
        print("=" * 80)
        print(f"Client ID         : {payload['client_id']}")
        print(f"Scopes            : {', '.join(bundle.scopes)}")
        print(f"Issued At         : {payload['issued_at']}")
        print(f"Access Expires    : {payload['expires_at']} ({payload['access_expires_in']}s)")
        print(
            f"Refresh Expires   : {payload['refresh_expires_at']} ({payload['refresh_expires_in']}s)"
        )
    return 0


def _command_auth_logout(args: argparse.Namespace) -> int:
    """Clear cached authentication tokens."""

    try:
        store = _get_token_store(allow_plaintext=args.allow_plaintext)
    except TokenStoreError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    try:
        bundle = store.load()
    except TokenStoreError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if bundle is None:
        print("No cached tokens to remove.")
        return 0

    if not args.force:
        prompt = input("Clear cached tokens? [y/N]: ").strip().lower()
        if prompt not in {"y", "yes"}:
            print("Logout aborted.")
            return 1

    try:
        store.clear()
    except TokenStoreError as exc:
        print(f"Error clearing tokens: {exc}", file=sys.stderr)
        return 1

    print("Cached tokens removed.")
    return 0


def _command_auth_refresh(args: argparse.Namespace) -> int:
    """Refresh the cached access token using the stored refresh token."""

    try:
        store = _get_token_store(allow_plaintext=args.allow_plaintext)
    except TokenStoreError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        bundle = store.load()
    except TokenStoreError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if bundle is None:
        print("No cached tokens found. Run 'amprealize auth login' to authenticate.")
        return 1

    if bundle.refresh_expires_in() <= 0:
        print("Refresh token expired. Run 'amprealize auth login' to authenticate again.", file=sys.stderr)
        try:
            store.clear()
        except TokenStoreError as exc:
            print(f"Warning: failed to clear expired tokens ({exc}).", file=sys.stderr)
        return 2

    if bundle.is_access_valid() and not args.force:
        if not args.quiet:
            remaining = bundle.access_expires_in()
            print(f"Access token still valid for {remaining}s; skipping refresh (use --force to override).")
        return 0

    manager = _get_device_flow_manager()
    try:
        session = manager.refresh_access_token(bundle.refresh_token)
    except (RefreshTokenNotFoundError, DeviceCodeNotFoundError):
        print("Stored refresh token is no longer recognized. Run 'amprealize auth login' to re-authenticate.", file=sys.stderr)
        return 2
    except RefreshTokenExpiredError:
        print("Refresh token expired. Run 'amprealize auth login' to re-authenticate.", file=sys.stderr)
        try:
            store.clear()
        except TokenStoreError as exc:
            print(f"Warning: failed to clear expired tokens ({exc}).", file=sys.stderr)
        return 2
    except DeviceCodeExpiredError:
        print("Original device authorization expired. Run 'amprealize auth login' to re-authenticate.", file=sys.stderr)
        return 2
    except DeviceFlowError as exc:
        print(f"Error refreshing tokens: {exc}", file=sys.stderr)
        return 1

    tokens = session.tokens
    assert tokens is not None, "refreshed session must include tokens"

    bundle.update_tokens(
        access_token=tokens.access_token,
        access_expires_at=tokens.access_token_expires_at,
        refresh_token=tokens.refresh_token,
        refresh_expires_at=tokens.refresh_token_expires_at,
    )

    try:
        store.save(bundle)
    except TokenStoreError as exc:
        print(f"Warning: refreshed tokens but failed to persist them ({exc}).", file=sys.stderr)
        return 4

    if not args.quiet:
        print("Access token refreshed successfully.")
        print(f"Access token valid until : {bundle.expires_at.isoformat()}")
        print(f"Refresh token valid until: {bundle.refresh_expires_at.isoformat()}")
    return 0


def _command_auth_consent_lookup(args: argparse.Namespace) -> int:
    """Lookup metadata for a consent code."""

    manager = _get_device_flow_manager()
    try:
        normalized = _normalize_user_code(args.user_code)
        session = manager.describe_user_code(normalized)
    except (ValueError, UserCodeNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    payload = {
        "user_code": session.user_code,
        "status": session.status.value,
        "client_id": session.client_id,
        "scopes": session.scopes,
        "surface": session.surface,
        "created_at": session.created_at.isoformat(),
        "expires_at": session.expires_at.isoformat(),
        "verification_uri": session.verification_uri,
        "verification_uri_complete": session.verification_uri_complete,
    }
    if session.approved_at:
        payload["approved_at"] = session.approved_at.isoformat()
    if session.denied_at:
        payload["denied_at"] = session.denied_at.isoformat()
        payload["denied_reason"] = session.denied_reason

    if args.format == "json":
        _print_json(payload)
    else:
        print("Consent Request Details")
        print("=" * 80)
        print(f"User Code         : {payload['user_code']}")
        print(f"Status            : {payload['status']}")
        print(f"Client ID         : {payload['client_id']}")
        print(f"Scopes            : {', '.join(session.scopes)}")
        print(f"Surface           : {payload['surface']}")
        print(f"Created At        : {payload['created_at']}")
        print(f"Expires At        : {payload['expires_at']}")
        if session.approved_at:
            print(f"Approved At       : {payload['approved_at']}")
        if session.denied_at:
            print(f"Denied At         : {payload['denied_at']} ({payload.get('denied_reason', 'n/a')})")
    return 0


def _command_auth_consent_approve(args: argparse.Namespace) -> int:
    """Approve a consent request via user code."""

    manager = _get_device_flow_manager()
    roles = args.roles or []
    try:
        normalized = _normalize_user_code(args.user_code)
        session = manager.approve_user_code(
            normalized,
            args.actor_id,
            approver_surface="CLI",
            roles=roles,
            mfa_verified=args.mfa_verified,
        )
    except (ValueError, UserCodeNotFoundError, DeviceCodeExpiredError, DeviceFlowError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Consent approved.")
    if session.tokens:
        print(f"Grant issued for scopes: {', '.join(session.scopes)}")
    return 0


def _command_auth_consent_deny(args: argparse.Namespace) -> int:
    """Deny a consent request via user code."""

    manager = _get_device_flow_manager()
    try:
        normalized = _normalize_user_code(args.user_code)
        session = manager.deny_user_code(
            normalized,
            args.actor_id,
            approver_surface="CLI",
            reason=args.reason,
        )
    except (ValueError, UserCodeNotFoundError, DeviceCodeExpiredError, DeviceFlowError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Consent denied.")
    if session.denied_reason:
        print(f"Reason: {session.denied_reason}")
    return 0


def _command_bci_rebuild_index(args: argparse.Namespace) -> int:
    """Rebuild the behavior retriever semantic index."""
    bci_service = _get_bci_service()

    try:
        result = bci_service.rebuild_index()
    except Exception as exc:  # pragma: no cover - defensive logging
        print(f"Error rebuilding index: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        _print_json(result)
    else:
        print("BehaviorRetriever Index Rebuild")
        print("=" * 60)
        print(f"Status           : {result.get('status', 'unknown')}")
        if "mode" in result:
            print(f"Mode             : {result.get('mode')}")
        if "behavior_count" in result:
            print(f"Behavior Count   : {result.get('behavior_count')}")
        if "duration_ms" in result:
            print(f"Duration (ms)    : {result.get('duration_ms')}")
        error = result.get("error")
        if error:
            print(f"Error            : {error}")
    return 0


def _load_json_file(path: str) -> Any:
    file_path = Path(path).expanduser().resolve()
    if not file_path.exists():
        raise ValueError(f"File not found: {file_path}")
    raw = file_path.read_text(encoding="utf-8")
    return json.loads(raw) if raw.strip() else None


def _render_bci_retrieve_table(payload: Dict[str, Any]) -> None:
    results: List[Dict[str, Any]] = payload.get("results", [])
    if not results:
        print("No behaviors matched the query.")
    else:
        headers = ["#", "Behavior", "Score", "Role", "Tags"]
        rows: List[List[str]] = []
        widths = [len(header) for header in headers]
        for idx, result in enumerate(results, start=1):
            row = [
                str(idx),
                result.get("name", "?"),
                f"{float(result.get('score', 0.0)):.3f}",
                result.get("role_focus", "-"),
                ", ".join(result.get("tags", [])) or "-",
            ]
            rows.append(row)
            widths = [max(widths[i], len(row[i])) for i in range(len(headers))]
        fmt = " | ".join(f"{{:<{width}}}" for width in widths)
        separator = "-+-".join("-" * width for width in widths)
        print(fmt.format(*headers))
        print(separator)
        for row in rows:
            print(fmt.format(*row))

    print()
    latency = payload.get("latency_ms")
    if latency is not None:
        print(f"Latency (ms): {latency}")
    print(f"Strategy Used: {payload.get('strategy_used', 'unknown')}")
    metadata = payload.get("metadata") or {}
    if metadata:
        print("Metadata:")
        for key, value in metadata.items():
            print(f"  - {key}: {value}")


def _render_bci_compose_table(payload: Dict[str, Any]) -> None:
    print("Composed Prompt")
    print("=" * 60)
    print(payload.get("prompt", ""))
    print()
    behaviors: List[Dict[str, Any]] = payload.get("behaviors", [])
    if behaviors:
        print("Behaviors Included:")
        for behavior in behaviors:
            label = behavior.get("citation_label") or behavior.get("name")
            print(f"  - {label} ({behavior.get('behavior_id', '?')})")
    metadata = payload.get("metadata") or {}
    if metadata:
        print()
        print("Metadata:")
        for key, value in metadata.items():
            print(f"  - {key}: {value}")


def _render_bci_validate_table(payload: Dict[str, Any]) -> None:
    print("Citation Validation Summary")
    print("=" * 60)
    print(f"Total Citations : {payload.get('total_citations', 0)}")
    print(f"Valid Citations : {len(payload.get('valid_citations', []))}")
    print(f"Invalid Citations: {len(payload.get('invalid_citations', []))}")
    print(f"Compliance Rate : {payload.get('compliance_rate', 0.0)}")
    print(f"Is Compliant    : {payload.get('is_compliant', False)}")
    missing = payload.get("missing_behaviors", [])
    if missing:
        print("Missing Behaviors:")
        for name in missing:
            print(f"  - {name}")
    warnings = payload.get("warnings", [])
    if warnings:
        print("Warnings:")
        for item in warnings:
            print(f"  - {item}")
    invalid = payload.get("invalid_citations", [])
    if invalid:
        print("Invalid Citations:")
        for citation in invalid:
            text = citation.get("text") if isinstance(citation, dict) else str(citation)
            behavior_name = citation.get("behavior_name") if isinstance(citation, dict) else None
            detail = f" (behavior={behavior_name})" if behavior_name else ""
            print(f"  - {text}{detail}")


def _command_bci_generate(args: argparse.Namespace) -> int:
    """Generate a behavior-conditioned LLM response."""
    from .llm import LLMConfig, ProviderType
    from .bci_contracts import RoleFocus

    bci_service = _get_bci_service()

    # Build LLM config from args
    llm_config = None
    if args.provider or args.model or args.temperature:
        config_kwargs = {}
        if args.provider:
            try:
                config_kwargs["provider"] = ProviderType(args.provider)
            except ValueError:
                print(f"Invalid provider: {args.provider}", file=sys.stderr)
                return 1
        if args.model:
            config_kwargs["model"] = args.model
        if args.temperature is not None:
            config_kwargs["temperature"] = args.temperature

        llm_config = LLMConfig.from_env()
        for key, value in config_kwargs.items():
            setattr(llm_config, key, value)

    # Parse role focus
    role_focus = None
    if args.role:
        try:
            role_focus = RoleFocus(args.role.upper())
        except ValueError:
            print(f"Invalid role: {args.role}", file=sys.stderr)
            return 1

    try:
        result = bci_service.generate_response(
            query=args.query,
            behaviors=args.behaviors,
            top_k=args.top_k,
            llm_config=llm_config,
            role_focus=role_focus,
        )

        # Format behaviors for display
        behaviors_display = "\n".join(f"- {b.name}" for b in result['behaviors_used']) if result['behaviors_used'] else "(auto-retrieved)"

        output_text = f"""# BCI Generation Result

## Query
{args.query}

## Behaviors Used
{behaviors_display}

## Response
{result['response'].content}

## Metadata
- Provider: {result['response'].provider.value}
- Model: {result['response'].model}
- Input Tokens: {result['response'].input_tokens}
- Output Tokens: {result['response'].output_tokens}
- Total Tokens: {result['response'].total_tokens}
- Token Savings (estimated): {result['token_savings']['total_saved']}
- Latency: {result['latency_ms']:.2f}ms
- LLM Latency: {result['response'].latency_ms:.2f}ms
"""

        if args.output:
            with open(args.output, "w") as f:
                f.write(output_text)
            print(f"Output written to {args.output}")
        else:
            print(output_text)

        return 0

    except Exception as exc:
        print(f"Generation failed: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


def _command_bci_improve(args: argparse.Namespace) -> int:
    """Analyze a failed run and generate improvement suggestions."""
    from .llm import LLMConfig, ProviderType

    bci_service = _get_bci_service()

    # Build LLM config from args
    llm_config = None
    if args.provider or args.model:
        config_kwargs = {}
        if args.provider:
            try:
                config_kwargs["provider"] = ProviderType(args.provider)
            except ValueError:
                print(f"Invalid provider: {args.provider}", file=sys.stderr)
                return 1
        if args.model:
            config_kwargs["model"] = args.model

        llm_config = LLMConfig.from_env()
        for key, value in config_kwargs.items():
            setattr(llm_config, key, value)

    try:
        result = bci_service.improve_run(
            run_id=args.run_id,
            llm_config=llm_config,
            max_behaviors=args.max_behaviors,
        )

        output_text = f"""# Run Improvement Analysis

## Run ID
{result['run_id']}

## Detected Patterns
{chr(10).join(f"- {p['description']} (frequency={p['frequency']}, score={p['score']:.2f})" for p in result['patterns'])}

## Improvement Suggestions
{result['suggestions']}

## Behaviors Extracted
{chr(10).join(f"- {b}" for b in result['behaviors_extracted'])}

## Metadata
- Patterns Detected: {len(result['patterns'])}
- Behaviors Extracted: {len(result['behaviors_extracted'])}
- Analysis Latency: {result['latency_ms']:.2f}ms
"""

        if args.output:
            with open(args.output, "w") as f:
                f.write(output_text)
            print(f"Output written to {args.output}")
        else:
            print(output_text)

        return 0

    except Exception as exc:
        print(f"Improvement analysis failed: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


def _command_bci_retrieve(args: argparse.Namespace) -> int:
    bci_service = _get_bci_service()
    try:
        strategy = RetrievalStrategy(args.strategy)
        role_focus = RoleFocus(args.role_focus) if args.role_focus else None
    except ValueError as exc:
        print(f"Invalid argument: {exc}", file=sys.stderr)
        return 1

    if args.top_k <= 0:
        print("--top-k must be greater than 0", file=sys.stderr)
        return 1

    request = RetrieveRequest(
        query=args.query,
        top_k=args.top_k,
        strategy=strategy,
        role_focus=role_focus,
        tags=args.tags or None,
        include_metadata=args.include_metadata,
        embedding_weight=args.embedding_weight,
        keyword_weight=args.keyword_weight,
    )

    try:
        response = bci_service.retrieve(request)
    except Exception as exc:  # pragma: no cover - defensive logging
        print(f"Error retrieving behaviors: {exc}", file=sys.stderr)
        return 1

    payload = response.to_dict()
    if args.format == "json":
        _print_json(payload)
    else:
        _render_bci_retrieve_table(payload)
    return 0


def _command_bci_compose_prompt(args: argparse.Namespace) -> int:
    bci_service = _get_bci_service()
    try:
        behaviors_payload = _load_json_file(args.behaviors_file)
        if not isinstance(behaviors_payload, list):
            raise ValueError("Behaviors file must contain a JSON array")
        behaviors = [BehaviorSnippet.from_dict(item) for item in behaviors_payload]
        if not behaviors:
            raise ValueError("Behaviors list cannot be empty")
        citation_mode = CitationMode(args.citation_mode)
        prompt_format = PromptFormat(args.prompt_format)
    except Exception as exc:
        print(f"Error preparing compose prompt request: {exc}", file=sys.stderr)
        return 1

    request = ComposePromptRequest(
        query=args.query,
        behaviors=behaviors,
        citation_mode=citation_mode,
        format=prompt_format,
        citation_instruction=args.citation_instruction,
        max_behaviors=args.max_behaviors,
    )

    try:
        response = bci_service.compose_prompt(request)
    except Exception as exc:  # pragma: no cover - defensive logging
        print(f"Error composing prompt: {exc}", file=sys.stderr)
        return 1

    payload = response.to_dict()
    if args.format == "json":
        _print_json(payload)
    else:
        _render_bci_compose_table(payload)
    return 0


def _command_bci_validate_citations(args: argparse.Namespace) -> int:
    if args.output_text and args.output_file:
        print("Provide either --output-text or --output-file, not both", file=sys.stderr)
        return 1

    bci_service = _get_bci_service()
    try:
        output_text = args.output_text
        if output_text is None and args.output_file:
            output_text = Path(args.output_file).expanduser().read_text(encoding="utf-8")
        if not output_text:
            raise ValueError("Either --output-text or --output-file must be provided")

        prepended_payload = _load_json_file(args.prepended_file)
        if not isinstance(prepended_payload, list):
            raise ValueError("Prepended file must contain a JSON array")
        prepended = [PrependedBehavior.from_dict(item) for item in prepended_payload]
        if not prepended:
            raise ValueError("Prepended behaviors list cannot be empty")
    except Exception as exc:
        print(f"Error preparing validation request: {exc}", file=sys.stderr)
        return 1

    request = ValidateCitationsRequest(
        output_text=output_text,
        prepended_behaviors=prepended,
        minimum_citations=args.minimum_citations,
        allow_unlisted_behaviors=args.allow_unlisted,
    )

    try:
        response = bci_service.validate_citations(request)
    except Exception as exc:  # pragma: no cover - defensive logging
        print(f"Error validating citations: {exc}", file=sys.stderr)
        return 1

    payload = response.to_dict()
    if args.format == "json":
        _print_json(payload)
    else:
        _render_bci_validate_table(payload)
    return 0


def _command_bci_inject(args: argparse.Namespace) -> int:
    """E3 Runtime Injection: resolve context, retrieve behaviors, compose enriched prompt."""
    from amprealize.runtime_injector import RuntimeInjector
    from amprealize.runtime_context import ContextResolverInput

    # Build ContextResolverInput from CLI args
    workspace_path = args.workspace_path or os.getcwd()
    resolver_input = ContextResolverInput(
        workspace_path=workspace_path,
        surface=args.surface,
        role=args.role,
        task=args.task,
        pack_id=getattr(args, "pack_id", None),
        pack_version=getattr(args, "pack_version", None),
    )

    # Build retrieval options
    tags = args.tags if args.tags else None
    retrieval_options = {
        "top_k": args.top_k,
        "strategy": args.strategy,
        "format": args.format,
        "citation_mode": args.citation_mode,
        "tags": tags,
    }

    # Inject
    try:
        injector = RuntimeInjector()
        result = injector.inject(resolver_input, retrieval_options)
    except Exception as exc:
        print(f"Error during runtime injection: {exc}", file=sys.stderr)
        return 1

    # Output
    if args.json:
        payload = result.to_dict()
        output_str = json.dumps(payload, indent=2)
    else:
        # Human-readable output
        lines = []
        lines.append("=" * 60)
        lines.append("RUNTIME INJECTION RESULT")
        lines.append("=" * 60)
        lines.append(f"Surface: {result.context.surface}")
        lines.append(f"Role: {result.context.role or 'Not specified'}")
        lines.append(f"Task Type: {result.context.task_type}")
        lines.append(f"Workspace Profile: {result.context.workspace_profile}")
        lines.append(f"Active Pack: {result.context.active_pack_id or 'None'}")
        lines.append("")
        lines.append("Behaviors Injected:")
        for b in result.behaviors_injected:
            lines.append(f"  - {b}")
        lines.append("")
        if result.overlays_included:
            lines.append("Overlays Included:")
            for o in result.overlays_included:
                lines.append(f"  - {o}")
            lines.append("")
        lines.append(f"Token Estimate: {result.token_estimate}")
        lines.append(f"Latency: {result.latency_ms:.1f}ms")
        lines.append("")
        lines.append("-" * 60)
        lines.append("COMPOSED PROMPT:")
        lines.append("-" * 60)
        lines.append(result.composed_prompt)
        output_str = "\n".join(lines)

    if args.output:
        Path(args.output).expanduser().write_text(output_str, encoding="utf-8")
        print(f"Output written to {args.output}")
    else:
        print(output_str)

    return 0


def _parse_evidence(items: List[str]) -> Dict[str, Any]:
    """Parse key=value evidence items into a dictionary."""
    evidence: Dict[str, Any] = {}
    for entry in items:
        if "=" not in entry:
            raise ValueError(f"Invalid evidence entry '{entry}'. Use KEY=VALUE format.")
        key, value = entry.split("=", 1)
        evidence[key] = value
    return evidence


def _command_compliance_create_checklist(args: argparse.Namespace) -> int:
    adapter = _get_compliance_adapter()
    try:
        checklist = adapter.create_checklist(
            title=args.title,
            description=args.description,
            template_id=args.template_id,
            milestone=args.milestone,
            compliance_category=args.compliance_category or [],
            actor_id=args.actor_id,
            actor_role=args.actor_role,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_checklist_table([checklist])
    else:
        _print_json(checklist)
    return 0


def _command_compliance_record_step(args: argparse.Namespace) -> int:
    adapter = _get_compliance_adapter()
    try:
        evidence = _parse_evidence(args.evidence_items or [])
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    try:
        step = adapter.record_step(
            checklist_id=args.checklist_id,
            title=args.title,
            status=args.status,
            evidence=evidence,
            behaviors_cited=args.behaviors_cited or [],
            related_run_id=args.related_run_id,
            actor_id=args.actor_id,
            actor_role=args.actor_role,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_step_table([step])
    else:
        _print_json(step)
    return 0


def _command_compliance_list(args: argparse.Namespace) -> int:
    adapter = _get_compliance_adapter()
    try:
        checklists = adapter.list_checklists(
            milestone=args.milestone,
            compliance_category=args.compliance_category,
            status_filter=args.status,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_checklist_table(checklists)
    else:
        _print_json(checklists)
    return 0


def _command_compliance_get(args: argparse.Namespace) -> int:
    adapter = _get_compliance_adapter()
    try:
        checklist = adapter.get_checklist(args.checklist_id)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_checklist_table([checklist])
    else:
        _print_json(checklist)
    return 0


def _command_compliance_validate(args: argparse.Namespace) -> int:
    adapter = _get_compliance_adapter()

    # Support either checklist_id or --action-id
    if args.action_id:
        try:
            result = adapter.validate_by_action_id(
                action_id=args.action_id,
                actor_id=args.actor_id,
                actor_role=args.actor_role,
            )
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    elif args.checklist_id:
        try:
            result = adapter.validate_checklist(
                checklist_id=args.checklist_id,
                actor_id=args.actor_id,
                actor_role=args.actor_role,
            )
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    else:
        print("Error: Either checklist_id or --action-id must be provided", file=sys.stderr)
        return 2

    if args.format == "table":
        _render_validation_table(result)
    else:
        _print_json(result)
    return 0


def _command_compliance_policies_list(args: argparse.Namespace) -> int:
    adapter = _get_compliance_adapter()
    try:
        policies = adapter.list_policies(
            org_id=args.org_id,
            project_id=args.project_id,
            policy_type=args.policy_type,
            enforcement_level=args.enforcement_level,
            is_active=True if args.active_only else None,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_policies_table(policies)
    else:
        _print_json(policies)
    return 0


def _command_compliance_policies_create(args: argparse.Namespace) -> int:
    adapter = _get_compliance_adapter()
    try:
        policy = adapter.create_policy(
            name=args.name,
            description=args.description,
            policy_type=args.policy_type,
            enforcement_level=args.enforcement_level,
            org_id=args.org_id,
            project_id=args.project_id,
            version=args.version,
            required_behaviors=args.required_behaviors or [],
            compliance_categories=args.compliance_categories or [],
            actor_id=args.actor_id,
            actor_role=args.actor_role,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_policies_table([policy])
    else:
        _print_json(policy)
    return 0


def _command_compliance_policies_get(args: argparse.Namespace) -> int:
    adapter = _get_compliance_adapter()
    try:
        policy = adapter.get_policy(args.policy_id)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_policies_table([policy])
    else:
        _print_json(policy)
    return 0


def _command_compliance_audit(args: argparse.Namespace) -> int:
    adapter = _get_compliance_adapter()
    try:
        report = adapter.get_audit_trail(
            run_id=args.run_id,
            checklist_id=args.checklist_id,
            action_id=args.action_id,
            start_date=args.start_date,
            end_date=args.end_date,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_audit_trail_table(report)
    else:
        _print_json(report)
    return 0


def _render_policies_table(policies: List[Dict]) -> None:
    """Render policies as a formatted table."""
    if not policies:
        print("No policies found.")
        return

    headers = ["ID", "Name", "Type", "Enforcement", "Scope", "Active", "Version"]
    rows = []
    for p in policies:
        scope = "project" if p.get("project_id") else ("org" if p.get("org_id") else "global")
        rows.append([
            p.get("policy_id", "")[:8],
            p.get("name", ""),
            p.get("policy_type", ""),
            p.get("enforcement_level", ""),
            scope,
            "✓" if p.get("is_active") else "✗",
            p.get("version", ""),
        ])

    _print_table(headers, rows)


def _render_audit_trail_table(report: Dict) -> None:
    """Render audit trail report as a formatted table."""
    summary = report.get("summary", {})
    print(f"\n=== Audit Trail Report ===")
    print(f"Run ID: {report.get('run_id', 'N/A')}")
    print(f"Checklists: {summary.get('checklist_count', 0)}")
    print(f"Total Entries: {summary.get('total_entries', 0)}")
    print(f"Generated: {report.get('generated_at', '')}")

    status_breakdown = summary.get("status_breakdown", {})
    if status_breakdown:
        print(f"\nStatus Breakdown:")
        for status, count in status_breakdown.items():
            print(f"  {status}: {count}")

    entries = report.get("entries", [])
    if entries:
        print(f"\n--- Entries ({len(entries)}) ---")
        headers = ["Timestamp", "Checklist", "Step", "Status", "Actor", "Behaviors"]
        rows = []
        for e in entries:
            rows.append([
                e.get("timestamp", "")[:19],
                e.get("checklist_id", "")[:8],
                e.get("title", "")[:30],
                e.get("status", ""),
                f"{e.get('actor', {}).get('id', '')}@{e.get('actor', {}).get('surface', '')}",
                ", ".join(e.get("behaviors_cited", [])[:2]) + ("..." if len(e.get("behaviors_cited", [])) > 2 else ""),
            ])
        _print_table(headers, rows)


def _ensure_pre_commit_available() -> None:
    if subprocess.call(["pre-commit", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
        raise RuntimeError("pre-commit CLI is required to run amprealize scan-secrets")


def _run_pre_commit(report_path: Path) -> int:
    cmd: List[str] = [
        "pre-commit",
        "run",
        "gitleaks",
        "--all-files",
        "--hook-stage",
        "manual",
        "--",
        "--report-format",
        "json",
        "--report-path",
        str(report_path),
    ]
    result = subprocess.run(cmd, text=True)  # noqa: S603
    return result.returncode


def _load_findings(report_path: Path) -> List[dict]:
    if not report_path.exists():
        return []
    raw = report_path.read_text(encoding="utf-8")
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive guard
        raise RuntimeError(f"Invalid JSON report generated by gitleaks: {exc}") from exc
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "findings" in data:
        payload = data.get("findings")
        return payload if isinstance(payload, list) else []
    return []


def _render_table(findings: List[dict]) -> None:
    if not findings:
        print("No secrets detected ✅")
        return

    print(f"Detected {len(findings)} potential secret(s):")
    for finding in findings:
        rule = finding.get("RuleID") or finding.get("rule") or "unknown_rule"
        file_path = finding.get("File") or finding.get("file") or "unknown_file"
        line = finding.get("StartLine") or finding.get("Line") or finding.get("line") or "?"
        print(f" - {rule} :: {file_path}:{line}")


def run_scan(
    *,
    output_path: Optional[Path] = None,
    fmt: str = "table",
    fail_on_findings: bool = False,
) -> int:
    _ensure_pre_commit_available()

    temp_file: Optional[Any] = None
    if output_path is None:
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        report_path = Path(temp_file.name)
        temp_file.close()
    else:
        report_path = output_path.expanduser().resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)

    exit_code = _run_pre_commit(report_path)
    findings = _load_findings(report_path)

    if fmt == "json":
        if output_path is None:
            print(json.dumps(findings, indent=2))
        else:
            print(f"JSON report written to {report_path}")
    else:
        _render_table(findings)

    if output_path is None and report_path.exists():
        report_path.unlink(missing_ok=True)

    if exit_code not in (0, 1):
        return exit_code

    if fail_on_findings and findings:
        return 1

    return 0


def _render_workflow_templates_table(templates: List[Dict[str, Any]]) -> None:
    if not templates:
        print("No workflow templates found.")
        return

    headers = ["Template ID", "Name", "Role", "Steps", "Tags"]
    widths = [len(header) for header in headers]
    rows: List[List[str]] = []

    for template in templates:
        row = [
            template["template_id"][:12],
            template["name"],
            template["role_focus"],
            str(len(template["steps"])),
            ", ".join(template.get("tags", [])) or "-",
        ]
        rows.append(row)
        widths = [max(width, len(value)) for width, value in zip(widths, row)]

    fmt = " | ".join(f"{{:<{width}}}" for width in widths)
    separator = "-+-".join("-" * width for width in widths)

    print(fmt.format(*headers))
    print(separator)
    for row in rows:
        print(fmt.format(*row))


def _render_workflow_run_table(run: Dict[str, Any]) -> None:
    headers = ["Run ID", "Template", "Status", "Total Tokens", "Behaviors"]
    row = [
        run["run_id"][:12],
        run["template_name"],
        run["status"],
        str(run.get("total_tokens", 0)),
        str(len(run.get("behaviors_cited", []))),
    ]
    widths = [max(len(header), len(value)) for header, value in zip(headers, row)]
    fmt = " | ".join(f"{{:<{width}}}" for width in widths)
    separator = "-+-".join("-" * width for width in widths)
    print(fmt.format(*headers))
    print(separator)
    print(fmt.format(*row))


def _render_reflection_table(result: Dict[str, Any]) -> None:
    summary = result.get("summary")
    if summary:
        print(summary)
        print()
    candidates = result.get("candidates", [])
    if not candidates:
        print("No high-confidence behavior candidates found.")
        return

    headers = ["Slug", "Confidence", "Duplicate", "Tags"]
    widths = [len(header) for header in headers]
    rows: List[List[str]] = []

    for candidate in candidates:
        duplicate = candidate.get("duplicate_behavior_name") or candidate.get("duplicate_behavior_id") or "-"
        row = [
            candidate["slug"][:28],
            f"{candidate.get('confidence', 0.0):.2f}",
            duplicate,
            ", ".join(candidate.get("tags", [])).strip() or "-",
        ]
        rows.append(row)
        widths = [max(width, len(value)) for width, value in zip(widths, row)]

    fmt = " | ".join(f"{{:<{width}}}" for width in widths)
    separator = "-+-".join("-" * width for width in widths)

    print(fmt.format(*headers))
    print(separator)
    for row in rows:
        print(fmt.format(*row))


def _render_candidates_list_table(result: Dict[str, Any]) -> None:
    """Render a table of behavior candidates for review."""
    candidates = result.get("candidates", [])
    total = result.get("total", len(candidates))

    if not candidates:
        print("No behavior candidates found.")
        return

    print(f"Found {total} candidate(s):\n")

    headers = ["ID", "Name", "Status", "Confidence", "Role", "Created"]
    widths = [len(header) for header in headers]
    rows: List[List[str]] = []

    for candidate in candidates:
        created = candidate.get("created_at", "")[:10] if candidate.get("created_at") else "-"
        row = [
            candidate.get("id", "")[:12],
            candidate.get("name", candidate.get("slug", ""))[:24],
            candidate.get("status", "proposed"),
            f"{candidate.get('confidence', 0.0):.2f}",
            candidate.get("role", "-")[:12],
            created,
        ]
        rows.append(row)
        widths = [max(width, len(value)) for width, value in zip(widths, row)]

    fmt = " | ".join(f"{{:<{width}}}" for width in widths)
    separator = "-+-".join("-" * width for width in widths)

    print(fmt.format(*headers))
    print(separator)
    for row in rows:
        print(fmt.format(*row))


def _command_reflection_extract(args: argparse.Namespace) -> int:
    """Handle 'amprealize reflection extract' subcommand."""
    adapter = _get_reflection_adapter()
    trace_text = getattr(args, "trace_text", None) or ""
    if not trace_text:
        trace_file = getattr(args, "trace_file", None)
        if not trace_file:
            print("Error: provide --trace or --trace-file for reflection", file=sys.stderr)
            return 2
        trace_path = Path(trace_file).expanduser().resolve()
        if not trace_path.exists():
            print(f"Error: Trace file not found: {trace_path}", file=sys.stderr)
            return 2
        trace_text = trace_path.read_text(encoding="utf-8")

    min_score = max(0.0, min(1.0, getattr(args, "min_score", 0.6)))

    try:
        result = adapter.reflect(
            trace_text=trace_text,
            trace_format=getattr(args, "trace_format", "chain_of_thought"),
            run_id=getattr(args, "run_id", None),
            max_candidates=getattr(args, "max_candidates", 5),
            min_quality_score=min_score,
            include_examples=not getattr(args, "no_examples", False),
            preferred_tags=getattr(args, "tags", None),
        )
    except Exception as exc:  # pragma: no cover - CLI guard
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if getattr(args, "output", "json") == "table":
        _render_reflection_table(result)
    else:
        _print_json(result)
    return 0


def _command_reflection_list(args: argparse.Namespace) -> int:
    """Handle 'amprealize reflection list' subcommand."""
    adapter = _get_reflection_adapter()

    payload: Dict[str, Any] = {
        "limit": getattr(args, "limit", 50),
        "offset": getattr(args, "offset", 0),
    }
    if getattr(args, "status", None):
        payload["status"] = args.status
    if getattr(args, "role", None):
        payload["role"] = args.role
    if getattr(args, "min_confidence", None) is not None:
        payload["min_confidence"] = args.min_confidence

    try:
        result = adapter.list_candidates(payload)
    except Exception as exc:  # pragma: no cover - CLI guard
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if getattr(args, "output", "table") == "table":
        _render_candidates_list_table(result)
    else:
        _print_json(result)
    return 0


def _command_reflection_approve(args: argparse.Namespace) -> int:
    """Handle 'amprealize reflection approve' subcommand."""
    adapter = _get_reflection_adapter()

    payload: Dict[str, Any] = {
        "candidate_id": args.candidate_id,
        "reviewed_by": getattr(args, "reviewed_by", DEFAULT_ACTOR_ID),
    }
    if getattr(args, "merge_to_handbook", False):
        payload["merge_to_handbook"] = True
    if getattr(args, "behavior_name", None):
        payload["behavior_name"] = args.behavior_name

    try:
        result = adapter.approve_candidate(payload)
    except Exception as exc:  # pragma: no cover - CLI guard
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if result.get("success"):
        print(f"Candidate {args.candidate_id} approved successfully.")
        if result.get("auto_approved"):
            print("(Auto-approved due to high confidence >= 0.8)")
        if result.get("merged_behavior_id"):
            print(f"Merged to handbook as behavior: {result['merged_behavior_id']}")
    else:
        print(f"Warning: {result.get('message', 'Unknown error')}", file=sys.stderr)

    if getattr(args, "output", "json") == "json":
        _print_json(result)
    return 0


def _command_reflection_reject(args: argparse.Namespace) -> int:
    """Handle 'amprealize reflection reject' subcommand."""
    adapter = _get_reflection_adapter()

    payload: Dict[str, Any] = {
        "candidate_id": args.candidate_id,
        "reviewed_by": getattr(args, "reviewed_by", DEFAULT_ACTOR_ID),
    }
    if getattr(args, "reason", None):
        payload["reason"] = args.reason

    try:
        result = adapter.reject_candidate(payload)
    except Exception as exc:  # pragma: no cover - CLI guard
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if result.get("success"):
        print(f"Candidate {args.candidate_id} rejected.")
    else:
        print(f"Warning: {result.get('message', 'Unknown error')}", file=sys.stderr)

    if getattr(args, "output", "json") == "json":
        _print_json(result)
    return 0


def _command_reflection(args: argparse.Namespace) -> int:
    """Dispatch reflection subcommands."""
    subcommand = getattr(args, "reflection_command", None)

    if subcommand == "extract":
        return _command_reflection_extract(args)
    elif subcommand == "list":
        return _command_reflection_list(args)
    elif subcommand == "approve":
        return _command_reflection_approve(args)
    elif subcommand == "reject":
        return _command_reflection_reject(args)
    else:
        # No subcommand: show help
        print("Usage: amprealize reflection <command>")
        print("\nCommands:")
        print("  extract    Analyze traces and propose reusable behavior candidates")
        print("  list       List behavior candidates for review")
        print("  approve    Approve a behavior candidate")
        print("  reject     Reject a behavior candidate")
        print("\nRun 'amprealize reflection <command> --help' for details.")
        return 0


def _command_workflow_create_template(args: argparse.Namespace) -> int:
    adapter = _get_workflow_adapter()
    try:
        # Load steps from file
        steps_path = Path(args.steps_file).expanduser().resolve()
        if not steps_path.exists():
            print(f"Error: Steps file not found: {steps_path}", file=sys.stderr)
            return 2
        steps_data = json.loads(steps_path.read_text(encoding="utf-8"))
        if not isinstance(steps_data, list):
            print("Error: Steps file must contain a JSON array", file=sys.stderr)
            return 2

        metadata = None
        if args.metadata_file:
            metadata = _load_metadata([], args.metadata_file)

        template = adapter.create_template(
            name=args.name,
            description=args.description,
            role_focus=args.role_focus,
            steps=steps_data,
            tags=args.tags or None,
            metadata=metadata,
            actor_id=args.actor_id,
            actor_role=args.actor_role,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_workflow_templates_table([template])
    else:
        _print_json(template)
    return 0


def _command_workflow_list_templates(args: argparse.Namespace) -> int:
    adapter = _get_workflow_adapter()
    try:
        templates = adapter.list_templates(
            role_focus=args.role_focus,
            tags=args.tags or None,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_workflow_templates_table(templates)
    else:
        _print_json(templates)
    return 0


def _command_workflow_get_template(args: argparse.Namespace) -> int:
    adapter = _get_workflow_adapter()
    try:
        template = adapter.get_template(args.template_id)
        if not template:
            print(f"Error: Template not found: {args.template_id}", file=sys.stderr)
            return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_workflow_templates_table([template])
    else:
        _print_json(template)
    return 0


def _command_workflow_run(args: argparse.Namespace) -> int:
    adapter = _get_workflow_adapter()
    try:
        metadata = None
        if args.metadata_file:
            metadata = _load_metadata([], args.metadata_file)

        # --no-early-retrieval flag disables EKA
        enable_early_retrieval = not getattr(args, "no_early_retrieval", False)

        run = adapter.run_workflow(
            template_id=args.template_id,
            behavior_ids=args.behavior_ids or None,
            metadata=metadata,
            actor_id=args.actor_id,
            actor_role=args.actor_role,
            enable_early_retrieval=enable_early_retrieval,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_workflow_run_table(run)
    else:
        _print_json(run)
    return 0


def _command_workflow_status(args: argparse.Namespace) -> int:
    adapter = _get_workflow_adapter()
    try:
        run = adapter.get_run(args.run_id)
        if not run:
            print(f"Error: Run not found: {args.run_id}", file=sys.stderr)
            return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "table":
        _render_workflow_run_table(run)
    else:
        _print_json(run)
    return 0


def _get_breakeramp_service() -> Any:
    """Factory for BreakerAmpService with dependencies."""
    from amprealize.breakeramp import BreakerAmpService

    # Use existing CLI adapters to get the underlying services
    action_adapter = _get_action_adapter()
    compliance_adapter = _get_compliance_adapter()
    metrics_adapter = _get_metrics_adapter()

    # The adapters wrap the service in ._service
    # We need to access the private member because the adapter doesn't expose the raw service
    # This is acceptable within the CLI module which owns the adapters
    return BreakerAmpService(
        action_service=action_adapter._service,
        compliance_service=compliance_adapter._service,
        metrics_service=metrics_adapter._service,
    )


def _override_breakeramp_env_file(env_file: Optional[str]) -> None:
    """Override BreakerAmp manifest path for the current process."""

    if env_file:
        os.environ["AMPREALIZE_ENV_FILE"] = env_file


def _command_breakeramp_plan(args: argparse.Namespace) -> int:
    from amprealize.breakeramp import PlanRequest
    from amprealize.action_contracts import Actor

    _override_breakeramp_env_file(args.env_file)
    service = _get_breakeramp_service()
    output_mode = _resolve_output_format(getattr(args, "output", None))

    # Parse variables
    vars_dict = {}
    for v in args.variables:
        if "=" in v:
            k, val = v.split("=", 1)
            vars_dict[k] = val

    # Create actor from CLI args
    actor = Actor(
        id=args.actor_id,
        role=args.actor_role,
        surface="cli"
    )

    try:
        req = PlanRequest(
            blueprint_id=args.blueprint_id,
            environment=args.environment,
            lifetime=args.lifetime,
            compliance_tier=args.compliance_tier,
            checklist_id=args.checklist_id,
            behaviors=args.behaviors,
            variables=vars_dict,
            active_modules=args.active_modules,
            force_podman=args.force_podman
        )
        # Service.plan signature: plan(self, request: PlanRequest, actor: Actor = None)
        resp = service.plan(req, actor)
        resp_data = _serialize_model(resp)
        snapshot_path = _save_breakeramp_snapshot("plan", resp_data)
        if output_mode == "json":
            _print_json(resp_data)
            _notify_snapshot_location(snapshot_path)
        else:
            _render_breakeramp_plan_summary(resp_data, snapshot_path)
            print("  (use --output json for the raw payload)")
        return 0
    except Exception as e:
        print(f"Error planning: {e}", file=sys.stderr)
        return 1


def _command_breakeramp_apply(args: argparse.Namespace) -> int:
    from amprealize.breakeramp import ApplyRequest
    from amprealize.action_contracts import Actor

    _override_breakeramp_env_file(args.env_file)
    service = _get_breakeramp_service()
    output_mode = _resolve_output_format(getattr(args, "output", None))

    # Create actor from CLI args
    actor = Actor(
        id=args.actor_id,
        role=args.actor_role,
        surface="cli"
    )

    try:
        manifest = None
        if args.manifest_file:
            with open(args.manifest_file, "r") as f:
                if args.manifest_file.endswith(('.yaml', '.yml')):
                    manifest = yaml.safe_load(f)
                else:
                    manifest = json.load(f)

        # Handle special value -1 for stale_max_age_hours (None = skip age check)
        stale_max_age = getattr(args, "stale_max_age_hours", 0.0)
        effective_stale_max_age = None if stale_max_age == -1 else stale_max_age

        req = ApplyRequest(
            plan_id=args.plan_id,
            manifest=manifest,
            watch=args.watch,
            resume=args.resume,
            force_podman=args.force_podman,
            skip_resource_check=args.skip_resource_check,
            auto_cleanup=getattr(args, "auto_cleanup", False),
            auto_cleanup_aggressive=getattr(args, "auto_cleanup_aggressive", False),
            auto_cleanup_include_volumes=getattr(args, "auto_cleanup_include_volumes", False),
            auto_cleanup_max_retries=getattr(args, "auto_cleanup_max_retries", 3),
            allow_host_resource_warning=getattr(args, "allow_host_resource_warning", False),
            min_disk_gb=args.min_disk_gb,
            min_memory_mb=args.min_memory_mb,
            proactive_cleanup=getattr(args, "proactive_cleanup", False),
            blueprint_aware_memory_check=getattr(args, "blueprint_aware_memory_check", True),
            memory_safety_margin_mb=getattr(args, "memory_safety_margin_mb", 512.0),
            auto_resolve_stale=getattr(args, "auto_resolve_stale", True),
            auto_resolve_conflicts=getattr(args, "auto_resolve_conflicts", True),
            stale_max_age_hours=effective_stale_max_age,
        )

        if args.watch:
            resp = service.apply(req, actor)
            run_id = resp.amp_run_id
            print(f"Apply started. Watching BreakerAmp run {run_id} (Ctrl+C to stop viewing)")
            events: List[Dict[str, Any]] = []
            try:
                for event in service.watch(run_id):
                    event_dict = _serialize_model(event)
                    events.append(event_dict)
                    _render_breakeramp_event(event_dict)
            except KeyboardInterrupt:
                print("Stopped watching apply. You can re-run with --watch to resume streaming.")
            status = service.status(run_id)
            status_dict = _serialize_model(status)
            snapshot_payload = {"status": status_dict, "events": events}
            snapshot_path = _save_breakeramp_snapshot("apply-watch", snapshot_payload)
            if output_mode == "json":
                _print_json(snapshot_payload)
                _notify_snapshot_location(snapshot_path)
            else:
                _render_breakeramp_status_summary(status_dict, snapshot_path, include_events=len(events))
            return 0
        resp = service.apply(req, actor)
        resp_data = _serialize_model(resp)
        snapshot_path = _save_breakeramp_snapshot("apply", resp_data)
        if output_mode == "json":
            _print_json(resp_data)
            _notify_snapshot_location(snapshot_path)
        else:
            _render_breakeramp_apply_summary(resp_data, snapshot_path, watched=False)
        return 0
    except Exception as e:
        print(f"Error applying: {e}", file=sys.stderr)
        return 1


def _command_breakeramp_status(args: argparse.Namespace) -> int:
    service = _get_breakeramp_service()
    output_mode = _resolve_output_format(getattr(args, "output", None))

    try:
        resp = service.status(args.amp_run_id)
        resp_data = _serialize_model(resp)
        snapshot_path = _save_breakeramp_snapshot("status", resp_data)
        if output_mode == "json":
            _print_json(resp_data)
            _notify_snapshot_location(snapshot_path)
        else:
            _render_breakeramp_status_summary(resp_data, snapshot_path)
        return 0
    except Exception as e:
        print(f"Error checking status: {e}", file=sys.stderr)
        return 1


def _command_breakeramp_destroy(args: argparse.Namespace) -> int:
    from amprealize.breakeramp import DestroyRequest
    from amprealize.action_contracts import Actor

    _override_breakeramp_env_file(args.env_file)
    service = _get_breakeramp_service()
    output_mode = _resolve_output_format(getattr(args, "output", None))

    # Create actor from CLI args
    actor = Actor(
        id=args.actor_id,
        role=args.actor_role,
        surface="cli"
    )

    try:
        req = DestroyRequest(
            amp_run_id=args.amp_run_id,
            cascade=args.cascade,
            reason=args.reason,
            force_podman=args.force_podman,
            cleanup_after_destroy=getattr(args, "cleanup_after_destroy", True),
            cleanup_aggressive=getattr(args, "cleanup_aggressive", True),
            cleanup_include_volumes=getattr(args, "cleanup_include_volumes", False),
        )

        resp = service.destroy(req, actor)
        resp_data = _serialize_model(resp)
        snapshot_path = _save_breakeramp_snapshot("destroy", resp_data)
        if output_mode == "json":
            _print_json(resp_data)
            _notify_snapshot_location(snapshot_path)
        else:
            _render_breakeramp_destroy_summary(resp_data, snapshot_path)
        return 0
    except Exception as e:
        print(f"Error destroying resources: {e}", file=sys.stderr)
        return 1


def _command_breakeramp_bootstrap(args: argparse.Namespace) -> int:
    service = _get_breakeramp_service()

    target_dir = Path(args.bootstrap_directory).expanduser()
    env_template = Path(args.env_template).expanduser() if args.env_template else None
    include_blueprints = args.include_blueprints or bool(args.blueprints)

    try:
        result = service.bootstrap(
            target_directory=target_dir,
            include_blueprints=include_blueprints,
            blueprints=args.blueprints or None,
            force=args.force,
            env_template=env_template,
        )
    except FileExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error bootstrapping BreakerAmp config: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, default=str))
    return 0


def _command_breakeramp_cleanup(args: argparse.Namespace) -> int:
    """Clean up stale and orphaned containers."""
    from breakeramp.executors import PodmanExecutor

    output_mode = getattr(args, "output", "table")
    dry_run = getattr(args, "dry_run", False)
    clean_stale = getattr(args, "stale", True)
    clean_orphans = getattr(args, "orphans", True)
    max_age_hours = getattr(args, "max_age_hours", None)
    all_non_running = getattr(args, "all_non_running", False)

    try:
        executor = PodmanExecutor()

        results = {
            "stale": {"found": 0, "removed": 0, "failed": 0, "details": []},
            "orphans": {"found": 0, "removed": 0, "details": []},
        }

        # Clean stale containers
        if clean_stale:
            stale_result = executor.cleanup_stale_containers(
                include_all=all_non_running,
                max_age_hours=max_age_hours,
                force=True,
                dry_run=dry_run,
            )

            results["stale"]["found"] = stale_result.get("total_found", 0)
            results["stale"]["removed"] = len(stale_result.get("removed", []))
            results["stale"]["failed"] = len(stale_result.get("failed", []))

            if dry_run:
                results["stale"]["details"] = stale_result.get("would_remove", [])
            else:
                results["stale"]["details"] = [
                    {"name": name, "action": "removed"}
                    for name in stale_result.get("removed", [])
                ]
                for name, error in stale_result.get("failed", []):
                    results["stale"]["details"].append({
                        "name": name, "action": "failed", "error": error
                    })

        # Clean orphaned BreakerAmp containers
        if clean_orphans:
            orphans = executor.find_orphaned_breakeramp_containers()
            results["orphans"]["found"] = len(orphans)

            if dry_run:
                results["orphans"]["details"] = [
                    {"name": c.name, "status": c.status, "created": c.created}
                    for c in orphans
                ]
            else:
                removed = executor.cleanup_orphaned_containers()
                results["orphans"]["removed"] = removed
                results["orphans"]["details"] = [
                    {"name": c.name, "action": "removed"} for c in orphans[:removed]
                ]

        # Output results
        if output_mode == "json":
            _print_json(results)
        else:
            _render_cleanup_summary(results, dry_run)

        return 0

    except Exception as e:
        print(f"Error during cleanup: {e}", file=sys.stderr)
        return 1


def _render_cleanup_summary(results: dict, dry_run: bool) -> None:
    """Render cleanup results as a human-readable summary."""
    action_word = "Would remove" if dry_run else "Removed"

    print()
    if dry_run:
        print("=== DRY RUN - No changes made ===")
        print()

    # Stale containers
    stale = results.get("stale", {})
    if stale.get("found", 0) > 0:
        print(f"Stale Containers: {stale['found']} found")
        for item in stale.get("details", []):
            status = item.get("status", "")
            name = item.get("name", "unknown")
            if status:
                print(f"  • {name} ({status})")
            else:
                action = item.get("action", "")
                if action == "failed":
                    print(f"  ✗ {name}: {item.get('error', 'unknown error')}")
                else:
                    print(f"  ✓ {name}")
        print(f"  {action_word}: {stale.get('removed', 0)}")
        if stale.get("failed", 0) > 0:
            print(f"  Failed: {stale['failed']}")
        print()
    else:
        print("Stale Containers: None found")
        print()

    # Orphaned containers
    orphans = results.get("orphans", {})
    if orphans.get("found", 0) > 0:
        print(f"Orphaned BreakerAmp Containers: {orphans['found']} found")
        for item in orphans.get("details", []):
            name = item.get("name", "unknown")
            status = item.get("status", "")
            if status:
                print(f"  • {name} ({status})")
            else:
                print(f"  ✓ {name}")
        print(f"  {action_word}: {orphans.get('removed', 0)}")
        print()
    else:
        print("Orphaned BreakerAmp Containers: None found")
        print()

    # Summary
    total_found = stale.get("found", 0) + orphans.get("found", 0)
    total_removed = stale.get("removed", 0) + orphans.get("removed", 0)

    if dry_run:
        print(f"Total: {total_found} containers would be removed")
    else:
        print(f"Total: {total_removed} containers removed")


# ── BreakerAmp Machine Commands ─────────────────────────────────────────────────

def _get_podman_executor():
    """Get a PodmanExecutor instance for machine management."""
    from breakeramp.executors import PodmanExecutor
    return PodmanExecutor()


def _render_machine_table(machines: list) -> None:
    """Render machine list as a table."""
    if not machines:
        print("No Podman machines found.")
        return

    # Header
    print(f"{'NAME':<25} {'STATUS':<12} {'CPUS':<6} {'MEMORY':<10} {'DISK':<10}")
    print("-" * 65)

    for m in machines:
        status = "Running" if m.running else "Stopped"
        cpus = str(m.cpus) if m.cpus else "-"
        memory = f"{m.memory_mb}MB" if m.memory_mb else "-"
        disk = f"{m.disk_gb}GB" if m.disk_gb else "-"
        print(f"{m.name:<25} {status:<12} {cpus:<6} {memory:<10} {disk:<10}")


def _command_breakeramp_machine_list(args: argparse.Namespace) -> int:
    """List all Podman machines."""
    try:
        executor = _get_podman_executor()
        machines = executor.list_machines()

        if getattr(args, "output", "table") == "json":
            data = [
                {
                    "name": m.name,
                    "running": m.running,
                    "cpus": m.cpus,
                    "memory_mb": m.memory_mb,
                    "disk_gb": m.disk_gb,
                }
                for m in machines
            ]
            _print_json(data)
        else:
            _render_machine_table(machines)
        return 0
    except Exception as e:
        print(f"Error listing machines: {e}", file=sys.stderr)
        return 1


def _command_breakeramp_machine_start(args: argparse.Namespace) -> int:
    """Start a Podman machine."""
    try:
        executor = _get_podman_executor()
        machines = executor.list_machines()

        # Determine which machine to start
        name = args.name
        if not name:
            # Try amprealize-ci first, then first available
            amprealize_machine = next((m for m in machines if m.name == "amprealize-ci"), None)
            if amprealize_machine:
                name = "amprealize-ci"
            elif machines:
                name = machines[0].name
            else:
                print("No Podman machines found. Use 'amprealize breakeramp machine ensure' to create one.", file=sys.stderr)
                return 1

        # Check if already running
        machine = executor.get_machine(name)
        if machine and machine.running:
            print(f"Machine '{name}' is already running.")
            return 0

        print(f"Starting machine '{name}'...")
        executor.start_machine(name)
        print(f"✓ Machine '{name}' started successfully.")
        return 0
    except Exception as e:
        print(f"Error starting machine: {e}", file=sys.stderr)
        return 1


def _command_breakeramp_machine_stop(args: argparse.Namespace) -> int:
    """Stop a Podman machine."""
    try:
        executor = _get_podman_executor()
        machines = executor.list_machines()

        if args.stop_all:
            # Stop all running machines
            running = [m for m in machines if m.running]
            if not running:
                print("No running machines to stop.")
                return 0

            for m in running:
                print(f"Stopping machine '{m.name}'...")
                executor.stop_machine(m.name)
                print(f"✓ Machine '{m.name}' stopped.")
            return 0

        # Stop a specific machine
        name = args.name
        if not name:
            # Try amprealize-ci first, then first running machine
            amprealize_machine = next((m for m in machines if m.name == "amprealize-ci" and m.running), None)
            if amprealize_machine:
                name = "amprealize-ci"
            else:
                running = next((m for m in machines if m.running), None)
                if running:
                    name = running.name
                else:
                    print("No running machines to stop.")
                    return 0

        # Check if already stopped
        machine = executor.get_machine(name)
        if machine and not machine.running:
            print(f"Machine '{name}' is already stopped.")
            return 0

        print(f"Stopping machine '{name}'...")
        executor.stop_machine(name)
        print(f"✓ Machine '{name}' stopped successfully.")
        return 0
    except Exception as e:
        print(f"Error stopping machine: {e}", file=sys.stderr)
        return 1


def _command_breakeramp_machine_ensure(args: argparse.Namespace) -> int:
    """Ensure a Podman machine is running (start if needed, create if missing)."""
    try:
        executor = _get_podman_executor()
        name = args.name or "amprealize-ci"

        machine = executor.get_machine(name)

        if machine:
            if machine.running:
                print(f"✓ Machine '{name}' is already running.")
                return 0
            else:
                print(f"Starting existing machine '{name}'...")
                executor.start_machine(name)
                print(f"✓ Machine '{name}' started successfully.")
                return 0

        # Machine doesn't exist - create it
        print(f"Creating new machine '{name}' (cpus={args.cpus}, memory={args.memory}MB, disk={args.disk}GB)...")
        executor.init_machine(
            name=name,
            cpus=args.cpus,
            memory_mb=args.memory,
            disk_gb=args.disk,
        )

        print(f"Starting machine '{name}'...")
        executor.start_machine(name)
        print(f"✓ Machine '{name}' created and started successfully.")
        return 0
    except Exception as e:
        print(f"Error ensuring machine: {e}", file=sys.stderr)
        return 1


def _command_breakeramp_machine_status(args: argparse.Namespace) -> int:
    """Show status of a Podman machine."""
    try:
        executor = _get_podman_executor()
        machines = executor.list_machines()

        # Determine which machine to show
        name = args.name
        if not name:
            # Try amprealize-ci first, then first available
            amprealize_machine = next((m for m in machines if m.name == "amprealize-ci"), None)
            if amprealize_machine:
                name = "amprealize-ci"
            elif machines:
                name = machines[0].name
            else:
                print("No Podman machines found.", file=sys.stderr)
                return 1

        machine = executor.get_machine(name)
        if not machine:
            print(f"Machine '{name}' not found.", file=sys.stderr)
            return 1

        if getattr(args, "output", "table") == "json":
            # Get detailed info
            try:
                details = executor.inspect_machine(name)
            except Exception:
                details = {}

            data = {
                "name": machine.name,
                "running": machine.running,
                "cpus": machine.cpus,
                "memory_mb": machine.memory_mb,
                "disk_gb": machine.disk_gb,
                "details": details,
            }
            _print_json(data)
        else:
            status = "Running ✓" if machine.running else "Stopped ✗"
            print(f"Machine: {machine.name}")
            print(f"Status:  {status}")
            print(f"CPUs:    {machine.cpus or 'unknown'}")
            print(f"Memory:  {machine.memory_mb}MB" if machine.memory_mb else "Memory:  unknown")
            print(f"Disk:    {machine.disk_gb}GB" if machine.disk_gb else "Disk:    unknown")

        return 0
    except Exception as e:
        print(f"Error getting machine status: {e}", file=sys.stderr)
        return 1


def _command_breakeramp_machine_resources(args: argparse.Namespace) -> int:
    """Show resource usage for host and Podman machines."""
    try:
        executor = _get_podman_executor()

        # Get all resources
        resources = executor.get_all_resources()

        if getattr(args, "check", False):
            # Health check mode
            healthy, warnings = executor.check_resource_health(
                min_disk_gb=args.min_disk_gb,
                min_memory_mb=args.min_memory_mb,
            )

            if getattr(args, "output", "table") == "json":
                _print_json({
                    "healthy": healthy,
                    "warnings": warnings,
                    "resources": [r.to_dict() for r in resources],
                })
            else:
                if healthy:
                    print("✓ All resources healthy")
                    print(f"  (Checked: disk >= {args.min_disk_gb}GB, memory >= {args.min_memory_mb}MB)")
                else:
                    print("✗ Resource health check FAILED")
                    for warning in warnings:
                        print(f"  • {warning}")
                    print()
                    print("  💡 To proceed with apply despite low resources, use:")
                    print("     amprealize breakeramp apply --skip-resource-check")

            return 0 if healthy else 1

        # Display mode
        if getattr(args, "output", "table") == "json":
            _print_json([r.to_dict() for r in resources])
        else:
            _render_resources_table(resources)

        return 0
    except Exception as e:
        print(f"Error getting resources: {e}", file=sys.stderr)
        return 1


def _render_resources_table(resources: list) -> None:
    """Render resource information as a table."""
    for resource in resources:
        source = resource.source
        if source == "host":
            print("═" * 60)
            print("HOST RESOURCES")
            print("═" * 60)
        else:
            print("─" * 60)
            print(f"MACHINE: {source.replace('machine:', '')}")
            print("─" * 60)

        # Disk
        if resource.disk:
            disk = resource.disk
            status = "🔴 CRITICAL" if disk.is_critical else ("🟡 WARNING" if disk.is_warning else "🟢 OK")
            print(f"  Disk:   {disk.used:.1f}/{disk.total:.1f} {disk.unit} ({disk.percent_used:.1f}% used) {status}")
            print(f"          Available: {disk.available:.1f} {disk.unit}")

        # Memory
        if resource.memory:
            mem = resource.memory
            status = "🔴 CRITICAL" if mem.is_critical else ("🟡 WARNING" if mem.is_warning else "🟢 OK")
            print(f"  Memory: {mem.used:.0f}/{mem.total:.0f} {mem.unit} ({mem.percent_used:.1f}% used) {status}")
            print(f"          Available: {mem.available:.0f} {mem.unit}")

        # CPU
        if resource.cpu:
            cpu = resource.cpu
            print(f"  CPU:    {cpu.used:.1f}/{cpu.total:.0f} {cpu.unit} (load avg)")

        # Warnings
        if resource.warnings:
            print("  Warnings:")
            for warning in resource.warnings:
                print(f"    ⚠️  {warning}")

        print()


def _command_breakeramp_machine_cleanup(args: argparse.Namespace) -> int:
    """Clean up unused resources to free disk space."""
    try:
        executor = _get_podman_executor()

        dry_run = getattr(args, "dry_run", False)
        aggressive = getattr(args, "aggressive", False)

        result = executor.mitigate_resources(
            dry_run=dry_run,
            prune_containers=not getattr(args, "skip_containers", False),
            prune_images=not getattr(args, "skip_images", False),
            prune_volumes=getattr(args, "include_volumes", False),
            prune_cache=not getattr(args, "skip_cache", False),
            prune_networks=getattr(args, "include_networks", False),
            prune_pods=getattr(args, "include_pods", False),
            prune_logs=getattr(args, "include_logs", False),
            aggressive=aggressive,
        )

        if getattr(args, "output", "table") == "json":
            _print_json(result.to_dict())
        else:
            _render_cleanup_result(result)

        return 0 if result.success else 1
    except Exception as e:
        print(f"Error during cleanup: {e}", file=sys.stderr)
        return 1


def _render_cleanup_result(result) -> None:
    """Render cleanup result as formatted output."""
    action = "Would clean" if result.dry_run else "Cleaned"

    if result.dry_run:
        print("═" * 60)
        print("DRY RUN - No changes made")
        print("═" * 60)
    else:
        print("═" * 60)
        print("CLEANUP COMPLETE")
        print("═" * 60)

    print()

    # Summary
    if result.items_cleaned == 0:
        print("  ✓ Nothing to clean - resources already optimized")
    else:
        if result.containers_removed > 0:
            print(f"  🗑️  {action}: {result.containers_removed} stopped container(s)")
            if result.details.get("containers"):
                for c in result.details["containers"][:5]:  # Show first 5
                    print(f"      • {c.get('name', c.get('id', 'unknown'))}")
                if len(result.details["containers"]) > 5:
                    print(f"      ... and {len(result.details['containers']) - 5} more")

        if result.images_removed > 0:
            print(f"  🗑️  {action}: {result.images_removed} unused image(s)")
            if result.details.get("images"):
                for img in result.details["images"][:5]:
                    print(f"      • {img.get('name', img.get('id', 'unknown'))}")
                if len(result.details["images"]) > 5:
                    print(f"      ... and {len(result.details['images']) - 5} more")

        if result.volumes_removed > 0:
            print(f"  🗑️  {action}: {result.volumes_removed} unused volume(s)")

        if result.networks_removed > 0:
            print(f"  🗑️  {action}: {result.networks_removed} unused network(s)")
            if result.details.get("networks"):
                for net in result.details["networks"][:5]:
                    print(f"      • {net}")
                if len(result.details["networks"]) > 5:
                    print(f"      ... and {len(result.details['networks']) - 5} more")

        if result.pods_removed > 0:
            print(f"  🗑️  {action}: {result.pods_removed} stopped pod(s)")
            if result.details.get("pods"):
                for pod in result.details["pods"][:5]:
                    print(f"      • {pod}")
                if len(result.details["pods"]) > 5:
                    print(f"      ... and {len(result.details['pods']) - 5} more")

        if result.logs_truncated > 0:
            print(f"  🗑️  {action}: {result.logs_truncated} container log(s)")

        if result.cache_cleared:
            print(f"  🗑️  {action}: build cache")

        if result.space_reclaimed_mb > 0:
            if result.space_reclaimed_mb > 1024:
                print(f"\n  📊 Estimated space {'to reclaim' if result.dry_run else 'reclaimed'}: {result.space_reclaimed_mb/1024:.1f} GB")
            else:
                print(f"\n  📊 Estimated space {'to reclaim' if result.dry_run else 'reclaimed'}: {result.space_reclaimed_mb:.0f} MB")

    # Errors
    if result.errors:
        print("\n  ⚠️  Warnings/Errors:")
        for error in result.errors:
            print(f"      • {error}")

    print()

    if result.dry_run:
        print("  💡 Run without --dry-run to perform the cleanup")


def _command_scan_secrets(args: argparse.Namespace) -> int:
    return run_scan(
        output_path=Path(args.output).resolve() if args.output else DEFAULT_OUTPUT.resolve(),
        fmt=args.format,
        fail_on_findings=args.fail_on_findings,
    )


def _command_bandwidth_check(args: argparse.Namespace) -> int:
    """Check current bandwidth usage against environment limits."""
    try:
        # Load environment config to get the limit
        from amprealize.breakeramp import BreakerAmpService

        # Initialize dependencies
        action_adapter = _get_action_adapter()
        compliance_adapter = _get_compliance_adapter()
        metrics_adapter = _get_metrics_adapter()

        service = BreakerAmpService(
            action_service=action_adapter._service,
            compliance_service=compliance_adapter._service,
            metrics_service=metrics_adapter._service
        )

        # We need to know which environment we are checking for. Default to 'dev' or take from args.
        env_name = getattr(args, "environment", "dev")

        # BreakerAmpService loads config in __init__ and stores in self.environments
        if env_name not in service.environments:
            print(f"Error: Environment '{env_name}' not found in configuration.", file=sys.stderr)
            return 1

        env_config = service.environments[env_name]
        limit_mbps = env_config.runtime.network_mbps

        if limit_mbps is None:
             print(f"No bandwidth limit defined for environment '{env_name}'.", file=sys.stderr)
             # We can still show usage, treat limit as infinite
             limit_mbps_val = float('inf')
        else:
             limit_mbps_val = float(limit_mbps)

        print(f"Checking bandwidth usage for environment: {env_name} (Limit: {limit_mbps_val} Mbps)")

        enforcer = BandwidthEnforcer(limit_mbps=limit_mbps)

        # Check usage
        stats = service.get_network_stats()
        usage_mbps = enforcer.get_current_usage_mbps(stats)

        print(f"Current Usage: {usage_mbps:.2f} Mbps")

        if usage_mbps > limit_mbps_val:
            print("Status: OVER LIMIT ⚠️")
            return 1
        else:
            print("Status: OK ✅")
            return 0

    except Exception as e:
        print(f"Error checking bandwidth: {e}", file=sys.stderr)
        return 1


# ── Audit Log Commands ────────────────────────────────────────────────────────

_audit_service_singleton: Optional[Any] = None


def _get_audit_service() -> Any:
    """Lazy singleton for AuditLogService."""
    global _audit_service_singleton
    if _audit_service_singleton is None:
        from amprealize.services.audit_log_service import AuditLogService
        from amprealize.config.settings import get_settings

        settings = get_settings()
        _audit_service_singleton = AuditLogService(settings=settings)
    return _audit_service_singleton


def _command_audit_verify(args: argparse.Namespace) -> int:
    """Verify integrity of an archived audit batch."""
    output_mode = _resolve_output_format(getattr(args, "output", None))

    try:
        service = _get_audit_service()
        public_key_path = getattr(args, "public_key", None)

        result = service.verify_archive(
            batch_id=args.batch_id,
            public_key_path=public_key_path,
        )

        if output_mode == "json":
            _print_json(result)
        else:
            print(f"Batch ID: {result.get('batch_id', args.batch_id)}")
            print(f"Archive Key: {result.get('archive_key', 'N/A')}")
            print(f"Event Count: {result.get('event_count', 'N/A')}")
            print(f"Content Hash: {result.get('content_hash', 'N/A')[:16]}...")
            print()

            if result.get("integrity_valid"):
                print("✅ Content Integrity: VALID")
            else:
                print(f"❌ Content Integrity: INVALID - {result.get('integrity_error', 'hash mismatch')}")

            if result.get("signature_valid") is True:
                print("✅ Signature: VALID")
            elif result.get("signature_valid") is False:
                print(f"❌ Signature: INVALID - {result.get('signature_error', 'verification failed')}")
            else:
                print("⚠️  Signature: NOT VERIFIED (no public key provided)")

            retention = result.get("retention_info", {})
            if retention:
                print()
                print(f"Retention Mode: {retention.get('mode', 'N/A')}")
                print(f"Retain Until: {retention.get('retain_until_date', 'N/A')}")
                print(f"Legal Hold: {retention.get('legal_hold_status', 'N/A')}")

        # Return 0 only if integrity is valid
        return 0 if result.get("integrity_valid") else 1

    except Exception as e:
        print(f"Error verifying audit batch: {e}", file=sys.stderr)
        return 1


def _command_audit_list(args: argparse.Namespace) -> int:
    """List archived audit batches."""
    output_mode = _resolve_output_format(getattr(args, "output", None))

    try:
        service = _get_audit_service()
        prefix = getattr(args, "prefix", None)
        limit = getattr(args, "limit", 100)

        batches = service.list_archives(prefix=prefix, limit=limit)

        if output_mode == "json":
            _print_json({"batches": batches, "count": len(batches)})
        else:
            if not batches:
                print("No archived audit batches found.")
                return 0

            headers = ["Batch ID", "Archived At", "Event Count", "Size (KB)"]
            widths = [len(h) for h in headers]
            rows = []

            for batch in batches:
                row = [
                    batch.get("batch_id", "-")[:36],
                    batch.get("archived_at", "-")[:19],
                    str(batch.get("event_count", "-")),
                    f"{batch.get('size_bytes', 0) / 1024:.1f}",
                ]
                rows.append(row)
                widths = [max(w, len(v)) for w, v in zip(widths, row)]

            fmt = " | ".join(f"{{:<{w}}}" for w in widths)
            separator = "-+-".join("-" * w for w in widths)

            print(fmt.format(*headers))
            print(separator)
            for row in rows:
                print(fmt.format(*row))

            print(f"\nTotal: {len(batches)} batches")

        return 0

    except Exception as e:
        print(f"Error listing audit batches: {e}", file=sys.stderr)
        return 1


def _command_audit_retention(args: argparse.Namespace) -> int:
    """Check retention info for an archived batch."""
    output_mode = _resolve_output_format(getattr(args, "output", None))

    try:
        service = _get_audit_service()

        retention = service.get_retention_info(batch_id=args.batch_id)

        if output_mode == "json":
            _print_json(retention)
        else:
            print(f"Batch ID: {args.batch_id}")
            print(f"Archive Key: {retention.get('archive_key', 'N/A')}")
            print()
            print(f"Object Lock Mode: {retention.get('mode', 'N/A')}")
            print(f"Retain Until: {retention.get('retain_until_date', 'N/A')}")
            print(f"Legal Hold: {retention.get('legal_hold_status', 'OFF')}")
            print(f"Versioned: {retention.get('is_versioned', False)}")

            if retention.get("version_id"):
                print(f"Version ID: {retention.get('version_id')}")

        return 0

    except Exception as e:
        print(f"Error getting retention info: {e}", file=sys.stderr)
        return 1


# ── Migration Commands ──────────────────────────────────────────────────────────

# Service configuration for migrations
_MIGRATION_CONFIG = {
    "behavior": {
        "migration": "001_create_behavior_service.sql",
        "dsn_env": "AMPREALIZE_BEHAVIOR_PG_DSN",
        "tables": ["behaviors", "behavior_history"],
    },
    "workflow": {
        "migration": "003_create_workflow_service.sql",
        "dsn_env": "AMPREALIZE_WORKFLOW_PG_DSN",
        "tables": ["workflow_templates", "workflow_runs", "workflow_steps"],
    },
    "action": {
        "migration": "004_create_action_service.sql",
        "dsn_env": "AMPREALIZE_ACTION_PG_DSN",
        "tables": ["actions", "replays"],
    },
    "run": {
        "migration": "005_create_run_service.sql",
        "dsn_env": "AMPREALIZE_RUN_PG_DSN",
        "tables": ["runs", "run_steps"],
    },
    "compliance": {
        "migration": "006_create_compliance_service.sql",
        "dsn_env": "AMPREALIZE_COMPLIANCE_PG_DSN",
        "tables": ["compliance_checklists", "compliance_steps", "compliance_policies"],
    },
    "metrics": {
        "migration": "007_create_metrics_service.sql",
        "dsn_env": "AMPREALIZE_METRICS_PG_DSN",
        "tables": ["metrics", "metric_snapshots"],
    },
    "reflection": {
        "migration": "020_create_reflection_service.sql",
        "dsn_env": "AMPREALIZE_REFLECTION_PG_DSN",
        "tables": ["reflection_patterns", "behavior_candidates", "pattern_observations", "reflection_sessions"],
    },
    "collaboration": {
        "migration": "021_create_collaboration_service.sql",
        "dsn_env": "AMPREALIZE_COLLABORATION_PG_DSN",
        "tables": ["workspaces", "workspace_members", "documents", "edit_operations", "comments", "activity_logs"],
    },
}


def _get_migration_path(migration_file: str) -> Path:
    """Get absolute path to a migration file."""
    repo_root = Path(__file__).parent.parent
    return repo_root / "schema" / "migrations" / migration_file


def _check_service_tables(dsn: str, tables: List[str]) -> Dict[str, bool]:
    """Check which tables exist for a service."""
    try:
        import psycopg2
    except ImportError:
        return {table: False for table in tables}

    result = {}
    try:
        with psycopg2.connect(dsn, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                for table in tables:
                    cur.execute(
                        """
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables
                            WHERE table_schema = 'public' AND table_name = %s
                        )
                        """,
                        (table,)
                    )
                    row = cur.fetchone()
                    result[table] = bool(row and row[0])
    except Exception:
        result = {table: False for table in tables}
    return result


def _apply_migration(dsn: str, migration_path: Path) -> bool:
    """Apply a single migration file."""
    try:
        import psycopg2
    except ImportError:
        print("  ❌ psycopg2 not installed. Run: pip install psycopg2-binary", file=sys.stderr)
        return False

    if not migration_path.exists():
        print(f"  ❌ Migration file not found: {migration_path}", file=sys.stderr)
        return False

    sql = migration_path.read_text(encoding="utf-8")

    try:
        with psycopg2.connect(dsn, connect_timeout=10) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(sql)
        return True
    except Exception as e:
        print(f"  ❌ Migration failed: {e}", file=sys.stderr)
        return False


def _command_migrate_apply(args: argparse.Namespace) -> int:
    """Apply pending schema migrations."""
    services = list(_MIGRATION_CONFIG.keys()) if args.service == "all" else [args.service]
    dry_run = getattr(args, "dry_run", False)

    print("=" * 70)
    print("Amprealize PostgreSQL Migration")
    print("=" * 70)
    print()

    results = []
    for service in services:
        config = _MIGRATION_CONFIG[service]
        dsn = apply_host_overrides(os.environ.get(config["dsn_env"]), service.upper())

        print(f"Service: {service}")

        if not dsn:
            print(f"  ⏭️  Skipped: {config['dsn_env']} not set")
            results.append((service, "skipped", "DSN not configured"))
            print()
            continue

        # Check existing tables
        table_status = _check_service_tables(dsn, config["tables"])
        existing = sum(1 for v in table_status.values() if v)
        total = len(config["tables"])

        if existing == total:
            print(f"  ✅ Already migrated: {existing}/{total} tables exist")
            results.append((service, "exists", f"{existing}/{total} tables"))
            print()
            continue

        migration_path = _get_migration_path(config["migration"])
        print(f"  📄 Migration: {config['migration']}")
        print(f"  📊 Tables: {existing}/{total} exist")

        if dry_run:
            print(f"  🔍 Would apply migration (dry-run)")
            results.append((service, "pending", f"{total - existing} tables to create"))
        else:
            print(f"  ⏳ Applying migration...")
            if _apply_migration(dsn, migration_path):
                print(f"  ✅ Migration applied successfully")
                results.append((service, "applied", f"{total} tables created"))
            else:
                results.append((service, "failed", "See error above"))
        print()

    # Summary
    print("=" * 70)
    print("Migration Summary")
    print("=" * 70)
    for service, status, detail in results:
        status_icon = {
            "applied": "✅",
            "exists": "✅",
            "pending": "🔍",
            "skipped": "⏭️",
            "failed": "❌",
        }.get(status, "❓")
        print(f"  {status_icon} {service}: {status} ({detail})")

    failed = sum(1 for _, status, _ in results if status == "failed")
    return 1 if failed > 0 else 0


def _command_migrate_status(args: argparse.Namespace) -> int:
    """Check migration status for all services."""
    output_mode = _resolve_output_format(getattr(args, "format", None))

    status_data = []
    for service, config in _MIGRATION_CONFIG.items():
        dsn = apply_host_overrides(os.environ.get(config["dsn_env"]), service.upper())

        entry = {
            "service": service,
            "dsn_env": config["dsn_env"],
            "dsn_configured": bool(dsn),
            "migration_file": config["migration"],
            "tables": {},
            "status": "unconfigured",
        }

        if dsn:
            table_status = _check_service_tables(dsn, config["tables"])
            entry["tables"] = table_status
            existing = sum(1 for v in table_status.values() if v)
            total = len(config["tables"])

            if existing == total:
                entry["status"] = "migrated"
            elif existing > 0:
                entry["status"] = "partial"
            else:
                entry["status"] = "pending"

        status_data.append(entry)

    if output_mode == "json":
        _print_json(status_data)
    else:
        print("=" * 70)
        print("PostgreSQL Migration Status")
        print("=" * 70)
        print()

        for entry in status_data:
            status_icon = {
                "migrated": "✅",
                "partial": "⚠️",
                "pending": "🔄",
                "unconfigured": "⏭️",
            }.get(entry["status"], "❓")

            print(f"{status_icon} {entry['service']}")
            print(f"   Env: {entry['dsn_env']}")
            print(f"   Status: {entry['status']}")

            if entry["dsn_configured"] and entry["tables"]:
                existing = sum(1 for v in entry["tables"].values() if v)
                total = len(entry["tables"])
                print(f"   Tables: {existing}/{total}")
            print()

    return 0


# ─── Research Evaluation Commands ───────────────────────────────────────────────


def _command_research_evaluate(args: argparse.Namespace) -> int:
    """Evaluate a research paper or article for Amprealize integration."""
    import asyncio
    from amprealize.research_service import ResearchService
    from amprealize.research.report import render_report
    from amprealize.research_contracts import EvaluatePaperRequest

    async def run_evaluation():
        service = ResearchService(llm_model=args.model)

        # Run the full evaluation pipeline
        request = EvaluatePaperRequest(
            source=args.source,
            llm_model=args.model,
            save_to_db=not getattr(args, "no_save", False),
        )

        phase = getattr(args, "phase", "full")

        # Store title override for phase execution
        title_override = args.title

        if phase == "full":
            response = service.evaluate(request)

            if args.format == "json":
                import json
                import dataclasses

                def serialize(obj):
                    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
                        return dataclasses.asdict(obj)
                    elif hasattr(obj, 'value'):  # Enum
                        return obj.value
                    return str(obj)

                output = json.dumps(dataclasses.asdict(response), default=serialize, indent=2)
            else:
                output = render_report(
                    response.ingested_paper,
                    response.comprehension,
                    response.evaluation,
                    response.recommendation,
                )

            # Output
            if args.output:
                Path(args.output).write_text(output, encoding="utf-8")
                print(f"Report saved to: {args.output}")
            else:
                print(output)

            # Already saved if save_to_db=True in request
            if request.save_to_db:
                print(f"\n💾 Evaluation saved with paper_id: {response.paper_id}", file=sys.stderr)

            return 0
        else:
            # Run specific phase only
            import dataclasses
            from amprealize.research_contracts import IngestPaperRequest

            print(f"📄 [Ingest] Loading paper from: {args.source}", file=sys.stderr)
            ingest_request = IngestPaperRequest(
                source=args.source,
                title_override=title_override,
            )
            paper = service.ingest_paper(ingest_request)
            print(f"✓ [Ingest] Loaded: {paper.metadata.title} ({paper.word_count:,} words)", file=sys.stderr)

            if phase == "comprehend":
                print(f"🧠 [Comprehend] Analyzing with {service.llm_model}...", file=sys.stderr)
                result = service.comprehend_paper(paper)
                print(f"✓ [Comprehend] Complete. Novelty: {result.novelty_score}/10", file=sys.stderr)
                _print_json(dataclasses.asdict(result) if hasattr(result, '__dataclass_fields__') else result)
            elif phase == "evaluate":
                print(f"🧠 [Comprehend] Analyzing with {service.llm_model}...", file=sys.stderr)
                comprehension = service.comprehend_paper(paper)
                print(f"✓ [Comprehend] Complete.", file=sys.stderr)
                print(f"📊 [Evaluate] Scoring for Amprealize fit...", file=sys.stderr)
                result = service.evaluate_paper(comprehension)
                print(f"✓ [Evaluate] Overall score: {result.overall_score:.1f}/10", file=sys.stderr)
                _print_json(dataclasses.asdict(result) if hasattr(result, '__dataclass_fields__') else result)
            elif phase == "recommend":
                print(f"🧠 [Comprehend] Analyzing with {service.llm_model}...", file=sys.stderr)
                comprehension = service.comprehend_paper(paper)
                print(f"✓ [Comprehend] Complete.", file=sys.stderr)
                print(f"📊 [Evaluate] Scoring for Amprealize fit...", file=sys.stderr)
                evaluation = service.evaluate_paper(comprehension)
                print(f"✓ [Evaluate] Overall score: {evaluation.overall_score:.1f}/10", file=sys.stderr)
                print(f"🎯 [Recommend] Generating verdict...", file=sys.stderr)
                result = service.recommend(paper, comprehension, evaluation)
                print(f"✓ [Recommend] Verdict: {result.verdict.value}", file=sys.stderr)
                _print_json(dataclasses.asdict(result) if hasattr(result, '__dataclass_fields__') else result)

            return 0

    return asyncio.run(run_evaluation())


def _command_research_list(args: argparse.Namespace) -> int:
    """List previously evaluated papers."""
    import asyncio
    from amprealize.research_service import ResearchStorage
    from amprealize.research_contracts import Verdict

    async def run_list():
        storage = ResearchStorage()

        verdict_filter = None
        if args.verdict:
            verdict_filter = Verdict(args.verdict)

        papers = await storage.search_papers(
            verdict=verdict_filter,
            limit=args.limit,
        )

        if args.format == "json":
            _print_json([p.__dict__ if hasattr(p, '__dict__') else p for p in papers])
        else:
            if not papers:
                print("No evaluated papers found.")
                return 0

            # Table format
            print(f"{'ID':<36} {'Title':<40} {'Verdict':<8} {'Score':<6} {'Date'}")
            print("-" * 100)
            for p in papers:
                title = (p.title[:37] + "...") if len(p.title) > 40 else p.title
                print(f"{p.id:<36} {title:<40} {p.verdict:<8} {p.overall_score:<6.2f} {p.evaluated_at}")

        return 0

    return asyncio.run(run_list())


def _command_research_get(args: argparse.Namespace) -> int:
    """Get details of a previously evaluated paper."""
    import asyncio
    from amprealize.research_service import ResearchStorage
    from amprealize.research.report import render_report

    async def run_get():
        storage = ResearchStorage()

        result = await storage.get_paper(args.paper_id)

        if result is None:
            print(f"Paper not found: {args.paper_id}", file=sys.stderr)
            return 1

        paper, comprehension, evaluation, recommendation = result

        if args.format == "json":
            import dataclasses
            _print_json({
                "paper": dataclasses.asdict(paper),
                "comprehension": dataclasses.asdict(comprehension),
                "evaluation": dataclasses.asdict(evaluation),
                "recommendation": dataclasses.asdict(recommendation),
            })
        else:
            print(render_report(paper, comprehension, evaluation, recommendation))

        return 0

    return asyncio.run(run_get())


def _command_research_export(args: argparse.Namespace) -> int:
    """Export evaluations to file."""
    import asyncio
    from datetime import datetime
    from amprealize.research_service import ResearchStorage
    from amprealize.research.report import render_report
    from amprealize.research_contracts import Verdict

    async def run_export():
        storage = ResearchStorage()

        verdict_filter = None
        if args.verdict:
            verdict_filter = Verdict(args.verdict)

        papers = await storage.search_papers(verdict=verdict_filter, limit=1000)

        # Filter by date if specified
        if args.since:
            since_date = datetime.strptime(args.since, "%Y-%m-%d")
            papers = [p for p in papers if datetime.fromisoformat(p.evaluated_at) >= since_date]

        output_path = Path(args.output)

        if output_path.suffix == ".json":
            import json
            import dataclasses

            all_data = []
            for summary in papers:
                result = await storage.get_paper(summary.id)
                if result:
                    paper, comp, eval_, rec = result
                    all_data.append({
                        "paper": dataclasses.asdict(paper),
                        "comprehension": dataclasses.asdict(comp),
                        "evaluation": dataclasses.asdict(eval_),
                        "recommendation": dataclasses.asdict(rec),
                    })

            output_path.write_text(json.dumps(all_data, indent=2, default=str), encoding="utf-8")
        else:
            # Markdown export
            parts = ["# Research Evaluations Export\n"]
            for summary in papers:
                result = await storage.get_paper(summary.id)
                if result:
                    paper, comp, eval_, rec = result
                    parts.append(render_report(paper, comp, eval_, rec))
                    parts.append("\n---\n")

            output_path.write_text("\n".join(parts), encoding="utf-8")

        print(f"Exported {len(papers)} evaluations to: {output_path}")
        return 0

    return asyncio.run(run_export())


def _command_research_index(args: argparse.Namespace) -> int:
    """Regenerate the RESEARCH_INDEX.md file."""
    from amprealize.research_service import ResearchStorage

    storage = ResearchStorage()
    index_path = storage.update_research_index()

    if index_path:
        print(f"✓ Updated research index: {index_path}")
        return 0
    else:
        print("⚠️  No papers found or could not write to project directory")
        return 1


def _command_research_handoff(args: argparse.Namespace) -> int:
    """Create handoff work items for ADOPT/ADAPT evaluations."""
    from amprealize.research_service import ResearchService
    from amprealize.research_contracts import SearchPapersRequest, Verdict
    from amprealize.services.board_service import BoardService
    from amprealize.multi_tenant.board_contracts import CreateWorkItemRequest, WorkItemType, WorkItemPriority
    from amprealize.action_contracts import Actor

    project_id = args.project_id
    dry_run = args.dry_run
    paper_id = args.paper_id

    if not project_id:
        print("❌ --project-id is required", file=sys.stderr)
        print("\nTo find your project ID, run: amprealize board list-projects", file=sys.stderr)
        return 1

    research_service = ResearchService()
    papers_to_process = []

    # Get papers to process
    if paper_id and paper_id != "all":
        # Specific paper
        result = research_service.get_paper(paper_id)
        if not result:
            print(f"❌ Paper not found: {paper_id}", file=sys.stderr)
            return 1
        if result.recommendation.verdict not in [Verdict.ADOPT, Verdict.ADAPT]:
            print(f"⚠️  Paper {paper_id} has verdict {result.recommendation.verdict.value} - handoff only for ADOPT/ADAPT", file=sys.stderr)
            return 1
        papers_to_process = [result]
    else:
        # All ADOPT/ADAPT papers
        for verdict in [Verdict.ADOPT, Verdict.ADAPT]:
            search_result = research_service.search_papers(SearchPapersRequest(verdict=verdict))
            for summary in search_result.papers:
                full_paper = research_service.get_paper(summary.paper_id)
                if full_paper:
                    papers_to_process.append(full_paper)

    if not papers_to_process:
        print("ℹ️  No ADOPT/ADAPT papers found to create handoffs for")
        return 0

    print(f"📋 Found {len(papers_to_process)} paper(s) to create handoffs for")

    if dry_run:
        print("\n🔍 DRY RUN - would create:")
        for paper_result in papers_to_process:
            rec = paper_result.recommendation
            eval_ = paper_result.evaluation
            print(f"  • {paper_result.paper_title} ({paper_result.paper_id})")
            print(f"    Verdict: {rec.verdict.value} ({eval_.overall_score:.1f}/10)")
            print(f"    Next Agent: {rec.next_agent or 'architect'}")
        return 0

    # Initialize BoardService (handles its own connection pool)
    try:
        board_service = BoardService()
    except Exception as e:
        print(f"❌ Failed to connect to database: {e}", file=sys.stderr)
        print("Make sure PostgreSQL is running and DATABASE_URL is configured", file=sys.stderr)
        return 1

    # Get the first board for the project
    boards = board_service.list_boards(project_id=project_id)
    if not boards:
        print(f"❌ No boards found for project {project_id}", file=sys.stderr)
        return 1
    board = boards[0]

    # Get columns for the board
    columns = board_service.list_columns(board.board_id)
    if not columns:
        print(f"❌ Board {board.board_id} has no columns", file=sys.stderr)
        return 1
    first_column = columns[0]

    actor = Actor(id="research-agent", role="STUDENT", surface="cli")
    created_count = 0

    for paper_result in papers_to_process:
        try:
            rec = paper_result.recommendation
            eval_ = paper_result.evaluation
            comp = paper_result.comprehension
            next_agent = rec.next_agent or "architect"

            # Build work item
            work_item_request = CreateWorkItemRequest(
                board_id=board.board_id,
                column_id=first_column.column_id,
                title=f"[Research Handoff] {paper_result.paper_title}",
                description=f"""## Research Handoff

**Paper**: {paper_result.paper_title}
**Paper ID**: {paper_result.paper_id}
**Verdict**: {rec.verdict.value} ({eval_.overall_score:.1f}/10)
**Next Agent**: {next_agent}

### Summary
{comp.core_idea}

### Implementation Notes
{comp.proposed_solution or 'See full research report for details.'}

### Scores
- Relevance: {eval_.relevance_score}/10
- Feasibility: {eval_.feasibility_score}/10
- Novelty: {eval_.novelty_score}/10
- ROI: {eval_.roi_score}/10
- Safety: {eval_.safety_score}/10

---
*Auto-generated by Research Agent. Awaiting {next_agent} agent processing.*
""",
                item_type=WorkItemType.STORY,
                priority=WorkItemPriority.MEDIUM,
                labels=["research-handoff", next_agent, rec.verdict.value.lower()],
                metadata={
                    "paper_id": paper_result.paper_id,
                    "research_verdict": rec.verdict.value,
                    "overall_score": eval_.overall_score,
                    "next_agent": next_agent,
                    "source": "research-agent",
                },
            )

            work_item = board_service.create_work_item(work_item_request, actor)
            print(f"✓ Created work item {work_item.item_id} for: {paper_result.paper_title}")
            created_count += 1

        except Exception as e:
            print(f"❌ Failed to create work item for {paper_result.paper_id}: {e}", file=sys.stderr)

    print(f"\n✅ Created {created_count} handoff work item(s)")
    return 0


def _command_architect_list(args: argparse.Namespace) -> int:
    """List pending work items for the architect agent."""
    from amprealize.services.board_service import BoardService
    from amprealize.multi_tenant.board_contracts import WorkItemStatus

    project_id = args.project_id
    output_format = args.format

    try:
        board_service = BoardService()
    except Exception as e:
        print(f"❌ Failed to connect to database: {e}", file=sys.stderr)
        return 1

    # Find work items with 'architect' label
    work_items = board_service.list_work_items(
        project_id=project_id,
        labels=["architect"],
    )

    if not work_items:
        print("ℹ️  No work items pending for architect agent")
        return 0

    if output_format == "json":
        import json
        items_data = []
        for item in work_items:
            items_data.append({
                "item_id": item.item_id,
                "title": item.title,
                "status": item.status.value,
                "labels": item.labels,
                "metadata": item.metadata,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            })
        print(json.dumps(items_data, indent=2))
    else:
        print(f"📋 Found {len(work_items)} work item(s) for architect agent:\n")
        for item in work_items:
            paper_id = item.metadata.get("paper_id", "N/A") if item.metadata else "N/A"
            score = item.metadata.get("overall_score", "N/A") if item.metadata else "N/A"
            verdict = item.metadata.get("research_verdict", "N/A") if item.metadata else "N/A"
            print(f"  {item.item_id}")
            print(f"    Title:   {item.title}")
            print(f"    Status:  {item.status.value}")
            print(f"    Paper:   {paper_id}")
            print(f"    Score:   {score}/10")
            print(f"    Verdict: {verdict}")
            print()

    return 0


def _command_architect_pickup(args: argparse.Namespace) -> int:
    """Pick up and process a work item for the architect agent using LLM."""
    from amprealize.services.board_service import BoardService
    from amprealize.services.work_item_assignment import auto_assign_work_item, find_best_agent_for_work_item
    from amprealize.research_service import ResearchService
    from amprealize.research.codebase_analyzer import CodebaseAnalyzer
    from amprealize.multi_tenant.board_contracts import WorkItemStatus, UpdateWorkItemRequest
    from amprealize.multi_tenant.board_contracts import CreateWorkItemRequest, WorkItemType, WorkItemPriority
    from amprealize.multi_tenant.organization_service import OrganizationService
    from amprealize.action_contracts import Actor
    from amprealize.llm import LLMClient, LLMConfig, ProviderType
    from datetime import datetime
    from pathlib import Path
    import os
    import json
    import re

    work_item_id = args.work_item_id
    project_id = args.project_id
    dry_run = args.dry_run
    output_dir = args.output or "docs/adr"

    try:
        board_service = BoardService()
    except Exception as e:
        print(f"❌ Failed to connect to database: {e}", file=sys.stderr)
        return 1

    # If no specific work item, find the first pending one
    if not work_item_id:
        work_items = board_service.list_work_items(
            project_id=project_id,
            labels=["architect"],
            status=WorkItemStatus.BACKLOG,
        )
        if not work_items:
            print("ℹ️  No pending work items for architect agent")
            return 0
        work_item = work_items[0]
        work_item_id = work_item.item_id
    else:
        try:
            work_item = board_service.get_work_item(work_item_id)
        except Exception as e:
            print(f"❌ Work item not found: {work_item_id}", file=sys.stderr)
            return 1

    print(f"🏗️  Architect Agent (LLM-powered) picking up: {work_item.item_id}")
    print(f"   Title: {work_item.title}")

    # Extract paper_id from metadata
    if not work_item.metadata or "paper_id" not in work_item.metadata:
        print(f"❌ Work item missing paper_id in metadata", file=sys.stderr)
        return 1

    paper_id = work_item.metadata["paper_id"]
    print(f"   Paper ID: {paper_id}")

    # Load the full research evaluation
    research_service = ResearchService()
    paper_result = research_service.get_paper(paper_id)

    if not paper_result:
        print(f"❌ Research paper not found: {paper_id}", file=sys.stderr)
        return 1

    print(f"   Paper: {paper_result.paper_title}")
    print(f"   Verdict: {paper_result.recommendation.verdict.value}")
    print(f"   Score: {paper_result.evaluation.overall_score:.1f}/10")

    if dry_run:
        print("\n🔍 DRY RUN - would process:")
        print(f"  • Load research evaluation from {paper_id}")
        print(f"  • Analyze codebase with CodebaseAnalyzer")
        print(f"  • Load AGENT_ARCHITECT.md playbook")
        print(f"  • Call LLM for deep architectural analysis")
        print(f"  • Generate ADR in {output_dir}/")
        print(f"  • Create implementation work items")
        return 0

    # Update work item status to IN_PROGRESS
    actor = Actor(id="architect-agent", role="STRATEGIST", surface="cli")
    try:
        board_service.update_work_item(
            work_item_id,
            UpdateWorkItemRequest(status=WorkItemStatus.IN_PROGRESS),
            actor
        )
        print("\n📋 Status: IN_PROGRESS")
    except Exception as e:
        print(f"⚠️  Warning: Could not update status: {e}")

    # ═══════════════════════════════════════════════════════════════════════════
    # Phase 1: Deep Context Gathering
    # ═══════════════════════════════════════════════════════════════════════════
    print("\n" + "="*70)
    print("Phase 1: DEEP CONTEXT GATHERING")
    print("="*70)

    # 1.1 Load Architect Agent Playbook
    print("\n📖 Loading AGENT_ARCHITECT.md playbook...")
    project_root = Path(__file__).parent.parent
    architect_playbook_path = project_root / "docs" / "agents" / "AGENT_ARCHITECT.md"
    architect_playbook = ""
    if architect_playbook_path.exists():
        architect_playbook = architect_playbook_path.read_text(encoding="utf-8")
        print(f"   ✓ Loaded playbook ({len(architect_playbook)} chars)")
    else:
        print(f"   ⚠️ Playbook not found at {architect_playbook_path}")

    # 1.2 Analyze Codebase
    print("\n🔍 Analyzing codebase structure...")
    codebase_analyzer = CodebaseAnalyzer(project_root)
    codebase_snapshot = codebase_analyzer.get_structural_index()
    codebase_context = codebase_snapshot.to_context_string()
    print(f"   ✓ Found {len(codebase_snapshot.services)} services")
    print(f"   ✓ Found {len(codebase_snapshot.behaviors)} behaviors")
    print(f"   ✓ Found {len(codebase_snapshot.mcp_tools)} MCP tools")
    print(f"   ✓ Found {len(codebase_snapshot.db_tables)} database tables")

    # 1.3 Load AGENTS.md for behavior context
    print("\n📚 Loading AGENTS.md for behavior patterns...")
    agents_md_path = project_root / "AGENTS.md"
    agents_md_content = ""
    if agents_md_path.exists():
        # Only load the behaviors section to save tokens
        full_agents = agents_md_path.read_text(encoding="utf-8")
        behaviors_start = full_agents.find("## 📖 Behaviors")
        if behaviors_start != -1:
            agents_md_content = full_agents[behaviors_start:behaviors_start + 8000]
        else:
            agents_md_content = full_agents[:8000]
        print(f"   ✓ Loaded behavior patterns ({len(agents_md_content)} chars)")

    # 1.4 Check existing ADRs for precedent
    print("\n📁 Checking existing ADRs for design precedent...")
    adr_dir = Path(output_dir)
    adr_dir.mkdir(parents=True, exist_ok=True)
    existing_adrs = list(adr_dir.glob("ADR-*.md"))
    existing_adr_summaries = []
    for adr_file in existing_adrs[:5]:  # Only recent 5
        try:
            content = adr_file.read_text()[:500]  # First 500 chars
            existing_adr_summaries.append(f"### {adr_file.name}\n{content}")
        except Exception:
            pass
    print(f"   ✓ Found {len(existing_adrs)} existing ADRs")

    # ═══════════════════════════════════════════════════════════════════════════
    # Phase 2: Prepare Research Context
    # ═══════════════════════════════════════════════════════════════════════════
    print("\n" + "="*70)
    print("Phase 2: PREPARING RESEARCH CONTEXT")
    print("="*70)

    rec = paper_result.recommendation
    eval_ = paper_result.evaluation
    comp = paper_result.comprehension

    # Build comprehensive research summary
    research_context = f"""
## Research Paper Summary

**Title:** {paper_result.paper_title}
**Paper ID:** {paper_id}
**Verdict:** {rec.verdict.value} (Overall Score: {eval_.overall_score:.1f}/10)

### Core Idea
{comp.core_idea}

### Problem Addressed
{comp.problem_addressed}

### Proposed Solution
{comp.proposed_solution}

### Evaluation Scores
- Relevance to Amprealize: {eval_.relevance_score}/10 - {eval_.relevance_rationale}
- Feasibility: {eval_.feasibility_score}/10 - {eval_.feasibility_rationale}
- Novelty: {eval_.novelty_score}/10 - {eval_.novelty_rationale}
- ROI Potential: {eval_.roi_score}/10 - {eval_.roi_rationale}
- Safety: {eval_.safety_score}/10 - {eval_.safety_rationale}

### Implementation Complexity
- Implementation: {eval_.implementation_complexity}
- Maintenance Burden: {eval_.maintenance_burden}
- Expertise Gap: {eval_.expertise_gap}
- Estimated Effort: {eval_.estimated_effort}

### Concerns
{chr(10).join(f'- {c}' for c in eval_.concerns) if eval_.concerns else 'None identified'}

### Risks
{chr(10).join(f'- {r}' for r in eval_.risks) if eval_.risks else 'None identified'}

### Potential Benefits
{chr(10).join(f'- {b}' for b in eval_.potential_benefits) if eval_.potential_benefits else 'See core idea'}

### Verdict Rationale
{rec.verdict_rationale}
"""

    # Add implementation roadmap if available
    if rec.implementation_roadmap:
        roadmap = rec.implementation_roadmap
        research_context += f"""
### Implementation Roadmap from Research Agent

**Affected Components:**
"""
        for comp_item in (roadmap.affected_components or []):
            if isinstance(comp_item, dict):
                research_context += f"- {comp_item.get('path', 'Unknown')}: {comp_item.get('what_changes', '')}\n"
            else:
                research_context += f"- {comp_item}\n"

        research_context += "\n**Proposed Steps:**\n"
        for step in (roadmap.proposed_steps or []):
            if isinstance(step, dict):
                research_context += f"- [{step.get('effort', '?')}] {step.get('description', str(step))}\n"
            else:
                research_context += f"- {step}\n"

        if roadmap.success_criteria:
            research_context += "\n**Success Criteria:**\n"
            for criterion in roadmap.success_criteria:
                research_context += f"- {criterion}\n"

    print(f"   ✓ Prepared research context ({len(research_context)} chars)")

    # ═══════════════════════════════════════════════════════════════════════════
    # Phase 3: LLM-Powered Architectural Analysis
    # ═══════════════════════════════════════════════════════════════════════════
    print("\n" + "="*70)
    print("Phase 3: LLM-POWERED ARCHITECTURAL ANALYSIS")
    print("="*70)

    # Initialize LLM
    print("\n🤖 Initializing LLM for architectural analysis...")
    llm_model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    if not api_key:
        print("❌ ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 1

    config = LLMConfig(
        provider=ProviderType.ANTHROPIC,
        model=llm_model,
        api_key=api_key,
        max_tokens=8000,
        temperature=0.2,  # Low temperature for precise technical analysis
    )
    llm_client = LLMClient(config)
    print(f"   ✓ Using model: {llm_model}")

    # Build the architect prompt
    next_adr_num = len(existing_adrs) + 1

    architect_prompt = f"""You are a Staff+ Principal Architect analyzing research for integration into the Amprealize codebase.

{architect_playbook}

---

# YOUR TASK

Generate a comprehensive Architecture Decision Record (ADR) for integrating the following research into Amprealize.

{research_context}

---

# CODEBASE CONTEXT

{codebase_context}

---

# EXISTING BEHAVIORS (from AGENTS.md)

{agents_md_content[:4000]}

---

# EXISTING ADRs FOR PRECEDENT

{chr(10).join(existing_adr_summaries) if existing_adr_summaries else "No existing ADRs found."}

---

# OUTPUT REQUIREMENTS

Generate a complete ADR in markdown format. The ADR number should be {next_adr_num:04d}.

Your ADR MUST include:

1. **Concrete technical decisions** - Not "TBD", but actual design choices with rationale
2. **Code examples** - Actual Python code showing data models, API signatures, service methods
3. **At least 2-3 alternatives considered** for each major decision, with pros/cons
4. **Specific file paths** that need modification (reference the codebase context)
5. **Migration strategy** for any data model changes
6. **Trade-offs explicitly stated** - What are we giving up with this approach?
7. **Risk/mitigation table** with likelihood and impact ratings
8. **Phased implementation plan** with specific tasks and effort estimates

Remember: You are a senior architect. Don't just reformat the research - add your own technical insights, identify gaps the research didn't consider, and make opinionated decisions about the best integration approach for THIS codebase.

Output ONLY the ADR markdown content, starting with the # ADR header.
"""

    print("\n📤 Sending to LLM for architectural analysis...")
    print("   Streaming output (you'll see the ADR as it's generated):\n")
    print("-" * 70)

    try:
        messages = [
            {"role": "system", "content": architect_playbook},
            {"role": "user", "content": architect_prompt},
        ]

        # Stream callback to print chunks as they arrive
        char_count = [0]  # Use list to allow mutation in closure
        def stream_callback(chunk: str):
            print(chunk, end="", flush=True)
            char_count[0] += len(chunk)

        # Use streaming
        response = llm_client.stream_sync(
            messages, callback=stream_callback,
            max_tokens=8192, temperature=0.4,
        )

        adr_content = response.content
        print("\n" + "-" * 70)
        print(f"\n   ✓ Received ADR ({char_count[0]} chars, {response.output_tokens} tokens)")
        print(f"   ✓ Input tokens: {response.input_tokens}, Latency: {response.latency_ms:.0f}ms")
    except Exception as e:
        print(f"\n❌ LLM call failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1

    # ═══════════════════════════════════════════════════════════════════════════
    # Phase 4: Save ADR
    # ═══════════════════════════════════════════════════════════════════════════
    print("\n" + "="*70)
    print("Phase 4: SAVING ADR")
    print("="*70)

    # Create slug from paper title
    title_slug = paper_result.paper_title.lower()
    title_slug = re.sub(r'[^a-z0-9]+', '-', title_slug)[:50].strip('-')

    adr_filename = f"ADR-{next_adr_num:04d}-{title_slug}.md"
    adr_path = adr_dir / adr_filename

    # Add metadata footer if not present
    if "---" not in adr_content[-200:]:
        adr_content += f"""

---
*Generated by Architect Agent (LLM-powered) on {datetime.now().isoformat()}*
*Research Reference: {paper_id}*
*Work Item: {work_item_id}*
"""

    adr_path.write_text(adr_content)
    print(f"\n✅ Generated ADR: {adr_path}")

    # ═══════════════════════════════════════════════════════════════════════════
    # Phase 5: Work Item Decomposition
    # ═══════════════════════════════════════════════════════════════════════════
    print("\n" + "="*70)
    print("Phase 5: WORK ITEM DECOMPOSITION")
    print("="*70)

    # Extract implementation tasks from ADR using LLM
    extraction_prompt = f"""Extract implementation tasks from this ADR. Return a JSON array of work items.

ADR Content:
{adr_content[:6000]}

Return ONLY valid JSON in this format:
{{
  "story": {{
    "title": "Implementation story title (max 60 chars)",
    "description": "2-3 sentence description"
  }},
  "tasks": [
    {{
      "title": "Task title (max 50 chars)",
      "description": "What specifically needs to be done",
      "effort": "S|M|L",
      "files": ["path/to/file.py"]
    }}
  ]
}}

Extract 3-6 concrete tasks from the implementation plan in the ADR.
"""

    print("\n📤 Extracting work items from ADR...")
    try:
        extract_messages = [
            {"role": "user", "content": extraction_prompt},
        ]
        extract_response = llm_client.call(
            extract_messages, max_tokens=2048, temperature=0.2,
        )
        extraction_result = extract_response.content
        # Parse JSON from response (handle markdown code blocks)
        json_match = re.search(r'\{[\s\S]*\}', extraction_result)
        if json_match:
            work_items_data = json.loads(json_match.group())
        else:
            work_items_data = {"story": {"title": f"Implement: {paper_result.paper_title[:50]}", "description": "See ADR"}, "tasks": []}
    except Exception as e:
        print(f"   ⚠️ Could not extract work items: {e}")
        work_items_data = {"story": {"title": f"Implement: {paper_result.paper_title[:50]}", "description": "See ADR"}, "tasks": []}

    # Get board for creating work items
    boards = board_service.list_boards(project_id=work_item.project_id)
    if not boards:
        print("⚠️  No boards found, skipping work item creation")
    else:
        board = boards[0]
        columns = board_service.list_columns(board.board_id)
        first_column = columns[0] if columns else None

        if first_column:
            tasks_created = 0

            # Create implementation story
            story_data = work_items_data.get("story", {})
            impl_story_request = CreateWorkItemRequest(
                board_id=board.board_id,
                column_id=first_column.column_id,
                title=f"[Implementation] {story_data.get('title', paper_result.paper_title[:60])}",
                description=f"""## Implementation Story

{story_data.get('description', 'Implement the architectural design from the ADR.')}

### ADR Reference
- **ADR:** [{adr_filename}]({adr_path})
- **Research Paper:** {paper_result.paper_title}
- **Paper ID:** {paper_id}
- **Verdict:** {rec.verdict.value} ({eval_.overall_score:.1f}/10)

### Source
- Research Handoff: {work_item_id}
- Generated by: Architect Agent

---
See ADR for full technical design and implementation details.
""",
                item_type=WorkItemType.STORY,
                priority=WorkItemPriority.HIGH if eval_.overall_score >= 8 else WorkItemPriority.MEDIUM,
                labels=["engineering", "implementation", rec.verdict.value.lower()],
                parent_id=work_item_id,
                metadata={
                    "paper_id": paper_id,
                    "adr": adr_filename,
                    "source": "architect-agent",
                },
            )

            impl_story = board_service.create_work_item(impl_story_request, actor)
            print(f"\n✅ Created implementation story: {impl_story.item_id}")
            tasks_created += 1

            # Create individual tasks
            for task_data in work_items_data.get("tasks", [])[:6]:
                task_title = task_data.get("title", "Implementation task")[:50]
                task_desc = task_data.get("description", "")
                task_effort = task_data.get("effort", "M")
                task_files = task_data.get("files", [])

                task_request = CreateWorkItemRequest(
                    board_id=board.board_id,
                    column_id=first_column.column_id,
                    title=task_title,
                    description=f"""## Task: {task_title}

{task_desc}

### Effort Estimate
{task_effort}

### Files to Modify
{chr(10).join(f'- `{f}`' for f in task_files) if task_files else '- See ADR for details'}

### Parent Story
{impl_story.item_id}

### ADR Reference
{adr_filename}

### Done When
- [ ] Implementation complete
- [ ] Tests added/updated
- [ ] Code reviewed
""",
                    item_type=WorkItemType.TASK,
                    priority=WorkItemPriority.MEDIUM,
                    labels=["engineering", "implementation"],
                    parent_id=impl_story.item_id,
                    metadata={
                        "effort": task_effort,
                        "files": task_files,
                        "source": "architect-agent",
                    },
                )

                task = board_service.create_work_item(task_request, actor)
                print(f"   ✓ Created task: {task.item_id} - {task_title}")
                tasks_created += 1

            print(f"\n✅ Created {tasks_created} work item(s)")

            # ═══════════════════════════════════════════════════════════════════════
            # Auto-assign work items to relevant agents
            # ═══════════════════════════════════════════════════════════════════════
            print("\n📋 Auto-assigning work items to agents...")

            # Get project agents for assignment
            project_agents = []
            project_owner_id = None
            try:
                org_service = OrganizationService()
                # Get agents for this project
                if work_item.project_id:
                    # Try to get project's org_id from the board
                    project_agents = org_service.list_agents(
                        org_id="default",  # TODO: Get actual org_id from project
                        project_id=work_item.project_id,
                    )
                    if not project_agents:
                        # Fallback to all org agents
                        project_agents = org_service.list_agents(org_id="default")
            except Exception as e:
                print(f"   ⚠️ Could not load agents: {e}")

            if project_agents:
                print(f"   Found {len(project_agents)} agents for assignment")

                # Assign the implementation story
                if impl_story:
                    success, msg = auto_assign_work_item(
                        board_service, impl_story, project_agents,
                        project_owner_id=project_owner_id, actor=actor
                    )
                    print(f"   • Story: {msg}")

                # Re-fetch tasks and assign them
                created_items = board_service.list_work_items(
                    board_id=board.board_id,
                    parent_id=impl_story.item_id if impl_story else None,
                )
                for item in created_items:
                    success, msg = auto_assign_work_item(
                        board_service, item, project_agents,
                        project_owner_id=project_owner_id, actor=actor
                    )
                    print(f"   • {item.title[:40]}: {msg}")
            else:
                print("   ⚠️ No agents found for auto-assignment")

    # Mark original handoff work item as DONE
    try:
        board_service.update_work_item(
            work_item_id,
            UpdateWorkItemRequest(status=WorkItemStatus.DONE),
            actor
        )
        print(f"\n✅ Marked handoff work item {work_item_id} as DONE")
    except Exception as e:
        print(f"⚠️  Warning: Could not update status: {e}")

    print("\n" + "="*70)
    print("✅ ARCHITECT AGENT COMPLETE (LLM-Powered)")
    print("="*70)
    print(f"\nArtifacts created:")
    print(f"  • ADR: {adr_path}")
    print(f"  • Implementation work items in board")
    print(f"\nNext: Engineering Agent should pick up implementation story")

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)

    # Module gating -- early exit for disabled modules
    _gate_msg = _check_cli_module_enabled(getattr(args, "command", ""))
    if _gate_msg:
        print(_gate_msg, file=sys.stderr)
        return 1

    if args.command == "scan-secrets":
        return _command_scan_secrets(args)
    elif args.command == "record-action":
        return _command_record_action(args)
    elif args.command == "list-actions":
        return _command_list_actions(args)
    elif args.command == "get-action":
        return _command_get_action(args)
    elif args.command == "replay-actions":
        return _command_replay_actions(args)
    elif args.command == "replay-status":
        return _command_replay_status(args)
    elif args.command == "dr":
        return _command_dr(args)
    elif args.command == "tasks":
        return _command_list_tasks(args)
    elif args.command == "behaviors":
        if args.behaviors_command == "create":
            return _command_behaviors_create(args)
        elif args.behaviors_command == "list":
            return _command_behaviors_list(args)
        elif args.behaviors_command == "search":
            return _command_behaviors_search(args)
        elif args.behaviors_command == "get":
            return _command_behaviors_get(args)
        elif args.behaviors_command == "update":
            return _command_behaviors_update(args)
        elif args.behaviors_command == "submit":
            return _command_behaviors_submit(args)
        elif args.behaviors_command == "approve":
            return _command_behaviors_approve(args)
        elif args.behaviors_command == "deprecate":
            return _command_behaviors_deprecate(args)
        elif args.behaviors_command == "delete-draft":
            return _command_behaviors_delete_draft(args)
        elif args.behaviors_command == "propose":
            return _command_behaviors_propose(args)
        elif args.behaviors_command == "get-for-task":
            return _command_behaviors_get_for_task(args)
    elif args.command == "compliance":
        if args.compliance_command == "create-checklist":
            return _command_compliance_create_checklist(args)
        elif args.compliance_command == "record-step":
            return _command_compliance_record_step(args)
        elif args.compliance_command == "list":
            return _command_compliance_list(args)
        elif args.compliance_command == "get":
            return _command_compliance_get(args)
        elif args.compliance_command == "validate":
            return _command_compliance_validate(args)
        elif args.compliance_command == "policies":
            if hasattr(args, "policies_command") and args.policies_command == "list":
                return _command_compliance_policies_list(args)
            elif hasattr(args, "policies_command") and args.policies_command == "create":
                return _command_compliance_policies_create(args)
            elif hasattr(args, "policies_command") and args.policies_command == "get":
                return _command_compliance_policies_get(args)
        elif args.compliance_command == "audit":
            return _command_compliance_audit(args)
    elif args.command == "workflow":
        if args.workflow_command == "create-template":
            return _command_workflow_create_template(args)
        elif args.workflow_command == "list-templates":
            return _command_workflow_list_templates(args)
        elif args.workflow_command == "get-template":
            return _command_workflow_get_template(args)
        elif args.workflow_command == "run":
            return _command_workflow_run(args)
        elif args.workflow_command == "status":
            return _command_workflow_status(args)
    elif args.command == "breakeramp":
        if args.breakeramp_command == "plan":
            return _command_breakeramp_plan(args)
        elif args.breakeramp_command == "apply":
            return _command_breakeramp_apply(args)
        elif args.breakeramp_command == "status":
            return _command_breakeramp_status(args)
        elif args.breakeramp_command == "destroy":
            return _command_breakeramp_destroy(args)
        elif args.breakeramp_command == "bootstrap":
            return _command_breakeramp_bootstrap(args)
        elif args.breakeramp_command == "cleanup":
            return _command_breakeramp_cleanup(args)
        elif args.breakeramp_command == "machine":
            if not hasattr(args, "machine_command") or not args.machine_command:
                print("Usage: amprealize breakeramp machine {list,start,stop,ensure,status,resources}", file=sys.stderr)
                return 1
            if args.machine_command == "list":
                return _command_breakeramp_machine_list(args)
            elif args.machine_command == "start":
                return _command_breakeramp_machine_start(args)
            elif args.machine_command == "stop":
                return _command_breakeramp_machine_stop(args)
            elif args.machine_command == "ensure":
                return _command_breakeramp_machine_ensure(args)
            elif args.machine_command == "status":
                return _command_breakeramp_machine_status(args)
            elif args.machine_command == "resources":
                return _command_breakeramp_machine_resources(args)
            elif args.machine_command == "cleanup":
                return _command_breakeramp_machine_cleanup(args)
    elif args.command == "telemetry":
        if args.telemetry_command == "emit":
            return _command_telemetry_emit(args)
        elif args.telemetry_command == "query":
            return _command_telemetry_query(args)
        elif args.telemetry_command == "dashboard":
            return _command_telemetry_dashboard(args)
    elif args.command == "agents":
        if args.agents_command == "assign":
            return _command_agents_assign(args)
        elif args.agents_command == "status":
            return _command_agents_status(args)
        elif args.agents_command == "switch":
            return _command_agents_switch(args)
    elif args.command == "analytics":
        if args.analytics_command == "project":
            return _command_analytics_project(args)
        elif args.analytics_command == "kpi-summary":
            return _command_analytics_kpi_summary(args)
        elif args.analytics_command == "project-kpi":
            return _command_analytics_project_kpi(args)
        elif args.analytics_command == "behavior-usage":
            return _command_analytics_behavior_usage(args)
        elif args.analytics_command == "token-savings":
            return _command_analytics_token_savings(args)
        elif args.analytics_command == "compliance-coverage":
            return _command_analytics_compliance_coverage(args)
        elif args.analytics_command == "cost-by-service":
            return _command_analytics_cost_by_service(args)
        elif args.analytics_command == "cost-per-run":
            return _command_analytics_cost_per_run(args)
        elif args.analytics_command == "roi-summary":
            return _command_analytics_roi_summary(args)
        elif args.analytics_command == "daily-costs":
            return _command_analytics_daily_costs(args)
        elif args.analytics_command == "top-expensive":
            return _command_analytics_top_expensive(args)
    elif args.command == "metrics":
        if args.metrics_command == "summary":
            return _command_metrics_summary(args)
        elif args.metrics_command == "export":
            return _command_metrics_export(args)
    elif args.command == "auth":
        if args.auth_command == "ensure-grant":
            return _command_auth_ensure_grant(args)
        elif args.auth_command == "list-grants":
            return _command_auth_list_grants(args)
        elif args.auth_command == "policy-preview":
            return _command_auth_policy_preview(args)
        elif args.auth_command == "revoke":
            return _command_auth_revoke(args)
        elif args.auth_command == "register":
            return _command_auth_register(args)
        elif args.auth_command == "login":
            return _command_auth_login(args)
        elif args.auth_command == "status":
            return _command_auth_status(args)
        elif args.auth_command == "logout":
            return _command_auth_logout(args)
        elif args.auth_command == "refresh":
            return _command_auth_refresh(args)
        elif args.auth_command == "consent-lookup":
            return _command_auth_consent_lookup(args)
        elif args.auth_command == "consent-approve":
            return _command_auth_consent_approve(args)
        elif args.auth_command == "consent-deny":
            return _command_auth_consent_deny(args)
    elif args.command == "bci":
        if args.bci_command == "rebuild-index":
            return _command_bci_rebuild_index(args)
        elif args.bci_command == "retrieve":
            return _command_bci_retrieve(args)
        elif args.bci_command == "compose-prompt":
            return _command_bci_compose_prompt(args)
        elif args.bci_command == "validate-citations":
            return _command_bci_validate_citations(args)
        elif args.bci_command == "generate":
            return _command_bci_generate(args)
        elif args.bci_command == "improve":
            return _command_bci_improve(args)
        elif args.bci_command == "inject":
            return _command_bci_inject(args)
    elif args.command == "audit":
        if args.audit_command == "verify":
            return _command_audit_verify(args)
        elif args.audit_command == "list":
            return _command_audit_list(args)
        elif args.audit_command == "retention":
            return _command_audit_retention(args)
    elif args.command == "reflection":
        return _command_reflection(args)
    elif args.command == "migrate":
        if args.migrate_command == "apply":
            return _command_migrate_apply(args)
        elif args.migrate_command == "status":
            return _command_migrate_status(args)
    elif args.command == "research":
        if args.research_command == "evaluate":
            return _command_research_evaluate(args)
        elif args.research_command == "list":
            return _command_research_list(args)
        elif args.research_command == "get":
            return _command_research_get(args)
        elif args.research_command == "export":
            return _command_research_export(args)
        elif args.research_command == "index":
            return _command_research_index(args)
        elif args.research_command == "handoff":
            return _command_research_handoff(args)
    elif args.command == "architect":
        if args.architect_command == "pickup":
            return _command_architect_pickup(args)
        elif args.architect_command == "list":
            return _command_architect_list(args)
    elif args.command == "work-item":
        if args.wi_command == "execute":
            return _command_wi_execute(args)
        elif args.wi_command == "status":
            return _command_wi_status(args)
        elif args.wi_command == "clarify":
            return _command_wi_clarify(args)
        elif args.wi_command == "approve-gate":
            return _command_wi_approve_gate(args)
    elif args.command == "config":
        if args.config_command == "show":
            return _command_config_show(args)
        elif args.config_command == "set":
            return _command_config_set(args)
        elif args.config_command == "path":
            return _command_config_path(args)

    elif args.command == "context":
        if args.context_command == "current":
            return _command_context_current(args)
        elif args.context_command == "list":
            return _command_context_list(args)
        elif args.context_command == "use":
            return _command_context_use(args)
        elif args.context_command == "add":
            return _command_context_add(args)
        elif args.context_command == "remove":
            return _command_context_remove(args)

    elif args.command == "items":
        if args.items_command == "migrate":
            return _command_items_migrate(args)

    elif args.command == "db":
        if args.db_command == "migrate":
            return _command_db_migrate(args)
        elif args.db_command == "status":
            return _command_db_status(args)

    elif args.command == "knowledge-pack":
        if args.knowledge_pack_command == "build":
            return _command_knowledge_pack_build(args)
        elif args.knowledge_pack_command == "validate":
            return _command_knowledge_pack_validate(args)
        elif args.knowledge_pack_command == "inspect":
            return _command_knowledge_pack_inspect(args)
        elif args.knowledge_pack_command == "list":
            return _command_knowledge_pack_list(args)

    elif args.command == "flags":
        if args.flags_command == "list":
            return _command_flags_list(args)
        elif args.flags_command == "get":
            return _command_flags_get(args)
        elif args.flags_command == "set":
            return _command_flags_set(args)

    elif args.command == "pack":
        if args.pack_command == "bootstrap":
            return _command_pack_bootstrap(args)
        elif args.pack_command == "rollback":
            return _command_pack_rollback(args)
        elif args.pack_command == "status":
            return _command_pack_status(args)

    elif args.command == "init":
        return _command_init(args)

    elif args.command == "bootstrap":
        return _command_bootstrap(args)

    elif args.command == "mcp-server":
        mcp_cmd = getattr(args, "mcp_command", None)
        if mcp_cmd == "init":
            return _command_mcp_init(args)
        if mcp_cmd == "doctor":
            return _command_mcp_doctor(args)
        return _command_mcp_server(args)

    elif args.command == "open":
        return _command_open(args)

    elif args.command == "infra":
        return _command_infra(args)

    elif args.command == "doctor":
        return _command_doctor(args)

    elif args.command == "conversation":
        if args.conversation_command == "list":
            return _command_conversation_list(args)
        elif args.conversation_command == "get":
            return _command_conversation_get(args)
        elif args.conversation_command == "create":
            return _command_conversation_create(args)
        elif args.conversation_command == "archive":
            return _command_conversation_archive(args)
        elif args.conversation_command == "send":
            return _command_conversation_send(args)
        elif args.conversation_command == "messages":
            return _command_conversation_messages(args)
        elif args.conversation_command == "search":
            return _command_conversation_search(args)
        elif args.conversation_command == "react":
            return _command_conversation_react(args)
        elif args.conversation_command == "edit":
            return _command_conversation_edit(args)
        elif args.conversation_command == "delete":
            return _command_conversation_delete(args)
        elif args.conversation_command == "get-message":
            return _command_conversation_get_message(args)
        elif args.conversation_command == "pin":
            return _command_conversation_pin(args)
        elif args.conversation_command == "unpin":
            return _command_conversation_unpin(args)

    # If no command matched or no subcommand provided
    print("Error: No command specified or command not recognized", file=sys.stderr)
    return 1


# ==============================================================================
# Knowledge Pack CLI Commands
# ==============================================================================


def _command_knowledge_pack_build(args: argparse.Namespace) -> int:
    """Build a knowledge pack from registered sources."""
    from amprealize.knowledge_pack.builder import PackBuilder, PackBuildConfig
    from amprealize.knowledge_pack.source_registry import SourceRegistryService

    try:
        registry = SourceRegistryService()
        builder = PackBuilder(
            registry=registry,
            primer_template_path=args.primer_template,
        )

        config = PackBuildConfig(
            pack_id=args.pack_id,
            version=args.version,
            profile=args.profile,
            token_budget=args.token_budget,
        )

        artifact = builder.build(config)

        # Optionally write to output directory
        if args.output_dir:
            import os

            os.makedirs(args.output_dir, exist_ok=True)
            manifest_path = os.path.join(args.output_dir, f"{artifact.pack_id}_{artifact.version}_manifest.json")
            with open(manifest_path, "w", encoding="utf-8") as f:
                f.write(artifact.manifest.model_dump_json(indent=2))
            print(f"✅ Wrote manifest to {manifest_path}", file=sys.stderr)

        output = {
            "pack_id": artifact.pack_id,
            "version": artifact.version,
            "profile": artifact.profile,
            "token_budget_used": artifact.token_budget_used,
            "overlay_count": len(artifact.manifest.overlays),
            "source_count": len(artifact.manifest.sources),
            "primer_hash": artifact.manifest.primer_hash,
            "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
        }

        if args.format == "table":
            print(f"Pack ID:        {output['pack_id']}")
            print(f"Version:        {output['version']}")
            print(f"Profile:        {output['profile']}")
            print(f"Token Budget:   {output['token_budget_used']}")
            print(f"Overlays:       {output['overlay_count']}")
            print(f"Sources:        {output['source_count']}")
            print(f"Primer Hash:    {output['primer_hash'][:16]}...")
        else:
            print(json.dumps(output, indent=2, default=str))
        return 0

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _command_knowledge_pack_validate(args: argparse.Namespace) -> int:
    """Validate a knowledge pack manifest file."""
    from amprealize.knowledge_pack.validator import ManifestValidator, ValidationIssue, ValidationSeverity
    from amprealize.knowledge_pack.schema import KnowledgePackManifest

    try:
        with open(args.manifest_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        manifest = KnowledgePackManifest.model_validate(raw_data)
        validator = ManifestValidator()
        issues = validator.validate(manifest)

        errors = [i for i in issues if i.severity == ValidationSeverity.ERROR]
        warnings = [i for i in issues if i.severity == ValidationSeverity.WARNING]

        if args.format == "table":
            if not issues:
                print("✅ Manifest is valid with no issues")
            else:
                print(f"{'ERROR' if errors else 'WARNING'}: Found {len(errors)} error(s), {len(warnings)} warning(s)")
                for issue in issues:
                    icon = "❌" if issue.severity == ValidationSeverity.ERROR else "⚠️"
                    print(f"  {icon} [{issue.code}] {issue.message}")
                    if issue.path:
                        print(f"     at path: {issue.path}")
        else:
            output = {
                "valid": len(errors) == 0 and (not args.strict or len(warnings) == 0),
                "error_count": len(errors),
                "warning_count": len(warnings),
                "issues": [
                    {
                        "severity": i.severity.value,
                        "code": i.code,
                        "message": i.message,
                        "path": i.path,
                    }
                    for i in issues
                ],
            }
            print(json.dumps(output, indent=2))

        # Exit code: 1 if errors or (strict mode and warnings)
        if errors or (args.strict and warnings):
            return 1
        return 0

    except json.JSONDecodeError as exc:
        print(f"Error: Invalid JSON in manifest file: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError:
        print(f"Error: Manifest file not found: {args.manifest_path}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _command_knowledge_pack_inspect(args: argparse.Namespace) -> int:
    """Inspect an existing knowledge pack."""
    from amprealize.knowledge_pack.source_registry import SourceRegistryService

    try:
        registry = SourceRegistryService()

        # Get pack info - this would typically query a storage layer
        # For now we provide a basic implementation querying registry
        pack_id = args.pack_id
        version = args.version

        if not pack_id:
            print("Error: --pack-id is required", file=sys.stderr)
            return 1

        # Query sources for this pack
        sources = registry.list_sources(scope=pack_id, limit=100)

        output: Dict[str, Any] = {
            "pack_id": pack_id,
            "version": version or "latest",
            "source_count": len(sources),
        }

        if args.show_sources:
            output["sources"] = [
                {
                    "source_id": s.source_id,
                    "source_type": s.source_type.value,
                    "ref": s.ref,
                    "scope": s.scope,
                    "version_hash": s.version_hash,
                }
                for s in sources
            ]

        if args.show_overlays:
            # Would need to query overlay metadata from pack storage
            output["overlay_summary"] = {
                "note": "Overlay breakdown requires built pack. Use 'build' then 'inspect' on output."
            }

        if args.format == "table":
            print(f"Pack ID:      {output['pack_id']}")
            print(f"Version:      {output['version']}")
            print(f"Sources:      {output['source_count']}")
            if args.show_sources and "sources" in output:
                print("\nSources:")
                for s in output["sources"]:
                    print(f"  - {s['source_type']}: {s['ref']} ({s['scope']})")
        else:
            print(json.dumps(output, indent=2, default=str))

        return 0

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _command_knowledge_pack_list(args: argparse.Namespace) -> int:
    """List available knowledge packs."""
    from amprealize.knowledge_pack.source_registry import SourceRegistryService

    try:
        registry = SourceRegistryService()

        # Get unique scopes (pack_ids) from sources
        # In a full implementation, this would query a packs table
        sources = registry.list_sources(limit=args.limit * 10)  # Over-fetch to dedupe

        # Group by scope to get pack summary
        packs: Dict[str, Dict[str, Any]] = {}
        for source in sources:
            scope = source.scope or "default"
            if args.pack_id and scope != args.pack_id:
                continue
            if scope not in packs:
                packs[scope] = {
                    "pack_id": scope,
                    "source_count": 0,
                    "latest_update": source.updated_at,
                }
            packs[scope]["source_count"] += 1
            if source.updated_at and (
                not packs[scope]["latest_update"]
                or source.updated_at > packs[scope]["latest_update"]
            ):
                packs[scope]["latest_update"] = source.updated_at

        results = list(packs.values())[: args.limit]

        if args.format == "table":
            if not results:
                print("No knowledge packs found")
            else:
                print(f"{'Pack ID':<30} {'Sources':<10} {'Last Updated':<25}")
                print("-" * 65)
                for pack in results:
                    updated = pack["latest_update"].isoformat() if pack["latest_update"] else "N/A"
                    print(f"{pack['pack_id']:<30} {pack['source_count']:<10} {updated:<25}")
        else:
            output = [
                {
                    "pack_id": p["pack_id"],
                    "source_count": p["source_count"],
                    "latest_update": p["latest_update"].isoformat() if p["latest_update"] else None,
                }
                for p in results
            ]
            print(json.dumps(output, indent=2))

        return 0

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


# ==============================================================================
# Feature Flags CLI Commands (T4.4.1)
# ==============================================================================

def _command_flags_list(args: argparse.Namespace) -> int:
    """List all registered feature flags."""
    from amprealize.feature_flags import FeatureFlagService

    svc = FeatureFlagService()
    flags = svc.list_flags()

    if args.format == "json":
        print(json.dumps([f.to_dict() for f in flags], indent=2))
    else:
        if not flags:
            print("No feature flags registered")
        else:
            print(f"{'Name':<42} {'Type':<12} {'Enabled':<9} {'%':<5} {'Users'}")
            print("-" * 85)
            for f in flags:
                users = ",".join(f.user_list[:3])
                if len(f.user_list) > 3:
                    users += f"… (+{len(f.user_list) - 3})"
                print(f"{f.name:<42} {f.flag_type.value:<12} {str(f.enabled):<9} {f.percentage:<5} {users}")
    return 0


def _command_flags_get(args: argparse.Namespace) -> int:
    """Get a single feature flag."""
    from amprealize.feature_flags import FeatureFlagService

    svc = FeatureFlagService()
    flag = svc.get_flag(args.flag_name)

    if flag is None:
        print(f"Flag not found: {args.flag_name}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(flag.to_dict(), indent=2))
    else:
        print(f"Name:        {flag.name}")
        print(f"Type:        {flag.flag_type.value}")
        print(f"Enabled:     {flag.enabled}")
        print(f"Percentage:  {flag.percentage}")
        print(f"User list:   {flag.user_list}")
        print(f"Description: {flag.description}")
        if flag.metadata:
            print(f"Metadata:    {json.dumps(flag.metadata)}")
    return 0


def _command_flags_set(args: argparse.Namespace) -> int:
    """Update a feature flag."""
    from amprealize.feature_flags import FeatureFlagService

    svc = FeatureFlagService()

    kwargs: Dict[str, Any] = {}
    if args.enabled is not None:
        kwargs["enabled"] = args.enabled
    if args.percentage is not None:
        kwargs["percentage"] = args.percentage
    if args.user_list is not None:
        kwargs["user_list"] = args.user_list

    if not kwargs:
        print("No changes specified. Use --enabled, --percentage, or --user-list.", file=sys.stderr)
        return 1

    flag = svc.set_flag(args.flag_name, **kwargs)

    if args.format == "json":
        print(json.dumps(flag.to_dict(), indent=2))
    else:
        print(f"Updated flag '{flag.name}': enabled={flag.enabled}, type={flag.flag_type.value}, percentage={flag.percentage}")
    return 0


# ==============================================================================
# Pack CLI Commands (bootstrap / rollback / status)
# ==============================================================================


def _command_pack_bootstrap(args: argparse.Namespace) -> int:
    """Bootstrap a knowledge pack for an existing workspace."""
    from amprealize.bootstrap.pack_migration import PackMigrationService
    from amprealize.bootstrap.profile import WorkspaceProfile

    profile = WorkspaceProfile(args.profile) if args.profile else None

    svc = PackMigrationService()
    result = svc.bootstrap(
        workspace_path=args.workspace,
        profile=profile,
        force=args.force,
    )

    if args.format == "json":
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(f"Workspace: {result.workspace_path}")
        print(f"Storage:   {result.storage.backend.value}")
        if result.profile:
            print(f"Profile:   {result.profile.value}")
        print(f"Pack:      {result.pack_id}@{result.pack_version}")
        print(f"Activated: {'yes' if result.activated else 'no'}")
        if result.files_written:
            print(f"Files:     {', '.join(result.files_written)}")
        if result.notes:
            print("\nNotes:")
            for note in result.notes:
                print(f"  - {note}")
    return 0


def _command_pack_rollback(args: argparse.Namespace) -> int:
    """Deactivate the active pack and restore pre-pack behaviour."""
    from amprealize.bootstrap.pack_migration import PackMigrationService

    svc = PackMigrationService()
    result = svc.rollback(workspace_path=args.workspace)

    if args.format == "json":
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(f"Workspace: {result.workspace_path}")
        if result.previous_pack_id:
            print(f"Previous:  {result.previous_pack_id}")
        print(f"Rolled back: {'yes' if result.deactivated else 'no'}")
        if result.notes:
            for note in result.notes:
                print(f"  - {note}")
    return 0


def _command_pack_status(args: argparse.Namespace) -> int:
    """Show workspace storage and pack activation status."""
    from amprealize.bootstrap.storage_detector import detect_storage_backend

    storage = detect_storage_backend(args.workspace)

    if args.format == "json":
        print(json.dumps(storage.to_dict(), indent=2))
    else:
        print(f"Storage backend:   {storage.backend.value}")
        if storage.path_or_dsn:
            print(f"Path/DSN:          {storage.path_or_dsn}")
        print(f"Feature flags:     {'present' if storage.has_feature_flags_table else 'not found'}")
        print(f"Activations table: {'present' if storage.has_activations_table else 'not found'}")
        print(f"Can migrate:       {'yes' if storage.can_migrate else 'no'}")
        if storage.reason:
            print(f"Note:              {storage.reason}")
    return 0


# ==============================================================================
# Config CLI Commands
# ==============================================================================


def _command_config_show(args: argparse.Namespace) -> int:
    """Display the fully resolved configuration."""
    from amprealize.config.loader import load_config

    cfg = load_config()
    data = cfg.model_dump()

    if getattr(args, "format", "yaml") == "json":
        print(json.dumps(data, indent=2, default=str))
    else:
        print(yaml.dump(data, default_flow_style=False, sort_keys=False))
    return 0


def _command_config_set(args: argparse.Namespace) -> int:
    """Set a config value in the user config file."""
    from amprealize.config.loader import set_config_value

    try:
        cfg = set_config_value(args.key, args.value)
        print(f"✅ Set {args.key} = {args.value}")
        print(f"   Config saved to ~/.amprealize/config.yaml")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


def _command_config_path(args: argparse.Namespace) -> int:
    """Print the user config file path."""
    from amprealize.config.loader import USER_CONFIG_PATH

    print(str(USER_CONFIG_PATH))
    return 0


# ==============================================================================
# Context CLI Commands
# ==============================================================================


def _command_context_current(args: argparse.Namespace) -> int:
    """Show the active context."""
    from amprealize.context import get_current_context, get_context_indicator

    name, cfg = get_current_context()
    indicator = get_context_indicator()

    print(f"Current context: {name} {indicator}")
    print(f"  Backend: {cfg.storage.backend}")

    if cfg.storage.backend == "postgres":
        dsn = cfg.storage.postgres.dsn
        # Mask password
        if "@" in dsn:
            prefix, rest = dsn.split("@", 1)
            if ":" in prefix:
                proto_user = prefix.rsplit(":", 1)[0]
                dsn = f"{proto_user}:****@{rest}"
        print(f"  DSN: {dsn}")
    elif cfg.storage.backend == "sqlite":
        print(f"  Path: {cfg.storage.sqlite.path}")

    return 0


def _command_context_list(args: argparse.Namespace) -> int:
    """List all available contexts."""
    from amprealize.context import list_contexts

    contexts = list_contexts()
    output_format = getattr(args, "format", "table")

    if output_format == "json":
        import json
        data = [
            {
                "name": c.name,
                "is_current": c.is_current,
                "storage_backend": c.storage_backend,
                "storage_location": c.storage_location,
                "port": c.port,
                "is_valid": c.is_valid,
                "validation_error": c.validation_error,
                "has_port_conflict": c.has_port_conflict,
                "conflict_with": c.conflict_with,
            }
            for c in contexts
        ]
        print(json.dumps(data, indent=2))
        return 0

    # Table format
    if not contexts:
        print("No contexts configured.")
        print("Run 'amprealize context add <name>' to create one.")
        return 0

    print("\nAMPREALIZE CONTEXTS")
    print("=" * 70)

    for ctx in contexts:
        # Current indicator
        marker = "→" if ctx.is_current else " "

        # Status icons
        status_parts = []
        if not ctx.is_valid:
            status_parts.append(f"⚠️ {ctx.validation_error}")
        if ctx.has_port_conflict:
            status_parts.append(f"⚡ port conflict with '{ctx.conflict_with}'")

        status = " | ".join(status_parts) if status_parts else "✓"

        print(f"\n{marker} {ctx.name}")
        print(f"    Backend:  {ctx.storage_backend}")
        print(f"    Location: {ctx.storage_location}")
        if ctx.port:
            print(f"    Port:     {ctx.port}")
        print(f"    Status:   {status}")

    print("\n" + "=" * 70)
    current = next((c.name for c in contexts if c.is_current), None)
    print(f"Current: {current or '(none)'}")
    print(f"Use 'amprealize context use <name>' to switch contexts.")

    return 0


def _command_context_use(args: argparse.Namespace) -> int:
    """Switch to a named context."""
    from amprealize.context import use_context, get_context_indicator

    success, message = use_context(args.name)

    if success:
        indicator = get_context_indicator()
        print(f"✅ {message}")
        print(f"   Context indicator: {indicator}")
        return 0
    else:
        print(f"❌ {message}", file=sys.stderr)
        return 1


def _command_context_add(args: argparse.Namespace) -> int:
    """Create a new named context."""
    from amprealize.context import add_context

    success, message = add_context(
        name=args.name,
        storage_backend=args.backend,
        dsn=getattr(args, "dsn", None),
        sqlite_path=getattr(args, "sqlite_path", None),
    )

    if success:
        print(f"✅ {message}")
        print(f"   Use 'amprealize context use {args.name}' to switch to it.")
        return 0
    else:
        print(f"❌ {message}", file=sys.stderr)
        return 1


def _command_context_remove(args: argparse.Namespace) -> int:
    """Remove a named context."""
    from amprealize.context import remove_context

    success, message = remove_context(args.name)

    if success:
        print(f"✅ {message}")
        return 0
    else:
        print(f"❌ {message}", file=sys.stderr)
        return 1


# ==============================================================================
# Items CLI Commands
# ==============================================================================


def _command_items_migrate(args: argparse.Namespace) -> int:
    """Migrate work items from one context to another."""
    import json
    from amprealize.migration import (
        MigrationEngine,
        FilterExpression,
        ConflictResolution,
        format_migration_summary,
        format_items_table,
        default_progress,
        quiet_progress,
    )
    from amprealize.multi_tenant.board_contracts import WorkItemType, WorkItemStatus

    # Build filter expression from args
    filter_parts = []
    if args.filter:
        filter_parts.append(args.filter)
    if args.project:
        filter_parts.append(f"project={args.project}")
    if args.board:
        filter_parts.append(f"board={args.board}")
    if hasattr(args, 'type') and args.type:
        filter_parts.append(f"type={args.type}")
    if args.status:
        filter_parts.append(f"status={args.status}")

    filter_expr_str = ",".join(filter_parts) if filter_parts else None
    filter_expr = FilterExpression.parse(filter_expr_str)

    # Map conflict resolution
    conflict_map = {
        "skip": ConflictResolution.SKIP,
        "overwrite": ConflictResolution.OVERWRITE,
        "rename": ConflictResolution.RENAME,
        "fail": ConflictResolution.FAIL,
    }
    conflict_resolution = conflict_map.get(args.on_conflict, ConflictResolution.SKIP)

    # Create engine
    progress_cb = quiet_progress if args.quiet else default_progress
    engine = MigrationEngine(
        source_context=args.source,
        target_context=args.target,
        dry_run=args.dry_run,
        conflict_resolution=conflict_resolution,
        progress_callback=progress_cb,
    )

    # Validate contexts
    valid, errors = engine.validate_contexts()
    if not valid:
        for error in errors:
            print(f"❌ {error}", file=sys.stderr)
        return 1

    # Preview items to migrate
    if not args.quiet:
        print(f"\n📋 Migration Preview")
        print(f"   Source: {args.source}")
        print(f"   Target: {args.target}")
        if filter_expr_str:
            print(f"   Filter: {filter_expr_str}")
        print()

    try:
        items = engine.list_source_items(filter_expr, org_id=args.org)
    except Exception as e:
        print(f"❌ Failed to list items from source: {e}", file=sys.stderr)
        return 1

    if not items:
        print("No items match the specified criteria.")
        return 0

    # Show preview
    if not args.quiet:
        print(f"Found {len(items)} item(s) to migrate:")
        print(format_items_table(items))
        print()

    # Confirm unless --yes
    if not args.yes and not args.dry_run:
        try:
            confirm = input(f"Proceed with migration? [y/N] ").strip().lower()
            if confirm not in ("y", "yes"):
                print("Migration cancelled.")
                return 0
        except (KeyboardInterrupt, EOFError):
            print("\nMigration cancelled.")
            return 0

    # Execute migration
    if args.dry_run:
        print("\n🔍 DRY RUN - No changes will be made\n")

    try:
        report = engine.migrate(
            filter_expr=filter_expr,
            org_id=args.org,
            migrate_boards=not args.no_boards,
        )
    except Exception as e:
        print(f"❌ Migration failed: {e}", file=sys.stderr)
        return 1

    # Print summary
    if not args.quiet:
        print(format_migration_summary(report))

    # Save report to file if requested
    if args.output:
        try:
            with open(args.output, "w") as f:
                json.dump(report.to_dict(), f, indent=2)
            print(f"\n📄 Report saved to: {args.output}")
        except Exception as e:
            print(f"⚠️  Failed to save report: {e}", file=sys.stderr)

    # Return code based on results
    if report.failed > 0:
        return 1
    return 0


# ==============================================================================
# DB CLI Commands
# ==============================================================================


def _command_db_migrate(args: argparse.Namespace) -> int:
    """Apply pending SQLite migrations."""
    from amprealize.config.loader import load_config
    from amprealize.storage.sqlite_pool import SQLitePool
    from amprealize.storage.sqlite_migrations import run_migrations

    cfg = load_config()
    if cfg.storage.backend != "sqlite":
        print(f"Error: db migrate only works with SQLite backend (current: {cfg.storage.backend})", file=sys.stderr)
        return 1

    pool = SQLitePool(dsn=cfg.storage.sqlite.path)
    try:
        applied = run_migrations(pool)
        if applied:
            for version, name in applied:
                print(f"  ✅ Applied migration {version:03d}: {name}")
            print(f"\n{len(applied)} migration(s) applied.")
        else:
            print("Database is up to date — no pending migrations.")
    finally:
        pool.close()
    return 0


def _command_db_status(args: argparse.Namespace) -> int:
    """Show applied and pending migrations."""
    from amprealize.config.loader import load_config
    from amprealize.storage.sqlite_pool import SQLitePool
    from amprealize.storage.sqlite_migrations import discover_migrations

    cfg = load_config()
    if cfg.storage.backend != "sqlite":
        print(f"Error: db status only works with SQLite backend (current: {cfg.storage.backend})", file=sys.stderr)
        return 1

    pool = SQLitePool(dsn=cfg.storage.sqlite.path)
    try:
        applied_versions = set(pool.get_applied_migrations())
        all_migrations = discover_migrations()

        print(f"Database: {pool.db_path}")
        print(f"Backend:  sqlite\n")

        if not all_migrations:
            print("No migrations found.")
            return 0

        for version, name, _sql in all_migrations:
            status = "✅ applied" if version in applied_versions else "⬜ pending"
            print(f"  {version:03d}  {name:30s}  {status}")

        applied_count = sum(1 for v, _, _ in all_migrations if v in applied_versions)
        pending_count = len(all_migrations) - applied_count
        print(f"\n{applied_count} applied, {pending_count} pending.")
    finally:
        pool.close()
    return 0


# ==============================================================================
# Init (Project Scaffolding) CLI Command
# ==============================================================================


_PROJECT_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


def _validate_project_name(name: str) -> str:
    """Validate project name: alphanumeric, hyphens, underscores. No leading dash."""
    name = name.strip()
    if not name:
        raise ValueError("Project name cannot be empty")
    if not _PROJECT_NAME_RE.match(name):
        raise ValueError(
            f"Invalid project name '{name}'. "
            "Use alphanumeric characters, hyphens, and underscores only."
        )
    return name


def _prompt(label: str, default: str, choices: Optional[List[str]] = None) -> str:
    """Interactive prompt with default value and optional choices."""
    if choices:
        choices_str = "/".join(choices)
        raw = input(f"  {label} [{choices_str}] (default: {default}): ").strip()
    else:
        raw = input(f"  {label} (default: {default}): ").strip()
    return raw if raw else default


def _resolve_modules_flag(value: str) -> tuple[str, ...]:
    """Parse ``--modules`` flag into a tuple of module names.

    Accepts a preset name (e.g. ``full``) or comma-separated module names
    (e.g. ``goals,agents``).  Always ensures ``goals`` is included.
    """
    from amprealize.module_registry import PRESETS, MODULE_REGISTRY

    value = value.strip()
    # Try as preset first
    if value in PRESETS:
        return PRESETS[value]
    # Otherwise treat as comma-separated module names
    names = tuple(n.strip() for n in value.split(",") if n.strip())
    unknown = [n for n in names if n not in MODULE_REGISTRY]
    if unknown:
        raise SystemExit(f"Error: Unknown modules: {', '.join(unknown)}")
    if "goals" not in names:
        names = ("goals",) + names
    return names


def _prompt_modules() -> tuple[str, ...]:
    """Interactive module picker — show available modules and presets."""
    from amprealize.module_registry import MODULE_REGISTRY, PRESETS

    print("\n  📦 Module Selection")
    print("     Presets: goals (minimal), goals-agents, goals-behaviors, full (all)")
    print("     Available modules:")
    for mod in MODULE_REGISTRY.values():
        tag = " [always on]" if mod.always_enabled else ""
        tag = " [enterprise]" if mod.enterprise_only else tag
        print(f"       • {mod.name}: {mod.description}{tag}")

    raw = _prompt("Modules (preset or comma-separated)", "goals",
                  ["goals", "goals-agents", "goals-behaviors", "full"])
    return _resolve_modules_flag(raw)


def _render_config_yaml(
    project_name: str,
    storage_backend: str,
    auth_mode: str,
    postgres_dsn: str = "",
    workspace_profile: str = "solo-dev",
    enabled_modules: tuple[str, ...] = ("goals",),
    deployment_mode: str = "local",
) -> str:
    """Render a .amprealize/config.yaml from the selected options."""
    import yaml

    config: Dict[str, Any] = {
        "version": 1,
        "project": {"name": project_name, "workspace_profile": workspace_profile},
        "server": {"host": "0.0.0.0", "port": 8765},
        "storage": {"backend": storage_backend},
        "auth": {"mode": auth_mode},
        "mcp": {"transport": "stdio"},
        "infra": {"managed_by": "auto"},
        "logging": {"level": "INFO", "format": "json"},
        "modules": {
            "goals": True,
            "agents": "agents" in enabled_modules,
            "behaviors": "behaviors" in enabled_modules,
        },
        "deployment": {
            "mode": deployment_mode,
        },
    }

    if storage_backend == "sqlite":
        config["storage"]["sqlite"] = {"path": ".amprealize/data/amprealize.db"}
    elif storage_backend == "postgres":
        config["storage"]["postgres"] = {
            "dsn": postgres_dsn or "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize"
        }

    header = (
        "# Amprealize Project Configuration\n"
        "# Generated by `amprealize init`\n"
        "# Docs: https://docs.amprealize.dev/config\n\n"
    )
    return header + yaml.dump(config, default_flow_style=False, sort_keys=False)


def _render_agents_md(project_name: str) -> str:
    """Render a starter AGENTS.md from the bundled template."""
    from datetime import date

    template_path = Path(__file__).parent / "templates" / "AGENTS.md.starter"
    if template_path.exists():
        content = template_path.read_text(encoding="utf-8")
        return content.replace("{{ date }}", date.today().isoformat())
    # Inline fallback if template file is missing
    return (
        f"# Agent Handbook — {project_name}\n\n"
        "> Retrieve behaviors before starting any task. "
        "Propose new behaviors when patterns repeat 3+ times.\n\n"
        "## Behaviors\n\n"
        "_Add project-specific behaviors here._\n"
    )


def _command_init(args: argparse.Namespace) -> int:
    """Scaffold a new Amprealize project in the current directory."""
    from amprealize.bootstrap.detector import WorkspaceDetector
    from amprealize.bootstrap.service import BootstrapService
    from amprealize.bootstrap.profile import WorkspaceProfile

    amprealize_dir = Path(".amprealize")
    template = getattr(args, "template", "full")
    non_interactive = getattr(args, "non_interactive", False)
    detect_only = getattr(args, "detect_only", False)
    skip_pack = getattr(args, "skip_pack", False)
    cli_profile = getattr(args, "profile", None)

    # ── Workspace detection ────────────────────────────────────────────────
    detector = WorkspaceDetector()
    detection = detector.detect(Path.cwd())

    if detect_only:
        print("\n🔍 Workspace Detection Result\n")
        print(f"  Profile:    {detection.profile.value}")
        print(f"  Confidence: {detection.confidence:.0%}")
        if detection.is_ambiguous and detection.runner_up:
            print(f"  Runner-up:  {detection.runner_up.value} (ambiguous)")
        print("\n  Signals:")
        for sig in detection.signals:
            marker = "✅" if sig.detected else "  "
            print(f"    {marker} {sig.signal_name}: {sig.evidence}")
        print()
        return 0

    # Determine workspace profile
    if cli_profile:
        workspace_profile = WorkspaceProfile(cli_profile)
    elif non_interactive:
        workspace_profile = detection.profile
    else:
        # Interactive: show detection and let user confirm
        print(f"\n🔍 Detected workspace profile: {detection.profile.value} ({detection.confidence:.0%} confidence)")
        if detection.is_ambiguous and detection.runner_up:
            print(f"   Also considered: {detection.runner_up.value}")
        profile_choices = [p.value for p in WorkspaceProfile]
        chosen = _prompt("Workspace profile", detection.profile.value, profile_choices)
        workspace_profile = WorkspaceProfile(chosen)

    # ── Detect existing project ────────────────────────────────────────────
    if amprealize_dir.exists():
        if non_interactive:
            print("⚠️  .amprealize/ already exists. Use interactive mode to merge.", file=sys.stderr)
            return 1
        answer = input("  .amprealize/ already exists. Overwrite config? [y/N]: ").strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted.")
            return 0

    # ── Collect options ────────────────────────────────────────────────────
    default_name = Path.cwd().name
    cli_name = getattr(args, "name", None)
    cli_storage = getattr(args, "storage", None)
    cli_auth = getattr(args, "auth", None)
    cli_modules = getattr(args, "modules", None)
    cli_deployment = getattr(args, "deployment", None)

    if non_interactive or cli_name:
        # Non-interactive: use flags or defaults
        project_name = cli_name or default_name
        storage_backend = cli_storage or "sqlite"
        auth_mode = cli_auth or "local"
        gen_ide = template == "full"
        gen_agents = template == "full"
        postgres_dsn = ""
        # Resolve modules from flag or default
        enabled_modules = _resolve_modules_flag(cli_modules) if cli_modules else ("goals",)
        deployment_mode = cli_deployment or "local"
    else:
        # Interactive wizard
        print("\n🚀 Amprealize Project Setup\n")

        raw_name = _prompt("Project name", default_name)
        try:
            project_name = _validate_project_name(raw_name)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        storage_backend = _prompt("Storage backend", "sqlite", ["sqlite", "postgres"])
        if storage_backend not in ("sqlite", "postgres"):
            print(f"Error: Invalid storage backend '{storage_backend}'", file=sys.stderr)
            return 1

        postgres_dsn = ""
        if storage_backend == "postgres":
            postgres_dsn = _prompt(
                "PostgreSQL DSN",
                "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize",
            )

        auth_mode = _prompt("Auth mode", "local", ["local", "cloud"])
        if auth_mode not in ("local", "cloud"):
            print(f"Error: Invalid auth mode '{auth_mode}'", file=sys.stderr)
            return 1

        # Module selection
        if cli_modules:
            enabled_modules = _resolve_modules_flag(cli_modules)
        else:
            enabled_modules = _prompt_modules()

        # Deployment mode
        if cli_deployment:
            deployment_mode = cli_deployment
        else:
            deployment_mode = _prompt("Deployment mode", "local", ["local", "cloud", "hybrid"])
            if deployment_mode not in ("local", "cloud", "hybrid"):
                print(f"Error: Invalid deployment mode '{deployment_mode}'", file=sys.stderr)
                return 1

        gen_ide_raw = _prompt("Generate IDE configs? (.vscode/mcp.json, etc.)", "y", ["y", "n"])
        gen_ide = gen_ide_raw.lower() in ("y", "yes")

        gen_agents_raw = _prompt("Generate AGENTS.md?", "y", ["y", "n"])
        gen_agents = gen_agents_raw.lower() in ("y", "yes")

    # Validate modules
    from amprealize.module_registry import validate_module_dependencies
    dep_errors = validate_module_dependencies(enabled_modules)
    if dep_errors:
        for err in dep_errors:
            print(f"Error: {err}", file=sys.stderr)
        return 1

    # Validate project name
    try:
        project_name = _validate_project_name(project_name)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    # ── Scaffold ───────────────────────────────────────────────────────────
    print(f"\n📁 Scaffolding project: {project_name}\n")

    # .amprealize/config.yaml
    amprealize_dir.mkdir(parents=True, exist_ok=True)
    config_path = amprealize_dir / "config.yaml"
    config_content = _render_config_yaml(
        project_name, storage_backend, auth_mode, postgres_dsn,
        workspace_profile=workspace_profile.value,
        enabled_modules=enabled_modules,
        deployment_mode=deployment_mode,
    )
    config_path.write_text(config_content, encoding="utf-8")
    print(f"  ✅ Created .amprealize/config.yaml")

    # .amprealize/data/ directory (and empty db placeholder for sqlite)
    data_dir = amprealize_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    if storage_backend == "sqlite":
        db_path = data_dir / "amprealize.db"
        if not db_path.exists():
            # Create an empty file; actual schema applied by `amprealize db migrate`
            db_path.touch()
            print(f"  ✅ Created .amprealize/data/amprealize.db (run `amprealize db migrate` to apply schema)")
        else:
            print(f"  ⏭️  .amprealize/data/amprealize.db already exists, skipping")

    # AGENTS.md (profile-scoped primer)
    if gen_agents:
        agents_path = Path("AGENTS.md")
        if agents_path.exists():
            print(f"  ⏭️  AGENTS.md already exists, skipping")
        else:
            # Use BootstrapService for profile-scoped primer
            bootstrap_svc = BootstrapService()
            agents_content = bootstrap_svc.get_primer_template(workspace_profile)
            # Substitute date placeholder
            from datetime import date
            agents_content = agents_content.replace("{{ date }}", date.today().isoformat())
            agents_path.write_text(agents_content, encoding="utf-8")
            print(f"  ✅ Created AGENTS.md (profile: {workspace_profile.value})")

    # IDE MCP configs (reuse D3 logic from _command_mcp_init)
    if gen_ide:
        _generate_ide_configs()

    # ── Summary ────────────────────────────────────────────────────────────
    print(f"\n🎉 Project '{project_name}' initialized!\n")
    print(f"  Workspace profile: {workspace_profile.value}")
    print(f"  Modules:           {', '.join(enabled_modules)}")
    print(f"  Deployment:        {deployment_mode}")
    print("\nNext steps:")
    print(f"  1. Review .amprealize/config.yaml")
    if storage_backend == "sqlite":
        print(f"  2. Run `amprealize db migrate` to create database tables")
    print(f"  3. Run `amprealize mcp-server` to start the MCP server")
    if gen_agents:
        print(f"  4. Customize AGENTS.md with project-specific behaviors")
    print()
    return 0


def _generate_ide_configs() -> None:
    """Generate MCP client configuration files (shared by init and mcp-server init)."""
    for rel_path, config_data in _build_ide_mcp_configs():
        target = Path(rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            print(f"  ⏭️  {rel_path} already exists, skipping")
            continue
        target.write_text(json.dumps(config_data, indent=2) + "\n")
        print(f"  ✅ Created {rel_path}")

    codex_targets = [
        Path.home() / ".codex" / "config.toml",
        Path(".codex") / "config.toml",
    ]
    for codex_config_path in codex_targets:
        try:
            status = _upsert_codex_mcp_server_config(codex_config_path)
        except OSError as exc:
            print(
                f"  ⚠️  Failed to update {codex_config_path}: {exc}",
                file=sys.stderr,
            )
            continue

        if status == "created":
            print(f"  ✅ Created {codex_config_path}")
        elif status == "updated":
            print(f"  ✅ Updated {codex_config_path}")
        else:
            print(f"  ⏭️  {codex_config_path} already up to date")


# ==============================================================================
# Bootstrap Commands (workspace profiling - MCP parity)
# ==============================================================================


def _command_bootstrap(args: argparse.Namespace) -> int:
    """Handle bootstrap command group."""
    bootstrap_cmd = getattr(args, "bootstrap_command", None)

    if bootstrap_cmd is None:
        print("Usage: amprealize bootstrap {detect,status,init}", file=sys.stderr)
        return 1

    if bootstrap_cmd == "detect":
        return _command_bootstrap_detect(args)
    elif bootstrap_cmd == "status":
        return _command_bootstrap_status(args)
    elif bootstrap_cmd == "init":
        return _command_bootstrap_init(args)
    else:
        print(f"Unknown bootstrap command: {bootstrap_cmd}", file=sys.stderr)
        return 1


def _command_bootstrap_detect(args: argparse.Namespace) -> int:
    """Detect workspace profile by analyzing project structure."""
    from amprealize.bootstrap.detector import WorkspaceDetector

    workspace_path = Path(getattr(args, "path", ".")).resolve()
    output_format = getattr(args, "format", "table")

    if not workspace_path.exists():
        print(f"Error: Path does not exist: {workspace_path}", file=sys.stderr)
        return 1

    detector = WorkspaceDetector()
    detection = detector.detect(workspace_path)

    if output_format == "json":
        result = {
            "profile": detection.profile.value,
            "confidence": round(detection.confidence, 4),
            "is_ambiguous": detection.is_ambiguous,
            "runner_up": detection.runner_up.value if detection.runner_up else None,
            "signals": [
                {
                    "signal_name": s.signal_name,
                    "detected": s.detected,
                    "evidence": s.evidence,
                }
                for s in detection.signals
            ],
        }
        print(json.dumps(result, indent=2))
    else:
        # Table format
        print("\n🔍 Workspace Detection Result\n")
        print(f"  Profile:    {detection.profile.value}")
        print(f"  Confidence: {detection.confidence:.0%}")
        if detection.is_ambiguous and detection.runner_up:
            print(f"  Runner-up:  {detection.runner_up.value} (ambiguous)")
        print("\n  Signals:")
        for sig in detection.signals:
            marker = "✅" if sig.detected else "  "
            print(f"    {marker} {sig.signal_name}: {sig.evidence}")
        print()

    return 0


def _command_bootstrap_status(args: argparse.Namespace) -> int:
    """Show bootstrap status for workspace."""
    workspace_path = Path(getattr(args, "path", ".")).resolve()
    output_format = getattr(args, "format", "table")

    if not workspace_path.exists():
        print(f"Error: Path does not exist: {workspace_path}", file=sys.stderr)
        return 1

    agents_md = workspace_path / "AGENTS.md"
    amprealize_dir = workspace_path / ".amprealize"
    manifest_path = amprealize_dir / "pack-manifest.json"
    config_path = amprealize_dir / "config.yaml"

    is_bootstrapped = agents_md.exists() or amprealize_dir.exists()

    # Try to read profile from config
    profile = None
    if config_path.exists():
        try:
            import yaml
            with open(config_path) as f:
                config = yaml.safe_load(f)
                profile = config.get("workspace_profile")
        except Exception:
            pass

    # Try to read pack info from manifest
    pack_id = None
    pack_version = None
    last_updated = None
    if manifest_path.exists():
        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
                pack_id = manifest.get("pack_id")
                pack_version = manifest.get("version")
                last_updated = manifest.get("installed_at")
        except Exception:
            pass

    # Detect profile from workspace signals if not found in config
    if is_bootstrapped and profile is None:
        from amprealize.bootstrap.detector import WorkspaceDetector
        detector = WorkspaceDetector()
        detection = detector.detect(workspace_path)
        profile = detection.profile.value

    # Get last_updated from file timestamps if not from manifest
    if last_updated is None:
        from datetime import datetime
        timestamps = []
        for f in [agents_md, amprealize_dir / "runtime-primer.md", manifest_path]:
            if f.exists():
                timestamps.append(f.stat().st_mtime)
        if timestamps:
            last_updated = datetime.fromtimestamp(max(timestamps)).isoformat()

    if output_format == "json":
        result = {
            "is_bootstrapped": is_bootstrapped,
            "profile": profile,
            "pack_id": pack_id,
            "pack_version": pack_version,
            "agents_md_exists": agents_md.exists(),
            "amprealize_dir_exists": amprealize_dir.exists(),
            "last_updated": last_updated,
        }
        print(json.dumps(result, indent=2))
    else:
        # Table format
        print("\n📊 Bootstrap Status\n")
        status_icon = "✅" if is_bootstrapped else "❌"
        print(f"  Status:     {status_icon} {'Bootstrapped' if is_bootstrapped else 'Not bootstrapped'}")
        print(f"  Profile:    {profile or 'N/A'}")
        print(f"  AGENTS.md:  {'✅ exists' if agents_md.exists() else '❌ missing'}")
        print(f"  .amprealize/:  {'✅ exists' if amprealize_dir.exists() else '❌ missing'}")
        if pack_id:
            print(f"  Pack:       {pack_id} v{pack_version or '?'}")
        if last_updated:
            print(f"  Updated:    {last_updated}")
        print()

    return 0


def _command_bootstrap_init(args: argparse.Namespace) -> int:
    """Initialize workspace with Amprealize (MCP-parity wrapper for BootstrapService)."""
    from amprealize.bootstrap.service import BootstrapService
    from amprealize.bootstrap.profile import WorkspaceProfile

    workspace_path = Path(getattr(args, "path", ".")).resolve()
    output_format = getattr(args, "format", "table")
    cli_profile = getattr(args, "profile", None)
    skip_primer = getattr(args, "skip_primer", False)
    skip_pack = getattr(args, "skip_pack", False)
    force = getattr(args, "force", False)

    if not workspace_path.exists():
        print(f"Error: Path does not exist: {workspace_path}", file=sys.stderr)
        return 1

    # Parse profile override
    profile_override = None
    if cli_profile:
        try:
            profile_override = WorkspaceProfile(cli_profile)
        except ValueError:
            print(f"Error: Invalid profile '{cli_profile}'", file=sys.stderr)
            return 1

    service = BootstrapService()
    result = service.bootstrap(
        workspace_path,
        profile=profile_override,
        skip_primer=skip_primer,
        skip_pack=skip_pack,
    )

    if output_format == "json":
        output = result.to_dict()
        output["success"] = True
        print(json.dumps(output, indent=2))
    else:
        # Table format
        print(f"\n✅ Bootstrap Complete\n")
        print(f"  Profile:  {result.profile.value}")
        print(f"  Pack ID:  {result.pack_id or 'none'}")
        if result.files_written:
            print("\n  Files written:")
            for f in result.files_written:
                print(f"    • {f}")
        if result.notes:
            print("\n  Notes:")
            for note in result.notes:
                print(f"    • {note}")
        print()

    return 0


# ==============================================================================
# Infrastructure Management (provider-agnostic)
# ==============================================================================

_PROFILE_BLUEPRINTS: dict[str, str] = {
    "minimal": "postgres.timescale.test",
    "standard": "local-dev",
    "full": "production",
}

_PROFILE_COMPOSE_FILES: dict[str, list[str]] = {
    "minimal": ["docker-compose.postgres.yml"],
    "standard": ["docker-compose.postgres.yml"],
    "full": ["docker-compose.postgres.yml", "docker-compose.test.yml"],
}


def _detect_infra_provider() -> str:
    """Auto-detect the best available infrastructure provider.

    Priority: breakeramp (if installed) → docker compose → none.
    """
    import shutil

    if shutil.which("breakeramp"):
        return "breakeramp"

    if shutil.which("docker") or shutil.which("podman"):
        return "docker-compose"

    return "none"


def _resolve_provider(args: argparse.Namespace) -> str:
    """Resolve which infra provider to use.

    Priority: CLI --provider flag → config managed_by → auto-detect.
    """
    cli_override = getattr(args, "provider", None)
    if cli_override and cli_override != "auto":
        return cli_override

    from amprealize.config.loader import load_config

    cfg = load_config()
    configured = cfg.infra.managed_by

    if configured != "auto":
        return configured

    return _detect_infra_provider()


def _run_breakeramp(breakeramp_args: list[str]) -> int:
    """Delegate to the breakeramp CLI."""
    import shutil
    import subprocess

    exe = shutil.which("breakeramp")
    if exe is None:
        print(
            "Error: breakeramp CLI not found.\n"
            "Install it with: pip install breakeramp[cli]",
            file=sys.stderr,
        )
        return 1
    result = subprocess.run([exe, *breakeramp_args])
    return result.returncode


def _find_compose_executable() -> list[str] | None:
    """Find a working compose command.

    Returns the base command list (e.g. ``["docker", "compose"]`` or
    ``["podman-compose"]``) or *None* if nothing is available.
    """
    import shutil
    import subprocess

    for engine in ("docker", "podman"):
        exe = shutil.which(engine)
        if exe:
            try:
                subprocess.run(
                    [exe, "compose", "version"],
                    capture_output=True,
                    timeout=10,
                )
                return [exe, "compose"]
            except (subprocess.SubprocessError, FileNotFoundError):
                pass

    for legacy in ("docker-compose", "podman-compose"):
        exe = shutil.which(legacy)
        if exe:
            return [exe]

    return None


def _run_compose(
    compose_args: list[str],
    *,
    compose_files: list[str] | None = None,
    project_name: str = "amprealize",
    profiles: list[str] | None = None,
) -> int:
    """Execute a docker/podman compose command."""
    import subprocess
    from pathlib import Path

    cmd = _find_compose_executable()
    if cmd is None:
        print(
            "Error: No compose tool found.\n"
            "Install Docker Desktop, Podman, or docker-compose.",
            file=sys.stderr,
        )
        return 1

    infra_dir = Path(__file__).resolve().parent.parent / "infra"

    full_cmd = list(cmd)
    full_cmd.extend(["--project-name", project_name])

    if compose_files:
        for cf in compose_files:
            full_cmd.extend(["-f", str(infra_dir / cf)])
    else:
        full_cmd.extend(["-f", str(infra_dir / "docker-compose.postgres.yml")])

    if profiles:
        for p in profiles:
            full_cmd.extend(["--profile", p])

    full_cmd.extend(compose_args)

    result = subprocess.run(full_cmd)
    return result.returncode


def _infra_via_breakeramp(action: str, args: argparse.Namespace) -> int:
    """Handle infra actions through the breakeramp provider."""
    if action == "up":
        profile = getattr(args, "profile", "standard")
        blueprint = _PROFILE_BLUEPRINTS.get(profile, "local-dev")
        print(f"🚀 Starting infrastructure via breakeramp (profile: {profile})...")
        return _run_breakeramp(["up", "--blueprint", blueprint])

    if action == "down":
        print("🛑 Stopping infrastructure (breakeramp)...")
        return _run_breakeramp(["stop"])

    if action == "status":
        return _run_breakeramp(["list"])

    if action == "resources":
        return _run_breakeramp(["resources"])

    if action == "reset":
        confirm = input(
            "⚠️  This will DESTROY all infrastructure data and recreate from scratch.\n"
            "Type 'yes' to confirm: "
        )
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            return 0
        print("♻️  Resetting infrastructure (breakeramp)...")
        return _run_breakeramp(["fresh"])

    print(f"Unknown infra action: {action}", file=sys.stderr)
    return 1


def _infra_via_compose(action: str, args: argparse.Namespace) -> int:
    """Handle infra actions through docker/podman compose."""
    from amprealize.config.loader import load_config

    cfg = load_config()
    compose_cfg = cfg.infra.compose
    project_name = compose_cfg.project_name
    profiles = compose_cfg.profiles or None

    if action == "up":
        profile = getattr(args, "profile", "standard")
        files = _PROFILE_COMPOSE_FILES.get(profile, ["docker-compose.postgres.yml"])

        if compose_cfg.file:
            files = [compose_cfg.file]

        print(f"🚀 Starting infrastructure via compose (profile: {profile})...")
        return _run_compose(
            ["up", "-d", "--wait"],
            compose_files=files,
            project_name=project_name,
            profiles=profiles,
        )

    if action == "down":
        print("🛑 Stopping infrastructure (compose)...")
        return _run_compose(
            ["down"],
            project_name=project_name,
            profiles=profiles,
        )

    if action == "status":
        return _run_compose(
            ["ps", "--format", "table"],
            project_name=project_name,
            profiles=profiles,
        )

    if action == "resources":
        return _run_compose(
            ["top"],
            project_name=project_name,
            profiles=profiles,
        )

    if action == "reset":
        confirm = input(
            "⚠️  This will DESTROY all infrastructure data and recreate from scratch.\n"
            "Type 'yes' to confirm: "
        )
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            return 0
        print("♻️  Resetting infrastructure (compose)...")
        rc = _run_compose(
            ["down", "-v", "--remove-orphans"],
            project_name=project_name,
            profiles=profiles,
        )
        if rc != 0:
            return rc
        return _run_compose(
            ["up", "-d", "--wait"],
            project_name=project_name,
            profiles=profiles,
        )

    print(f"Unknown infra action: {action}", file=sys.stderr)
    return 1


def _infra_via_external(action: str, _args: argparse.Namespace) -> int:
    """Handle infra actions when provider is external/none."""
    if action == "status":
        print("ℹ️  Infrastructure is externally managed. No status available.")
        return 0
    print(
        f"ℹ️  Infrastructure provider is set to external/none.\n"
        f"   The '{action}' command is not available.\n"
        f"   Manage your infrastructure directly or switch provider:\n"
        f"     amprealize infra configure",
        file=sys.stderr,
    )
    return 1


def _command_infra_configure() -> int:
    """Interactively select and persist an infrastructure provider."""
    from amprealize.config.loader import set_config_value

    print("\n🔧 Infrastructure Provider Configuration\n")
    print("  Choose how amprealize manages local infrastructure:\n")
    choices = [
        ("auto", "Auto-detect best available (recommended)"),
        ("breakeramp", "BreakerAmp — full orchestration with blueprints"),
        ("docker-compose", "Docker/Podman Compose — lightweight, direct compose files"),
        ("external", "External — you manage infrastructure yourself"),
        ("none", "None — disable infrastructure management"),
    ]
    for i, (key, desc) in enumerate(choices, 1):
        print(f"    {i}) {key:17s} {desc}")

    print()
    while True:
        raw = input("  Select [1-5] (default: 1): ").strip()
        if raw == "":
            selection = 0
            break
        try:
            selection = int(raw) - 1
            if 0 <= selection < len(choices):
                break
        except ValueError:
            pass
        print("  Invalid choice. Enter 1-5.")

    provider, desc = choices[selection]
    set_config_value("infra.managed_by", provider)
    print(f"\n  ✅ Infrastructure provider set to: {provider}")
    print(f"     ({desc})")
    print(f"     Saved to ~/.amprealize/config.yaml\n")
    return 0


def _command_infra(args: argparse.Namespace) -> int:
    """Provider-agnostic infrastructure management."""
    action = getattr(args, "infra_action", None)

    if action is None:
        print(
            "Usage: amprealize infra {up,down,status,resources,reset,configure}\n"
            "       amprealize infra --provider <provider> <action>",
            file=sys.stderr,
        )
        return 1

    if action == "configure":
        return _command_infra_configure()

    provider = _resolve_provider(args)

    if action == "status":
        print(f"📦 Infrastructure provider: {provider}\n")

    if provider == "breakeramp":
        return _infra_via_breakeramp(action, args)
    elif provider == "docker-compose":
        return _infra_via_compose(action, args)
    elif provider in ("external", "none"):
        return _infra_via_external(action, args)
    else:
        print(f"Unknown provider: {provider}", file=sys.stderr)
        return 1


# ==============================================================================
# Conversation CLI Commands
# ==============================================================================


def _render_conversations_table(data: Dict[str, Any]) -> None:
    """Render a table of conversations."""
    convs = data.get("conversations", [])
    if not convs:
        print("No conversations found.")
        return
    total = data.get("total", len(convs))
    print(f"\nConversations ({len(convs)} of {total}):\n")
    header = f"{'ID':<38} {'Scope':<14} {'Title':<30} {'Participants':<13} {'Archived':<9} {'Updated'}"
    print(header)
    print("-" * len(header))
    for c in convs:
        title = (c.get("title") or "(untitled)")[:30]
        updated = (c.get("updated_at") or "")[:19]
        print(
            f"{c['id']:<38} {c.get('scope', ''):<14} {title:<30} "
            f"{c.get('participant_count', 0):<13} {str(c.get('is_archived', False)):<9} {updated}"
        )


def _render_conversation_detail(data: Dict[str, Any]) -> None:
    """Render a single conversation's details."""
    print(f"\nConversation: {data['id']}")
    print(f"  Project:      {data.get('project_id', '')}")
    print(f"  Scope:        {data.get('scope', '')}")
    print(f"  Title:        {data.get('title') or '(untitled)'}")
    print(f"  Created by:   {data.get('created_by', '')}")
    print(f"  Participants: {data.get('participant_count', 0)}")
    print(f"  Archived:     {data.get('is_archived', False)}")
    print(f"  Created:      {(data.get('created_at') or '')[:19]}")
    print(f"  Updated:      {(data.get('updated_at') or '')[:19]}")
    if data.get("pinned_message_id"):
        print(f"  Pinned msg:   {data['pinned_message_id']}")


def _render_messages_table(data: Dict[str, Any]) -> None:
    """Render a table of messages."""
    msgs = data.get("messages", [])
    if not msgs:
        print("No messages found.")
        return
    total = data.get("total", len(msgs))
    has_more = data.get("has_more", False)
    print(f"\nMessages ({len(msgs)} of {total}, more={has_more}):\n")
    header = f"{'ID':<38} {'Sender':<20} {'Type':<14} {'Replies':<8} {'Time':<20} {'Content'}"
    print(header)
    print("-" * min(len(header) + 40, 160))
    for m in msgs:
        content = (m.get("content") or "")[:50].replace("\n", " ")
        created = (m.get("created_at") or "")[:19]
        reactions_str = ""
        if m.get("reactions"):
            emojis = [r["emoji"] for r in m["reactions"]]
            reactions_str = f" [{', '.join(emojis)}]"
        print(
            f"{m['id']:<38} {m.get('sender_id', '')[:20]:<20} "
            f"{m.get('message_type', 'text'):<14} {m.get('reply_count', 0):<8} "
            f"{created:<20} {content}{reactions_str}"
        )


def _render_message_detail(data: Dict[str, Any]) -> None:
    """Render a single message detail."""
    print(f"\nMessage: {data['id']}")
    print(f"  Conversation: {data.get('conversation_id', '')}")
    print(f"  Sender:       {data.get('sender_id', '')} ({data.get('sender_type', '')})")
    print(f"  Type:         {data.get('message_type', 'text')}")
    print(f"  Created:      {(data.get('created_at') or '')[:19]}")
    if data.get("is_edited"):
        print(f"  Edited:       {(data.get('edited_at') or '')[:19]}")
    if data.get("parent_id"):
        print(f"  Thread:       reply to {data['parent_id']}")
    if data.get("run_id"):
        print(f"  Run:          {data['run_id']}")
    if data.get("behavior_id"):
        print(f"  Behavior:     {data['behavior_id']}")
    if data.get("work_item_id"):
        print(f"  Work Item:    {data['work_item_id']}")
    print(f"  Replies:      {data.get('reply_count', 0)}")
    if data.get("reactions"):
        emojis = [f"{r['emoji']} ({r['actor_id']})" for r in data["reactions"]]
        print(f"  Reactions:    {', '.join(emojis)}")
    print(f"\n  {data.get('content') or '(no content)'}")


def _render_search_results_table(data: Dict[str, Any]) -> None:
    """Render search results."""
    results = data.get("results", [])
    if not results:
        print("No results found.")
        return
    total = data.get("total", len(results))
    print(f"\nSearch Results ({len(results)} of {total}):\n")
    header = f"{'Rank':<8} {'ID':<38} {'Sender':<20} {'Content'}"
    print(header)
    print("-" * min(len(header) + 40, 140))
    for r in results:
        msg = r.get("message", {})
        rank = r.get("rank", 0.0)
        content = (r.get("headline") or msg.get("content") or "")[:60].replace("\n", " ")
        print(
            f"{rank:<8.3f} {msg.get('id', ''):<38} "
            f"{msg.get('sender_id', '')[:20]:<20} {content}"
        )


def _command_conversation_list(args: argparse.Namespace) -> int:
    adapter = _get_conversation_adapter()
    try:
        result = adapter.list_conversations(
            project_id=args.project_id,
            user_id=args.user_id,
            org_id=args.org_id,
            scope=args.scope,
            include_archived=args.include_archived,
            limit=args.limit,
            offset=args.offset,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        _print_json(result)
    else:
        _render_conversations_table(result)
    return 0


def _command_conversation_get(args: argparse.Namespace) -> int:
    adapter = _get_conversation_adapter()
    try:
        result = adapter.get_conversation(
            args.conversation_id,
            org_id=args.org_id,
            user_id=args.user_id,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        _print_json(result)
    else:
        _render_conversation_detail(result)
    return 0


def _command_conversation_create(args: argparse.Namespace) -> int:
    adapter = _get_conversation_adapter()
    try:
        result = adapter.create_conversation(
            project_id=args.project_id,
            scope=args.scope,
            title=args.title,
            created_by=args.user_id,
            participant_ids=args.participants,
            org_id=args.org_id,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        _print_json(result)
    else:
        _render_conversation_detail(result)
    return 0


def _command_conversation_archive(args: argparse.Namespace) -> int:
    adapter = _get_conversation_adapter()
    try:
        result = adapter.archive_conversation(
            args.conversation_id,
            user_id=args.user_id,
            org_id=args.org_id,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        _print_json(result)
    else:
        print(f"Conversation {args.conversation_id} archived.")
    return 0


def _command_conversation_send(args: argparse.Namespace) -> int:
    adapter = _get_conversation_adapter()
    try:
        result = adapter.send_message(
            args.conversation_id,
            sender_id=args.user_id,
            content=args.content,
            message_type=args.message_type,
            parent_id=args.parent_id,
            run_id=args.run_id,
            behavior_id=args.behavior_id,
            work_item_id=args.work_item_id,
            org_id=args.org_id,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        _print_json(result)
    else:
        _render_message_detail(result)
    return 0


def _command_conversation_messages(args: argparse.Namespace) -> int:
    adapter = _get_conversation_adapter()
    try:
        result = adapter.list_messages(
            args.conversation_id,
            user_id=args.user_id,
            org_id=args.org_id,
            parent_id=args.parent_id,
            limit=args.limit,
            offset=args.offset,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        _print_json(result)
    else:
        _render_messages_table(result)
    return 0


def _command_conversation_search(args: argparse.Namespace) -> int:
    adapter = _get_conversation_adapter()
    try:
        result = adapter.search_messages(
            args.conversation_id,
            query=args.query,
            user_id=args.user_id,
            org_id=args.org_id,
            limit=args.limit,
            offset=args.offset,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        _print_json(result)
    else:
        _render_search_results_table(result)
    return 0


def _command_conversation_react(args: argparse.Namespace) -> int:
    adapter = _get_conversation_adapter()
    try:
        if args.remove:
            result = adapter.remove_reaction(
                args.message_id,
                actor_id=args.user_id,
                emoji=args.emoji,
                org_id=args.org_id,
            )
        else:
            result = adapter.add_reaction(
                args.message_id,
                actor_id=args.user_id,
                emoji=args.emoji,
                org_id=args.org_id,
            )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    _print_json(result)
    return 0


def _command_conversation_edit(args: argparse.Namespace) -> int:
    adapter = _get_conversation_adapter()
    try:
        result = adapter.edit_message(
            args.message_id,
            new_content=args.content,
            editor_id=args.user_id,
            org_id=args.org_id,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        _print_json(result)
    else:
        _render_message_detail(result)
    return 0


def _command_conversation_delete(args: argparse.Namespace) -> int:
    adapter = _get_conversation_adapter()
    try:
        result = adapter.delete_message(
            args.message_id,
            deleter_id=args.user_id,
            org_id=args.org_id,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        _print_json(result)
    else:
        print(f"Message {args.message_id} deleted.")
    return 0


def _command_conversation_get_message(args: argparse.Namespace) -> int:
    adapter = _get_conversation_adapter()
    try:
        result = adapter.get_message(
            args.message_id,
            user_id=args.user_id,
            org_id=args.org_id,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    _print_json(result)
    return 0


def _command_conversation_pin(args: argparse.Namespace) -> int:
    adapter = _get_conversation_adapter()
    try:
        result = adapter.pin_message(
            args.conversation_id,
            args.message_id,
            user_id=args.user_id,
            org_id=args.org_id,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    _print_json(result)
    return 0


def _command_conversation_unpin(args: argparse.Namespace) -> int:
    adapter = _get_conversation_adapter()
    try:
        result = adapter.unpin_message(
            args.conversation_id,
            user_id=args.user_id,
            org_id=args.org_id,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    _print_json(result)
    return 0


# ==============================================================================
# Diagnostics (amprealize doctor)
# ==============================================================================


def _command_doctor(args: argparse.Namespace) -> int:
    """Run diagnostics to verify Amprealize installation health."""
    verbose = getattr(args, "verbose", False)
    fix = getattr(args, "fix", False)
    output_json = getattr(args, "json", False)

    checks: list[dict[str, Any]] = []
    all_passed = True

    def add_check(name: str, passed: bool, message: str, fix_hint: str | None = None) -> None:
        nonlocal all_passed
        if not passed:
            all_passed = False
        checks.append({
            "name": name,
            "passed": passed,
            "message": message,
            "fix_hint": fix_hint,
        })

    # ── Check 1: Python version ────────────────────────────────────────────
    py_version = sys.version_info
    py_ok = py_version >= (3, 10)
    add_check(
        "Python version",
        py_ok,
        f"Python {py_version.major}.{py_version.minor}.{py_version.micro}",
        "Upgrade to Python 3.10+" if not py_ok else None,
    )

    # ── Check 2: Amprealize package installed ─────────────────────────────────
    try:
        import amprealize
        amprealize_version = getattr(amprealize, "__version__", "unknown")
        add_check("Amprealize package", True, f"Version {amprealize_version}")
    except ImportError:
        add_check(
            "Amprealize package",
            False,
            "Not installed",
            "pip install amprealize",
        )

    # ── Check 3: Config file exists ────────────────────────────────────────
    user_config = Path.home() / ".amprealize" / "config.yaml"
    project_config = Path(".amprealize") / "config.yaml"
    config_exists = user_config.exists() or project_config.exists()
    config_path = project_config if project_config.exists() else user_config if user_config.exists() else None

    if config_exists:
        add_check("Config file", True, f"Found at {config_path}")
    else:
        add_check(
            "Config file",
            False,
            "No config found",
            "Run `amprealize init` to create one",
        )
        if fix:
            print("  🔧 Running `amprealize init --non-interactive`...")
            _command_init(argparse.Namespace(
                name=None, storage=None, auth=None,
                template="minimal", non_interactive=True
            ))
            config_exists = project_config.exists()
            checks[-1]["passed"] = config_exists
            checks[-1]["message"] = f"Created {project_config}" if config_exists else "Fix failed"

    # ── Check 4: Config is valid YAML ──────────────────────────────────────
    config_valid = False
    config_data = None
    if config_path and config_path.exists():
        try:
            config_data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            config_valid = isinstance(config_data, dict)
            add_check("Config syntax", True, "Valid YAML")
        except yaml.YAMLError as e:
            add_check("Config syntax", False, f"Invalid YAML: {e}", "Fix syntax errors in config file")
    else:
        add_check("Config syntax", False, "No config to validate", "Create config first")

    # ── Check 5: Storage backend ───────────────────────────────────────────
    storage_ok = False
    storage_backend = "unknown"
    if config_data:
        storage_cfg = config_data.get("storage", {})
        storage_backend = storage_cfg.get("backend", "sqlite")

        if storage_backend == "sqlite":
            sqlite_path = storage_cfg.get("sqlite", {}).get("path")
            if sqlite_path:
                db_path = Path(sqlite_path).expanduser()
            else:
                db_path = Path(".amprealize") / "data" / "amprealize.db"

            if db_path.exists():
                storage_ok = True
                add_check("Storage backend", True, f"SQLite at {db_path}")
            else:
                add_check(
                    "Storage backend",
                    False,
                    f"SQLite file not found: {db_path}",
                    "Run `amprealize db migrate` to create database",
                )
                if fix:
                    print("  🔧 Creating SQLite database...")
                    db_path.parent.mkdir(parents=True, exist_ok=True)
                    db_path.touch()
                    checks[-1]["passed"] = True
                    checks[-1]["message"] = f"Created {db_path}"

        elif storage_backend == "postgres":
            postgres_cfg = storage_cfg.get("postgres", {})
            dsn = postgres_cfg.get("dsn", "")
            if dsn:
                try:
                    import psycopg
                    with psycopg.connect(dsn, connect_timeout=5) as conn:
                        with conn.cursor() as cur:
                            cur.execute("SELECT 1")
                    storage_ok = True
                    add_check("Storage backend", True, f"PostgreSQL connected")
                except ImportError:
                    add_check(
                        "Storage backend",
                        False,
                        "psycopg not installed",
                        "pip install 'psycopg[binary]'",
                    )
                except Exception as e:
                    add_check(
                        "Storage backend",
                        False,
                        f"PostgreSQL connection failed: {e}",
                        "Check DSN and ensure database is running",
                    )
            else:
                add_check("Storage backend", False, "No PostgreSQL DSN configured", "Set storage.postgres.dsn in config")
    else:
        add_check("Storage backend", False, "Cannot check (no config)", None)

    # ── Check 6: MCP server dependencies ───────────────────────────────────
    mcp_deps_ok = True
    missing_deps = []
    for pkg in ["mcp", "pydantic", "httpx"]:
        try:
            __import__(pkg)
        except ImportError:
            mcp_deps_ok = False
            missing_deps.append(pkg)

    if mcp_deps_ok:
        add_check("MCP dependencies", True, "All required packages installed")
    else:
        add_check(
            "MCP dependencies",
            False,
            f"Missing: {', '.join(missing_deps)}",
            f"pip install {' '.join(missing_deps)}",
        )

    # ── Check 7: Container runtime (for breakeramp) ────────────────────────
    container_runtime = None
    for runtime in ["podman", "docker"]:
        try:
            result = subprocess.run(
                [runtime, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                container_runtime = runtime
                version_line = result.stdout.strip().split("\n")[0]
                break
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    if container_runtime:
        add_check("Container runtime", True, f"{container_runtime}: {version_line}")
    else:
        add_check(
            "Container runtime",
            False,
            "No container runtime found",
            "Install Podman or Docker for infrastructure management",
        )

    # ── Check 8: Network connectivity (cloud auth) ─────────────────────────
    auth_mode = "local"
    if config_data:
        auth_mode = config_data.get("auth", {}).get("mode", "local")

    if auth_mode == "cloud":
        try:
            req = urllib.request.Request("https://api.amprealize.dev/health", method="HEAD")
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status in (200, 204):
                    add_check("Cloud connectivity", True, "Amprealize API reachable")
                else:
                    add_check("Cloud connectivity", False, f"Unexpected status: {resp.status}", None)
        except Exception as e:
            add_check(
                "Cloud connectivity",
                False,
                f"Cannot reach Amprealize API: {e}",
                "Check network connection and firewall settings",
            )
    else:
        add_check("Cloud connectivity", True, "Skipped (local auth mode)")

    # ── Check 9: Data directories ──────────────────────────────────────────
    data_dirs = [
        Path.home() / ".amprealize",
        Path.home() / ".amprealize" / "data",
        Path.home() / ".amprealize" / "telemetry",
    ]
    missing_dirs = [d for d in data_dirs if not d.exists()]
    if not missing_dirs:
        add_check("Data directories", True, "All directories exist")
    else:
        add_check(
            "Data directories",
            False,
            f"Missing: {', '.join(str(d) for d in missing_dirs)}",
            "Directories will be created automatically on first use",
        )
        if fix:
            print("  🔧 Creating missing directories...")
            for d in missing_dirs:
                d.mkdir(parents=True, exist_ok=True)
            checks[-1]["passed"] = True
            checks[-1]["message"] = "Created missing directories"

    # ── Output results ─────────────────────────────────────────────────────
    if output_json:
        result = {
            "passed": all_passed,
            "checks": checks,
            "summary": {
                "total": len(checks),
                "passed": sum(1 for c in checks if c["passed"]),
                "failed": sum(1 for c in checks if not c["passed"]),
            },
        }
        print(json.dumps(result, indent=2))
    else:
        print("\n🩺 Amprealize Doctor\n")
        for check in checks:
            icon = "✅" if check["passed"] else "❌"
            print(f"  {icon} {check['name']}: {check['message']}")
            if verbose and check.get("fix_hint") and not check["passed"]:
                print(f"     💡 Fix: {check['fix_hint']}")

        print()
        passed_count = sum(1 for c in checks if c["passed"])
        total_count = len(checks)
        if all_passed:
            print(f"✨ All {total_count} checks passed! Amprealize is healthy.\n")
        else:
            failed_count = total_count - passed_count
            print(f"⚠️  {failed_count}/{total_count} checks failed.")
            print("   Run with --verbose to see fix suggestions, or --fix to auto-repair.\n")

    return 0 if all_passed else 1


# ==============================================================================
# Dashboard Launcher (amprealize open)
# ==============================================================================

_PID_FILE = Path.home() / ".amprealize" / "data" / "server.pid"
_DEEP_LINK_ROUTES: dict[str, str] = {
    "behaviors": "/behaviors",
    "runs": "/runs",
    "boards": "/boards",
    "settings": "/settings",
}


def _read_pid() -> int | None:
    """Read the saved server PID, or None if missing/stale."""
    if not _PID_FILE.exists():
        return None
    try:
        pid = int(_PID_FILE.read_text().strip())
    except (ValueError, OSError):
        return None
    # Check if process is actually alive
    try:
        os.kill(pid, 0)
    except OSError:
        # Process doesn't exist — stale PID file
        _PID_FILE.unlink(missing_ok=True)
        return None
    return pid


def _write_pid(pid: int) -> None:
    """Write a PID to the PID file."""
    _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(pid))


def _remove_pid() -> None:
    """Remove the PID file."""
    _PID_FILE.unlink(missing_ok=True)


def _wait_for_server(host: str, port: int, timeout: float = 10.0) -> bool:
    """Poll the /health endpoint until it responds or timeout expires."""
    import time
    import urllib.request
    import urllib.error

    url = f"http://{host}:{port}/health"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError, TimeoutError):
            pass
        time.sleep(0.5)
    return False


def _is_port_in_use(host: str, port: int) -> bool:
    """Check if a port is already bound."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) == 0


def _command_open_stop() -> int:
    """Stop a running Amprealize server."""
    import signal

    pid = _read_pid()
    if pid is None:
        print("No running Amprealize server found.")
        return 0
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"✅ Stopped Amprealize server (PID {pid})")
    except OSError as exc:
        print(f"Error stopping server (PID {pid}): {exc}", file=sys.stderr)
        return 1
    finally:
        _remove_pid()
    return 0


def _command_open(args: argparse.Namespace) -> int:
    """Launch the Amprealize dashboard, starting the server if needed."""
    import subprocess

    from amprealize.config.loader import load_config

    # Handle --stop
    if getattr(args, "stop", False):
        return _command_open_stop()

    cfg = load_config()
    host = cfg.server.host
    port = getattr(args, "port", None) or cfg.server.port
    # For browser URLs, replace 0.0.0.0 with localhost
    browse_host = "127.0.0.1" if host == "0.0.0.0" else host

    # Build the target URL
    base_url = f"http://{browse_host}:{port}"
    page = getattr(args, "page", None)
    if page and page in _DEEP_LINK_ROUTES:
        target_url = base_url + _DEEP_LINK_ROUTES[page]
    else:
        target_url = base_url

    no_browser = getattr(args, "no_browser", False)

    # 1. Check if server is already running (via PID or port probe)
    existing_pid = _read_pid()
    server_running = existing_pid is not None

    if not server_running and _is_port_in_use(browse_host, port):
        # Something else is using the port
        print(
            f"Error: Port {port} is already in use by another process.\n"
            f"Choose a different port with --port or stop the conflicting process.",
            file=sys.stderr,
        )
        return 1

    # 2. Start server if not running
    if not server_running:
        print(f"🚀 Starting Amprealize server on {host}:{port}...")
        # Find python executable (same one running this CLI)
        python_path = sys.executable
        server_proc = subprocess.Popen(
            [
                python_path,
                "-m",
                "uvicorn",
                "amprealize.api:app",
                "--host",
                host,
                "--port",
                str(port),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        _write_pid(server_proc.pid)

        # Wait for health check
        if not _wait_for_server(browse_host, port):
            print(
                f"Error: Server failed to start within 10 seconds.\n"
                f"Check logs or try: {python_path} -m uvicorn amprealize.api:app --host {host} --port {port}",
                file=sys.stderr,
            )
            _remove_pid()
            return 1

        print(f"  ✅ Server running (PID {server_proc.pid})")
    else:
        print(f"✅ Server already running (PID {existing_pid})")

    # 3. Open browser or print URL
    if no_browser:
        print(f"\n🔗 {target_url}")
        print(f"   (use --stop to shut down the server)")
    else:
        print(f"🌐 Opening {target_url}")
        webbrowser.open(target_url)

    return 0


# ==============================================================================
# MCP Server CLI Commands
# ==============================================================================


def _command_mcp_server(args: argparse.Namespace) -> int:
    """Start the Amprealize MCP server."""
    import asyncio as _asyncio
    from amprealize.config.loader import load_config

    cfg = load_config()

    # CLI overrides for transport / port / log-level
    transport = getattr(args, "transport", None) or cfg.mcp.transport
    port = getattr(args, "port", None) or cfg.server.port
    log_level = getattr(args, "log_level", None) or cfg.logging.level

    # Apply log-level override via env before MCPServer reads it
    os.environ.setdefault("MCP_LOG_LEVEL", log_level)

    if transport == "sse":
        os.environ["MCP_TRANSPORT"] = "sse"
        os.environ["MCP_SSE_PORT"] = str(port)

    print(f"Amprealize MCP Server", file=sys.stderr)
    print(f"  Transport : {transport}", file=sys.stderr)
    if transport == "sse":
        print(f"  Port      : {port}", file=sys.stderr)
    print(f"  Log level : {log_level}", file=sys.stderr)
    print(f"  Config    : {cfg.version}", file=sys.stderr)
    print(file=sys.stderr)

    from amprealize.mcp_server import main as mcp_main

    _asyncio.run(mcp_main())
    return 0


def _command_mcp_init(args: argparse.Namespace) -> int:
    """Generate MCP configuration files for supported local clients."""
    _generate_ide_configs()
    return 0


def _command_mcp_doctor(args: argparse.Namespace) -> int:
    """Smoke-test MCP startup and tool discovery."""

    try:
        summary = _run_mcp_smoke_test(timeout=float(getattr(args, "timeout", 10.0)))
    except Exception as exc:
        print(f"✗ MCP smoke test failed: {exc}", file=sys.stderr)
        return 1

    print("✓ MCP smoke test passed")
    print(f"  Server    : {summary['server_name']}")
    print(f"  Protocol  : {summary['protocol_version']}")
    print(f"  Tools     : {summary['tool_count']}")
    print(f"  Sample    : {', '.join(summary['sample_tools'])}")
    return 0


# ==============================================================================
# Work Item CLI Commands
# ==============================================================================


def _wi_api_base() -> str:
    """Get the API base URL from environment."""
    return os.environ.get("AMPREALIZE_API_URL", "http://localhost:8000")


def _wi_auth_headers() -> Dict[str, str]:
    """Get auth headers for API calls."""
    token = os.environ.get("AMPREALIZE_TOKEN") or os.environ.get("GA_TOKEN", "")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _wi_api_call(
    method: str, path: str, body: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Make an API call and return JSON response."""
    import urllib.request
    import json as _json

    url = f"{_wi_api_base()}/api{path}"
    data = _json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url,
        data=data,
        headers=_wi_auth_headers(),
        method=method,
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return _json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        try:
            return _json.loads(error_body)
        except Exception:
            return {"error": f"HTTP {e.code}: {error_body[:200]}"}


def _command_wi_execute(args: argparse.Namespace) -> int:
    """Execute a work item."""
    import json as _json

    body: Dict[str, Any] = {}
    if args.model:
        body["model_override"] = args.model
    if args.callback_url:
        body["callback_url"] = args.callback_url

    params = f"project_id={args.project_id}"
    if args.org_id:
        params += f"&org_id={args.org_id}"

    result = _wi_api_call(
        "POST",
        f"/v1/work-items/{args.item_id}:execute?{params}",
        body or {},
    )

    if args.format == "json":
        _print_json(result)
    else:
        if result.get("success"):
            print(f"✅ Execution started")
            print(f"   Run ID:     {result.get('run_id', 'N/A')}")
            print(f"   Cycle ID:   {result.get('task_cycle_id', 'N/A')}")
            print(f"   Status:     {result.get('status', 'N/A')}")
        else:
            detail = result.get("detail", result)
            print(f"❌ Execution failed: {detail}", file=sys.stderr)
            return 1

    # --watch mode: connect to SSE stream
    if getattr(args, "watch", False) and result.get("run_id"):
        run_id = result["run_id"]
        print(f"\n📡 Watching execution events (Ctrl+C to stop)...\n")
        return _wi_watch_sse(run_id, args)

    return 0


def _wi_watch_sse(run_id: str, args: argparse.Namespace) -> int:
    """Connect to SSE stream and print events."""
    import urllib.request

    url = f"{_wi_api_base()}/api/v1/runs/{run_id}/events"
    req = urllib.request.Request(url, headers=_wi_auth_headers())

    try:
        with urllib.request.urlopen(req) as resp:
            event_type = ""
            data_lines = []
            for raw_line in resp:
                line = raw_line.decode("utf-8").rstrip("\n")

                if line.startswith("event: "):
                    event_type = line[7:]
                elif line.startswith("data: "):
                    data_lines.append(line[6:])
                elif line == "":
                    # End of event
                    if data_lines:
                        import json as _json
                        data_str = "\n".join(data_lines)
                        try:
                            payload = _json.loads(data_str)
                        except Exception:
                            payload = {"raw": data_str}

                        _print_sse_event(event_type, payload)

                        # Stop watching on terminal events
                        if event_type in ("run.completed", "run.failed"):
                            return 0 if event_type == "run.completed" else 1

                    event_type = ""
                    data_lines = []
                elif line.startswith(":"):
                    # Comment (keepalive) — ignore
                    pass

    except KeyboardInterrupt:
        print("\n⏹  Stopped watching.")
        return 0
    except Exception as e:
        print(f"SSE connection error: {e}", file=sys.stderr)
        return 1
    return 0


def _print_sse_event(event_type: str, payload: Dict[str, Any]) -> None:
    """Pretty-print an SSE event."""
    emoji = {
        "execution.status": "📊",
        "execution.step": "📝",
        "gate.waiting": "🚧",
        "gate.clarification_needed": "❓",
        "gate.approved": "✅",
        "gate.soft_passed": "⏩",
        "run.completed": "🎉",
        "run.failed": "❌",
    }.get(event_type, "📋")

    phase = payload.get("phase", "")
    status = payload.get("status", "")
    current_step = payload.get("current_step", "")

    summary_parts = []
    if phase:
        summary_parts.append(f"phase={phase}")
    if status:
        summary_parts.append(f"status={status}")
    if current_step:
        summary_parts.append(f"step={current_step}")

    summary = " | ".join(summary_parts) if summary_parts else ""

    print(f"  {emoji} {event_type}  {summary}")

    # Show clarification questions if present
    questions = payload.get("clarification_questions", [])
    for q in questions:
        q_text = q.get("question", q.get("text", str(q)))
        print(f"     ❓ {q_text}")


def _command_wi_status(args: argparse.Namespace) -> int:
    """Get work item execution status."""
    params = f"project_id={args.project_id}"
    if args.org_id:
        params += f"&org_id={args.org_id}"

    result = _wi_api_call("GET", f"/v1/work-items/{args.item_id}/execution?{params}")

    if args.format == "json":
        _print_json(result)
    else:
        if not result.get("has_execution"):
            print(f"No active execution for work item {args.item_id}")
            return 0

        print(f"📊 Execution Status")
        print(f"   Run ID:      {result.get('run_id', 'N/A')}")
        print(f"   Cycle ID:    {result.get('task_cycle_id', 'N/A')}")
        print(f"   State:       {result.get('state', 'N/A')}")
        print(f"   Phase:       {result.get('phase', 'N/A')}")
        print(f"   Progress:    {result.get('progress_pct', 0):.0f}%")
        print(f"   Step:        {result.get('current_step', 'N/A')}")

        clarifications = result.get("pending_clarifications", [])
        if clarifications:
            print(f"\n   ❓ Pending Clarifications:")
            for c in clarifications:
                c_id = c.get("id", c.get("clarification_id", "N/A"))
                q_text = c.get("question", c.get("text", str(c)))
                print(f"      [{c_id}] {q_text}")

    return 0


def _command_wi_clarify(args: argparse.Namespace) -> int:
    """Provide clarification for a paused execution."""
    params = f"project_id={args.project_id}"
    if args.org_id:
        params += f"&org_id={args.org_id}"

    result = _wi_api_call(
        "POST",
        f"/v1/work-items/{args.item_id}:clarify?{params}",
        {
            "clarification_id": args.clarification_id,
            "response": args.response,
        },
    )

    if result.get("success"):
        print(f"✅ Clarification provided")
    else:
        print(f"❌ Failed: {result.get('message', result)}", file=sys.stderr)
        return 1

    return 0


def _command_wi_approve_gate(args: argparse.Namespace) -> int:
    """Approve a strict gate and resume execution."""
    params = f"project_id={args.project_id}"
    if args.org_id:
        params += f"&org_id={args.org_id}"

    body: Dict[str, Any] = {}
    if args.phase:
        body["phase"] = args.phase
    if args.notes:
        body["notes"] = args.notes

    result = _wi_api_call(
        "POST",
        f"/v1/work-items/{args.item_id}:approve-gate?{params}",
        body,
    )

    if result.get("success"):
        print(f"✅ Gate approved")
        print(f"   Run ID:   {result.get('run_id', 'N/A')}")
        print(f"   Resumed:  {result.get('resumed', False)}")
        print(f"   Message:  {result.get('message', '')}")
    else:
        print(f"❌ Failed: {result.get('message', result)}", file=sys.stderr)
        return 1

    return 0


def main_mcp_server() -> int:
    """Convenience entry point for ``amprealize-mcp-server`` console script.

    Delegates to ``amprealize mcp-server``, forwarding any extra CLI args.
    """
    return main(["mcp-server"] + sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
