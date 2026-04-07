"""
Test behavior coverage to enforce >80% target per AGENTS.md metrics.

This test parses AGENTS.md and AGENT_*.md files to:
1. Extract all defined behaviors from AGENTS.md
2. Extract all task categories from AGENT_*.md domain playbooks
3. Map tasks to behaviors via explicit references and keyword matching
4. Calculate coverage rate and fail CI if below 80%

Following `behavior_curate_behavior_handbook` (Metacognitive Strategist):
Coverage tracking ensures the behavior handbook remains effective.
"""

import re
import os
from pathlib import Path
from typing import NamedTuple

import pytest

from amprealize.agent_registry_service import AgentRegistryService
from amprealize.services.agent_loader import AgentPlaybookLoader

# Paths relative to repo root
REPO_ROOT = Path(__file__).parent.parent
AGENTS_MD = REPO_ROOT / "AGENTS.md"
PLAYBOOKS_DIR = REPO_ROOT / "amprealize" / "agents" / "playbooks"
PLAYBOOK_FILES = AgentPlaybookLoader(agents_dir=PLAYBOOKS_DIR).discover_playbooks()

# Coverage target per AGENTS.md ## Behavior Metrics & Health
COVERAGE_TARGET = 0.80  # >80% of tasks covered


class Behavior(NamedTuple):
    """A behavior extracted from AGENTS.md."""
    name: str
    keywords: list[str]
    role: str


class TaskCategory(NamedTuple):
    """A task category extracted from AGENT_*.md files."""
    source_file: str
    category_name: str
    description: str
    referenced_behaviors: list[str]


class PlaybookSource(NamedTuple):
    """Registry-backed playbook content plus inherited default behaviors."""
    slug: str
    content: str
    default_behaviors: list[str]


def _agent_registry_dsn() -> str | None:
    """Return the registry/execution DSN used for builtin agent playbooks."""
    return (
        os.environ.get("AMPREALIZE_AGENT_REGISTRY_PG_DSN")
        or os.environ.get("AMPREALIZE_EXECUTION_PG_DSN")
        or os.environ.get("AMPREALIZE_PG_DSN")
    )


def _load_registry_playbooks() -> list[PlaybookSource]:
    """Load builtin playbooks from the agent registry DB, bootstrapping them if needed."""
    dsn = _agent_registry_dsn()
    if not dsn:
        return []

    service = AgentRegistryService(dsn=dsn, agents_dir=PLAYBOOKS_DIR)
    service.bootstrap_from_playbooks(force=True)

    conn = service._pool.proxy()  # noqa: SLF001 - test helper needs direct registry query
    with conn.cursor() as cur:
        cur.execute(
            """
                        SELECT a.slug, av.playbook_content, av.default_behaviors
            FROM execution.agents a
            JOIN execution.agent_versions av ON av.agent_id = a.agent_id
            WHERE a.is_builtin = TRUE
              AND av.status = 'ACTIVE'
              AND av.playbook_content IS NOT NULL
            ORDER BY a.slug
            """
        )
        rows = cur.fetchall()

    return [
        PlaybookSource(slug=row[0], content=row[1], default_behaviors=list(row[2] or []))
        for row in rows
        if row[1]
    ]


def _load_playbook_sources() -> list[PlaybookSource]:
    """Load playbook content from the registry DB, falling back to filesystem when needed."""
    registry_rows = _load_registry_playbooks()
    if registry_rows:
        return registry_rows

    loader = AgentPlaybookLoader(agents_dir=PLAYBOOKS_DIR)
    parsed = loader.load_all()
    return [
        PlaybookSource(
            slug=playbook.agent_id,
            content=Path(playbook.playbook_path).read_text() if playbook.playbook_path else "",
            default_behaviors=list(playbook.default_behaviors),
        )
        for playbook in parsed
        if playbook.playbook_path
    ]


def extract_behaviors_from_agents_md() -> list[Behavior]:
    """
    Parse AGENTS.md to extract all behavior definitions.

    Looks for patterns like:
    - ### `behavior_name` in the Behaviors section
    - Quick Triggers table entries
    """
    content = AGENTS_MD.read_text()
    behaviors = []

    # Extract from ### `behavior_*` headers in Behaviors section
    behavior_pattern = r"### `(behavior_\w+)`"
    for match in re.finditer(behavior_pattern, content):
        name = match.group(1)
        # Extract keywords from Quick Triggers table
        keywords = _extract_keywords_for_behavior(content, name)
        role = _extract_role_for_behavior(content, name)
        behaviors.append(Behavior(name=name, keywords=keywords, role=role))

    return behaviors


