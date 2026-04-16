"""Rich terminal display helpers for the wizard."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.prompt import Confirm, Prompt
    from rich.table import Table
    from rich.syntax import Syntax

    HAS_RICH = True
except ImportError:  # pragma: no cover
    HAS_RICH = False


class WizardDisplay:
    """Terminal display for wizard output.

    Uses ``rich`` when available, falls back to plain ``print``.
    """

    def __init__(self, *, quiet: bool = False) -> None:
        self.quiet = quiet
        if HAS_RICH and not quiet:
            self._console = Console(stderr=True)
        else:
            self._console = None  # type: ignore[assignment]

    # -- helpers --------------------------------------------------------------

    def _print(self, msg: str) -> None:
        if self.quiet:
            return
        if self._console:
            self._console.print(msg)
        else:
            print(msg, file=sys.stderr)

    # -- public API -----------------------------------------------------------

    def banner(self) -> None:
        """Print the wizard welcome banner."""
        self._print(
            "\n[bold cyan]🧙 Amprealize Wizard[/bold cyan]"
            if HAS_RICH
            else "\n🧙 Amprealize Wizard"
        )
        self._print(
            "[dim]AI-powered project analysis and configuration[/dim]\n"
            if HAS_RICH
            else "AI-powered project analysis and configuration\n"
        )

    def step(self, number: int, total: int, description: str) -> None:
        """Print a numbered step header."""
        self._print(
            f"[bold]Step {number}/{total}:[/bold] {description}"
            if HAS_RICH
            else f"Step {number}/{total}: {description}"
        )

    def success(self, msg: str) -> None:
        self._print(f"[green]  ✅ {msg}[/green]" if HAS_RICH else f"  ✅ {msg}")

    def warning(self, msg: str) -> None:
        self._print(f"[yellow]  ⚠️  {msg}[/yellow]" if HAS_RICH else f"  ⚠️  {msg}")

    def error(self, msg: str) -> None:
        self._print(f"[red]  ❌ {msg}[/red]" if HAS_RICH else f"  ❌ {msg}")

    def info(self, msg: str) -> None:
        self._print(f"  {msg}")

    def spinner(self, description: str) -> Any:
        """Return a context manager that shows a spinner.

        Usage::

            with display.spinner("Analysing project..."):
                do_work()
        """
        if self._console and HAS_RICH:
            return Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=self._console,
                transient=True,
            )
        return _NullSpinner()

    def spinner_task(self, spinner: Any, description: str) -> Any:
        """Add a task to a spinner context."""
        if HAS_RICH and hasattr(spinner, "add_task"):
            return spinner.add_task(description, total=None)
        return None

    def detection_result(
        self,
        profile: str,
        confidence: float,
        signals: List[Dict[str, Any]],
    ) -> None:
        """Display workspace detection results."""
        self._print("\n🔍 Workspace Detection\n")
        self._print(f"  Profile:    {profile}")
        self._print(f"  Confidence: {confidence:.0%}")
        if signals:
            self._print("\n  Signals:")
            for sig in signals:
                marker = "✅" if sig.get("detected") else "  "
                self._print(f"    {marker} {sig.get('signal_name', '?')}: {sig.get('evidence', '')}")

    def analysis_result(self, analysis: Dict[str, Any]) -> None:
        """Display LLM analysis results."""
        self._print("\n🤖 AI Analysis\n")

        tech = analysis.get("tech_stack", {})
        if tech.get("languages"):
            self._print(f"  Languages:  {', '.join(tech['languages'])}")
        if tech.get("frameworks"):
            self._print(f"  Frameworks: {', '.join(tech['frameworks'])}")

        arch = analysis.get("architecture", {})
        if arch.get("pattern"):
            self._print(f"  Architecture: {arch['pattern']}")
        if arch.get("description"):
            self._print(f"  {arch['description']}")

        profile = analysis.get("suggested_profile")
        if profile:
            self._print(f"\n  Suggested profile: [bold]{profile}[/bold]" if HAS_RICH else f"\n  Suggested profile: {profile}")
        rationale = analysis.get("profile_rationale")
        if rationale:
            self._print(f"  Rationale: {rationale}")

    def file_preview(self, path: str, content: str) -> None:
        """Show a preview of a file that will be generated."""
        if self._console and HAS_RICH:
            ext = Path(path).suffix.lstrip(".")
            lang = {"yaml": "yaml", "yml": "yaml", "md": "markdown", "json": "json"}.get(ext, "text")
            self._console.print(Panel(
                Syntax(content, lang, theme="monokai", line_numbers=False),
                title=f"📄 {path}",
                border_style="dim",
            ))
        else:
            self._print(f"\n--- {path} ---")
            self._print(content)
            self._print(f"--- end {path} ---\n")

    def cost_summary(self, total_cost: float, tokens: Dict[str, int]) -> None:
        """Print a cost and token summary."""
        self._print("\n💰 Usage Summary\n")
        self._print(f"  Input tokens:  {tokens.get('input', 0):,}")
        self._print(f"  Output tokens: {tokens.get('output', 0):,}")
        self._print(f"  Total cost:    ${total_cost:.4f}")

    def final_summary(self, files_written: List[str]) -> None:
        """Print the final success summary."""
        self._print(
            "\n[bold green]🎉 Wizard complete![/bold green]\n"
            if HAS_RICH
            else "\n🎉 Wizard complete!\n"
        )
        self._print("  Files created:")
        for f in files_written:
            self.success(f)
        self._print("\n  Next steps:")
        self._print("    1. Review the generated configuration")
        self._print("    2. Run [bold]amprealize serve[/bold] to start the server" if HAS_RICH else "    2. Run `amprealize serve` to start the server")
        self._print("    3. Open .amprealize/wizard-report.md for the full analysis\n")

    def confirm(self, prompt: str, default: bool = True) -> bool:
        """Interactive Y/n confirmation."""
        if HAS_RICH and self._console:
            return Confirm.ask(prompt, default=default, console=self._console)
        answer = input(f"{prompt} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
        if not answer:
            return default
        return answer in ("y", "yes")

    def prompt_api_key(self) -> Optional[str]:
        """Prompt the user for an API key."""
        self._print("\n🔑 No API key found for the LLM provider.")
        self._print("  The wizard requires an API key to analyse your project.")
        self._print("  Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or another provider key.\n")
        if HAS_RICH and self._console:
            key = Prompt.ask(
                "  Enter API key (or press Enter to skip)",
                default="",
                console=self._console,
                password=True,
            )
        else:
            key = input("  Enter API key (or press Enter to skip): ").strip()
        return key if key else None


class _NullSpinner:
    """No-op context manager when rich is unavailable."""

    def __enter__(self) -> "_NullSpinner":
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def add_task(self, description: str, total: Any = None) -> None:
        pass
