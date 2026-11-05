---
type: Decision
title: "Config updates use a ruamel.yaml round-trip, not regex or PyYAML"
description: "The generated config has comments PyYAML would drop; regex was accepted only as a stopgap, and #138 replaced it with ruamel.yaml."
tags: [config, yaml]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:48Z" }
status: stable
code_refs: [src/llmaven/infrastructure/config/loader.py, src/llmaven/infrastructure/config/defaults.py]
sources:
  - resource: "PRs #82, #138"
  - resource: "issue #95"
  - resource: src/llmaven/infrastructure/config/loader.py
---

**Status at e248584:** implemented in `config/loader.py`.

The config is generated from a string template with comments, and PyYAML drops them on rewrite. #82 used regular expressions to avoid a dependency. The project owner's review accepted that only as an intermediary because edge cases could be missed, and asked for a separate issue (#95). #138 delivered the round-trip update. The initial config still comes from the string template in `defaults.py`.

**Sources:** PRs #82, #138; issue #95; src/llmaven/infrastructure/config/loader.py

# Related Concepts
- [The Pulumi state store and resource group live outside the Pulumi program](../architecture/pulumi-state-store-bootstrap.md): Bootstrap writes state names back through this updater