def _extract_keywords_for_behavior(content: str, behavior_name: str) -> list[str]:
    """Extract trigger keywords for a behavior from Quick Triggers table."""
    keywords = []

    # Find Quick Triggers table section
    triggers_section = re.search(
        r"## 🎯 Quick Triggers.*?\n\n(.*?)\n\n---",
        content,
        re.DOTALL
    )
    if not triggers_section:
        return keywords

    table_content = triggers_section.group(1)

    # Find rows mentioning this behavior
    for line in table_content.split("\n"):
        if behavior_name in line and "|" in line:
            parts = line.split("|")
            if len(parts) >= 2:
                # First column contains keywords
                keyword_text = parts[1].strip().strip("*")
                keywords.extend([k.strip() for k in keyword_text.split(",") if k.strip()])

    return keywords


def _extract_role_for_behavior(content: str, behavior_name: str) -> str:
    """Extract the default role for a behavior."""
    # Check Quick Triggers table for role
    triggers_section = re.search(
        r"## 🎯 Quick Triggers.*?\n\n(.*?)\n\n---",
        content,
        re.DOTALL
    )
    if triggers_section:
        for line in triggers_section.group(1).split("\n"):
            if behavior_name in line:
                if "📖 Student" in line:
                    return "Student"
                elif "🎓 Teacher" in line:
                    return "Teacher"
                elif "🧠" in line or "Strategist" in line:
                    return "Strategist"

    # Check behavior definition for role
    behavior_section = re.search(
        rf"### `{behavior_name}`.*?(?=### `behavior_|---|\Z)",
        content,
        re.DOTALL
    )
    if behavior_section:
        text = behavior_section.group(0)
        if "Student" in text and "Role" in text:
            return "Student"
        elif "Teacher" in text and "Role" in text:
            return "Teacher"
        elif "Strategist" in text and "Role" in text:
            return "Strategist"

    return "Student"  # Default


def extract_task_categories_from_agent_files() -> list[TaskCategory]:
    """
    Parse AGENT_*.md files to extract task categories.

    Looks for:
    - H2/H3 headers describing task areas
    - Explicit behavior references in the content
    - Checklist items describing tasks
    """
    categories = []

    for playbook in _load_playbook_sources():
        agent_name = f"AGENT_{playbook.slug.upper()}"
        content = playbook.content
        inherited_behaviors = list(playbook.default_behaviors)

        # Extract task categories from headers and checklists
        # Look for ## or ### headers followed by content
        header_pattern = r"^(#{2,3})\s+(.+?)$"

        current_section = None
        current_description = []
        referenced_behaviors = []

        for line in content.split("\n"):
            header_match = re.match(header_pattern, line)
            if header_match:
                # Save previous section if exists
                if current_section:
                    categories.append(TaskCategory(
                        source_file=agent_name,
                        category_name=current_section,
                        description="\n".join(current_description),
                        referenced_behaviors=list(set(referenced_behaviors))
                    ))

                current_section = header_match.group(2).strip()
                current_description = []
                referenced_behaviors = list(inherited_behaviors)
            else:
                if current_section:
                    current_description.append(line)
                    # Extract behavior references
                    behavior_refs = re.findall(r"`(behavior_\w+)`", line)
                    referenced_behaviors.extend(behavior_refs)

        # Save last section
        if current_section:
            categories.append(TaskCategory(
                source_file=agent_name,
                category_name=current_section,
                description="\n".join(current_description),
                referenced_behaviors=list(set(referenced_behaviors))
            ))

    return categories


