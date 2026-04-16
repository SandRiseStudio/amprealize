#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# Nightly Database Backup — Environment-Aware
# ─────────────────────────────────────────────────────────────────────
# Detects the active database environment (local Postgres, Neon cloud,
# SQLite, etc.) and creates a timestamped backup.
#
# Runs via macOS launchd every night at 9:30 PM PST.
#
# Usage:
#   ./scripts/nightly_db_backup.sh            # auto-detect environment
#   ./scripts/nightly_db_backup.sh --list     # list available backups
#   ./scripts/nightly_db_backup.sh --prune 30 # delete backups older than N days
#
# Environment variables (all optional — auto-detected from .env/config):
#   BACKUP_ROOT          Override backup storage directory
#   AMPREALIZE_PG_DSN    Postgres DSN (highest priority)
#   DATABASE_URL         Postgres DSN (fallback)
#   RETENTION_DAYS       Days to keep backups (default: 30)
#   MAX_RETRIES          Retry attempts on failure (default: 3)
#   RETRY_BASE_DELAY     Initial retry delay in seconds (default: 5)
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Paths ────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Load .env if present (same resolution order as settings.py)
for _env in "${PROJECT_ROOT}/.env" "${HOME}/.amprealize/.env"; do
    if [[ -f "$_env" ]]; then
        # shellcheck disable=SC1090
        set -a; source "$_env"; set +a
        break
    fi
done

BACKUP_ROOT="${BACKUP_ROOT:-${HOME}/.amprealize/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="${BACKUP_ROOT}/nightly_backup.log"
MAX_RETRIES="${MAX_RETRIES:-3}"
RETRY_BASE_DELAY="${RETRY_BASE_DELAY:-5}"
LAST_BACKUP_FILE=""

# ── Logging ──────────────────────────────────────────────────────────
mkdir -p "${BACKUP_ROOT}"

log() {
    local msg="[$(date +'%Y-%m-%d %H:%M:%S %Z')] $*"
    echo "$msg" | tee -a "${LOG_FILE}"
}

die() { log "❌ $*"; exit 1; }

# ── Subcommands ──────────────────────────────────────────────────────
if [[ "${1:-}" == "--list" ]]; then
    echo "Available backups in ${BACKUP_ROOT}:"
    find "${BACKUP_ROOT}" -maxdepth 1 \( -name "*.sql.gz" -o -name "*.db" -o -name "*.dump" \) \
        -exec ls -lh {} \; | sort -k6,7
    exit 0
fi

if [[ "${1:-}" == "--prune" ]]; then
    days="${2:-${RETENTION_DAYS}}"
    log "Pruning backups older than ${days} days..."
    find "${BACKUP_ROOT}" -maxdepth 1 \( -name "*.sql.gz" -o -name "*.db" -o -name "*.dump" -o -name "*.meta.json" \) \
        -mtime +"${days}" -delete -print | while read -r f; do log "  deleted: $f"; done
    log "✅ Prune complete"
    exit 0
fi

# ── Environment Detection ────────────────────────────────────────────

detect_via_breakeramp() {
    if ! command -v breakeramp &>/dev/null; then
        return 1
    fi

    local json
    json="$(breakeramp list --json --no-reconcile 2>/dev/null)" || return 1
    [[ -z "$json" || "$json" == "[]" ]] && return 1

    local entry
    entry="$(echo "$json" | python3 -c "
import json, sys
envs = json.load(sys.stdin)
applied = [e for e in envs if e.get('phase') == 'APPLIED']
pick = applied[0] if applied else envs[0]
import json as j
print(j.dumps(pick))
" 2>/dev/null)" || return 1

    [[ -z "$entry" ]] && return 1

    BREAKERAMP_ENV="$(echo "$entry"   | python3 -c "import json,sys; print(json.load(sys.stdin).get('environment',''))")"
    BREAKERAMP_BLUEPRINT="$(echo "$entry" | python3 -c "import json,sys; print(json.load(sys.stdin).get('blueprint_id',''))")"
    BREAKERAMP_DSN="$(echo "$entry"   | python3 -c "
import json, sys
e = json.load(sys.stdin)
outputs = e.get('environment_outputs') or {}
pg = outputs.get('postgres') or {}
print(pg.get('url', ''))
")"

    [[ -n "$BREAKERAMP_ENV" ]] && return 0
    return 1
}

