# Testing the PostgreSQL backup script locally

Uses the docker-compose stack (`docker/docker-compose.yml`) with Azurite (Azure
Blob emulator).

## Prerequisites

### PostgreSQL client tools

**macOS:**

```bash
brew install libpq
# libpq is keg-only — add it to PATH for this session (or add to your shell profile)
export PATH="/opt/homebrew/opt/libpq/bin:$PATH"   # Apple Silicon
```

**Linux (Debian/Ubuntu):**

```bash
sudo apt-get install -y postgresql-client
```

### Python dependencies

Activate the pixi backup environment (installs fsspec, adlfs, pyyaml):

```bash
pixi run -e backup python --version  # triggers environment solve on first run
```

Or if running outside pixi:

```bash
pip install fsspec adlfs pyyaml
```

## Azure Blob (Azurite)

### 1. Start required services

```bash
cd docker
docker compose up -d db azurite
docker compose ps db azurite  # wait for both to be healthy
```

### 2. Set environment variables

Pull DB credentials from `docker/.env`:

```bash
export DATABASE_URL="postgresql://<POSTGRES_USER>:<POSTGRES_PASSWORD>@localhost:<POSTGRES_PORT>/<POSTGRES_DB>"

# Azurite fixed dev credentials — public, safe to use as-is
export AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
```

### 3. Create the blob container

Azurite uses fixed well-known dev credentials:

```bash
az storage container create \
  --name pg-backups \
  --connection-string "$AZURE_STORAGE_CONNECTION_STRING"
```

### 4. Confirm destination in config

`llmaven-backup-config.yaml` already has:

```yaml
pg_backup:
  destination: "az://pg-backups/llmaven/"
```

No changes needed — this matches the container created above.

### 5. Run the backup

```bash
pixi run -e backup backup
# or directly:
pixi run -e backup python scripts/backup_postgres.py --config llmaven-backup-config.yaml
```

Expected output:

```
Backing up 'postgres' → az://pg-backups/llmaven/postgres/2026-05-08T02-00-00Z.dump
Upload complete.
Done. Retained 1 backup(s) under az://pg-backups/llmaven/postgres/
```

### 6. Verify the backup landed

```bash
az storage blob list \
  --container-name pg-backups \
  --prefix llmaven/ \
  --connection-string "$AZURE_STORAGE_CONNECTION_STRING" \
  --output table
```

### 7. Test retention

Set `keep_last_n: 2` in the config and run the script three times. On the third
run you should see a `Deleted old backup:` line and only 2 files remain in
Azurite.

### 8. Verify the dump is valid

```bash
BLOB_NAME=$(az storage blob list \
  --container-name pg-backups \
  --prefix llmaven/postgres/ \
  --connection-string "$AZURE_STORAGE_CONNECTION_STRING" \
  --query '[-1].name' -o tsv)

az storage blob download \
  --container-name pg-backups \
  --name "$BLOB_NAME" \
  --file /tmp/test.dump \
  --connection-string "$AZURE_STORAGE_CONNECTION_STRING"

pg_restore --list /tmp/test.dump | head -20
```
