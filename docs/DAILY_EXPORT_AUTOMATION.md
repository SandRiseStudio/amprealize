# Daily Export Automation

> **Status:** ✅ Complete (Epic 4.7 - Daily Export Automation)
> **Last Updated:** 2025-11-07
> **Owner:** DevOps + Engineering

## Overview

The Daily Export Automation system automatically handles the DuckDB to SQLite export pipeline with backup rotation, monitoring, and alerting. This completes Epic 4.7, bringing the Analytics & Observability epic to 100% completion.

## Architecture

```
┌─────────────────────┐
│   Cron Scheduler    │
│   (Daily 2:00 AM)   │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Daily Export Job   │
│  (automation.py)    │
├─────────────────────┤
│  • Create backup    │
│  • Run export       │
│  • Rotate backups   │
│  • Emit telemetry   │
│  • Send alerts      │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│   Export Results    │
│  (telemetry events) │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│   Analytics Stack   │
│  (Metabase Dashboards)│
└─────────────────────┘
```

## Components

### 1. Daily Export Automation Script
**File:** `scripts/daily_export_automation.py`

**Features:**
- **Backup Creation:** Automatic timestamped backups before export
- **Export Execution:** Runs `export_duckdb_to_sqlite.py` with error handling
- **Backup Rotation:** Removes backups older than retention policy (default: 30 days)
- **Telemetry Emission:** Emits job completion and metrics events
- **Failure Alerting:** Webhook and email notifications for failures
- **Configuration:** Environment variable driven configuration

**Usage:**
```bash
# Run with default settings
python3 scripts/daily_export_automation.py

# Run with custom retention
python3 scripts/daily_export_automation.py --retention-days 7

# Dry run for testing
python3 scripts/daily_export_automation.py --dry-run

# Verbose logging
python3 scripts/daily_export_automation.py --verbose
```

### 2. Cron Setup Script
**File:** `scripts/setup_daily_export_cron.sh`

**Features:**
- **Automated Installation:** One-command cron job setup
- **Time Configuration:** Configurable execution time (default: 2:00 AM UTC)
- **Safety Checks:** Dry-run mode and job validation
- **Monitoring Integration:** Automatic log file creation
- **Retention Control:** Configurable backup retention

**Usage:**
```bash
# Dry run to see what would be installed
./scripts/setup_daily_export_cron.sh --dry-run

# Install with custom time and retention
./scripts/setup_daily_export_cron.sh --time "03:00" --retention-days 7

# Install with defaults
./scripts/setup_daily_export_cron.sh
```

### 3. Export Contracts
**File:** `amprealize/export_contracts.py`

**Purpose:** Type-safe data structures for job tracking and configuration.

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AMPREALIZE_EXPORT_DUCKDB_PATH` | `data/telemetry.duckdb` | Path to DuckDB warehouse |
| `AMPREALIZE_EXPORT_SQLITE_PATH` | `data/telemetry_sqlite.db` | Path to SQLite export |
| `AMPREALIZE_EXPORT_BACKUP_DIR` | `data/backups` | Backup storage directory |
| `AMPREALIZE_EXPORT_RETENTION_DAYS` | `30` | Backup retention period |
| `AMPREALIZE_EXPORT_DRY_RUN` | `false` | Enable dry-run mode |
| `AMPREALIZE_EXPORT_ALERT_WEBHOOK` | - | Webhook URL for failure alerts |
| `AMPREALIZE_EXPORT_NOTIFICATION_EMAIL` | - | Email for failure notifications |
| `AMPREALIZE_EXPORT_ALERT_ON_SUCCESS` | `false` | Send success notifications |

### Example Configuration

```bash
# Production configuration
export AMPREALIZE_EXPORT_DUCKDB_PATH="data/telemetry.duckdb"
export AMPREALIZE_EXPORT_SQLITE_PATH="data/telemetry_sqlite.db"
export AMPREALIZE_EXPORT_BACKUP_DIR="/var/backups/amprealize"
export AMPREALIZE_EXPORT_RETENTION_DAYS="30"
export AMPREALIZE_EXPORT_ALERT_WEBHOOK="https://hooks.slack.com/services/YOUR/WEBHOOK"
export AMPREALIZE_EXPORT_NOTIFICATION_EMAIL="ops@amprealize.com"

# Run the export
python3 scripts/daily_export_automation.py
```

## Monitoring & Observability

### Telemetry Events

The automation emits two types of telemetry events:

1. **Job Completion Event** (`analytics.daily_export_complete`)
   ```json
   {
     "job_id": "uuid",
     "status": "complete|failed",
     "tables_exported": 8,
     "rows_exported": 1000,
     "file_size_mb": 42.5,
     "backups_deleted": 2,
     "duration_seconds": 5.2,
     "backup_path": "/data/backups/telemetry_sqlite_20251107_020000.db"
   }
   ```

2. **Export Metrics Event** (`analytics.export_metrics`)
   ```json
   {
     "job_id": "uuid",
     "export_success": true,
     "tables_exported": 8,
     "rows_exported": 1000,
     "file_size_mb": 42.5,
     "backup_created": true,
     "old_backups_cleaned": 2,
     "export_duration_seconds": 5.2
   }
   ```

### Logs

**Log Location:** `/var/log/amprealize/daily_export.log` (or `daily_export.log` in project directory)

**Log Format:**
```
2025-11-07 02:00:30 [INFO] daily_export: Starting daily export job c6256ecd-116f-4d3b-b0eb-30eeec3989ee
2025-11-07 02:00:30 [INFO] root: Job c6256ecd-116f-4d3b-b0eb-30eeec3989ee status: running - Creating backup
2025-11-07 02:00:32 [INFO] root: Job c6256ecd-116f-4d3b-b0eb-30eeec3989ee status: complete - Export complete
```

### Monitoring Dashboard

Integration with existing Grafana dashboards:
- **Export Success Rate** metric
- **Export Duration** trends
- **File Size** tracking
- **Backup Rotation** statistics

## Installation & Setup

### Quick Start

1. **Test the automation:**
   ```bash
   python3 scripts/daily_export_automation.py --dry-run
   ```

2. **Install cron job:**
   ```bash
   ./scripts/setup_daily_export_cron.sh
   ```

3. **Verify installation:**
   ```bash
   crontab -l | grep daily_export
   tail -f /var/log/amprealize/daily_export.log
   ```

### Manual Installation

If you prefer manual cron setup:

```bash
# Add to crontab (runs at 2:00 AM UTC daily)
(crontab -l 2>/dev/null; echo "0 2 * * * cd /path/to/amprealize && python3 scripts/daily_export_automation.py --retention-days 30 >> /var/log/amprealize/daily_export.log 2>&1") | crontab -
```

### Docker/Container Setup

For containerized deployments:

```bash
# Mount backup volume
docker run -v /host/backups:/data/backups ...

