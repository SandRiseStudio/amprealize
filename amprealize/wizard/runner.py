"""WizardRunner — main orchestration for the amprealize wizard."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from amprealize.bootstrap.profile import WorkspaceProfile
from amprealize.wizard.analyzer import AnalysisResult, ProjectAnalyzer
from amprealize.wizard.display import WizardDisplay
from amprealize.wizard.generator import ConfigGenerator

logger = logging.getLogger(__name__)

# Default model for wizard analysis
DEFAULT_MODEL = "claude-sonnet-4-5"

# Known provider env vars — checked in order to find an API key
_API_KEY_ENV_VARS = [
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "TOGETHER_API_KEY",
    "GROQ_API_KEY",
    "FIREWORKS_API_KEY",
    "AMPREALIZE_LLM_API_KEY",
]


class WizardRunner:
    """Orchestrates the full wizard flow.

    Flow:
        1. Detect  — check for API key, heuristic workspace detection
        2. Analyse — LLM-powered deep analysis
        3. Propose — display proposed configuration
        4. Confirm — interactive Y/n (skip if non-interactive)
        5. Generate — write files (skip if dry-run)
        6. Verify  — check generated files
        7. Summary — display cost, files, next steps
    """

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        dry_run: bool = False,
        non_interactive: bool = False,
        skip_login: bool = False,
        profile_override: Optional[str] = None,
        quiet: bool = False,
    ) -> None:
        self.model = model
        self.dry_run = dry_run
        self.non_interactive = non_interactive
        self.skip_login = skip_login
        self.profile_override = profile_override

        self.display = WizardDisplay(quiet=quiet)
        self.analyzer = ProjectAnalyzer(model=model)
        self.generator = ConfigGenerator()

    def run(self, workspace: Optional[Path] = None) -> int:
        """Run the full wizard flow.

        Args:
            workspace: Project root (defaults to cwd).

        Returns:
            Exit code: 0 for success, 1 for error/abort.
        """
        workspace = workspace or Path.cwd()
        if not workspace.is_dir():
            self.display.error(f"Not a directory: {workspace}")
            return 1

        self.display.banner()
        total_steps = 4 if self.dry_run else 5

        # Step 1: API key check + heuristic detection
        self.display.step(1, total_steps, "Detecting workspace signals")

        api_key = self._resolve_api_key()
        if api_key is None and not self.skip_login:
            return self._fallback_to_init()

        detection = self.analyzer.detect_signals(workspace)
        self.display.detection_result(
            profile=detection.profile.value,
            confidence=detection.confidence,
            signals=[
                {
                    "signal_name": s.signal_name,
                    "detected": s.detected,
                    "evidence": s.evidence,
                }
                for s in detection.signals
            ],
        )

        # Apply profile override if provided
        if self.profile_override:
            for p in WorkspaceProfile:
                if p.value == self.profile_override:
                    detection.profile = p
                    self.display.info(f"  Profile overridden to: {p.value}")
                    break

        # Step 2: LLM analysis
        self.display.step(2, total_steps, "Analysing project with AI")

        with self.display.spinner("Analysing project...") as spinner:
            self.display.spinner_task(spinner, "Running LLM analysis...")
            try:
                analysis = self.analyzer.analyse(
                    workspace,
                    api_key=api_key,
                    detection=detection,
                )
            except Exception as exc:
                self.display.error(f"LLM analysis failed: {exc}")
                logger.exception("Wizard LLM analysis failed")
                return 1

        self.display.analysis_result(analysis.raw_response)

        # Step 3: Propose configuration
        self.display.step(3, total_steps, "Proposed configuration")

        files = self.generator.generate(
            workspace, analysis, dry_run=True,
        )

        for path, content in files.items():
            self.display.file_preview(path, content)

        # Confirm (unless non-interactive or dry-run)
        if self.dry_run:
            self.display.info("\n  --dry-run: no files written.")
            self.display.cost_summary(
                analysis.cost_usd,
                {"input": analysis.input_tokens, "output": analysis.output_tokens},
            )
            return 0

        if not self.non_interactive:
            if not self.display.confirm("Write these files?"):
                self.display.info("  Aborted by user.")
                return 1

        # Step 4: Generate files
        self.display.step(4, total_steps, "Writing configuration files")

        written_files = self.generator.generate(workspace, analysis)

        for path in written_files:
            self.display.success(path)

        # Step 5: Summary
        self.display.step(5, total_steps, "Done")
        self.display.cost_summary(
            analysis.cost_usd,
            {"input": analysis.input_tokens, "output": analysis.output_tokens},
        )
        self.display.final_summary(list(written_files.keys()))

        return 0

    # -- helpers --------------------------------------------------------------

    def _resolve_api_key(self) -> Optional[str]:
        """Find an API key from environment or prompt the user."""
        if self.skip_login:
            return "skip"

        # Check known env vars
        for var in _API_KEY_ENV_VARS:
            key = os.environ.get(var)
            if key:
                return key

        # Interactive prompt
        if not self.non_interactive:
            return self.display.prompt_api_key()

        return None

    def _fallback_to_init(self) -> int:
        """Fall back to `amprealize init` when no API key is available."""
        self.display.warning(
            "No API key available. Falling back to heuristic-only mode."
        )
        self.display.info(
            "  Run [bold]amprealize init[/bold] for offline setup, or set an API key and try again.\n"
        )
        return 1
