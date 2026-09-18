#!/usr/bin/env bash
# dbexport.sh — download a LiteLLM pg_dump backup from Azure Blob and
# export LiteLLM_SpendLogs as JSONL compatible with reader.py.
#
# Usage:
#   ./scripts/dbexport.sh [--dump path/to/local.dump] [--out spend_logs.jsonl]
#
# Without --dump, downloads the latest backup from Azure Blob and skips the
# download if the file is already present locally.
#
# Environment variables (same as backup_postgres.py):
#   BACKUP_DESTINATION              az://container/prefix/   (required unless --dump)
#   DB_NAME                         database name in the backup path (required unless --dump)
#   AZURE_STORAGE_CONNECTION_STRING  preferred auth
#   AZURE_STORAGE_ACCOUNT_NAME       fallback auth
#   AZURE_STORAGE_ACCOUNT_KEY        fallback auth

set -euo pipefail

DUMP_FILE=""
OUT_FILE="spend_logs.jsonl"
PG_PORT=15432
PG_PASS="export_$$"
PG_CONTAINER="pg-llmaven-export-$$"
BACKUP_DESTINATION="az://pg-backups/llmaven"
DB_NAME="litellm_db"


usage() {
    grep '^#' "$0" | sed 's/^# \{0,1\}//'
    exit 1
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --dump) DUMP_FILE="$2"; shift 2 ;;
        --out)  OUT_FILE="$2";  shift 2 ;;
        -h|--help) usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

for tool in az docker pg_restore psql; do
    command -v "$tool" &>/dev/null || { echo "ERROR: $tool not found in PATH"; exit 1; }
done

# --- Azure download (skipped when --dump is given) ---

if [[ -z "$DUMP_FILE" ]]; then
    : "${BACKUP_DESTINATION:?BACKUP_DESTINATION is required (e.g. az://container/prefix/)}"
    : "${DB_NAME:?DB_NAME is required}"

    # Parse az://container/prefix/ → CONTAINER and BLOB_PREFIX
    _url="${BACKUP_DESTINATION#az://}"
    _container="${_url%%/*}"
    _prefix="${_url#*/}"
    _blob_prefix="${_prefix%/}/${DB_NAME}/"

    # Build auth args array
    AZ_AUTH=()
    if [[ -n "${AZURE_STORAGE_CONNECTION_STRING:-}" ]]; then
        AZ_AUTH+=(--connection-string "$AZURE_STORAGE_CONNECTION_STRING")
    elif [[ -n "${AZURE_STORAGE_ACCOUNT_NAME:-}" ]]; then
        AZ_AUTH+=(--account-name "$AZURE_STORAGE_ACCOUNT_NAME")
        [[ -n "${AZURE_STORAGE_ACCOUNT_KEY:-}" ]] && AZ_AUTH+=(--account-key "$AZURE_STORAGE_ACCOUNT_KEY")
    fi

    echo "Listing backups under ${BACKUP_DESTINATION}${DB_NAME}/ ..."
    LATEST_BLOB=$(az storage blob list \
        --container-name "$_container" \
        --prefix "$_blob_prefix" \
        "${AZ_AUTH[@]}" \
        --query "[-1].name" -o tsv)

    [[ -n "$LATEST_BLOB" ]] || { echo "ERROR: no backups found"; exit 1; }

    DUMP_FILE="${LATEST_BLOB##*/}"

    if [[ -f "$DUMP_FILE" ]]; then
        echo "Already present: $DUMP_FILE — skipping download."
    else
        echo "Downloading $LATEST_BLOB → $DUMP_FILE ..."
        az storage blob download \
            --container-name "$_container" \
            --name "$LATEST_BLOB" \
            --file "$DUMP_FILE" \
            "${AZ_AUTH[@]}" \
            --output none
        echo "Download complete."
    fi
fi

[[ -f "$DUMP_FILE" ]] || { echo "ERROR: dump file not found: $DUMP_FILE"; exit 1; }

