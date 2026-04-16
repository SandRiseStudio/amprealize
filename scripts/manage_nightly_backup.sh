#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# Manage the nightly DB backup launchd job
# Usage:
#   ./scripts/manage_nightly_backup.sh install   # install & enable
#   ./scripts/manage_nightly_backup.sh uninstall # disable & remove
#   ./scripts/manage_nightly_backup.sh status    # check if loaded
#   ./scripts/manage_nightly_backup.sh run       # run backup now (manual)
#   ./scripts/manage_nightly_backup.sh logs      # tail the backup log
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_TEMPLATE="${SCRIPT_DIR}/com.amprealize.nightly-db-backup.plist"
BACKUP_SCRIPT="${SCRIPT_DIR}/nightly_db_backup.sh"
LABEL="com.amprealize.nightly-db-backup"
PLIST_DEST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
BACKUP_ROOT="${HOME}/.amprealize/backups"

case "${1:-help}" in
    install)
        echo "Installing nightly DB backup schedule..."

        # Ensure backup dir exists
        mkdir -p "${BACKUP_ROOT}"

        # Make backup script executable
        chmod +x "${BACKUP_SCRIPT}"

        # Generate plist with resolved paths
        sed \
            -e "s|__SCRIPT_PATH__|${BACKUP_SCRIPT}|g" \
            -e "s|__HOME__|${HOME}|g" \
            "${PLIST_TEMPLATE}" > "${PLIST_DEST}"

        # Unload first if already loaded (idempotent)
        launchctl unload "${PLIST_DEST}" 2>/dev/null || true

        # Load the job
        launchctl load "${PLIST_DEST}"

        echo "✅ Installed and loaded: ${LABEL}"
        echo "   Schedule : every day at 9:30 PM (system timezone)"
        echo "   Backups  : ${BACKUP_ROOT}/"
        echo "   Plist    : ${PLIST_DEST}"
        echo "   Logs     : ${BACKUP_ROOT}/nightly_backup.log"
        echo ""
        echo "Run manually: $0 run"
        ;;

    uninstall)
        echo "Uninstalling nightly DB backup schedule..."

        if [[ -f "${PLIST_DEST}" ]]; then
            launchctl unload "${PLIST_DEST}" 2>/dev/null || true
            rm -f "${PLIST_DEST}"
            echo "✅ Unloaded and removed: ${LABEL}"
        else
            echo "⚠️  Not installed (${PLIST_DEST} not found)"
        fi
        ;;

    status)
        if launchctl list "${LABEL}" &>/dev/null; then
            echo "✅ ${LABEL} is loaded"
            launchctl list "${LABEL}"
        else
            echo "❌ ${LABEL} is NOT loaded"
            [[ -f "${PLIST_DEST}" ]] && echo "   Plist exists but is not loaded. Run: $0 install"
        fi
        echo ""
        echo "Last 5 backups:"
        find "${BACKUP_ROOT}" -maxdepth 1 \( -name "*.sql.gz" -o -name "*.db" -o -name "*.tar.gz" \) \
            -exec ls -lht {} + 2>/dev/null | head -5 || echo "  (none)"
        ;;

    run)
        echo "Running backup now..."
        bash "${BACKUP_SCRIPT}"
        ;;

    logs)
        if [[ -f "${BACKUP_ROOT}/nightly_backup.log" ]]; then
            tail -50 "${BACKUP_ROOT}/nightly_backup.log"
        else
            echo "No backup log found yet."
        fi
        ;;

    help|*)
        echo "Usage: $0 {install|uninstall|status|run|logs}"
        echo ""
        echo "  install   — Install launchd job (runs nightly at 9:30 PM)"
        echo "  uninstall — Remove launchd job"
        echo "  status    — Check if job is loaded + list recent backups"
        echo "  run       — Run a backup right now"
        echo "  logs      — Show recent backup log entries"
        ;;
esac
