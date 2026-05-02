#!/usr/bin/env bash
# =============================================================================
# pg_restore.sh
# Restores a full PostgreSQL backup (created by pg_backup.sh) into an
# empty (or existing) database.
#
# Restore modes:
#   --full      Restore schema + data from dump.custom  (default, fastest)
#   --sql       Restore from dump.sql (or dump.sql.gz)  (plain SQL fallback)
#   --schema    Restore schema only from schema_only.sql
#
# Safety options:
#   --clean     DROP all existing objects before restoring (requires the
#               pg_drop_all_objects.sql script in the backup directory or
#               the same directory as this script).
#   --create    CREATE the target database if it does not exist.
#
# Usage:
#   chmod +x pg_restore.sh
#   ./pg_restore.sh [options]
#
# Options:
#   -h HOST       Database host           (default: localhost)
#   -p PORT       Database port           (default: 5432)
#   -U USER       Database user           (default: postgres)
#   -d DATABASE   Target database name    (required)
#   -i DIR        Backup directory        (required)
#   -s SCHEMA     Target schema           (default: public)
#   -j JOBS       Parallel restore jobs   (default: 4, custom format only)
#   --full        Restore schema + data via custom dump  (default)
#   --sql         Restore via plain SQL dump
#   --schema      Restore schema only
#   --clean       Drop all objects before restoring
#   --create      Create target database if it doesn't exist
#   --no-owner    Skip ownership assignments
#   --no-privs    Skip GRANT/REVOKE statements
#   --dry-run     Show what would be done, make no changes
#   --help        Show this help
#
# Examples:
#   ./pg_restore.sh -d newdb -i ./backups/mydb_20250307_120000
#   ./pg_restore.sh -d newdb -i ./backups/mydb_20250307_120000 --clean --create
#   ./pg_restore.sh -d newdb -i ./backups/mydb_20250307_120000 --sql
#   ./pg_restore.sh -d newdb -i ./backups/mydb_20250307_120000 --schema
# =============================================================================

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
PG_HOST="localhost"
PG_PORT="5432"
PG_USER="postgres"
PG_DATABASE=""
BACKUP_DIR=""
SCHEMA="public"
PARALLEL_JOBS=4
MODE="full"            # full | sql | schema
OPT_CLEAN=false
OPT_CREATE=false
OPT_NO_OWNER=false
OPT_NO_PRIVS=false
DRY_RUN=false

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

log()     { echo -e "${CYAN}[$(date '+%H:%M:%S')]${RESET} $*"; }
success() { echo -e "${GREEN}[$(date '+%H:%M:%S')] ✔ $*${RESET}"; }
warn()    { echo -e "${YELLOW}[$(date '+%H:%M:%S')] ⚠ $*${RESET}"; }
error()   { echo -e "${RED}[$(date '+%H:%M:%S')] ✘ $*${RESET}" >&2; }
die()     { error "$*"; exit 1; }
drylog()  { echo -e "${YELLOW}[DRY-RUN]${RESET} $*"; }

# ── Help ──────────────────────────────────────────────────────────────────────
usage() {
cat <<EOF
${BOLD}Usage:${RESET} $(basename "$0") [options]

${BOLD}Options:${RESET}
  -h HOST       Database host           (default: localhost)
  -p PORT       Database port           (default: 5432)
  -U USER       Database user           (default: postgres)
  -d DATABASE   Target database name    (required)
  -i DIR        Backup directory        (required)
  -s SCHEMA     Target schema           (default: public)
  -j JOBS       Parallel jobs           (default: 4)
  --full        Restore schema+data via custom dump (default)
  --sql         Restore via plain SQL dump
  --schema      Restore DDL (schema only)
  --clean       Drop existing objects before restoring
  --create      Create target database if it doesn't exist
  --no-owner    Skip ownership assignments
  --no-privs    Skip GRANT/REVOKE statements
  --dry-run     Show actions without executing them
  --help        Show this help

${BOLD}Environment variables:${RESET}
  PGPASSWORD    Password (avoids interactive prompt)

${BOLD}Examples:${RESET}
  $(basename "$0") -d newdb -i ./backups/mydb_20250307_120000
  $(basename "$0") -d newdb -i ./backups/mydb_20250307_120000 --clean --create
  $(basename "$0") -d newdb -i ./backups/mydb_20250307_120000 --sql
  $(basename "$0") -d newdb -i ./backups/mydb_20250307_120000 --schema
EOF
}

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h)          PG_HOST="$2";      shift 2 ;;
        -p)          PG_PORT="$2";      shift 2 ;;
        -U)          PG_USER="$2";      shift 2 ;;
        -d)          PG_DATABASE="$2";  shift 2 ;;
        -i)          BACKUP_DIR="$2";   shift 2 ;;
        -s)          SCHEMA="$2";       shift 2 ;;
        -j)          PARALLEL_JOBS="$2";shift 2 ;;
        --full)      MODE="full";       shift   ;;
        --sql)       MODE="sql";        shift   ;;
        --schema)    MODE="schema";     shift   ;;
        --clean)     OPT_CLEAN=true;    shift   ;;
        --create)    OPT_CREATE=true;   shift   ;;
        --no-owner)  OPT_NO_OWNER=true; shift   ;;
        --no-privs)  OPT_NO_PRIVS=true; shift   ;;
        --dry-run)   DRY_RUN=true;      shift   ;;
        --help)      usage; exit 0      ;;
        *) die "Unknown option: $1. Use --help for usage." ;;
    esac
