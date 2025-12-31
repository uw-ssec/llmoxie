# Commit Message Format

LLMaven follows [Conventional Commits](https://www.conventionalcommits.org/).

## Format

```
<type>(<scope>): <subject>
```

---

## Types

| Type | Description |
|------|-------------|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `style` | Formatting, no code change |
| `refactor` | Code restructuring |
| `test` | Adding/updating tests |
| `chore` | Maintenance tasks |
| `perf` | Performance improvements |

---

## Scopes

| Scope | Area |
|-------|------|
| `api` | REST API endpoints |
| `ui` | Streamlit frontend |
| `infra` | Pulumi infrastructure |
| `core` | ML/AI components |
| `cli` | Command-line interface |
| `agentic` | Agentic RAG system |

---

## Examples

```bash
git commit -m "feat(api): add summarization endpoint"
git commit -m "fix(core): handle empty document retrieval"
git commit -m "docs: update API documentation"
git commit -m "refactor(agentic): simplify ingestion pipeline"
git commit -m "test(api): add retrieval endpoint tests"
```
