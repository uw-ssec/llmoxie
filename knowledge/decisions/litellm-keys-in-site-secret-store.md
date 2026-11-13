---
type: Decision
title: "The chart takes the LiteLLM master and salt keys from the site's secret store and generates them only on request"
description: "For the Helm chart in #236: keys live in the site's own secret store, never beside the backups; a salt key is set from the first install; the chart refuses to install without them unless litellm.keys.generate=true. Unmerged prototype."
tags: [secrets, litellm, helm, backup, restore]
generated: { by: "claude-code:claude-fable-5-2", at: "2026-11-13T00:13:19Z" }
status: stable
code_refs: [charts/llmoxie/templates/litellm.yaml, charts/llmoxie/values.yaml, charts/llmoxie/ci/k3s-values.yaml]
governance: constraint
---

**Status at a7e7d32:** decided on 2026-11-12 for the Helm chart tracked in #236. The agent proposed it when the project owner asked for the secure option, and the owner approved. Implemented only in the uncommitted prototype on branch `llmoxie-helm`.

## Decision

- A site keeps the LiteLLM master key and salt key in its own secret store (AWS Secrets Manager, GCP Secret Manager, Azure Key Vault, Vault), under different access than the backup destination. A site without one keeps them in an encrypted file or a password manager and creates the Secret by hand.
- The chart never writes a key outside the cluster. No copy sits beside the backups.
- New installs set `LITELLM_SALT_KEY` from the start. The salt key encrypts stored provider credentials and never changes; the master key is then only the admin credential.
- The chart reads both from one Secret, `litellm.keys.existingSecret`, with entries `master-key` and `salt-key`. Without it the chart refuses to install. `litellm.keys.generate=true` makes the chart generate both in the cluster; that is for the local and CI stacks.

One Secret for both keys rather than two, and the value names, are the agent's choices, not the owner's words.

## Why

- The dump holds provider credentials encrypted with the salt key and virtual keys only as hashes. A stolen dump is of limited use alone; with the key beside it, it gives away every provider credential.
- A key generated inside the cluster exists nowhere else, so losing the cluster loses the stored credentials. The restore drill showed that (facts/litellm-restore-drill-results).
- With a salt key, a restore needs only that one secret, and the master key can be new. Verified by the drill on LiteLLM 1.108.6.

## Rejected

- A copy of the key written beside the backups: one stolen bucket would yield both the data and the key.
- Generating keys by default: convenient, and the way a site ends up with no copy.

## Limits

- The Azure production database holds credentials encrypted with the master key and no salt key. Adding a salt key there breaks their decryption (requirements/litellm-master-and-salt-key), so this decision covers new chart installs; the production move is designed separately.
- How the Secret travels from the secret store into the cluster is not decided.
- Rotating the master key on a running install with a salt key was not tested.

**Sources:** issue #236; docs/superpowers/specs/2026-11-12-llmoxie-helm-chart-design.md; charts/llmoxie/values.yaml; charts/llmoxie/templates/litellm.yaml; charts/llmoxie/templates/_helpers.tpl

# Related Concepts
- [A litellm_db restore brings back virtual keys under any keys, but stored models need the old salt key](../facts/litellm-restore-drill-results.md): The drill verified that a restore needs only the old salt key
- [Never add a fresh salt key to an existing database, and rotate the master key by migration](../requirements/litellm-master-and-salt-key.md): New installs start with a salt key; the existing-database hazard still applies to the Azure move
- [Database backups live outside the cluster they protect](../requirements/backups-outside-the-cluster.md): Keys are kept apart from the backup destination
