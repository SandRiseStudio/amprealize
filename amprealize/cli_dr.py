"""
Disaster Recovery CLI Commands
Provides operational commands for backup, restore, failover testing, and status monitoring
"""

import click
import subprocess
import json
import os
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional


logger = logging.getLogger(__name__)


@click.group(name="dr")
def dr_group():
    """Disaster Recovery commands for backup, restore, and failover testing."""
    pass


@dr_group.command(name="backup")
@click.option(
    "--service",
    type=click.Choice(["postgres", "redis", "duckdb", "all"]),
    default="all",
    help="Service to backup (default: all)",
)
@click.option(
    "--output-dir",
    type=click.Path(exists=False),
    default="/var/backups/amprealize",
    help="Backup output directory",
)
@click.option(
    "--s3-bucket",
    type=str,
    default=None,
    help="S3 bucket for remote backup storage (optional)",
)
def backup_command(service: str, output_dir: str, s3_bucket: Optional[str]):
    """
    Perform backup of specified service(s).

    Examples:
        amprealize dr backup --service postgres
        amprealize dr backup --service all --s3-bucket s3://amprealize-backups
    """
    click.echo(f"🔄 Starting backup for: {service}")

    # Set environment variables
    env = os.environ.copy()
    env["BACKUP_DIR"] = output_dir
    if s3_bucket:
        env["S3_BUCKET"] = s3_bucket

    # Get script directory
    script_dir = Path(__file__).parent.parent.parent / "scripts"

    services_to_backup = ["postgres", "redis", "duckdb"] if service == "all" else [service]
    results = {}

    for svc in services_to_backup:
        script_name = f"dr_backup_{svc}.sh"
        script_path = script_dir / script_name

        if not script_path.exists():
            click.echo(f"❌ Script not found: {script_path}")
            results[svc] = {"status": "error", "message": "Script not found"}
            continue

        try:
            click.echo(f"  → Running backup for {svc}...")
            result = subprocess.run(
                [str(script_path)],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )

            click.echo(f"✅ {svc} backup completed")
            if result.stdout:
                click.echo(result.stdout)

            results[svc] = {"status": "success", "message": "Backup completed"}

        except subprocess.CalledProcessError as e:
            click.echo(f"❌ {svc} backup failed: {e}")
            if e.stderr:
                click.echo(e.stderr)
            results[svc] = {"status": "error", "message": str(e)}

    # Summary
    click.echo("\n" + "=" * 60)
    click.echo("Backup Summary:")
    for svc, result in results.items():
        status_icon = "✅" if result["status"] == "success" else "❌"
        click.echo(f"  {status_icon} {svc}: {result['message']}")

    # Exit with error if any backup failed
    if any(r["status"] == "error" for r in results.values()):
        raise click.ClickException("One or more backups failed")


@dr_group.command(name="restore")
@click.option(
    "--service",
    type=click.Choice(["postgres", "redis", "duckdb"]),
    required=True,
    help="Service to restore",
)
@click.option(
    "--backup-name",
    type=str,
    default="latest",
    help="Backup name or 'latest' for most recent (default: latest)",
)
@click.option(
    "--backup-dir",
    type=click.Path(exists=True),
    default="/var/backups/amprealize",
    help="Backup directory",
)
@click.option(
    "--confirm",
    is_flag=True,
    help="Skip confirmation prompt (use with caution)",
)
def restore_command(service: str, backup_name: str, backup_dir: str, confirm: bool):
    """
    Restore service from backup.

    ⚠️  WARNING: This will overwrite current data!

    Examples:
        amprealize dr restore --service postgres --backup-name latest
        amprealize dr restore --service redis --backup-name redis_backup_20250112_143000
    """
    if not confirm:
        click.confirm(
            f"⚠️  This will restore {service} from backup '{backup_name}' and OVERWRITE current data. Continue?",
            abort=True,
        )

    click.echo(f"🔄 Starting restore for: {service}")

    # Set environment variables
    env = os.environ.copy()
    env["BACKUP_DIR"] = backup_dir

    # Get script directory
    script_dir = Path(__file__).parent.parent.parent / "scripts"

    # Currently only postgres has restore script
    if service == "postgres":
        script_path = script_dir / "dr_restore_postgres.sh"
    else:
        click.echo(f"❌ Restore not yet implemented for {service}")
        raise click.ClickException(f"Restore script not available for {service}")

    if not script_path.exists():
        click.echo(f"❌ Script not found: {script_path}")
        raise click.ClickException(f"Script not found: {script_path}")

    try:
        click.echo(f"  → Running restore for {service} from {backup_name}...")
        result = subprocess.run(
            [str(script_path), backup_name],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )

        click.echo(f"✅ {service} restore completed")
        if result.stdout:
            click.echo(result.stdout)

    except subprocess.CalledProcessError as e:
        click.echo(f"❌ {service} restore failed: {e}")
        if e.stderr:
            click.echo(e.stderr)
        raise click.ClickException(f"Restore failed: {e}")


