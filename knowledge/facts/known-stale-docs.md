---
type: Fact
title: Docs and comments that disagree with the code at e248584
description: "A checked list of stale statements in the rules, workflow docs and deploy code; trust the code, and remove entries as they're fixed."
tags: [documentation, stale]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:49Z" }
status: stable
code_refs: [.agents/rules/troubleshooting.md, .agents/rules/pixi-environments.md, .agents/rules/pulumi-state-recovery.md, src/llmaven/deployment/deploy.py, pyproject.toml]
stale_after: 2027-05-01
sources:
  - resource: the cited paths
  - resource: "issue #192"
  - resource: "PR #212"
---

**Status at e248584:** each item was checked in the checkout. Fix these rather than keeping them here.

- `.agents/rules/troubleshooting.md` cites a CUDA wheel under `[target.linux-64.pypi-dependencies]`, but `pixi.toml` has no target tables.
- `.agents/rules/pixi-environments.md` calls the default environment a "legacy notebook/panel stack", but `[dependencies]` holds only Python.
- `.agents/rules/pulumi-state-recovery.md`'s resource map predates #212 and lists no Redis resources or `private-endpoints-subnet`, so add those from `redis.py` during a post-Redis recovery.
- `.agents/rules/infrastructure.md` describes `infra extract` as LiteLLM spend logs only, but it also exports MLflow traces.
- `deploy.py` and `deploy_backup.py` call `install_plugin("azure-native", "v2.0.0")`, while the SDK floor is 3.29. #192 flagged this, and its effect is unverified, so don't assume it's harmless or that it's the version in use.
- `deploy.py`'s success message suggests `llmaven status`, but the CLI has `infra status`.
- `pyproject.toml`'s URLs still point at `uw-ssec/llmaven`, and it declares a Python 3.11 classifier despite `requires-python >=3.12`.

Ruff and `pre-commit run` drift are in their own concepts.

**Sources:** the cited paths; issue #192; PR #212

# Related Concepts
- [Ruff rules are pinned explicitly so hook updates can't widen lint policy](ruff-rules-pinned-explicitly.md): Another rule file that has drifted
- [CI was once green while tests failed, and two traps make CI failures hard to reproduce](../bugs/ci-false-green-and-repro-traps.md): Workflow docs that have drifted
