---
type: Decision
title: "New data-pipeline features belong in llmoxie-analysis, not src/llmaven/data"
description: The source-adapter PRs were closed because the data pipeline is moving to uw-ssec/llmoxie-analysis; src/llmaven/data still ships on main.
tags: [data, llmoxie-analysis, scope]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:48Z" }
status: draft
code_refs: [src/llmaven/data/reader.py, src/llmaven/data/group_sessions.py]
sources:
  - resource: "PRs #151, #166, #169"
  - resource: "PR #111 (open, no description)"
  - resource: "uw-ssec/llmoxie-analysis#3"
  - resource: src/llmaven/data/
---

**Status at e248584:** the move is planned. `src/llmaven/data/` is still on main, and no issue tracks removing it here.

#166 and #169 (a source adapter over ADLS and LiteLLM) were closed in favor of `uw-ssec/llmoxie-analysis` (llmoxie-analysis#3). Add new data-pipeline features there.

An open design question moved with them: in `auto` mode, any ADLS record for a day means LiteLLM is never queried, so a day where ADLS is only partial silently omits requests. The options recorded are to document it, merge and dedupe by request ID, or compare per-day counts and warn.

A process lesson from the same PRs: #166 was stacked on #151's pre-squash commits, so merging main produced add/add conflicts on every file #151 touched, and its `reader.py` edits would have undone #151's review fixes. #169 rebuilt on main instead. Rebuild, don't merge, a branch stacked on a squash-merged PR.

**Sources:** PRs #151, #166, #169; PR #111 (open, no description); uw-ssec/llmoxie-analysis#3; src/llmaven/data/

# Related Concepts
- [The repo is the LiteLLM and MLflow platform only; RAG lives in llmoxie-rag](platform-only-scope.md): The same scoping decision applied to the data pipeline