done

# ── Validate required args ────────────────────────────────────────────────────
[[ -z "$PG_DATABASE" ]] && die "Target database is required. Use -d <database>."
[[ -z "$BACKUP_DIR"  ]] && die "Backup directory is required. Use -i <dir>."
[[ -d "$BACKUP_DIR"  ]] || die "Backup directory not found: $BACKUP_DIR"

# ── Locate the correct dump file ──────────────────────────────────────────────
CUSTOM_DUMP="${BACKUP_DIR}/dump.custom"
SQL_DUMP="${BACKUP_DIR}/dump.sql"
SQL_DUMP_GZ="${BACKUP_DIR}/dump.sql.gz"
SCHEMA_DUMP="${BACKUP_DIR}/schema_only.sql"
DROP_SCRIPT=""

# Look for the drop script (same dir as this script, or inside the backup dir)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if   [[ -f "${SCRIPT_DIR}/pg_drop_all_objects.sql" ]]; then
    DROP_SCRIPT="${SCRIPT_DIR}/pg_drop_all_objects.sql"
elif [[ -f "${BACKUP_DIR}/pg_drop_all_objects.sql" ]]; then
    DROP_SCRIPT="${BACKUP_DIR}/pg_drop_all_objects.sql"
fi

case "$MODE" in
    full)
        [[ -f "$CUSTOM_DUMP" ]] \
            || die "Binary dump not found: $CUSTOM_DUMP. Use --sql or --schema instead."
        RESTORE_FILE="$CUSTOM_DUMP"
        ;;
    sql)
        if   [[ -f "$SQL_DUMP"    ]]; then RESTORE_FILE="$SQL_DUMP"
        elif [[ -f "$SQL_DUMP_GZ" ]]; then RESTORE_FILE="$SQL_DUMP_GZ"
        else die "SQL dump not found: $SQL_DUMP (or .gz). Use --full or --schema instead."
        fi
        ;;
    schema)
        [[ -f "$SCHEMA_DUMP" ]] \
            || die "Schema dump not found: $SCHEMA_DUMP."
        RESTORE_FILE="$SCHEMA_DUMP"
        ;;
esac

# ── Pre-flight: tool availability ────────────────────────────────────────────
for cmd in psql pg_restore; do
    command -v "$cmd" &>/dev/null || die "'$cmd' not found. Install PostgreSQL client tools."
done

