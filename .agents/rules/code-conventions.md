# Code Conventions

**Load when:** naming a new module, class, function or constant, or answering a
style question.

## Naming

| Kind              | Convention         | Example                                  |
| ----------------- | ------------------ | ---------------------------------------- |
| Python modules    | `snake_case.py`    | `qdrant_manager.py`                      |
| Classes           | `PascalCase`       | `LanguageModel`, `QdrantManager`         |
| Functions/methods | `snake_case`       | `retrieve_docs()`, `perform_retrieval()` |
| Constants         | `UPPER_SNAKE_CASE` | `MODEL_INSTANCES`                        |
| Config files      | `kebab-case.yaml`  | `llmaven-config.yaml`                    |

## Style

Ruff lints and formats Python through pre-commit (`ruff-check --fix` and
`ruff-format`), with its default settings. `pyproject.toml` only sets excludes.
The `.flake8` file in the repo root isn't used by any hook or CI job. Don't
follow its 120-character limit; `ruff-format` wraps at 88. Run
`pixi run -e llmaven pre-commit-all`; see
[pre-commit-and-quality.md](pre-commit-and-quality.md).

## Follow Existing Patterns

When unsure, copy the nearest existing code:

- `src/llmaven/cli.py`: Typer commands
- `src/llmaven/deployment/`: `infra init|validate|deploy` logic (see
  [infrastructure.md](infrastructure.md))
- `src/llmaven/infrastructure/resources/`: Pulumi resources
- `src/llmaven/data/`: request-log tooling