resolve_dsn() {
    # 1. BreakerAmp DSN (from environment_outputs)
    if [[ -n "${BREAKERAMP_DSN:-}" ]]; then
        echo "$BREAKERAMP_DSN"
        return
    fi

    # 2. Amprealize context config (~/.amprealize/config.yaml)
    local config_file="${HOME}/.amprealize/config.yaml"
    if [[ -f "$config_file" ]]; then
        local ctx_dsn
        ctx_dsn="$(python3 -c "
import yaml
with open('${config_file}') as f:
    cfg = yaml.safe_load(f) or {}
ctx_name = cfg.get('current_context', 'default')
ctx = (cfg.get('contexts') or {}).get(ctx_name, {})
dsn = (ctx.get('storage', {}).get('postgres', {}) or {}).get('dsn', '')
if dsn:
    print(dsn)
" 2>/dev/null || true)"
        if [[ -n "$ctx_dsn" ]]; then
            echo "$ctx_dsn"
            return
        fi
    fi

    # 3. Explicit env var
    local dsn="${AMPREALIZE_PG_DSN:-${DATABASE_URL:-}}"
    if [[ -n "$dsn" ]]; then
        echo "$dsn"
        return
    fi

    # 4. Python config system
    local py="${PROJECT_ROOT}/.venv/bin/python"
    [[ -x "$py" ]] || py="python3"

    dsn="$("$py" -c "
import os, sys
sys.path.insert(0, '${PROJECT_ROOT}')
os.chdir('${PROJECT_ROOT}')
try:
    from amprealize.config.settings import Settings
    s = Settings()
    print(s.database.postgres_url)
except Exception:
    pass
" 2>/dev/null || true)"

    if [[ -n "$dsn" ]]; then
        echo "$dsn"
        return
    fi
}

classify_host() {
    local host="$1"
    case "$host" in
        localhost|127.0.0.1|::1|host.containers.internal) echo "local-postgres" ;;
        *.neon.tech)              echo "neon-cloud"     ;;
        *.rds.amazonaws.com)      echo "aws-rds"        ;;
        *.gcp.*.neon.tech|*.cloud-sql.*) echo "gcp-cloud" ;;
        *.database.azure.com)     echo "azure-db"       ;;
        *)                        echo "remote-postgres" ;;
    esac
}

detect_environment() {
    # Strategy 1: BreakerAmp
    if detect_via_breakeramp; then
        log "BreakerAmp active: env=${BREAKERAMP_ENV} blueprint=${BREAKERAMP_BLUEPRINT}" >&2
        case "${BREAKERAMP_ENV}" in
            development|dev|local*)   echo "local-postgres" ;;
            staging|stg)              echo "staging-postgres" ;;
            production|prod)          echo "production-postgres" ;;
            cloud-dev|cloud_dev)      echo "neon-cloud" ;;
            *)
                if [[ -n "${BREAKERAMP_DSN:-}" ]]; then
                    local host
                    host="$(echo "$BREAKERAMP_DSN" | sed -E 's|.*@([^:/]+).*|\1|')"
                    classify_host "$host"
                else
                    echo "${BREAKERAMP_ENV}-postgres"
                fi
                ;;
        esac
        return
    fi

    # Strategy 2: DSN-based
    local dsn
    dsn="$(resolve_dsn)"
    if [[ -n "$dsn" ]]; then
        local host
        host="$(echo "$dsn" | sed -E 's|.*@([^:/]+).*|\1|')"
        classify_host "$host"
        return
    fi

    # Strategy 3: File-based
    if [[ -f "${PROJECT_ROOT}/.amprealize/amprealize.db" ]]; then
        echo "sqlite"
        return
    fi
    if [[ -f "${PROJECT_ROOT}/.amprealize/state.json" ]]; then
        echo "json"
        return
    fi

    echo "unknown"
}

get_dsn() {
    resolve_dsn
}

# ── Backup Functions ─────────────────────────────────────────────────

backup_postgres() {
    local env_label="$1"
    local dsn
    dsn="$(get_dsn)"
    if [[ -z "$dsn" ]]; then
        log "❌ No Postgres DSN found for environment: ${env_label}"
        return 1
    fi

    local out_file="${BACKUP_ROOT}/${env_label}_${TIMESTAMP}.sql.gz"

    log "Backing up ${env_label} Postgres → ${out_file}"

    if ! pg_dump "${dsn}" --no-owner --no-acl --clean --if-exists 2>>"${LOG_FILE}" | gzip > "${out_file}"; then
        rm -f "${out_file}"
        log "❌ pg_dump failed for ${env_label}"
        return 1
    fi

    local size
    size="$(du -h "${out_file}" | cut -f1)"
    log "✅ Postgres backup complete (${size}): ${out_file}"

    write_meta "${out_file}" "${env_label}" "postgres" "${size}"
    LAST_BACKUP_FILE="${out_file}"
}

