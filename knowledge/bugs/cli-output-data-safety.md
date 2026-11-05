---
type: Bug
title: CLI tidy-ups can corrupt captured values
description: "Routing all output through Rich wrapped a long PostgreSQL URI captured by a shell, so the backup-infra output value stays on typer.echo."
tags: [cli, rich, backup]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:48Z" }
status: stable
code_refs: [src/llmaven/cli.py]
sources:
  - resource: "PR #136"
  - resource: src/llmaven/cli.py
---

**Status at e248584:** implemented.

Routing all CLI output through Rich wrapped long values, so a 168-character PostgreSQL URI captured by a shell gained newlines. The shell-captured `backup-infra output` value therefore stays on `typer.echo`, while human messages use Rich. A future tidy-up shouldn't move it back.

**Sources:** PR #136; src/llmaven/cli.py

# Related Concepts
- [Backup storage is a separate Pulumi stack; the backup job stays in the main stack](../architecture/backup-storage-isolated-stack.md): The captured value feeds the backup job's deployment
