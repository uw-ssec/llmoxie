---
type: Fact
title: The deployer is Contributor and cannot make Azure role assignments
description: "Whoever runs infra deploy is Contributor on the subscription, so the program creates no role assignments; isolation uses separate access-policy vaults and keys, not RBAC."
tags: [azure, rbac, key-vault, infra]
generated: { by: "claude-code:claude-sonnet-5-5", at: "2026-11-16T07:25:50Z" }
status: stable
code_refs: [src/llmaven/infrastructure/resources/console_secrets.py, src/llmaven/infrastructure/resources/console_mail.py, src/llmaven/infrastructure/resources/key_vault.py, tests/infrastructure/test_console_secrets.py]
---

Checked 2026-11-15: the operator's `az login` is Contributor on the subscription. That can create identities, vaults (with inline access policies), Communication Services, storage and environment storage, but not `Microsoft.Authorization` role assignments.

## Consequences

- The program never creates `azure_native.authorization.*`. A test asserts it.
- Per-secret RBAC, a managed identity with a role on the mail service, and ACS SMTP login (needs an Entra app) were all ruled out for this reason. The console sends mail with the Communication Service connection string, and each container gets its own access-policy vault.
- Anything new that needs a role assignment needs an owner with more rights, not a workaround.

Not verified: that Contributor can create every console resource; the first dev deploy shows it.
