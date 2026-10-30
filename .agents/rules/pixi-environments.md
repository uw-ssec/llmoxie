# Pixi Environments & Dependencies

**Load when:** setting up the repo, running any command, adding or changing a
dependency, or editing `pixi.toml`.

## Pixi Overview

This project uses **Pixi** exclusively for dependency and environment
management. Pixi handles both Conda and PyPI dependencies; the `llmaven` package
itself is installed editable from `pyproject.toml` through the `llmaven`
feature. See https://pixi.sh/latest/llms-full.txt for more details.

**ALWAYS use Pixi commands — never use conda, pip, or venv directly.**

## Prerequisites

`pixi.toml` sets `requires-pixi = ">=0.63.2"`, and CI pins
`PIXI_VERSION: v0.63.2`:

```bash
pixi --version  # Must be 0.63.2 or higher
```

If not installed, direct users to: https://pixi.sh/latest/#installation. A newer
Pixi may rewrite `pixi.lock` in a newer lock-file format that CI's Pixi cannot
read; check `git diff pixi.lock` (its first line is `version: <n>`) before
committing a re-solved lock.

## Environment Setup (ALWAYS RUN FIRST)

```bash
# Install the development environment (required before any other commands)
pixi install -e llmaven
```

The `llmaven` environment sets `no-default-feature = true`, so the top-level
`[dependencies]` are **not** in it, and a bare `pixi run <task>` resolves
against a different environment. Always pass `-e llmaven` for development work,
testing, and verification.

## Available Environments

| Environment | Features                                                      | Use for                                       |
| ----------- | ------------------------------------------------------------- | --------------------------------------------- |
| `llmaven`   | `docker`, `llmaven`, `pulumi`, `pre-commit`, `gh-cli`, `okf`  | Development, tests, pre-commit, `verify`, CI  |
| `infra`     | `infra`                                                       | Pulumi/Azure tooling                          |
| `backup`    | `backup`                                                      | `pixi run -e backup backup` (Postgres backup) |
| `default`   | top-level `[dependencies]` only (legacy notebook/panel stack) | Legacy `archive/` tooling; not for new work   |

## Adding Dependencies

```bash
# Add a conda package to a feature
pixi add --feature <feature-name> <package-name>

# Add a PyPI package to a feature
pixi add --feature <feature-name> --pypi <package-name>

# Always run after manual pixi.toml edits
pixi install -e llmaven
```

Runtime dependencies of the `llmaven` package belong in `pyproject.toml`
(`dependencies` or an extra), not in `pixi.toml`. Adding a dependency needs
justification — see [contribution-discipline.md](contribution-discipline.md).

## pixi.toml Structure

- **`[workspace]`**: Project metadata (name, version, platforms, channels)
- **`[environments]`**: Named environments with feature sets
- **`[dependencies]` / `[pypi-dependencies]`**: The `default` environment only,
  because every named environment disables the default feature
- **`[feature.<name>.dependencies]`**: Feature-specific conda packages
- **`[feature.<name>.pypi-dependencies]`**: Feature-specific PyPI packages
- **`[feature.<name>.tasks]`**: Feature-specific Pixi tasks

## Available Pixi Tasks (`-e llmaven`)

Run `pixi task list -e llmaven` to see them all:

- `verify`: `pre-commit-all` + `okf-validate` + `test` — the gate before any
  commit or PR
- `test`: `pytest tests/`, the full suite
- `pre-commit-install` / `pre-commit` / `pre-commit-all`: install hooks, check
  staged files, check all files
- `okf-validate`: `okf validate --strict --drift` on `knowledge/`
- `up` / `down` / `status` / `logs` / `restart`: manage the local Docker stack
- `clean`: `docker-compose down -v` — **deletes the stack's volumes**; ask first
- `install-pulumi`: install the Pulumi CLI into the environment

## GitHub CLI Usage

```bash
pixi run -e llmaven gh --version
pixi run -e llmaven gh <command>   # e.g. gh issue list, gh pr create
```

## OKF Agent Memory Usage

`okf-agent-memory` comes from the `okf` feature, which only the `llmaven`
environment includes. The package installs a binary named **`okf`**:

```bash
pixi run -e llmaven okf version   # 0.7.1 (OKF v0.2 specification) or higher
pixi run -e llmaven okf --help
```

It backs the project memory in `knowledge/`; see the `okf-memory` skill.
