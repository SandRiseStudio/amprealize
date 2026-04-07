"""Amprealize Work Item Standard (GWS) v1.0 — Single source of truth.

All GWS constants, title patterns, validation helpers, and prompt texts
live here. Other modules import from this file; never duplicate these values.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

# =============================================================================
# Version
# =============================================================================

GWS_VERSION = "1.0"

# =============================================================================
# Hierarchy
# =============================================================================

HIERARCHY = {
    "goal": {
        "description": "Top-level strategic objective",
        "allowed_children": ["feature"],
    },
    "feature": {
        "description": "Deliverable capability under a goal",
        "allowed_children": ["task", "bug"],
    },
    "task": {
        "description": "Atomic unit of work under a feature",
        "allowed_children": [],
    },
    "bug": {
        "description": "Defect or issue to fix under a feature",
        "allowed_children": [],
    },
}

# =============================================================================
# Title patterns — regex per item_type
# =============================================================================

# Goal titles: imperative verb phrase, no prefix numbering
# Good: "Standardize Work Item Creation Across Agents"
# Bad:  "Phase 1: Work Items", "EPIC-001 Standardize..."
_GOAL_PATTERN = re.compile(
    r"""^[A-Z][A-Za-z0-9 :'‘’&/,\-–—()._+#@*~"`→<>\[\]?!;=]{4,120}$"""
)

# Feature titles: imperative verb phrase describing a deliverable
# Good: "Add GWS Title Validation to MCP Handler"
# Bad:  "Sprint-3 Story: validation", "S-042 Add validation"
_FEATURE_PATTERN = re.compile(
    r"""^[A-Z][A-Za-z0-9 :'‘’&/,\-–—()._+#@*~"`→<>\[\]?!;=]{4,120}$"""
)

# Task titles: action-oriented, starts with verb
# Good: "Write unit tests for title regex"
# Bad:  "Task 1 - tests"
_TASK_PATTERN = re.compile(
    r"""^[A-Z][A-Za-z0-9 :'‘’&/,\-–—()._+#@*~"`→<>\[\]?!;=]{2,120}$"""
)

# Bug titles: describe the defect
# Good: "Fix race condition in board column reorder"
# Bad:  "BUG-99 column issue"
_BUG_PATTERN = re.compile(
    r"""^[A-Z][A-Za-z0-9 :'‘’&/,\-–—()._+#@*~"`→<>\[\]?!;=]{4,120}$"""
)

GWS_TITLE_PATTERNS: Dict[str, re.Pattern[str]] = {
    "goal": _GOAL_PATTERN,
    "feature": _FEATURE_PATTERN,
    "task": _TASK_PATTERN,
    "bug": _BUG_PATTERN,
}

# =============================================================================
# Anti-patterns — titles matching these are always rejected
# =============================================================================

_ANTI_PATTERNS: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"^(Phase|Track|Sprint|Milestone)\s*\d", re.IGNORECASE),
     "Do not prefix titles with Phase/Track/Sprint/Milestone numbers. Use labels instead."),
    (re.compile(r"^(EPIC|STORY|TASK|BUG|FEAT|FIX|ISSUE|TICKET)[\s\-:#]+\d", re.IGNORECASE),
     "Do not prefix titles with type-number codes (e.g., EPIC-001). The system tracks IDs automatically."),
    (re.compile(r"^\d+[\s.\-:)]+", re.IGNORECASE),
     "Do not start titles with manual numbering (e.g., '1. Do X'). Order is managed by position."),
    (re.compile(r"^(TODO|WIP|DRAFT|TBD|FIXME)\b", re.IGNORECASE),
     "Do not use TODO/WIP/DRAFT/TBD/FIXME as title prefixes. Use status field instead."),
    (re.compile(r"^[A-Z]\d+(?:[.\-][A-Z]?\d+)*\s*[:\-–—]"),
     "Do not prefix titles with coded-section identifiers (e.g., 'A1:', 'S1.1 —'). Use labels instead."),
    (re.compile(r"^\[.+?\]"),
     "Do not wrap type labels in brackets (e.g., '[Bug]'). Use the item_type field instead."),
]

