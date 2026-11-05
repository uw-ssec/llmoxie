---
type: Fact
title: "Rebrand compatibility plan, and llmaven names that look like deployed state but aren't"
description: "The #187 audits recommend one release of overlap for the CLI, env prefix and config filenames, and show several llmaven names are safe to rename."
tags: [rebrand, compatibility]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:48Z" }
status: draft
code_refs: [.gitignore, src/llmaven/infrastructure/utils/secrets.py]
sources:
  - resource: "issue #187 (comments)"
  - resource: .gitignore
  - resource: src/llmaven/cli.py
  - resource: src/llmaven/infrastructure/utils/secrets.py
---

**Status at e248584:** recommendation, not agreed. Main has no `LLMOXIE_SECRETS_*` handling.

Recommended: one release of overlap for the `llmaven` CLI command, `LLMAVEN_SECRETS_*` and config filenames, and no import-path shim. Nothing is published to PyPI or conda-forge under either name. `llmoxie-analysis` documents `llmaven infra extract`, which is why the CLI alias stays.

Traps when it happens:

- If config filenames change, `.gitignore` must keep both patterns, or a renamed config holding secrets could be committed.
- Renaming the compose volume orphans each developer's local database unless the old name is pinned with `name:`.
- String `patch()` targets in tests are missed by a naive package rename.

**Safe, despite appearances:**

- `llmaven_litellm_spend_logs_*` is a zip filename prefix written by `infra extract`, not a database table prefix, as #187's body first claimed.
- Key Vault secret names come from the suffix of `LLMAVEN_SECRETS_*`, so renaming that prefix changes no deployed secret.

**Sources:** issue #187 (comments); .gitignore; src/llmaven/cli.py; src/llmaven/infrastructure/utils/secrets.py

# Related Concepts
- [The llmoxie rebrand must not rename identifiers that carry live state](../decisions/rebrand-keeps-deployed-identifiers.md): Compatibility details for the same rebrand
