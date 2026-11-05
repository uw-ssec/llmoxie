---
type: Bug
title: "infra extract has no pagination, and a malformed response still skips a day"
description: "PR #167's title is misleading: the merged code adds a database export, not pagination, and a non-list body still warns and skips while the run succeeds."
tags: [extract, cli, data-loss]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:48Z" }
status: stable
code_refs: [src/llmaven/cli.py, scripts/dbexport.sh]
sources:
  - resource: "issue #88"
  - resource: "PRs #132, #133, #167, #168"
  - resource: src/llmaven/cli.py
  - resource: scripts/dbexport.sh
  - resource: tests/infrastructure/test_cli_extract.py
---

**Status at e248584:** HTTP failure handling is fixed. The two gaps below are open.

**Fixed (#133).** `infra extract` used to sleep after a 5xx, parse the failed response, log "skipping" and report success, so one HTTP 500 produced an empty ZIP and "complete". It now retries 429, 5xx and transport errors up to 5 attempts with backoff, and a day that still fails exits 1. `tenacity` was replaced by a stdlib loop because it became undeclared after the RAG dependency cleanup.

**No pagination.** #167 is titled "Support pagination in data download", and its review describes `/spend/logs/v2`, but that was an intermediate commit. The squash contains no paging; it adds `scripts/dbexport.sh`, which exports `LiteLLM_SpendLogs` from a `pg_dump` backup as JSONL. Main makes one GET per day to `/spend/logs`. Don't trust the PR title when reasoning about completeness. That the export replaced pagination for large pulls is inferred.

**Malformed bodies.** A response body that isn't a JSON list still warns and skips that day, so a run can succeed with a day missing. This was left out of #133's scope.

Separately, `--no-zip` first deleted every regular file in an existing output directory, so it now removes only `<source prefix>*.jsonl` (#132).

**Sources:** issue #88; PRs #132, #133, #167, #168; src/llmaven/cli.py; scripts/dbexport.sh; tests/infrastructure/test_cli_extract.py

# Related Concepts
- [infra extract sits under infra and writes day-partitioned JSONL](../decisions/infra-extract-design.md): Completeness gaps in the same command
