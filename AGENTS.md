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

# Agentic RAG (NEW)
llmaven agentic ingest ./docs             # Ingest documents
llmaven agentic search "query"            # Hybrid search
llmaven agentic chat                      # Interactive RAG chat

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
| Agentic RAG | pydantic-ai + fastembed | Hybrid search with multi-vector embeddings |
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

## Agentic RAG System

The Agentic RAG system is a next-generation retrieval and question-answering system that combines hybrid search (Dense + Sparse + ColBERT) with intelligent agent-based answer generation. It provides superior retrieval accuracy compared to the legacy single-vector search system.

### Architecture Overview

The agentic RAG system consists of four main components:

1. **Ingestion Pipeline** (`src/llmaven/agentic/ingestion/pipeline.py`)
   - Multi-format document processing with `docling`
   - Intelligent chunking that preserves document structure
   - Multi-vector embedding generation (Dense, Sparse, ColBERT)
   - Batch processing with progress indicators

2. **Vector Store** (`src/llmaven/agentic/vector_store/qdrant_manager.py`)
   - Qdrant Named Vectors support
   - Collection management and validation
   - Hybrid search operations

3. **Hybrid Search** (`src/llmaven/agentic/search/hybrid_searcher.py`)
   - Three-stage search pipeline:
     - **Prefetch**: Parallel Dense + Sparse vector queries
     - **Rerank**: Optional ColBERT MaxSim reranking
   - Configurable top-K parameters
   - Score metadata tracking

4. **RAG Agent** (`src/llmaven/agentic/agent/rag_agent.py`)
   - Pydantic-AI based agent with structured output
   - Citation support with relevance scores
   - Multi-provider LLM support (OpenAI, Ollama, HuggingFace)
   - Message history for multi-turn conversations

### Usage Examples

#### CLI Commands

**Ingest Documents:**
```bash
# Ingest documents from a directory
llmaven agentic ingest ./docs

# Ingest from multiple directories with custom collection
llmaven agentic ingest ./docs ./papers --collection research-docs

# Force overwrite existing collection
llmaven agentic ingest ./docs --force

# Custom batch size
llmaven agentic ingest ./docs --batch-size 50
```

**Search Knowledge Base:**
```bash
# Basic hybrid search
llmaven agentic search "What is machine learning?"

# Search with custom top-k
llmaven agentic search "transformer architecture" --top-k 10

# Search without reranking (faster)
llmaven agentic search "vector embeddings" --no-rerank

# Search specific collection
llmaven agentic search "query" --collection my-collection
```

**Interactive Chat:**
```bash
# Start interactive RAG chat
llmaven agentic chat

# Chat with custom collection
llmaven agentic chat --collection my-docs

# Use different LLM provider
llmaven agentic chat --provider ollama --model llama2
```

#### Python API Usage

```python
from llmaven.agentic import RAGAgent, HybridSearcher, IngestionPipeline

# Ingest documents
pipeline = IngestionPipeline(collection_name="docs")
pipeline.ingest(directories=["./docs"], force=True)

# Search
searcher = HybridSearcher(collection_name="docs")
results = searcher.search("What is machine learning?", limit=5)

# Chat with agent
agent = RAGAgent(collection_name="docs")
response = agent.run_sync("Explain transformers")
print(response.answer)
for citation in response.citations:
    print(f"- {citation.source_file}: {citation.relevance_score}")
```

### Configuration Options

The agentic RAG system uses environment variables with the `AGENTIC_` prefix:

**Qdrant Configuration:**
```bash
AGENTIC_QDRANT_URL=http://localhost:6333
AGENTIC_QDRANT_API_KEY=your-api-key  # Optional
AGENTIC_COLLECTION_NAME=agentic-rag
```

**Embedding Models:**
```bash
AGENTIC_DENSE_MODEL=sentence-transformers/all-MiniLM-L6-v2
AGENTIC_SPARSE_MODEL=Qdrant/bm25
AGENTIC_COLBERT_MODEL=colbert-ir/colbertv2.0
```

**LLM Configuration:**
```bash
AGENTIC_LLM_PROVIDER=openai  # Options: openai, ollama, huggingface
AGENTIC_LLM_MODEL=gpt-4o-mini
AGENTIC_HUGGINGFACE_MODEL=optional-local-model
```

**Search Configuration:**
```bash
AGENTIC_ENABLE_RERANK=true
AGENTIC_PREFETCH_TOP_K=20
AGENTIC_FINAL_TOP_K=5
```

### Migration from Legacy System

The agentic RAG system coexists with the legacy `core/retriever/` and `core/embeddings/` modules. During the transition period:

1. **Legacy endpoints remain functional**: `/v1/retrieve` and `/v1/generate` continue to work
2. **New endpoints available**: `/v1/agentic/retrieve` and `/v1/agentic/chat` provide enhanced capabilities
3. **Separate collections**: Agentic system uses its own Qdrant collections (default: `agentic-rag`)
4. **No breaking changes**: Existing code continues to work unchanged

**Key Differences:**

| Feature | Legacy System | Agentic System |
|---------|--------------|----------------|
| Embeddings | Single dense vector | Multi-vector (Dense + Sparse + ColBERT) |
| Search | Single method | Hybrid (Prefetch + Rerank) |
| Document Processing | Basic text extraction | `docling` with structure preservation |
| Answer Generation | Simple prompt | Agent-based with citations |
| Vector Store | Standard Qdrant | Named Vectors support |

**Migration Path:**

1. Start using agentic CLI commands for new document collections
2. Test agentic endpoints alongside legacy endpoints
3. Gradually migrate API consumers to new endpoints
4. Legacy modules will be deprecated in Phase 5+ with migration utilities

---

**Last Updated**: 2025-12-31 | **Maintained By**: LLMaven Development Team (UW SSEC)
