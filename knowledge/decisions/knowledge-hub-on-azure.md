---
type: Decision
title: Knowledge hub on Azure
description: "okf-hub runs as an internal Container App in the same deploy, Keycloak tokens only, image from uw-ssec/okf-hub"
tags: [knowledge, azure, okf-hub]
generated: { by: "claude:opus-5.5", at: "2026-11-18T19:16:37Z" }
status: stable
---

## Context

The console's organization knowledge needs an okf-hub. Spec: docs/superpowers/specs/2026-11-17-okf-hub-container-design.md. Builds on the console rollout.

## Decided by the owner (2026-11-17)

- Everything in Azure, one deploy.
- uw-ssec/okf-hub, made container-native; not okf-memory-rs.
- Keycloak tokens only.
- The code lives in uw-ssec/okf-hub, which publishes an image; the owner makes the repository public when ready.
- The Cloudflare version stays on main; the container version is a copy on a branch.
- Organizations that already exist get knowledge when the hub turns on, even if their bundles are empty (the console-know job).

## Consequences

- The hub URL (internal FQDN) is the token audience everywhere and never changes for a stack.
- LLMAVEN_SECRETS_OKF_HUB_MASTER_KEY is generated once by the owner and can never change while bundles exist; it lives only in the hub vault.
- Container Apps here pull only public images, so the dev deploy waits for okf-hub to be public.
- The hub's Blob container is in a storage account of its own, retained like the okf_hub database: in the console's account (not retained) turning the console off would delete bundles the retained database still points at (final review, 2026-11-18).
- Operator steps and unverified items: .agents/rules/infrastructure.md, "The knowledge hub".

# Related Concepts
- [The console runs on the Azure stack from a console block, with a vault per container and mail through ACS](console-on-azure.md): The hub extends the console's Azure rollout and reuses its database job and realm; it keeps its own storage account
