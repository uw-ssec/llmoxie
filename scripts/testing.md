# Testing the PostgreSQL backup script locally

Uses the docker-compose stack (`docker/docker-compose.yml`). Azurite (Azure Blob emulator) and MinIO (S3 emulator) are both available.

## Prerequisites

### PostgreSQL client tools

**macOS:**
```bash
brew install libpq
# libpq is keg-only — add it to PATH for this session (or add to your shell profile)
export PATH="/opt/homebrew/opt/libpq/bin:$PATH"   # Apple Silicon
# export PATH="/usr/local/opt/libpq/bin:$PATH"    # Intel Mac
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

### 2. Create the blob container

Azurite uses fixed well-known dev credentials. `azure-storage-blob` is pulled in by `adlfs`:

```bash
python -c "
from azure.storage.blob import BlobServiceClient
cs = 'DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;'
BlobServiceClient.from_connection_string(cs).create_container('pg-backups')
print('Container created.')
"
```

### 3. Set environment variables

Pull DB credentials from `docker/.env`:

```bash
export DATABASE_URL="postgresql://<POSTGRES_USER>:<POSTGRES_PASSWORD>@localhost:<POSTGRES_PORT>/<POSTGRES_DB>"

# Azurite fixed dev credentials — public, safe to use as-is
export AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
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
python -c "
from azure.storage.blob import BlobServiceClient
cs = 'DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;'
cc = BlobServiceClient.from_connection_string(cs).get_container_client('pg-backups')
for b in cc.list_blobs(): print(b.name, b.size)
"
```

### 7. Test retention

Set `keep_last_n: 2` in the config and run the script three times. On the third run you should see a `Deleted old backup:` line and only 2 files remain in Azurite.

### 8. Verify the dump is valid

```bash
python -c "
from azure.storage.blob import BlobServiceClient
cs = 'DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;'
cc = BlobServiceClient.from_connection_string(cs).get_container_client('pg-backups')
blobs = list(cc.list_blobs(name_starts_with='llmaven/postgres/'))
data = cc.download_blob(blobs[-1].name).readall()
open('/tmp/test.dump', 'wb').write(data)
print('Downloaded', blobs[-1].name)
"
pg_restore --list /tmp/test.dump | head -20
```

---

## AWS S3 (MinIO)

MinIO is already running in the stack and the `llmaven` bucket is pre-created by the `createbuckets` service.

### 1. Start required services

```bash
cd docker
docker compose up -d db minio createbuckets
```

### 2. Update the destination in the config

```yaml
pg_backup:
  destination: "s3://llmaven/pg-backups/"
```

### 3. Set environment variables

```bash
export DATABASE_URL="postgresql://<POSTGRES_USER>:<POSTGRES_PASSWORD>@localhost:<POSTGRES_PORT>/<POSTGRES_DB>"
export AWS_ENDPOINT_URL="http://localhost:9000"
export AWS_ACCESS_KEY_ID="<MINIO_ROOT_USER from docker/.env>"
export AWS_SECRET_ACCESS_KEY="<MINIO_ROOT_PASSWORD from docker/.env>"
```

### 4. Run the backup

```bash
pixi run -e backup backup
# or directly:
pixi run -e backup python scripts/backup_postgres.py --config llmaven-backup-config.yaml
```

### 5. Verify via MinIO console

Open http://localhost:9001 and log in with the MinIO root credentials. Navigate to the `llmaven` bucket to confirm the dump file is present.
