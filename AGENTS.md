# AGENTS.md - LLMaven AI Assistant Guide

> Essential context for AI coding assistants. See `agent_docs/` for detailed guides.

---

## Project Overview

**LLMaven** is a scientific research tool that extends LLMs with domain-specific
knowledge using Retrieval Augmented Generation (RAG).

**Users**: Astrophysics researchers working with Rubin Observatory/LSST data.

**Purpose**: Enable researchers to query scientific literature and datasets
using natural language, with answers grounded in domain-specific sources.

**Stack**: Python package with FastAPI backend, Streamlit frontend, and Azure
deployment via Pulumi.

---

## Directory Map

| Path | Purpose | Notes |
|------|---------|-------|
| `src/llmaven/` | Main installable package | Core development |
| `src/llmaven/v1/` | REST API v1 endpoints | Route handlers |
| `src/llmaven/core/` | ML/AI components | Embeddings, retrieval, generation |
| `src/llmaven/services/` | Business logic | Service orchestration |
| `src/llmaven/schemas/` | Pydantic models | API contracts |
| `src/llmaven/frontend/` | Streamlit UI | User interface |
| `src/llmaven/agentic/` | Agentic RAG system | Ingestion, agents, vector store |
| `src/llmaven/infrastructure/` | Pulumi resources | Azure deployment |
| `archive/` | Archived code | **DO NOT MODIFY** |
| `tests/` | Test suite | pytest |

---

## Essential Commands

```bash
# Environment
pixi install                              # Install dependencies
pixi shell -e llmaven                     # Enter environment

# Development
llmaven server serve --env development --reload  # API (localhost:8000)
llmaven server ui                                # Streamlit (localhost:8501)

# Testing & Validation
pytest --cov=llmaven                      # Run tests with coverage
pre-commit run --all-files                # Lint and format
```

---

## Key Technologies

| Category | Technology | Purpose |
|----------|------------|---------|
| API | FastAPI | REST endpoints |
| UI | Streamlit | Interactive frontend |
| Vector DB | Qdrant | Semantic search |
| LLM | LangChain + HuggingFace | RAG orchestration |
| Infra | Pulumi | Azure deployment |
| Package Manager | Pixi | Dependencies |

---

## Documentation Index

Before starting work, review relevant docs in `agent_docs/`:

| Document | When to Read |
|----------|--------------|
| [`adding_endpoints.md`](agent_docs/adding_endpoints.md) | Adding new API endpoints |
| [`code_conventions.md`](agent_docs/code_conventions.md) | Naming patterns, style questions |
| [`commit_messages.md`](agent_docs/commit_messages.md) | Writing commit messages |
| [`infrastructure.md`](agent_docs/infrastructure.md) | Pulumi/Azure deployment |
| [`troubleshooting.md`](agent_docs/troubleshooting.md) | Debugging common issues |

---

## Critical Reminders

- **Never modify `archive/`** — Contains legacy code for reference only
- **Run `pre-commit run --all-files`** before committing
- **Configuration file `llmaven-config.yaml`** is gitignored (contains secrets)

---

**Last Updated**: 2025-12-31 | **Maintained By**: LLMaven Development Team (UW SSEC)
