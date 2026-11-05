---
type: Requirement
title: Stack-managed Foundry accepts traffic only from the Container Apps subnet (implemented, unproven on Azure)
description: "`foundry.enabled` creates default-deny ACLs with one subnet rule; the boundary is the whole environment subnet, not LiteLLM, and no live acceptance has run."
tags: [foundry, azure, network]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:48Z" }
status: draft
code_refs: [docker/config.yaml, src/llmaven/infrastructure/resources/foundry.py, src/llmaven/infrastructure/main.py]
stale_after: 2027-05-01
sources:
  - resource: "issues #41, #196, #209"
  - resource: "PR #208"
---

**Status:** implemented in code by #208, off by default, and not yet proven on Azure. No approved deploy has exercised it.

`foundry.enabled` keeps `publicNetworkAccess=Enabled` with `defaultAction=Deny`, `bypass=None`, no IP rules and one VNet rule for `container-apps-subnet`, plus a `Microsoft.CognitiveServices` service endpoint on that subnet. With Foundry disabled, no Foundry resources or service endpoint are created, and `model_list` in `docker/config.yaml` still has to match hand-created models by hand.

**Don't describe this as per-app isolation.** The boundary is the environment subnet, so MLflow and the backup job can reach Foundry too. Isolating LiteLLM needs a separate subnet or a private endpoint.

API-key auth stays because the managed-identity path couldn't be verified without a live deploy. Deployments are chained with `depends_on` because Azure rejects concurrent deployment operations on one account.

#196 requires that `foundry.enabled: false` leaves the plan unchanged so `--expect-no-changes` still passes, and that `versionUpgradeOption` is set so upgrades aren't silent. Quota and regional availability can only be checked against Azure.

The mocks prove resource inputs, not enforcement. Acceptance needs an approved deploy showing a working completion through the gateway and a valid key rejected from outside the subnet.

**Sources:** issues #41, #196, #209; PR #208

# Related Concepts
- [Making a deploy a true no-op: revisions, probes and the preview gate](../decisions/no-op-deploy-controls.md): Disabled features must keep --expect-no-changes passing
