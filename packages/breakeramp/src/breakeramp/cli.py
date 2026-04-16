"""BreakerAmp Command-Line Interface.

Standalone CLI for managing container environments using BreakerAmp.

Usage:
    breakeramp plan postgres-dev --env development
    breakeramp apply --plan-id <plan-id>
    breakeramp status amp-abc123
    breakeramp destroy amp-abc123 --reason "cleanup"
    breakeramp list

Install with CLI support:
    pip install breakeramp[cli]
"""

import os
from pathlib import Path
from typing import Optional, List, Dict, Any
import json
import sys

try:
    import typer
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.prompt import Confirm, Prompt
except ImportError as e:
    raise ImportError(
        "CLI requires typer and rich. Install with: pip install breakeramp[cli]"
    ) from e

from .service import BreakerAmpService
from .executors import PodmanExecutor
from .models import PlanRequest, ApplyRequest, DestroyRequest
from .display import LiveProgressDisplay, render_header, render_summary

app = typer.Typer(
    name="breakeramp",
    help="Container environment management made simple.",
    add_completion=False,
)
console = Console()


def get_service() -> BreakerAmpService:
    """Get configured BreakerAmpService instance."""
    executor = PodmanExecutor()
    return BreakerAmpService(executor=executor)


def _apply_amprealize_context(quiet: bool = False) -> Optional[str]:
    """Apply amprealize context to environment if available.

    This ensures DATABASE_URL and other DSNs are set from the active context
    before breakeramp expands blueprint variables.

    Returns the context name if applied, None otherwise.
    """
    try:
        from amprealize.context import apply_context_to_environment
        ctx_name = apply_context_to_environment(force=True)
        if ctx_name and not quiet:
            console.print(f"[dim]📍 Using context: {ctx_name}[/dim]")
        return ctx_name
    except ImportError:
        # amprealize not installed - breakeramp running standalone
        return None
    except Exception:
        # Context system not configured or failed - continue without it
        return None


def _get_environment_podman_machine(
    service: BreakerAmpService,
    environment: str,
) -> Optional[str]:
    """Return the configured Podman machine for an environment, if any."""
    env_def = service.environments.get(environment)
    if not env_def:
        return None

    runtime = getattr(env_def, "runtime", None)
    if runtime is None or getattr(runtime, "provider", None) != "podman":
        return None

    return getattr(runtime, "podman_machine", None)


