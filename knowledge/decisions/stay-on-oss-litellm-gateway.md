---
type: Decision
title: LiteLLM stays as the gateway; OSS limits shape what must be built around it
description: "Moving to MLflow's AI Gateway was recommended against as of 2026-10-30, and OSS LiteLLM refuses Admin UI SSO past 5 user rows, which limits what can be built on it."
tags: [litellm, mlflow, gateway, licensing]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:36:28Z" }
status: draft
code_refs: [docker/dockerfiles/litellm.dockerfile, docker/config.yaml]
stale_after: 2027-05-01
sources:
  - resource: "https://github.com/BerriAI/litellm/blob/v1.106.6/litellm/proxy/management_endpoints/ui_sso.py"
  - resource: "https://github.com/BerriAI/litellm/blob/v1.106.6/litellm/repositories/user_repository.py"
  - resource: "mlflow/mlflow#26123"
  - resource: "mlflow/rfcs#63"
---

**Status:** a research recommendation as of 2026-10-30, with no recorded decision. Behavior below is a dated snapshot of upstream, so recheck before relying on it.

**MLflow AI Gateway (as of 2026-10-30).** Its advantages were one less service, native tracing and less LiteLLM supply-chain exposure. Against it: OSS auth was HTTP Basic with no per-user keys, per-endpoint rate limiting was closed unmerged (mlflow/mlflow#26123), and budgets across replicas would still need Redis. An RFC for rate limits has merged (mlflow/rfcs#63), so revisit once token auth and per-consumer limits ship.

**OSS LiteLLM.** In v1.106.6, `_raise_if_sso_exceeds_free_user_limit` refuses Admin UI SSO once `count_billable_users()` exceeds 5, and that count covers every user row except SCIM-deactivated ones, not just SSO logins. Per-participant user rows therefore trip it. The management API was reported as working without a license, while team admins, team-scoped models, RBAC and audit logs were reported as licensed, so anything built on OSS must provide those itself. Patching out the check was advised against as an upgrade burden.

**Sources:** https://github.com/BerriAI/litellm/blob/v1.106.6/litellm/proxy/management_endpoints/ui_sso.py; https://github.com/BerriAI/litellm/blob/v1.106.6/litellm/repositories/user_repository.py; mlflow/mlflow#26123; mlflow/rfcs#63

# Related Concepts
- [LiteLLM is pinned by version and digest, and upgrades across migrations are one-way](litellm-image-digest-pin-and-one-way-upgrade.md): The version this snapshot was read at