def calculate_coverage(
    behaviors: list[Behavior],
    task_categories: list[TaskCategory]
) -> tuple[float, dict]:
    """
    Calculate behavior coverage for task categories.

    A task is covered if:
    1. It explicitly references a behavior, OR
    2. Its description/name contains keywords from a behavior's triggers

    Returns:
        Tuple of (coverage_rate, details_dict)
    """
    behavior_names = {b.name for b in behaviors}
    behavior_keywords = {}
    for b in behaviors:
        for kw in b.keywords:
            behavior_keywords[kw.lower()] = b.name

    covered_tasks = []
    uncovered_tasks = []

    for task in task_categories:
        # Skip meta sections that aren't actual tasks
        skip_patterns = [
            # Meta sections
            "overview", "context", "appendix", "reference", "tl;dr", "summary",
            "table of contents", "introduction", "handbook", "mission",
            # Template/format sections (not actual tasks)
            "output template", "evaluation rubric", "decision rubric",
            "escalation rules", "workflow", "required inputs", "style guardrails",
            # Specific non-task headings
            "keep it clear", "no fluff", "action-oriented", "consistent formatting",
            "be precise", "behavior contributions", "checklist",
            # Fine-grained style guidelines (covered by behavior_craft_messaging)
            "no redundant", "buttons and actions", "neutral", "professional tone",
            "anticipate user", "ui copy", "timeframe", "user-centered",
            "prior knowledge", "solution-oriented", "distraction", "error message",
            "confirmation message", "form label", "cta", "short but", "cleverness",
            "show don't tell", "sentence case", "passive voice", "remove it",
            "progressive disclosure", "knows what they", "keep it short",
            "show, don't tell",
            # Contract/schema sections (technical specs, not tasks)
            "schemas", "proto", "`agent", "rbac scopes", "`switch", "`assignment",
            # Agent review templates (output format, not tasks)
            "agent review"
        ]
        if any(skip in task.category_name.lower() for skip in skip_patterns):
            continue

        coverage_reason = None

        # Check explicit references
        if task.referenced_behaviors:
            coverage_reason = f"explicit: {', '.join(task.referenced_behaviors)}"

        # Check keyword matches
        if not coverage_reason:
            task_text = f"{task.category_name} {task.description}".lower()
            for keyword, behavior_name in behavior_keywords.items():
                if keyword in task_text:
                    coverage_reason = f"keyword '{keyword}' -> {behavior_name}"
                    break

        if coverage_reason:
            covered_tasks.append((task, coverage_reason))
        else:
            uncovered_tasks.append(task)

    total_tasks = len(covered_tasks) + len(uncovered_tasks)
    coverage_rate = len(covered_tasks) / total_tasks if total_tasks > 0 else 0

    return coverage_rate, {
        "total_tasks": total_tasks,
        "covered_count": len(covered_tasks),
        "uncovered_count": len(uncovered_tasks),
        "covered_tasks": covered_tasks,
        "uncovered_tasks": uncovered_tasks,
        "behaviors_count": len(behaviors)
    }


class TestBehaviorCoverage:
    """Test suite for behavior coverage metrics."""

    @pytest.fixture(scope="class")
    def behaviors(self) -> list[Behavior]:
        """Extract behaviors from AGENTS.md."""
        return extract_behaviors_from_agents_md()

    @pytest.fixture(scope="class")
    def task_categories(self) -> list[TaskCategory]:
        """Extract task categories from AGENT_*.md files."""
        return extract_task_categories_from_agent_files()

    @pytest.fixture(scope="class")
    def coverage_data(
        self,
        behaviors: list[Behavior],
        task_categories: list[TaskCategory]
    ) -> tuple[float, dict]:
        """Calculate coverage metrics."""
        return calculate_coverage(behaviors, task_categories)

    def test_agents_md_exists(self):
        """Verify AGENTS.md handbook exists."""
        assert AGENTS_MD.exists(), "AGENTS.md not found at repo root"

    def test_agent_files_exist(self):
        """Verify at least one AGENT_*.md playbook exists in the playbook directory."""
        assert len(PLAYBOOK_FILES) > 0, "No AGENT_*.md files found in amprealize/agents/playbooks"

    def test_playbooks_bootstrapped_to_registry(self):
        """Verify builtin playbooks are present in the applicable registry DB when configured."""
        dsn = _agent_registry_dsn()
        if not dsn:
            pytest.skip("Agent registry DB not configured")

        expected = {path.stem.replace("AGENT_", "").lower() for path in PLAYBOOK_FILES}
        registered = {playbook.slug for playbook in _load_registry_playbooks()}
        missing = sorted(expected - registered)
        assert not missing, f"Builtin playbooks missing from agent registry DB: {missing}"

    def test_behaviors_extracted(self, behaviors: list[Behavior]):
        """Verify behaviors can be extracted from AGENTS.md."""
        assert len(behaviors) >= 20, (
            f"Expected at least 20 behaviors, found {len(behaviors)}. "
            "Check AGENTS.md formatting."
        )

    def test_task_categories_extracted(self, task_categories: list[TaskCategory]):
        """Verify task categories can be extracted from registry-backed playbooks."""
        assert len(task_categories) >= 10, (
            f"Expected at least 10 task categories, found {len(task_categories)}. "
            "Check agent playbook content and registry bootstrap."
        )

    def test_coverage_meets_target(self, coverage_data: tuple[float, dict]):
        """
        Verify behavior coverage meets >80% target.

        Per AGENTS.md ## Behavior Metrics & Health:
        | Metric | Target |
        | Coverage Rate | >80% of tasks covered |
        """
        coverage_rate, details = coverage_data

        # Build detailed failure message
        if coverage_rate < COVERAGE_TARGET:
            uncovered_list = "\n".join(
                f"  - [{t.source_file}] {t.category_name}"
                for t in details["uncovered_tasks"][:10]  # Show first 10
            )

            msg = (
                f"\n\nBehavior coverage {coverage_rate:.1%} below {COVERAGE_TARGET:.0%} target.\n"
                f"Covered: {details['covered_count']}/{details['total_tasks']} tasks\n"
                f"Behaviors: {details['behaviors_count']}\n\n"
                f"Uncovered tasks (first 10):\n{uncovered_list}\n\n"
                "To fix: Add behaviors in AGENTS.md covering these task categories,\n"
                "or add keyword mappings in Quick Triggers table.\n"
                "See `behavior_curate_behavior_handbook` for process."
            )
            pytest.fail(msg)

    def test_critical_behaviors_exist(self, behaviors: list[Behavior]):
        """Verify critical behaviors required by handbook exist."""
        behavior_names = {b.name for b in behaviors}

        critical_behaviors = [
            "behavior_prefer_mcp_tools",
            "behavior_use_raze_for_logging",
            "behavior_use_breakeramp_for_environments",
            "behavior_prevent_secret_leaks",
            "behavior_update_docs_after_changes",
            "behavior_curate_behavior_handbook",
        ]

        missing = [b for b in critical_behaviors if b not in behavior_names]
        assert not missing, f"Missing critical behaviors: {missing}"

    def test_all_behaviors_have_keywords(self, behaviors: list[Behavior]):
        """
        Warn if behaviors lack keywords for retrieval.

        Behaviors without keywords may have poor retrieval accuracy.
        """
        no_keywords = [b.name for b in behaviors if not b.keywords]

        # Allow some behaviors without keywords (they may be triggered differently)
        if len(no_keywords) > len(behaviors) * 0.3:  # More than 30% without keywords
            pytest.fail(
                f"Too many behaviors without keywords ({len(no_keywords)}/{len(behaviors)}): "
                f"{no_keywords[:5]}... Add keywords in Quick Triggers table."
            )


