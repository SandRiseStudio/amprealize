"""Overlay classification rules for knowledge pack generation.

Implements T1.3.2 (AMPREALIZE-302) of the Knowledge Pack Foundations epic.

Provides rule-based classification for:
- Task families: docs, implementation, testing, migration, config, deployment, incident
- Surface rules: vscode, cli, mcp, copilot, claude
- Role rules: Student (execution), Teacher (examples), Strategist (analysis)

These rules determine which overlays a fragment belongs to, enabling
targeted guidance injection during BCI prompt composition.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set


# ---------------------------------------------------------------------------
# Enums & Constants
# ---------------------------------------------------------------------------


class TaskFamily(str, Enum):
    """Recognized task families for overlay classification."""

    DOCS = "docs"
    IMPLEMENTATION = "implementation"
    TESTING = "testing"
    MIGRATION = "migration"
    CONFIG = "config"
    DEPLOYMENT = "deployment"
    INCIDENT = "incident"
    GENERAL = "general"  # fallback


class Surface(str, Enum):
    """Target surfaces for overlay generation."""

    VSCODE = "vscode"
    CLI = "cli"
    MCP = "mcp"
    COPILOT = "copilot"
    CLAUDE = "claude"
    WEB = "web"
    API = "api"


class Role(str, Enum):
    """Agent roles per Amprealize metacognitive framework."""

    STUDENT = "student"
    TEACHER = "teacher"
    STRATEGIST = "strategist"
    ENGINEER = "engineer"  # fallback / default


# ---------------------------------------------------------------------------
# Classification rule dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TaskClassificationRule:
    """Rule for classifying content into a task family.

    Attributes:
        family: Target task family.
        keywords: Trigger words that suggest this family.
        patterns: Regex patterns to match (case-insensitive).
        priority: Higher priority rules take precedence (default 0).
    """

    family: TaskFamily
    keywords: Set[str] = field(default_factory=set)
    patterns: List[str] = field(default_factory=list)
    priority: int = 0

    def matches(self, text: str) -> bool:
        """Return True if *text* matches this rule."""
        text_lower = text.lower()
        # Keyword match — any keyword found in text
        for kw in self.keywords:
            if kw in text_lower:
                return True
        # Pattern match
        for pat in self.patterns:
            if re.search(pat, text, re.IGNORECASE):
                return True
        return False


@dataclass
class SurfaceClassificationRule:
    """Rule for classifying content to a target surface.

    Attributes:
        surface: Target surface.
        keywords: Trigger words for this surface.
        patterns: Regex patterns to match.
        file_extensions: File extensions that indicate this surface.
    """

    surface: Surface
    keywords: Set[str] = field(default_factory=set)
    patterns: List[str] = field(default_factory=list)
    file_extensions: Set[str] = field(default_factory=set)

    def matches(self, text: str, *, file_path: str = "") -> bool:
        """Return True if *text* or *file_path* matches this rule."""
        text_lower = text.lower()
        for kw in self.keywords:
            if kw in text_lower:
                return True
        for pat in self.patterns:
            if re.search(pat, text, re.IGNORECASE):
                return True
        if file_path:
            ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
            if ext in self.file_extensions:
                return True
        return False


@dataclass
class RoleClassificationRule:
    """Rule for classifying content to an agent role.

    Attributes:
        role: Target role.
        keywords: Trigger words for this role.
        patterns: Regex patterns to match.
    """

    role: Role
    keywords: Set[str] = field(default_factory=set)
    patterns: List[str] = field(default_factory=list)

    def matches(self, text: str) -> bool:
        """Return True if *text* matches this rule."""
        text_lower = text.lower()
        for kw in self.keywords:
            if kw in text_lower:
                return True
        for pat in self.patterns:
            if re.search(pat, text, re.IGNORECASE):
                return True
        return False


# ---------------------------------------------------------------------------
# Default rule sets
# ---------------------------------------------------------------------------

DEFAULT_TASK_RULES: List[TaskClassificationRule] = [
    TaskClassificationRule(
        family=TaskFamily.DOCS,
        keywords={
            "documentation",
            "readme",
            "docstring",
            "api docs",
            "jsdoc",
            "pydoc",
            "wiki",
            "changelog",
            "release notes",
            "user guide",
        },
        patterns=[
            r"\bdocs?\b",
            r"\bdocument(ing|ed|ation)?\b",
            r"readme\.md",
            r"changelog\.md",
        ],
        priority=1,
    ),
    TaskClassificationRule(
        family=TaskFamily.IMPLEMENTATION,
        keywords={
            "implement",
            "feature",
            "add function",
            "create class",
            "write code",
            "build",
            "coding",
            "develop",
            "refactor",
        },
        patterns=[
            r"\bimplement(ing|ed|ation)?\b",
            r"\bfeature\b",
            r"\bcoding\b",
            r"\brefactor(ing)?\b",
        ],
        priority=0,
    ),
    TaskClassificationRule(
        family=TaskFamily.TESTING,
        keywords={
            "test",
            "pytest",
            "unittest",
            "jest",
            "mocha",
            "coverage",
            "tdd",
            "assertion",
            "mock",
            "fixture",
            "spec",
        },
        patterns=[
            r"\btest(ing|ed|s)?\b",
            r"\bspec(s)?\b",
            r"\bcoverage\b",
            r"test_\w+\.py",
            r"\.spec\.(ts|js)",
        ],
        priority=2,
    ),
    TaskClassificationRule(
        family=TaskFamily.MIGRATION,
        keywords={
            "migration",
            "alembic",
            "schema change",
            "database migration",
            "upgrade",
            "downgrade",
            "migrate",
        },
        patterns=[
            r"\bmigrat(e|ing|ion)\b",
            r"\balembic\b",
            r"schema.*(change|update)",
        ],
        priority=2,
    ),
    TaskClassificationRule(
        family=TaskFamily.CONFIG,
        keywords={
            "config",
            "configuration",
            "settings",
            "environment",
            "env var",
            ".env",
            "yaml",
            "toml",
            "ini",
        },
        patterns=[
            r"\bconfig(uration)?\b",
            r"\bsettings?\b",
            r"\.env\b",
            r"\.ya?ml\b",
            r"\.toml\b",
        ],
        priority=1,
    ),
    TaskClassificationRule(
        family=TaskFamily.DEPLOYMENT,
        keywords={
            "deploy",
            "deployment",
            "ci/cd",
            "pipeline",
            "docker",
            "kubernetes",
            "k8s",
            "helm",
            "release",
            "rollout",
            "production",
        },
        patterns=[
            r"\bdeploy(ing|ment|ed)?\b",
            r"\bci/?cd\b",
            r"\bkubernetes|k8s\b",
            r"\bdocker(file)?\b",
            r"\bhelm\b",
        ],
        priority=1,
    ),
    TaskClassificationRule(
        family=TaskFamily.INCIDENT,
        keywords={
            "incident",
            "outage",
            "alert",
            "on-call",
            "postmortem",
            "rca",
            "root cause",
            "p1",
            "p2",
            "severity",
            "triage",
        },
        patterns=[
            r"\bincident\b",
            r"\boutage\b",
            r"\bpostmortem\b",
            r"\broot.?cause\b",
            r"\btriage\b",
        ],
        priority=3,  # High priority — incident tasks are urgent
    ),
]

DEFAULT_SURFACE_RULES: List[SurfaceClassificationRule] = [
    SurfaceClassificationRule(
        surface=Surface.VSCODE,
        keywords={
            "vscode",
            "vs code",
            "visual studio code",
            "extension",
            "webview",
            "treeview",
            "command palette",
        },
        patterns=[
            r"\bvs\s*code\b",
            r"\bextension\.ts\b",
            r"TreeDataProvider",
            r"WebviewPanel",
        ],
        file_extensions={"vsix"},
    ),
    SurfaceClassificationRule(
        surface=Surface.CLI,
        keywords={
            "cli",
            "command line",
            "terminal",
            "argparse",
            "click",
            "typer",
            "amprealize init",
            "amprealize run",
        },
        patterns=[
            r"\bcli\b",
            r"command.?line",
            r"argparse",
            r"if __name__.*__main__",
        ],
    ),
    SurfaceClassificationRule(
        surface=Surface.MCP,
        keywords={
            "mcp",
            "model context protocol",
            "mcp tool",
            "mcp server",
            "tool manifest",
        },
        patterns=[
            r"\bmcp\b",
            r"ToolGroupId",
            r"mcp_server",
            r"tool.*manifest",
        ],
        file_extensions={"json"},  # Tool manifests are JSON
    ),
    SurfaceClassificationRule(
        surface=Surface.COPILOT,
        keywords={
            "copilot",
            "github copilot",
            "copilot instructions",
            "copilot-instructions.md",
        },
        patterns=[
            r"\bcopilot\b",
            r"copilot-instructions\.md",
        ],
    ),
    SurfaceClassificationRule(
        surface=Surface.CLAUDE,
        keywords={
            "claude",
            "claude.md",
            "anthropic",
        },
        patterns=[
            r"\bclaude\b",
            r"CLAUDE\.md",
        ],
    ),
    SurfaceClassificationRule(
        surface=Surface.WEB,
        keywords={
            "web",
            "browser",
            "react",
            "vue",
            "angular",
            "frontend",
            "dashboard",
            "ui",
        },
        patterns=[
            r"\bweb\s*(app|console|ui)?\b",
            r"\bfrontend\b",
            r"\bdashboard\b",
        ],
        file_extensions={"tsx", "jsx", "vue", "svelte"},
    ),
    SurfaceClassificationRule(
        surface=Surface.API,
        keywords={
            "api",
            "rest",
            "graphql",
            "fastapi",
            "flask",
            "endpoint",
            "route",
        },
        patterns=[
            r"\bapi\b",
            r"\brest(ful)?\b",
            r"@(app|router)\.(get|post|put|delete|patch)",
        ],
    ),
]

DEFAULT_ROLE_RULES: List[RoleClassificationRule] = [
    RoleClassificationRule(
        role=Role.STUDENT,
        keywords={
            "student",
            "routine",
            "follow pattern",
            "established behavior",
            "execute",
            "apply",
        },
        patterns=[
            r"\bstudent\b",
            r"routine\s+execution",
            r"follow(ing)?\s+behavior",
        ],
    ),
    RoleClassificationRule(
        role=Role.TEACHER,
        keywords={
            "teacher",
            "example",
            "documentation",
            "reference",
            "validate",
            "review",
            "explain",
        },
        patterns=[
            r"\bteacher\b",
            r"creat(e|ing)\s+example",
            r"document(ation|ing)",
        ],
    ),
    RoleClassificationRule(
        role=Role.STRATEGIST,
        keywords={
            "strategist",
            "metacognitive",
            "root cause",
            "analysis",
            "architecture",
            "design decision",
            "propose behavior",
        },
        patterns=[
            r"\bstrategist\b",
            r"\bmetacognitive\b",
            r"root\s+cause\s+analysis",
            r"propos(e|ing)\s+behavior",
        ],
    ),
]


# ---------------------------------------------------------------------------
# Classifier class
# ---------------------------------------------------------------------------


class OverlayClassifier:
    """Classifies text into task families, surfaces, and roles.

    Uses configurable rule sets; falls back to defaults if none provided.
    """

    def __init__(
        self,
        *,
        task_rules: Optional[List[TaskClassificationRule]] = None,
        surface_rules: Optional[List[SurfaceClassificationRule]] = None,
        role_rules: Optional[List[RoleClassificationRule]] = None,
    ):
        self.task_rules = task_rules or DEFAULT_TASK_RULES
        self.surface_rules = surface_rules or DEFAULT_SURFACE_RULES
        self.role_rules = role_rules or DEFAULT_ROLE_RULES

    def classify_task(self, text: str) -> TaskFamily:
        """Return the highest-priority matching task family, or GENERAL."""
        matches: List[TaskClassificationRule] = []
        for rule in self.task_rules:
            if rule.matches(text):
                matches.append(rule)
        if not matches:
            return TaskFamily.GENERAL
        # Sort by priority descending, take first
        matches.sort(key=lambda r: r.priority, reverse=True)
        return matches[0].family

    def classify_surfaces(
        self, text: str, *, file_path: str = ""
    ) -> List[Surface]:
        """Return all matching surfaces (can be multiple)."""
        result: List[Surface] = []
        for rule in self.surface_rules:
            if rule.matches(text, file_path=file_path):
                result.append(rule.surface)
        return result

    def classify_role(self, text: str) -> Role:
        """Return the matching role, or ENGINEER as default."""
        for rule in self.role_rules:
            if rule.matches(text):
                return rule.role
        return Role.ENGINEER

    def classify_all(
        self, text: str, *, file_path: str = ""
    ) -> Dict[str, object]:
        """Return full classification result.

        Returns:
            {
                "task_family": TaskFamily,
                "surfaces": [Surface, ...],
                "role": Role,
            }
        """
        return {
            "task_family": self.classify_task(text),
            "surfaces": self.classify_surfaces(text, file_path=file_path),
            "role": self.classify_role(text),
        }


# ---------------------------------------------------------------------------
# Overlay filtering helpers
# ---------------------------------------------------------------------------


def filter_overlays_by_task(
    overlays: List[Dict], task_family: TaskFamily
) -> List[Dict]:
    """Filter overlay dicts to those matching *task_family*."""
    return [
        o
        for o in overlays
        if o.get("applies_to", {}).get("task_family") == task_family.value
    ]


def filter_overlays_by_surface(
    overlays: List[Dict], surface: Surface
) -> List[Dict]:
    """Filter overlay dicts to those matching *surface*."""
    return [
        o
        for o in overlays
        if o.get("applies_to", {}).get("surface") == surface.value
    ]


def filter_overlays_by_role(overlays: List[Dict], role: Role) -> List[Dict]:
    """Filter overlay dicts to those matching *role*."""
    return [
        o for o in overlays if o.get("applies_to", {}).get("role") == role.value
    ]


# Default classifier instance for convenience
default_classifier = OverlayClassifier()
