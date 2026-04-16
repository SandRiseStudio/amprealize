"""BreakerAmp Rich Live Display.

Provides a live-updating terminal display for BreakerAmp operations,
showing per-service status, elapsed times, and phase progress.

Implements the ProgressCallback protocol from models.py.
"""

import time
from typing import Any, Dict, List, Optional, Tuple

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.rule import Rule
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from .models import NoOpProgress, ServiceStatus

# =============================================================================
# Color Palette
# =============================================================================

STYLE_WAITING = "dim"
STYLE_ACTIVE = "cyan"
STYLE_HEALTHY = "green"
STYLE_WARNING = "yellow"
STYLE_FAILED = "red"
STYLE_PHASE = "bold cyan"
STYLE_HEADER = "bold"
STYLE_DIM = "dim"

STATUS_ICONS: Dict[ServiceStatus, Tuple[str, str]] = {
    ServiceStatus.WAITING: ("◌", STYLE_WAITING),
    ServiceStatus.PULLING: ("↓", STYLE_ACTIVE),
    ServiceStatus.BUILDING: ("⚙", STYLE_ACTIVE),
    ServiceStatus.STARTING: ("▶", STYLE_ACTIVE),
    ServiceStatus.HEALTH_CHECKING: ("♥", STYLE_ACTIVE),
    ServiceStatus.HEALTHY: ("✓", STYLE_HEALTHY),
    ServiceStatus.RUNNING_POST_START: ("⚡", STYLE_ACTIVE),
    ServiceStatus.FAILED: ("✗", STYLE_FAILED),
}

STATUS_LABELS: Dict[ServiceStatus, str] = {
    ServiceStatus.WAITING: "waiting",
    ServiceStatus.PULLING: "pulling",
    ServiceStatus.BUILDING: "building",
    ServiceStatus.STARTING: "starting",
    ServiceStatus.HEALTH_CHECKING: "checking",
    ServiceStatus.HEALTHY: "healthy",
    ServiceStatus.RUNNING_POST_START: "post-start",
    ServiceStatus.FAILED: "failed",
}


def _format_duration(seconds: float) -> str:
    """Format a duration in seconds to a human-readable string."""
    if seconds < 0.1:
        return "—"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}m{secs:.0f}s"


# =============================================================================
# Header / Summary Renderers
# =============================================================================


def render_header(
    command: str,
    environment: str,
    blueprint: str = "",
    service_count: int = 0,
) -> Panel:
    """Render a styled header panel for a BreakerAmp command."""
    lines = [f"[{STYLE_HEADER}]Environment:[/{STYLE_HEADER}]  {environment}"]
    if blueprint:
        lines.append(f"[{STYLE_HEADER}]Blueprint:[/{STYLE_HEADER}]    {blueprint}")
    if service_count > 0:
        lines.append(f"[{STYLE_HEADER}]Services:[/{STYLE_HEADER}]     {service_count}")

    return Panel(
        "\n".join(lines),
        title=f"[bold]⚡ breakeramp {command}[/bold]",
        border_style="cyan",
        expand=False,
        padding=(0, 2),
    )


def render_summary(
    total_duration_s: float,
    service_ports: Dict[str, int],
    amp_run_id: str = "",
    warnings: Optional[List[str]] = None,
    failed_services: Optional[List[str]] = None,
) -> Panel:
    """Render a completion summary panel with service URLs."""
    if failed_services:
        header = f"[{STYLE_FAILED}]✗ Environment failed after {_format_duration(total_duration_s)}[/{STYLE_FAILED}]"
    else:
        header = f"[{STYLE_HEALTHY}]✓ Environment ready in {_format_duration(total_duration_s)}[/{STYLE_HEALTHY}]"

    lines = [header, ""]

    # Service URLs
    for name, port in sorted(service_ports.items(), key=lambda x: x[1]):
        # Well-known HTTP ports
        if port in (8000, 8080, 8443, 3000, 5173, 5000, 9090):
            scheme = "https" if port == 8443 else "http"
            lines.append(f"  [{STYLE_HEADER}]{name:<14}[/{STYLE_HEADER}] {scheme}://localhost:{port}")
        else:
            lines.append(f"  [{STYLE_HEADER}]{name:<14}[/{STYLE_HEADER}] localhost:{port}")

    if amp_run_id:
        lines.append("")
        lines.append(f"  [{STYLE_DIM}]Run ID  {amp_run_id}[/{STYLE_DIM}]")

    if warnings:
        lines.append("")
        for w in warnings:
            lines.append(f"  [{STYLE_WARNING}]⚠ {w}[/{STYLE_WARNING}]")

    if failed_services:
        lines.append("")
        for svc in failed_services:
            lines.append(f"  [{STYLE_FAILED}]✗ {svc}[/{STYLE_FAILED}]")

    border = STYLE_FAILED if failed_services else STYLE_HEALTHY
    return Panel(
        "\n".join(lines),
        border_style=border,
        expand=False,
        padding=(0, 2),
    )