# Connection args for psql (no -d yet — we need to connect to postgres first for --create)
CONN_ARGS=(-h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER")
PSQL_DB=("${CONN_ARGS[@]}" -d "$PG_DATABASE" -v ON_ERROR_STOP=1)

# ── Log file ──────────────────────────────────────────────────────────────────
LOG_FILE="${BACKUP_DIR}/restore_$(date '+%Y%m%d_%H%M%S').log"

# ── Banner ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════${RESET}"
echo -e "${BOLD}  PostgreSQL Restore${RESET}"
echo -e "${BOLD}═══════════════════════════════════════════════════${RESET}"
echo -e "  Host       : ${CYAN}${PG_HOST}:${PG_PORT}${RESET}"
echo -e "  Database   : ${CYAN}${PG_DATABASE}${RESET}"
echo -e "  Schema     : ${CYAN}${SCHEMA}${RESET}"
echo -e "  Backup dir : ${CYAN}${BACKUP_DIR}${RESET}"
echo -e "  Mode       : ${CYAN}${MODE}${RESET}"
echo -e "  Restore    : ${CYAN}$(basename "$RESTORE_FILE")${RESET}"
$OPT_CLEAN  && echo -e "  ${YELLOW}--clean   : will drop all existing objects first${RESET}"
$OPT_CREATE && echo -e "  ${YELLOW}--create  : will create database if missing${RESET}"
$DRY_RUN    && echo -e "  ${RED}DRY RUN   : no changes will be made${RESET}"
echo -e "${BOLD}═══════════════════════════════════════════════════${RESET}"
echo ""

# ── Dry-run shortcut ──────────────────────────────────────────────────────────
if $DRY_RUN; then
    drylog "Step 1: Check / create database '${PG_DATABASE}'"
    $OPT_CLEAN && drylog "Step 2: Run drop script → ${DROP_SCRIPT:-<not found>}"
    drylog "Step 3: Restore from → ${RESTORE_FILE}"
    drylog "No changes made (--dry-run)."
    exit 0
fi

exec > >(tee -a "$LOG_FILE") 2>&1
echo "Restore started: $(date)"

# ── Step 1: Create database if needed ────────────────────────────────────────
if $OPT_CREATE; then
    DB_EXISTS=$(psql "${CONN_ARGS[@]}" -d postgres -tAc \
        "SELECT 1 FROM pg_database WHERE datname='${PG_DATABASE}';" 2>/dev/null || true)

    if [[ "$DB_EXISTS" == "1" ]]; then
        warn "Database '${PG_DATABASE}' already exists — skipping CREATE."
    else
        log "Creating database '${PG_DATABASE}'..."
        psql "${CONN_ARGS[@]}" -d postgres -c \
            "CREATE DATABASE \"${PG_DATABASE}\" ENCODING 'UTF8' LC_COLLATE 'en_US.UTF-8' LC_CTYPE 'en_US.UTF-8' TEMPLATE template0;" \
            2>>"$LOG_FILE"
        success "Database '${PG_DATABASE}' created."
    fi
else
    # Verify database exists
    psql "${PSQL_DB[@]}" -c "SELECT 1;" &>/dev/null \
        || die "Database '${PG_DATABASE}' does not exist. Use --create to create it."
fi

# ── Step 2: Drop existing objects if --clean ─────────────────────────────────
if $OPT_CLEAN; then
    if [[ -z "$DROP_SCRIPT" ]]; then
        die "--clean requested but pg_drop_all_objects.sql was not found.\n" \
            "Place it in the same directory as this script or inside the backup directory."
    fi

    warn "Dropping all existing objects in '${PG_DATABASE}'.${SCHEMA}..."

    # Prompt for confirmation unless stdin is not a terminal (CI/CD pipes)
    if [[ -t 0 ]]; then
        echo -ne "${RED}${BOLD}  ⚠  This will destroy ALL objects in ${PG_DATABASE}.${SCHEMA}. Confirm? [yes/N]: ${RESET}"
        read -r CONFIRM
        [[ "${CONFIRM,,}" == "yes" ]] || { warn "Aborted by user."; exit 0; }
    fi

    psql "${PSQL_DB[@]}" -f "$DROP_SCRIPT" 2>>"$LOG_FILE"
    success "All existing objects dropped."
fi

# ── Step 3: Restore ───────────────────────────────────────────────────────────

# Build optional flags
OWNER_FLAG=();  $OPT_NO_OWNER && OWNER_FLAG=(--no-owner)
PRIVS_FLAG=();  $OPT_NO_PRIVS && PRIVS_FLAG=(--no-acl)

case "$MODE" in

    # ── Binary custom format (pg_restore) ─────────────────────────────────────
    full)
        log "Restoring schema + data from binary dump (${PARALLEL_JOBS} parallel jobs)..."
        pg_restore \
            "${CONN_ARGS[@]}" \
            --dbname="$PG_DATABASE" \
            --schema="$SCHEMA" \
            --jobs="$PARALLEL_JOBS" \
            --verbose \
            --no-password \
            "${OWNER_FLAG[@]}" \
            "${PRIVS_FLAG[@]}" \
            "$RESTORE_FILE" \
            2>>"$LOG_FILE" || {
                error "pg_restore reported errors (see $LOG_FILE)."
                error "This is often harmless (e.g. pre-existing roles). Check the log."
            }
        success "Binary restore complete."
        ;;

    # ── Plain SQL dump ─────────────────────────────────────────────────────────
    sql)
        log "Restoring from plain SQL dump..."
        if [[ "$RESTORE_FILE" == *.gz ]]; then
            log "Decompressing ${RESTORE_FILE}..."
            gunzip -c "$RESTORE_FILE" | psql "${PSQL_DB[@]}" \
                --no-password 2>>"$LOG_FILE"
        else
            psql "${PSQL_DB[@]}" \
                --no-password \
                -f "$RESTORE_FILE" \
                2>>"$LOG_FILE"
        fi
        success "SQL restore complete."
        ;;

    # ── Schema only ───────────────────────────────────────────────────────────
    schema)
        log "Restoring schema only (DDL)..."
        psql "${PSQL_DB[@]}" \
            --no-password \
            -f "$RESTORE_FILE" \
            2>>"$LOG_FILE"
        success "Schema restore complete."
        ;;
