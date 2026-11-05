---
type: Fact
title: "Azure E2E through floci-az needs a spike and can't replace a real preview"
description: "floci-az 0.15.0 documents only Terraform and OpenTofu and has no Container Apps Jobs handler, so #192 starts with a time-boxed spike; a human-approved real preview stays the gate."
tags: [testing, azure, floci, ci]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:48Z" }
status: draft
code_refs: [src/llmaven/deployment/deploy.py, .github/workflows/ci.yml]
stale_after: 2027-05-01
sources:
  - resource: "issue #192"
  - resource: "PR #212"
  - resource: src/llmaven/deployment/deploy.py
---

**Status at e248584:** open. Nothing has been run; the assessment is from docs and source only.

`tests/infrastructure/` mocks Pulumi, so the Pulumi program and the `az` bootstrap first run against real Azure. #192 proposes `floci-az`.

- Pulumi support is the main unknown. floci documents Terraform and OpenTofu only.
- No `Microsoft.App/jobs` handler was found, so the backup job likely fails. Storage management policies and Key Vault access policies are unverified. The assessment predates #212, so it says nothing about Redis.
- The `az` bootstrap in `initialize_azure_infra()` must be redirected or skipped.
- An emulator pass isn't an Azure pass. floci doesn't enforce VNet delegation, private DNS, RBAC, SKU or quota, so a human-approved `deploy --preview` stays the gate.
- Resources floci can't serve must be skipped through config or test markers, never mocked in product code.

**Sources:** issue #192; PR #212; src/llmaven/deployment/deploy.py

# Related Concepts
- [Managed Redis arrives automatically on the next deploy and is unproven live](managed-redis-rollout-and-limits.md): Another case where mocks prove inputs, not deployability
