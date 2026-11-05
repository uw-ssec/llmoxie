---
type: Bug
title: Key Vault access policies get wiped by two separate mechanisms
description: "keyvault.AccessPolicy replaces rather than adds, and updating the Vault rewrites its list, so the stack uses one shared identity and ignores policy changes on the vault."
tags: [azure, key-vault, pulumi]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:47Z" }
status: stable
governance: constraint
code_refs:
  - "src/llmaven/infrastructure/main.py"
  - "src/llmaven/infrastructure/resources/key_vault.py"
sources:
  - resource: "PRs #127, #170, #171, #172"
---

**Status at e248584:** implemented.

1. Per #127, azure-native's `keyvault.AccessPolicy` uses the replace kind for both create and update, so with several `AccessPolicy` resources the last one written survives. All container apps and the backup job therefore share one user-assigned identity and one policy. Per-app identities were rejected for that reason.
2. Updating the `Vault` resource rewrites its whole policy list, which dropped policies added separately. The vault now sets `ignore_changes=["properties.accessPolicies"]` (#170, #172). As a result, edits to the vault's inline deployer policy only take effect on newly created vaults.

Don't add a second `AccessPolicy`, and don't remove the ignore. The comment in `key_vault.py` saying it "adds to the existing policies" contradicts #127.

Moving an existing stack to the shared identity is a create-then-delete migration. New identity access can take a minute to propagate, so a deploy may fail and need a re-run while the current revision keeps serving (#171).

Not verified: the provider behavior comes from #127 and wasn't re-checked against provider source. #170 reports deployer and identity policies coexisting, so how one `replace` treats the inline policy is unclear.

**Sources:** PRs #127, #170, #171, #172
