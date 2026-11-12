---
type: Bug
title: A failed pg_dump can leave a truncated blob that counts toward retention
description: "backup_postgres.py streams into the final blob name, so a stopped (confirmed) or failed (inferred) run leaves a truncated dump that sorts newest and counts toward keep_last_n."
tags: [backup, postgres]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-12T19:51:07Z" }
status: draft
code_refs: [scripts/backup_postgres.py]
sources:
  - resource: scripts/backup_postgres.py
  - resource: src/llmaven/infrastructure/resources/container_apps.py
  - resource: "issue #193"
  - resource: "PR #215 (open)"
---

**Status at a7e7d32:** open. Truncated blobs were confirmed for a *stopped* execution on 2026-11-12. The failed-`pg_dump` path is still inferred from the code, and no issue tracks it.

`backup_postgres.py` streams `pg_dump` straight into the destination `.dump` blob through `fsspec`. It checks the exit code only after the file has closed, so a dump failing midway can leave a truncated blob. That run raises before pruning. The next successful run sorts all blobs by name and keeps the newest `keep_last_n`, so truncated blobs count toward retention and push out older good dumps. With `replica_retry_limit=2`, one bad night can add up to three.

**Confirmed (2026-11-12):** stopping a running prod execution (`az containerapp job stop … --job-execution-name …`) about 20 minutes in left `llmaven/litellm_db/2026-11-12T19-33-36Z.dump` at 105 MB, against about 9.3 GB for a full dump. Its name sorted newest, so it looked like the latest restore point and would have counted toward the 7 kept. It was deleted by hand. After stopping or failing a run, list `pg-backups/llmaven/litellm_db/` (storage account in the backup stack; listing needs `--auth-mode key`) and delete any blob far smaller than its neighbors. A stopped execution shows as `Stopped`, not `Failed`.

`stderr` is a pipe read only after stdout finishes, so a very chatty `pg_dump` could also block.

Nothing validates a dump. #193 notes restores have never been drilled. Uploading to a temporary name and renaming on success is one fix; none has been discussed publicly.

**Sources:** scripts/backup_postgres.py; src/llmaven/infrastructure/resources/container_apps.py; issue #193; PR #215; prod execution llmaven-backup-prod-gs7r9ty (stopped 2026-11-12)

# Related Concepts
- [Backup storage is a separate Pulumi stack; the backup job stays in the main stack](../architecture/backup-storage-isolated-stack.md): A failure mode of the same job
