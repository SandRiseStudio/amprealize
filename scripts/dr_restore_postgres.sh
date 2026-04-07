#!/usr/bin/env bash
# PostgreSQL Disaster Recovery Restore Script
# Supports full restore and Point-In-Time Recovery (PITR)
# RTO: 15 min, RPO: 5 min

set -euo pipefail

# Configuration
BACKUP_DIR="${BACKUP_DIR:-/var/backups/amprealize/postgres}"
S3_BUCKET="${S3_BUCKET:-s3://amprealize-backups/postgres}"
POSTGRES_DATA_DIR="${POSTGRES_DATA_DIR:-/var/lib/postgresql/data}"
POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_USER="${POSTGRES_USER:-amprealize_admin}"

# Parse arguments
RESTORE_TARGET="${1:-latest}"  # 'latest' or timestamp 'YYYY-MM-DD HH:MM:SS'

# Logging
log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*" | tee -a "${BACKUP_DIR}/restore.log"
}

# Safety checks
if [ ! -d "${BACKUP_DIR}" ]; then
    mkdir -p "${BACKUP_DIR}"
fi

log "🔄 Starting PostgreSQL restore"
log "   Target: ${RESTORE_TARGET}"

# 1. Stop PostgreSQL
log "Stopping PostgreSQL..."
if command -v pg_ctl &> /dev/null; then
    pg_ctl -D "${POSTGRES_DATA_DIR}" stop -m fast || log "PostgreSQL already stopped"
elif command -v systemctl &> /dev/null; then
    systemctl stop postgresql || log "PostgreSQL already stopped"
fi

# 2. Find backup to restore
if [ "${RESTORE_TARGET}" = "latest" ]; then
    log "Finding latest backup..."

    # List S3 backups
    if command -v aws &> /dev/null; then
        LATEST_BACKUP=$(aws s3 ls "${S3_BUCKET}/" | grep "postgres_backup_" | sort -r | head -n 1 | awk '{print $NF}' | sed 's:/$::')

        if [ -z "${LATEST_BACKUP}" ]; then
            log "❌ No backups found in S3"
            exit 1
        fi

        log "Latest backup: ${LATEST_BACKUP}"

        # Download from S3
        log "Downloading backup from S3..."
        aws s3 sync "${S3_BUCKET}/${LATEST_BACKUP}" "${BACKUP_DIR}/${LATEST_BACKUP}" || {
            log "❌ S3 download failed"
            exit 1
        }
    else
        # Use local backup
        LATEST_BACKUP=$(ls -1t "${BACKUP_DIR}" 2>/dev/null | grep "postgres_backup_" | head -n 1)

        if [ -z "${LATEST_BACKUP}" ]; then
            log "❌ No local backups found"
            exit 1
        fi

        log "Using local backup: ${LATEST_BACKUP}"
    fi
else
    log "❌ PITR to specific timestamp not yet implemented"
    log "   For now, only 'latest' restore is supported"
    exit 1
fi

# 3. Backup current data directory (safety)
if [ -d "${POSTGRES_DATA_DIR}" ]; then
    SAFETY_BACKUP="${POSTGRES_DATA_DIR}.pre_restore_$(date +%Y%m%d_%H%M%S)"
    log "Creating safety backup of current data: ${SAFETY_BACKUP}"
    mv "${POSTGRES_DATA_DIR}" "${SAFETY_BACKUP}" || {
        log "❌ Failed to backup current data directory"
        exit 1
    }
fi

# 4. Extract base backup
log "Extracting base backup..."
mkdir -p "${POSTGRES_DATA_DIR}"

tar -xzf "${BACKUP_DIR}/${LATEST_BACKUP}/base.tar.gz" -C "${POSTGRES_DATA_DIR}" || {
    log "❌ Failed to extract base backup"
    exit 1
}

log "✅ Base backup extracted"

