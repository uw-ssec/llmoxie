---
type: Requirement
title: Never drop the llmaven blob container from storage config
description: "The container looks like a RAG leftover, but removing a container from config deletes its blob data on the next infra deploy; a test pins the list."
tags: [storage, data-loss, rebrand]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:48Z" }
status: stable
governance: constraint
code_refs: [src/llmaven/infrastructure/config/schema.py, src/llmaven/infrastructure/config/defaults.py, src/llmaven/infrastructure/resources/storage.py, tests/test_platform_scope.py]
sources:
  - resource: "issues #177, #195"
  - resource: "PR #190"
  - resource: tests/test_platform_scope.py
  - resource: src/llmaven/infrastructure/config/defaults.py
  - resource: src/llmaven/infrastructure/resources/adl_logger.py
---

**Status at e248584:** implemented, with a test.

#177 and #195 state this as a hard rule. `tests/test_platform_scope.py::test_storage_keeps_llmaven_container` pins `StorageConfig().containers == ["mlflow", "llmaven", "litellm-logs"]`.

**Gap:** the guard covers the schema default only. The `infra init` defaults in `config/defaults.py` list just `mlflow` and `llmaven`. `AdlLogger` creates `litellm-logs` itself at startup, so the logs container can exist outside the configured list. The effect of that mismatch on a generated config hasn't been verified.

**Sources:** issues #177, #195; PR #190; tests/test_platform_scope.py; src/llmaven/infrastructure/config/defaults.py; src/llmaven/infrastructure/resources/adl_logger.py

# Related Concepts
- [The llmoxie rebrand must not rename identifiers that carry live state](../decisions/rebrand-keeps-deployed-identifiers.md): One of the identifiers that must not change
