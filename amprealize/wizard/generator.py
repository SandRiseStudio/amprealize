"""Config file generator for the wizard."""

from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from amprealize.bootstrap.profile import WorkspaceProfile
from amprealize.bootstrap.service import BootstrapService
from amprealize.wizard.analyzer import AnalysisResult

logger = logging.getLogger(__name__)


class ConfigGenerator:
    """Generates Amprealize configuration files from an AnalysisResult."""

    def __init__(
        self,
        *,
        bootstrap_service: Optional[BootstrapService] = None,
    ) -> None:
        self._bootstrap = bootstrap_service or BootstrapService()

    # -- public API -----------------------------------------------------------

    def generate(
        self,
        workspace: Path,
        analysis: AnalysisResult,
        *,
        project_name: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, str]:
        """Generate all config files and return a map of path → content.

        Args:
            workspace: Project root directory.
            analysis: The LLM analysis result.
            project_name: Override project name (default: directory name).
            dry_run: If True, return content without writing to disk.

        Returns:
            Dict mapping relative file path to generated content.
        """
        name = project_name or workspace.name
        profile = self._resolve_profile(analysis.suggested_profile)

        files: Dict[str, str] = {}

        # 1. .amprealize/config.yaml
        config_content = self._render_config_yaml(name, profile, analysis)
        files[".amprealize/config.yaml"] = config_content

        # 2. AGENTS.md
        agents_content = self._render_agents_md(profile, analysis)
        files["AGENTS.md"] = agents_content

        # 3. .vscode/mcp.json
        mcp_content = self._render_mcp_json()
        files[".vscode/mcp.json"] = mcp_content

        # 4. .amprealize/wizard-report.md
        report_content = self._render_wizard_report(name, analysis)
        files[".amprealize/wizard-report.md"] = report_content

        if not dry_run:
            self._write_files(workspace, files)

        return files

    # -- renderers ------------------------------------------------------------

    def _render_config_yaml(
        self,
        project_name: str,
        profile: WorkspaceProfile,
        analysis: AnalysisResult,
    ) -> str:
        """Render .amprealize/config.yaml."""
        modules = analysis.suggested_modules or {
            "goals": True,
            "agents": True,
            "behaviors": True,
        }

        storage = analysis.storage_recommendation or "sqlite"
        deployment = analysis.deployment_recommendation or "local"

        config: Dict[str, Any] = {
            "version": 1,
            "project": {
                "name": project_name,
                "workspace_profile": profile.value,
            },
            "server": {
                "host": "0.0.0.0",
                "port": 8765,
            },
            "storage": {
                "backend": storage,
            },
            "auth": {
                "mode": "local",
            },
            "mcp": {
                "transport": "stdio",
            },
            "logging": {
                "level": "INFO",
                "format": "json",
            },
            "modules": {k: bool(v) for k, v in modules.items()},
            "deployment": {
                "mode": deployment,
            },
        }

        if storage == "sqlite":
            config["storage"]["sqlite"] = {"path": ".amprealize/data/amprealize.db"}
        elif storage == "postgres":
            config["storage"]["postgres"] = {
                "dsn": "postgresql://user:password@localhost:5432/amprealize"
            }

        return yaml.dump(config, default_flow_style=False, sort_keys=False)

    def _render_agents_md(
        self,
        profile: WorkspaceProfile,
        analysis: AnalysisResult,
    ) -> str:
        """Render AGENTS.md using the bootstrap service primer template."""
        template = self._bootstrap.get_primer_template(profile)
        if template:
            return template

        # Fallback: generate a minimal AGENTS.md
        tech = analysis.tech_stack
        languages = ", ".join(tech.get("languages", ["unknown"]))
        frameworks = ", ".join(tech.get("frameworks", []))

        return (
            f"# AGENTS.md\n\n"
            f"## Project Overview\n\n"
            f"- **Profile**: {profile.value}\n"
            f"- **Languages**: {languages}\n"
            f"- **Frameworks**: {frameworks}\n\n"
            f"## Coding Guidelines\n\n"
            f"Follow the conventions established in this project.\n"
        )

    def _render_mcp_json(self) -> str:
        """Render .vscode/mcp.json for IDE integration."""
        config = {
            "servers": {
                "amprealize": {
                    "type": "stdio",
                    "command": "amprealize",
                    "args": ["mcp", "serve"],
                }
            }
        }
        return json.dumps(config, indent=2) + "\n"

    def _render_wizard_report(
        self,
        project_name: str,
        analysis: AnalysisResult,
    ) -> str:
        """Render .amprealize/wizard-report.md."""
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        tech = analysis.tech_stack
        arch = analysis.architecture

        lines = [
            "# Wizard Analysis Report",
            "",
            f"**Project**: {project_name}",
            f"**Generated**: {now}",
            f"**Model**: {analysis.model_used}",
            "",
            "## Tech Stack",
            "",
            f"- **Languages**: {', '.join(tech.get('languages', []))}",
            f"- **Frameworks**: {', '.join(tech.get('frameworks', []))}",
            f"- **Build tools**: {', '.join(tech.get('build_tools', []))}",
            f"- **Package managers**: {', '.join(tech.get('package_managers', []))}",
            "",
            "## Architecture",
            "",
            f"- **Pattern**: {arch.get('pattern', 'unknown')}",
            f"- **Description**: {arch.get('description', '')}",
            "",
            "## Profile Selection",
            "",
            f"- **Profile**: {analysis.suggested_profile}",
            f"- **Rationale**: {analysis.profile_rationale}",
            "",
            "## Suggested Modules",
            "",
        ]

        for mod, enabled in analysis.suggested_modules.items():
            status = "✅" if enabled else "❌"
            lines.append(f"- {status} {mod}")

        if analysis.module_rationale:
            lines.extend(["", f"*{analysis.module_rationale}*"])

        if analysis.suggested_behaviors:
            lines.extend(["", "## Suggested Behaviors", ""])
            for beh in analysis.suggested_behaviors:
                lines.append(f"### {beh.get('name', 'Untitled')}")
                lines.append("")
                lines.append(f"- **Description**: {beh.get('description', '')}")
                lines.append(f"- **Trigger**: {beh.get('trigger', 'on_commit')}")
                lines.append("")

        lines.extend([
            "## Deployment",
            "",
            f"- **Mode**: {analysis.deployment_recommendation}",
            f"- **Storage**: {analysis.storage_recommendation}",
            "",
            "## Usage",
            "",
            f"- Input tokens: {analysis.input_tokens:,}",
            f"- Output tokens: {analysis.output_tokens:,}",
            f"- Cost: ${analysis.cost_usd:.4f}",
            f"- Latency: {analysis.latency_ms:.0f}ms",
            "",
        ])

        if analysis.notes:
            lines.extend(["## Notes", "", analysis.notes, ""])

        return "\n".join(lines)

    # -- file I/O -------------------------------------------------------------

    @staticmethod
    def _resolve_profile(name: str) -> WorkspaceProfile:
        """Map a profile name string to the enum."""
        for p in WorkspaceProfile:
            if p.value == name:
                return p
        return WorkspaceProfile.SOLO_DEV

    @staticmethod
    def _write_files(workspace: Path, files: Dict[str, str]) -> None:
        """Write generated files to disk."""
        for rel_path, content in files.items():
            full = workspace / rel_path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content)
            logger.info("Wrote %s", full)