# =============================================================================
# Service State Tracking
# =============================================================================


class _ServiceState:
    """Internal state tracker for a single service."""

    __slots__ = ("name", "status", "detail", "port", "start_time", "end_time")

    def __init__(self, name: str, port: int = 0) -> None:
        self.name = name
        self.status = ServiceStatus.WAITING
        self.detail = ""
        self.port = port
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None

    @property
    def elapsed(self) -> float:
        if self.start_time is None:
            return 0.0
        end = self.end_time or time.monotonic()
        return end - self.start_time


# =============================================================================
# LiveProgressDisplay — implements ProgressCallback
# =============================================================================


class LiveProgressDisplay:
    """Rich Live display implementing the ProgressCallback protocol.

    Usage::

        display = LiveProgressDisplay(console=console)
        display.set_services(["db", "redis", "api"], ports={"db": 5432, "redis": 6379, "api": 8000})
        with display:
            service.apply(request, progress=display)
        display.print_summary(amp_run_id=response.amp_run_id)
    """

    def __init__(
        self,
        console: Optional[Console] = None,
        *,
        quiet: bool = False,
        verbose: bool = False,
    ) -> None:
        self._console = console or Console()
        self._quiet = quiet
        self._verbose = verbose
        self._live: Optional[Live] = None
        self._services: Dict[str, _ServiceState] = {}
        self._service_order: List[str] = []
        self._phase: str = ""
        self._phase_desc: str = ""
        self._phase_total: int = 0
        self._phase_done: int = 0
        self._start_time: float = 0.0
        self._warnings: List[str] = []
        self._errors: List[str] = []
        self._verbose_lines: List[str] = []

    @property
    def quiet(self) -> bool:
        """Whether to suppress detailed output."""
        return self._quiet

    # -- Setup ----------------------------------------------------------------

    def set_services(
        self,
        names: List[str],
        ports: Optional[Dict[str, int]] = None,
    ) -> None:
        """Pre-register services for display before the Live context starts."""
        ports = ports or {}
        self._service_order = list(names)
        self._services = {
            name: _ServiceState(name, port=ports.get(name, 0))
            for name in names
        }

    # -- Context manager (Rich Live) ------------------------------------------

    def __enter__(self) -> "LiveProgressDisplay":
        self._start_time = time.monotonic()
        if not self._quiet:
            self._live = Live(
                self._render(),
                console=self._console,
                refresh_per_second=8,
                transient=True,
            )
            self._live.__enter__()
        return self

    def __exit__(self, *args: Any) -> None:
        if self._live is not None:
            self._live.__exit__(*args)
            self._live = None

    # -- ProgressCallback implementation --------------------------------------

    def on_phase(self, phase: str, description: str, total_steps: int = 0) -> None:
        self._phase = phase
        self._phase_desc = description
        self._phase_total = total_steps
        self._phase_done = 0
        self._refresh()

    def on_step(self, step: str, description: str, *, service: Optional[str] = None) -> None:
        if self._verbose:
            self._verbose_lines.append(f"  {description}")
            # Cap verbose buffer
            if len(self._verbose_lines) > 50:
                self._verbose_lines = self._verbose_lines[-30:]
        self._refresh()

    def on_step_done(self, step: str, *, duration_s: float = 0.0, service: Optional[str] = None, detail: str = "") -> None:
        self._phase_done += 1
        if detail and not self.quiet:
            self._verbose_lines.append(f"  {step}: {detail}")
        self._refresh()

    def on_service_status(self, service: str, status: ServiceStatus, detail: str = "") -> None:
        state = self._services.get(service)
        if state is None:
            # Dynamically discovered service
            state = _ServiceState(service)
            self._services[service] = state
            self._service_order.append(service)

        old_status = state.status
        state.status = status
        state.detail = detail

        # Track timing
        if old_status == ServiceStatus.WAITING and status != ServiceStatus.WAITING:
            state.start_time = time.monotonic()
        if status in (ServiceStatus.HEALTHY, ServiceStatus.FAILED):
            state.end_time = time.monotonic()

        self._refresh()

    def on_warning(self, message: str) -> None:
        self._warnings.append(message)
        self._refresh()

    def on_error(self, message: str, *, service: Optional[str] = None) -> None:
        self._errors.append(message)
        self._refresh()

    # -- Rendering ------------------------------------------------------------

    def _refresh(self) -> None:
        if self._live is not None:
            self._live.update(self._render())

    def _render(self) -> Group:
        """Build the full Rich renderable for Live."""
        parts: List[Any] = []

        # Phase header
        if self._phase_desc:
            elapsed = _format_duration(time.monotonic() - self._start_time)
            if self._phase_total > 0:
                progress_text = f"{self._phase_done}/{self._phase_total}"
                parts.append(
                    Text.from_markup(
                        f"[{STYLE_PHASE}]{self._phase_desc}[/{STYLE_PHASE}]"
                        f"  [{STYLE_DIM}]{progress_text}  {elapsed}[/{STYLE_DIM}]"
                    )
                )
            else:
                parts.append(
                    Text.from_markup(
                        f"[{STYLE_PHASE}]{self._phase_desc}[/{STYLE_PHASE}]"
                        f"  [{STYLE_DIM}]{elapsed}[/{STYLE_DIM}]"
                    )
                )
            parts.append(Text(""))

        # Service table
        if self._services:
            healthy_count = sum(
                1 for s in self._services.values()
                if s.status == ServiceStatus.HEALTHY
            )
            total = len(self._services)

            for name in self._service_order:
                state = self._services.get(name)
                if state is None:
                    continue

                icon, icon_style = STATUS_ICONS.get(state.status, ("?", "white"))
                label = STATUS_LABELS.get(state.status, str(state.status.value))
                detail = state.detail or label

                # Port display
                port_str = f":{state.port}" if state.port else ""

                # Duration
                dur = _format_duration(state.elapsed)
                dur_style = STYLE_WARNING if state.elapsed > 30 else STYLE_DIM

                # Compose line
                if state.status in (
                    ServiceStatus.PULLING, ServiceStatus.BUILDING,
                    ServiceStatus.STARTING, ServiceStatus.HEALTH_CHECKING,
                    ServiceStatus.RUNNING_POST_START,
                ):
                    # Active — use spinner-like icon
                    parts.append(
                        Text.from_markup(
                            f"  [{icon_style}]{icon}[/{icon_style}]"
                            f" [{icon_style}]{name:<22}[/{icon_style}]"
                            f" [{icon_style}]{detail:<14}[/{icon_style}]"
                            f" [{STYLE_DIM}]{port_str:<8}[/{STYLE_DIM}]"
                            f" [{dur_style}]{dur:>8}[/{dur_style}]"
                        )
                    )
                elif state.status == ServiceStatus.FAILED:
                    parts.append(
                        Text.from_markup(
                            f"  [{STYLE_FAILED}]{icon} {name:<22} {detail:<14}[/{STYLE_FAILED}]"
                            f" [{STYLE_DIM}]{port_str:<8}[/{STYLE_DIM}]"
                            f" [{dur_style}]{dur:>8}[/{dur_style}]"
                        )
                    )
                elif state.status == ServiceStatus.HEALTHY:
                    parts.append(
                        Text.from_markup(
                            f"  [{STYLE_HEALTHY}]{icon} {name:<22} {detail:<14}[/{STYLE_HEALTHY}]"
                            f" [{STYLE_DIM}]{port_str:<8}[/{STYLE_DIM}]"
                            f" [{dur_style}]{dur:>8}[/{dur_style}]"
                        )
                    )
                else:
                    # Waiting
                    parts.append(
                        Text.from_markup(
                            f"  [{STYLE_WAITING}]{icon} {name:<22} {detail:<14}"
                            f" {port_str:<8}    —[/{STYLE_WAITING}]"
                        )
                    )

            # Status bar
            parts.append(Text(""))
            bar_text = f"  {healthy_count}/{total} services ready"
            if healthy_count == total and total > 0:
                parts.append(Text.from_markup(f"  [{STYLE_HEALTHY}]{bar_text}[/{STYLE_HEALTHY}]"))
            else:
                parts.append(Text.from_markup(f"  [{STYLE_DIM}]{bar_text}[/{STYLE_DIM}]"))

        # Verbose lines
        if self._verbose and self._verbose_lines:
            parts.append(Text(""))
            for line in self._verbose_lines[-5:]:
                parts.append(Text.from_markup(f"  [{STYLE_DIM}]{line}[/{STYLE_DIM}]"))

        # Warnings
        for w in self._warnings[-3:]:
            parts.append(Text.from_markup(f"  [{STYLE_WARNING}]⚠ {w}[/{STYLE_WARNING}]"))

        return Group(*parts)

    # -- Post-run Summary -----------------------------------------------------

    def print_summary(self, amp_run_id: str = "") -> None:
        """Print the completion summary panel after Live has exited."""
        total_duration = time.monotonic() - self._start_time if self._start_time else 0.0

        service_ports: Dict[str, int] = {}
        failed: List[str] = []
        for name in self._service_order:
            state = self._services.get(name)
            if state is None:
                continue
            if state.status == ServiceStatus.FAILED:
                failed.append(name)
            if state.port:
                service_ports[name] = state.port

        summary = render_summary(
            total_duration_s=total_duration,
            service_ports=service_ports,
            amp_run_id=amp_run_id,
            warnings=self._warnings if self._warnings else None,
            failed_services=failed if failed else None,
        )
        self._console.print(summary)

    @property
    def total_elapsed(self) -> float:
        if self._start_time == 0:
            return 0.0
        return time.monotonic() - self._start_time

    @property
    def has_failures(self) -> bool:
        return any(
            s.status == ServiceStatus.FAILED
            for s in self._services.values()
        )
