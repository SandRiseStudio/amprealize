"""Codebase analyzer for the research pipeline."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

_BEHAVIOR_NAME_RE = re.compile(r"\b(behavior_[a-z0-9_]+)\b", re.IGNORECASE)
_CREATE_TABLE_SQL_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?:[`\"]?\w+[`\"]?\.)?[`\"]?(\w+)[`\"]?\s*\(",
    re.IGNORECASE,
)
_CREATE_TABLE_PY_RE = re.compile(
    r"""op\.create_table\s*\(\s*['"](\w+)['"]""",
    re.IGNORECASE,
)
_MCP_TOOL_NAME_RE = re.compile(r'"name"\s*:\s*"([^"]+)"')

TOKEN_BUDGETS: dict[str, int] = {
    "small": 4_000,
    "medium": 16_000,
    "large": 64_000,
}


@dataclass
class CodebaseSnapshot:
    """Point-in-time snapshot of codebase structure and content."""

    root_path: str = ""
    file_count: int = 0
    total_lines: int = 0
    languages: dict[str, int] = field(default_factory=dict)
    tree: list[str] = field(default_factory=list)
    content_map: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StructuralIndex:
    """Lightweight structural buckets for research progress + LLM context.

    Populated by :meth:`CodebaseAnalyzer.get_structural_index` via bounded,
    layout-aware scans (services, handbook behaviors, MCP tool names, tables
    inferred from migrations). This is a coarse index for grounding evaluations,
    not a semantic code search index.
    """

    services: List[str] = field(default_factory=list)
    behaviors: List[str] = field(default_factory=list)
    mcp_tools: List[str] = field(default_factory=list)
    db_tables: List[str] = field(default_factory=list)

    def to_context_string(self) -> str:
        """Compact markdown for LLM prompts (token-bounded)."""
        if not (
            self.services
            or self.behaviors
            or self.mcp_tools
            or self.db_tables
        ):
            return ""

        def _section(title: str, items: List[str], *, cap: int = 40) -> str:
            if not items:
                return ""
            head, rest = items[:cap], items[cap:]
            lines = "\n".join(f"- `{x}`" for x in head)
            more = f"\n- _…and {len(rest)} more_" if rest else ""
            return f"### {title} ({len(items)})\n{lines}{more}\n"

        parts = [
            "## Amprealize codebase index (structural scan)",
            "_Heuristic inventory only — use deep_dive_file for source detail._\n",
        ]
        parts.append(_section("Python services / APIs (`amprealize/services`)", self.services))
        parts.append(_section("Named behaviors (from AGENTS.md / CLAUDE.md)", self.behaviors))
        parts.append(_section("MCP tools (`mcp/tools/*.json`)", self.mcp_tools))
        parts.append(
            _section("Tables (from SQL + Alembic migrations)", self.db_tables)
        )
        text = "\n".join(p for p in parts if p)
        max_chars = 12_000
        if len(text) > max_chars:
            return text[:max_chars] + "\n\n[… codebase index truncated …]"
        return text


class CodebaseAnalyzer:
    """Analyzes a codebase to produce structured snapshots.

    ``get_structural_index`` / ``deep_dive`` provide stable hooks for
    :class:`amprealize.research_service.ResearchService`. Indexing is bounded
    and best-effort so the pipeline stays fast in large trees.
    """

    def __init__(self, root_path: str | Path = ".", **kwargs: Any) -> None:
        if "project_root" in kwargs:
            root_path = kwargs.pop("project_root")
        self.root_path = str(root_path)
        self._config = kwargs

    def get_structural_index(self) -> StructuralIndex:
        """Return structural buckets for UI, progress text, and LLM prompts."""
        root = Path(self.root_path).expanduser()
        try:
            root = root.resolve()
        except OSError as exc:
            logger.warning("CodebaseAnalyzer: could not resolve root %s: %s", self.root_path, exc)
            return StructuralIndex()

        if not root.is_dir():
            logger.debug("CodebaseAnalyzer: root is not a directory: %s", root)
            return StructuralIndex()

        services = self._collect_service_modules(root)
        behaviors = self._collect_behavior_names(root)
        mcp_tools = self._collect_mcp_tool_names(root)
        db_tables = self._collect_migration_tables(root)

        return StructuralIndex(
            services=services,
            behaviors=behaviors,
            mcp_tools=mcp_tools,
            db_tables=db_tables,
        )

    def _collect_service_modules(self, root: Path) -> List[str]:
        """List ``*.py`` stems under ``amprealize/services`` (Amprealize layout)."""
        svc_dir = root / "amprealize" / "services"
        if not svc_dir.is_dir():
            return []
        names: list[str] = []
        for path in sorted(svc_dir.glob("*.py")):
            if path.name == "__init__.py":
                continue
            names.append(path.stem)
        return names[:60]

    def _collect_behavior_names(self, root: Path) -> List[str]:
        """Extract ``behavior_*`` tokens from handbook-style markdown files."""
        found: set[str] = set()
        for rel in ("AGENTS.md", "CLAUDE.md"):
            path = root / rel
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                logger.debug("behavior scan skipped %s: %s", path, exc)
                continue
            for m in _BEHAVIOR_NAME_RE.finditer(text):
                found.add(m.group(1).lower())
            if len(found) >= 120:
                break
        return sorted(found)[:100]

    def _collect_mcp_tool_names(self, root: Path) -> List[str]:
        """Read tool ``name`` fields from ``mcp/tools/*.json``."""
        tools_dir = root / "mcp" / "tools"
        if not tools_dir.is_dir():
            return []
        names: list[str] = []
        for path in sorted(tools_dir.glob("*.json")):
            try:
                raw = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            m = _MCP_TOOL_NAME_RE.search(raw)
            if m:
                names.append(m.group(1))
            else:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                n = data.get("name")
                if isinstance(n, str) and n.strip():
                    names.append(n.strip())
        # Dedupe while preserving order
        seen: set[str] = set()
        out: list[str] = []
        for n in names:
            if n not in seen:
                seen.add(n)
                out.append(n)
        return out[:220]

    def _collect_migration_tables(self, root: Path) -> List[str]:
        """Infer table names from SQL migrations and Alembic revision files."""
        tables: set[str] = set()

        def _scan_sql_dir(d: Path) -> None:
            if not d.is_dir():
                return
            for path in sorted(d.glob("*.sql")):
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for m in _CREATE_TABLE_SQL_RE.finditer(text):
                    tables.add(m.group(1).lower())

        def _scan_py_migrations(d: Path) -> None:
            if not d.is_dir():
                return
            for path in sorted(d.glob("*.py")):
                if path.name.startswith("__"):
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for m in _CREATE_TABLE_PY_RE.finditer(text):
                    tables.add(m.group(1).lower())

        _scan_sql_dir(root / "schema" / "migrations")
        _scan_py_migrations(root / "migrations" / "versions")
        _scan_py_migrations(root / "migrations_telemetry" / "versions")

        # Skip obvious SQL keywords mistaken as identifiers
        noise = {"if", "as", "select", "where", "on", "using"}
        cleaned = sorted(t for t in tables if t not in noise)
        return cleaned[:80]

    def deep_dive(
        self,
        file_path: str,
        start_line: int = 1,
        end_line: Optional[int] = None,
    ) -> str:
        """Read a slice of a file under :attr:`root_path` for LLM follow-ups."""
        base = Path(self.root_path).resolve()
        candidate = (base / file_path).resolve()
        try:
            candidate.relative_to(base)
        except ValueError:
            return f"[deep_dive: path outside root: {file_path}]"

        if not candidate.is_file():
            return f"[deep_dive: not a file: {file_path}]"

        try:
            lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            logger.warning("deep_dive read failed: %s", exc)
            return f"[deep_dive: could not read {file_path}: {exc}]"

        if not lines:
            return f"[deep_dive: empty file: {file_path}]"

        lo = max(1, int(start_line))
        hi = int(end_line) if end_line is not None else len(lines)
        hi = max(lo, min(hi, len(lines)))
        body = "\n".join(lines[lo - 1 : hi])
        return f"// {file_path} lines {lo}-{hi}\n{body}"

    async def analyze(self, **kwargs: Any) -> CodebaseSnapshot:
        raise NotImplementedError("CodebaseAnalyzer.analyze not yet implemented")


def get_codebase_context(
    root_path: str = ".",
    budget: str = "medium",
    **kwargs: Any,
) -> str:
    """Return a text summary of the codebase, limited by token budget.

    Stub — replace with real implementation.
    """
    raise NotImplementedError("get_codebase_context not yet implemented")
