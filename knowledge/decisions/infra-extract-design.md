---
type: Decision
title: infra extract sits under infra and writes day-partitioned JSONL
description: "The project owner placed it under infra because it reads the main infrastructure, and specified one JSONL file per day; MLflow exports partition by experiment and JSONL has an exact newline contract."
tags: [extract, cli, data]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:48Z" }
status: stable
code_refs: [src/llmaven/cli.py, tests/infrastructure/test_cli_extract.py]
sources:
  - resource: "issues #69, #70, #77, #87, #102"
  - resource: "PRs #79, #100, #116"
  - resource: src/llmaven/cli.py
  - resource: tests/infrastructure/test_cli_extract.py
---

**Status at e248584:** implemented. Parquet remains a proposal (#77).

- The project owner moved it from `llmaven agentic extract` to `llmaven infra extract` because it reads the main infrastructure and adds no agentic function (#69). That placement is why it survived the RAG removal (inferred).
- Output is JSON Lines with one file per UTC day, zipped, for evaluation datasets, usage statistics and possible fine-tuning. `--from` and `--to` are inclusive, which supersedes the exclusive end implied in #69. Scheduling is external, with no built-in scheduler (#87).
- MLflow filenames must not say "spend logs", because MLflow logs hold no spend data (#100). Output has one file per date and experiment, `mlflow_traces_<date>_experiment_<id>.jsonl`.
- The JSONL contract is exact: every record ends in `\n`, including the last, and an empty list serializes to `""`. Keep exact-string assertions, since substring checks can't detect a missing final newline (#116).
- It uses LiteLLM's HTTP API, not Postgres. #79's automated summary describes a `psycopg2` extractor that never reached main.

**Sources:** issues #69, #70, #77, #87, #102; PRs #79, #100, #116; src/llmaven/cli.py; tests/infrastructure/test_cli_extract.py

# Related Concepts
- [New data-pipeline features belong in llmoxie-analysis, not src/llmaven/data](data-pipeline-moves-to-llmoxie-analysis.md): Extract output feeds the analysis pipeline