backup_neon() {
    local dsn
    dsn="$(get_dsn)"
    if [[ -z "$dsn" ]]; then
        log "❌ No Neon DSN found"
        return 1
    fi

    local out_file="${BACKUP_ROOT}/neon-cloud_${TIMESTAMP}.sql.gz"

    log "Backing up Neon cloud DB → ${out_file}"

    if ! pg_dump "${dsn}" --no-owner --no-acl --clean --if-exists 2>>"${LOG_FILE}" | gzip > "${out_file}"; then
        rm -f "${out_file}"
        log "❌ pg_dump failed for Neon cloud"
        return 1
    fi

    local size
    size="$(du -h "${out_file}" | cut -f1)"
    log "✅ Neon cloud backup complete (${size}): ${out_file}"

    write_meta "${out_file}" "neon-cloud" "neon-postgres" "${size}"
    LAST_BACKUP_FILE="${out_file}"
}

backup_sqlite() {
    local db_path="${PROJECT_ROOT}/.amprealize/amprealize.db"
    if [[ ! -f "$db_path" ]]; then
        log "❌ SQLite DB not found at ${db_path}"
        return 1
    fi

    local out_file="${BACKUP_ROOT}/sqlite_${TIMESTAMP}.db"

    log "Backing up SQLite → ${out_file}"

    if command -v sqlite3 &>/dev/null; then
        if ! sqlite3 "${db_path}" ".backup '${out_file}'" 2>>"${LOG_FILE}"; then
            log "❌ sqlite3 .backup failed"
            return 1
        fi
    else
        if ! cp "${db_path}" "${out_file}"; then
            log "❌ cp failed for SQLite backup"
            return 1
        fi
    fi

    local size
    size="$(du -h "${out_file}" | cut -f1)"
    log "✅ SQLite backup complete (${size}): ${out_file}"

    write_meta "${out_file}" "sqlite" "sqlite" "${size}"
    LAST_BACKUP_FILE="${out_file}"
}

backup_json() {
    local json_dir="${PROJECT_ROOT}/.amprealize"
    if [[ ! -d "$json_dir" ]]; then
        log "❌ JSON storage dir not found at ${json_dir}"
        return 1
    fi

    local out_file="${BACKUP_ROOT}/json_${TIMESTAMP}.tar.gz"

    log "Backing up JSON state → ${out_file}"

    if ! tar -czf "${out_file}" -C "$(dirname "${json_dir}")" "$(basename "${json_dir}")" 2>>"${LOG_FILE}"; then
        rm -f "${out_file}"
        log "❌ tar failed for JSON state"
        return 1
    fi

    local size
    size="$(du -h "${out_file}" | cut -f1)"
    log "✅ JSON backup complete (${size}): ${out_file}"

    write_meta "${out_file}" "json" "json" "${size}"
    LAST_BACKUP_FILE="${out_file}"
}

# ── Metadata Sidecar ─────────────────────────────────────────────────

write_meta() {
    local backup_file="$1" env_label="$2" backend="$3" size="$4"
    local meta_file="${backup_file}.meta.json"
    cat > "$meta_file" <<EOF
{
    "timestamp": "${TIMESTAMP}",
    "environment": "${env_label}",
    "backend": "${backend}",
    "size": "${size}",
    "hostname": "$(hostname)",
    "script_version": "1.1.0",
    "retention_days": ${RETENTION_DAYS}
}
EOF
}

# ── Pre-flight Checks ────────────────────────────────────────────────

