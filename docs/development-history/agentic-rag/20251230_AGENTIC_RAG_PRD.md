# Product Requirements Document: Agentic RAG Agent (Qdrant Edition)

## Executive Summary

The Agentic RAG Agent is an intelligent document retrieval and
question-answering system that combines semantic vector search with keyword
search and advanced reranking to deliver high-quality responses from a knowledge
base. Built on **Qdrant**'s hybrid search capabilities and **Pydantic AI**, this
system enables users to interact conversationally with their document
collections through an intelligent agent that can perform both conceptual
queries and precise keyword searches, refined by ColBERT reranking.

The core innovation lies in leveraging **Qdrant's Hybrid Search** (Dense +
Sparse) combined with **ColBERT Reranking** (Late Interaction). This approach
provides superior retrieval accuracy compared to single-method search systems.
The ingestion pipeline uses `docling` for multi-format document processing and
intelligent chunking that preserves document structure and hierarchical context.

The MVP focuses on delivering a production-ready CLI-based conversational agent
capable of ingesting documents, storing them in Qdrant with rich metadata, and
providing accurate retrieval through a 3-stage search pipeline (Prefetch
Dense/Sparse -> Rerank).

## Mission

**Empower users to extract actionable insights from their document collections
through intelligent, context-aware conversational search powered by Qdrant and
modern Agentic AI techniques.**

### Core Principles

1.  **Retrieval Accuracy First**: Hybrid search (Dense+Sparse) followed by
    ColBERT Reranking ensures top-tier relevance.
2.  **Document Fidelity**: Preserve original document structure, rich metadata
    (headings), and source attribution.
3.  **Production-Ready Architecture**: Build on Qdrant's scalable vector engine
    with robust client management.
4.  **Developer-Friendly**: Type-safe code with `pydantic-ai` and `fastembed`
    for easy extensibility.
5.  **Transparent Operation**: Users can see citations and relevance scores in
    the structured output.

## Target Users

### Primary User Persona: Technical Knowledge Worker

- **Role**: Software Engineer, Data Scientist, Researcher, or Technical Writer.
- **Goal**: Quickly find specific information, code snippets, or conceptual
  explanations within large repositories of technical documents (PDFs, Markdown,
  etc.).
- **Pain Points**: "Cmd+F" doesn't work for concepts; pure vector search misses
  specific keywords; standard RAG hallucinates or misses context.

## MVP Scope

### In Scope: Core Functionality

- **Ingestion Pipeline**: recursive file reading, `docling` processing, text
  chunking, and generation of Dense+Sparse+ColBERT embeddings.
- **Vector Store**: Qdrant (local/docker) with Named Vectors config.
- **Search Engine**: Hybrid Prefetch (Dense + BM25) + ColBERT Reranker.
- **Agent**: Pydantic-AI agent with a `search_knowledge_base` tool.
- **CLI**: `typer` app with `ingest` and `chat` commands.
- **Structured Citations**: Answers must include source file and relevance
  confidence.

### Out of Scope: Future Enhancements (Deferred Phases)

- **Advanced Agentic Patterns**: Query Routing, Self-Correction loops,
  Plan-and-Execute (Deferred to Phase 5).
- **Automated Eval Pipeline**: Golden dataset generation and Hit-Rate
  calculation (Deferred to Phase 6).
- **Cloud Deployment**: Initial focus is local Docker or Cloud API connection.

## Technology Stack

### Package Management

- **Pixi**: Fast, reproducible package manager for Python/Conda ecosystems.

### Core Python Dependencies

**AI & LLM**

- `pydantic-ai`: Agent framework.
- `pydantic`: Data validation.
- `pydantic-settings`: Config management.
- `openai`: Standard SDK for LLM interactions.

**Vector Database**

- `qdrant-client`: Async/Sync client for Qdrant.
- `fastembed`: Efficient, local embedding generation (Dense, Sparse, ColBERT).

**Document Processing**

- `docling`: Multi-format converter (PDF, MD, HTML, etc.).

**CLI & UI**

- `typer`: CLI framework.
- `rich`: Terminal formatting.

### System Requirements

- **Python**: 3.10+
- **Docker**: For running local Qdrant instance.

## Implementation Phases

### Phase 1: Project Scaffolding & Configuration

**Goal**: Establish project foundation. **Deliverables**:

- Project structure with `pixi`.
- `Settings` class (Qdrant URL, API Keys).
- Dependencies installed (`qdrant-client`, `fastembed`, etc.).

### Phase 2: Document Ingestion Pipeline

**Goal**: Build pipeline from documents to Qdrant Points. **Deliverables**:

- `docling` integration for reading and Hierarchical Chunking.
- `fastembed` integration for 3-vector generation (Dense, Sparse, ColBERT).
- `QdrantManager` with Named Vectors configuration.
- Batch Upsert logic with rich Payload (text, path, headings).
- CLI `ingest` command.

### Phase 3: Search Implementation

**Goal**: High-accuracy retrieval logic. **Deliverables**:

- `HybridSearcher` class.
- Query Embedding generation.
- Prefetch Logic (Dense + Sparse).
- Rerank Logic (ColBERT).

### Phase 4: Basic Agent & CLI

**Goal**: Interactive user experience. **Deliverables**:

- `RAGAgent` using `pydantic-ai`.
- `search_knowledge_base` tool.
- Structured Output (`RAGResponse` with `Citation`).
- CLI `chat` command.

### Phase 5: Advanced Agentic Capabilities (Deferred)

**Goal**: Reasoning and self-correction. **Deliverables**:

- Query Router & Grader.
- Query Rewriting / HyDE.

### Phase 6: Robust Evaluation (Deferred)

**Goal**: Data-driven quality assurance. **Deliverables**:

- Golden Dataset.
- Automated Eval Script (Hit Rate, MRR).

## Appendix

### Project Structure (Proposed)

```
llmaven/
├── src/
│   ├── llmaven/
│   │   ├── agent/              # Pydantic AI Agent & Tools
│   │   ├── cli/                # Typer commands
│   │   ├── config/             # Settings (Pydantic)
│   │   ├── ingestion/          # Docling + FastEmbed pipeline
│   │   ├── search/             # Hybrid Searcher logic
│   │   └── vector_store/       # Qdrant Client manager
├── tests/
├── pixi.toml
└── README.md
```
