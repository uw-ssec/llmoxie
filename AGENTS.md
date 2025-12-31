# AGENTS.md - LLMaven AI Assistant Guide

> **Purpose**: Essential technical reference for AI assistants working on the
> LLMaven codebase.

---

## 1. Project Overview

LLMaven is a scientific research tool using Retrieval Augmented Generation (RAG)
to extend LLMs with domain-specific knowledge. Focus areas: astrophysics
research, Rubin Observatory/LSST data.

**Architecture**: Python package with FastAPI backend, Streamlit frontend, and
Azure infrastructure deployment via Pulumi.

---

## 2. Directory Structure

```
llmaven/
├── src/llmaven/                  # Main package (installable)
│   ├── main.py                  # FastAPI application entry point
│   ├── cli.py                   # CLI commands (server, infra)
│   ├── config.py                # Web service configuration
│   ├── v1/                      # API version 1 endpoints
│   │   ├── router.py            # Main v1 router
│   │   └── endpoints/           # Individual endpoint modules
│   ├── schemas/                 # Pydantic request/response models
│   ├── services/                # Business logic layer
│   ├── core/                    # ML/AI components
│   │   ├── embeddings/          # HuggingFace embeddings
│   │   ├── retriever/           # Qdrant vector DB operations
│   │   └── generator/           # HuggingFace LLM inference
│   ├── frontend/                # Streamlit UI
│   ├── agentic/                 # Agentic RAG components
│   │   ├── ingestion/           # Document ingestion pipeline
│   │   ├── vector_store/        # Qdrant manager
│   │   ├── search/              # Search utilities
│   │   └── agent/               # Agent implementations
│   ├── deployment/              # Deployment utilities
│   └── infrastructure/          # Pulumi Azure resources
├── archive/                      # Archived code - DO NOT MODIFY
├── tests/                        # Test suite
├── docker/                       # Docker compose configs
├── pyproject.toml               # Python package metadata
├── pixi.toml                    # Pixi package manager config
└── llmaven-config.yaml          # Infrastructure config (gitignored)
```

### Directory Purposes

| Directory                | Purpose                        | When to Modify                  |
| ------------------------ | ------------------------------ | ------------------------------- |
| `src/llmaven/`           | Main installable package       | Core API development            |
| `src/llmaven/v1/`        | API version 1 endpoints        | Adding/modifying REST endpoints |
| `src/llmaven/core/`      | ML/AI components               | RAG algorithms                  |
| `src/llmaven/services/`  | Business logic                 | Service-level orchestration     |
| `src/llmaven/schemas/`   | API contracts                  | Request/response models         |
| `src/llmaven/frontend/`  | Streamlit UI                   | User interface changes          |
| `src/llmaven/agentic/`   | Agentic RAG system             | Agent/ingestion features        |
| `src/llmaven/deployment/`| Deployment utilities           | Deployment workflows            |
| `archive/`               | Archived code                  | **Do not modify**               |
| `tests/`                 | Test suite                     | Adding tests                    |

---

## 3. Code Organization

### Naming Conventions

**Files**: `snake_case.py` for Python, `kebab-case.yml` for configs

**Classes**: `PascalCase`

```python
class LanguageModel:
class Retriever:
class QdrantManager:
```

**Functions/Methods**: `snake_case`

```python
def get_embedding_model(model_name: str):
def retrieve_docs(query: str):
```

**Constants**: `UPPER_SNAKE_CASE`

```python
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L12-v2"
```

### Code Style

- **Line length**: 120 characters max (`.flake8`)
- **Linting**: Flake8
- **Pre-commit hooks**: Run `pre-commit run --all-files` before committing

---

## 4. Adding New Features

### Add a New API Endpoint

1. **Create Schema** (`src/llmaven/schemas/new_feature.py`):

```python
from pydantic import BaseModel

class NewFeatureRequest(BaseModel):
    param: str

class NewFeatureResponse(BaseModel):
    result: str
    status_code: int
```

2. **Create Service** (`src/llmaven/services/new_feature_service.py`):

```python
def process_feature(param: str) -> dict:
    # Business logic here
    return {"result": "...", "status_code": 200}
```

3. **Create Endpoint** (`src/llmaven/v1/endpoints/new_feature.py`):

```python
from fastapi import APIRouter, HTTPException
from llmaven.schemas.new_feature import NewFeatureRequest, NewFeatureResponse
from llmaven.services.new_feature_service import process_feature

router = APIRouter()

@router.post("/new_feature/", response_model=NewFeatureResponse)
async def new_feature(request: NewFeatureRequest):
    try:
        return process_feature(request.param)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

4. **Register Router** (`src/llmaven/v1/router.py`):

```python
from llmaven.v1.endpoints import new_feature
router.include_router(new_feature.router)
```

5. **Add Tests** (`tests/test_new_feature.py`)

---

## 5. Commit Message Format

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <subject>
```

**Types**: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `perf`

**Scopes**: `api`, `ui`, `infra`, `core`, `cli`, `agentic`

**Examples**:

```bash
git commit -m "feat(api): add summarization endpoint"
git commit -m "fix(core): handle empty document retrieval"
git commit -m "docs: update API documentation"
```

---

## 6. Quick Reference Commands

```bash
# Installation
pixi install                          # Install all dependencies
pixi shell -e llmaven                 # Enter llmaven environment

# Development
llmaven server serve --env development --reload  # Start API (localhost:8000)
llmaven server ui                     # Start Streamlit UI (localhost:8501)
llmaven version                       # Show version

# Infrastructure
llmaven infra init                    # Initialize configuration
llmaven infra validate --strict       # Validate configuration
llmaven infra deploy --preview        # Preview deployment
llmaven infra deploy --yes            # Deploy infrastructure
llmaven infra status                  # Check deployment status
llmaven infra destroy --yes           # Destroy infrastructure

# Testing
pytest                                # Run all tests
pytest tests/test_retriever.py -v     # Run specific test
pytest --cov=llmaven                  # Run with coverage

# Linting
pre-commit run --all-files            # Run all pre-commit hooks
```

---

## 7. Key Technologies

| Category        | Technology    | Purpose                      |
| --------------- | ------------- | ---------------------------- |
| Web Framework   | FastAPI       | REST API                     |
| Frontend        | Streamlit     | Interactive UI               |
| Vector DB       | Qdrant        | Semantic search              |
| LLM Framework   | LangChain     | RAG orchestration            |
| Embeddings      | HuggingFace   | Sentence transformers        |
| Infrastructure  | Pulumi        | Azure deployment             |
| Package Manager | Pixi          | Conda/PyPI unified manager   |

---

## 8. Common Gotchas

### Vector Database

**Problem**: `Collection not found` error

**Solution**: Verify collection name and Qdrant path:

```python
from qdrant_client import QdrantClient
client = QdrantClient(path="path/to/qdrant")
print([c.name for c in client.get_collections().collections])
```

### Model Loading

**Problem**: `CUDA out of memory` error

**Solution**: Use quantization:

```python
model.load_language_model(quantization="4bit")  # or "8bit"
```

---

**Last Updated**: 2025-12-30 | **Maintained By**: LLMaven Development Team (UW SSEC)
