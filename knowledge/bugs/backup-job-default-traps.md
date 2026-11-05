---
type: Bug
title: Backup job defaults disagree with the docs and may miss the important database
description: "backup_job.database defaults to llmaven, not litellm_db or mlflow_db, and connection_string_env, schedule and restore path differ from the README runbook."
tags: [backup, config, documentation]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:48Z" }
status: stable
code_refs: [src/llmaven/infrastructure/config/schema.py, src/llmaven/infrastructure/main.py, src/llmaven/infrastructure_backup/README.md]
sources:
  - resource: "PRs #125, #141, #170"
  - resource: "issues #140, #193"
  - resource: src/llmaven/infrastructure/config/schema.py
  - resource: src/llmaven/infrastructure/main.py
  - resource: src/llmaven/infrastructure_backup/README.md
---

**Status at e248584:** open. Items marked inferred were read from the code, not run.

- **Database.** `backup_job.database` defaults to `llmaven`. #140 and #141 chose that to fix an `infra init` crash and because it passes the cross-check against `database.databases`, not because it holds the data. LiteLLM and MLflow use `litellm_db` and `mlflow_db`, and one job backs up one database, so a job enabled with the default doesn't capture them (inferred). #193 asks for backing up all configured databases and notes restores have never been drilled.
- **Env var.** `connection_string_env` defaults to `LLMAVEN_SECRETS_BACKUP_STORAGE_CONNECTION_STRING`, but the README, the CLI output and `deploy_backup.py` export `BACKUP_STORAGE_CONNECTION_STRING`. Following the runbook with only `enabled: true` raises `ValueError` in `main.py` (inferred).
- **Schedule.** The default is `0 10 * * *`, but the README says `0 2 * * *` is the default.
- **Timeout.** `replica_timeout` defaults to 1800 s, which #170 found too short for a production-sized database. Size it to the database.
- **Restore path.** `backup_postgres.py` writes `{destination}{db}/{timestamp}.dump`, but the README's restore command uses `llmaven/<timestamp>.dump`, omitting the `{db}/` segment.

**Sources:** PRs #125, #141, #170; issues #140, #193; src/llmaven/infrastructure/config/schema.py; src/llmaven/infrastructure/main.py; src/llmaven/infrastructure_backup/README.md

# Related Concepts
- [Backup storage is a separate Pulumi stack; the backup job stays in the main stack](../architecture/backup-storage-isolated-stack.md): Configuration traps in the backup job
