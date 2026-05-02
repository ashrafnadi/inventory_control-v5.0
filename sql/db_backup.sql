#!/usr/bin/env bash
# =============================================================================
# pg_backup.sh
# Full backup of all PostgreSQL database objects and data.
#
# Backs up (in order):
#   extensions, types, sequences, tables (schema + data), views,
#   materialized views, functions, procedures, triggers.
#
# Output: a timestamped directory containing:
#   - dump.custom      → pg_dump binary format (fastest restore)
#   - dump.sql         → plain-SQL fallback (human-readable)
#   - schema_only.sql  → DDL only (no data)
#   - manifest.txt     → inventory of every object backed up
#
# Usage:
#   chmod +x pg_backup.sh
#   ./pg_backup.sh [options]
#
# Options:
#   -h HOST       Database host          (default: localhost)
#   -p PORT       Database port          (default: 5432)
#   -U USER       Database user          (default: postgres)
#   -d DATABASE   Database name          (required)
#   -o OUTPUT     Output directory       (default: ./backups)
#   -s SCHEMA     Schema to back up      (default: public)
#   -x            Skip data (schema only)
#   -c            Compress SQL dump      (gzip)
#   -e            Exclude specific table patterns (comma-separated, e.g. "tmp_*,log_*")
#   --help        Show this help
#
# Requirements:
#   pg_dump, psql (PostgreSQL client tools matching the server major version)
#
# Examples:
#   ./pg_backup.sh -d mydb
#   ./pg_backup.sh -h db.example.com -U admin -d mydb -o /var/backups/pg
#   ./pg_backup.sh -d mydb -x                  # schema only
#   ./pg_backup.sh -d mydb -c                  # compress SQL output
#   ./pg_backup.sh -d mydb -e "tmp_*,log_*"   # exclude tables
# =============================================================================

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
PG_HOST="localhost"
PG_PORT="5432"
PG_USER="postgres"
PG_DATABASE=""
OUTPUT_DIR="./backups"
SCHEMA="public"
SCHEMA_ONLY=false
COMPRESS=false
EXCLUDE_PATTERNS=""

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

log()     { echo -e "${CYAN}[$(date '+%H:%M:%S')]${RESET} $*"; }
success() { echo -e "${GREEN}[$(date '+%H:%M:%S')] ✔ $*${RESET}"; }
warn()    { echo -e "${YELLOW}[$(date '+%H:%M:%S')] ⚠ $*${RESET}"; }
error()   { echo -e "${RED}[$(date '+%H:%M:%S')] ✘ $*${RESET}" >&2; }
die()     { error "$*"; exit 1; }

# ── Help ──────────────────────────────────────────────────────────────────────
usage() {
cat <<EOF
${BOLD}Usage:${RESET} $(basename "$0") [options]

${BOLD}Options:${RESET}
  -h HOST       Database host          (default: localhost)
  -p PORT       Database port          (default: 5432)
  -U USER       Database user          (default: postgres)
  -d DATABASE   Database name          (required)
  -o OUTPUT     Output directory       (default: ./backups)
  -s SCHEMA     Schema to back up      (default: public)
  -x            Schema only (no data)
  -c            Compress SQL dump (gzip)
  -e PATTERNS   Exclude table patterns, comma-separated (e.g. "tmp_*,log_*")
  --help        Show this help

${BOLD}Environment variables (alternative to flags):${RESET}
  PGPASSWORD    Password (avoids interactive prompt)
  PGPASSFILE    Path to .pgpass file

${BOLD}Examples:${RESET}
  $(basename "$0") -d mydb
  $(basename "$0") -h db.example.com -U admin -d mydb -o /var/backups/pg
  $(basename "$0") -d mydb -x
  PGPASSWORD=secret $(basename "$0") -d mydb
EOF
}

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h) PG_HOST="$2";          shift 2 ;;
        -p) PG_PORT="$2";          shift 2 ;;
        -U) PG_USER="$2";          shift 2 ;;
        -d) PG_DATABASE="$2";      shift 2 ;;
        -o) OUTPUT_DIR="$2";       shift 2 ;;
        -s) SCHEMA="$2";           shift 2 ;;
        -x) SCHEMA_ONLY=true;      shift   ;;
        -c) COMPRESS=true;         shift   ;;
        -e) EXCLUDE_PATTERNS="$2"; shift 2 ;;
        --help) usage; exit 0      ;;
        *) die "Unknown option: $1. Use --help for usage." ;;
    esac
