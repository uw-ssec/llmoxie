---
type: Fact
title: What a fresh stack needs for LiteLLM to start
description: "LiteLLM runs migrations at boot and needs a long probe budget, apps must depend on the access policy, and the subnet needs explicit delegation."
tags: [container-apps, litellm, pulumi]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:48Z" }
status: stable
code_refs: [src/llmaven/infrastructure/resources/container_apps.py, src/llmaven/infrastructure/main.py]
sources:
  - resource: "PR #120"
---

**Status at e248584:** implemented (#120).

Three failures seen on a fresh stack:

- LiteLLM connects to Postgres and runs migrations at boot. A startup probe with `failure_threshold=10` and `period_seconds=10` killed it with exit 137 after about 110 s, made worse by too little CPU and memory. The threshold is now 30.
- Discarding the return value of `grant_key_vault_access()` left no dependency edge, so apps were created in parallel with their policy and failed with "Unable to get value using Managed identity". Apps must `depends_on` the policy.
- The Container Apps subnet needs explicit delegation to `Microsoft.App/environments`, or Azure fails with `ManagedEnvironmentSubnetDelegationError`.

**Sources:** PR #120

# Related Concepts
- [Key Vault access policies get wiped by two separate mechanisms](../bugs/key-vault-access-policy-replace.md): Access policy ordering
