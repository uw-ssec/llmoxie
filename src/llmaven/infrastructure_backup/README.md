# LLMaven PostgreSQL Backup

Secondary backup safety net for the Azure PostgreSQL Flexible Server. It runs
independently of the Azure-native point-in-time backups so that an accidental
database deletion (which would also delete those backups) does not result in
data loss.

## How it works

```
┌─────────────────────────────────────────────────┐
│  Main stack  (rg-llmaven-{env})                 │
│                                                 │
│  Container Apps Environment (VNet-integrated)   │
│    └── Container Apps Job  ──scheduled daily──► │──┐
│         pg_dump (streams, no disk write)        │  │
└─────────────────────────────────────────────────┘  │
                                                     │ az:// connection string
┌─────────────────────────────────────────────────┐  │
│  Backup storage stack  (rg-llmaven-backup-{env})│  │
│                                                 │◄─┘
│  Storage Account (Standard LRS)                 │
│    └── pg-backups/                              │
│         └── llmaven/                            │
│              └── {db}/{YYYY-MM-DDTHH-MM-SSZ}.dump│
└─────────────────────────────────────────────────┘
```

The Container Apps Job runs inside the same VNet as the database, so PostgreSQL
does not need a public endpoint. `pg_dump` stdout is streamed directly to Azure
Blob Storage via [fsspec](https://filesystem-spec.readthedocs.io/) — no bytes
are written to local disk.

### Two Pulumi stacks, intentionally separated

| Stack              | Config file                  | What it owns                            |
| ------------------ | ---------------------------- | --------------------------------------- |
| **Main**           | `llmaven-config.yaml`        | Container Apps Job, everything else     |
| **Backup storage** | `llmaven-backup-config.yaml` | Storage account, `pg-backups` container |

The backup storage stack uses an existing resource group (specified in the
config) and provisions only the storage account and container within it. Keeping
the storage account in a separate stack means destroying the main stack (e.g.
tearing down a dev environment) does not touch the backup data.

### Authentication

Storage access uses the storage account key embedded in a connection string. No
role assignments are required anywhere. The connection string is stored as an
inline Container Apps Job secret — it never appears in config files or Pulumi
state in plain text.

---

## Configuration

Backup job settings live in the main config (`llmaven-config.yaml`) under
`backup_job`:

```yaml
backup_job:
  enabled: true
  image: ghcr.io/uw-ssec/llmaven-backup:latest
  schedule: "0 2 * * *" # daily at 2am UTC
  destination: "az://pg-backups/llmaven/"
  keep_last_n: 7 # retain the 7 most recent dumps, delete older ones
  cpu: 0.25
  memory: 0.5Gi
  replica_timeout: 1800 # abort if the job runs longer than 30 minutes
  connection_string_env: BACKUP_STORAGE_CONNECTION_STRING
```

All fields have defaults; set `enabled: true` to activate.

---

## Operator runbook

### First-time setup

**Step 1 — Deploy the backup storage stack**

```bash
llmaven backup-infra deploy --config llmaven-backup-config.yaml
```

This provisions the storage account and `pg-backups` container in the isolated
backup stack (using the existing resource group specified in the config). On
completion, the stack prints its outputs including
`backup_storage_connection_string` (shown as `(secret)`).

**Step 2 — Retrieve the connection string**

```bash
# Using the llmaven CLI (requires the stack to be deployed):
llmaven backup-infra output \
  --config llmaven-backup-config.yaml \
  --secret backup_storage_connection_string

# Or directly with the Azure CLI:
az storage account keys list \
  --resource-group rg-llmaven-backup-dev-westus2 \
  --account-name <storage-account-name> \
  --query '[0].value' -o tsv
```

**Step 3 — Set the connection string in your environment**

```bash
export BACKUP_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=https;AccountName=...;AccountKey=...;EndpointSuffix=core.windows.net"
```

**Step 4 — Enable the backup job in the main config**

Add or update `backup_job` in `llmaven-config.yaml`:

```yaml
backup_job:
  enabled: true
```

**Step 5 — Deploy the main stack**

```bash
llmaven deploy --config llmaven-config.yaml
```

The job is created in the existing Container Apps Environment and will run on
its first scheduled trigger.

---

### Day-to-day

The job runs automatically on the configured schedule (`0 2 * * *` by default).
No operator action is required.

Monitor job history in the Azure Portal:

> Container Apps → Jobs → `llmaven-backup-{env}` → Execution history

Or via the Azure CLI:

```bash
az containerapp job execution list \
  --name llmaven-backup-dev \
  --resource-group rg-llmaven-dev-westus2 \
  --output table
```

---

### Trigger a manual backup

```bash
az containerapp job start \
  --name llmaven-backup-dev \
  --resource-group rg-llmaven-dev-westus2
```

---

### Verify a backup landed

```bash
az storage blob list \
  --account-name <backup-storage-account> \
  --container-name pg-backups \
  --prefix llmaven/ \
  --output table \
  --account-key <key>
```

---

### Restore from a backup

**Step 1 — Download the dump file**

```bash
az storage blob download \
  --account-name <backup-storage-account> \
  --container-name pg-backups \
  --name "llmaven/<timestamp>.dump" \
  --file restore.dump \
  --account-key <key>
```

**Step 2 — Inspect the dump (optional)**

```bash
pg_restore --list restore.dump | head -30
```

**Step 3 — Restore to the target database**

```bash
pg_restore \
  --host <server-fqdn> \
  --username <admin-login> \
  --dbname llmaven \
  --no-owner \
  --no-privileges \
  --verbose \
  restore.dump
```

`pg_restore` will prompt for the password unless `PGPASSWORD` is set.

---

### Rotate the storage account key

When rotating the storage account key:

1. Generate a new key in the Azure Portal or via the CLI.
2. Re-export `BACKUP_STORAGE_CONNECTION_STRING` with the new key.
3. Re-deploy the main stack — this updates the inline Container Apps Job secret:

```bash
export BACKUP_STORAGE_CONNECTION_STRING="...new connection string..."
llmaven deploy --config llmaven-config.yaml
```

---

## Local testing

See [`scripts/testing.md`](../../scripts/testing.md) for instructions on running
the backup script locally against Azurite (Azure Blob emulator) and the
docker-compose PostgreSQL instance.
