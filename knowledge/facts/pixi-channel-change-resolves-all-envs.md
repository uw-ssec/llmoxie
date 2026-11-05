---
type: Fact
title: Changing workspace channels re-solves every Pixi environment
description: "Dropping the pytorch channel in #189 made every lock section stale and would have moved Pulumi and azure-native, so infra and backup were restored by hand."
tags: [pixi, lockfile, dependencies]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:48Z" }
status: stable
code_refs: [pixi.toml, pixi.lock]
sources:
  - resource: "PRs #189, #212"
  - resource: "issue #176"
  - resource: pixi.toml
---

**Status at e248584:** history of #189. The pins below are current.

Channels are workspace-level, so dropping `pytorch` made every environment's lock stale. Pixi 0.63.2 re-solved `infra` and `backup` from scratch without preferring locked versions, which would have upgraded Pulumi and azure-native and downgraded backup's azure-identity. #189 restored main's solutions for those environments and changed only the channel list; re-locking then left the file byte-identical. #212's later azure-native 3.29 upgrade was deliberate.

The same re-solve forced pins that look arbitrary:

- `typer <0.25`, because 0.25+ drops `CliRunner.isolated_filesystem`.
- `importlib-metadata <9`, for mlflow-skinny 3.10.0.
- Explicit `pandas` and `tqdm`, because `llmaven.data` imports them and they used to arrive transitively.

**Sources:** PRs #189, #212; issue #176; pixi.toml

# Related Concepts
- [Any pyproject.toml edit can stale pixi.lock, and a newer local Pixi hides it](pixi-lock-hash-needs-ci-version.md): Same lockfile, different stale-lock cause
