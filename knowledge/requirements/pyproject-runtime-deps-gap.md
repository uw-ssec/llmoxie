---
type: Requirement
title: jsonlines and mlflow are imported by the package but declared only in pixi.toml
description: "The owner ruled that package dependencies go in pyproject.toml so pip users get them; jsonlines and mlflow still violate that, so a pip install lacks them (inferred)."
tags: [dependencies, pixi, packaging]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:49Z" }
status: stable
code_refs: [pyproject.toml, pixi.toml, src/llmaven/data/reader.py]
sources:
  - resource: "issue #118"
  - resource: "PR #116"
  - resource: pixi.toml
  - resource: pyproject.toml
  - resource: src/llmaven/data/reader.py
---

**Status at e248584:** open.

The project owner ruled on #116 and #118 that package dependencies go in `pyproject.toml`, because pip users would otherwise miss them, and that `pixi.toml` is for the development environment. The rule is in `.agents/rules/pixi-environments.md`. What isn't stated there: `jsonlines` (`src/llmaven/data/`) and `mlflow` (`src/llmaven/cli.py`) still violate it, so a pip install lacks them (inferred from the manifests). #118's cross-repo sync question has no decision.

**Sources:** issue #118; PR #116; pixi.toml; pyproject.toml; src/llmaven/data/reader.py

# Related Concepts
- [Any pyproject.toml edit can stale pixi.lock, and a newer local Pixi hides it](../facts/pixi-lock-hash-needs-ci-version.md): Fixing this edits pyproject.toml and stales the lock
