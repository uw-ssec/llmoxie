---
type: Fact
title: "Production-readiness gaps are tracked in #193, and some settings do less than they suggest"
description: "#193 tracks platform gaps; enable_application_insights provisions nothing, and enable_private_endpoints denies access without creating endpoints."
tags: [production, security, config]
generated: { by: "copilot-vscode:ssec-claude-opus-5-5", at: "2026-11-06T03:20:11Z" }
status: stable
code_refs: [src/llmaven/infrastructure/config/schema.py, src/llmaven/infrastructure/config/defaults.py, src/llmaven/infrastructure/resources/key_vault.py, src/llmaven/infrastructure/resources/storage.py, src/llmaven/deployment/validate.py]
sources:
  - resource: "issue #193"
  - resource: "PR #215 (open)"
  - resource: src/llmaven/infrastructure/config/defaults.py
  - resource: src/llmaven/infrastructure/resources/key_vault.py
  - resource: src/llmaven/infrastructure/resources/storage.py
  - resource: src/llmaven/deployment/validate.py
  - resource: docker/config.yaml
  - resource: README.md
---

**Status at e248584:** open. #193 is the tracker, and it deliberately covers what the platform code provisions rather than live deployment specifics. Keep that line in this bundle too, because the repo is public. Redis split out and shipped (#211, #212); salt key split out (#200).

Settings that look active but aren't:

- `monitoring.enable_application_insights` provisions nothing; its only use outside config is the cost estimate in `validate.py`, and loading a config with it set now raises a `FutureWarning`.
- `security.enable_private_endpoints` sets deny rules on Key Vault and storage, but no private endpoint exists for them (`PrivateEndpoint` appears only in `redis.py`). The apps would probably lose access (inferred in #193, not tested), yet the production defaults set it to `True` with the comment "Required for production", and `validate` warns when it's off. Check before relying on `infra init -e prod` output.
- The `mlflow` callbacks in `docker/config.yaml` are static and stay on when `mlflow.enabled` is false.
- The README's Presidio PII masking isn't configured anywhere.

No longer a gap:

- `monitoring.daily_data_cap_gb` is wired to the Log Analytics workspace's `daily_quota_gb` (`main.py:332` via `helpers.py`), so it does cap ingestion. Stacks created by an earlier `infra init` already carry `1.0` (dev) / `5.0` (staging) in their config, so the first deploy after upgrading shows a one-time in-place workspace update. Once the cap is hit the workspace stops ingesting, so the log-based `backup_job_failures` alert may not see new failures until the cap resets.
- Alerting shipped: see decisions/monitoring-alerts-config. It is opt-in per environment through `monitoring.alerts.enabled_alerts`, and its dollar thresholds are still placeholders.

**Sources:** issue #193; PR #215; src/llmaven/infrastructure/config/defaults.py; src/llmaven/infrastructure/main.py; src/llmaven/infrastructure/resources/key_vault.py; src/llmaven/infrastructure/resources/storage.py; src/llmaven/deployment/validate.py; docker/config.yaml; README.md

# Related Concepts
- [Never add a fresh salt key to an existing database, and rotate the master key by migration](../requirements/litellm-master-and-salt-key.md): Salt key was split out of #193
- [Managed Redis arrives automatically on the next deploy and is unproven live](managed-redis-rollout-and-limits.md): Redis was split out of #193
