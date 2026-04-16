"""Source Extractor for Knowledge Packs.

Parses registered sources (AGENTS.md, behavior store, playbooks) into
structured fragments that feed into pack generation.

Implements T1.2.2 (AMPREALIZE-299) of the Knowledge Pack Foundations epic.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fragment dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DoctrineFragment:
    """A fragment extracted from a canonical doctrine source (e.g. AGENTS.md)."""

    fragment_id: str
    source_ref: str
    section_heading: str
    content: str
    scope: str  # canonical | operational | surface | runtime
    role_applicability: List[str] = field(default_factory=list)
    surface_applicability: List[str] = field(default_factory=list)
    retrieval_keywords: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fragment_id": self.fragment_id,
            "source_ref": self.source_ref,
            "section_heading": self.section_heading,
            "content": self.content,
            "scope": self.scope,
            "role_applicability": self.role_applicability,
            "surface_applicability": self.surface_applicability,
            "retrieval_keywords": self.retrieval_keywords,
        }


@dataclass(frozen=True)
class BehaviorFragment:
    """A fragment extracted from the BehaviorService store."""

    fragment_id: str
    source_ref: str
    behavior_name: str
    description: str
    instruction: str
    trigger_keywords: List[str] = field(default_factory=list)
    role_focus: str = "ENGINEER"
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fragment_id": self.fragment_id,
            "source_ref": self.source_ref,
            "behavior_name": self.behavior_name,
            "description": self.description,
            "instruction": self.instruction,
            "trigger_keywords": self.trigger_keywords,
            "role_focus": self.role_focus,
            "tags": self.tags,
        }


@dataclass(frozen=True)
class PlaybookFragment:
    """A fragment extracted from an operational playbook document."""

    fragment_id: str
    source_ref: str
    section_heading: str
    content: str
    scope: str
    role_applicability: List[str] = field(default_factory=list)
    surface_applicability: List[str] = field(default_factory=list)
    retrieval_keywords: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fragment_id": self.fragment_id,
            "source_ref": self.source_ref,
            "section_heading": self.section_heading,
            "content": self.content,
            "scope": self.scope,
            "role_applicability": self.role_applicability,
            "surface_applicability": self.surface_applicability,
            "retrieval_keywords": self.retrieval_keywords,
        }


@dataclass
class ExtractionResult:
    """Aggregated result of running all extractors."""

    doctrine_fragments: List[DoctrineFragment] = field(default_factory=list)
    behavior_fragments: List[BehaviorFragment] = field(default_factory=list)
    playbook_fragments: List[PlaybookFragment] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def total_fragments(self) -> int:
        return (
            len(self.doctrine_fragments)
            + len(self.behavior_fragments)
            + len(self.playbook_fragments)
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "doctrine_fragments": [f.to_dict() for f in self.doctrine_fragments],
            "behavior_fragments": [f.to_dict() for f in self.behavior_fragments],
            "playbook_fragments": [f.to_dict() for f in self.playbook_fragments],
            "errors": self.errors,
            "total_fragments": self.total_fragments,
        }


# ---------------------------------------------------------------------------
# Keyword utilities
# ---------------------------------------------------------------------------

_STOPWORDS: Set[str] = {
    "when", "the", "a", "an", "or", "and", "for", "to", "in", "on",
    "with", "is", "are", "any", "of", "by", "at", "be", "as", "it",
    "this", "that", "from", "not", "all", "if", "may", "can",
}


def _extract_keywords(text: str, *, limit: int = 15) -> List[str]:
    """Extract significant words from text, filtering stopwords."""
    words = re.findall(r"\b\w+\b", text.lower())
    seen: Set[str] = set()
    keywords: List[str] = []
    for w in words:
        if len(w) > 3 and w not in _STOPWORDS and w not in seen:
            seen.add(w)
            keywords.append(w)
            if len(keywords) >= limit:
                break
    return keywords


def _stable_fragment_id(source_ref: str, heading: str) -> str:
    """Produce a deterministic fragment ID from source ref and heading."""
    raw = f"{source_ref}::{heading}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:12]
    slug = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")[:40]
    return f"{slug}-{digest}"


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

# Behavior block regex — matches ### `behavior_name` ... until next ### or ---
_BEHAVIOR_RE = re.compile(
    r"### `(behavior_\w+)`\s*\n"
    r"- \*\*When\*\*:\s*(.+?)\n"
    r"- \*\*Steps\*\*:\s*\n"
    r"((?:\s+\d+\.\s+.+?\n)+)",
    re.MULTILINE,
)

# Top-level ## section heading
_H2_RE = re.compile(r"^## (.+)$", re.MULTILINE)

# Role keywords for inferring applicability
_ROLE_MAP: Dict[str, List[str]] = {
    "Student": ["student", "routine", "execution", "consume"],
    "Teacher": ["teacher", "example", "documentation", "validate", "review"],
    "Strategist": ["strategist", "metacognitive", "pattern", "propose", "curate"],
}

# Surface keywords
_SURFACE_MAP: Dict[str, List[str]] = {
    "vscode": ["vscode", "extension", "ide", "copilot chat"],
    "cli": ["cli", "command", "terminal", "argparse"],
    "mcp": ["mcp", "tool", "server"],
    "web": ["web", "dashboard", "console"],
}


def _infer_roles(text: str) -> List[str]:
    lower = text.lower()
    return [role for role, kws in _ROLE_MAP.items() if any(k in lower for k in kws)]


def _infer_surfaces(text: str) -> List[str]:
    lower = text.lower()
    return [surf for surf, kws in _SURFACE_MAP.items() if any(k in lower for k in kws)]


# ---------------------------------------------------------------------------
# SourceExtractor
# ---------------------------------------------------------------------------


class SourceExtractor:
    """Extracts structured fragments from registered knowledge pack sources."""

    def extract_from_agents_md(self, path: Path) -> List[DoctrineFragment]:
        """Parse AGENTS.md into doctrine fragments (one per ## section)."""
        if not path.is_file():
            raise FileNotFoundError(f"AGENTS.md not found: {path}")

        content = path.read_text()
        fragments: List[DoctrineFragment] = []

        # Split into ## sections
        headings = list(_H2_RE.finditer(content))
        for i, match in enumerate(headings):
            heading = match.group(1).strip()
            start = match.end()
            end = headings[i + 1].start() if i + 1 < len(headings) else len(content)
            section_text = content[start:end].strip()

            if not section_text:
                continue

            fragment_id = _stable_fragment_id(str(path), heading)
            fragments.append(
                DoctrineFragment(
                    fragment_id=fragment_id,
                    source_ref=str(path),
                    section_heading=heading,
                    content=section_text,
                    scope="canonical",
                    role_applicability=_infer_roles(section_text),
                    surface_applicability=_infer_surfaces(section_text),
                    retrieval_keywords=_extract_keywords(f"{heading} {section_text}"),
                )
            )

        logger.info("Extracted %d doctrine fragments from %s", len(fragments), path)
        return fragments

    def extract_behaviors_from_agents_md(
        self, path: Path
    ) -> List[BehaviorFragment]:
        """Parse behavior definitions from AGENTS.md into behavior fragments.

        Uses the same regex pattern as scripts/seed_behaviors_from_agents_md.py.
        """
        if not path.is_file():
            raise FileNotFoundError(f"AGENTS.md not found: {path}")

        content = path.read_text()
        fragments: List[BehaviorFragment] = []

        for match in _BEHAVIOR_RE.finditer(content):
            name = match.group(1)
            when_clause = match.group(2).strip()
            steps_raw = match.group(3)

            steps: List[str] = []
            for step_match in re.finditer(
                r"\d+\.\s+(.+?)(?=\n\s+\d+\.|\n\n|\Z)", steps_raw, re.DOTALL
            ):
                step_text = re.sub(r"\s+", " ", step_match.group(1).strip())
                steps.append(step_text)

            instruction = "Steps:\n" + "\n".join(
                f"{i + 1}. {s}" for i, s in enumerate(steps)
            )

            # Keywords from name parts + when clause
            name_parts = name.replace("behavior_", "").split("_")
            kws = [p for p in name_parts if len(p) > 2]
            kws.extend(_extract_keywords(when_clause, limit=10))
            # deduplicate preserving order
            seen: Set[str] = set()
            unique_kws: List[str] = []
            for k in kws:
                if k not in seen:
                    seen.add(k)
                    unique_kws.append(k)

            fragment_id = _stable_fragment_id(str(path), name)
            fragments.append(
                BehaviorFragment(
                    fragment_id=fragment_id,
                    source_ref=str(path),
                    behavior_name=name,
                    description=f"Trigger: {when_clause}",
                    instruction=instruction,
                    trigger_keywords=unique_kws[:15],
                    role_focus=_infer_behavior_role(name),
                    tags=_infer_behavior_tags(name),
                )
            )

        logger.info(
            "Extracted %d behavior fragments from %s", len(fragments), path
        )
        return fragments

    def extract_from_behavior_service(
        self, behaviors: List[Dict[str, Any]]
    ) -> List[BehaviorFragment]:
        """Convert BehaviorService records to fragments.

        Accepts pre-fetched behavior dicts (from ``service.list_behaviors()``).
        This avoids a hard dependency on BehaviorService at import time.
        """
        fragments: List[BehaviorFragment] = []
        for entry in behaviors:
            b = entry.get("behavior", entry)
            name = b.get("name", "")
            fragment_id = _stable_fragment_id("behavior-service", name)
            fragments.append(
                BehaviorFragment(
                    fragment_id=fragment_id,
                    source_ref="behavior-service",
                    behavior_name=name,
                    description=b.get("description", ""),
                    instruction=b.get("instruction", ""),
                    trigger_keywords=b.get("trigger_keywords", []),
                    role_focus=b.get("role_focus", "ENGINEER"),
                    tags=b.get("tags", []),
                )
            )
        logger.info(
            "Extracted %d behavior fragments from BehaviorService", len(fragments)
        )
        return fragments

    def extract_from_playbook(
        self, path: Path, scope: str = "operational"
    ) -> List[PlaybookFragment]:
        """Parse a markdown playbook/guide into playbook fragments."""
        if not path.is_file():
            raise FileNotFoundError(f"Playbook not found: {path}")

        content = path.read_text()
        fragments: List[PlaybookFragment] = []

        headings = list(_H2_RE.finditer(content))
        for i, match in enumerate(headings):
            heading = match.group(1).strip()
            start = match.end()
            end = headings[i + 1].start() if i + 1 < len(headings) else len(content)
            section_text = content[start:end].strip()

            if not section_text:
                continue

            fragment_id = _stable_fragment_id(str(path), heading)
            fragments.append(
                PlaybookFragment(
                    fragment_id=fragment_id,
                    source_ref=str(path),
                    section_heading=heading,
                    content=section_text,
                    scope=scope,
                    role_applicability=_infer_roles(section_text),
                    surface_applicability=_infer_surfaces(section_text),
                    retrieval_keywords=_extract_keywords(f"{heading} {section_text}"),
                )
            )

        logger.info(
            "Extracted %d playbook fragments from %s", len(fragments), path
        )
        return fragments

    def extract_all(
        self, sources: List[Any]
    ) -> ExtractionResult:
        """Orchestrate extraction from a list of source records.

        Accepts both ``SourceRecord`` objects (from ``SourceRegistryService``)
        and plain dicts with ``source_type``, ``ref``, and ``scope`` keys.
        """
        result = ExtractionResult()

        for src in sources:
            # Normalise SourceRecord → dict so .get() works uniformly
            if hasattr(src, "to_dict"):
                src = src.to_dict()
            source_type = src.get("source_type", "")
            ref = src.get("ref", "")
            scope = src.get("scope", "canonical")

            try:
                if source_type == "file":
                    path = Path(ref)
                    if not path.is_file():
                        result.errors.append(f"File not found: {ref}")
                        continue

                    name_lower = path.name.lower()
                    if name_lower == "agents.md":
                        result.doctrine_fragments.extend(
                            self.extract_from_agents_md(path)
                        )
                        result.behavior_fragments.extend(
                            self.extract_behaviors_from_agents_md(path)
                        )
                    elif name_lower.endswith(".md"):
                        result.playbook_fragments.extend(
                            self.extract_from_playbook(path, scope=scope)
                        )
                elif source_type == "service":
                    # Service sources are handled externally
                    logger.debug(
                        "Skipping service source %s (requires external fetch)", ref
                    )
            except Exception as exc:
                msg = f"Error extracting {ref}: {exc}"
                logger.warning(msg)
                result.errors.append(msg)

        logger.info(
            "Extraction complete: %d total fragments, %d errors",
            result.total_fragments,
            len(result.errors),
        )
        return result


# ---------------------------------------------------------------------------
# Helper functions (used by extract_behaviors_from_agents_md)
# ---------------------------------------------------------------------------


def _infer_behavior_role(name: str) -> str:
    """Determine primary role focus from behavior name."""
    if any(x in name for x in ("security", "secret", "credential", "auth", "cors")):
        return "SECURITY"
    if any(x in name for x in ("doc", "readme", "update_docs")):
        return "COPYWRITING"
    if any(x in name for x in ("financial", "budget", "roi")):
        return "FINANCE"
    if any(x in name for x in ("accessibility", "wcag")):
        return "ACCESSIBILITY"
    if any(x in name for x in ("compliance", "audit")):
        return "COMPLIANCE"
    if any(x in name for x in ("cicd", "deploy", "pipeline")):
        return "DEVOPS"
    return "ENGINEER"


def _infer_behavior_tags(name: str) -> List[str]:
    """Extract category tags from behavior name."""
    tags = ["handbook", "agents-md"]
    tag_map = {
        "observability": ("logging", "raze", "telemetry", "metrics"),
        "security": ("secret", "credential", "security", "auth", "cors"),
        "storage": ("storage", "database", "postgres", "migration"),
        "integration": ("cli", "api", "mcp", "service"),
        "documentation": ("doc", "update", "readme"),
        "quality": ("test", "validate", "compliance"),
        "infrastructure": ("environment", "breakeramp", "container", "docker"),
        "devops": ("git", "branch", "merge", "cicd"),
        "configuration": ("config", "externalize", "setting"),
    }
    for tag, keywords in tag_map.items():
        if any(k in name for k in keywords):
            tags.append(tag)
    return tags
