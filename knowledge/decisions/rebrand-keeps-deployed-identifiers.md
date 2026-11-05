---
type: Decision
title: The llmoxie rebrand must not rename identifiers that carry live state
description: "Pulumi project, project.name, Postgres names, blob containers and the compose volume identify live resources; renaming them orphans state or replaces data."
tags: [rebrand, pulumi, azure]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:47Z" }
status: draft
governance: constraint
code_refs:
  - "src/llmaven/deployment/deploy.py"
  - "src/llmaven/deployment/deploy_backup.py"
  - "src/llmaven/infrastructure/config/schema.py"
  - "docker/docker-compose.yml"
sources:
  - resource: "issue #187 (body and audit comments)"
  - resource: "src/llmaven/deployment/deploy.py"
  - resource: "src/llmaven/deployment/deploy_backup.py"
---

**Status at e248584:** the identifiers are unchanged and the rebrand is open. This is the #187 audits' recommendation, and the "Rename plan agreed" box in #187 is unticked.

A grep-and-replace is explicitly rejected. These identify live resources: the Pulumi project and stack names, `project.name` and the names derived from it, the resource group, Postgres server, database and admin login, Key Vault, storage account, blob containers and the compose volume. Pulumi treats a new project name as a new project with empty state, and Azure names such as the resource group and Postgres server can't be changed, so a rename means replacing them and losing data. Only tags are safe to change in place, and even that produces a deploy diff.

**The sharpest hazard:** the main stack's Pulumi project is the literal `"llmaven"` in five functions in `deploy.py` (deploy, destroy, refresh, cancel, status), independent of `project.name`. Changing it hides every existing stack, so the next deploy provisions fresh infrastructure. Changing only some of the five is worse, because status or cancel would report "no stack" during an incident. #187 proposes one named constant with a comment explaining why it must not change; that constant doesn't exist yet.

The backup stack differs: its Pulumi project comes from config `project.name`, and `BACKUP_PROJECT_NAME` in `deploy_backup.py` is dead code.

Any real migration of live names is a separate blue/green effort with a data copy.

**Sources:** issue #187 (body and audit comments); src/llmaven/deployment/deploy.py; src/llmaven/deployment/deploy_backup.py
