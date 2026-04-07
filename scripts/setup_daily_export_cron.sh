#!/bin/bash
# Setup Cron Job for Daily Export Automation
#
# This script installs and configures a cron job to run the daily export automation
# at 2:00 AM UTC daily, following the recommendation in DUCKDB_SQLITE_EXPORT.md.
#
# Usage:
#     ./scripts/setup_daily_export_cron.sh [--dry-run] [--time HH:MM] [--retention-days N]

# Parse command line arguments
DRY_RUN=false
EXPORT_TIME="02:00"
RETENTION_DAYS=30

while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --time)
            EXPORT_TIME="$2"
            shift 2
            ;;
        --retention-days)
            RETENTION_DAYS="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [--dry-run] [--time HH:MM] [--retention-days N]"
            echo ""
            echo "Options:"
            echo "  --dry-run          Show what would be installed without making changes"
            echo "  --time HH:MM       Time to run export (default: 02:00)"
            echo "  --retention-days   Backup retention days (default: 30)"
            echo "  --help             Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Get the current directory and project path
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_PATH="$(cd "$PROJECT_DIR" && pwd)"

echo "🚀 Setting up daily export automation cron job"
echo "================================================"
echo "Project directory: $PROJECT_PATH"
echo "Export time: $EXPORT_TIME UTC"
echo "Retention days: $RETENTION_DAYS"
echo "Dry run: $DRY_RUN"
echo ""

# Parse time into hours and minutes
IFS=':' read -ra TIME_PARTS <<< "$EXPORT_TIME"
HOUR="${TIME_PARTS[0]}"
MINUTE="${TIME_PARTS[1]}"

# Validate time format
if [[ ! "$HOUR" =~ ^[0-9]{1,2}$ ]] || [[ ! "$MINUTE" =~ ^[0-9]{1,2}$ ]]; then
    echo "❌ Error: Invalid time format. Use HH:MM (e.g., 02:00)"
    exit 1
fi

if [ "$HOUR" -gt 23 ] || [ "$MINUTE" -gt 59 ]; then
    echo "❌ Error: Invalid time. Hours must be 0-23, minutes must be 0-59"
    exit 1
fi

# Create the cron job command
CRON_CMD="$MINUTE $HOUR * * * cd '$PROJECT_PATH' && python3 scripts/daily_export_automation.py --retention-days $RETENTION_DAYS >> /var/log/amprealize/daily_export.log 2>&1"

# Create log directory if it doesn't exist
LOG_DIR="/var/log/amprealize"
if [ "$DRY_RUN" = false ]; then
    sudo mkdir -p "$LOG_DIR" 2>/dev/null || mkdir -p "$LOG_DIR" 2>/dev/null || {
        echo "⚠️  Warning: Could not create log directory $LOG_DIR"
        echo "   Falling back to current directory logging"
        LOG_DIR="."
        CRON_CMD="$MINUTE $HOUR * * * cd '$PROJECT_PATH' && python3 scripts/daily_export_automation.py --retention-days $RETENTION_DAYS >> daily_export.log 2>&1"
    }

    # Set appropriate permissions
    if command -v sudo &> /dev/null; then
        sudo chown -R "$USER:$USER" "$LOG_DIR" 2>/dev/null || true
    fi
fi

echo "📋 Proposed cron job:"
echo "   $CRON_CMD"
echo ""

# Check if cron job already exists
EXISTING_CRON=$(crontab -l 2>/dev/null | grep -F "daily_export_automation.py" || true)

if [ -n "$EXISTING_CRON" ]; then
    echo "⚠️  Existing daily export cron job found:"
    echo "   $EXISTING_CRON"
    echo ""

    if [ "$DRY_RUN" = false ]; then
        read -p "Replace existing job? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "❌ Aborted by user"
            exit 1
        fi

        # Remove existing job
        (crontab -l 2>/dev/null | grep -v "daily_export_automation.py" | crontab -) || true
        echo "✅ Removed existing cron job"
    fi
fi

if [ "$DRY_RUN" = true ]; then
    echo "🔍 [DRY RUN] Would install cron job:"
    echo "   $CRON_CMD"
    echo ""
    echo "🔍 [DRY RUN] Would create log file: $LOG_DIR/daily_export.log"
    echo ""
    echo "✅ Dry run complete. Run without --dry-run to actually install."
    exit 0
fi

# Install the cron job
echo "📥 Installing cron job..."
(crontab -l 2>/dev/null; echo "$CRON_CMD") | crontab -

if [ $? -eq 0 ]; then
    echo "✅ Cron job installed successfully"
else
    echo "❌ Failed to install cron job"
    exit 1
fi

# Verify installation
echo ""
echo "🔍 Verifying installation..."
sleep 1
CURRENT_CRON=$(crontab -l 2>/dev/null | grep -F "daily_export_automation.py" || true)

if [ -n "$CURRENT_CRON" ]; then
    echo "✅ Cron job verified:"
    echo "   $CURRENT_CRON"
else
    echo "❌ Cron job verification failed"
    exit 1
fi

# Test the script
echo ""
echo "🧪 Testing daily export script..."
cd "$PROJECT_PATH"

# Run a dry test
python3 scripts/daily_export_automation.py --dry-run

if [ $? -eq 0 ]; then
    echo "✅ Script test passed"
else
    echo "❌ Script test failed"
    echo "   Please check your Python environment and dependencies"
fi

# Show how to view logs
echo ""
echo "📊 Monitoring"
echo "============="
echo "View logs:            tail -f $LOG_DIR/daily_export.log"
echo "View cron status:     crontab -l"
echo "Run manually:         python3 scripts/daily_export_automation.py"
echo "Run with retention:   python3 scripts/daily_export_automation.py --retention-days 7"
echo ""
echo "🎉 Daily export automation setup complete!"
echo "   Next run: $(date -d "$EXPORT_TIME:00 tomorrow" '+%Y-%m-%d %H:%M:%S UTC')"