# --- Throwaway Postgres ---

_SANITIZE_PY=""
cleanup() {
    echo "Removing container $PG_CONTAINER ..."
    docker rm -f "$PG_CONTAINER" &>/dev/null || true
    [[ -n "$_SANITIZE_PY" ]] && rm -f "$_SANITIZE_PY"
}
trap cleanup EXIT

DB_URL="postgresql://postgres:${PG_PASS}@localhost:${PG_PORT}/postgres"

echo "Starting Postgres ($PG_CONTAINER) on port $PG_PORT ..."
docker run -d \
    --name "$PG_CONTAINER" \
    -e POSTGRES_PASSWORD="$PG_PASS" \
    -p "${PG_PORT}:5432" \
    postgres:17 > /dev/null

echo "Waiting for Postgres to be ready ..."
for i in $(seq 1 30); do
    psql "$DB_URL" -c "SELECT 1" &>/dev/null && break || sleep 1
done
psql "$DB_URL" -c "SELECT 1" &>/dev/null || { echo "ERROR: Postgres did not start"; exit 1; }

# Restore schema so pg_restore knows table structure.
# Errors from missing extensions/roles are expected and harmless.
echo "Restoring schema ..."
pg_restore --schema-only --no-privileges --no-owner \
    --dbname="$DB_URL" "$DUMP_FILE" 2>/dev/null || true

psql "$DB_URL" -c '\d "LiteLLM_SpendLogs"' &>/dev/null || {
    echo "ERROR: LiteLLM_SpendLogs not found in dump"
    exit 1
}


echo "Restoring LiteLLM_SpendLogs data ..."
RESTORE_LIST=$(mktemp)
pg_restore --list "$DUMP_FILE" \
    | grep "TABLE DATA public LiteLLM_SpendLogs" \
    > "$RESTORE_LIST"
[[ -s "$RESTORE_LIST" ]] || { echo "ERROR: TABLE DATA entry for LiteLLM_SpendLogs not found in TOC"; exit 1; }

pg_restore --use-list="$RESTORE_LIST" --no-privileges --no-owner --dbname="$DB_URL" "$DUMP_FILE"
rm -f "$RESTORE_LIST"
echo "Restore complete."
ROW_COUNT=$(psql "$DB_URL" -t -c 'SELECT count(*) FROM "LiteLLM_SpendLogs"' | tr -d ' ')
echo "Exporting $ROW_COUNT rows → $OUT_FILE ..."
_SANITIZE_PY=$(mktemp /tmp/dbexport_sanitize_XXXX.py)
cat > "$_SANITIZE_PY" << 'PYEOF'
import sys, json

def sanitize(line):
    # row_to_json() mis-encodes backslash-quote pairs stored in JSONB columns:
    # a JSONB value containing \" (backslash + quote) is serialized as \\"
    # (escaped backslash + unescaped quote) instead of the correct \\\"
    # (escaped backslash + escaped quote).  The unescaped " terminates the
    # JSON string early.  Fix by inserting the missing backslash before each
    # unescaped quote that follows a double-backslash.
    return line.replace('\\\\"', '\\\\\\"')

skipped = 0
for raw in sys.stdin:
    line = raw.rstrip('\n')
    if not line:
        continue
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        try:
            obj = json.loads(sanitize(line))
        except json.JSONDecodeError as exc:
            print(f'WARNING: skipping unparsable row: {exc}', file=sys.stderr)
            skipped += 1
            continue
    print(json.dumps(obj, ensure_ascii=False))

if skipped:
    print(f'WARNING: {skipped} row(s) could not be sanitized and were skipped.', file=sys.stderr)
PYEOF

psql "$DB_URL" -t \
    -c 'COPY (SELECT row_to_json(t) FROM "LiteLLM_SpendLogs" t) TO STDOUT' \
    | python3 "$_SANITIZE_PY" > "$OUT_FILE"


echo "Done. $OUT_FILE is ready for reader.py."
