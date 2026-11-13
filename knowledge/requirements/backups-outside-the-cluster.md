---
type: Requirement
title: Database backups live outside the cluster they protect
description: "Owner directive for the Helm chart in #236: the chart bundles no backup destination and backups never go to the bundled RustFS; the local stack uses a second k3d cluster. Unmerged prototype."
tags: [backup, helm, kubernetes, postgres, rustfs]
generated: { by: "claude-code:claude-fable-5-2", at: "2026-11-12T21:44:13Z" }
status: stable
code_refs: [charts/llmoxie/templates/backup.yaml, charts/llmoxie/values.yaml, scripts/k3s/up.sh]
governance: constraint
---

**Status at a7e7d32:** directive from the project owner on 2026-11-12 for the Helm chart tracked in #236. Implemented only in the uncommitted prototype on branch `llmoxie-helm`.

## Requirement

A site's database backups live in a separate place from the cluster they protect. The Azure deployment already follows this rule: backup storage is its own Pulumi stack so that destroying the main stack cannot take the backups with it.

## What must hold in the chart

- The chart bundles no backup destination. Backups never go to the release's bundled RustFS.
- `backup.storage` (endpoint, region, bucket, key Secret) is configured separately from `objectStorage`.
- With `backup.enabled=true` and no destination, the chart refuses to install. It also refuses a destination equal to its own bundled store. These two checks are the agent's choice of enforcement, not the owner's words; the chart cannot verify that a destination is really elsewhere.

## Local stack

The owner asked for a separate cluster in the local prototype. `scripts/k3s/up.sh` creates a second k3d cluster, `llmoxie-backup`, that runs only RustFS. Both clusters join the Docker network `llmoxie-local`, and the backup job reaches the store at `http://k3d-llmoxie-backup-server-0:30900`.

Verified on 2026-11-12: with the main cluster stopped, the dump was read from the backup cluster (276,921 bytes, starting with `PGDMP`), and the main cluster's RustFS held no `backups` bucket.

## Not settled

- The backup engine: the prototype keeps the `pg_dump` CronJob; CloudNativePG's continuous backup is proposed.
- Restore is neither designed nor prototyped.

**Sources:** issue #236; docs/superpowers/specs/2026-11-12-llmoxie-helm-chart-design.md; charts/llmoxie/templates/backup.yaml; charts/llmoxie/templates/_helpers.tpl; scripts/k3s/up.sh

# Related Concepts
- [Backup storage is a separate Pulumi stack; the backup job stays in the main stack](../architecture/backup-storage-isolated-stack.md): The same rule on Azure, where backup storage is a separate Pulumi stack
- [RustFS is the Helm chart's bundled object store, and S3 is the storage protocol](../decisions/rustfs-bundled-object-store.md): The bundled RustFS holds application data only; backups use a separate store
