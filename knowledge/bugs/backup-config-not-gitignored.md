---
type: Bug
title: "llmaven-backup-config.yaml isn't covered by .gitignore"
description: "The Pixi backup task reads llmaven-backup-config.yaml, which the llmaven-config*.yaml glob doesn't match, so the gitignored-configs rule doesn't protect it."
tags: [secrets, backup, gitignore]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:48Z" }
status: stable
code_refs: [.gitignore, pixi.toml]
sources:
  - resource: "PR #182"
  - resource: .gitignore
  - resource: pixi.toml
---

**Status at e248584:** open.

The `backup` task in `pixi.toml` reads `llmaven-backup-config.yaml`, and `.gitignore` has only `llmaven-config*.yaml`. The "never commit deployment config" non-negotiable in `AGENTS.md` therefore has no enforcement for this file. #182 flagged it as out of scope and nothing has fixed it. Whether the file holds secrets depends on use, because `scripts/backup_postgres.py` also accepts environment configuration.

**Sources:** PR #182; .gitignore; pixi.toml

# Related Concepts
- [Backup storage is a separate Pulumi stack; the backup job stays in the main stack](../architecture/backup-storage-isolated-stack.md): Config file for the same backup path
