---
type: Decision
title: "Making a deploy a true no-op: revisions, probes and the preview gate"
description: "deploy --expect-no-changes previews first because Pulumi's own flag errors only after applying; REFRESH_TRIGGER defaults to the current time, and only LiteLLM and the Traefik edge can pin it."
tags: [deploy, pulumi, container-apps]
generated: { by: "claude-code:claude-sonnet-5-5", at: "2026-11-13T21:05:00Z" }
status: stable
code_refs: [src/llmaven/deployment/deploy.py, src/llmaven/infrastructure/resources/container_apps.py, src/llmaven/infrastructure/resources/helpers.py, tests/infrastructure/test_deploy_expect_no_changes.py]
sources:
  - resource: "PRs #49, #170, #171, #172, #212"
  - resource: tests/infrastructure/test_deploy_expect_no_changes.py
  - resource: src/llmaven/infrastructure/main.py
---

**Status at e248584:** implemented, with an open MLflow gap.

- `REFRESH_TRIGGER` defaults to the current time, so every deploy creates a new revision (#49). `litellm.refresh_trigger` pins it, and so does `edge.refresh_trigger` for the Traefik edge; an unpinned edge rolls a new Traefik revision on every deploy, which fails `--expect-no-changes` and can cut long streams on the single entry point. A pinned `revision_suffix` must change in the same deploy as any template change, including removing the sidecar from LiteLLM.
- Liveness and readiness TCP probes are declared explicitly because Azure adds them by default and undeclared ones show as drift.
- Pulumi's `up(expect_no_changes=True)` was rejected as the guard: the Automation API runs `up` with `--skip-preview`, so it errors only after changes are applied, which #170 reproduced. `deploy --expect-no-changes` previews first and refuses unless everything is `same` or `read`, then keeps the flag as a backstop. It also refuses when the state store or resource group is unset, because initialization would change Azure outside the preview.

**Open gap (inferred from the code, not run):** `refresh_trigger` validates on the shared app config, but `create_mlflow_app` doesn't take it. With MLflow enabled, every preview should plan an MLflow change, so `--expect-no-changes` can't pass even when LiteLLM is pinned.

To reconcile a stack that lags main: branch from the deployed commit, add config fields defaulting to old behavior, `refresh`, confirm a zero-change preview, then merge main and treat the resulting diff as an explicit migration (#170-#172).

Enabling Redis on an existing stack reports changes once.

**Sources:** PRs #49, #170, #171, #172, #212; tests/infrastructure/test_deploy_expect_no_changes.py; src/llmaven/infrastructure/main.py

# Related Concepts
- [The Pulumi state store and resource group live outside the Pulumi program](../architecture/pulumi-state-store-bootstrap.md): The preview gate refuses when bootstrap would change Azure
