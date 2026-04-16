"""LLM-powered project analyser for the wizard."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from amprealize.bootstrap.detector import WorkspaceDetector
from amprealize.bootstrap.profile import ProfileDetectionResult, WorkspaceSignal
from amprealize.llm.client import LLMClient
from amprealize.llm.types import LLMConfig, LLMResponse, ProviderType
from amprealize.wizard.prompts import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger(__name__)

# Files to look for when gathering project context
_KEY_FILES = [
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "README.md",
    "readme.md",
    "README.rst",
    ".github/workflows/ci.yml",
    ".github/workflows/ci.yaml",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    ".amprealize/config.yaml",
    "AGENTS.md",
    "alembic.ini",
    "tsconfig.json",
    "vite.config.ts",
    "vite.config.js",
    "next.config.js",
    "next.config.ts",
    ".eslintrc.json",
    ".eslintrc.js",
    "Makefile",
    "requirements.txt",
    "setup.py",
    "setup.cfg",
]

# Max bytes to read per file to stay within token budgets
_MAX_FILE_BYTES = 8_000

# Max depth for directory listing
_MAX_DIR_DEPTH = 3

# Max entries in directory listing
_MAX_DIR_ENTRIES = 200


@dataclass
class AnalysisResult:
    """Structured result of the LLM analysis."""

    tech_stack: Dict[str, List[str]] = field(default_factory=dict)
    architecture: Dict[str, str] = field(default_factory=dict)
    team_signals: Dict[str, Any] = field(default_factory=dict)
    suggested_profile: str = "solo-dev"
    profile_rationale: str = ""
    suggested_modules: Dict[str, bool] = field(default_factory=dict)
    module_rationale: str = ""
    suggested_behaviors: List[Dict[str, str]] = field(default_factory=list)
    deployment_recommendation: str = "local"
    storage_recommendation: str = "sqlite"
    notes: str = ""
    raw_response: Dict[str, Any] = field(default_factory=dict)

    # Metadata from the LLM call
    model_used: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0

    @classmethod
    def from_llm_response(
        cls, parsed: Dict[str, Any], response: LLMResponse
    ) -> "AnalysisResult":
        """Build from parsed JSON and raw LLM response metadata."""
        return cls(
            tech_stack=parsed.get("tech_stack", {}),
            architecture=parsed.get("architecture", {}),
            team_signals=parsed.get("team_signals", {}),
            suggested_profile=parsed.get("suggested_profile", "solo-dev"),
            profile_rationale=parsed.get("profile_rationale", ""),
            suggested_modules=parsed.get("suggested_modules", {}),
            module_rationale=parsed.get("module_rationale", ""),
            suggested_behaviors=parsed.get("suggested_behaviors", []),
            deployment_recommendation=parsed.get("deployment_recommendation", "local"),
            storage_recommendation=parsed.get("storage_recommendation", "sqlite"),
            notes=parsed.get("notes", ""),
            raw_response=parsed,
            model_used=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=response.cost_usd,
            latency_ms=response.latency_ms,
        )


class ProjectAnalyzer:
    """Analyses a project workspace using LLM and heuristic signals."""

    def __init__(
        self,
        *,
        model: str = "claude-sonnet-4-5",
        llm_client: Optional[LLMClient] = None,
        detector: Optional[WorkspaceDetector] = None,
    ) -> None:
        self._model = model
        self._llm_client = llm_client
        self._detector = detector or WorkspaceDetector()

    def _ensure_llm_client(self, api_key: Optional[str] = None) -> LLMClient:
        """Lazily init the LLM client."""
        if self._llm_client is not None:
            return self._llm_client

        config = LLMConfig.from_env()
        if api_key:
            config.api_key = api_key
        self._llm_client = LLMClient(config=config)
        return self._llm_client

    # -- project scanning -----------------------------------------------------

    def detect_signals(self, workspace: Path) -> ProfileDetectionResult:
        """Run fast heuristic workspace detection."""
        return self._detector.detect(workspace)

    def gather_directory_listing(
        self, workspace: Path, max_depth: int = _MAX_DIR_DEPTH
    ) -> str:
        """Build a truncated directory tree string."""
        lines: List[str] = []
        count = 0

        def _walk(p: Path, depth: int, prefix: str) -> None:
            nonlocal count
            if depth > max_depth or count >= _MAX_DIR_ENTRIES:
                return
            try:
                entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name))
            except PermissionError:
                return
            for entry in entries:
                if entry.name.startswith(".") and entry.name not in (
                    ".github",
                    ".amprealize",
                    ".vscode",
                ):
                    continue
                if entry.name in (
                    "node_modules",
                    "__pycache__",
                    ".git",
                    ".venv",
                    "venv",
                    "dist",
                    "build",
                    ".tox",
                    ".mypy_cache",
                    ".pytest_cache",
                    "*.egg-info",
                ):
                    continue
                count += 1
                if count > _MAX_DIR_ENTRIES:
                    lines.append(f"{prefix}... (truncated)")
                    return
                if entry.is_dir():
                    lines.append(f"{prefix}{entry.name}/")
                    _walk(entry, depth + 1, prefix + "  ")
                else:
                    lines.append(f"{prefix}{entry.name}")

        _walk(workspace, 0, "")
        return "\n".join(lines)

    def gather_key_files(self, workspace: Path) -> str:
        """Read key config/doc files and concatenate their contents."""
        parts: List[str] = []
        for rel_path in _KEY_FILES:
            full = workspace / rel_path
            if full.is_file():
                try:
                    content = full.read_text(errors="replace")[:_MAX_FILE_BYTES]
                    parts.append(f"### {rel_path}\n\n```\n{content}\n```\n")
                except OSError:
                    continue
        return "\n".join(parts) if parts else "(no key files found)"

    def _signals_summary(self, signals: List[WorkspaceSignal]) -> str:
        lines: List[str] = []
        for sig in signals:
            status = "DETECTED" if sig.detected else "not detected"
            lines.append(f"- {sig.signal_name}: {status} (confidence={sig.confidence:.2f}) {sig.evidence}")
        return "\n".join(lines)

    # -- LLM analysis ---------------------------------------------------------

    def analyse(
        self,
        workspace: Path,
        *,
        api_key: Optional[str] = None,
        detection: Optional[ProfileDetectionResult] = None,
    ) -> AnalysisResult:
        """Run full LLM-powered analysis on a workspace.

        Args:
            workspace: Path to the project root.
            api_key: Optional API key override.
            detection: Pre-computed detection result (avoids double-scan).

        Returns:
            AnalysisResult with structured LLM output.
        """
        client = self._ensure_llm_client(api_key)

        # Pre-detection pass
        if detection is None:
            detection = self.detect_signals(workspace)

        # Gather context
        dir_listing = self.gather_directory_listing(workspace)
        key_files = self.gather_key_files(workspace)
        signals_text = self._signals_summary(detection.signals)

        user_prompt = build_user_prompt(
            directory_listing=dir_listing,
            key_files_content=key_files,
            signals_summary=signals_text,
            heuristic_profile=detection.profile.value,
            heuristic_confidence=detection.confidence,
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        response = client.call(
            messages,
            model=self._model,
            temperature=0.3,
            max_tokens=4096,
        )

        parsed = self._parse_response(response.content)
        return AnalysisResult.from_llm_response(parsed, response)

    @staticmethod
    def _parse_response(content: str) -> Dict[str, Any]:
        """Parse the LLM JSON response, tolerating markdown fences."""
        text = content.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            first_newline = text.index("\n")
            text = text[first_newline + 1 :]
            if text.endswith("```"):
                text = text[:-3].rstrip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM response as JSON, returning raw content")
            return {"notes": text, "_parse_error": True}
