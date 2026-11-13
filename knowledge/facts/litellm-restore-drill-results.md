---
type: Fact
title: "A litellm_db restore brings back virtual keys under any keys, but stored models need the old salt key"
description: "Drill on LiteLLM 1.108.6: after losing the cluster, pg_restore of litellm_db recovers virtual keys under new keys, while database-stored models return only with the old salt key (or the old master key when no salt key is set); pg_dump and server majors must match."
tags: [restore, backup, litellm, postgres, helm]
generated: { by: "claude-code:claude-fable-5-2", at: "2026-11-13T00:13:18Z" }
status: stable
code_refs: [scripts/k3s/restore_drill.py, charts/llmoxie/templates/postgres.yaml]
---

**Status at a7e7d32:** observed on 2026-11-12 in the uncommitted prototype on branch `llmoxie-helm`, with LiteLLM 1.108.6, PostgreSQL 17.11 under CloudNativePG, and `pg_dump` 17.11. The project owner set the goal: a restore must bring back the LiteLLM service.

## What the drill does

`scripts/k3s/restore_drill.py` seeds a virtual key and a model stored in the database with a provider credential, runs the backup job, deletes the main k3d cluster, builds a new one (the chart generates a new master key and a new salt key there), and restores `litellm_db` from the backup cluster with `pg_restore --clean --if-exists --no-owner --no-privileges` while LiteLLM is scaled to zero. A full pass took 175 seconds.

## Observed with a salt key set

- Before the restore, the new cluster rejects the virtual key with HTTP 401 `token_not_found_in_db`.
- After the restore, with a new master key and a new salt key, the virtual key authenticates and a config-file model answers. The database-stored model is missing: `Invalid model name passed in model=db-mock`.
- After only the old salt key is put back and LiteLLM restarts, with the master key still new, the stored model answers again.

So with `LITELLM_SALT_KEY` set, the salt key alone decides whether stored credentials decrypt, and the master key can differ. A site needs three things outside the cluster to recover: the dump, the salt key, and the chart values. Custody is settled in decisions/litellm-keys-in-site-secret-store.

## Observed earlier without a salt key

The first run of the drill had no salt key. The result was the same with the master key in the salt key's place: the stored model came back only after the old master key was restored.

## PostgreSQL major versions must match

Restoring a dump made by `pg_dump` 17 into PostgreSQL 16 failed with `unrecognized configuration parameter "transaction_timeout"`; `pg_restore` ignored the error but exited non-zero. The chart therefore bundles PostgreSQL 17, the major version in the backup image. A newer server than the client cannot be dumped at all.

Inferred, not tested: the Azure deployment runs the same backup image against PostgreSQL 16, so a restore into that server would report the same error.

## Not tested

Restoring `mlflow_db`, restoring into a database that LiteLLM is still connected to, a dump from PostgreSQL 16 restored into 17, and rotating the master key on a running install that has a salt key.

**Sources:** issue #236; docs/superpowers/specs/2026-11-12-llmoxie-helm-chart-design.md; scripts/k3s/restore_drill.py; charts/llmoxie/values.yaml

# Related Concepts
- [Never add a fresh salt key to an existing database, and rotate the master key by migration](../requirements/litellm-master-and-salt-key.md): The drill shows what the master key being the encryption key means for a restore
- [Database backups live outside the cluster they protect](../requirements/backups-outside-the-cluster.md): The restore reads the dump from the off-cluster backup destination
