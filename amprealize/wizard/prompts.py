"""Prompt templates for the wizard's LLM-powered project analysis."""

from __future__ import annotations

SYSTEM_PROMPT = """\
You are the Amprealize Wizard — an expert developer-tools analyst.
You will receive a snapshot of a software project (file listing, key config files,
README excerpts) and must produce a structured JSON analysis.

Respond with ONLY valid JSON — no markdown fences, no commentary.

Required JSON schema:

{
  "tech_stack": {
    "languages": ["python", "typescript", ...],
    "frameworks": ["fastapi", "react", ...],
    "build_tools": ["vite", "poetry", ...],
    "package_managers": ["pip", "npm", ...]
  },
  "architecture": {
    "pattern": "monolith | monorepo | microservices | library | cli-tool | unknown",
    "description": "One-sentence summary of the architecture."
  },
  "team_signals": {
    "estimated_team_size": "solo | small (2-5) | medium (6-15) | large (16+)",
    "has_ci": true,
    "has_code_review": true,
    "has_linting": true,
    "has_tests": true
  },
  "suggested_profile": "solo-dev | amprealize-platform | team-collab | extension-dev | api-backend | compliance-sensitive",
  "profile_rationale": "Why this profile fits.",
  "suggested_modules": {
    "goals": true,
    "agents": true,
    "behaviors": true,
    "compliance": false,
    "collaboration": false
  },
  "module_rationale": "Why these modules were chosen.",
  "suggested_behaviors": [
    {
      "name": "Descriptive behavior name",
      "description": "What this behavior enforces or tracks.",
      "trigger": "on_commit | on_pr | on_deploy | scheduled"
    }
  ],
  "deployment_recommendation": "local | cloud | hybrid",
  "storage_recommendation": "sqlite | postgres",
  "notes": "Any additional observations."
}
"""

USER_PROMPT_TEMPLATE = """\
Analyse this project and produce your JSON assessment.

## Directory Listing (top 3 levels)

{directory_listing}

## Key Files

{key_files_content}

## Pre-detection Signals

The heuristic detector found these signals:
{signals_summary}

Suggested profile (heuristic): {heuristic_profile} (confidence: {heuristic_confidence:.0%})
"""


def build_user_prompt(
    *,
    directory_listing: str,
    key_files_content: str,
    signals_summary: str,
    heuristic_profile: str,
    heuristic_confidence: float,
) -> str:
    """Build the user prompt from gathered project data."""
    return USER_PROMPT_TEMPLATE.format(
        directory_listing=directory_listing,
        key_files_content=key_files_content,
        signals_summary=signals_summary,
        heuristic_profile=heuristic_profile,
        heuristic_confidence=heuristic_confidence,
    )