esac

# ── Step 4: Post-restore verification ────────────────────────────────────────
log "Running post-restore verification..."

TABLE_COUNT=$(psql "${PSQL_DB[@]}" --no-psqlrc -tAc \
    "SELECT COUNT(*) FROM pg_tables WHERE schemaname='${SCHEMA}';" 2>>"$LOG_FILE")
VIEW_COUNT=$(psql "${PSQL_DB[@]}" --no-psqlrc -tAc \
    "SELECT COUNT(*) FROM pg_views WHERE schemaname='${SCHEMA}';" 2>>"$LOG_FILE")
SEQ_COUNT=$(psql "${PSQL_DB[@]}" --no-psqlrc -tAc \
    "SELECT COUNT(*) FROM information_schema.sequences WHERE sequence_schema='${SCHEMA}';" 2>>"$LOG_FILE")
FUNC_COUNT=$(psql "${PSQL_DB[@]}" --no-psqlrc -tAc \
    "SELECT COUNT(*) FROM pg_proc p
     JOIN pg_namespace n ON n.oid = p.pronamespace
     WHERE n.nspname='${SCHEMA}' AND p.prokind='f';" 2>>"$LOG_FILE")
PROC_COUNT=$(psql "${PSQL_DB[@]}" --no-psqlrc -tAc \
    "SELECT COUNT(*) FROM pg_proc p
     JOIN pg_namespace n ON n.oid = p.pronamespace
     WHERE n.nspname='${SCHEMA}' AND p.prokind='p';" 2>>"$LOG_FILE")
TRIG_COUNT=$(psql "${PSQL_DB[@]}" --no-psqlrc -tAc \
    "SELECT COUNT(DISTINCT trigger_name)
     FROM information_schema.triggers WHERE trigger_schema='${SCHEMA}';" 2>>"$LOG_FILE")

echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════${RESET}"
echo -e "${GREEN}${BOLD}  Restore completed successfully!${RESET}"
echo -e "${BOLD}═══════════════════════════════════════════════════${RESET}"
echo -e "  Database   : ${CYAN}${PG_DATABASE}${RESET}"
echo -e "${BOLD}───────────────────────────────────────────────────${RESET}"
echo -e "  Objects restored in schema '${SCHEMA}':"
echo -e "    Tables          : ${CYAN}${TABLE_COUNT}${RESET}"
echo -e "    Views           : ${CYAN}${VIEW_COUNT}${RESET}"
echo -e "    Sequences       : ${CYAN}${SEQ_COUNT}${RESET}"
echo -e "    Functions       : ${CYAN}${FUNC_COUNT}${RESET}"
echo -e "    Procedures      : ${CYAN}${PROC_COUNT}${RESET}"
echo -e "    Triggers        : ${CYAN}${TRIG_COUNT}${RESET}"
echo -e "${BOLD}───────────────────────────────────────────────────${RESET}"
echo -e "  Log file   : ${CYAN}${LOG_FILE}${RESET}"
echo -e "${BOLD}═══════════════════════════════════════════════════${RESET}"
echo ""

echo "Restore completed: $(date)" >> "$LOG_FILE"