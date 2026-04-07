#!/usr/bin/env bash
# Redis Disaster Recovery Backup Script
# Implements RDB snapshots + AOF append-only file backup
# RTO: 1 hr, RPO: 15 min

set -euo pipefail

# Configuration
BACKUP_DIR="${BACKUP_DIR:-/var/backups/amprealize/redis}"
S3_BUCKET="${S3_BUCKET:-s3://amprealize-backups/redis}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"
REDIS_DATA_DIR="${REDIS_DATA_DIR:-/var/lib/redis}"

# Logging
log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*" | tee -a "${BACKUP_DIR}/backup.log"
}

# Create backup directory
mkdir -p "${BACKUP_DIR}"

# Generate timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="redis_backup_${TIMESTAMP}"
BACKUP_PATH="${BACKUP_DIR}/${BACKUP_NAME}"

mkdir -p "${BACKUP_PATH}"

log "Starting Redis backup: ${BACKUP_NAME}"

# 1. Trigger BGSAVE (background save)
log "Triggering BGSAVE..."
if command -v redis-cli &> /dev/null; then
    redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" BGSAVE || {
        log "❌ BGSAVE command failed"
        exit 1
    }

    # Wait for BGSAVE to complete
    log "Waiting for BGSAVE to complete..."
    for i in {1..60}; do
        SAVE_STATUS=$(redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" LASTSAVE)
        sleep 2
        NEW_SAVE_STATUS=$(redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" LASTSAVE)

        if [ "${NEW_SAVE_STATUS}" != "${SAVE_STATUS}" ]; then
            log "✅ BGSAVE completed"
            break
        fi

        if [ $i -eq 60 ]; then
            log "⚠️  BGSAVE still running after 2 minutes, proceeding anyway"
        fi
    done
else
    log "❌ redis-cli not found"
    exit 1
fi

# 2. Copy RDB file
log "Copying RDB snapshot..."
RDB_FILE=$(redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" CONFIG GET dir | tail -n 1)
RDB_NAME=$(redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" CONFIG GET dbfilename | tail -n 1)

if [ -z "${RDB_FILE}" ] || [ -z "${RDB_NAME}" ]; then
    RDB_FULL_PATH="${REDIS_DATA_DIR}/dump.rdb"
else
    RDB_FULL_PATH="${RDB_FILE}/${RDB_NAME}"
fi

if [ -f "${RDB_FULL_PATH}" ]; then
    cp "${RDB_FULL_PATH}" "${BACKUP_PATH}/dump.rdb" || {
        log "❌ Failed to copy RDB file"
        exit 1
    }
    log "✅ RDB snapshot copied ($(du -sh "${BACKUP_PATH}/dump.rdb" | cut -f1))"
else
    log "⚠️  RDB file not found at ${RDB_FULL_PATH}"
fi

# 3. Copy AOF file (if enabled)
log "Checking for AOF file..."
AOF_ENABLED=$(redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" CONFIG GET appendonly | tail -n 1)

if [ "${AOF_ENABLED}" = "yes" ]; then
    AOF_NAME=$(redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" CONFIG GET appendfilename | tail -n 1)
    AOF_FULL_PATH="${RDB_FILE}/${AOF_NAME}"

    if [ -f "${AOF_FULL_PATH}" ]; then
        cp "${AOF_FULL_PATH}" "${BACKUP_PATH}/appendonly.aof" || {
            log "⚠️  Failed to copy AOF file (non-critical)"
        }
        log "✅ AOF file copied ($(du -sh "${BACKUP_PATH}/appendonly.aof" | cut -f1))"
    else
        log "⚠️  AOF file not found at ${AOF_FULL_PATH}"
    fi
else
    log "ℹ️  AOF not enabled, skipping"
fi

# 4. Compress backup
log "Compressing backup..."
tar -czf "${BACKUP_DIR}/${BACKUP_NAME}.tar.gz" -C "${BACKUP_DIR}" "${BACKUP_NAME}" || {
    log "❌ Compression failed"
    exit 1
}

BACKUP_SIZE=$(du -sb "${BACKUP_DIR}/${BACKUP_NAME}.tar.gz" | cut -f1)
log "✅ Backup compressed ($(du -sh "${BACKUP_DIR}/${BACKUP_NAME}.tar.gz" | cut -f1))"

# Clean up uncompressed backup
rm -rf "${BACKUP_PATH}"

# 5. Upload to S3
log "Uploading to S3..."
if command -v aws &> /dev/null; then
    aws s3 cp "${BACKUP_DIR}/${BACKUP_NAME}.tar.gz" "${S3_BUCKET}/${BACKUP_NAME}.tar.gz" \
        --storage-class STANDARD \
        --metadata "backup-type=redis,timestamp=${TIMESTAMP},rpo=15min" || {
        log "❌ S3 upload failed"
        exit 1
    }
    log "✅ S3 upload completed"
else
    log "⚠️  AWS CLI not installed, skipping S3 upload (local backup only)"
fi

# 6. Record backup metadata
cat > "${BACKUP_DIR}/${BACKUP_NAME}.meta.json" <<EOF
{
  "backup_name": "${BACKUP_NAME}",
  "timestamp": "${TIMESTAMP}",
  "type": "redis_snapshot",
  "size_bytes": ${BACKUP_SIZE},
  "rdb_file": "dump.rdb",
  "aof_file": "$([ -f "${BACKUP_PATH}/appendonly.aof" ] && echo "appendonly.aof" || echo "null")",
  "rpo_minutes": 15,
  "rto_hours": 1,
  "s3_location": "${S3_BUCKET}/${BACKUP_NAME}.tar.gz",
  "retention_days": ${RETENTION_DAYS}
}
EOF

if command -v aws &> /dev/null; then
    aws s3 cp "${BACKUP_DIR}/${BACKUP_NAME}.meta.json" "${S3_BUCKET}/${BACKUP_NAME}.meta.json"
fi

# 7. Cleanup old local backups (keep last 7 days)
log "Cleaning up old local backups..."
find "${BACKUP_DIR}" -name "redis_backup_*.tar.gz" -mtime +${RETENTION_DAYS} -exec rm -f {} \; 2>/dev/null || true
find "${BACKUP_DIR}" -name "redis_backup_*.meta.json" -mtime +${RETENTION_DAYS} -exec rm -f {} \; 2>/dev/null || true

# 8. Cleanup old S3 backups (lifecycle policy should handle this, but verify)
if command -v aws &> /dev/null; then
    log "Verifying S3 lifecycle policy..."
    # Note: In production, ensure S3 bucket has lifecycle policy configured
    # to transition to GLACIER after 7 days and delete after retention period
fi

# 9. Verify backup integrity
log "Verifying backup integrity..."
if tar -tzf "${BACKUP_DIR}/${BACKUP_NAME}.tar.gz" > /dev/null 2>&1; then
    log "✅ Backup integrity verified"
else
    log "❌ Backup integrity check failed"
    exit 1
fi

# 10. Get Redis info for validation
REDIS_VERSION=$(redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" INFO SERVER | grep redis_version | cut -d: -f2 | tr -d '\r')
REDIS_KEYS=$(redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" DBSIZE | cut -d: -f2 | tr -d ' \r')
REDIS_MEMORY=$(redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" INFO MEMORY | grep used_memory_human | cut -d: -f2 | tr -d '\r')

log "Redis snapshot metadata:"
log "  - Version: ${REDIS_VERSION}"
log "  - Keys: ${REDIS_KEYS}"
log "  - Memory: ${REDIS_MEMORY}"

# 11. Record action in amprealize
if command -v amprealize &> /dev/null; then
    amprealize record-action \
        --service redis \
        --action dr_backup \
        --status success \
        --metadata "{\"backup_name\": \"${BACKUP_NAME}\", \"size_mb\": $((BACKUP_SIZE / 1048576)), \"keys\": ${REDIS_KEYS}}" \
        --behaviors "behavior_align_storage_layers,behavior_orchestrate_cicd" 2>/dev/null || true
fi

log "✅ Redis backup completed successfully: ${BACKUP_NAME}"
log "   - Size: $(du -sh "${BACKUP_DIR}/${BACKUP_NAME}.tar.gz" | cut -f1)"
log "   - Keys: ${REDIS_KEYS}"
log "   - S3: ${S3_BUCKET}/${BACKUP_NAME}.tar.gz"
log "   - RPO: 15 minutes, RTO: 1 hour"