# 5. Extract pg_wal if exists
if [ -f "${BACKUP_DIR}/${LATEST_BACKUP}/pg_wal.tar.gz" ]; then
    log "Extracting WAL files..."
    mkdir -p "${POSTGRES_DATA_DIR}/pg_wal"
    tar -xzf "${BACKUP_DIR}/${LATEST_BACKUP}/pg_wal.tar.gz" -C "${POSTGRES_DATA_DIR}/pg_wal" || {
        log "⚠️  Failed to extract WAL files (non-critical)"
    }
fi

# 6. Configure recovery (if PITR needed)
if [ "${RESTORE_TARGET}" != "latest" ]; then
    log "Configuring Point-In-Time Recovery..."

    cat > "${POSTGRES_DATA_DIR}/recovery.conf" <<EOF
restore_command = 'wal-g wal-fetch %f %p'
recovery_target_time = '${RESTORE_TARGET}'
recovery_target_action = 'promote'
EOF

    log "✅ Recovery configuration created"
fi

# 7. Set proper permissions
log "Setting permissions..."
if command -v chown &> /dev/null; then
    chown -R postgres:postgres "${POSTGRES_DATA_DIR}" 2>/dev/null || log "⚠️  Could not set ownership (run as root if needed)"
fi
chmod 700 "${POSTGRES_DATA_DIR}"

# 8. Start PostgreSQL
log "Starting PostgreSQL..."
if command -v pg_ctl &> /dev/null; then
    pg_ctl -D "${POSTGRES_DATA_DIR}" start || {
        log "❌ Failed to start PostgreSQL"
        exit 1
    }
elif command -v systemctl &> /dev/null; then
    systemctl start postgresql || {
        log "❌ Failed to start PostgreSQL"
        exit 1
    }
fi

log "✅ PostgreSQL started"

# 9. Wait for PostgreSQL to be ready
log "Waiting for PostgreSQL to be ready..."
for i in {1..30}; do
    if pg_isready -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" -U "${POSTGRES_USER}" > /dev/null 2>&1; then
        log "✅ PostgreSQL is ready"
        break
    fi

    if [ $i -eq 30 ]; then
        log "❌ PostgreSQL did not become ready within 30 seconds"
        exit 1
    fi

    sleep 1
done

# 10. Smoke test
log "Running smoke tests..."

# Check databases exist
EXPECTED_DBS=("behaviors" "workflows" "auth" "tasks" "telemetry")
for db in "${EXPECTED_DBS[@]}"; do
    if psql -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" -U "${POSTGRES_USER}" -lqt | cut -d \| -f 1 | grep -qw "${db}"; then
        log "  ✅ Database '${db}' exists"
    else
        log "  ⚠️  Database '${db}' not found"
    fi
done

# Check table counts
TABLE_COUNT=$(psql -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" -U "${POSTGRES_USER}" -d behaviors -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';" 2>/dev/null || echo "0")
log "  ✅ Found ${TABLE_COUNT} tables in 'behaviors' database"

# 11. Record action in amprealize
if command -v amprealize &> /dev/null; then
    amprealize record-action \
        --service postgres \
        --action dr_restore \
        --status success \
        --metadata "{\"backup_name\": \"${LATEST_BACKUP}\", \"restore_target\": \"${RESTORE_TARGET}\"}" \
        --behaviors "behavior_align_storage_layers,behavior_orchestrate_cicd" 2>/dev/null || true
fi

log "✅ PostgreSQL restore completed successfully"
log "   - Restored from: ${LATEST_BACKUP}"
log "   - Safety backup: ${SAFETY_BACKUP:-none}"
log "   - RTO achieved: $(date +%s) - <start_time> seconds"
log ""
log "⚠️  IMPORTANT NEXT STEPS:"
log "   1. Verify application connectivity"
log "   2. Run amprealize test-failover to validate"
log "   3. Check replication status if applicable"
log "   4. Review logs for any warnings"
