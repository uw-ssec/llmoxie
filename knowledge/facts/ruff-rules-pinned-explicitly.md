---
type: Fact
title: "Ruff rules are pinned explicitly so hook updates can't widen lint policy"
description: "Ruff 0.16 expanded its defaults, so #210 selects E4, E7, E9 and F; adopting more rules should be its own change."
tags: [ruff, pre-commit]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:48Z" }
status: stable
code_refs: [pyproject.toml, .pre-commit-config.yaml]
sources:
  - resource: "PR #210"
  - resource: pyproject.toml
  - resource: .pre-commit-config.yaml
  - resource: "https://github.com/astral-sh/ruff/releases/tag/0.16.0"
---

**Status at e248584:** implemented.

Ruff 0.16 expanded its default rule set, so the #210 hook bump to 0.17.3 produced a repository-wide lint failure. `pyproject.toml` therefore selects `E4`, `E7`, `E9` and `F`, the pre-0.16 defaults. Adopting more rules should be its own change. Doing this edit in `pyproject.toml` also staled `pixi.lock`.

`.agents/rules/code-conventions.md` still says Ruff runs with default settings and that `pyproject.toml` only sets excludes; that's no longer true.

**Sources:** PR #210; pyproject.toml; .pre-commit-config.yaml; https://github.com/astral-sh/ruff/releases/tag/0.16.0

# Related Concepts
- [Any pyproject.toml edit can stale pixi.lock, and a newer local Pixi hides it](pixi-lock-hash-needs-ci-version.md): This edit is what staled the lock on #210