done

[[ -z "$PG_DATABASE" ]] && die "Database name is required. Use -d <database>."

# ── Pre-flight checks ─────────────────────────────────────────────────────────
for cmd in pg_dump psql; do
    command -v "$cmd" &>/dev/null || die "'$cmd' not found. Install PostgreSQL client tools."
done

# ── Setup output directory ────────────────────────────────────────────────────
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
BACKUP_DIR="${OUTPUT_DIR}/${PG_DATABASE}_${TIMESTAMP}"
mkdir -p "$BACKUP_DIR"

CUSTOM_DUMP="${BACKUP_DIR}/dump.custom"
SQL_DUMP="${BACKUP_DIR}/dump.sql"
SCHEMA_DUMP="${BACKUP_DIR}/schema_only.sql"
MANIFEST="${BACKUP_DIR}/manifest.txt"
LOG_FILE="${BACKUP_DIR}/backup.log"

# Shared psql / pg_dump connection args
CONN_ARGS=(-h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER")
PSQL_ARGS=("${CONN_ARGS[@]}" -d "$PG_DATABASE" -v ON_ERROR_STOP=1)

# ── Test connection ───────────────────────────────────────────────────────────
log "Testing connection to ${PG_HOST}:${PG_PORT}/${PG_DATABASE} as ${PG_USER}..."
psql "${PSQL_ARGS[@]}" -c "SELECT version();" &>/dev/null \
    || die "Cannot connect to database. Check credentials and host."
success "Connection OK"

# ── Build exclude flags for pg_dump ──────────────────────────────────────────
EXCLUDE_FLAGS=()
if [[ -n "$EXCLUDE_PATTERNS" ]]; then
    IFS=',' read -ra PATTERNS <<< "$EXCLUDE_PATTERNS"
    for pat in "${PATTERNS[@]}"; do
        EXCLUDE_FLAGS+=(--exclude-table-data="${SCHEMA}.${pat}")
        warn "Excluding table data matching: ${SCHEMA}.${pat}"
    done
fi

# ── Banner ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════${RESET}"
echo -e "${BOLD}  PostgreSQL Backup${RESET}"
echo -e "${BOLD}═══════════════════════════════════════════════════${RESET}"
echo -e "  Host     : ${CYAN}${PG_HOST}:${PG_PORT}${RESET}"
echo -e "  Database : ${CYAN}${PG_DATABASE}${RESET}"
echo -e "  Schema   : ${CYAN}${SCHEMA}${RESET}"
echo -e "  Output   : ${CYAN}${BACKUP_DIR}${RESET}"
$SCHEMA_ONLY && echo -e "  Mode     : ${YELLOW}SCHEMA ONLY (no data)${RESET}" \
             || echo -e "  Mode     : ${GREEN}SCHEMA + DATA${RESET}"
echo -e "${BOLD}═══════════════════════════════════════════════════${RESET}"
echo ""

{
echo "Backup started: $(date)"
echo "Host:     ${PG_HOST}:${PG_PORT}"
echo "Database: ${PG_DATABASE}"
echo "Schema:   ${SCHEMA}"

# ── 1. Custom binary dump (fastest restore) ───────────────────────────────────
log "Creating binary dump (pg_dump custom format)..."
DUMP_FLAGS=(
    "${CONN_ARGS[@]}"
    --format=custom
    --schema="$SCHEMA"
    --verbose
    --no-password
    "${EXCLUDE_FLAGS[@]}"
)
$SCHEMA_ONLY && DUMP_FLAGS+=(--schema-only)

pg_dump "${DUMP_FLAGS[@]}" "$PG_DATABASE" > "$CUSTOM_DUMP" 2>>"$LOG_FILE"
success "Binary dump saved → dump.custom ($(du -sh "$CUSTOM_DUMP" | cut -f1))"

# ── 2. Plain SQL dump ─────────────────────────────────────────────────────────
log "Creating plain SQL dump..."
DUMP_FLAGS[2]="--format=plain"   # swap format only
pg_dump "${DUMP_FLAGS[@]}" "$PG_DATABASE" > "$SQL_DUMP" 2>>"$LOG_FILE"

if $COMPRESS; then
    gzip -f "$SQL_DUMP"
    SQL_DUMP="${SQL_DUMP}.gz"
    success "Compressed SQL dump saved → dump.sql.gz ($(du -sh "$SQL_DUMP" | cut -f1))"
else
    success "Plain SQL dump saved → dump.sql ($(du -sh "$SQL_DUMP" | cut -f1))"
fi

# ── 3. Schema-only dump (always, even in full mode) ───────────────────────────
log "Creating schema-only dump (DDL)..."
pg_dump "${CONN_ARGS[@]}" \
    --format=plain \
    --schema-only \
    --schema="$SCHEMA" \
    --no-password \
    "$PG_DATABASE" > "$SCHEMA_DUMP" 2>>"$LOG_FILE"
success "Schema dump saved → schema_only.sql ($(du -sh "$SCHEMA_DUMP" | cut -f1))"

# ── 4. Generate manifest ──────────────────────────────────────────────────────
log "Generating object manifest..."

PSQL="psql ${PSQL_ARGS[*]}"

{
echo "============================================================"
echo " BACKUP MANIFEST"
echo " Database : ${PG_DATABASE}"
echo " Schema   : ${SCHEMA}"
echo " Generated: $(date)"
echo "============================================================"
echo ""

echo "─── TABLES ─────────────────────────────────────────────────"
psql "${PSQL_ARGS[@]}" --no-psqlrc -t -A -c \
    "SELECT schemaname||'.'||tablename
     FROM pg_tables
     WHERE schemaname = '${SCHEMA}'
     ORDER BY tablename;" 2>>"$LOG_FILE"

echo ""
echo "─── ROW COUNTS ──────────────────────────────────────────────"
psql "${PSQL_ARGS[@]}" --no-psqlrc -t -A -c \
    "SELECT
         schemaname||'.'||relname AS table,
         n_live_tup              AS approx_rows
     FROM pg_stat_user_tables
     WHERE schemaname = '${SCHEMA}'
     ORDER BY n_live_tup DESC;" 2>>"$LOG_FILE"

echo ""
echo "─── VIEWS ───────────────────────────────────────────────────"
psql "${PSQL_ARGS[@]}" --no-psqlrc -t -A -c \
    "SELECT schemaname||'.'||viewname
     FROM pg_views
     WHERE schemaname = '${SCHEMA}'
     ORDER BY viewname;" 2>>"$LOG_FILE"

echo ""
echo "─── MATERIALIZED VIEWS ──────────────────────────────────────"
psql "${PSQL_ARGS[@]}" --no-psqlrc -t -A -c \
    "SELECT schemaname||'.'||matviewname
     FROM pg_matviews
     WHERE schemaname = '${SCHEMA}'
     ORDER BY matviewname;" 2>>"$LOG_FILE"

echo ""
echo "─── SEQUENCES ───────────────────────────────────────────────"
psql "${PSQL_ARGS[@]}" --no-psqlrc -t -A -c \
    "SELECT sequence_schema||'.'||sequence_name
     FROM information_schema.sequences
     WHERE sequence_schema = '${SCHEMA}'
     ORDER BY sequence_name;" 2>>"$LOG_FILE"

echo ""
echo "─── FUNCTIONS ───────────────────────────────────────────────"
psql "${PSQL_ARGS[@]}" --no-psqlrc -t -A -c \
    "SELECT n.nspname||'.'||p.proname||'('||pg_get_function_identity_arguments(p.oid)||')'
     FROM pg_proc p
     JOIN pg_namespace n ON n.oid = p.pronamespace
     WHERE n.nspname = '${SCHEMA}' AND p.prokind = 'f'
     ORDER BY p.proname;" 2>>"$LOG_FILE"

echo ""
echo "─── PROCEDURES ──────────────────────────────────────────────"
psql "${PSQL_ARGS[@]}" --no-psqlrc -t -A -c \
    "SELECT n.nspname||'.'||p.proname||'('||pg_get_function_identity_arguments(p.oid)||')'
     FROM pg_proc p
     JOIN pg_namespace n ON n.oid = p.pronamespace
     WHERE n.nspname = '${SCHEMA}' AND p.prokind = 'p'
     ORDER BY p.proname;" 2>>"$LOG_FILE"

echo ""
echo "─── TRIGGERS ────────────────────────────────────────────────"
psql "${PSQL_ARGS[@]}" --no-psqlrc -t -A -c \
    "SELECT trigger_schema||'.'||trigger_name||' ON '||event_object_table
     FROM information_schema.triggers
     WHERE trigger_schema = '${SCHEMA}'
     GROUP BY trigger_schema, trigger_name, event_object_table
     ORDER BY trigger_name;" 2>>"$LOG_FILE"

echo ""
echo "─── USER-DEFINED TYPES ──────────────────────────────────────"
psql "${PSQL_ARGS[@]}" --no-psqlrc -t -A -c \
    "SELECT n.nspname||'.'||t.typname||' ('||
         CASE t.typtype
             WHEN 'e' THEN 'enum'
             WHEN 'c' THEN 'composite'
             WHEN 'd' THEN 'domain'
             WHEN 'r' THEN 'range'
             ELSE 'base'
         END||')'
     FROM pg_type t
     JOIN pg_namespace n ON n.oid = t.typnamespace
     WHERE n.nspname = '${SCHEMA}'
       AND t.typtype IN ('e','c','d','r','b')
       AND NOT EXISTS (SELECT 1 FROM pg_type a WHERE a.typelem = t.oid)
     ORDER BY t.typname;" 2>>"$LOG_FILE"

echo ""
echo "─── INDEXES ─────────────────────────────────────────────────"
psql "${PSQL_ARGS[@]}" --no-psqlrc -t -A -c \
    "SELECT schemaname||'.'||indexname||' ON '||tablename
     FROM pg_indexes
     WHERE schemaname = '${SCHEMA}'
     ORDER BY tablename, indexname;" 2>>"$LOG_FILE"

echo ""
echo "─── FILES ───────────────────────────────────────────────────"
} > "$MANIFEST"

# append file sizes to manifest
for f in "$BACKUP_DIR"/*; do
    echo "  $(du -sh "$f" | cut -f1)  $(basename "$f")"
done >> "$MANIFEST"
echo "" >> "$MANIFEST"
echo "Backup completed: $(date)" >> "$MANIFEST"

} 2>&1 | tee -a "$LOG_FILE"

success "Manifest saved → manifest.txt"

# ── Summary ───────────────────────────────────────────────────────────────────
TOTAL_SIZE=$(du -sh "$BACKUP_DIR" | cut -f1)
echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════${RESET}"
echo -e "${GREEN}${BOLD}  Backup completed successfully!${RESET}"
echo -e "${BOLD}═══════════════════════════════════════════════════${RESET}"
echo -e "  Directory  : ${CYAN}${BACKUP_DIR}${RESET}"
echo -e "  Total size : ${CYAN}${TOTAL_SIZE}${RESET}"
echo -e "${BOLD}───────────────────────────────────────────────────${RESET}"
echo -e "  Files created:"
for f in "$BACKUP_DIR"/*; do
    sz=$(du -sh "$f" | cut -f1)
    echo -e "    ${sz}  $(basename "$f")"
done
echo -e "${BOLD}═══════════════════════════════════════════════════${RESET}"
echo ""
echo -e "${YELLOW}To restore this backup:${RESET}"
echo -e "  ${CYAN}./pg_restore.sh -d <target_db> -i \"${BACKUP_DIR}\"${RESET}"
echo ""