---
type: Requirement
title: "Never add a fresh salt key to an existing database, and rotate the master key by migration"
description: "With no LITELLM_SALT_KEY the master key encrypts stored credentials, so replacing it needs a migration, and adding a salt key to existing data breaks decryption."
tags: [litellm, secrets, encryption]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:48Z" }
status: draft
governance: constraint
code_refs: [docker/config.yaml, docker/.env.example, src/llmaven/infrastructure/config/schema.py, src/llmaven/infrastructure/resources/secrets_manager.py]
sources:
  - resource: "issues #193, #200"
  - resource: "PR #148"
  - resource: docker/README.md
  - resource: docker/config.yaml
  - resource: "https://github.com/BerriAI/litellm/blob/v1.106.6/litellm/proxy/auth/master_key_boot_check.py"
---

**Status at e248584:** no salt key is provisioned. #200 is open.

`store_model_in_db: true` makes LiteLLM encrypt stored provider credentials with `LITELLM_SALT_KEY`, or with the master key when that's unset. LLMoxie provisions no salt key, so the master key is both the admin credential and the data-encryption key.

- **Rotating the master key is a migration.** Set `LITELLM_MIGRATE_FROM_MASTER_KEY=<old>` beside the new key, start once, then remove it. See `docker/README.md`.
- **Adding a fresh salt key to a database with stored credentials breaks decryption of every stored value.** #200 requires that `deploy` change nothing on an existing stack until the operator opts in, and that the key is stable once created.
- `LLMAVEN_SECRETS_LITELLM_SALT_KEY` creates a Key Vault secret today but doesn't reach the container, because it's missing from `key_vault_secret_refs`. The risk comes when someone wires it up on an existing database.
- v1.106.6 refuses to boot when the master key is unset, empty or publicly known, such as `sk-1234`. It compares SHA-256 digests and doesn't check strength, so passing doesn't mean the key is strong.

Unverified: #200's rotation hazard after adopting a salt key came from reading v1.82.3 and is untested. Re-check on the pinned version before writing a runbook.

**Sources:** issues #193, #200; PR #148; docker/README.md; docker/config.yaml; https://github.com/BerriAI/litellm/blob/v1.106.6/litellm/proxy/auth/master_key_boot_check.py

# Related Concepts
- [LiteLLM is pinned by version and digest, and upgrades across migrations are one-way](../decisions/litellm-image-digest-pin-and-one-way-upgrade.md): The boot check arrived with this upgrade