preflight_checks() {
    local env_label="$1"
    local errors=0

    log "── Pre-flight checks ──"

    # 1. Required tools
    for cmd in python3 gzip date find; do
        if ! command -v "$cmd" &>/dev/null; then
            log "  ✗ Missing required command: $cmd"
            ((errors++))
        fi
    done

    # 2. Backend-specific checks
    case "$env_label" in
        *postgres*|neon-cloud|aws-rds|gcp-cloud|azure-db)
            if ! command -v pg_dump &>/dev/null; then
                log "  ✗ pg_dump not found — install postgresql client tools"
                ((errors++))
            else
                log "  ✓ pg_dump $(pg_dump --version | head -1 | awk '{print $NF}')"
            fi

            local dsn
            dsn="$(get_dsn)"
            if [[ -z "$dsn" ]]; then
                log "  ✗ No DSN resolved for ${env_label}"
                ((errors++))
            else
                local host
                host="$(echo "$dsn" | sed -E 's|.*@([^:/]+).*|\1|')"
                log "  ✓ DSN resolved (host: ${host})"

                # Connectivity check
                if command -v pg_isready &>/dev/null; then
                    if pg_isready -d "$dsn" -t 10 &>/dev/null; then
                        log "  ✓ Database reachable (pg_isready)"
                    else
                        log "  ✗ Database unreachable at ${host} (pg_isready failed)"
                        ((errors++))
                    fi
                elif command -v psql &>/dev/null; then
                    if psql "$dsn" -c "SELECT 1" &>/dev/null; then
                        log "  ✓ Database reachable (psql)"
                    else
                        log "  ✗ Database unreachable at ${host} (psql test failed)"
                        ((errors++))
                    fi
                else
                    log "  ⚠ Cannot verify connectivity (no pg_isready or psql)"
                fi
            fi
            ;;
        sqlite)
            local db_path="${PROJECT_ROOT}/.amprealize/amprealize.db"
            if [[ ! -f "$db_path" ]]; then
                log "  ✗ SQLite DB not found at ${db_path}"
                ((errors++))
            else
                log "  ✓ SQLite DB exists ($(du -h "$db_path" | cut -f1))"
            fi
            ;;
        json)
            if [[ ! -d "${PROJECT_ROOT}/.amprealize" ]]; then
                log "  ✗ JSON state dir not found"
                ((errors++))
            else
                log "  ✓ JSON state directory exists"
            fi
            ;;
    esac

    # 3. Disk space (require at least 500MB free)
    local avail_kb
    avail_kb="$(df -k "${BACKUP_ROOT}" | tail -1 | awk '{print $4}')"
    local avail_mb=$((avail_kb / 1024))
    if [[ "$avail_mb" -lt 500 ]]; then
        log "  ✗ Low disk space: ${avail_mb}MB free (need ≥500MB)"
        ((errors++))
    else
        log "  ✓ Disk space: ${avail_mb}MB available"
    fi

    # 4. Backup directory writable
    if ! touch "${BACKUP_ROOT}/.write_test" 2>/dev/null; then
        log "  ✗ Backup directory not writable: ${BACKUP_ROOT}"
        ((errors++))
    else
        rm -f "${BACKUP_ROOT}/.write_test"
        log "  ✓ Backup directory writable"
    fi

    if [[ "$errors" -gt 0 ]]; then
        log "  ✗ Pre-flight failed with ${errors} error(s)"
        return 1
    fi

    log "  ✓ All pre-flight checks passed"
    return 0
}

# ── Post-Backup Validation ───────────────────────────────────────────