@dr_group.command(name="test-failover")
@click.option(
    "--output-dir",
    type=click.Path(exists=False),
    default="/var/log/amprealize/dr_tests",
    help="Test results output directory",
)
def test_failover_command(output_dir: str):
    """
    Run automated failover tests.

    Tests include:
      - PostgreSQL health check and query latency
      - Redis health check and read/write latency
      - Backup freshness for all services
      - RTO compliance validation

    Example:
        amprealize dr test-failover
    """
    click.echo("🔄 Running DR failover test suite...")

    # Set environment variables
    env = os.environ.copy()
    env["RESULTS_DIR"] = output_dir

    # Get script directory
    script_dir = Path(__file__).parent.parent.parent / "scripts"
    script_path = script_dir / "dr_test_failover.sh"

    if not script_path.exists():
        click.echo(f"❌ Script not found: {script_path}")
        raise click.ClickException(f"Script not found: {script_path}")

    try:
        result = subprocess.run(
            [str(script_path)],
            env=env,
            capture_output=True,
            text=True,
            check=False,  # Don't raise on non-zero exit (tests may fail)
        )

        # Output test results
        click.echo(result.stdout)

        if result.returncode == 0:
            click.echo("✅ All failover tests passed")
        else:
            click.echo("⚠️  Some failover tests failed (see output above)")
            raise click.ClickException("Failover tests did not pass")

    except subprocess.CalledProcessError as e:
        click.echo(f"❌ Test execution failed: {e}")
        if e.stderr:
            click.echo(e.stderr)
        raise click.ClickException(f"Test execution failed: {e}")


@dr_group.command(name="status")
@click.option(
    "--service",
    type=click.Choice(["postgres", "redis", "duckdb", "all"]),
    default="all",
    help="Service to check status (default: all)",
)
@click.option(
    "--backup-dir",
    type=click.Path(exists=True),
    default="/var/backups/amprealize",
    help="Backup directory",
)
def status_command(service: str, backup_dir: str):
    """
    Check disaster recovery status and backup freshness.

    Example:
        amprealize dr status
        amprealize dr status --service postgres
    """
    click.echo("🔍 Checking DR status...\n")

    backup_base = Path(backup_dir)
    services = ["postgres", "redis", "duckdb"] if service == "all" else [service]

    for svc in services:
        click.echo(f"{'=' * 60}")
        click.echo(f"{svc.upper()}")
        click.echo(f"{'=' * 60}")

        svc_backup_dir = backup_base / svc

        if not svc_backup_dir.exists():
            click.echo(f"  ⚠️  No backup directory found: {svc_backup_dir}")
            click.echo()
            continue

        # Find latest backup
        if svc == "postgres":
            backups = list(svc_backup_dir.glob("postgres_backup_*"))
            backups = [b for b in backups if b.is_dir()]
        else:
            backups = list(svc_backup_dir.glob(f"{svc}_backup_*.tar.gz"))

        if not backups:
            click.echo("  ❌ No backups found")
            click.echo()
            continue

        # Sort by modification time
        backups.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        latest_backup = backups[0]

        # Get backup age
        backup_time = datetime.fromtimestamp(latest_backup.stat().st_mtime)
        backup_age = datetime.now() - backup_time

        # Get backup size
        if latest_backup.is_dir():
            backup_size = sum(f.stat().st_size for f in latest_backup.rglob("*") if f.is_file())
        else:
            backup_size = latest_backup.stat().st_size

        backup_size_mb = backup_size / 1048576

        # Determine status
        if svc == "postgres":
            threshold_hours = 2
            is_fresh = backup_age.total_seconds() / 3600 < threshold_hours
        elif svc == "redis":
            threshold_mins = 30
            is_fresh = backup_age.total_seconds() / 60 < threshold_mins
        else:  # duckdb
            threshold_hours = 2
            is_fresh = backup_age.total_seconds() / 3600 < threshold_hours

        status_icon = "✅" if is_fresh else "⚠️"

        click.echo(f"  {status_icon} Latest Backup: {latest_backup.name}")
        click.echo(f"     Age: {backup_age}")
        click.echo(f"     Size: {backup_size_mb:.2f} MB")
        click.echo(f"     Total Backups: {len(backups)}")

        # Load metadata if available
        meta_file = svc_backup_dir / f"{latest_backup.stem}.meta.json"
        if meta_file.exists():
            try:
                with open(meta_file) as f:
                    meta = json.load(f)
                    click.echo(f"     RTO Target: {meta.get('rto_minutes', meta.get('rto_hours', 'N/A'))}")
                    click.echo(f"     RPO Target: {meta.get('rpo_minutes', 'N/A')} min")
            except Exception as e:
                logger.debug(f"Could not load metadata: {e}")

        click.echo()


@dr_group.command(name="failover")
@click.option(
    "--target",
    type=click.Choice(["primary", "secondary", "standby"]),
    required=True,
    help="Failover target (primary, secondary, or standby)",
)
@click.option(
    "--confirm",
    is_flag=True,
    help="Skip confirmation prompt (use with caution)",
)
def failover_command(target: str, confirm: bool):
    """
    Initiate manual failover to specified target.

    ⚠️  WARNING: This will trigger a production failover!

    Example:
        amprealize dr failover --target secondary --confirm
    """
    if not confirm:
        click.confirm(
            f"⚠️  This will initiate a PRODUCTION FAILOVER to {target}. Continue?",
            abort=True,
        )

    click.echo(f"🔄 Initiating failover to: {target}")
    click.echo("⚠️  Failover automation is not yet implemented.")
    click.echo("    Follow manual runbook procedures from docs/DISASTER_RECOVERY_POLICY.md")
    click.echo()
    click.echo("Manual steps:")
    click.echo("  1. Stop traffic to primary")
    click.echo("  2. Verify data replication lag < RPO")
    click.echo("  3. Promote target to primary")
    click.echo("  4. Update DNS/load balancer")
    click.echo("  5. Validate application connectivity")
    click.echo("  6. Monitor for 15 minutes")

    raise click.ClickException("Manual failover required - automated failover not yet implemented")
