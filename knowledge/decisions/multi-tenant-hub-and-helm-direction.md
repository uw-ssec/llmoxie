---
type: Decision
title: "Multi-tenant hub on a Helm chart in this repo (draft spec, nothing on main)"
description: "Draft spec on branch docs/multi-tenant-hub-spec: one SSEC hub for several orgs, chart at charts/llmoxie, Pulumi reused around ArgoCD, key-only participants, own console on OSS LiteLLM."
tags: [helm, nebari, multi-tenancy, roadmap]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:49Z" }
status: draft
code_refs: [docker/dockerfiles/mlflow.dockerfile, .github/workflows/build-services.yml]
stale_after: 2027-05-01
sources:
  - resource: "branch docs/multi-tenant-hub-spec (commits 770287f, 1419463; docs/specs/2026-11-02-multi-tenant-hub-design.md)"
  - resource: "issue #193"
  - resource: "bitnami/charts#35164"
  - resource: docker/dockerfiles/mlflow.dockerfile
---

**Status at e248584:** draft. The spec is on the public branch `docs/multi-tenant-hub-spec` (commit `1419463`), marked "draft for review", with no PR. Main has no `charts/`, and that branch could disappear, so read the spec itself for detail. Refs #193.

Decisions recorded there, with D-numbers from the spec:

- **Infrastructure (D1, D2).** Pulumi stage A (network, managed Postgres, bucket, secrets), then `nic deploy`, then Pulumi stage B (workload identity, K8s Secret, values), then ArgoCD installs the chart. The chart lives at `charts/llmoxie`, published to `oci://ghcr.io/uw-ssec/charts` and versioned with the app images.
- **Tenancy (D3-D7).** Platform admin, org lead and participant. Org leads sign in through Keycloak, participants are key-only, the roster lives in Keycloak, and the org-lead console is built here rather than depending on LiteLLM Enterprise.
- **Consent and traces (D8-D10).** No consent, no key, with a per-participant research opt-out. The system of record is an append-only log in object storage written by a LiteLLM callback, and MLflow is optional. Proxy-level traces only, with no client telemetry.
- **Milestone (D11, D12).** Each org brings its own provider keys. Milestone 1 is the hub on Azure.

Known gaps toward this: `mlflow.dockerfile` adds only `azure-storage-blob`, so `s3://` and `gs://` need more packages. `LITELLM_SALT_KEY` must be set before the first model is added. For embedded charts, avoid Bitnami, since its free catalog ended (bitnami/charts#35164).

**Sources:** branch docs/multi-tenant-hub-spec (commits 770287f, 1419463; docs/specs/2026-11-02-multi-tenant-hub-design.md); issue #193; bitnami/charts#35164; docker/dockerfiles/mlflow.dockerfile

# Related Concepts
- [LiteLLM stays as the gateway; OSS limits shape what must be built around it](stay-on-oss-litellm-gateway.md): Why the console is custom
- [Never add a fresh salt key to an existing database, and rotate the master key by migration](../requirements/litellm-master-and-salt-key.md): The spec sets the salt key before the first model
- [Production-readiness gaps are tracked in #193, and some settings do less than they suggest](../facts/production-readiness-gaps.md): The spec maps onto #193 items
