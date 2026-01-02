# Code Conventions

This document describes the naming conventions and code style patterns used in
LLMaven.

## Naming Conventions

### Files

| Type           | Convention       | Example               |
| -------------- | ---------------- | --------------------- |
| Python modules | `snake_case.py`  | `embedding_model.py`  |
| Config files   | `kebab-case.yml` | `llmaven-config.yaml` |

### Classes

Use `PascalCase`:

```python
class LanguageModel:
class Retriever:
class QdrantManager:
```

### Functions and Methods

Use `snake_case`:

```python
def get_embedding_model(model_name: str):
def retrieve_docs(query: str):
```

### Constants

Use `UPPER_SNAKE_CASE`:

```python
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L12-v2"
DEFAULT_COLLECTION = "research_papers"
```

---

## Code Style

| Setting         | Value            | Config File               |
| --------------- | ---------------- | ------------------------- |
| Max line length | 120 characters   | `.flake8`                 |
| Linter          | Flake8           | `.flake8`                 |
| Formatter       | Pre-commit hooks | `.pre-commit-config.yaml` |

---

## Validation

Before committing, always run:

```bash
pre-commit run --all-files
```

This will automatically check and fix many style issues.

---

## Learning from the Codebase

When in doubt, follow existing patterns in the codebase. Key reference files:

- `src/llmaven/core/embeddings/` — Embedding model patterns
- `src/llmaven/services/` — Service layer patterns
- `src/llmaven/v1/endpoints/` — Endpoint patterns