def _list_podman_machine_names() -> List[str]:
    """List available Podman machine names, stripped of active markers."""
    import subprocess

    result = subprocess.run(
        ["podman", "machine", "list", "--format", "{{.Name}}"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        return []

    names: List[str] = []
    for line in result.stdout.strip().split("\n"):
        name = line.strip().rstrip("*")
        if name:
            names.append(name)
    return names


def _select_podman_machine_for_environment(
    available_names: List[str],
    preferred_name: Optional[str] = None,
) -> Optional[str]:
    """Choose which Podman machine to start for a fresh run.

    If the environment explicitly configures a Podman machine, only that
    machine is eligible. Otherwise, fall back to the first amprealize-named
    machine discovered locally.
    """
    if preferred_name:
        return preferred_name if preferred_name in available_names else None

    for name in available_names:
        if "amprealize" in name.lower():
            return name

    return None


def _is_cloud_dsn(dsn: str) -> bool:
    """Return True if the DSN hostname is not a local address."""
    try:
        from urllib.parse import urlparse
        host = (urlparse(dsn).hostname or "").lower()
        return bool(host) and host not in ("localhost", "127.0.0.1", "::1")
    except Exception:
        return False


def _check_context_blueprint_mismatch(
    context_name: Optional[str],
    environment: str,
    service: BreakerAmpService,
    blueprint_override: Optional[str] = None,
) -> Optional[tuple]:
    """Detect mismatch between a cloud context and a local-DB blueprint.

    Returns ``(warning_message, suggested_environment)`` when the active
    context points to a remote database but the selected environment would
    spin up local database containers.  Returns ``None`` when there is no
    mismatch (or not enough information to decide).
    """
    if not context_name:
        return None

    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn or not _is_cloud_dsn(dsn):
        return None

    # Resolve which blueprint the environment would use
    env_def = service.environments.get(environment)
    if not env_def:
        return None

    infra = getattr(env_def, "infrastructure", None)
    blueprint_id = blueprint_override or getattr(infra, "blueprint_id", None)
    if not blueprint_id:
        return None

    # If the blueprint is already cloud-oriented, there is no mismatch
    cloud_env = "cloud-dev"
    cloud_env_def = service.environments.get(cloud_env)
    if not cloud_env_def:
        return None  # no cloud-dev environment to suggest

    cloud_infra = getattr(cloud_env_def, "infrastructure", None)
    cloud_blueprint = getattr(cloud_infra, "blueprint_id", "cloud-dev")
    if blueprint_id == cloud_blueprint:
        return None

    try:
        from urllib.parse import urlparse
        host = urlparse(dsn).hostname or "cloud host"
    except Exception:
        host = "cloud host"

    warning = (
        f"Context '{context_name}' points to a remote database ({host}) "
        f"but environment '{environment}' uses blueprint '{blueprint_id}' "
        f"which starts local database containers.\n"
        f"  → Use 'breakeramp fresh {cloud_env}' to skip local DB containers."
    )
    return warning, cloud_env


def _recover_podman_machine_start(
    service: BreakerAmpService,
    machine_name: str,
    *,
    quiet: bool = False,
) -> bool:
    """Recreate a Podman machine when startup fails in a way `fresh` can tolerate.

    This is intentionally destructive and is only appropriate for flows like
    `breakeramp fresh`, where the caller has already chosen a full reset.
    """
    try:
        from .executors.podman import PodmanExecutor
        import subprocess

        if not isinstance(service.executor, PodmanExecutor):
            return False

        machine_info = service.executor.inspect_machine(machine_name)
        resources = machine_info.get("Resources", {}) if isinstance(machine_info, dict) else {}
        ssh_cfg = machine_info.get("SSH", {}) if isinstance(machine_info, dict) else {}
        ssh_port = ssh_cfg.get("Port")

        cpus = resources.get("CPUs")
        memory_mb = resources.get("Memory")
        disk_gb = resources.get("DiskSize")

        if not quiet:
            console.print(f"[yellow]Attempting machine recovery for '{machine_name}'...[/yellow]")

        try:
            service.executor.stop_machine(machine_name)
        except Exception:
            pass

        if ssh_port:
            subprocess.run(
                ["pkill", "-f", f"gvproxy.*-ssh-port {ssh_port}"],
                capture_output=True,
                text=True,
            )

        subprocess.run(
            [
                "rm",
                "-f",
                os.path.expanduser(f"~/.local/share/containers/podman/machine/applehv/{machine_name}-ignition.sock"),
                os.path.expanduser(f"~/.config/containers/podman/machine/applehv/{machine_name}.lock"),
            ],
            capture_output=True,
            text=True,
        )

        service.executor.remove_machine(machine_name, force=True)
        service.executor.init_machine(
            machine_name,
            cpus=cpus,
            memory_mb=memory_mb,
            disk_gb=disk_gb,
        )
        service.executor.start_machine(machine_name)
        return True
    except Exception as exc:
        if not quiet:
            console.print(f"[yellow]Machine recovery failed: {exc}[/yellow]")
        return False


# =============================================================================
# Plan Command
# =============================================================================

@app.command()
def plan(
    environment: str = typer.Argument(
        ...,
        help="Environment name (e.g., 'development')",
    ),
    blueprint: Optional[str] = typer.Option(
        None,
        "--blueprint", "-b",
        help="Blueprint ID to plan (e.g., 'postgres-dev')",
    ),
    lifetime: Optional[str] = typer.Option(
        None,
        "--lifetime", "-l",
        help="Environment lifetime (e.g., '2h', '90m')",
    ),
    compliance_tier: Optional[str] = typer.Option(
        None,
        "--compliance", "-c",
        help="Compliance tier override",
    ),
    modules: Optional[List[str]] = typer.Option(
        None,
        "--module", "-m",
        help="Modules to activate (can specify multiple times)",
    ),
    machine_disk_size_gb: Optional[int] = typer.Option(
        None,
        "--machine-disk-size-gb",
        help="Override Podman machine disk size in GB (default: 20GB, Podman's default is 100GB!)",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output", "-o",
        help="Output plan to JSON file",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet", "-q",
        help="Only output plan ID",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose", "-v",
        help="Show detailed resource insights",
    ),
    force_podman: bool = typer.Option(
        False,
        "--force-podman",
        help="Skip Podman machine checks/warnings",
    ),
) -> None:
    """Plan an environment deployment.

    Analyzes the blueprint and environment, generating a deployment plan
    that shows what actions will be taken during apply.
    """
    service = get_service()

    request = PlanRequest(
        environment=environment,
        blueprint_id=blueprint,
        lifetime=lifetime,
        compliance_tier=compliance_tier,
        active_modules=modules,
        force_podman=force_podman,
        machine_disk_size_gb=machine_disk_size_gb,
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task("Planning...", total=None)

        try:
            response = service.plan(request)
        except Exception as e:
            console.print(f"[red]Plan failed: {e}[/red]")
            raise typer.Exit(1)

    if quiet:
        console.print(response.plan_id)
        return

    if output:
        output.write_text(response.model_dump_json(indent=2))
        console.print(f"[green]Plan written to {output}[/green]")
        return

    # Display plan summary
    estimates = response.environment_estimates
    console.print(Panel(
        f"[bold]Plan ID:[/bold] {response.plan_id}\n"
        f"[bold]Run ID:[/bold] {response.amp_run_id}\n"
        f"[bold]Memory:[/bold] {estimates.memory_footprint_mb} MB\n"
        f"[bold]Boot Time:[/bold] ~{estimates.expected_boot_duration_s}s",
        title="BreakerAmp Plan",
        expand=False,
    ))

    # Show manifest services
    manifest = response.signed_manifest
    if manifest.get("services"):
        table = Table(title="Planned Services")
        table.add_column("Service", style="cyan")
        table.add_column("Image", style="green")
        table.add_column("Ports")

        for svc_name, svc_config in manifest.get("services", {}).items():
            ports = ", ".join(svc_config.get("ports", [])) if svc_config.get("ports") else "-"
            table.add_row(
                svc_name,
                svc_config.get("image", "unknown"),
                ports,
            )

        console.print(table)

    # Show resource insights
    try:
        executor = PodmanExecutor()
        resource_data = executor.get_resource_insights(verbose=verbose)
        if resource_data.get("summary"):
            console.print()
            console.print(Panel(
                resource_data["summary"],
                title="Resource Status",
                expand=False,
            ))
    except Exception:
        pass  # Skip insights if unavailable

    console.print()
    console.print(f"[dim]Run 'breakeramp apply --plan-id {response.plan_id}' to execute this plan[/dim]")


# =============================================================================
# Apply Command
# =============================================================================

@app.command()
def apply(
    plan_id: Optional[str] = typer.Option(
        None,
        "--plan-id", "-p",
        help="Plan ID from a previous plan command",
    ),
    plan_file: Optional[Path] = typer.Option(
        None,
        "--plan-file", "-f",
        help="Apply from a saved plan JSON file",
    ),
    watch: bool = typer.Option(
        True,
        "--watch/--no-watch", "-w",
        help="Watch for completion",
    ),
    resume: bool = typer.Option(
        False,
        "--resume",
        help="Resume a partial apply",
    ),
    force_podman: bool = typer.Option(
        False,
        "--force-podman",
        help="Skip Podman machine checks/warnings",
    ),
    skip_resource_check: bool = typer.Option(
        False,
        "--skip-resource-check",
        help="Skip pre-flight resource health check",
    ),
    proactive_cleanup: bool = typer.Option(
        True,
        "--proactive-cleanup/--no-proactive-cleanup",
        help="Run cleanup BEFORE resource check to maximize available resources (default: enabled)",
    ),
    auto_cleanup: bool = typer.Option(
        True,
        "--auto-cleanup/--no-auto-cleanup",
        help="Automatically clean up resources if low during apply (default: enabled)",
    ),
    auto_cleanup_aggressive: bool = typer.Option(
        True,
        "--auto-cleanup-aggressive/--no-auto-cleanup-aggressive",
        help="Use aggressive cleanup including images/cache (default: enabled)",
    ),
    auto_cleanup_volumes: bool = typer.Option(
        False,
        "--auto-cleanup-volumes",
        help="Include volumes in cleanup (WARNING: may lose data)",
    ),
    blueprint_aware_memory: bool = typer.Option(
        True,
        "--blueprint-aware-memory/--no-blueprint-aware-memory",
        help="Use blueprint memory estimates for resource check (default: enabled)",
    ),
    memory_safety_margin_mb: float = typer.Option(
        512.0,
        "--memory-safety-margin-mb",
        help="Extra memory to require beyond blueprint estimate (default: 512 MB)",
    ),
    min_disk_gb: float = typer.Option(
        5.0,
        "--min-disk-gb",
        help="Minimum disk space required in GB (default: 5.0)",
    ),
    machine_disk_size_gb: Optional[int] = typer.Option(
        None,
        "--machine-disk-size-gb",
        help="Override Podman machine disk size in GB for auto_init (default: use environment config, typically 20GB)",
    ),
    min_memory_mb: float = typer.Option(
        1024.0,
        "--min-memory-mb",
        help="Minimum memory required in MB (default: 1024)",
    ),
    auto_resolve_stale: bool = typer.Option(
        True,
        "--auto-resolve-stale/--no-auto-resolve-stale",
        help="Automatically remove stale/exited/dead containers before apply (default: enabled)",
    ),
    auto_resolve_conflicts: bool = typer.Option(
        True,
        "--auto-resolve-conflicts/--no-auto-resolve-conflicts",
        help="Automatically resolve port conflicts (stop conflicting containers/processes) (default: enabled)",
    ),
    stale_max_age_hours: Optional[float] = typer.Option(
        0.0,
        "--stale-max-age-hours",
        help="Max age for stale container cleanup in hours (0 = all stale, -1 = skip age check)",
    ),
    # Machine scale-down options for critical disk situations
    auto_cleanup_scaledown_machines: bool = typer.Option(
        False,
        "--auto-cleanup-scaledown-machines",
        help="Stop unused Podman machines when disk is critically low (last resort, macOS/Windows only)",
    ),
    auto_cleanup_remove_machines: bool = typer.Option(
        False,
        "--auto-cleanup-remove-machines",
        help="Remove unused machines if scaledown enabled (WARNING: destructive, requires rebuilding machine)",
    ),
    preserve_machines: Optional[List[str]] = typer.Option(
        None,
        "--preserve-machine",
        help="Machine names to never scale down (can specify multiple times)",
    ),
    allow_host_resource_warning: bool = typer.Option(
        False,
        "--allow-host-resource-warning",
        help="Proceed even if only HOST is low on disk/memory (unsafe; may still fail later)",
    ),
    interactive: bool = typer.Option(
        False,
        "--interactive/--no-interactive",
        help="On resource shortage, prompt for actions and retry (default: disabled)",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet", "-q",
        help="Minimal output",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose", "-v",
        help="Show detailed progress and streaming build/healthcheck output",
    ),
) -> None:
    """Apply an environment plan.

    Creates or updates the environment based on the blueprint and configuration.

    By default, proactive resource management is enabled:
    - Proactive cleanup runs BEFORE resource check to maximize available resources
    - Auto-cleanup handles low resources during provisioning
    - Blueprint-aware memory checking uses actual service memory requirements
    - Auto-resolve removes stale containers and resolves port conflicts automatically
    """
    service = get_service()

    manifest = None

    # Load plan from file if provided
    if plan_file and plan_file.exists():
        plan_data = json.loads(plan_file.read_text())
        plan_id = plan_data.get("plan_id")
        manifest = plan_data.get("signed_manifest")

    if not plan_id and not manifest:
        console.print("[red]Plan ID or plan file required[/red]")
        console.print("[dim]Run 'breakeramp plan <environment>' first[/dim]")
        raise typer.Exit(1)

    # Handle special value -1 for stale_max_age_hours (skip age check)
    effective_stale_max_age = None if stale_max_age_hours == -1 else stale_max_age_hours

    request = ApplyRequest(
        plan_id=plan_id,
        manifest=manifest,
        watch=watch,
        resume=resume,
        force_podman=force_podman,
        skip_resource_check=skip_resource_check,
        proactive_cleanup=proactive_cleanup,
        auto_cleanup=auto_cleanup,
        auto_cleanup_aggressive=auto_cleanup_aggressive,
        auto_cleanup_include_volumes=auto_cleanup_volumes,
        allow_host_resource_warning=allow_host_resource_warning,
        blueprint_aware_memory_check=blueprint_aware_memory,
        memory_safety_margin_mb=memory_safety_margin_mb,
        min_disk_gb=min_disk_gb,
        min_memory_mb=min_memory_mb,
        auto_resolve_stale=auto_resolve_stale,
        auto_resolve_conflicts=auto_resolve_conflicts,
        stale_max_age_hours=effective_stale_max_age,
        auto_cleanup_scale_down=auto_cleanup_scaledown_machines,
        auto_cleanup_remove_machines=auto_cleanup_remove_machines,
        preserve_machines=preserve_machines or [],
    )

    def _is_resource_shortage_error(exc: Exception) -> bool:
        text = str(exc)
        return "Resource shortage detected" in text

    def _is_podman_connection_error(exc: Exception) -> bool:
        """Check if exception is a Podman connection/proxy error.

        These can happen when:
        - Podman machine is not running
        - gvproxy process died but machine reports as running
        - SSH tunnel to VM failed
        - Socket file is stale
        """
        text = str(exc).lower()
        return (
            "cannot connect to podman" in text
            or "unable to connect to podman socket" in text
            or ("connection refused" in text and "podman" in text)
            or ("podman system connection" in text and "refused" in text)
            # New: catch dial tcp connection refused (from Go network layer)
            or ("dial tcp" in text and "connection refused" in text)
        )

    def _extract_warnings(exc: Exception) -> List[str]:
        text = str(exc)
        warnings: List[str] = []
        if "Warnings:" not in text:
            return warnings
        after = text.split("Warnings:", 1)[1]
        for line in after.splitlines():
            stripped = line.strip()
            if stripped.startswith("- "):
                warnings.append(stripped[2:].strip())
            elif stripped.startswith("• "):
                warnings.append(stripped[2:].strip())
            elif stripped.startswith("  - "):
                warnings.append(stripped[4:].strip())
        return warnings

    if interactive and not (sys.stdin.isatty() and sys.stdout.isatty()):
        console.print("[red]--interactive requires an interactive TTY (stdin/stdout).[/red]")
        raise typer.Exit(2)

    interactive_enabled = bool(interactive)
    max_attempts = 3
    attempt = 0
    response = None

    # NOTE: Prompts must run outside Rich Live; otherwise the live refresh can
    # prevent interactive input from appearing/working correctly in some terminals.
    while True:
        attempt += 1
        try:
            display = LiveProgressDisplay(console=console, quiet=quiet, verbose=verbose)
            with display:
                display.on_phase("apply", "Applying environment")
                response = service.apply(request, progress=display)
            if response:
                display.print_summary(amp_run_id=response.amp_run_id)
            break
        except Exception as e:
            # Podman connectivity failures are common on macOS/Windows if the VM isn't running.
            # In interactive mode, offer to start/init a machine before retrying.
            if interactive_enabled and _is_podman_connection_error(e):
                console.print(f"[red]Apply failed: {e}[/red]")
                try:
                    from .executors.podman import PodmanExecutor

                    if isinstance(service.executor, PodmanExecutor):
                        machines = service.executor.list_machines()
                        running = [m for m in machines if m.running]
                        stopped = [m for m in machines if not m.running]

                        machine_summary = "No Podman machines found."
                        if machines:
                            machine_summary = "\n".join(
                                f"- {m.name}: {'running' if m.running else 'stopped'}"
                                for m in machines
                                if m.name
                            )
                        console.print(Panel(machine_summary, title="Podman Machines", expand=False))

                        # If machine shows running but we got connection error, it's likely a dead proxy
                        if running:
                            console.print("[yellow]⚠ Machine reports 'running' but connection failed - proxy may be dead.[/yellow]")

                        choices = {
                            "1": "Force restart machine (fixes dead proxy) and retry",
                            "2": "Start a Podman machine and retry",
                            "3": "Init + start a new machine (podman-machine-default) and retry",
                            "4": "Show podman connections (diagnostic)",
                            "5": "Abort",
                        }
                        menu = "\n".join([f"[bold]{k}.[/bold] {v}" for k, v in choices.items()])
                        console.print(Panel(menu, title="Next Step", expand=False))
                        selection = Prompt.ask("Choose", choices=list(choices.keys()), default="1" if running else "2")

                        if selection == "5":
                            raise typer.Exit(1)

                        if selection == "4":
                            try:
                                connections = service.executor.list_connections()
                                pretty = "\n".join(
                                    f"- {c.get('Name')}: {c.get('URI')} ({'default' if c.get('Default') else 'non-default'})"
                                    for c in connections
                                ) or "No connections found."
                                console.print(Panel(pretty, title="podman system connection list", expand=False))
                            except Exception as exc:
                                console.print(f"[yellow]Failed to list podman connections: {exc}[/yellow]")
                            continue

                        # selection 1: force restart (stop --force, then start)
                        if selection == "1":
                            try:
                                import subprocess
                                target = None
                                for m in running:
                                    if m.name:
                                        target = m.name
                                        break
                                if not target:
                                    for m in machines:
                                        if m.name:
                                            target = m.name
                                            break
                                if target:
                                    console.print(f"[dim]Force stopping Podman machine '{target}'...[/dim]")
                                    subprocess.run(["podman", "machine", "stop", target], capture_output=True)
                                    import time
                                    time.sleep(2)
                                    console.print(f"[dim]Starting Podman machine '{target}'...[/dim]")
                                    result = subprocess.run(["podman", "machine", "start", target], capture_output=True, text=True)
                                    if result.returncode != 0:
                                        console.print(f"[yellow]Start failed: {result.stderr}[/yellow]")
                                    else:
                                        console.print("[green]✓ Machine restarted successfully[/green]")
                                        time.sleep(2)  # Give proxy time to initialize
                                else:
                                    console.print("[yellow]No machine found to restart[/yellow]")
                            except Exception as exc:
                                console.print(f"[yellow]Force restart failed: {exc}[/yellow]")
                            continue

                        # selection 2/3: start/init machine best-effort.
                        try:
                            preferred = None
                            for m in stopped:
                                if m.name == "podman-machine-default":
                                    preferred = m.name
                                    break
                            if not preferred and stopped:
                                preferred = stopped[0].name
                            if not preferred and machines:
                                preferred = machines[0].name

                            if selection == "3" or not machines:
                                name = "podman-machine-default"
                                console.print(f"[dim]Initializing Podman machine '{name}'...[/dim]")
                                service.executor.init_machine(name)
                                preferred = name

                            if preferred:
                                console.print(f"[dim]Starting Podman machine '{preferred}'...[/dim]")
                                service.executor.start_machine(preferred)
                            elif running:
                                console.print("[dim]A Podman machine is already running.[/dim]")
                        except Exception as exc:
                            console.print(f"[yellow]Podman machine operation failed: {exc}[/yellow]")
                        continue
                except Exception:
                    # If we can't provide a guided fix, fall through to default handling below.
                    pass

            # In interactive mode, allow unlimited attempts for resource resolution
            if not _is_resource_shortage_error(e) or (not interactive_enabled and attempt >= max_attempts):
                console.print(f"[red]Apply failed: {e}[/red]")
                raise typer.Exit(1)

            warnings = _extract_warnings(e)
            warning_block = "\n".join(f"- {w}" for w in warnings) if warnings else str(e)
            console.print(
                Panel(
                    warning_block,
                    title="Resource Shortage Detected",
                    subtitle=f"Attempt {attempt}/{max_attempts} (interactive)",
                    expand=False,
                )
            )

            # Provide a small, context-aware menu.
            choices = {
                "1": "Show resource report (disk/memory) and retry",
                "2": "Run safe cleanup (host cache) and retry",
                "3": "Remove unused Podman machines (frees disk; destructive) and retry",
                "4": "Show disk space analysis (find what's using space)",
                "5": "Run AGGRESSIVE cleanup (Trash, Homebrew, npm, pip, Xcode)",
                "6": "Run DEEP cleanup (VS Code caches, Podman cache, unused machines)",
                "7": "Proceed anyway (allow host warning)",
                "8": "Skip resource checks (unsafe)",
                "9": "Adjust thresholds and retry",
                "0": "Abort",
            }
            menu = "\n".join([f"[bold]{k}.[/bold] {v}" for k, v in choices.items()])
            console.print(Panel(menu, title="Next Step", expand=False))
            selection = Prompt.ask("Choose", choices=list(choices.keys()), default="0")

            if selection == "0":
                raise typer.Exit(1)

            if selection == "1":
                try:
                    from .executors.base import ResourceCapableExecutor
                    if isinstance(service.executor, ResourceCapableExecutor):
                        resources = service.executor.get_all_resources()
                        lines = []
                        for info in resources:
                            disk = info.disk
                            mem = info.memory
                            cpu = info.cpu
                            lines.append(
                                f"- {info.source}: "
                                f"disk {disk.available:.1f}{disk.unit} free ({disk.percent_used:.1f}% used), "
                                f"mem {mem.available:.0f}{mem.unit} free ({mem.percent_used:.1f}% used), "
                                f"cpu load {cpu.used:.2f}/{cpu.total:.0f}"
                                if disk and mem and cpu else f"- {info.source}: (incomplete metrics)"
                            )
                        console.print(Panel("\n".join(lines) or "No resource info available.", title="Resource Report", expand=False))
                except Exception as exc:
                    console.print(f"[yellow]Failed to collect resource report: {exc}[/yellow]")
                continue

            if selection == "2":
                if not Confirm.ask("Run host cache cleanup and retry apply?", default=True):
                    raise typer.Exit(1)
                try:
                    from .executors.podman import PodmanExecutor
                    if isinstance(service.executor, PodmanExecutor):
                        cleanup = service.executor.mitigate_host_resources(
                            dry_run=False,
                            clean_container_cache=True,
                            clean_tmp_files=True,
                            aggressive=True,
                        )

                        # Build detailed report
                        details = cleanup.details or {}
                        cleaned_items = []
                        if details.get("cache_dirs"):
                            for d in details["cache_dirs"]:
                                cleaned_items.append(f"  - {d['path']}: {d['size_mb']:.1f}MB")
                        if details.get("tmp_files"):
                            for f in details["tmp_files"]:
                                cleaned_items.append(f"  - {f['path']}: {f['size_mb']:.1f}MB")
                        if details.get("additional_caches"):
                            for c in details["additional_caches"]:
                                cleaned_items.append(f"  - {c['path']}: {c['size_mb']:.1f}MB")

                        if cleanup.host_space_reclaimed_mb < 1:
                            # If nothing was cleaned, provide helpful suggestions
                            summary = (
                                f"Host cleanup reclaimed ~{cleanup.host_space_reclaimed_mb:.0f}MB\n\n"
                                f"[yellow]Very little found to clean.[/yellow] Your host disk is {cleanup.details.get('host_disk_percent_used', 99):.0f}% full.\n\n"
                                f"To free significant space, try:\n"
                                f"  - Empty Trash (often has GB of data)\n"
                                f"  - Remove large downloads/files\n"
                                f"  - Run: docker system prune -a (if Docker installed)\n"
                                f"  - Run: brew cleanup --prune=all (if Homebrew installed)\n"
                                f"  - Use Disk Utility > First Aid on your disk\n"
                                f"  - Check ~/Library/Caches for large app caches"
                            )
                        else:
                            summary = (
                                f"Host cleanup reclaimed ~{cleanup.host_space_reclaimed_mb:.0f}MB"
                                + (f" (errors: {len(cleanup.errors)})" if cleanup.errors else "")
                            )
                            if cleaned_items:
                                summary += "\n\nCleaned:\n" + "\n".join(cleaned_items[:10])
                                if len(cleaned_items) > 10:
                                    summary += f"\n  ...and {len(cleaned_items) - 10} more"

                        console.print(Panel(summary, title="Host Cleanup", expand=False))
                except Exception as exc:
                    console.print(f"[yellow]Host cleanup failed: {exc}[/yellow]")
                continue

            if selection == "3":
                if not Confirm.ask(
                    "Remove stopped/unused Podman machines and retry apply? (destructive)",
                    default=False,
                ):
                    raise typer.Exit(1)
                # Actually perform the cleanup immediately and report results
                try:
                    from .executors.podman import PodmanExecutor
                    if isinstance(service.executor, PodmanExecutor):
                        # First show what machines exist
                        machines = service.executor.list_machines()
                        running = [m for m in machines if m.running]
                        stopped = [m for m in machines if not m.running]

                        if not stopped:
                            console.print(Panel(
                                f"No stopped machines to remove.\n"
                                f"Running machines: {', '.join(m.name or 'unnamed' for m in running) or 'none'}\n\n"
                                f"[yellow]Note:[/yellow] The running machine cannot be removed while in use.\n"
                                f"To free significant space, you may need to:\n"
                                f"  - Empty Trash (often has GB of data)\n"
                                f"  - Remove large files/downloads\n"
                                f"  - Run: docker system prune -a (if Docker Desktop installed)\n"
                                f"  - Run: brew cleanup (if Homebrew installed)",
                                title="Machine Cleanup",
                                expand=False,
                            ))
                        else:
                            # Actually remove stopped machines
                            scale_result = service.executor.scale_down_machines(
                                keep_count=1,
                                remove_stopped=True,
                            )
                            removed = scale_result.get("removed", [])
                            disk_freed = scale_result.get("disk_freed_gb", 0)

                            if removed:
                                console.print(Panel(
                                    f"Removed machines: {', '.join(removed)}\n"
                                    f"Estimated disk freed: {disk_freed:.1f} GB",
                                    title="Machine Cleanup",
                                    expand=False,
                                ))
                            else:
                                console.print(Panel(
                                    f"No machines were removed (they may be in use or protected).",
                                    title="Machine Cleanup",
                                    expand=False,
                                ))
                except Exception as exc:
                    console.print(f"[yellow]Machine cleanup failed: {exc}[/yellow]")

                request.auto_cleanup = True
                request.auto_cleanup_scale_down = True
                request.auto_cleanup_remove_machines = True
                continue

            if selection == "4":
                # Show disk space analysis to help users find what's using space
                try:
                    import subprocess
                    console.print("[dim]Analyzing disk usage...[/dim]")

                    # Find large directories in home folder
                    home = os.path.expanduser("~")
                    large_dirs = []

                    # Check common space hogs
                    check_paths = [
                        ("Trash", os.path.expanduser("~/.Trash")),
                        ("Downloads", os.path.expanduser("~/Downloads")),
                        ("Docker Desktop (if installed)", os.path.expanduser("~/Library/Containers/com.docker.docker")),
                        ("Xcode DerivedData", os.path.expanduser("~/Library/Developer/Xcode/DerivedData")),
                        ("Homebrew Cache", os.path.expanduser("~/Library/Caches/Homebrew")),
                        ("npm Cache", os.path.expanduser("~/.npm")),
                        ("pip Cache", os.path.expanduser("~/Library/Caches/pip")),
                        ("Podman Machines", os.path.expanduser("~/.local/share/containers/podman/machine")),
                        ("VS Code Cache", os.path.expanduser("~/Library/Application Support/Code/Cache")),
                        ("Browser Caches", os.path.expanduser("~/Library/Caches")),
                    ]

                    from .executors.podman import PodmanExecutor
                    if isinstance(service.executor, PodmanExecutor):
                        get_size = service.executor._get_dir_size
                    else:
                        def get_size(path):
                            total = 0
                            try:
                                for dp, dn, fn in os.walk(path):
                                    for f in fn:
                                        try:
                                            total += os.path.getsize(os.path.join(dp, f))
                                        except:
                                            pass
                            except:
                                pass
                            return total

                    for name, path in check_paths:
                        if os.path.exists(path):
                            size_bytes = get_size(path)
                            size_gb = size_bytes / (1024 ** 3)
                            if size_gb >= 0.1:  # Only show if >= 100MB
                                large_dirs.append((name, path, size_gb))

                    # Sort by size descending
                    large_dirs.sort(key=lambda x: x[2], reverse=True)

                    # Build report
                    lines = ["[bold]Potential space savings:[/bold]\n"]
                    total_potential = 0
                    for name, path, size_gb in large_dirs[:10]:
                        lines.append(f"  {size_gb:6.1f} GB - {name}")
                        total_potential += size_gb

                    if total_potential > 0:
                        lines.append(f"\n[bold]Total potential: {total_potential:.1f} GB[/bold]")
                        lines.append("\n[dim]Option 5 will automatically clean these (except Downloads)[/dim]")
                    else:
                        lines.append("\nNo large cleanable directories found.")
                        lines.append("Your disk may be full from other applications or system files.")

                    console.print(Panel("\n".join(lines), title="Disk Space Analysis", expand=False))
                except Exception as exc:
                    console.print(f"[yellow]Disk analysis failed: {exc}[/yellow]")
                continue

            if selection == "5":
                # Aggressive cleanup - run all available cleanup strategies
                console.print(Panel(
                    "[bold yellow]AGGRESSIVE CLEANUP[/bold yellow]\n\n"
                    "This will clean:\n"
                    "  • System Trash\n"
                    "  • Homebrew caches (brew cleanup --prune=all)\n"
                    "  • npm caches (npm cache clean --force)\n"
                    "  • pip caches (pip cache purge)\n"
                    "  • Xcode DerivedData\n"
                    "  • Docker data (if installed)\n"
                    "  • Container caches\n\n"
                    "[dim]This is safe but will require rebuilding some caches later.[/dim]",
                    title="⚠️  Aggressive Cleanup",
                    expand=False,
                ))
                if not Confirm.ask("Run aggressive host cleanup?", default=False):
                    continue
                try:
                    from .executors.podman import PodmanExecutor
                    if isinstance(service.executor, PodmanExecutor):
                        console.print("[dim]Running aggressive cleanup (this may take a minute)...[/dim]")
                        cleanup = service.executor.mitigate_host_resources(
                            dry_run=False,
                            clean_container_cache=True,
                            clean_tmp_files=True,
                            aggressive=True,
                            clean_homebrew=True,
                            clean_npm=True,
                            clean_pip=True,
                            clean_docker=True,
                            clean_trash=True,
                            clean_xcode=True,
                        )

                        # Build detailed report
                        details = cleanup.details or {}
                        report_lines = []

                        # Summarize what was cleaned
                        for category in ["trash", "homebrew", "npm", "pip", "xcode", "docker", "cache_dirs", "tmp_files"]:
                            items = details.get(category, [])
                            for item in items:
                                if item.get("size_freed_mb", 0) > 0.1:
                                    report_lines.append(f"  ✓ {item.get('action', category)}: {item['size_freed_mb']:.1f}MB freed")
                                elif item.get("success"):
                                    report_lines.append(f"  ✓ {item.get('action', category)}: cleaned")

                        if cleanup.host_space_reclaimed_mb > 0:
                            summary = (
                                f"[bold green]Aggressive cleanup reclaimed {cleanup.host_space_reclaimed_mb:.0f} MB[/bold green]\n\n"
                                + "\n".join(report_lines[:15])
                            )
                            if cleanup.errors:
                                summary += f"\n\n[yellow]Warnings: {len(cleanup.errors)}[/yellow]"
                        else:
                            summary = (
                                f"[yellow]Cleanup complete but freed minimal space.[/yellow]\n\n"
                                f"Your disk may be full from:\n"
                                f"  • Large files in ~/Downloads or ~/Documents\n"
                                f"  • Application data (check About This Mac > Storage)\n"
                                f"  • System files or Time Machine snapshots\n\n"
                                f"[dim]Consider using Disk Utility or a disk analyzer app.[/dim]"
                            )

                        console.print(Panel(summary, title="Aggressive Cleanup Results", expand=False))
                except Exception as exc:
                    console.print(f"[red]Aggressive cleanup failed: {exc}[/red]")
                continue

            if selection == "6":
                # Deep cleanup - VS Code caches, Podman cache, unused machines
                console.print(Panel(
                    "[bold cyan]DEEP CLEANUP[/bold cyan]\n\n"
                    "This will clean:\n"
                    "  • VS Code caches (workspaceStorage, History, logs) - often 2-4GB\n"
                    "  • Podman machine cache - often 500MB-1GB\n"
                    "  • Unused/stopped Podman machines - can be 1-10GB each\n\n"
                    "[yellow]Note:[/yellow] VS Code will rebuild caches on next launch.\n"
                    "[yellow]Note:[/yellow] Only stopped machines will be removed.",
                    title="🔍 Deep Cleanup",
                    expand=False,
                ))
                if not Confirm.ask("Run deep cleanup?", default=False):
                    continue
                try:
                    from .executors.podman import PodmanExecutor
                    if isinstance(service.executor, PodmanExecutor):
                        console.print("[dim]Running deep cleanup (VS Code, Podman cache, unused machines)...[/dim]")
                        cleanup = service.executor.mitigate_host_resources(
                            dry_run=False,
                            clean_container_cache=True,
                            clean_tmp_files=True,
                            aggressive=False,
                            clean_vscode=True,
                            clean_unused_machines=True,
                            clean_podman_cache=True,
                        )

                        # Build detailed report
                        details = cleanup.details or {}
                        report_lines = []

                        # Summarize what was cleaned
                        for item in details.get("vscode", []):
                            if item.get("size_freed_mb", 0) > 0.1:
                                path_short = os.path.basename(item.get("path", ""))
                                report_lines.append(f"  ✓ VS Code {path_short}: {item['size_freed_mb']:.1f}MB freed")

                        for item in details.get("podman_cache", []):
                            if item.get("size_freed_mb", 0) > 0.1:
                                report_lines.append(f"  ✓ Podman cache: {item['size_freed_mb']:.1f}MB freed")

                        for item in details.get("unused_machines", []):
                            if item.get("size_freed_mb", 0) > 0.1:
                                report_lines.append(f"  ✓ Removed machine '{item.get('machine')}': {item['size_freed_mb']:.1f}MB freed")

                        # Show Podman recovery status if it was attempted
                        recovery_info = details.get("podman_recovery", {})
                        if recovery_info.get("attempted"):
                            if recovery_info.get("success"):
                                report_lines.append(f"  ✓ Podman machine '{recovery_info.get('machine')}' restarted successfully")
                            else:
                                report_lines.append(f"  ⚠ Podman machine restart failed - may need manual restart")

                        if cleanup.host_space_reclaimed_mb > 0:
                            summary = (
                                f"[bold green]Deep cleanup reclaimed {cleanup.host_space_reclaimed_mb:.0f} MB ({cleanup.host_space_reclaimed_mb/1024:.2f} GB)[/bold green]\n\n"
                                + "\n".join(report_lines[:15])
                            )
                            if cleanup.errors:
                                summary += f"\n\n[yellow]Warnings: {len(cleanup.errors)}[/yellow]"
                        else:
                            summary = (
                                f"[yellow]Deep cleanup complete but freed minimal space.[/yellow]\n\n"
                                f"VS Code caches and Podman cache may already be minimal.\n"
                                f"No unused Podman machines found to remove."
                            )

                        console.print(Panel(summary, title="Deep Cleanup Results", expand=False))
                except Exception as exc:
                    console.print(f"[red]Deep cleanup failed: {exc}[/red]")
                continue

            if selection == "7":
                if not Confirm.ask(
                    "Proceed even though host resources are below threshold?",
                    default=False,
                ):
                    raise typer.Exit(1)
                request.auto_cleanup = True
                request.allow_host_resource_warning = True
                continue

            if selection == "8":
                if not Confirm.ask("Skip resource checks and proceed?", default=False):
                    raise typer.Exit(1)
                request.skip_resource_check = True
                continue

            if selection == "9":
                new_disk = Prompt.ask(
                    "Minimum host disk free (GB)",
                    default=str(request.min_disk_gb),
                )
                new_mem = Prompt.ask(
                    "Minimum host memory free (MB)",
                    default=str(int(request.min_memory_mb)),
                )
                try:
                    request.min_disk_gb = float(new_disk)
                    request.min_memory_mb = float(new_mem)
                except ValueError:
                    console.print("[red]Invalid thresholds; aborting.[/red]")
                    raise typer.Exit(1)
                continue

    if quiet:
        assert response is not None
        console.print(response.amp_run_id)
        return

    assert response is not None

    # Services were already health-checked during DAG-parallel apply; do one
    # quick verification to confirm nothing crashed immediately after startup.
    try:
        status_response = service.status(response.amp_run_id)
        all_healthy = all(
            check.status == "running"
            for check in status_response.checks
        )
        if not all_healthy:
            console.print("[yellow]⚠ Some services may still be starting[/yellow]")
    except Exception:
        pass  # Non-blocking

    # Display result
    console.print(Panel(
        f"[bold]Run ID:[/bold] {response.amp_run_id}\n"
        f"[bold]Action ID:[/bold] {response.action_id}",
        title="Apply Result",
        expand=False,
    ))

    if response.environment_outputs:
        table = Table(title="Environment Outputs")
        table.add_column("Key", style="cyan")
        table.add_column("Value", style="green")

        for key, value in response.environment_outputs.items():
            table.add_row(key, str(value)[:60])

        console.print(table)

    if response.status_stream_url:
        console.print(f"\n[dim]Status stream: {response.status_stream_url}[/dim]")


# =============================================================================
# Status Command
# =============================================================================

@app.command()
def status(
    run_id: str = typer.Argument(
        ...,
        help="BreakerAmp run ID to check",
    ),
    watch: bool = typer.Option(
        False,
        "--watch", "-w",
        help="Watch for status changes",
    ),
    json_output: bool = typer.Option(
        False,
        "--json", "-j",
        help="Output as JSON",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose", "-v",
        help="Show detailed resource insights",
    ),
) -> None:
    """Get the status of a run.

    Check the current status of an apply or destroy operation.
    """
    service = get_service()

    try:
        response = service.status(run_id)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Status check failed: {e}[/red]")
        raise typer.Exit(1)

    if json_output:
        console.print(response.model_dump_json(indent=2))
        return

    # Display status
    phase_colors = {
        "PLANNED": "yellow",
        "PROVISIONING": "blue",
        "APPLIED": "green",
        "DEGRADED": "yellow",
        "FAILED": "red",
        "DESTROYING": "orange",
        "DESTROYED": "dim",
    }
    phase_color = phase_colors.get(response.phase, "white")

    console.print(Panel(
        f"[bold]Run ID:[/bold] {response.amp_run_id}\n"
        f"[bold]Phase:[/bold] [{phase_color}]{response.phase}[/{phase_color}]\n"
        f"[bold]Progress:[/bold] {response.progress_pct}%",
        title="Run Status",
        expand=False,
    ))

    if response.checks:
        table = Table(title="Health Checks")
        table.add_column("Service", style="cyan")
        table.add_column("Status")
        table.add_column("Last Probe")

        status_colors = {
            "running": "green",
            "exited": "red",
            "stopped": "red",
            "removed": "dim",
            "paused": "yellow",
            "created": "yellow",
        }
        for check in response.checks:
            color = status_colors.get(check.status, "red")
            table.add_row(
                check.name,
                f"[{color}]{check.status}[/{color}]",
                check.last_probe.isoformat()[:19],
            )

        console.print(table)

    # Show resource insights
    try:
        executor = PodmanExecutor()
        resource_data = executor.get_resource_insights(verbose=verbose)
        if resource_data.get("summary"):
            console.print()
            console.print(Panel(
                resource_data["summary"],
                title="Resource Status",
                expand=False,
            ))
    except Exception:
        pass  # Skip insights if unavailable


# =============================================================================
# Destroy Command
# =============================================================================

@app.command()
def destroy(
    run_id: str = typer.Argument(
        ...,
        help="Run ID to destroy",
    ),
    reason: str = typer.Option(
        "manual cleanup",
        "--reason", "-r",
        help="Reason for destruction",
    ),
    cascade: bool = typer.Option(
        True,
        "--cascade/--no-cascade",
        help="Cascade to dependent resources",
    ),
    force: bool = typer.Option(
        False,
        "--force", "-f",
        help="Force destroy without confirmation",
    ),
    interactive: bool = typer.Option(
        False,
        "--interactive/--no-interactive",
        help="Require interactive confirmation prompt (default: disabled)",
    ),
    force_podman: bool = typer.Option(
        False,
        "--force-podman",
        help="Skip Podman machine checks/warnings",
    ),
    cleanup_after_destroy: bool = typer.Option(
        True,
        "--cleanup/--no-cleanup",
        help="Run resource cleanup after destroying containers (default: enabled)",
    ),
    cleanup_aggressive: bool = typer.Option(
        True,
        "--cleanup-aggressive/--no-cleanup-aggressive",
        help="Use aggressive cleanup including dangling images/cache (default: enabled)",
    ),
    cleanup_volumes: bool = typer.Option(
        False,
        "--cleanup-volumes",
        help="Include volumes in cleanup (WARNING: may lose data)",
    ),
) -> None:
    """Destroy an environment.

    Tears down all resources associated with an environment.
    By default, post-destroy cleanup is enabled to reclaim disk space.
    """
    service = get_service()

    # Confirmation
    if not force:
        if not interactive:
            console.print("[red]Refusing to prompt in non-interactive mode.[/red]")
            console.print("[dim]Use --force to destroy without confirmation, or --interactive to confirm.[/dim]")
            raise typer.Exit(2)
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            console.print("[red]--interactive requires an interactive TTY (stdin/stdout).[/red]")
            raise typer.Exit(2)
        if not typer.confirm(f"Destroy run {run_id}?"):
            console.print("[yellow]Cancelled[/yellow]")
            raise typer.Exit(0)

    request = DestroyRequest(
        amp_run_id=run_id,
        cascade=cascade,
        reason=reason,
        force_podman=force_podman,
        cleanup_after_destroy=cleanup_after_destroy,
        cleanup_aggressive=cleanup_aggressive,
        cleanup_include_volumes=cleanup_volumes,
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task("Destroying...", total=None)

        try:
            response = service.destroy(request)
        except Exception as e:
            console.print(f"[red]Destroy failed: {e}[/red]")
            raise typer.Exit(1)

    console.print(Panel(
        f"[bold]Action ID:[/bold] {response.action_id}\n"
        f"[bold]Destroyed:[/bold] {len(response.teardown_report)} resources",
        title="Destroy Result",
        expand=False,
    ))

    if response.teardown_report:
        for item in response.teardown_report[:10]:
            console.print(f"  [dim]✓ {item}[/dim]")
        if len(response.teardown_report) > 10:
            console.print(f"  [dim]... and {len(response.teardown_report) - 10} more[/dim]")


# =============================================================================
# Restart Command
# =============================================================================

@app.command()
def restart(
    run_id: Optional[str] = typer.Argument(
        None,
        help="Run ID to restart (defaults to most recent active environment)",
    ),
    services: Optional[List[str]] = typer.Option(
        None,
        "--service", "-s",
        help="Specific service(s) to restart (can specify multiple times)",
    ),
    all_services: bool = typer.Option(
        False,
        "--all", "-a",
        help="Restart all services in the environment",
    ),
    force: bool = typer.Option(
        False,
        "--force", "-f",
        help="Force restart (stop + start) even if container is healthy",
    ),
    json_output: bool = typer.Option(
        False,
        "--json", "-j",
        help="Output as JSON",
    ),
) -> None:
    """Restart containers in an environment.

    By default, restarts only containers that are not healthy or have been
    updated. Use --all to restart everything, or --service to target specific
    services.

    If no run_id is specified, uses the most recent active environment.

    Examples:
        breakeramp restart                      # Restart unhealthy containers in latest env
        breakeramp restart --all                # Restart all containers in latest env
        breakeramp restart -s postgres-amprealize  # Restart specific service
        breakeramp restart amp-abc123 --force   # Force restart all in specific env
    """
    import subprocess

    service = get_service()

    # Find the run to restart
    target_run_id = run_id
    if not target_run_id:
        # Find most recent active environment by file modification time
        # Include STOPPED environments since restart can bring them back
        envs = list(service.environments_dir.glob("*.json"))
        active_runs = []
        for env_file in envs:
            try:
                with open(env_file) as f:
                    data = json.load(f)
                if data.get("phase") in ("APPLIED", "PROVISIONING", "DEGRADED", "STOPPED"):
                    mtime = env_file.stat().st_mtime
                    active_runs.append((env_file.stem, data, mtime))
            except Exception:
                pass

        if not active_runs:
            console.print("[yellow]No active environments found[/yellow]")
            console.print("[dim]Run 'breakeramp plan <environment>' to create one[/dim]")
            raise typer.Exit(1)

        # Sort by modification time (most recent first)
        active_runs.sort(key=lambda x: x[2], reverse=True)
        target_run_id = active_runs[0][0]
        console.print(f"[dim]Using most recent environment: {target_run_id}[/dim]")

    # Load environment manifest
    env_path = service.environments_dir / f"{target_run_id}.json"
    if not env_path.exists():
        console.print(f"[red]Environment {target_run_id} not found[/red]")
        raise typer.Exit(1)

    with open(env_path) as f:
        run_data = json.load(f)

    runtime = run_data.get("runtime", {})
    executor = PodmanExecutor(connection=runtime.get("podman_connection"))
    if not executor.connection:
        machine_name = runtime.get("podman_machine")
        if machine_name:
            executor.connection = executor.resolve_connection_for_machine(machine_name)

    podman_cmd = ["podman"]
    if executor.connection:
        podman_cmd.extend(["--connection", executor.connection])

    outputs = run_data.get("environment_outputs", {})
    if not outputs:
        console.print(f"[yellow]No services found in environment {target_run_id}[/yellow]")
        raise typer.Exit(1)

    runtime = run_data.get("runtime", {})
    executor = PodmanExecutor(connection=runtime.get("podman_connection"))
    if not executor.connection:
        machine_name = runtime.get("podman_machine")
        if machine_name:
            executor.connection = executor.resolve_connection_for_machine(machine_name)

    podman_cmd = ["podman"]
    if executor.connection:
        podman_cmd.extend(["--connection", executor.connection])

    # Determine which services to restart
    target_services = []
    if services:
        # Specific services requested
        for svc in services:
            if svc in outputs:
                target_services.append(svc)
            else:
                console.print(f"[yellow]Service '{svc}' not found in environment[/yellow]")
    elif all_services or force:
        # Restart all services
        target_services = list(outputs.keys())
    else:
        # Smart restart: only unhealthy or stopped containers
        for svc_name, svc_info in outputs.items():
            container_id = svc_info.get("container_id")
            if container_id:
                try:
                    info = executor.inspect_container(container_id)
                    if info.status != "running" or (info.health and info.health != "healthy"):
                        target_services.append(svc_name)
                except Exception:
                    # Container doesn't exist or error - needs restart
                    target_services.append(svc_name)

    if not target_services:
        console.print("[green]✓ All services are healthy - nothing to restart[/green]")
        if json_output:
            console.print(json.dumps({"restarted": [], "status": "healthy"}))
        return

    # First, check if containers actually exist
    missing_containers = []
    existing_containers = []
    for svc_name in target_services:
        svc_info = outputs.get(svc_name, {})
        container_id = svc_info.get("container_id")
        if container_id:
            check = subprocess.run(
                podman_cmd + ["container", "exists", container_id],
                capture_output=True,
            )
            if check.returncode != 0:
                missing_containers.append(svc_name)
            else:
                existing_containers.append(svc_name)
        else:
            missing_containers.append(svc_name)

    # If all containers are missing, suggest using 'up' instead
    if missing_containers and not existing_containers:
        console.print("[yellow]⚠ All containers have been removed[/yellow]")
        console.print(
            "[dim]Environment manifest exists but containers were deleted (e.g., by 'breakeramp nuke')[/dim]"
        )
        console.print()
        console.print("[bold]To recreate the environment:[/bold]")
        blueprint = run_data.get("blueprint_name", "development")
        # Simplify suggestion - 'development' is the default so no arg needed
        if blueprint == "development":
            console.print("  [cyan]breakeramp up[/cyan]")
        else:
            console.print(f"  [cyan]breakeramp up {blueprint}[/cyan]")
        console.print()
        console.print("[dim]Or to start fresh:[/dim]")
        if blueprint == "development":
            console.print("  [dim]breakeramp plan && breakeramp apply <plan-id>[/dim]")
        else:
            console.print(f"  [dim]breakeramp plan {blueprint} && breakeramp apply <plan-id>[/dim]")
        if json_output:
            console.print(
                json.dumps(
                    {
                        "error": "containers_missing",
                        "missing": missing_containers,
                        "suggestion": "breakeramp up" if blueprint == "development" else f"breakeramp up {blueprint}",
                    }
                )
            )
        raise typer.Exit(1)

    # If some containers are missing, warn but continue with existing ones
    if missing_containers:
        console.print(f"[yellow]⚠ {len(missing_containers)} container(s) no longer exist:[/yellow]")
        for svc in missing_containers:
            console.print(f"  [dim]• {svc}[/dim]")
        console.print(f"[dim]Continuing with {len(existing_containers)} existing container(s)...[/dim]")
        console.print()
        target_services = existing_containers

    results = {"restarted": [], "failed": [], "skipped": [], "missing": missing_containers}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Restarting services...", total=len(target_services))
        for svc_name in target_services:
            progress.update(task, description=f"Restarting {svc_name}...")
            svc_info = outputs.get(svc_name, {})
            container_id = svc_info.get("container_id")

            if not container_id:
                results["skipped"].append({"service": svc_name, "reason": "no container_id"})
                progress.advance(task)
                continue

            try:
                # Stop container
                try:
                    subprocess.run(
                        podman_cmd + ["stop", "-t", "10", container_id],
                        capture_output=True,
                        timeout=30,
                    )
                except Exception:
                    pass  # Container might already be stopped

                # Start container
                result = subprocess.run(
                    podman_cmd + ["start", container_id],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

                if result.returncode == 0:
                    results["restarted"].append(svc_name)
                else:
                    results["failed"].append(
                        {
                            "service": svc_name,
                            "error": result.stderr.strip() or "Unknown error",
                        }
                    )
            except Exception as e:
                results["failed"].append({"service": svc_name, "error": str(e)})

            progress.advance(task)

    # Update manifest phase back to APPLIED if we successfully restarted containers
    if results["restarted"] and not results["failed"]:
        if run_data.get("phase") == "STOPPED":
            run_data["phase"] = "APPLIED"
            with open(env_path, "w") as f:
                json.dump(run_data, f, indent=2, default=str)

    if json_output:
        console.print(json.dumps(results, indent=2))
        return

    # Display results
    if results["restarted"]:
        console.print(f"[green]✓ Restarted {len(results['restarted'])} service(s):[/green]")
        for svc in results["restarted"]:
            console.print(f"  [dim]• {svc}[/dim]")

    if results["failed"]:
        console.print(f"[red]✗ Failed to restart {len(results['failed'])} service(s):[/red]")
        for item in results["failed"]:
            console.print(f"  [red]• {item['service']}: {item['error']}[/red]")

    if results["skipped"]:
        console.print(f"[yellow]⊘ Skipped {len(results['skipped'])} service(s)[/yellow]")


# =============================================================================
# Stop Command
# =============================================================================

@app.command()
def stop(
    run_id: Optional[str] = typer.Argument(
        None,
        help="Run ID to stop (defaults to most recent active environment)",
    ),
    services: Optional[List[str]] = typer.Option(
        None,
        "--service", "-s",
        help="Specific service(s) to stop (can specify multiple times)",
    ),
    timeout: int = typer.Option(
        10,
        "--timeout", "-t",
        help="Seconds to wait for graceful stop before killing",
    ),
    json_output: bool = typer.Option(
        False,
        "--json", "-j",
        help="Output as JSON",
    ),
) -> None:
    """Stop containers in an environment without removing them.

    Containers are stopped gracefully (SIGTERM, then SIGKILL after timeout).
    The environment manifest is preserved, so you can use 'breakeramp restart'
    to bring the containers back up.

    For full cleanup (remove containers), use 'breakeramp nuke' instead.

    Examples:
        breakeramp stop                      # Stop all containers in latest env
        breakeramp stop amp-abc123           # Stop all containers in specific env
        breakeramp stop -s postgres-amprealize  # Stop specific service
    """
    import subprocess

    service = get_service()

    # Find the run to stop
    target_run_id = run_id
    if not target_run_id:
        # Find most recent active environment by file modification time
        envs = list(service.environments_dir.glob("*.json"))
        active_runs = []
        for env_file in envs:
            try:
                with open(env_file) as f:
                    data = json.load(f)
                if data.get("phase") in ("APPLIED", "PROVISIONING", "DEGRADED"):
                    mtime = env_file.stat().st_mtime
                    active_runs.append((env_file.stem, data, mtime))
            except Exception:
                pass

        if not active_runs:
            console.print("[yellow]No active environments found[/yellow]")
            console.print("[dim]Nothing to stop[/dim]")
            raise typer.Exit(0)

        # Sort by modification time (most recent first)
        active_runs.sort(key=lambda x: x[2], reverse=True)
        target_run_id = active_runs[0][0]
        console.print(f"[dim]Using most recent environment: {target_run_id}[/dim]")

    # Load environment manifest
    env_path = service.environments_dir / f"{target_run_id}.json"
    if not env_path.exists():
        console.print(f"[red]Environment {target_run_id} not found[/red]")
        raise typer.Exit(1)

    with open(env_path) as f:
        run_data = json.load(f)

    # Build podman command with connection info from runtime
    runtime = run_data.get("runtime", {})
    executor = PodmanExecutor(connection=runtime.get("podman_connection"))
    if not executor.connection:
        machine_name = runtime.get("podman_machine")
        if machine_name:
            executor.connection = executor.resolve_connection_for_machine(machine_name)

    podman_cmd = ["podman"]
    if executor.connection:
        podman_cmd.extend(["--connection", executor.connection])

    outputs = run_data.get("environment_outputs", {})
    if not outputs:
        console.print(f"[yellow]No services found in environment {target_run_id}[/yellow]")
        raise typer.Exit(0)

    # Determine which services to stop
    target_services = []
    if services:
        # Specific services requested
        for svc in services:
            if svc in outputs:
                target_services.append(svc)
            else:
                console.print(f"[yellow]Service '{svc}' not found in environment[/yellow]")
    else:
        # Stop all services
        target_services = list(outputs.keys())

    if not target_services:
        console.print("[yellow]No services to stop[/yellow]")
        raise typer.Exit(0)

    # Check which containers exist and their current state
    containers_to_stop = []
    already_stopped = []
    missing_containers = []

    for svc_name in target_services:
        svc_info = outputs.get(svc_name, {})
        container_id = svc_info.get("container_id")
        if not container_id:
            missing_containers.append(svc_name)
            continue

        # Check if container exists
        check = subprocess.run(
            podman_cmd + ["container", "exists", container_id],
            capture_output=True,
        )
        if check.returncode != 0:
            missing_containers.append(svc_name)
            continue

        # Check if container is running
        inspect = subprocess.run(
            podman_cmd + ["inspect", "--format", "{{.State.Running}}", container_id],
            capture_output=True,
            text=True,
        )
        is_running = inspect.stdout.strip().lower() == "true"

        if is_running:
            containers_to_stop.append((svc_name, container_id))
        else:
            already_stopped.append(svc_name)

    # Report missing containers
    if missing_containers:
        console.print(f"[yellow]⚠ {len(missing_containers)} container(s) do not exist:[/yellow]")
        for svc in missing_containers:
            console.print(f"  [dim]• {svc}[/dim]")
        console.print()

    # Report already stopped
    if already_stopped and not json_output:
        console.print(f"[dim]Already stopped: {', '.join(already_stopped)}[/dim]")

    if not containers_to_stop:
        if json_output:
            console.print(json.dumps({
                "stopped": [],
                "already_stopped": already_stopped,
                "missing": missing_containers,
            }))
        else:
            console.print("[green]✓ All containers are already stopped[/green]")
            console.print("[dim]Use 'breakeramp restart' to start them again[/dim]")
        return

    results = {"stopped": [], "failed": [], "already_stopped": already_stopped, "missing": missing_containers}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Stopping services...", total=len(containers_to_stop))

        for svc_name, container_id in containers_to_stop:
            progress.update(task, description=f"Stopping {svc_name}...")

            try:
                result = subprocess.run(
                    podman_cmd + ["stop", "-t", str(timeout), container_id],
                    capture_output=True,
                    text=True,
                    timeout=timeout + 15,  # Allow extra time for podman
                )

                if result.returncode == 0:
                    results["stopped"].append(svc_name)
                else:
                    results["failed"].append({
                        "service": svc_name,
                        "error": result.stderr.strip() or "Unknown error",
                    })
            except subprocess.TimeoutExpired:
                # Force kill if stop times out
                subprocess.run(podman_cmd + ["kill", container_id], capture_output=True)
                results["stopped"].append(svc_name)
            except Exception as e:
                results["failed"].append({"service": svc_name, "error": str(e)})

            progress.advance(task)

    # Update manifest phase to STOPPED (optional - allows tracking stopped state)
    if results["stopped"] and not results["failed"]:
        # Check if all containers are now stopped
        all_stopped = (len(results["stopped"]) + len(already_stopped)) == len([
            s for s in outputs.keys() if outputs[s].get("container_id")
        ])
        if all_stopped:
            run_data["phase"] = "STOPPED"
            with open(env_path, "w") as f:
                json.dump(run_data, f, indent=2, default=str)

    if json_output:
        console.print(json.dumps(results, indent=2))
        return

    # Display results
    if results["stopped"]:
        console.print(f"[green]✓ Stopped {len(results['stopped'])} service(s):[/green]")
        for svc in results["stopped"]:
            console.print(f"  [dim]• {svc}[/dim]")

    if results["failed"]:
        console.print(f"[red]✗ Failed to stop {len(results['failed'])} service(s):[/red]")
        for item in results["failed"]:
            console.print(f"  [red]• {item['service']}: {item['error']}[/red]")

    console.print()
    console.print("[dim]Containers preserved. Use 'breakeramp restart' to start them again.[/dim]")


# =============================================================================
# Up Command (convenience: plan + apply in one step)
# =============================================================================

@app.command()
def up(
    environment: str = typer.Argument(
        "development",
        help="Environment name (default: 'development')",
    ),
    blueprint: Optional[str] = typer.Option(
        None,
        "--blueprint", "-b",
        help="Blueprint ID to plan (e.g., 'core-data-plane')",
    ),
    force: bool = typer.Option(
        False,
        "--force", "-f",
        help="Force recreation even if environment exists",
    ),
    skip_resource_check: bool = typer.Option(
        False,
        "--skip-resource-check", "-S",
        help="Skip resource availability checks (proceed despite disk/memory warnings)",
    ),
    auto_cleanup: bool = typer.Option(
        False,
        "--auto-cleanup", "-c",
        help="Automatically clean up resources if disk/memory is low",
    ),
    rebuild_images: bool = typer.Option(
        False,
        "--rebuild-images", "-R",
        help="Force rebuild of local images (ensures latest code is used)",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet", "-q",
        help="Minimal output",
    ),
) -> None:
    """Bring up an environment (combines plan + apply).

    This is a convenience command that plans and applies in one step.
    If an active environment already exists, it will be reused unless --force is specified.

    Examples:
        breakeramp up                           # Bring up default development env
        breakeramp up development -b core-data-plane  # Specific blueprint
        breakeramp up --force                   # Force recreate
        breakeramp up --skip-resource-check    # Ignore disk/memory warnings
        breakeramp up --auto-cleanup           # Auto-cleanup if resources low
        breakeramp up --rebuild-images         # Rebuild local images with latest code
    """
    import subprocess

    # Apply amprealize context to get DATABASE_URL and other DSNs
    ctx_name = _apply_amprealize_context(quiet=quiet)

    service = get_service()

    # Warn (and offer to switch) when cloud context + local-DB blueprint
    mismatch = _check_context_blueprint_mismatch(ctx_name, environment, service, blueprint)
    if mismatch:
        warning_msg, suggested_env = mismatch
        console.print(f"[yellow]⚠ {warning_msg}[/yellow]")
        console.print()
        if typer.confirm(f"Switch to '{suggested_env}' environment instead?", default=True):
            environment = suggested_env
            blueprint = None
            console.print(f"[green]→ Switched to '{environment}'[/green]")
            console.print()

    # Check for existing active environment with running containers
    if not force:
        envs = list(service.environments_dir.glob("*.json"))
        active_envs = []
        for env_file in envs:
            try:
                with open(env_file) as f:
                    data = json.load(f)
                if data.get("phase") in ("APPLIED", "PROVISIONING"):
                    mtime = env_file.stat().st_mtime
                    active_envs.append((env_file.stem, data, mtime))
            except Exception:
                pass

        # Sort by modification time (most recent first)
        active_envs.sort(key=lambda x: x[2], reverse=True)

        # Check if the most recent active env has running containers
        for run_id, data, _ in active_envs:
            outputs = data.get("environment_outputs", {})
            if outputs:
                # Check if at least one container exists
                container_exists = False
                for svc_info in outputs.values():
                    cid = svc_info.get("container_id")
                    if cid:
                        check = subprocess.run(
                            ["podman", "container", "exists", cid],
                            capture_output=True,
                        )
                        if check.returncode == 0:
                            container_exists = True
                            break

                if container_exists:
                    if not quiet:
                        console.print(f"[green]✓ Environment already active: {run_id}[/green]")
                        console.print("[dim]Use --force to recreate, or 'breakeramp restart' to restart services[/dim]")
                    return

    # Plan
    if not quiet:
        console.print(f"[dim]Planning environment '{environment}'...[/dim]")

    from .models import PlanRequest
    plan_req = PlanRequest(
        environment=environment,
        blueprint=blueprint,
    )

    try:
        plan_response = service.plan(plan_req)
    except Exception as e:
        console.print(f"[red]Plan failed: {e}[/red]")
        raise typer.Exit(1)

    if not quiet:
        console.print(f"[dim]Plan created: {plan_response.plan_id}[/dim]")
        console.print(f"[dim]Applying...[/dim]")

    # Apply
    from .models import ApplyRequest
    apply_req = ApplyRequest(
        plan_id=plan_response.plan_id,
        watch=True,
        skip_resource_check=skip_resource_check,
        auto_cleanup=auto_cleanup,
        rebuild_images=rebuild_images,
    )

    display = LiveProgressDisplay(console=console, quiet=quiet)
    try:
        with display:
            display.on_phase("apply", f"Bringing up '{environment}'")
            apply_response = service.apply(apply_req, progress=display)
    except Exception as e:
        console.print(f"[red]Apply failed: {e}[/red]")
        raise typer.Exit(1)

    if apply_response:
        display.print_summary(amp_run_id=apply_response.amp_run_id)

    # Check if all containers are running
    all_running = all(
        svc.get("status") == "running"
        for svc in apply_response.environment_outputs.values()
    )

    if all_running:
        if not quiet:
            console.print(f"[green]✓ Environment ready: {apply_response.amp_run_id}[/green]")

            # Show connection info
            if apply_response.environment_outputs:
                console.print()
                for svc_name, svc_info in apply_response.environment_outputs.items():
                    host = svc_info.get("host", "localhost")
                    port = svc_info.get("port")
                    if port:
                        console.print(f"  [cyan]{svc_name}:[/cyan] {host}:{port}")
    else:
        console.print(f"[yellow]⚠ Some services may not be running[/yellow]")
        for svc_name, svc_info in apply_response.environment_outputs.items():
            status = svc_info.get("status", "unknown")
            icon = "✓" if status == "running" else "✗"
            color = "green" if status == "running" else "yellow"
            console.print(f"  [{color}]{icon} {svc_name}: {status}[/{color}]")
        raise typer.Exit(1)


# =============================================================================
# List Command
# =============================================================================

@app.command("list")
def list_environments(
    json_output: bool = typer.Option(
        False,
        "--json", "-j",
        help="Output as JSON",
    ),
    no_reconcile: bool = typer.Option(
        False,
        "--no-reconcile",
        help="Skip container reality check (faster but may show stale entries)",
    ),
    keep_stale: bool = typer.Option(
        False,
        "--keep-stale",
        help="Don't auto-remove stale state files for missing containers",
    ),
) -> None:
    """List active environments.

    Shows all environments currently deployed or in progress.
    By default, reconciles with actual container state and removes stale entries.
    """
    service = get_service()

    try:
        environments = service.list_environments(
            reconcile=not no_reconcile,
            auto_cleanup=not keep_stale,
        )
    except Exception as e:
        console.print(f"[red]List failed: {e}[/red]")
        raise typer.Exit(1)

    if json_output:
        console.print(json.dumps(environments, indent=2))
        return

    if not environments:
        console.print("[dim]No active environments[/dim]")
        return

    table = Table(title="Active Environments")
    table.add_column("Run ID", style="cyan")
    table.add_column("Environment", style="green")
    table.add_column("Phase")
    table.add_column("Blueprint")
    table.add_column("Created")
    # Show actual status columns when reconciling
    if not no_reconcile:
        table.add_column("Containers", justify="right")
        table.add_column("Health")

    for env in environments:
        phase_colors = {
            "PLANNED": "yellow",
            "PROVISIONING": "blue",
            "APPLIED": "green",
            "FAILED": "red",
        }
        phase = env.get("phase", "unknown")
        phase_styled = f"[{phase_colors.get(phase, 'white')}]{phase}[/{phase_colors.get(phase, 'white')}]"

        run_id = env.get("amp_run_id", "")
        display_id = run_id[:12] + "..." if len(run_id) > 12 else run_id

        row = [
            display_id,
            env.get("environment", ""),
            phase_styled,
            env.get("blueprint_id", ""),
            (env.get("created_at", "") or "")[:19],
        ]

        if not no_reconcile:
            container_count = env.get("container_count", 0)
            running_count = env.get("running_count", 0)
            actual_status = env.get("actual_status", "")

            # Show running/total counts
            if actual_status == "STALE":
                row.append("[red]0[/red]")
                row.append("[red]STALE[/red]")
            elif actual_status == "STOPPED":
                row.append(f"[red]0/{container_count}[/red]")
                row.append("[red]STOPPED[/red]")
            elif actual_status == "DEGRADED":
                row.append(f"[yellow]{running_count}/{container_count}[/yellow]")
                row.append("[yellow]DEGRADED[/yellow]")
            elif actual_status == "RUNNING":
                row.append(f"[green]{running_count}/{container_count}[/green]")
                row.append("[green]HEALTHY[/green]")
            else:
                row.append(str(container_count))
                row.append("[dim]UNKNOWN[/dim]")

        table.add_row(*row)

    console.print(table)


# =============================================================================
# Blueprints Command
# =============================================================================

@app.command()
def blueprints(
    json_output: bool = typer.Option(
        False,
        "--json", "-j",
        help="Output as JSON",
    ),
) -> None:
    """List available blueprints.

    Shows both built-in and user-defined blueprints.
    """
    service = get_service()

    try:
        bps = service.list_blueprints()
    except Exception as e:
        console.print(f"[red]List failed: {e}[/red]")
        raise typer.Exit(1)

    if json_output:
        console.print(json.dumps(bps, indent=2))
        return

    if not bps:
        console.print("[dim]No blueprints found[/dim]")
        return

    table = Table(title="Available Blueprints")
    table.add_column("ID", style="cyan")
    table.add_column("Source", style="green")
    table.add_column("Path")

    for bp in bps:
        table.add_row(
            bp.get("id", ""),
            bp.get("source", ""),
            bp.get("path", ""),
        )

    console.print(table)


# =============================================================================
# Configure Command
# =============================================================================

@app.command()
def configure(
    path: Path = typer.Argument(
        Path("./config/breakeramp"),
        help="Directory to configure",
    ),
    include_blueprints: bool = typer.Option(
        False,
        "--blueprints", "-b",
        help="Include packaged blueprints",
    ),
    force: bool = typer.Option(
        False,
        "--force", "-f",
        help="Overwrite existing files",
    ),
) -> None:
    """Configure BreakerAmp in a directory.

    Creates environment templates and optionally copies blueprints to
    help you get started quickly.
    """
    service = get_service()

    try:
        result = service.configure(
            config_dir=path,
            include_blueprints=include_blueprints,
            force=force,
        )
    except Exception as e:
        console.print(f"[red]Configure failed: {e}[/red]")
        raise typer.Exit(1)

    console.print(Panel(
        f"[bold]Environment file:[/bold] {result['environment_file']} ({result['environment_status']})",
        title="Configuration Complete",
        expand=False,
    ))

    if result.get("blueprints"):
        table = Table(title="Blueprints")
        table.add_column("Blueprint", style="cyan")
        table.add_column("Status", style="green")

        for bp in result["blueprints"]:
            table.add_row(bp.get("blueprint", ""), bp.get("status", ""))

        console.print(table)

    console.print()
    console.print("[dim]Edit the environment file to customize your setup[/dim]")


# =============================================================================
# Resources Command
# =============================================================================

@app.command()
def resources(
    machine: Optional[str] = typer.Option(
        None,
        "--machine", "-m",
        help="Podman machine name (uses default if not specified)",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose", "-v",
        help="Show detailed resource information",
    ),
    json_output: bool = typer.Option(
        False,
        "--json", "-j",
        help="Output as JSON",
    ),
) -> None:
    """Show resource status with plain-English insights.

    Displays current resource utilization (memory, disk, CPU) with
    human-readable status messages like "plenty of memory" or
    "nearing capacity".

    Configure thresholds via environment variables:
        BREAKERAMP_INSIGHT_MEMORY_WARNING=70
        BREAKERAMP_INSIGHT_MEMORY_CRITICAL=90
    """
    executor = PodmanExecutor()

    try:
        resource_data = executor.get_resource_insights(
            machine_name=machine,
            verbose=verbose,
        )
    except Exception as e:
        console.print(f"[red]Failed to get resources: {e}[/red]")
        raise typer.Exit(1)

    if json_output:
        import json as json_module
        console.print(json_module.dumps(resource_data, indent=2, default=str))
        return

    # Show raw metrics first if verbose
    if verbose:
        resources_dict = resource_data.get("resources", {})
        metrics_table = Table(title="Resource Metrics")
        metrics_table.add_column("Metric", style="cyan")
        metrics_table.add_column("Value", style="green")
        metrics_table.add_column("Total", style="dim")

        if resources_dict.get("memory_total_mb"):
            used = resources_dict.get("memory_used_mb", 0)
            total = resources_dict.get("memory_total_mb", 0)
            pct = (used / total * 100) if total > 0 else 0
            metrics_table.add_row(
                "Memory",
                f"{used:.0f} MB ({pct:.1f}%)",
                f"{total:.0f} MB",
            )

        if resources_dict.get("disk_total_mb"):
            used = resources_dict.get("disk_used_mb", 0)
            total = resources_dict.get("disk_total_mb", 0)
            pct = (used / total * 100) if total > 0 else 0
            metrics_table.add_row(
                "Disk",
                f"{used:.0f} MB ({pct:.1f}%)",
                f"{total:.0f} MB",
            )

        if resources_dict.get("cpu_cores"):
            metrics_table.add_row(
                "CPU Cores",
                str(resources_dict.get("cpu_cores", 0)),
                "-",
            )

        console.print(metrics_table)
        console.print()

    # Show insights summary
    summary = resource_data.get("summary", "")
    if summary:
        console.print(Panel(
            summary,
            title="Resource Status",
            expand=False,
        ))
    else:
        console.print("[dim]No resource data available. Is Podman machine running?[/dim]")

    # Hint about threshold configuration
    if not json_output:
        console.print()
        console.print("[dim]Configure thresholds with BREAKERAMP_INSIGHT_* env vars[/dim]")


# =============================================================================
# Cleanup Command
# =============================================================================

@app.command()
def cleanup(
    aggressive: bool = typer.Option(
        False,
        "--aggressive", "-a",
        help="Remove unused images and build cache in addition to containers/volumes",
    ),
    include_volumes: bool = typer.Option(
        True,
        "--include-volumes/--no-volumes",
        help="Remove anonymous (hash-named) volumes not attached to running containers (default: on)",
    ),
    include_images: bool = typer.Option(
        False,
        "--include-images", "-i",
        help="Remove images not referenced by any container",
    ),
    include_stale_state: bool = typer.Option(
        False,
        "--include-stale-state", "-s",
        help="Remove stale state files (environments, manifests, snapshots) for non-running environments",
    ),
    scaledown_machines: bool = typer.Option(
        False,
        "--scaledown-machines",
        help="Stop unused Podman machines (macOS/Windows only)",
    ),
    remove_machines: bool = typer.Option(
        False,
        "--remove-machines",
        help="Remove unused machines after stopping (WARNING: requires rebuild)",
    ),
    preserve_machines: Optional[List[str]] = typer.Option(
        None,
        "--preserve-machine", "-p",
        help="Machine names to never stop/remove (can specify multiple times)",
    ),
    preserve_environments: Optional[List[str]] = typer.Option(
        None,
        "--preserve-env", "-e",
        help="Environment run IDs to preserve (can specify multiple times, partial IDs work)",
    ),
    preserve_volumes: Optional[List[str]] = typer.Option(
        None,
        "--preserve-volume",
        help="Additional volume name patterns to preserve (can specify multiple times)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run", "-n",
        help="Show what would be cleaned without actually doing it",
    ),
    json_output: bool = typer.Option(
        False,
        "--json", "-j",
        help="Output as JSON",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet", "-q",
        help="Minimal output",
    ),
) -> None:
    """Clean up stale container resources to free disk space.

    This is the safe middle-ground between doing nothing and 'breakeramp nuke'.
    By default it removes dead/exited containers and anonymous (hash-named)
    volumes while preserving all named database volumes, pip/node caches,
    and anything attached to running containers.

    Use --aggressive to also remove unused images and build cache.
    Use --include-stale-state to remove orphaned state files.

    Database and backup volumes are ALWAYS preserved, even with --aggressive.

    Examples:
        breakeramp cleanup                    # Remove dead containers + anonymous volumes
        breakeramp cleanup --dry-run          # Preview what would be cleaned
        breakeramp cleanup --aggressive       # Also remove unused images + build cache
        breakeramp cleanup -a -s              # Aggressive + clean stale state
        breakeramp cleanup --no-volumes       # Only clean dead containers
        breakeramp cleanup --include-images   # Also remove unused images
        breakeramp cleanup --preserve-volume mydata  # Extra volume pattern to protect
        breakeramp cleanup -s --preserve-env amp-abc123  # Clean state but keep specific env
        breakeramp cleanup --scaledown-machines --preserve-machine default
    """
    import subprocess
    import re

    executor = PodmanExecutor()

    # Aggressive enables images + build cache
    if aggressive:
        include_images = True

    # --- Phase 1: Smart cleanup via executor (containers, volumes, images, cache) ---
    smart_result = executor.smart_cleanup(
        dry_run=dry_run,
        remove_dead_containers=True,
        remove_anonymous_volumes=include_volumes,
        remove_unused_images=include_images,
        prune_build_cache=aggressive,
        preserve_volume_patterns=preserve_volumes,
    )

    # --- Phase 2: Stale state files (same logic as before) ---
    stale_state_to_remove: Dict[str, List[Path]] = {
        "environments": [],
        "manifests": [],
        "snapshots": [],
    }
    running_env_ids: set = set()
    most_recent_env_id: Optional[str] = None

    if include_stale_state:
        try:
            result = subprocess.run(
                ["podman", "ps", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            for line in result.stdout.strip().split("\n"):
                if line.startswith("amp-"):
                    match = re.match(r"(amp-[a-f0-9-]{36})", line)
                    if match:
                        running_env_ids.add(match.group(1))
        except Exception:
            pass

        if preserve_environments:
            for env_id in preserve_environments:
                running_env_ids.add(env_id)

        state_dir = Path.home() / ".amprealize" / "breakeramp"
        if state_dir.exists():
            env_files = list((state_dir / "environments").glob("*.json")) if (state_dir / "environments").exists() else []
            if env_files:
                most_recent_file = max(env_files, key=lambda f: f.stat().st_mtime)
                most_recent_env_id = most_recent_file.stem

            for category in ["environments", "manifests", "snapshots"]:
                category_dir = state_dir / category
                if category_dir.exists():
                    for f in category_dir.glob("*"):
                        if f.is_file():
                            file_id = f.stem
                            is_preserved = False
                            for running_id in running_env_ids:
                                if running_id in file_id or file_id in running_id:
                                    is_preserved = True
                                    break
                            if most_recent_env_id and (most_recent_env_id in file_id or file_id in most_recent_env_id):
                                is_preserved = True
                            if not is_preserved:
                                stale_state_to_remove[category].append(f)

    total_stale_files = sum(len(files) for files in stale_state_to_remove.values())

    # --- Dry run output ---
    if dry_run:
        if json_output:
            output = {
                "dry_run": True,
                **smart_result,
                "stale_state": {k: [str(f) for f in v] for k, v in stale_state_to_remove.items()},
            }
            console.print(json.dumps(output, indent=2, default=str))
            return

        console.print("[yellow]Dry run — no changes will be made[/yellow]")
        console.print()

        # Dead containers
        if smart_result["dead_containers"]:
            table = Table(title="Dead Containers to Remove")
            table.add_column("Name", style="cyan")
            table.add_column("Status", style="dim")
            for c in smart_result["dead_containers"]:
                table.add_row(c["name"], c.get("status", "")[:40])
            console.print(table)
        else:
            console.print("[green]No dead containers found[/green]")

        console.print()

        # Anonymous volumes
        anon_count = len(smart_result["anonymous_volumes"])
        if anon_count:
            console.print(f"[cyan]Anonymous volumes to remove:[/cyan] {anon_count}")
            # Show first few
            for vol in smart_result["anonymous_volumes"][:5]:
                console.print(f"  • {vol[:16]}...")
            if anon_count > 5:
                console.print(f"  [dim]... and {anon_count - 5} more[/dim]")
        else:
            console.print("[green]No anonymous volumes to clean[/green]")

        # Preserved volumes
        if smart_result["preserved_volumes"]:
            console.print()
            console.print(f"[green]Preserved volumes ({len(smart_result['preserved_volumes'])}):[/green]")
            for vol in smart_result["preserved_volumes"]:
                console.print(f"  [green]✓[/green] {vol}")

        # Unused images
        if smart_result["unused_images"]:
            console.print()
            table = Table(title="Unused Images to Remove")
            table.add_column("Image", style="cyan")
            table.add_column("Size", style="dim", justify="right")
            for img in smart_result["unused_images"]:
                table.add_row(img["name"], img.get("size", ""))
            console.print(table)

        if aggressive:
            console.print()
            console.print("[cyan]Build cache will be pruned[/cyan]")

        # Stale state
        if include_stale_state:
            console.print()
            if total_stale_files:
                console.print(f"[cyan]Stale state files to remove:[/cyan] {total_stale_files}")
                for category, files in stale_state_to_remove.items():
                    if files:
                        console.print(f"  • {category}: {len(files)} file(s)")
            else:
                console.print("[green]No stale state files[/green]")
            if running_env_ids:
                console.print(f"  [green]Preserving running environments: {', '.join(sorted(running_env_ids)[:3])}{'...' if len(running_env_ids) > 3 else ''}[/green]")

        # Machine
        if scaledown_machines:
            console.print()
            console.print("[cyan]Unused Podman machines would be stopped[/cyan]")
            if remove_machines:
                console.print("[red]Unused machines would be removed (rebuild required)[/red]")
            if preserve_machines:
                console.print(f"  Preserving machines: {', '.join(preserve_machines)}")

        return

    # --- Execute (non-dry-run already happened in smart_cleanup) ---
    # Phase 2 execution: stale state files
    stale_state_removed = {"environments": 0, "manifests": 0, "snapshots": 0}
    if include_stale_state and total_stale_files > 0:
        for category, files in stale_state_to_remove.items():
            for f in files:
                try:
                    f.unlink()
                    stale_state_removed[category] += 1
                except Exception:
                    pass

    total_state_removed = sum(stale_state_removed.values())

    # Phase 3: Machine scaledown
    machine_result = None
    if scaledown_machines and hasattr(executor, 'stop_unused_machines'):
        machine_result = executor.stop_unused_machines(
            preserve=preserve_machines or []
        )

    # --- Output ---
    if json_output:
        output = {
            **{k: v for k, v in smart_result.items() if k != "errors"},
            "dead_containers_removed": len(smart_result["dead_containers"]),
            "anonymous_volumes_removed": len(smart_result["anonymous_volumes"]),
            "unused_images_removed": len(smart_result["unused_images"]),
            "build_cache_cleared": smart_result["build_cache_cleared"],
            "stale_state_removed": stale_state_removed,
            "errors": smart_result["errors"],
        }
        if machine_result:
            output["machines_stopped"] = machine_result.machines_stopped
        console.print(json.dumps(output, indent=2, default=str))
        return

    if quiet:
        items = (
            len(smart_result["dead_containers"])
            + len(smart_result["anonymous_volumes"])
            + len(smart_result["unused_images"])
            + total_state_removed
        )
        if machine_result:
            items += machine_result.machines_stopped
        console.print(f"{items}")
        return

    # Summary table
    table = Table(title="Cleanup Results")
    table.add_column("Resource", style="cyan")
    table.add_column("Cleaned", style="green")

    table.add_row("Dead Containers", str(len(smart_result["dead_containers"])))
    table.add_row("Anonymous Volumes", str(len(smart_result["anonymous_volumes"])))

    if include_images:
        table.add_row("Unused Images", str(len(smart_result["unused_images"])))
    if aggressive and smart_result["build_cache_cleared"]:
        table.add_row("Build Cache", "Pruned")

    if include_stale_state and total_state_removed > 0:
        table.add_row("Stale State Files", str(total_state_removed))
        for category, count in stale_state_removed.items():
            if count > 0:
                table.add_row(f"  └─ {category.capitalize()}", str(count))

    if machine_result:
        table.add_row("Machines Stopped", str(machine_result.machines_stopped))

    console.print(table)

    # Show preserved volumes
    if smart_result["preserved_volumes"]:
        console.print()
        console.print(f"[green]Preserved {len(smart_result['preserved_volumes'])} named volume(s):[/green]")
        for vol in smart_result["preserved_volumes"][:8]:
            console.print(f"  [green]✓[/green] {vol}")
        if len(smart_result["preserved_volumes"]) > 8:
            console.print(f"  [dim]... and {len(smart_result['preserved_volumes']) - 8} more[/dim]")

    # Errors
    if smart_result["errors"]:
        console.print()
        for err in smart_result["errors"]:
            console.print(f"  [yellow]⚠[/yellow] {err}")

    console.print()
    console.print("[green]✓ Cleanup complete[/green]")


# =============================================================================
# Validate Command
# =============================================================================

@app.command()
def validate(
    path: Optional[Path] = typer.Argument(
        None,
        help="Path to environments.yaml file (auto-detects if not specified)",
    ),
    json_output: bool = typer.Option(
        False,
        "--json", "-j",
        help="Output as JSON",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet", "-q",
        help="Only output errors (exit code indicates validity)",
    ),
) -> None:
    """Validate an environments.yaml configuration file.

    Checks that the file:
    - Is valid YAML
    - Has the correct structure
    - Contains no unknown fields (strict validation)
    - Has valid runtime/infrastructure configuration

    Examples:
        breakeramp validate
        breakeramp validate ./environments.yaml
        breakeramp validate --json
    """
    import json as json_lib

    service = get_service()

    try:
        result = service.validate_environment_file(path=path, strict=False)
    except FileNotFoundError as e:
        if json_output:
            console.print(json_lib.dumps({
                "valid": False,
                "path": str(path) if path else None,
                "errors": [str(e)],
            }))
        else:
            console.print(f"[red]✗ {e}[/red]")
        raise typer.Exit(1)

    if json_output:
        console.print(json_lib.dumps(result, indent=2))
        if not result["valid"]:
            raise typer.Exit(1)
        return

    if result["valid"]:
        if not quiet:
            console.print(f"[green]✓ Valid:[/green] {result['path']}")
            console.print()

            # Show environments table
            table = Table(title="Environments")
            table.add_column("Name", style="cyan")
            table.add_column("Description")

            # Load manifest to get descriptions
            from .models import EnvironmentManifest
            manifest = EnvironmentManifest.validate_file(result["path"])
            for env_name in result["environments"]:
                env_def = manifest.get_environment(env_name)
                desc = env_def.description if env_def else "-"
                table.add_row(env_name, desc or "-")

            console.print(table)

            # Show warnings if any
            if result["warnings"]:
                console.print()
                console.print("[yellow]Warnings:[/yellow]")
                for warning in result["warnings"]:
                    console.print(f"  [yellow]⚠[/yellow] {warning}")
    else:
        console.print(f"[red]✗ Invalid:[/red] {result['path']}")
        console.print()

        for error in result["errors"]:
            console.print(f"  [red]•[/red] {error}")

        raise typer.Exit(1)


# =============================================================================
# Plan for Tests Command
# =============================================================================

@app.command("plan-for-tests")
def plan_for_tests(
    test_paths: List[str] = typer.Argument(
        ...,
        help="Test file or directory paths to analyze",
    ),
    blueprint: str = typer.Option(
        ...,
        "--blueprint", "-b",
        help="Blueprint ID containing full service definitions",
    ),
    environment: str = typer.Option(
        "development",
        "--env", "-e",
        help="Environment to use",
    ),
    markers: Optional[List[str]] = typer.Option(
        None,
        "--marker", "-m",
        help="Explicit pytest markers to include (can specify multiple)",
    ),
    suite_config: Optional[Path] = typer.Option(
        None,
        "--suite-config", "-s",
        help="Path to test suite configuration YAML",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output", "-o",
        help="Output plan to JSON file",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet", "-q",
        help="Only output plan ID",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose", "-v",
        help="Show detailed analysis information",
    ),
) -> None:
    """Analyze tests and plan minimal infrastructure.

    This command examines test files to discover which services they need,
    then creates a minimal deployment plan containing only those services.

    Examples:
        breakeramp plan-for-tests tests/integration/ -b full-stack
        breakeramp plan-for-tests tests/test_api.py -b dev-stack -m db -m redis
        breakeramp plan-for-tests tests/ -b full-stack --suite-config tests/suite.yaml
    """
    from .models import PlanForTestsRequest

    service = get_service()

    request = PlanForTestsRequest(
        test_paths=test_paths,
        blueprint_id=blueprint,
        environment=environment,
        markers=markers,
        suite_config_path=str(suite_config) if suite_config else None,
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task("Analyzing tests...", total=None)

        try:
            response = service.plan_for_tests(request)
        except Exception as e:
            console.print(f"[red]Analysis failed: {e}[/red]")
            raise typer.Exit(1)

    if quiet:
        console.print(response.plan_id)
        return

    if output:
        output.write_text(json.dumps({
            "plan_id": response.plan_id,
            "amp_run_id": response.amp_run_id,
            "required_services": response.required_services,
            "startup_order": response.startup_order,
            "discovered_markers": response.discovered_markers,
            "service_sources": response.service_sources,
            "test_files_analyzed": response.test_files_analyzed,
            "environment_estimates": {
                "memory_footprint_mb": response.environment_estimates.memory_footprint_mb,
                "expected_boot_duration_s": response.environment_estimates.expected_boot_duration_s,
            },
        }, indent=2))
        console.print(f"[green]Plan written to {output}[/green]")
        return

    # Display analysis summary
    console.print(Panel(
        f"[bold]Plan ID:[/bold] {response.plan_id}\n"
        f"[bold]Run ID:[/bold] {response.amp_run_id}\n"
        f"[bold]Test Files Analyzed:[/bold] {response.test_files_analyzed}\n"
        f"[bold]Memory:[/bold] {response.environment_estimates.memory_footprint_mb} MB\n"
        f"[bold]Boot Time:[/bold] ~{response.environment_estimates.expected_boot_duration_s}s",
        title="Test Infrastructure Plan",
        expand=False,
    ))

    # Show discovered markers
    if response.discovered_markers:
        console.print()
        console.print("[bold]Discovered Markers:[/bold]")
        for marker in response.discovered_markers:
            console.print(f"  [cyan]@pytest.mark.{marker}[/cyan]")

    # Show required services with startup order
    if response.required_services:
        console.print()
        table = Table(title="Required Services (Startup Order)")
        table.add_column("#", style="dim")
        table.add_column("Service", style="cyan")
        table.add_column("Reason", style="green")

        for i, svc in enumerate(response.startup_order, 1):
            reason = response.service_sources.get(svc, "dependency")
            table.add_row(str(i), svc, reason)

        console.print(table)

    # Show analysis errors if any
    if response.analysis_errors:
        console.print()
        console.print("[yellow]Analysis Warnings:[/yellow]")
        for error in response.analysis_errors:
            console.print(f"  [yellow]⚠[/yellow] {error}")

    if verbose and response.minimal_blueprint:
        console.print()
        console.print("[bold]Minimal Blueprint Services:[/bold]")
        for svc_name, svc_config in response.minimal_blueprint.get("services", {}).items():
            console.print(f"  [cyan]{svc_name}[/cyan]: {svc_config.get('image', 'unknown')}")
            if svc_config.get("depends_on"):
                console.print(f"    [dim]depends_on: {', '.join(svc_config['depends_on'])}[/dim]")

    console.print()
    console.print(f"[dim]Run 'breakeramp apply --plan-id {response.plan_id}' to provision[/dim]")


# =============================================================================
# Run Tests Command
# =============================================================================

@app.command("run-tests")
def run_tests(
    test_paths: List[str] = typer.Argument(
        ...,
        help="Test file or directory paths",
    ),
    blueprint: str = typer.Option(
        ...,
        "--blueprint", "-b",
        help="Blueprint ID containing full service definitions",
    ),
    environment: str = typer.Option(
        "development",
        "--env", "-e",
        help="Environment to use",
    ),
    markers: Optional[List[str]] = typer.Option(
        None,
        "--marker", "-m",
        help="Pytest markers to filter tests (can specify multiple)",
    ),
    pytest_args: Optional[List[str]] = typer.Option(
        None,
        "--pytest-arg", "-p",
        help="Additional pytest arguments (can specify multiple)",
    ),
    suite_config: Optional[Path] = typer.Option(
        None,
        "--suite-config", "-s",
        help="Path to test suite configuration YAML",
    ),
    timeout: int = typer.Option(
        600,
        "--timeout", "-t",
        help="Test execution timeout in seconds",
    ),
    keep: bool = typer.Option(
        False,
        "--keep", "-k",
        help="Keep infrastructure after tests complete",
    ),
    no_pytest: bool = typer.Option(
        False,
        "--no-pytest",
        help="Only provision infrastructure, don't run pytest",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose", "-v",
        help="Show detailed output",
    ),
) -> None:
    """Provision infrastructure, run tests, and teardown.

    This is an all-in-one command that:
    1. Analyzes test files to determine required services
    2. Provisions only the needed infrastructure
    3. Runs pytest with the specified options
    4. Tears down the environment (unless --keep)

    Examples:
        breakeramp run-tests tests/integration/ -b full-stack
        breakeramp run-tests tests/test_api.py -b dev-stack -p "-v" -p "--tb=short"
        breakeramp run-tests tests/ -b full-stack -m db --keep
    """
    from .models import RunTestsRequest

    service = get_service()

    request = RunTestsRequest(
        test_paths=test_paths,
        blueprint_id=blueprint,
        environment=environment,
        markers=markers,
        pytest_args=pytest_args,
        suite_config_path=str(suite_config) if suite_config else None,
        timeout_s=timeout,
        skip_teardown=keep,
        run_pytest=not no_pytest,
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Analyzing tests...", total=None)

        try:
            progress.update(task, description="Planning infrastructure...")
            # Note: run_tests() handles the full workflow internally
            response = service.run_tests(request)
        except Exception as e:
            console.print(f"[red]Test run failed: {e}[/red]")
            raise typer.Exit(1)

    # Display results
    console.print()
    console.print(Panel(
        f"[bold]Plan ID:[/bold] {response.plan_id or 'N/A'}\n"
        f"[bold]Run ID:[/bold] {response.amp_run_id or 'N/A'}\n"
        f"[bold]Services:[/bold] {', '.join(response.required_services) or 'None'}\n"
        f"[bold]Duration:[/bold] {response.total_duration_s:.1f}s",
        title="Test Run Summary",
        expand=False,
    ))

    # Show pytest results
    if response.pytest_exit_code is not None:
        console.print()
        if response.pytest_exit_code == 0:
            console.print("[green]✓ Tests passed[/green]")
        else:
            console.print(f"[red]✗ Tests failed (exit code: {response.pytest_exit_code})[/red]")

        if verbose and response.pytest_output:
            console.print()
            console.print("[bold]Pytest Output:[/bold]")
            console.print(response.pytest_output)

    # Show environment outputs
    if response.environment_outputs and verbose:
        console.print()
        table = Table(title="Service Endpoints")
        table.add_column("Service", style="cyan")
        table.add_column("URL/Endpoint", style="green")

        for svc_name, outputs in response.environment_outputs.items():
            url = outputs.get("url") or f"{outputs.get('host', 'localhost')}:{outputs.get('port', '?')}"
            table.add_row(svc_name, url)

        console.print(table)

    # Show teardown report
    if response.teardown_report:
        console.print()
        console.print("[dim]Teardown:[/dim]", ", ".join(response.teardown_report))

    # Show errors
    if response.errors:
        console.print()
        console.print("[yellow]Errors:[/yellow]")
        for error in response.errors:
            console.print(f"  [yellow]⚠[/yellow] {error}")

    # Exit with pytest exit code if tests were run
    if response.pytest_exit_code is not None and response.pytest_exit_code != 0:
        raise typer.Exit(response.pytest_exit_code)


# =============================================================================
# Nuke Command
# =============================================================================

@app.command()
def nuke(
    dry_run: bool = typer.Option(
        False,
        "--dry-run", "-n",
        help="Preview what would be removed without actually doing it",
    ),
    include_volumes: bool = typer.Option(
        False,
        "--include-volumes", "-v",
        help="Also remove associated volumes (WARNING: data loss possible)",
    ),
    include_state: bool = typer.Option(
        False,
        "--include-state", "-s",
        help="Also remove breakeramp state files (manifests, environments)",
    ),
    include_processes: bool = typer.Option(
        True,
        "--include-processes/--no-processes", "-p/-P",
        help="Kill Amprealize processes (uvicorn, vite) on standard ports",
    ),
    include_networks: bool = typer.Option(
        True,
        "--include-networks/--no-networks",
        help="Remove amprealize/breakeramp Podman networks",
    ),
    stop_machine: bool = typer.Option(
        True,
        "--stop-machine/--no-stop-machine",
        help="Stop (not destroy) the Podman machine to release ports (safe, VM preserved)",
    ),
    include_machine: bool = typer.Option(
        False,
        "--include-machine", "-m",
        help="Also destroy the Podman machine (WARNING: removes VM completely)",
    ),
    force: bool = typer.Option(
        False,
        "--force", "-f",
        help="Skip confirmation prompt",
    ),
    json_output: bool = typer.Option(
        False,
        "--json", "-j",
        help="Output as JSON",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet", "-q",
        help="Minimal output",
    ),
    skip_backup: bool = typer.Option(
        False,
        "--skip-backup",
        help="Skip automatic database backup before nuking",
    ),
) -> None:
    """Remove ALL Amprealize/legacy amprealize breakeramp containers, volumes, networks, state, and processes.

    This command is a nuclear option to clean up all Amprealize infrastructure.
    It finds and removes:
    - Containers matching amprealize-* or amp-*
    - Podman networks matching amprealize-* or amp-*
    - Amprealize processes on ports 8000 (backend) and 5173 (frontend)
    - Stops the Podman machine to release ports (gvproxy)
    - Optionally: volumes, state files, and destroy (not just stop) the Podman machine

    Before any destruction, databases are automatically backed up to
    ~/.amprealize/backups/ unless --skip-backup is passed.

    Use --dry-run to preview what would be removed before actually doing it.

    Examples:
        breakeramp nuke --dry-run          # Preview what would be removed
        breakeramp nuke                    # Remove containers + networks + processes + stop machine
        breakeramp nuke --force            # Remove without confirmation
        breakeramp nuke -v -s              # Also remove volumes and state files
        breakeramp nuke -m                 # Also destroy the Podman machine (not just stop)
        breakeramp nuke --no-stop-machine  # Keep machine running (ports may remain bound)
        breakeramp nuke --no-processes     # Skip killing processes
        breakeramp nuke --skip-backup      # Skip pre-nuke database backup
        breakeramp nuke --no-networks      # Skip removing networks
        breakeramp nuke --json             # Output results as JSON
    """
    import subprocess
    import re

    executor = PodmanExecutor()

    # Prefer a connection that targets the amprealize Podman machine (when present),
    # so nuke operates on the same Podman "universe" as other breakeramp commands.
    podman_local_cmd = ["podman"]
    machine_name: Optional[str] = None
    try:
        result = subprocess.run(
            podman_local_cmd + ["machine", "list", "--format", "{{.Name}}\t{{.Running}}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        default_name: Optional[str] = None
        first_name: Optional[str] = None
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            name_raw = parts[0].strip()
            name = name_raw.rstrip("*")
            if first_name is None:
                first_name = name
            if name_raw.endswith("*"):
                default_name = name
            if "amprealize" in name.lower():
                machine_name = name
                break

        machine_name = machine_name or default_name or first_name
    except Exception:
        machine_name = None

    # If we can identify a machine, clean both its common rootless/rootful
    # connections so "nuke" truly means nuke.
    podman_connections_to_clean: List[Optional[str]] = []
    if machine_name:
        resolved: Optional[str] = None
        try:
            resolved = executor.resolve_connection_for_machine(machine_name)
        except Exception:
            resolved = None

        for candidate in [resolved, machine_name, f"{machine_name}-root"]:
            if candidate and candidate not in podman_connections_to_clean:
                podman_connections_to_clean.append(candidate)

    if not podman_connections_to_clean:
        podman_connections_to_clean = [None]

    def _podman_cmd_for_connection(connection: Optional[str]) -> List[str]:
        cmd = ["podman"]
        if connection:
            cmd += ["--connection", connection]
        return cmd

    # Container name patterns to match
    patterns = [
        r"^amprealize-",
        r"^amp-[a-f0-9-]+.*amprealize",
        r"^amp-[a-f0-9-]+-",  # BreakerAmp-managed containers
    ]

    # Discover containers
    try:
        all_containers = []
        discovery_errors: List[str] = []
        any_success = False
        for connection in podman_connections_to_clean:
            podman_cmd = _podman_cmd_for_connection(connection)
            try:
                # Get all containers (running + stopped)
                result = subprocess.run(
                    podman_cmd + ["ps", "-a", "--format", "{{.ID}}\t{{.Names}}\t{{.Status}}"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                any_success = True
                for line in result.stdout.strip().split("\n"):
                    if not line.strip():
                        continue
                    parts = line.split("\t")
                    if len(parts) >= 3:
                        container_id, name, status = parts[0], parts[1], parts[2]
                        # Check if name matches any pattern
                        for pattern in patterns:
                            if re.match(pattern, name):
                                all_containers.append({
                                    "id": container_id,
                                    "name": name,
                                    "status": status,
                                    "running": "Up" in status,
                                    "connection": connection,
                                })
                                break
            except subprocess.TimeoutExpired:
                discovery_errors.append(f"Timeout discovering containers (connection={connection or 'default'})")
            except Exception as e:
                discovery_errors.append(f"Failed to list containers (connection={connection or 'default'}): {e}")

        if not any_success:
            console.print("[red]Failed to discover containers on any Podman connection[/red]")
            for err in discovery_errors:
                console.print(f"[red]  • {err}[/red]")
            raise typer.Exit(1)
    except subprocess.TimeoutExpired:
        console.print("[red]Timeout discovering containers[/red]")
        raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Failed to list containers: {e}[/red]")
        raise typer.Exit(1)

    # Discover volumes
    volumes_to_remove: List[Dict[str, Any]] = []
    if include_volumes:
        try:
            for connection in podman_connections_to_clean:
                podman_cmd = _podman_cmd_for_connection(connection)
                result = subprocess.run(
                    podman_cmd + ["volume", "ls", "--format", "{{.Name}}"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                for vol_name in result.stdout.strip().split("\n"):
                    vol_name = vol_name.strip()
                    if not vol_name:
                        continue
                    for pattern in patterns:
                        if re.match(pattern, vol_name):
                            volumes_to_remove.append({"name": vol_name, "connection": connection})
                            break
        except Exception:
            pass  # Non-critical, continue anyway

    # Discover networks
    networks_to_remove: List[Dict[str, Any]] = []
    if include_networks:
        try:
            for connection in podman_connections_to_clean:
                podman_cmd = _podman_cmd_for_connection(connection)
                result = subprocess.run(
                    podman_cmd + ["network", "ls", "--format", "{{.Name}}"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                for net_name in result.stdout.strip().split("\n"):
                    net_name = net_name.strip()
                    if not net_name or net_name == "podman":  # Never remove default network
                        continue
                    for pattern in patterns:
                        if re.match(pattern, net_name):
                            networks_to_remove.append({"name": net_name, "connection": connection})
                            break
        except Exception:
            pass  # Non-critical, continue anyway

    # Discover state files
    state_files_to_remove: List[Path] = []
    if include_state:
        state_dir = Path.home() / ".amprealize" / "breakeramp"
        if state_dir.exists():
            for subdir in ["manifests", "environments"]:
                path = state_dir / subdir
                if path.exists():
                    for f in path.glob("*.json"):
                        state_files_to_remove.append(f)

    # Discover Amprealize processes on standard ports
    processes_to_kill: List[Dict[str, Any]] = []
    amprealize_ports = {
        8000: "backend (uvicorn)",
        5173: "frontend (vite)",
        5174: "frontend alt (vite)",
        3000: "web console",
    }
    if include_processes:
        import platform
        for port, description in amprealize_ports.items():
            try:
                if platform.system() == "Darwin":
                    # macOS: use lsof
                    result = subprocess.run(
                        ["lsof", "-ti", f":{port}"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        pids = result.stdout.strip().split("\n")
                        for pid in pids:
                            pid = pid.strip()
                            if pid:
                                # Get process command
                                ps_result = subprocess.run(
                                    ["ps", "-p", pid, "-o", "command="],
                                    capture_output=True,
                                    text=True,
                                    timeout=5,
                                )
                                cmd = ps_result.stdout.strip()[:60] if ps_result.returncode == 0 else "unknown"
                                processes_to_kill.append({
                                    "pid": pid,
                                    "port": port,
                                    "description": description,
                                    "command": cmd,
                                })
                else:
                    # Linux: use ss or netstat
                    result = subprocess.run(
                        ["ss", "-tlnp", f"sport = :{port}"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    # Parse PID from ss output
                    for line in result.stdout.split("\n"):
                        if f":{port}" in line and "pid=" in line:
                            pid_match = re.search(r"pid=(\d+)", line)
                            if pid_match:
                                pid = pid_match.group(1)
                                processes_to_kill.append({
                                    "pid": pid,
                                    "port": port,
                                    "description": description,
                                    "command": "unknown",
                                })
            except Exception:
                pass  # Non-critical

    # Discover Podman machine to stop (releases gvproxy ports)
    machine_to_stop: Optional[Dict[str, Any]] = None
    if stop_machine and not include_machine:  # Only stop if not destroying
        try:
            result = subprocess.run(
                podman_local_cmd + ["machine", "list", "--format", "{{.Name}}\t{{.VMType}}\t{{.Running}}"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.split("\t")
                if len(parts) >= 3:
                    name, vm_type, running = parts[0], parts[1], parts[2]
                    # Match amprealize machines that are running
                    if "amprealize" in name.lower() and running.lower() == "true":
                        machine_to_stop = {
                            "name": name.rstrip("*"),  # Remove default marker
                            "vm_type": vm_type,
                            "running": True,
                        }
                        break
        except Exception:
            pass  # Non-critical

    # Discover Podman machine to destroy (complete removal)
    machine_to_destroy: Optional[Dict[str, str]] = None
    if include_machine:
        try:
            result = subprocess.run(
                podman_local_cmd + ["machine", "list", "--format", "{{.Name}}\t{{.VMType}}\t{{.Running}}"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.split("\t")
                if len(parts) >= 3:
                    name, vm_type, running = parts[0], parts[1], parts[2]
                    # Match amprealize machines
                    if "amprealize" in name.lower():
                        machine_to_destroy = {
                            "name": name.rstrip("*"),  # Remove default marker
                            "vm_type": vm_type,
                            "running": running.lower() == "true",
                        }
                        break
        except Exception:
            pass  # Non-critical

    # Calculate totals
    running_count = sum(1 for c in all_containers if c["running"])
    stopped_count = len(all_containers) - running_count

    # Dry run output
    if dry_run:
        if json_output:
            output = {
                "dry_run": True,
                "containers": all_containers,
                "processes": processes_to_kill,
                "volumes": [
                    (f"{v['name']} (conn: {v['connection']})" if v.get("connection") else v["name"])
                    for v in volumes_to_remove
                ],
                "networks": [
                    (f"{n['name']} (conn: {n['connection']})" if n.get("connection") else n["name"])
                    for n in networks_to_remove
                ],
                "state_files": [str(f) for f in state_files_to_remove],
                "machine_to_stop": machine_to_stop,
                "machine_to_destroy": machine_to_destroy,
                "summary": {
                    "containers_running": running_count,
                    "containers_stopped": stopped_count,
                    "containers_total": len(all_containers),
                    "processes": len(processes_to_kill),
                    "volumes": len(volumes_to_remove),
                    "networks": len(networks_to_remove),
                    "state_files": len(state_files_to_remove),
                    "machine_stop": 1 if machine_to_stop else 0,
                    "machine_destroy": 1 if machine_to_destroy else 0,
                },
            }
            console.print(json.dumps(output, indent=2))
            return

        console.print("[yellow]Dry run mode - no changes will be made[/yellow]")
        console.print()

        if all_containers:
            table = Table(title="Containers to Remove")
            table.add_column("Name", style="cyan")
            table.add_column("Status", style="dim")
            table.add_column("State", style="green")

            for c in all_containers:
                state = "[green]running[/green]" if c["running"] else "[dim]stopped[/dim]"
                table.add_row(c["name"], c["status"][:30], state)

            console.print(table)
            console.print()
            console.print(f"[bold]Total:[/bold] {len(all_containers)} containers ({running_count} running, {stopped_count} stopped)")
        else:
            console.print("[green]No amprealize containers found[/green]")

        if volumes_to_remove:
            console.print()
            console.print("[bold]Volumes to remove:[/bold]")
            for vol in volumes_to_remove:
                if vol.get("connection"):
                    console.print(f"  • {vol['name']} [dim](conn: {vol['connection']})[/dim]")
                else:
                    console.print(f"  • {vol['name']}")

        if networks_to_remove:
            console.print()
            console.print("[bold]Networks to remove:[/bold]")
            for net in networks_to_remove:
                if net.get("connection"):
                    console.print(f"  • {net['name']} [dim](conn: {net['connection']})[/dim]")
                else:
                    console.print(f"  • {net['name']}")

        if state_files_to_remove:
            console.print()
            console.print("[bold]State files to remove:[/bold]")
            for f in state_files_to_remove:
                console.print(f"  • {f.name}")

        if processes_to_kill:
            console.print()
            table = Table(title="Processes to Kill")
            table.add_column("PID", style="cyan")
            table.add_column("Port", style="yellow")
            table.add_column("Description", style="dim")
            table.add_column("Command", style="dim")

            for p in processes_to_kill:
                table.add_row(p["pid"], str(p["port"]), p["description"], p["command"][:40])

            console.print(table)

        if machine_to_stop:
            console.print()
            console.print(f"[bold yellow]Podman machine to stop:[/bold yellow] {machine_to_stop['name']} ({machine_to_stop['vm_type']}) - [green]running[/green]")
            console.print("[dim]  (stops VM to release ports; use --no-stop-machine to keep running)[/dim]")

        if machine_to_destroy:
            console.print()
            status = "[green]running[/green]" if machine_to_destroy.get("running") else "[dim]stopped[/dim]"
            console.print(f"[bold red]Podman machine to destroy:[/bold red] {machine_to_destroy['name']} ({machine_to_destroy['vm_type']}) - {status}")

        return

    # Nothing to do
    if not all_containers and not volumes_to_remove and not networks_to_remove and not state_files_to_remove and not processes_to_kill and not machine_to_stop and not machine_to_destroy:
        if json_output:
            console.print(json.dumps({"message": "Nothing to remove", "removed": {}}))
        elif not quiet:
            console.print("[green]✓ Nothing to remove - no amprealize resources found[/green]")
        return

    # Confirmation
    if not force:
        console.print()
        console.print("[bold red]⚠ WARNING: This will remove:[/bold red]")
        if all_containers:
            console.print(f"  • {len(all_containers)} container(s) ({running_count} running)")
        if processes_to_kill:
            console.print(f"  • {len(processes_to_kill)} process(es) on ports {', '.join(str(p['port']) for p in processes_to_kill)}")
        if networks_to_remove:
            console.print(f"  • {len(networks_to_remove)} network(s)")
        if volumes_to_remove:
            console.print(f"  • {len(volumes_to_remove)} volume(s) [red](data loss possible)[/red]")
        if state_files_to_remove:
            console.print(f"  • {len(state_files_to_remove)} state file(s)")
        if machine_to_stop:
            console.print(f"  • Stop Podman machine '{machine_to_stop['name']}' [yellow](releases ports, VM preserved)[/yellow]")
        if machine_to_destroy:
            console.print(f"  • Podman machine '{machine_to_destroy['name']}' [red](VM will be destroyed)[/red]")
        console.print()

        if not Confirm.ask("[yellow]Are you sure you want to continue?[/yellow]"):
            console.print("[dim]Aborted[/dim]")
            raise typer.Exit(0)

    # Auto-backup databases before destruction
    if not skip_backup and not dry_run:
        from .backup import backup_databases, validate_backup, rotate_backups

        if not quiet:
            console.print("[bold cyan]Auto-backing up databases before nuke...[/bold cyan]")

        backup_result = backup_databases(tag="pre-nuke", quiet=quiet)
        if backup_result["databases"]:
            if not quiet:
                for db in backup_result["databases"]:
                    console.print(f"  [green]✓[/green] {db}")
                if backup_result.get("validated"):
                    console.print("  [green]✓[/green] Backup validated")
                elif backup_result.get("errors"):
                    for e in backup_result["errors"]:
                        console.print(f"  [yellow]⚠ {e}[/yellow]")
                console.print(f"  [dim]Saved to: {backup_result['path']}[/dim]")
                console.print()
            rotate_backups(tag="pre-nuke")
        elif not quiet:
            if backup_result["skipped"]:
                console.print("  [dim]No running databases to back up[/dim]")
                console.print()

    # Execute removal
    removed = {
        "containers": [],
        "processes": [],
        "volumes": [],
        "networks": [],
        "state_files": [],
        "machine_stopped": None,
        "machine": None,
        "errors": [],
    }

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=quiet,
    ) as progress:
        # Kill processes first (before containers, so ports are freed)
        if processes_to_kill:
            task = progress.add_task("Killing processes...", total=len(processes_to_kill))

            for proc in processes_to_kill:
                try:
                    subprocess.run(
                        ["kill", "-9", proc["pid"]],
                        capture_output=True,
                        timeout=10,
                    )
                    removed["processes"].append(f"PID {proc['pid']} (port {proc['port']})")
                except Exception as e:
                    removed["errors"].append(f"Failed to kill PID {proc['pid']}: {e}")

                progress.advance(task)

        # Remove containers
        if all_containers:
            task = progress.add_task("Removing containers...", total=len(all_containers))

            for container in all_containers:
                try:
                    container_podman_cmd = _podman_cmd_for_connection(container.get("connection"))
                    # Stop if running
                    if container["running"]:
                        subprocess.run(
                            container_podman_cmd + ["stop", "--time", "5", container["id"]],
                            capture_output=True,
                            timeout=30,
                        )

                    # Remove
                    subprocess.run(
                        container_podman_cmd + ["rm", "-f", container["id"]],
                        capture_output=True,
                        timeout=30,
                    )
                    if container.get("connection") and len(podman_connections_to_clean) > 1:
                        removed["containers"].append(f"{container['name']} (conn: {container['connection']})")
                    else:
                        removed["containers"].append(container["name"])
                except Exception as e:
                    removed["errors"].append(f"Failed to remove {container['name']}: {e}")

                progress.advance(task)

        # Remove volumes
        if volumes_to_remove:
            task = progress.add_task("Removing volumes...", total=len(volumes_to_remove))

            for vol in volumes_to_remove:
                try:
                    subprocess.run(
                        _podman_cmd_for_connection(vol.get("connection")) + ["volume", "rm", "-f", vol["name"]],
                        capture_output=True,
                        timeout=30,
                    )
                    if vol.get("connection") and len(podman_connections_to_clean) > 1:
                        removed["volumes"].append(f"{vol['name']} (conn: {vol['connection']})")
                    else:
                        removed["volumes"].append(vol["name"])
                except Exception as e:
                    removed["errors"].append(f"Failed to remove volume {vol.get('name')}: {e}")

                progress.advance(task)

        # Remove networks (after containers are removed)
        if networks_to_remove:
            task = progress.add_task("Removing networks...", total=len(networks_to_remove))

            for net in networks_to_remove:
                try:
                    subprocess.run(
                        _podman_cmd_for_connection(net.get("connection")) + ["network", "rm", "-f", net["name"]],
                        capture_output=True,
                        timeout=30,
                    )
                    if net.get("connection") and len(podman_connections_to_clean) > 1:
                        removed["networks"].append(f"{net['name']} (conn: {net['connection']})")
                    else:
                        removed["networks"].append(net["name"])
                except Exception as e:
                    removed["errors"].append(f"Failed to remove network {net.get('name')}: {e}")

                progress.advance(task)

        # Remove state files
        if state_files_to_remove:
            task = progress.add_task("Removing state files...", total=len(state_files_to_remove))

            for f in state_files_to_remove:
                try:
                    f.unlink()
                    removed["state_files"].append(str(f))
                except Exception as e:
                    removed["errors"].append(f"Failed to remove {f}: {e}")

                progress.advance(task)

        # Stop Podman machine (releases gvproxy ports)
        # Do this after containers are removed but before machine destroy
        if machine_to_stop and not machine_to_destroy:
            # Only stop if we're not also destroying (destroy does its own stop)
            task = progress.add_task(f"Stopping Podman machine '{machine_to_stop['name']}'...", total=1)

            try:
                result = subprocess.run(
                    podman_local_cmd + ["machine", "stop", machine_to_stop["name"]],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if result.returncode == 0:
                    removed["machine_stopped"] = machine_to_stop["name"]
                else:
                    # Machine might already be stopped
                    if "already stopped" in result.stderr.lower() or "not running" in result.stderr.lower():
                        removed["machine_stopped"] = f"{machine_to_stop['name']} (was already stopped)"
                    elif "process does not exist" in result.stderr.lower():
                        removed["machine_stopped"] = f"{machine_to_stop['name']} (process already gone)"
                    else:
                        removed["errors"].append(f"Failed to stop machine: {result.stderr}")
            except Exception as e:
                removed["errors"].append(f"Failed to stop machine {machine_to_stop['name']}: {e}")

            progress.advance(task)

        # Destroy Podman machine (do this last, after containers are removed)
        if machine_to_destroy:
            task = progress.add_task(f"Destroying Podman machine '{machine_to_destroy['name']}'...", total=1)

            try:
                # Stop first if running
                if machine_to_destroy.get("running"):
                    subprocess.run(
                        podman_local_cmd + ["machine", "stop", machine_to_destroy["name"]],
                        capture_output=True,
                        timeout=60,
                    )

                # Destroy the machine
                result = subprocess.run(
                    podman_local_cmd + ["machine", "rm", "-f", machine_to_destroy["name"]],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if result.returncode == 0:
                    removed["machine"] = machine_to_destroy["name"]
                else:
                    removed["errors"].append(f"Failed to destroy machine: {result.stderr}")
            except Exception as e:
                removed["errors"].append(f"Failed to destroy machine {machine_to_destroy['name']}: {e}")

            progress.advance(task)

    # Output results
    if json_output:
        console.print(json.dumps(removed, indent=2))
        return

    if quiet:
        parts = []
        if removed["containers"]:
            parts.append(f"{len(removed['containers'])} containers")
        if removed["processes"]:
            parts.append(f"{len(removed['processes'])} processes")
        if removed["volumes"]:
            parts.append(f"{len(removed['volumes'])} volumes")
        if removed["state_files"]:
            parts.append(f"{len(removed['state_files'])} state files")
        if removed["networks"]:
            parts.append(f"{len(removed['networks'])} networks")
        if removed["machine_stopped"]:
            parts.append(f"stopped machine '{removed['machine_stopped']}'")
        if removed["machine"]:
            parts.append(f"destroyed machine '{removed['machine']}'")
        console.print(", ".join(parts) if parts else "nothing removed")
        return

    # Summary table
    console.print()
    table = Table(title="Nuke Results")
    table.add_column("Resource", style="cyan")
    table.add_column("Removed", style="green")

    table.add_row("Processes", str(len(removed["processes"])))
    table.add_row("Containers", str(len(removed["containers"])))
    table.add_row("Networks", str(len(removed["networks"])))
    table.add_row("Volumes", str(len(removed["volumes"])))
    table.add_row("State Files", str(len(removed["state_files"])))
    table.add_row("Machine Stopped", removed["machine_stopped"] or "-")
    table.add_row("Machine Destroyed", removed["machine"] or "-")

    console.print(table)

    if removed["errors"]:
        console.print()
        console.print("[yellow]Errors:[/yellow]")
        for error in removed["errors"]:
            console.print(f"  [yellow]⚠[/yellow] {error}")

    console.print()
    console.print("[green]✓ Nuke complete[/green]")


# =============================================================================
# Fresh Command (nuke + up in one step)
# =============================================================================

@app.command()
def fresh(
    environment: str = typer.Argument(
        "development",
        help="Environment name (default: 'development')",
    ),
    blueprint: Optional[str] = typer.Option(
        None,
        "--blueprint", "-b",
        help="Blueprint ID to plan (e.g., 'core-data-plane')",
    ),
    include_volumes: bool = typer.Option(
        False,
        "--include-volumes", "-v",
        help="Also remove volumes during nuke (WARNING: data loss possible)",
    ),
    include_state: bool = typer.Option(
        False,
        "--include-state", "-s",
        help="Also remove state files during nuke",
    ),
    skip_machine_stop: bool = typer.Option(
        False,
        "--skip-machine-stop",
        help="Don't stop the Podman machine (faster but ports may remain bound)",
    ),
    skip_resource_check: bool = typer.Option(
        False,
        "--skip-resource-check", "-S",
        help="Skip resource availability checks (proceed despite disk/memory warnings)",
    ),
    auto_cleanup: bool = typer.Option(
        False,
        "--auto-cleanup", "-c",
        help="Automatically clean up resources if disk/memory is low",
    ),
    force: bool = typer.Option(
        False,
        "--force", "-f",
        help="Skip confirmation prompt",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet", "-q",
        help="Minimal output",
    ),
    skip_backup: bool = typer.Option(
        False,
        "--skip-backup",
        help="Skip automatic database backup before nuking",
    ),
) -> None:
    """Nuke everything and bring up a fresh environment.

    This is the nuclear rebuild option - it combines:
    1. breakeramp nuke (stop/remove containers, networks, processes)
    2. breakeramp up (plan + apply a fresh environment)

    Before destruction, databases are automatically backed up to
    ~/.amprealize/backups/ unless --skip-backup is passed.

    Use this when you want a completely clean slate.

    Examples:
        breakeramp fresh                         # Nuke + bring up default development env
        breakeramp fresh development -b core-data-plane  # Specific blueprint
        breakeramp fresh --force                 # Skip confirmation
        breakeramp fresh -v -s                   # Also remove volumes and state files
        breakeramp fresh --skip-machine-stop     # Faster, but may have port conflicts
        breakeramp fresh --skip-resource-check   # Ignore disk/memory warnings
        breakeramp fresh --auto-cleanup          # Auto-cleanup if resources low
        breakeramp fresh --skip-backup           # Skip pre-nuke database backup
    """
    # Apply amprealize context to get DATABASE_URL and other DSNs
    ctx_name = _apply_amprealize_context(quiet=quiet)

    service = get_service()

    # Warn (and offer to switch) when cloud context + local-DB blueprint
    mismatch = _check_context_blueprint_mismatch(ctx_name, environment, service, blueprint)
    if mismatch:
        warning_msg, suggested_env = mismatch
        console.print(f"[yellow]⚠ {warning_msg}[/yellow]")
        console.print()
        if not force:
            if typer.confirm(f"Switch to '{suggested_env}' environment instead?", default=True):
                environment = suggested_env
                blueprint = None  # use the environment's default blueprint
                console.print(f"[green]→ Switched to '{environment}'[/green]")
                console.print()

    # Confirmation prompt
    if not force:
        console.print("[yellow]⚠ This will:[/yellow]")
        console.print("  • Kill all amprealize processes (ports 8000, 5173, 3000)")
        console.print("  • Remove all amprealize/amp containers")
        console.print("  • Remove all amprealize/amp networks")
        if not skip_machine_stop:
            console.print("  • Stop the Podman machine")
        if include_volumes:
            console.print("  • [red]Remove all amprealize volumes (DATA LOSS)[/red]")
        if include_state:
            console.print("  • Remove breakeramp state files")
        console.print("  • Bring up a fresh environment")
        console.print()

        if not typer.confirm("Continue?"):
            raise typer.Exit(0)

    console.print()

    try:
        nuke(
            dry_run=False,
            include_volumes=include_volumes,
            include_state=include_state,
            include_processes=True,
            include_networks=True,
            stop_machine=not skip_machine_stop,
            include_machine=False,
            force=True,  # Already confirmed above
            json_output=False,
            quiet=True,
            skip_backup=skip_backup,
        )
    except typer.Exit as e:
        if e.exit_code != 0:
            console.print("[red]Nuke failed, aborting fresh[/red]")
            raise
    except Exception as e:
        console.print(f"[red]Nuke failed: {e}[/red]")
        raise typer.Exit(1)

    if not skip_machine_stop:
        try:
            import subprocess

            preferred_machine = _get_environment_podman_machine(service, environment)
            machine_name = _select_podman_machine_for_environment(
                _list_podman_machine_names(),
                preferred_name=preferred_machine,
            )

            if machine_name:
                start_result = subprocess.run(
                    ["podman", "machine", "start", machine_name],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if start_result.returncode != 0 and "already running" not in start_result.stderr.lower():
                    console.print(f"[yellow]Could not start machine: {start_result.stderr.strip()}[/yellow]")
                    if _recover_podman_machine_start(service, machine_name, quiet=quiet):
                        if not quiet:
                            console.print(f"[green]✓ Recovered Podman machine '{machine_name}'[/green]")
            elif not quiet:
                console.print("[dim]No Podman machine to start[/dim]")
        except Exception as e:
            console.print(f"[yellow]Machine start error: {e}[/yellow]")

    display = LiveProgressDisplay(console=console, quiet=quiet)
    try:
        with display:
            display.on_phase("plan", "Planning fresh environment")

            from .models import PlanRequest as _PlanReq
            plan_req = _PlanReq(
                environment=environment,
                blueprint=blueprint,
            )

            plan_response = service.plan(plan_req)
            display.on_step_done("plan", detail=plan_response.plan_id)

            display.on_phase("apply", "Applying environment")

            from .models import ApplyRequest as _ApplyReq
            apply_req = _ApplyReq(
                plan_id=plan_response.plan_id,
                watch=True,
                force_podman=True,
                skip_resource_check=skip_resource_check,
                auto_cleanup=auto_cleanup,
                rebuild_images=True,  # Always rebuild on fresh to ensure latest code
            )

            apply_response = service.apply(apply_req, progress=display)
    except Exception as e:
        console.print(f"[red]Fresh apply failed: {e}[/red]")
        raise typer.Exit(1)

    # Print summary after Live exits
    if apply_response:
        display.print_summary(amp_run_id=apply_response.amp_run_id)

    console.print()
    console.print("[bold green]✓ Fresh environment ready![/bold green]")


# =============================================================================
# Backup Command
# =============================================================================

@app.command()
def backup(
    tag: str = typer.Option(
        "manual",
        "--tag", "-t",
        help="Label for this backup (e.g., 'pre-migration', 'manual')",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet", "-q",
        help="Minimal output",
    ),
    json_output: bool = typer.Option(
        False,
        "--json", "-j",
        help="Output as JSON",
    ),
    cloud: bool = typer.Option(
        True,
        "--cloud/--no-cloud",
        help="Allow cloud backup when no containers running (default: enabled)",
    ),
) -> None:
    """Backup all PostgreSQL databases to ~/.amprealize/backups/.

    Runs pg_dump inside each running database container and saves
    compressed SQL dumps. When no containers are running but DATABASE_URL
    is set, backs up from the cloud database instead.

    Examples:
        breakeramp backup                        # Quick backup with 'manual' tag
        breakeramp backup -t pre-migration       # Tagged backup
        breakeramp backup --json                 # JSON output for scripting
        breakeramp backup --no-cloud             # Skip cloud fallback
    """
    from .backup import backup_databases, rotate_backups

    if not quiet and not json_output:
        console.print("[bold cyan]Backing up databases...[/bold cyan]")

    result = backup_databases(tag=tag, quiet=quiet, allow_cloud=cloud)

    if json_output:
        console.print(json.dumps(result, indent=2))
        return

    if result["databases"]:
        for db in result["databases"]:
            console.print(f"  [green]✓[/green] {db}")
        if result.get("cloud"):
            console.print("  [dim](backed up from cloud database)[/dim]")
    if result["skipped"]:
        for s in result["skipped"]:
            console.print(f"  [dim]⊘ {s}[/dim]")
    if result["errors"]:
        for e in result["errors"]:
            console.print(f"  [red]✗ {e}[/red]")

    if result["databases"] and not result["errors"]:
        if result.get("validated"):
            console.print("  [green]✓[/green] Backup validated")
        console.print(f"\n[bold green]✓ Backup saved to:[/bold green] {result['path']}")
    elif result["databases"] and result["errors"]:
        console.print(f"\n[yellow]⚠ Backup saved but validation failed:[/yellow] {result['path']}")
        console.print("[yellow]  This backup may not restore correctly. Consider re-running.[/yellow]")
    elif not result["errors"]:
        console.print("[yellow]No databases found to back up[/yellow]")
    else:
        console.print("[red]Backup failed[/red]")
        raise typer.Exit(1)


# =============================================================================
# Restore Command
# =============================================================================

@app.command()
def restore(
    backup_name: Optional[str] = typer.Argument(
        None,
        help="Backup directory name (e.g., '2025-07-15T10-30-00_manual'). Uses latest if omitted.",
    ),
    force: bool = typer.Option(
        False,
        "--force", "-f",
        help="Skip confirmation prompt",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet", "-q",
        help="Minimal output",
    ),
    json_output: bool = typer.Option(
        False,
        "--json", "-j",
        help="Output as JSON",
    ),
    to_cloud: bool = typer.Option(
        False,
        "--to-cloud",
        help="Restore to cloud database (DATABASE_URL) instead of containers",
    ),
    to_cloud_dsn: Optional[str] = typer.Option(
        None,
        "--to-cloud-dsn",
        help="Explicit cloud DSN (overrides DATABASE_URL)",
        envvar="DATABASE_URL",
    ),
) -> None:
    """Restore PostgreSQL databases from a backup.

    By default restores the most recent backup. Specify a backup name
    to restore a specific one (see ``breakeramp backups`` for available backups).

    This overwrites existing data in the target databases.

    Examples:
        breakeramp restore                       # Restore latest backup
        breakeramp restore 2025-07-15T10-30-00_manual
        breakeramp restore --force               # Skip confirmation
        breakeramp restore --to-cloud            # Restore to cloud database
        breakeramp restore --to-cloud-dsn "postgresql://..."
    """
    from pathlib import Path as _P
    from .backup import restore_databases, validate_backup, list_backups, BACKUP_ROOT

    available = list_backups()
    if not available:
        console.print("[yellow]No backups found in ~/.amprealize/backups/[/yellow]")
        raise typer.Exit(1)

    if backup_name:
        target = BACKUP_ROOT / backup_name
        if not target.is_dir():
            console.print(f"[red]Backup not found:[/red] {backup_name}")
            console.print("[dim]Run 'breakeramp backups' to see available backups[/dim]")
            raise typer.Exit(1)
    else:
        target = _P(available[0]["path"])
        if not quiet and not json_output:
            console.print(f"[dim]Using latest backup: {available[0]['name']}[/dim]")

    # Pre-flight validation — check backup integrity before touching any data
    # (Skip for cloud restores since validate_backup checks container availability)
    if not to_cloud:
        if not quiet and not json_output:
            console.print("[bold cyan]Validating backup...[/bold cyan]")
        preflight = validate_backup(backup_path=target)
        if not preflight["ok"]:
            console.print("[red]✗ Backup validation failed — no databases were modified[/red]")
            for err in preflight["errors"]:
                console.print(f"  [red]✗ {err}[/red]")
            if json_output:
                console.print(json.dumps(preflight, indent=2))
            raise typer.Exit(1)
        if not quiet and not json_output:
            for check in preflight["checks"]:
                console.print(f"  [green]✓[/green] {check}")
    else:
        # Basic file existence check for cloud restores
        dump_files = list(target.glob("*.sql.gz"))
        if not dump_files:
            console.print(f"[red]No .sql.gz files found in {target}[/red]")
            raise typer.Exit(1)
        if not quiet and not json_output:
            console.print(f"  [green]✓[/green] Found {len(dump_files)} backup file(s)")

    if not force:
        target_desc = "cloud database" if to_cloud else "local containers"
        console.print(f"\n[yellow]⚠ This will drop and recreate databases from:[/yellow]")
        console.print(f"  {target}")
        console.print(f"  [dim]Target: {target_desc}[/dim]")
        dumps = list(target.glob("*.sql.gz"))
        for d in dumps:
            console.print(f"  • {d.stem.replace('.sql', '')}")
        console.print()
        if not Confirm.ask("[yellow]Continue?[/yellow]"):
            raise typer.Exit(0)

    if not quiet and not json_output:
        if to_cloud:
            console.print("[bold cyan]Restoring to cloud database...[/bold cyan]")
        else:
            console.print("[bold cyan]Restoring databases...[/bold cyan]")

    result = restore_databases(
        backup_path=target,
        to_cloud=to_cloud,
        cloud_dsn=to_cloud_dsn,
    )

    if json_output:
        console.print(json.dumps(result, indent=2))
        return

    if result["restored"]:
        for db in result["restored"]:
            console.print(f"  [green]✓[/green] {db}")
        if result.get("cloud"):
            console.print("  [dim](restored to cloud database)[/dim]")
    if result["skipped"]:
        for s in result["skipped"]:
            console.print(f"  [dim]⊘ {s}[/dim]")
    if result["errors"]:
        for e in result["errors"]:
            console.print(f"  [red]✗ {e}[/red]")

    if result["restored"]:
        if result.get("safety_backup"):
            console.print(f"  [dim]Safety snapshot: {result['safety_backup']}[/dim]")
        console.print("\n[bold green]✓ Restore complete[/bold green]")
    else:
        console.print("[red]Restore failed[/red]")
        raise typer.Exit(1)


# =============================================================================
# Backups Command (list)
# =============================================================================

@app.command()
def backups(
    json_output: bool = typer.Option(
        False,
        "--json", "-j",
        help="Output as JSON",
    ),
) -> None:
    """List available database backups.

    Examples:
        breakeramp backups
        breakeramp backups --json
    """
    from .backup import list_backups

    available = list_backups()

    if json_output:
        console.print(json.dumps(available, indent=2))
        return

    if not available:
        console.print("[dim]No backups found in ~/.amprealize/backups/[/dim]")
        return

    table = Table(title="Database Backups")
    table.add_column("Name", style="cyan")
    table.add_column("Tag", style="yellow")
    table.add_column("Databases", style="green")
    table.add_column("Size", style="dim", justify="right")

    for b in available:
        table.add_row(
            b["created"],
            b["tag"],
            ", ".join(b["databases"]),
            f"{b['size_kb']:.1f} KB",
        )

    console.print(table)
    console.print(f"\n[dim]Location: ~/.amprealize/backups/[/dim]")


# =============================================================================
# Version Command
# =============================================================================

@app.command()
def version() -> None:
    """Show version information."""
    from . import __version__
    console.print(f"breakeramp {__version__}")


# =============================================================================
# Entry Point
# =============================================================================

def main() -> None:
    """CLI entry point."""
    app()


if __name__ == "__main__":
    main()
