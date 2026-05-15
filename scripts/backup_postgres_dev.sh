#!/usr/bin/env bash
# Run a pg_dump backup against the local docker-compose stack (db + azurite),
# then download the resulting .dump file to the directory where this script was invoked.
set -euo pipefail

INVOKE_DIR="$(pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DOCKER_DIR="${REPO_ROOT}/docker"


# --- Read credentials from docker/.env (fall back to .env.example defaults) --
_read_env() {
    local key=$1 file=$2 default=$3
    local val
    val=$(grep "^${key}=" "$file" 2>/dev/null | cut -d= -f2- | head -1)
    echo "${val:-$default}"
}

ENV_FILE="${DOCKER_DIR}/.env"
[[ -f "$ENV_FILE" ]] || ENV_FILE="${DOCKER_DIR}/.env.example"

POSTGRES_USER=$(_read_env POSTGRES_USER "$ENV_FILE" "llmaven-admin")
POSTGRES_PASSWORD=$(_read_env POSTGRES_PASSWORD "$ENV_FILE" "dbpassword9090")
POSTGRES_PORT=$(_read_env POSTGRES_PORT "$ENV_FILE" "5432")

# --- Fixed Azurite well-known dev credentials --------------------------------
# These are public, documented constants — safe to hardcode for local dev.
AZURITE_CONN_STR="DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
BACKUP_CONTAINER="pg-backups"
DB_NAME="litellm_db"

# --- Set env vars for the backup script --------------------------------------
export DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:${POSTGRES_PORT}/${DB_NAME}"
export AZURE_STORAGE_CONNECTION_STRING="$AZURITE_CONN_STR"
export BACKUP_DESTINATION="az://${BACKUP_CONTAINER}/"
export BACKUP_KEEP_LAST_N="${BACKUP_KEEP_LAST_N:-7}"

# --- Ensure blob container exists --------------------------------------------
echo "Ensuring '${BACKUP_CONTAINER}' container exists in Azurite..."
az storage container create \
    --name "$BACKUP_CONTAINER" \
    --connection-string "$AZURE_STORAGE_CONNECTION_STRING" \
    --output none

# --- Run backup --------------------------------------------------------------
echo "Running backup..."
cd "$REPO_ROOT"
pixi run -e backup python scripts/backup_postgres.py

# --- Download latest dump to the directory where the script was invoked ------
echo ""
echo "Fetching latest backup blob..."
BLOB_NAME=$(az storage blob list \
    --container-name "$BACKUP_CONTAINER" \
    --prefix "${DB_NAME}/" \
    --connection-string "$AZURE_STORAGE_CONNECTION_STRING" \
    --query "[-1].name" \
    --output tsv)

if [[ -z "$BLOB_NAME" || "$BLOB_NAME" == "None" ]]; then
    echo "ERROR: No backup blobs found under ${BACKUP_CONTAINER}/${DB_NAME}/" >&2
    exit 1
fi

OUT_FILE="${INVOKE_DIR}/$(basename "$BLOB_NAME")"
echo "Downloading ${BLOB_NAME} → ${OUT_FILE}"
az storage blob download \
    --container-name "$BACKUP_CONTAINER" \
    --name "$BLOB_NAME" \
    --file "$OUT_FILE" \
    --connection-string "$AZURE_STORAGE_CONNECTION_STRING" \
    --output none

echo "Done! Backup saved to ${OUT_FILE}"
echo "Inspect with pg_restore --list ${OUT_FILE}"