validate_backup() {
    local backup_file="$1"
    local errors=0

    log "── Post-backup validation ──"

    # 1. File exists and non-empty
    if [[ ! -f "$backup_file" ]]; then
        log "  ✗ Backup file missing: $backup_file"
        return 1
    fi

    local size size_bytes
    size="$(du -h "$backup_file" | cut -f1)"
    size_bytes="$(wc -c < "$backup_file" | tr -d ' ')"

    if [[ "$size_bytes" -lt 100 ]]; then
        log "  ✗ Backup suspiciously small: ${size} (${size_bytes} bytes)"
        return 1
    fi
    log "  ✓ File exists (${size}, ${size_bytes} bytes)"

    # 2. Format-specific integrity checks
    case "$backup_file" in
        *.sql.gz)
            # gzip integrity
            if ! gzip -t "$backup_file" 2>/dev/null; then
                log "  ✗ gzip integrity check FAILED"
                ((errors++))
            else
                log "  ✓ gzip integrity OK"
            fi

            # Decompress once to a temp file for all content checks
            local tmpfile
            tmpfile="$(mktemp)"
            if ! gunzip -c "$backup_file" > "$tmpfile" 2>/dev/null; then
                log "  ✗ Could not decompress backup for content checks"
                rm -f "$tmpfile"
                return 1
            fi

            # pg_dump header
            if ! head -5 "$tmpfile" | grep -q "PostgreSQL database dump"; then
                log "  ✗ Missing pg_dump header"
                ((errors++))
            else
                log "  ✓ pg_dump header present"
            fi

            # Completion marker
            if ! tail -5 "$tmpfile" | grep -q "PostgreSQL database dump complete"; then
                log "  ✗ Missing completion marker — dump may be truncated"
                ((errors++))
            else
                log "  ✓ Completion marker present (dump not truncated)"
            fi

            # Schema / table / data counts
            local create_count copy_count line_count schemas
            create_count="$(grep -c '^CREATE TABLE' "$tmpfile" || true)"
            copy_count="$(grep -c '^COPY ' "$tmpfile" || true)"
            line_count="$(wc -l < "$tmpfile" | tr -d ' ')"
            schemas="$(grep '^CREATE TABLE' "$tmpfile" | awk '{print $3}' | cut -d. -f1 | sort -u | tr '\n' ' ')"

            if [[ "$create_count" -eq 0 ]]; then
                log "  ✗ No CREATE TABLE statements found"
                ((errors++))
            else
                log "  ✓ ${create_count} tables across schemas: ${schemas}"
            fi

            if [[ "$copy_count" -eq 0 ]]; then
                log "  ⚠ No COPY (data) statements — database may be empty"
            else
                log "  ✓ ${copy_count} COPY (data) statements"
            fi

            # CREATE/COPY parity check
            if [[ "$create_count" -gt 0 && "$copy_count" -gt 0 ]]; then
                local diff=$(( create_count - copy_count ))
                diff=${diff#-}
                if [[ "$diff" -gt 5 ]]; then
                    log "  ⚠ Table/data mismatch: ${create_count} tables vs ${copy_count} COPY statements"
                fi
            fi

            if [[ "$line_count" -lt 10 ]]; then
                log "  ✗ Only ${line_count} SQL lines — dump appears empty or broken"
                ((errors++))
            else
                log "  ✓ ${line_count} total SQL lines"
            fi

            # Compare table count with live database
            local dsn
            dsn="$(get_dsn)"
            if [[ -n "$dsn" ]] && command -v psql &>/dev/null; then
                local live_count
                live_count="$(psql "$dsn" -tAc \
                    "SELECT count(*) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema')" \
                    2>/dev/null || echo "")"
                if [[ -n "$live_count" && "$create_count" -gt 0 ]]; then
                    local tbl_diff=$(( live_count - create_count ))
                    tbl_diff=${tbl_diff#-}
                    if [[ "$tbl_diff" -le 2 ]]; then
                        log "  ✓ Table count matches live DB (backup: ${create_count}, live: ${live_count})"
                    elif [[ "$tbl_diff" -le 5 ]]; then
                        log "  ⚠ Table count differs slightly (backup: ${create_count}, live: ${live_count})"
                    else
                        log "  ✗ Table count mismatch (backup: ${create_count}, live: ${live_count})"
                        ((errors++))
                    fi
                fi
            fi
            rm -f "$tmpfile"
            ;;

        *.db)
            if command -v sqlite3 &>/dev/null; then
                local integrity
                integrity="$(sqlite3 "$backup_file" "PRAGMA integrity_check;" 2>/dev/null || echo "FAIL")"
                if [[ "$integrity" == "ok" ]]; then
                    log "  ✓ SQLite integrity check passed"
                else
                    log "  ✗ SQLite integrity check failed: $integrity"
                    ((errors++))
                fi

                local table_count
                table_count="$(sqlite3 "$backup_file" "SELECT count(*) FROM sqlite_master WHERE type='table';" 2>/dev/null || echo "0")"
                log "  ✓ ${table_count} tables in SQLite backup"
            else
                log "  ⚠ sqlite3 not available — skipping integrity check"
            fi
            ;;

        *.tar.gz)
            if ! tar -tzf "$backup_file" &>/dev/null; then
                log "  ✗ tar archive integrity check failed"
                ((errors++))
            else
                local file_count
                file_count="$(tar -tzf "$backup_file" | wc -l | tr -d ' ')"
                log "  ✓ tar archive OK (${file_count} files)"
            fi
            ;;
    esac

    # 3. Metadata sidecar
    if [[ -f "${backup_file}.meta.json" ]]; then
        if python3 -c "import json, sys; json.load(open(sys.argv[1]))" "${backup_file}.meta.json" 2>/dev/null; then
            log "  ✓ Metadata JSON valid"
        else
            log "  ✗ Metadata JSON is malformed"
            ((errors++))
        fi
    else
        log "  ⚠ No metadata sidecar found"
    fi

    if [[ "$errors" -gt 0 ]]; then
        log "  ✗ Validation failed with ${errors} error(s)"
        return 1
    fi

    log "  ✓ All validation checks passed"
    return 0
}