# Add environment variables
docker run -e AMPREALIZE_EXPORT_BACKUP_DIR=/data/backups ...
```

## Backup Management

### Retention Policy

- **Default:** 30 days retention
- **Configurable:** `--retention-days` parameter
- **Automatic Cleanup:** Removes files older than retention period
- **Safe Naming:** Timestamp-based filenames (`telemetry_sqlite_YYYYMMDD_HHMMSS.db`)

### Backup Location

```
/data/backups/
├── telemetry_sqlite_20251107_020000.db
├── telemetry_sqlite_20251106_020000.db
├── telemetry_sqlite_20251105_020000.db
└── ...
```

## Troubleshooting

### Common Issues

**1. Export Script Import Error**
```
Error: No module named 'export_duckdb_to_sqlite'
```
**Solution:** Ensure you're running from the project root directory.

**2. Permission Denied on Log Directory**
```
Error: Permission denied: /var/log/amprealize/daily_export.log
```
**Solution:** The script will fallback to current directory logging automatically.

**3. Backup Directory Creation Fails**
```
Error: Cannot create backup directory
```
**Solution:** Check directory permissions or set `AMPREALIZE_EXPORT_BACKUP_DIR` to a writable path.

### Debug Mode

Enable verbose logging for troubleshooting:

```bash
python3 scripts/daily_export_automation.py --verbose --dry-run
```

### Log Analysis

```bash
# Check recent export activity
tail -f /var/log/amprealize/daily_export.log

# Search for errors
grep ERROR /var/log/amprealize/daily_export.log

# Check export success rate
grep "Export complete" /var/log/amprealize/daily_export.log | wc -l
```

## Security Considerations

### File Permissions
- Backup directory: `drwxr-xr-x` (readable by owner and group)
- Log files: `rw-r--r--` (readable by all, writable by owner)
- SQLite exports: `rw-rw-r--` (readable/writable by owner and group)

### Credential Management
- Webhook URLs: Stored in environment variables
- Email addresses: Stored in environment variables
- No hardcoded secrets in scripts

### Data Protection
- Backups are created before export to prevent data loss
- Failed exports do not overwrite existing SQLite files
- All file operations use atomic operations where possible

## Integration with Existing Systems

### Metabase Integration
- Automatically keeps SQLite exports fresh for Metabase dashboards
- No manual intervention required for dashboard updates
- Supports the existing `export_duckdb_to_sqlite.py` workflow

### Telemetry Integration
- Leverages existing `TelemetryClient` for event emission
- Integrates with PRD metrics tracking
- Compatible with existing monitoring infrastructure

### CI/CD Integration
- Can be included in deployment pipelines
- Environment-based configuration supports different environments
- Dry-run mode suitable for integration testing

## Performance Considerations

### Expected Performance
- **Export Duration:** 2-5 seconds for typical datasets
- **Backup Creation:** 1-2 seconds
- **Backup Cleanup:** <1 second for typical retention periods
- **Total Job Duration:** <10 seconds for 30-day retention

### Resource Usage
- **Memory:** Minimal (<50MB)
- **CPU:** Low impact (single-threaded operations)
- **Disk I/O:** Sequential read/write operations
- **Network:** Only if webhook notifications enabled

### Scalability
- Linear scaling with dataset size
- Retention policy affects cleanup time only
- Suitable for multi-tenant deployments with environment isolation

## Future Enhancements

### Potential Improvements
1. **Parallel Export:** Multi-threaded export for large datasets
2. **Compression:** Automatic backup compression for storage efficiency
3. **Cloud Storage:** Support for S3/Blob storage backends
4. **Advanced Scheduling:** Cron expression support beyond daily runs
5. **Health Checks:** Integration with service health monitoring

### Monitoring Enhancements
1. **Prometheus Metrics:** Export duration and success rate metrics
2. **Alerting Rules:** Grafana alerts for export failures
3. **Dashboard Widgets:** Export status widgets in existing dashboards

---

## References

- **Epic 4.7:** Daily Export Automation in `WORK_STRUCTURE.md`
- **Export Script:** `scripts/export_duckdb_to_sqlite.py`
- **Setup Script:** `scripts/setup_daily_export_cron.sh`
- **Contracts:** `amprealize/export_contracts.py`
- **Integration:** `docs/analytics/DUCKDB_SQLITE_EXPORT.md`
- **Monitoring:** `docs/MONITORING_GUIDE.md`
