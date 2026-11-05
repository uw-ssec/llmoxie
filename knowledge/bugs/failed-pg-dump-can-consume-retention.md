---
type: Bug
title: A failed pg_dump can leave a truncated blob that counts toward retention
description: "backup_postgres.py checks the exit code after the upload closes, and pruning keeps the newest keep_last_n by name, so truncated dumps can push out good ones (inferred, not reproduced)."
tags: [backup, postgres]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:48Z" }
status: draft
code_refs: [scripts/backup_postgres.py]
sources:
  - resource: scripts/backup_postgres.py
  - resource: src/llmaven/infrastructure/resources/container_apps.py
  - resource: "issue #193"
  - resource: "PR #215 (open)"
---

**Status at e248584:** open. This is inferred from reading the code, not reproduced, and no issue tracks it yet.

`backup_postgres.py` checks `pg_dump`'s exit code only after the `fsspec` file has closed, so a dump failing midway can leave a truncated `.dump` blob. That run raises before pruning. The next successful run sorts all blobs by name and keeps the newest `keep_last_n`, so truncated blobs count toward retention and push out older good dumps. With `replica_retry_limit=2`, one bad night can add up to three.

`stderr` is a pipe read only after stdout finishes, so a very chatty `pg_dump` could also block.

Nothing validates a dump. #193 notes restores have never been drilled. PR #215 proposes alerting on job failure and isn't merged. Uploading to a temporary name and renaming on success is one fix; none has been discussed publicly.

**Sources:** scripts/backup_postgres.py; src/llmaven/infrastructure/resources/container_apps.py; issue #193; PR #215 (open)

# Related Concepts
- [Backup storage is a separate Pulumi stack; the backup job stays in the main stack](../architecture/backup-storage-isolated-stack.md): A failure mode of the same job
