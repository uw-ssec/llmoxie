---
type: Fact
title: "Any pyproject.toml edit can stale pixi.lock, and a newer local Pixi hides it"
description: "pixi.lock holds a hash for the editable package, so even a description edit fails CI's locked install under 0.63.2 before tests run; a newer Pixi accepted the stale lock on #210."
tags: [pixi, ci, lockfile]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:48Z" }
status: stable
code_refs: [pyproject.toml, pixi.lock, .github/workflows/ci.yml]
sources:
  - resource: "PRs #116, #186, #210"
  - resource: commit 5730f27
  - resource: .github/workflows/ci.yml
  - resource: pixi.lock
---

**Status at e248584:** a recurring trap. It hit #186 and #210. `.agents/rules/troubleshooting.md` covers only the lock format.

`pixi.lock` stores a hash for the editable `llmaven` package. Any `pyproject.toml` edit, even a description or a `[tool.ruff]` section, makes it stale. CI then fails at setup, before tests or hooks, with a "lock-file not up-to-date" error, while a local `verify` passes.

Check under CI's version before pushing:

```bash
pixi exec --spec pixi==0.63.2 -- pixi install -e llmaven --locked
```

Regenerate with that same version so only the hash line changes. A newer Pixi rewrites the whole lock to a newer format. When CI reports a Pixi error on a PR that changes dependencies, check lock sync first (#116).

**Sources:** PRs #116, #186, #210; commit 5730f27; .github/workflows/ci.yml; pixi.lock

# Related Concepts
- [CI was once green while tests failed, and two traps make CI failures hard to reproduce](../bugs/ci-false-green-and-repro-traps.md): Another way local and CI results differ
