"""
Agent Playbook Loader - Dynamic agent registration from markdown playbooks.

This module provides dynamic loading of agent personas from markdown playbook files,
eliminating the need for hardcoded agent definitions.

Usage:
    from amprealize.services.agent_loader import AgentPlaybookLoader

    loader = AgentPlaybookLoader()
    personas = loader.load_all()
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Default agents directory relative to project root
DEFAULT_AGENTS_DIR = "amprealize/agents/playbooks"


@dataclass
class ParsedPlaybook:
    """Parsed content from an agent playbook markdown file."""

    agent_id: str
    display_name: str
    mission: str
    role_alignment: str
    capabilities: List[str] = field(default_factory=list)
    default_behaviors: List[str] = field(default_factory=list)
    playbook_path: str = ""
    raw_sections: Dict[str, str] = field(default_factory=dict)


class AgentPlaybookLoader:
    """
    Loads and parses agent playbook markdown files to create AgentPersona objects.

    The loader scans a directory for AGENT_*.md files and extracts:
    - agent_id: Derived from filename (AGENT_ENGINEERING.md → engineering)
    - display_name: Parsed from H1 title
    - mission: Content under ## Mission
    - capabilities: Derived from checklist items and section content
    - default_behaviors: Extracted behavior_* references from text
    - role_alignment: Inferred from content patterns or explicit frontmatter
    """

    # Role alignment patterns for inference
    ROLE_PATTERNS = {
        "STRATEGIST": ["strategic", "architect", "design", "plan", "vision", "research"],
        "TEACHER": ["review", "validate", "ensure", "check", "audit", "compliance"],
        "STUDENT": ["execute", "implement", "build", "develop", "create", "code"],
        "MULTI_ROLE": ["orchestrat", "coordinat", "manag", "facilitat"],
    }

    def __init__(
        self,
        agents_dir: Optional[Path] = None,
        project_root: Optional[Path] = None,
    ):
        """
        Initialize the loader.

        Args:
            agents_dir: Explicit path to agents directory
            project_root: Project root to resolve relative agents_dir
        """
        if agents_dir:
            self.agents_dir = Path(agents_dir)
        elif project_root:
            self.agents_dir = Path(project_root) / DEFAULT_AGENTS_DIR
        else:
            # Auto-detect project root by finding amprealize package
            self.agents_dir = self._find_agents_dir()

    def _find_agents_dir(self) -> Path:
        """Auto-detect agents directory by traversing up from this file."""
        current = Path(__file__).resolve()
        # Go up: services/ -> amprealize/ -> project_root/
        project_root = current.parent.parent.parent
        agents_path = project_root / DEFAULT_AGENTS_DIR
        if agents_path.exists():
            return agents_path
        # Fallback to current working directory
        return Path.cwd() / DEFAULT_AGENTS_DIR

    def discover_playbooks(self) -> List[Path]:
        """Find all AGENT_*.md files in the agents directory."""
        if not self.agents_dir.exists():
            logger.warning(f"Agents directory not found: {self.agents_dir}")
            return []

        playbooks = sorted(self.agents_dir.glob("AGENT_*.md"))
        logger.info(f"Discovered {len(playbooks)} agent playbooks in {self.agents_dir}")
        return playbooks

    def parse_playbook(self, path: Path) -> Optional[ParsedPlaybook]:
        """
        Parse a single playbook file.

        Args:
            path: Path to the AGENT_*.md file

        Returns:
            ParsedPlaybook or None if parsing fails
        """
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to read playbook {path}: {e}")
            return None

        # Extract agent_id from filename
        # AGENT_ENGINEERING.md → engineering
        # AGENT_DATA_SCIENCE.md → data_science
        filename = path.stem  # AGENT_ENGINEERING
        agent_id = filename.replace("AGENT_", "").lower()

        # Parse sections
        sections = self._parse_sections(content)

        # Extract display name from H1 title
        display_name = self._extract_display_name(content, agent_id)

        # Extract mission
        mission = sections.get("Mission", "").strip()

        # Extract behaviors from entire content
        behaviors = self._extract_behaviors(content)

        # Extract capabilities from checklist and content
        capabilities = self._extract_capabilities(content, sections)

        # Infer role alignment
        role_alignment = self._infer_role_alignment(content, mission)

        return ParsedPlaybook(
            agent_id=agent_id,
            display_name=display_name,
            mission=mission,
            role_alignment=role_alignment,
            capabilities=capabilities,
            default_behaviors=behaviors,
            playbook_path=str(path),
            raw_sections=sections,
        )

    def _parse_sections(self, content: str) -> Dict[str, str]:
        """Parse markdown into sections by H2 headers."""
        sections: Dict[str, str] = {}
        current_section = ""
        current_content: List[str] = []

        for line in content.split("\n"):
            if line.startswith("## "):
                # Save previous section
                if current_section:
                    sections[current_section] = "\n".join(current_content).strip()
                # Start new section
                current_section = line[3:].strip()
                current_content = []
            elif current_section:
                current_content.append(line)

        # Save last section
        if current_section:
            sections[current_section] = "\n".join(current_content).strip()

        return sections

    def _extract_display_name(self, content: str, agent_id: str) -> str:
        """Extract display name from H1 title or derive from agent_id."""
        # Look for H1 title
        match = re.search(r"^#\s+(.+?)(?:\s+Playbook)?\s*$", content, re.MULTILINE)
        if match:
            title = match.group(1).strip()
            # Clean up common suffixes
            title = re.sub(r"\s+Agent$", "", title)
            return f"{title} Agent"

        # Derive from agent_id
        # data_science → Data Science Agent
        parts = agent_id.replace("_", " ").title()
        return f"{parts} Agent"

    def _extract_behaviors(self, content: str) -> List[str]:
        """Extract all behavior_* references from content."""
        # Find all behavior references
        pattern = r"`?(behavior_[a-z_]+)`?"
        matches = re.findall(pattern, content, re.IGNORECASE)

        # Deduplicate while preserving order
        seen: Set[str] = set()
        behaviors: List[str] = []
        for behavior in matches:
            behavior_lower = behavior.lower()
            if behavior_lower not in seen:
                seen.add(behavior_lower)
                behaviors.append(behavior_lower)

        return behaviors

    def _extract_capabilities(
        self, content: str, sections: Dict[str, str]
    ) -> List[str]:
        """Extract capabilities from checklist items and section headers."""
        capabilities: Set[str] = set()

        # Extract from Review Checklist section
        checklist = sections.get("Review Checklist", "")
        # Look for **Bold Text** patterns which typically indicate capability areas
        bold_items = re.findall(r"\*\*([^*]+)\*\*", checklist)
        for item in bold_items:
            # Clean and normalize
            cap = item.strip().lower().replace(" ", "_").replace("&", "and")
            # Remove common suffixes
            cap = re.sub(r"[–-].*$", "", cap).strip("_")
            if cap and len(cap) < 50:  # Reasonable length
                capabilities.add(cap)

        # Extract from Decision Rubric
        rubric = sections.get("Decision Rubric", "") or sections.get("Evaluation Rubric", "")
        rubric_caps = re.findall(r"\|\s*\*?\*?([A-Z][a-z]+(?:\s+[A-Z]?[a-z]+)*)", rubric)
        for cap in rubric_caps:
            cap_clean = cap.strip().lower().replace(" ", "_")
            if cap_clean and len(cap_clean) < 30:
                capabilities.add(cap_clean)

        return sorted(capabilities)

    def _infer_role_alignment(self, content: str, mission: str) -> str:
        """Infer role alignment from content patterns."""
        content_lower = content.lower()
        mission_lower = mission.lower()

        scores: Dict[str, int] = {role: 0 for role in self.ROLE_PATTERNS}

        for role, patterns in self.ROLE_PATTERNS.items():
            for pattern in patterns:
                # Weight mission text higher
                if pattern in mission_lower:
                    scores[role] += 3
                # Count occurrences in full content
                scores[role] += content_lower.count(pattern)

        # Return highest scoring role
        best_role = max(scores, key=lambda k: scores[k])
        return best_role if scores[best_role] > 0 else "TEACHER"  # Default

    def load_all(self) -> List[ParsedPlaybook]:
        """
        Load and parse all playbooks from the agents directory.

        Returns:
            List of ParsedPlaybook objects
        """
        playbooks: List[ParsedPlaybook] = []

        for path in self.discover_playbooks():
            parsed = self.parse_playbook(path)
            if parsed:
                playbooks.append(parsed)
                logger.debug(
                    f"Loaded agent: {parsed.agent_id} "
                    f"(role={parsed.role_alignment}, "
                    f"behaviors={len(parsed.default_behaviors)}, "
                    f"capabilities={len(parsed.capabilities)})"
                )

        logger.info(f"Loaded {len(playbooks)} agent playbooks")
        return playbooks

    def to_persona_defs(self) -> List[Dict[str, Any]]:
        """
        Load playbooks and convert to AgentPersona-compatible dicts.

        Returns format compatible with _DEFAULT_PERSONA_DEFS in
        agent_orchestrator_service.py
        """
        playbooks = self.load_all()
        return [
            {
                "agent_id": p.agent_id,
                "display_name": p.display_name,
                "role_alignment": p.role_alignment,
                "default_behaviors": p.default_behaviors,
                "playbook_refs": [Path(p.playbook_path).name],
                "capabilities": p.capabilities,
            }
            for p in playbooks
        ]


# Convenience function for quick loading
def load_agent_personas(
    agents_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """
    Load agent personas from playbook files.

    Args:
        agents_dir: Optional path to agents directory

    Returns:
        List of persona definition dicts
    """
    loader = AgentPlaybookLoader(agents_dir=agents_dir)
    return loader.to_persona_defs()


if __name__ == "__main__":
    # Simple test when run directly
    import json

    logging.basicConfig(level=logging.DEBUG)

    loader = AgentPlaybookLoader()
    personas = loader.to_persona_defs()

    print(f"\nLoaded {len(personas)} agents:\n")
    for p in personas:
        print(f"  {p['agent_id']}: {p['display_name']}")
        print(f"    Role: {p['role_alignment']}")
        print(f"    Behaviors: {', '.join(p['default_behaviors'][:3])}...")
        print(f"    Capabilities: {', '.join(p['capabilities'][:3])}...")
        print()

    # Full JSON output
    print("\n--- Full JSON ---")
    print(json.dumps(personas, indent=2))
