"""AI-powered project wizard for Amprealize onboarding.

Uses LLMClient to analyse a project's codebase and generate customised
Amprealize configuration (.amprealize/config.yaml, AGENTS.md, etc.).
"""

from amprealize.wizard.analyzer import ProjectAnalyzer
from amprealize.wizard.generator import ConfigGenerator
from amprealize.wizard.runner import WizardRunner

__all__ = [
    "ConfigGenerator",
    "ProjectAnalyzer",
    "WizardRunner",
]
