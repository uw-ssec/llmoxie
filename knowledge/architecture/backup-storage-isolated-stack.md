---
type: Architecture
title: Backup storage is a separate Pulumi stack; the backup job stays in the main stack
description: "Scheduled pg_dump is a safety net because deleting the server deletes native backups, so storage lives in its own stack while the job runs in the VNet with the main stack."
tags: [backup, postgres, pulumi]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:48Z" }
status: stable
code_refs: [src/llmaven/infrastructure_backup/main.py, src/llmaven/deployment/deploy_backup.py, scripts/backup_postgres.py, docker/dockerfiles/backup.dockerfile]
sources:
  - resource: "PRs #125, #127"
  - resource: src/llmaven/infrastructure_backup/README.md
  - resource: src/llmaven/infrastructure_backup/main.py
  - resource: scripts/backup_postgres.py
  - resource: docker/dockerfiles/backup.dockerfile
---

**Status at e248584:** implemented.

Deleting the Azure Postgres server also deletes its native point-in-time backups, so scheduled `pg_dump` is a secondary safety net (#125). Storage lives in a separate Pulumi stack, deployed once with `llmaven backup-infra deploy`, so destroying the main stack leaves the dumps alone. That stack owns its resource group, unlike the main stack.

The job itself belongs to the main stack, because it must run in the VNet to reach private Postgres. The database URL comes from Key Vault through the shared identity (#127). Rotating the backup storage key means re-exporting the connection string and redeploying the main stack.

The dump streams from `pg_dump` stdout to blob storage with no local disk writes. `backup_postgres.py` accepts only `az://` or `abfs://` destinations, which supersedes #125's mention of S3, and the image ships only `adlfs`.

**Sources:** PRs #125, #127; src/llmaven/infrastructure_backup/README.md; src/llmaven/infrastructure_backup/main.py; scripts/backup_postgres.py; docker/dockerfiles/backup.dockerfile

# Related Concepts
- [The Pulumi state store and resource group live outside the Pulumi program](pulumi-state-store-bootstrap.md): The main stack's group and state store are bootstrapped differently
