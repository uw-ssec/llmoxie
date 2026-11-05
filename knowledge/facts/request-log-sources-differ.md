---
type: Fact
title: "ADLS logs, LiteLLM spend logs and MLflow traces are different datasets"
description: "ADLS holds untruncated per-request JSON of successes only, including raw prompts; spend logs may truncate; MLflow traces are a derived view without API keys."
tags: [data, adls, mlflow, privacy]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:48Z" }
status: stable
code_refs: [src/llmaven/infrastructure/resources/adl_logger.py, src/llmaven/data/reader.py, src/llmaven/data/README.md]
sources:
  - resource: "issues #69, #70"
  - resource: "PRs #123, #151, #166, #169"
  - resource: src/llmaven/data/README.md
  - resource: src/llmaven/infrastructure/resources/adl_logger.py
  - resource: docker/config.yaml
---

**Status at e248584:** implemented, with the gaps noted.

- **ADLS** (`AdlLogger`): one JSON file per request, not truncated, and preferred per `src/llmaven/data/README.md`. It defines only `async_log_success_event`, so failed requests are absent, even though a comment in `docker/config.yaml` mentions `async_log_failure_event`. It writes full `kwargs` and the response, which can include prompts and metadata, with no redaction or documented retention (#123 review, still true).
- **LiteLLM spend logs** (`infra extract`): fallback for history predating `AdlLogger`, and may truncate long messages. Older statements that the LiteLLM export is the source of truth (#70) are superseded by that README for the question of which to prefer.
- **MLflow traces**: derived data, not schema-equivalent. LiteLLM's MLflow integration maps only a subset of the logging payload, and traces lacked LiteLLM API keys as observed in January 2026, so they couldn't be told apart by key (#69). That hasn't been re-verified on the current image.

Treat ADLS as success-only and as holding raw prompt data.

**Sources:** issues #69, #70; PRs #123, #151, #166, #169; src/llmaven/data/README.md; src/llmaven/infrastructure/resources/adl_logger.py; docker/config.yaml

# Related Concepts
- [infra extract sits under infra and writes day-partitioned JSONL](../decisions/infra-extract-design.md): Which sources extract reads
- [New data-pipeline features belong in llmoxie-analysis, not src/llmaven/data](../decisions/data-pipeline-moves-to-llmoxie-analysis.md): Sources the analysis pipeline consumes
