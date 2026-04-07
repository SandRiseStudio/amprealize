#!/usr/bin/env bash
# DuckDB Disaster Recovery Backup Script
# Implements Parquet exports + full database backup
# RTO: 1 hr, RPO: 15 min

set -euo pipefail

# Configuration
BACKUP_DIR="${BACKUP_DIR:-/var/backups/amprealize/duckdb}"
S3_BUCKET="${S3_BUCKET:-s3://amprealize-backups/duckdb}"
RETENTION_DAYS="${RETENTION_DAYS:-90}"
DUCKDB_PATH="${DUCKDB_PATH:-/var/lib/amprealize/analytics.duckdb}"

# Logging
log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*" | tee -a "${BACKUP_DIR}/backup.log"
}

# Create backup directory
mkdir -p "${BACKUP_DIR}"

# Generate timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="duckdb_backup_${TIMESTAMP}"
BACKUP_PATH="${BACKUP_DIR}/${BACKUP_NAME}"

mkdir -p "${BACKUP_PATH}"

log "Starting DuckDB backup: ${BACKUP_NAME}"

# Check if DuckDB file exists
if [ ! -f "${DUCKDB_PATH}" ]; then
    log "❌ DuckDB file not found: ${DUCKDB_PATH}"
    exit 1
fi

# 1. Export tables to Parquet (using Python + DuckDB API)
log "Exporting tables to Parquet..."

python3 <<PYTHON_SCRIPT
import duckdb
import sys
import os

try:
    conn = duckdb.connect("${DUCKDB_PATH}", read_only=True)

    # Get all tables
    tables = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()

    print(f"Found {len(tables)} tables to export")

    for (table_name,) in tables:
        parquet_file = "${BACKUP_PATH}/${table_name}.parquet"
        print(f"Exporting {table_name} to Parquet...")

        conn.execute(f"""
            COPY (SELECT * FROM {table_name})
            TO '{parquet_file}'
            (FORMAT PARQUET, COMPRESSION ZSTD)
        """)

        file_size = os.path.getsize(parquet_file) / 1048576  # MB
        print(f"✅ {table_name}: {file_size:.2f} MB")

    # Export metadata
    metadata_file = "${BACKUP_PATH}/metadata.json"
    conn.execute(f"""
        COPY (
            SELECT
                table_name,
                (SELECT COUNT(*) FROM information_schema.columns
                 WHERE table_name = t.table_name) as column_count,
                (SELECT COUNT(*) FROM information_schema.tables
                 WHERE table_name = t.table_name) as row_count_estimate
            FROM information_schema.tables t
            WHERE table_schema = 'main'
        ) TO '{metadata_file}' (FORMAT JSON)
    """)

    conn.close()
    print("✅ Parquet export completed")

except Exception as e:
    print(f"❌ Export failed: {str(e)}")
    sys.exit(1)
PYTHON_SCRIPT

if [ $? -ne 0 ]; then
    log "❌ Parquet export failed"
    exit 1
fi

log "✅ Parquet export completed"

# 2. Copy full DuckDB file (for complete backup)
log "Copying full DuckDB database..."
cp "${DUCKDB_PATH}" "${BACKUP_PATH}/analytics.duckdb" || {
    log "❌ Failed to copy DuckDB file"
    exit 1
}

DB_SIZE=$(du -sh "${BACKUP_PATH}/analytics.duckdb" | cut -f1)
log "✅ DuckDB file copied (${DB_SIZE})"

# 3. Copy WAL file if exists
if [ -f "${DUCKDB_PATH}.wal" ]; then
    log "Copying WAL file..."
    cp "${DUCKDB_PATH}.wal" "${BACKUP_PATH}/analytics.duckdb.wal" || {
        log "⚠️  Failed to copy WAL file (non-critical)"
    }
    log "✅ WAL file copied"
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
        --storage-class STANDARD_IA \
        --metadata "backup-type=duckdb,timestamp=${TIMESTAMP},rpo=15min" || {
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
  "type": "duckdb_full_backup",
  "size_bytes": ${BACKUP_SIZE},
  "database_file": "analytics.duckdb",
  "export_format": "parquet",
  "rpo_minutes": 15,
  "rto_hours": 1,
  "s3_location": "${S3_BUCKET}/${BACKUP_NAME}.tar.gz",
  "retention_days": ${RETENTION_DAYS}
}
EOF

if command -v aws &> /dev/null; then
    aws s3 cp "${BACKUP_DIR}/${BACKUP_NAME}.meta.json" "${S3_BUCKET}/${BACKUP_NAME}.meta.json"
fi

# 7. Cleanup old local backups (keep based on retention)
log "Cleaning up old local backups..."
find "${BACKUP_DIR}" -name "duckdb_backup_*.tar.gz" -mtime +${RETENTION_DAYS} -exec rm -f {} \; 2>/dev/null || true
find "${BACKUP_DIR}" -name "duckdb_backup_*.meta.json" -mtime +${RETENTION_DAYS} -exec rm -f {} \; 2>/dev/null || true

# 8. Verify backup integrity
log "Verifying backup integrity..."
if tar -tzf "${BACKUP_DIR}/${BACKUP_NAME}.tar.gz" > /dev/null 2>&1; then
    log "✅ Backup integrity verified"
else
    log "❌ Backup integrity check failed"
    exit 1
fi

# 9. Validate Parquet files (sample check)
log "Validating Parquet files..."
python3 <<PYTHON_VALIDATION
import sys
import os

try:
    # Just verify the compressed archive contains .parquet files
    import tarfile

    with tarfile.open("${BACKUP_DIR}/${BACKUP_NAME}.tar.gz", "r:gz") as tar:
        parquet_files = [m for m in tar.getmembers() if m.name.endswith('.parquet')]
        print(f"✅ Found {len(parquet_files)} Parquet files in backup")

        if len(parquet_files) == 0:
            print("⚠️  No Parquet files found (unexpected)")
            sys.exit(1)

except Exception as e:
    print(f"❌ Validation failed: {str(e)}")
    sys.exit(1)
PYTHON_VALIDATION

if [ $? -ne 0 ]; then
    log "❌ Parquet validation failed"
    exit 1
fi

# 10. Get database info for validation
DB_INFO=$(python3 <<PYTHON_INFO
import duckdb
try:
    conn = duckdb.connect("${DUCKDB_PATH}", read_only=True)

    table_count = conn.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='main'").fetchone()[0]

    # Get approximate total rows (may be slow for large DBs)
    print(f"Tables: {table_count}")

    conn.close()
except Exception as e:
    print(f"Error: {str(e)}")
PYTHON_INFO
)

log "DuckDB snapshot metadata:"
log "  - ${DB_INFO}"
log "  - Database size: ${DB_SIZE}"

# 11. Record action in amprealize
if command -v amprealize &> /dev/null; then
    amprealize record-action \
        --service duckdb \
        --action dr_backup \
        --status success \
        --metadata "{\"backup_name\": \"${BACKUP_NAME}\", \"size_mb\": $((BACKUP_SIZE / 1048576))}" \
        --behaviors "behavior_align_storage_layers,behavior_orchestrate_cicd" 2>/dev/null || true
fi

log "✅ DuckDB backup completed successfully: ${BACKUP_NAME}"
log "   - Size: $(du -sh "${BACKUP_DIR}/${BACKUP_NAME}.tar.gz" | cut -f1)"
log "   - Database: ${DB_SIZE}"
log "   - S3: ${S3_BUCKET}/${BACKUP_NAME}.tar.gz"
log "   - RPO: 15 minutes, RTO: 1 hour"
log "   - Retention: ${RETENTION_DAYS} days"