# ── Retry Wrapper ────────────────────────────────────────────────────

run_with_retry() {
    local backup_fn="$1"
    shift
    local attempt=1
    local delay="${RETRY_BASE_DELAY}"

    while [[ "$attempt" -le "$MAX_RETRIES" ]]; do
        if [[ "$attempt" -gt 1 ]]; then
            log "── Retry attempt ${attempt}/${MAX_RETRIES} (waiting ${delay}s) ──"
            sleep "$delay"
            delay=$((delay * 2))
            TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
        fi

        LAST_BACKUP_FILE=""

        # Attempt the backup (|| true prevents set -e from exiting)
        local rc=0
        "$backup_fn" "$@" && rc=0 || rc=$?

        if [[ "$rc" -ne 0 ]]; then
            log "  Backup attempt ${attempt} failed (exit code: ${rc})"
            ((attempt++))
            continue
        fi

        # Validate the backup
        if [[ -z "$LAST_BACKUP_FILE" ]]; then
            log "  ✗ No backup file produced on attempt ${attempt}"
            ((attempt++))
            continue
        fi

        local vrc=0
        validate_backup "$LAST_BACKUP_FILE" && vrc=0 || vrc=$?

        if [[ "$vrc" -eq 0 ]]; then
            return 0
        fi

        log "  Validation failed on attempt ${attempt} — cleaning up bad backup"
        rm -f "$LAST_BACKUP_FILE" "${LAST_BACKUP_FILE}.meta.json"
        ((attempt++))
    done

    die "Backup failed after ${MAX_RETRIES} attempts"
}

# ── Main ─────────────────────────────────────────────────────────────

main() {
    log "═══════════════════════════════════════════════════════════"
    log "Nightly DB Backup — $(date)"
    log "═══════════════════════════════════════════════════════════"

    local env
    env="$(detect_environment)"
    log "Detected environment: ${env}"

    # ── Pre-flight checks ──
    local prc=0
    preflight_checks "$env" && prc=0 || prc=$?
    if [[ "$prc" -ne 0 ]]; then
        die "Pre-flight checks failed — aborting backup"
    fi

    # ── Run backup with retry + post-validation ──
    case "${env}" in
        local-postgres)           run_with_retry backup_postgres "local-dev" ;;
        staging-postgres)         run_with_retry backup_postgres "staging" ;;
        production-postgres)      run_with_retry backup_postgres "production" ;;
        neon-cloud)               run_with_retry backup_neon ;;
        aws-rds)                  run_with_retry backup_postgres "aws-rds" ;;
        gcp-cloud)                run_with_retry backup_postgres "gcp-cloud" ;;
        azure-db)                 run_with_retry backup_postgres "azure-db" ;;
        remote-postgres|*-postgres) run_with_retry backup_postgres "${env%-postgres}" ;;
        sqlite)                   run_with_retry backup_sqlite ;;
        json)                     run_with_retry backup_json ;;
        unknown)
            log "⚠️  No database detected — nothing to back up."
            log "    Set AMPREALIZE_PG_DSN or DATABASE_URL, or ensure .amprealize/ exists."
            exit 0
            ;;
        *)
            die "Unrecognized environment: ${env}"
            ;;
    esac

    # Auto-prune old backups
    local pruned
    pruned="$(find "${BACKUP_ROOT}" -maxdepth 1 \( -name "*.sql.gz" -o -name "*.db" -o -name "*.dump" -o -name "*.tar.gz" -o -name "*.meta.json" \) \
        -mtime +"${RETENTION_DAYS}" -delete -print 2>/dev/null | wc -l | tr -d ' ')"
    if [[ "$pruned" -gt 0 ]]; then
        log "🗑  Pruned ${pruned} backup file(s) older than ${RETENTION_DAYS} days"
    fi

    log "✅ Nightly backup finished"
    log ""
}

main "$@"
