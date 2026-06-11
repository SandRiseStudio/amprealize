"""Workspace signal detection and profile suggestion.

Scans a workspace directory for structural signals that indicate
which ``WorkspaceProfile`` best fits, enabling ``amprealize init`` to
auto-select a knowledge pack (architecture doc §8.1, §8.2).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List

from amprealize.bootstrap.profile import (
    ProfileDetectionResult,
    WorkspaceProfile,
    WorkspaceSignal,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Weight table — maps (signal_name, profile) → weight
# ---------------------------------------------------------------------------

# Each profile has a base weight for each signal.  The detector accumulates
# weighted hits and picks the highest-scoring profile.

_PROFILE_WEIGHTS: Dict[str, Dict[WorkspaceProfile, float]] = {
    # Core amprealize-platform signals
    "agents_md": {
        WorkspaceProfile.AMPREALIZE_PLATFORM: 0.25,
        WorkspaceProfile.TEAM_COLLAB: 0.15,
        WorkspaceProfile.SOLO_DEV: 0.10,
    },
    "amprealize_imports": {
        WorkspaceProfile.AMPREALIZE_PLATFORM: 0.35,
    },
    "mcp_tools_dir": {
        WorkspaceProfile.AMPREALIZE_PLATFORM: 0.20,
        WorkspaceProfile.API_BACKEND: 0.05,
    },
    "knowledge_pack_dir": {
        WorkspaceProfile.AMPREALIZE_PLATFORM: 0.15,
    },
    # Extension signals
    "extension_dir": {
        WorkspaceProfile.EXTENSION_DEV: 0.40,
        WorkspaceProfile.AMPREALIZE_PLATFORM: 0.05,
    },
    "vscode_extension_manifest": {
        WorkspaceProfile.EXTENSION_DEV: 0.30,
    },
    # API / backend signals
    "fastapi_or_flask": {
        WorkspaceProfile.API_BACKEND: 0.30,
        WorkspaceProfile.AMPREALIZE_PLATFORM: 0.05,
    },
    "alembic_ini": {
        WorkspaceProfile.API_BACKEND: 0.15,
        WorkspaceProfile.AMPREALIZE_PLATFORM: 0.10,
    },
    "openapi_spec": {
        WorkspaceProfile.API_BACKEND: 0.20,
    },
    # Team / collab signals
    "github_dir": {
        WorkspaceProfile.TEAM_COLLAB: 0.15,
        WorkspaceProfile.SOLO_DEV: 0.05,
    },
    "codeowners": {
        WorkspaceProfile.TEAM_COLLAB: 0.25,
    },
    "pr_template": {
        WorkspaceProfile.TEAM_COLLAB: 0.20,
    },
    # Compliance signals
    "policy_dir": {
        WorkspaceProfile.COMPLIANCE_SENSITIVE: 0.35,
    },
    "security_md": {
        WorkspaceProfile.COMPLIANCE_SENSITIVE: 0.20,
        WorkspaceProfile.TEAM_COLLAB: 0.05,
    },
    "soc2_or_hipaa": {
        WorkspaceProfile.COMPLIANCE_SENSITIVE: 0.30,
    },
    # Solo-dev signals (absence-based — detected separately)
    "pyproject_toml": {
        WorkspaceProfile.SOLO_DEV: 0.10,
        WorkspaceProfile.API_BACKEND: 0.05,
        WorkspaceProfile.AMPREALIZE_PLATFORM: 0.05,
    },
    "single_contributor": {
        WorkspaceProfile.SOLO_DEV: 0.30,
    },
}

# Ambiguity threshold: if the gap between top-2 profiles is less than
# this fraction of the leader's score, the result is marked ambiguous.
_AMBIGUITY_THRESHOLD = 0.15


class WorkspaceDetector:
    """Detects workspace signals and suggests a profile.

    Usage::

        detector = WorkspaceDetector()
        result = detector.detect(Path("/path/to/workspace"))
        print(result.profile, result.confidence)
    """

    def detect_signals(self, workspace: Path) -> List[WorkspaceSignal]:
        """Scan *workspace* for structural signals.

        Returns a list of ``WorkspaceSignal`` objects, one per probe.
        Signals with ``detected=False`` are still returned so callers
        can inspect what was *not* found.
        """
        signals: List[WorkspaceSignal] = []
        signals.append(self._check_agents_md(workspace))
        signals.append(self._check_amprealize_imports(workspace))
        signals.append(self._check_mcp_tools_dir(workspace))
        signals.append(self._check_knowledge_pack_dir(workspace))
        signals.append(self._check_extension_dir(workspace))
        signals.append(self._check_vscode_extension_manifest(workspace))
        signals.append(self._check_fastapi_or_flask(workspace))
        signals.append(self._check_alembic_ini(workspace))
        signals.append(self._check_openapi_spec(workspace))
        signals.append(self._check_github_dir(workspace))
        signals.append(self._check_codeowners(workspace))
        signals.append(self._check_pr_template(workspace))
        signals.append(self._check_policy_dir(workspace))
        signals.append(self._check_security_md(workspace))
        signals.append(self._check_soc2_or_hipaa(workspace))
        signals.append(self._check_pyproject_toml(workspace))
        signals.append(self._check_single_contributor(workspace))
        return signals

    def suggest_profile(
        self, signals: List[WorkspaceSignal]
    ) -> ProfileDetectionResult:
        """Score profiles against *signals* and return the best match."""
        scores: Dict[WorkspaceProfile, float] = {p: 0.0 for p in WorkspaceProfile}

        for sig in signals:
            if not sig.detected:
                continue
            weights = _PROFILE_WEIGHTS.get(sig.signal_name, {})
            for profile, weight in weights.items():
                scores[profile] += weight * sig.confidence

        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        best_profile, best_score = ranked[0]
        runner_profile, runner_score = ranked[1] if len(ranked) > 1 else (None, 0.0)

        # Normalise confidence to 0–1 (cap at 1.0)
        confidence = min(best_score, 1.0)

        # Ambiguity: two profiles close in score
        is_ambiguous = False
        if best_score > 0 and runner_score > 0:
            gap = (best_score - runner_score) / best_score
            if gap < _AMBIGUITY_THRESHOLD:
                is_ambiguous = True

        # If nothing scored, default to solo-dev
        if best_score == 0:
            best_profile = WorkspaceProfile.SOLO_DEV
            confidence = 0.1

        return ProfileDetectionResult(
            profile=best_profile,
            confidence=confidence,
            signals=signals,
            is_ambiguous=is_ambiguous,
            runner_up=runner_profile if is_ambiguous else None,
        )

    def detect(self, workspace: Path) -> ProfileDetectionResult:
        """Convenience: detect signals then suggest profile in one call."""
        signals = self.detect_signals(workspace)
        return self.suggest_profile(signals)

    # ====================================================================
    # Individual signal probes
    # ====================================================================

    @staticmethod
    def _check_agents_md(ws: Path) -> WorkspaceSignal:
        path = ws / "AGENTS.md"
        if path.is_file():
            size = path.stat().st_size
            return WorkspaceSignal(
                signal_name="agents_md",
                detected=True,
                confidence=min(1.0, size / 500),  # larger = more real
                evidence=f"AGENTS.md found ({size} bytes)",
            )
        return WorkspaceSignal(signal_name="agents_md", detected=False)

    @staticmethod
    def _check_amprealize_imports(ws: Path) -> WorkspaceSignal:
        """Look for ``amprealize/`` package directory with Python files."""
        pkg = ws / "amprealize"
        if pkg.is_dir() and (pkg / "__init__.py").is_file():
            return WorkspaceSignal(
                signal_name="amprealize_imports",
                detected=True,
                confidence=1.0,
                evidence="amprealize/ package with __init__.py",
            )
        return WorkspaceSignal(signal_name="amprealize_imports", detected=False)

    @staticmethod
    def _check_mcp_tools_dir(ws: Path) -> WorkspaceSignal:
        mcp = ws / "mcp" / "tools"
        if mcp.is_dir():
            tool_count = len(list(mcp.glob("*.json")))
            if tool_count > 0:
                return WorkspaceSignal(
                    signal_name="mcp_tools_dir",
                    detected=True,
                    confidence=min(1.0, tool_count / 5),
                    evidence=f"mcp/tools/ with {tool_count} JSON schemas",
                )
        return WorkspaceSignal(signal_name="mcp_tools_dir", detected=False)

    @staticmethod
    def _check_knowledge_pack_dir(ws: Path) -> WorkspaceSignal:
        kp = ws / "amprealize" / "knowledge_pack"
        if kp.is_dir() and (kp / "__init__.py").is_file():
            return WorkspaceSignal(
                signal_name="knowledge_pack_dir",
                detected=True,
                confidence=1.0,
                evidence="amprealize/knowledge_pack/ package found",
            )
        return WorkspaceSignal(signal_name="knowledge_pack_dir", detected=False)

    @staticmethod
    def _check_extension_dir(ws: Path) -> WorkspaceSignal:
        ext = ws / "extension"
        if ext.is_dir() and (ext / "package.json").is_file():
            return WorkspaceSignal(
                signal_name="extension_dir",
                detected=True,
                confidence=0.9,
                evidence="extension/ directory with package.json",
            )
        return WorkspaceSignal(signal_name="extension_dir", detected=False)

    @staticmethod
    def _check_vscode_extension_manifest(ws: Path) -> WorkspaceSignal:
        """Check for VS Code extension manifest keys in extension/package.json."""
        pkg_json = ws / "extension" / "package.json"
        if pkg_json.is_file():
            try:
                import json

                data = json.loads(pkg_json.read_text(encoding="utf-8"))
                if "contributes" in data or "activationEvents" in data:
                    return WorkspaceSignal(
                        signal_name="vscode_extension_manifest",
                        detected=True,
                        confidence=1.0,
                        evidence="extension/package.json has VS Code extension keys",
                    )
            except (json.JSONDecodeError, OSError):
                pass
        return WorkspaceSignal(
            signal_name="vscode_extension_manifest", detected=False
        )

    @staticmethod
    def _check_fastapi_or_flask(ws: Path) -> WorkspaceSignal:
        """Check pyproject.toml or requirements for FastAPI/Flask."""
        for candidate in ("pyproject.toml", "requirements.txt", "setup.cfg"):
            p = ws / candidate
            if p.is_file():
                try:
                    text = p.read_text(encoding="utf-8").lower()
                    for framework in ("fastapi", "flask", "django", "starlette"):
                        if framework in text:
                            return WorkspaceSignal(
                                signal_name="fastapi_or_flask",
                                detected=True,
                                confidence=0.9,
                                evidence=f"{framework} found in {candidate}",
                            )
                except OSError:
                    pass
        return WorkspaceSignal(signal_name="fastapi_or_flask", detected=False)

    @staticmethod
    def _check_alembic_ini(ws: Path) -> WorkspaceSignal:
        if (ws / "alembic.ini").is_file():
            return WorkspaceSignal(
                signal_name="alembic_ini",
                detected=True,
                confidence=0.9,
                evidence="alembic.ini found",
            )
        return WorkspaceSignal(signal_name="alembic_ini", detected=False)

    @staticmethod
    def _check_openapi_spec(ws: Path) -> WorkspaceSignal:
        for name in ("openapi.yaml", "openapi.yml", "openapi.json", "swagger.json"):
            if (ws / name).is_file() or (ws / "docs" / name).is_file():
                return WorkspaceSignal(
                    signal_name="openapi_spec",
                    detected=True,
                    confidence=0.8,
                    evidence=f"{name} found",
                )
        return WorkspaceSignal(signal_name="openapi_spec", detected=False)

    @staticmethod
    def _check_github_dir(ws: Path) -> WorkspaceSignal:
        gh = ws / ".github"
        if gh.is_dir():
            return WorkspaceSignal(
                signal_name="github_dir",
                detected=True,
                confidence=0.7,
                evidence=".github/ directory found",
            )
        return WorkspaceSignal(signal_name="github_dir", detected=False)

    @staticmethod
    def _check_codeowners(ws: Path) -> WorkspaceSignal:
        for loc in (
            ws / "CODEOWNERS",
            ws / ".github" / "CODEOWNERS",
            ws / "docs" / "CODEOWNERS",
        ):
            if loc.is_file():
                return WorkspaceSignal(
                    signal_name="codeowners",
                    detected=True,
                    confidence=0.9,
                    evidence=f"CODEOWNERS at {loc.relative_to(ws)}",
                )
        return WorkspaceSignal(signal_name="codeowners", detected=False)

    @staticmethod
    def _check_pr_template(ws: Path) -> WorkspaceSignal:
        templates = ws / ".github" / "PULL_REQUEST_TEMPLATE"
        single = ws / ".github" / "pull_request_template.md"
        if templates.is_dir() or single.is_file():
            return WorkspaceSignal(
                signal_name="pr_template",
                detected=True,
                confidence=0.8,
                evidence="PR template found in .github/",
            )
        return WorkspaceSignal(signal_name="pr_template", detected=False)

    @staticmethod
    def _check_policy_dir(ws: Path) -> WorkspaceSignal:
        if (ws / "policy").is_dir():
            return WorkspaceSignal(
                signal_name="policy_dir",
                detected=True,
                confidence=0.9,
                evidence="policy/ directory found",
            )
        return WorkspaceSignal(signal_name="policy_dir", detected=False)

    @staticmethod
    def _check_security_md(ws: Path) -> WorkspaceSignal:
        if (ws / "SECURITY.md").is_file():
            return WorkspaceSignal(
                signal_name="security_md",
                detected=True,
                confidence=0.7,
                evidence="SECURITY.md found",
            )
        return WorkspaceSignal(signal_name="security_md", detected=False)

    @staticmethod
    def _check_soc2_or_hipaa(ws: Path) -> WorkspaceSignal:
        """Check for compliance-related files or keywords."""
        compliance_files = [
            "SOC2.md",
            "HIPAA.md",
            "COMPLIANCE.md",
            "compliance.yaml",
        ]
        for name in compliance_files:
            if (ws / name).is_file() or (ws / "docs" / name).is_file():
                return WorkspaceSignal(
                    signal_name="soc2_or_hipaa",
                    detected=True,
                    confidence=0.9,
                    evidence=f"{name} found",
                )
        return WorkspaceSignal(signal_name="soc2_or_hipaa", detected=False)

    @staticmethod
    def _check_pyproject_toml(ws: Path) -> WorkspaceSignal:
        if (ws / "pyproject.toml").is_file():
            return WorkspaceSignal(
                signal_name="pyproject_toml",
                detected=True,
                confidence=0.6,
                evidence="pyproject.toml found",
            )
        return WorkspaceSignal(signal_name="pyproject_toml", detected=False)

    @staticmethod
    def _check_single_contributor(ws: Path) -> WorkspaceSignal:
        """Heuristic: no .github/CODEOWNERS, no PR template, no team markers."""
        has_codeowners = any(
            (ws / loc).is_file()
            for loc in ("CODEOWNERS", ".github/CODEOWNERS")
        )
        has_pr_template = (
            (ws / ".github" / "pull_request_template.md").is_file()
            or (ws / ".github" / "PULL_REQUEST_TEMPLATE").is_dir()
        )
        if not has_codeowners and not has_pr_template:
            return WorkspaceSignal(
                signal_name="single_contributor",
                detected=True,
                confidence=0.5,
                evidence="No CODEOWNERS or PR templates — likely solo contributor",
            )
        return WorkspaceSignal(signal_name="single_contributor", detected=False)