def test_behavior_naming_convention():
    """
    Verify all behaviors follow `behavior_<verb>_<noun>` naming convention.

    Per AGENTS.md Teacher Validation Checklist:
    | Naming | Does name follow `behavior_<verb>_<noun>` pattern? |
    """
    content = AGENTS_MD.read_text()

    # Find all behavior names
    behavior_pattern = r"`(behavior_\w+)`"
    all_behaviors = set(re.findall(behavior_pattern, content))

    # Exclude template placeholders (examples like behavior_xyz in documentation)
    template_placeholders = {"behavior_xyz", "behavior_name", "behavior_example"}
    all_behaviors = all_behaviors - template_placeholders

    # Check naming convention (should have at least verb_noun structure)
    malformed = []
    for name in all_behaviors:
        # Remove 'behavior_' prefix and check remaining parts
        parts = name.replace("behavior_", "").split("_")
        if len(parts) < 2:
            malformed.append(name)

    assert not malformed, (
        f"Behaviors not following `behavior_<verb>_<noun>` convention: {malformed}"
    )


def test_quick_triggers_have_roles():
    """
    Verify Quick Triggers table entries have role assignments.

    Per AGENTS.md, each trigger should specify Student/Teacher/Strategist role.
    """
    content = AGENTS_MD.read_text()

    # Find Quick Triggers table
    triggers_section = re.search(
        r"## 🎯 Quick Triggers.*?\n\n(.*?)\n\n---",
        content,
        re.DOTALL
    )

    assert triggers_section, "Quick Triggers section not found in AGENTS.md"

    table_content = triggers_section.group(1)
    table_lines = [
        line for line in table_content.split("\n")
        if line.strip().startswith("|") and "---" not in line
    ][1:]  # Skip header row

    missing_roles = []
    for line in table_lines:
        if not any(role in line for role in ["📖 Student", "🎓 Teacher", "🧠"]):
            # Extract first column for error message
            parts = line.split("|")
            if len(parts) >= 2:
                missing_roles.append(parts[1].strip()[:50])

    assert not missing_roles, (
        f"Quick Trigger entries missing role assignment: {missing_roles[:5]}"
    )
