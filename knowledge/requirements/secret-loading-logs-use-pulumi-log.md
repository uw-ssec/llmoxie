---
type: Requirement
title: Secret-loading diagnostics stay on pulumi.log
description: "Project owner directive on #134: stdlib logging hides found, loaded and skipped secret names by default, so these messages use pulumi.log and never print values."
tags: [pulumi, logging, secrets]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:48Z" }
status: stable
governance: constraint
code_refs: [src/llmaven/infrastructure/utils/secrets.py]
sources:
  - resource: "PRs #129, #134"
  - resource: "issue #89"
  - resource: src/llmaven/infrastructure/utils/secrets.py
---

**Status at e248584:** implemented.

The project owner's directive on #134: secret-loading messages stay on `pulumi.log`, showing found, loaded and skipped secret names and the count, and never values. The contributed switch to stdlib `logging` was reverted because the infrastructure CLI configures no logger and Python defaults to WARNING, so those lines disappear. `pulumi.log.info` sends INFO events to the engine inside a Pulumi runtime and writes to stderr outside one. #129 dropped a similar change for the same reason.

The deduplicated loader itself was kept, and environment values still beat env-file values. #89's closing comment says `secrets.py` moved to `logging`; that's wrong, and main matches #134.

**Sources:** PRs #129, #134; issue #89; src/llmaven/infrastructure/utils/secrets.py

# Related Concepts
- [The llmoxie rebrand must not rename identifiers that carry live state](../decisions/rebrand-keeps-deployed-identifiers.md): The same loader's env prefix is part of the rebrand plan
