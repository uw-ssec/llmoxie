---
type: Bug
title: "CI was once green while tests failed, and two traps make CI failures hard to reproduce"
description: "The core test step ended in || echo until #184; the pre-commit Pixi task shadows the binary, and Rich colors Typer errors only under GITHUB_ACTIONS."
tags: [ci, pixi, testing]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:48Z" }
status: stable
code_refs:
  - ".github/workflows/ci.yml"
  - ".github/workflows/README.md"
  - "pixi.toml"
  - "tests/infrastructure/test_cli_env_file_validation.py"
sources:
  - resource: "issues #78, #183"
  - resource: "PRs #182, #184"
  - resource: "tests/infrastructure/test_cli_env_file_validation.py"
  - resource: ".github/workflows/README.md"
  - resource: "pixi.toml"
---

**Status at e248584:** fixed in `ci.yml`. The traps remain, and `.github/workflows/README.md` still documents the broken command.

`ci.yml`'s core test step ended in `|| echo`, which turned pytest failures into success, and its summary job only warned. #184 fixed both.

**Pixi task shadowing.** The `pre-commit` task already runs `pre-commit run`, so `pixi run -e llmaven pre-commit run --all-files` becomes `pre-commit run run ...` and fails with "No hook with id 'run'". Use `pre-commit-all`, as CI does. A Pixi task named like an executable shadows it.

**CI-only output.** Rich colors Typer's error box when `GITHUB_ACTIONS` is set, so literal assertions pass locally and fail in CI. Reproduce with `GITHUB_ACTIONS=true`, and assert against `click.unstyle(result.output)`.

**Sources:** issues #78, #183; PRs #182, #184; tests/infrastructure/test_cli_env_file_validation.py; .github/workflows/README.md; pixi.toml