# =============================================================================
# Validation
# =============================================================================


def validate_title(item_type: str, title: str) -> Optional[str]:
    """Validate a work item title against GWS conventions.

    Returns None if valid, or an error message string if invalid.
    """
    item_type = item_type.lower()

    # Check anti-patterns first
    for pattern, message in _ANTI_PATTERNS:
        if pattern.search(title):
            return f"GWS v{GWS_VERSION} violation: {message}"

    # Check type-specific pattern
    type_pattern = GWS_TITLE_PATTERNS.get(item_type)
    if type_pattern and not type_pattern.match(title):
        return (
            f"GWS v{GWS_VERSION} violation: {item_type.capitalize()} titles must start with "
            f"an uppercase letter and be 5-120 characters of letters, numbers, spaces, "
            f"and common punctuation/symbols."
        )

    return None


# =============================================================================
# Convention text — full version for docs/agents
# =============================================================================

GWS_CONVENTION_TEXT = f"""\
# Amprealize Work Item Standard (GWS) v{GWS_VERSION}

## Hierarchy
- **Goal**: Top-level strategic objective (parent_id=None)
  - **Feature**: Deliverable capability under a goal (parent_id=goal_id)
    - **Task**: Atomic unit of work (parent_id=feature_id)
    - **Bug**: Defect or issue to fix (parent_id=feature_id)

## Naming Rules
1. Titles start with an UPPERCASE letter
2. Use imperative verb phrases: "Add X", "Implement Y", "Fix Z"
3. 5-120 characters, letters/numbers/spaces/basic punctuation
4. Sizing uses **points** (not story_points)
5. Depth levels: goal_only, goal_and_features, full

## Anti-Patterns (Rejected)
- Phase/Track/Sprint/Milestone numbering → use **labels** instead
- Type-number prefixes (EPIC-001, STORY-42) → system assigns IDs
- Manual numbering (1. Do X) → use **position** field
- Status prefixes (TODO, WIP, DRAFT) → use **status** field
- Coded-section prefixes (A1:, S1.1 —, T1.1.1 —) → use **labels** instead
- Bracket-type prefixes ([Bug], [Feature]) → use **item_type** field

## Labels for Phasing
Instead of "Phase 1: …" in titles, add labels:
  labels: ["phase:1", "track:backend"]

## Examples
| Type    | Good ✅                                           | Bad ❌                          |
|---------|----------------------------------------------------|---------------------------------|
| Goal    | Standardize Work Item Creation Across Agents       | Phase 1: Work Items             |
| Feature | Add GWS Title Validation to MCP Handler            | STORY-042 Add validation        |
| Task    | Write unit tests for title regex                   | Task 1 - tests                  |
| Bug     | Fix race condition in board column reorder          | BUG-99 column issue             |
"""

# =============================================================================
# Compact summary — for injection into agent planning prompts (~20 lines)
# =============================================================================

GWS_COMPACT_SUMMARY = f"""\
[GWS v{GWS_VERSION}] Work Item Naming Standard:
- Hierarchy: goal → feature → task/bug
- Titles: uppercase start, imperative verb phrase, 5-120 chars
- Sizing: use "points" (not story_points)
- Depth: goal_only | goal_and_features | full
- NO Phase/Sprint/Track numbering in titles — use labels: ["phase:1"]
- NO type-number prefixes (EPIC-001) — system assigns IDs
- NO manual numbering (1. Do X) — use position field
- NO status prefixes (TODO, WIP) — use status field
- NO coded-section prefixes (A1:, S1.1 —) — use labels: ["section:a1"]
- NO bracket-type prefixes ([Bug]) — use item_type field
Examples:
  goal:    "Standardize Work Item Creation Across Agents"
  feature: "Add GWS Title Validation to MCP Handler"
  task:    "Write unit tests for title regex"
  bug:     "Fix race condition in board column reorder"\
"""
