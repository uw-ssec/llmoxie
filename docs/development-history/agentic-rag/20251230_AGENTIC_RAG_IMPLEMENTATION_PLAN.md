# Agentic RAG Implementation Roadmap (Phases 1-4)

This plan details the roadmap for implementing the Agentic RAG system within
`llmaven`, covering Phases 1 through 4 as outlined in the
[AGENTIC_RAG_PLAN.md](./AGENTIC_RAG_PLAN.md) and informed by the
[AGENTIC_RAG_FEEDBACK.md](./AGENTIC_RAG_FEEDBACK.md).

## Architecture Decision

> [!NOTE] **Decision**: The new Agentic RAG modules will **eventually replace**
> the existing `core/retriever/` and `core/embeddings/` modules.
>
> The existing modules use `langchain` and `HuggingFaceEmbeddings`. The new
> components will use `fastembed` for multi-vector embeddings and direct
> `qdrant-client` for Named Vector support. During the transition, both will
> co-exist, but the legacy modules will be deprecated and removed in a future
> phase.

### Deprecation Timeline

| Phase     | Milestone                   | Legacy Module Status                                                 |
| --------- | --------------------------- | -------------------------------------------------------------------- |
| Phase 1-4 | Agentic RAG MVP             | Legacy modules fully functional, no changes                          |
| Phase 5   | Feature parity achieved     | Add deprecation warnings to `core/retriever/` and `core/embeddings/` |
| Phase 6   | Migration period (3 months) | Document migration path, provide conversion utilities                |
| Phase 7   | Legacy removal              | Remove `core/retriever/` and `core/embeddings/` modules              |

**Migration Path for Existing Users**:

1. Existing Qdrant collections will continue to work with legacy `Retriever`
2. New `QdrantManager` can import/convert legacy collections to Named Vectors
   format (conversion utility planned for Phase 5)
3. API endpoints will maintain backward compatibility via versioning (`/v1/` vs
   `/v2/`)
4. Deprecation warnings will be logged 3 months before removal

---

## Phase 1: Project Scaffolding & Configuration

**Goal**: Establish the project foundation with new dependencies and a dedicated
`Settings` class for the agentic components.

### Proposed Changes

#### [MODIFY] `pyproject.toml`

Add the following new dependencies to the core `dependencies` list with proper
version constraints:

- `pydantic-ai` (Agent Framework)
- `fastembed` (Multi-vector Embeddings: Dense, Sparse, ColBERT)
- `docling` (Multi-format Document Processing)
- `rich` (Enhanced CLI output)

**⚠️ Pre-requisite**: Verify all dependencies support Python 3.12 before adding.

```diff
 dependencies = [
+    "pydantic-ai>=0.1.0,<1.0",
+    "fastembed>=0.5.0,<1.0",
+    "docling>=1.0.0,<2.0",
+    "rich>=13.0.0,<14.0",
     "fastapi>=0.115.0,<1",
     # ... rest of existing dependencies
 ]
```

**Note**: The current `qdrant-client>=1.11.2,<1.12` constraint is compatible
with Named Vectors (requires Qdrant 1.7.0+). Consider updating to
`>=1.11.2,<2.0` to allow future versions, but verify ColBERT `MaxSim`
multivector config is available in 1.11.2.

---

#### [NEW] `src/llmaven/agentic/settings.py`

Create a new `Settings` class using `pydantic-settings` to manage configuration
for the agentic components. This will live in a new `agentic/` directory.

**⚠️ Important**: Follow the existing pattern from `src/llmaven/config.py`:

- Use `pydantic_settings.BaseSettings`
- Use `SettingsConfigDict` with `env_file`, `env_prefix`, `extra="ignore"`
- Create a global instance for easy access

**Implementation pattern:**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class AgenticConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Ignore unexpected environment variables
        env_prefix="AGENTIC_",  # Consistent with API_ prefix pattern
    )

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    collection_name: str = "agentic-rag"
    dense_model: str = "sentence-transformers/all-MiniLM-L12-v2"  # 384-dim
    sparse_model: str = "Qdrant/bm25"
    colbert_model: str = "colbert-ir/colbertv2.0"
    llm_provider: str = "openai"  # Options: "openai", "ollama", "huggingface"
    llm_model: str = "gpt-4o-mini"
    # Additional fields for HuggingFace integration
    huggingface_model: str | None = None  # For local HuggingFace models
    enable_rerank: bool = True
    prefetch_top_k: int = 20
    final_top_k: int = 5

# Global configuration instance
config = AgenticConfig()
```

**Key fields:**

- `qdrant_url: str` (default: `http://localhost:6333`)
- `qdrant_api_key: Optional[str]`
- `collection_name: str` (default: `agentic-rag`) - **Note**: Consider namespace
  prefix to avoid conflicts
- `dense_model: str` (default: `sentence-transformers/all-MiniLM-L12-v2`) -
  **Updated**: Use L12 variant for 384-dim
- `sparse_model: str` (default: `Qdrant/bm25`)
- `colbert_model: str` (default: `colbert-ir/colbertv2.0`)
- `llm_provider: str` (e.g., `openai`, `ollama`, `huggingface`) - **Added**:
  Support for HuggingFace
- `llm_model: str` (e.g., `gpt-4o-mini`)
- `huggingface_model: str | None` - **Added**: For local HuggingFace model
  integration
- `enable_rerank: bool` (default: `True`)
- `prefetch_top_k: int` (default: `20`)
- `final_top_k: int` (default: `5`)

---

## Pre-Phase 2: Technical Verification

> [!IMPORTANT] Before proceeding with Phase 2 implementation, the following
> technical verifications must be completed to ensure compatibility.

### Qdrant Named Vectors Verification

| Verification Item                                       | Expected             | Status               |
| ------------------------------------------------------- | -------------------- | -------------------- |
| Collection creation with 3 named vectors                | Works                | ✅ Verified (1.11.3) |
| Sparse vector format (dict with `indices` and `values`) | Compatible           | ✅ Verified          |
| `MultiVectorConfig` with `Comparator.MAX_SIM` exists    | Available in 1.11.2+ | ✅ Verified          |

> [!TIP] **Version Constraint Recommendation**: The current
> `qdrant-client>=1.11.2,<1.12` constraint in `pyproject.toml` is narrow but
> safe. After Phase 2 implementation is complete and tested, consider relaxing
> to `>=1.11.2,<2.0` for better future compatibility.

**Test Script**:

```python
from qdrant_client import QdrantClient
from qdrant_client.models import (
    VectorParams, Distance, SparseVectorParams,
    MultiVectorConfig, MultiVectorComparator
)

client = QdrantClient(":memory:")

# Verify named vectors with ColBERT multivector config
client.create_collection(
    collection_name="test_collection",
    vectors_config={
        "dense": VectorParams(size=384, distance=Distance.COSINE),
        "colbert": VectorParams(
            size=128,
            distance=Distance.COSINE,
            multivector_config=MultiVectorConfig(
                comparator=MultiVectorComparator.MAX_SIM
            )
        ),
    },
    sparse_vectors_config={
        "sparse": SparseVectorParams(),
    }
)
print("✅ Named Vectors with ColBERT MaxSim verified!")
```

### fastembed Model Verification

| Model                                     | Expected Dimensions  | Status     |
| ----------------------------------------- | -------------------- | ---------- |
| `sentence-transformers/all-MiniLM-L12-v2` | 384                  | ⏳ Pending |
| `Qdrant/bm25`                             | Sparse (dict format) | ⏳ Pending |
| `colbert-ir/colbertv2.0`                  | 128 per token        | ⏳ Pending |

**Test Script**:

```python
from fastembed import TextEmbedding, SparseTextEmbedding, LateInteractionTextEmbedding

# Dense model
dense = TextEmbedding("sentence-transformers/all-MiniLM-L12-v2")
dense_vec = list(dense.embed(["test"]))[0]
assert len(dense_vec) == 384, f"Expected 384, got {len(dense_vec)}"
print(f"✅ Dense model: {len(dense_vec)} dimensions")

# Sparse model
sparse = SparseTextEmbedding("Qdrant/bm25")
sparse_vec = list(sparse.embed(["test"]))[0]
print(f"✅ Sparse model: {type(sparse_vec)} format")

# ColBERT model
colbert = LateInteractionTextEmbedding("colbert-ir/colbertv2.0")
colbert_vec = list(colbert.embed(["test"]))[0]
print(f"✅ ColBERT model: {colbert_vec.shape} shape")
```

### Model Caching Strategy

fastembed models are automatically cached to `~/.cache/fastembed/` on first use:

| Aspect         | Behavior                                                                |
| -------------- | ----------------------------------------------------------------------- |
| First download | Models downloaded automatically on first use                            |
| Cache location | `~/.cache/fastembed/` (configurable via `FASTEMBED_CACHE_PATH` env var) |
| Offline mode   | Set `FASTEMBED_CACHE_PATH` to pre-downloaded models directory           |
| Cache size     | ~500MB for all 3 models combined                                        |

**Recommendations**:

- Document first-run download behavior for users
- For CI/CD: Pre-cache models or mock embedding calls
- For air-gapped environments: Pre-download models and set
  `FASTEMBED_CACHE_PATH`

---

## Phase 2: Qdrant Client & Ingestion Pipeline

**Goal**: Build the ingestion pipeline from documents to Qdrant Points with
**Named Vectors** (Dense, Sparse, ColBERT).

### Proposed Changes

#### [NEW] `src/llmaven/agentic/vector_store/qdrant_manager.py`

Implement the `QdrantManager` class to handle all Qdrant interactions.

**Key responsibilities:**

- `ensure_collection()`: Create or verify the collection with Named Vectors
  config:
  - `dense`: `size=384`, `distance=Cosine`
  - `sparse`: `index_type=Sparse`
  - `colbert`: `size=128`, `distance=Cosine`, `multivector_config=MaxSim`
- `upsert_points(points: list[PointStruct])`: Batch upsert with rich payloads.
- `search(query_vectors: dict, limit: int)`: Execute Prefetch + Rerank query.
- `validate_collection_exists(collection_name: str)`: Check if collection exists
  before operations.
- `delete_collection(collection_name: str, confirm: bool = False)`: Safe
  collection deletion.

**⚠️ Verification Required**:

- Confirm `MaxSim` is the correct config name in Qdrant 1.11.2
- Verify ColBERT model produces 128-dim vectors
- Test sparse vector format (dict vs list) compatibility

**Error Handling**:

- Raise `QdrantConnectionError` for connection issues
- Raise `CollectionNotFoundError` when collection doesn't exist
- Implement retry logic for transient failures

---

#### [NEW] `src/llmaven/agentic/ingestion/pipeline.py`

Implement the `IngestionPipeline` class.

**Key responsibilities:**

1. **Load**: Traverse input directories, filter by supported file types (PDF,
   MD, TXT, etc.).
2. **Parse**: Use `docling` to convert documents and extract `heading_hierarchy`
   metadata.
   - **Fallback**: If `docling` fails, use basic text extraction (PyMuPDF for
     PDFs, file read for text)
3. **Chunk**: Use `docling`'s Hybrid Chunking strategy.
4. **Embed**: Use `fastembed` to generate 3 vectors per chunk (Dense, Sparse,
   ColBERT).
5. **Upsert**: Construct `PointStruct` objects with:
   - `vectors`: `{"dense": [...], "sparse": {...}, "colbert": [...]}`
   - `payload`:
     `{"text": "...", "file_path": "...", "heading_hierarchy": "...", "chunk_index": N, "content_hash": "..."}`

**Additional features:**

- **Batch Processing**: Process documents in batches for large collections
- **Progress Indicators**: Use `rich` for progress bars and status updates
- **Collection Validation**: Check if collection exists and warn before
  overwriting (unless `--force` flag)
- **Content Hashing**: Generate MD5/SHA256 hashes to detect duplicate content
- **Error Recovery**: Continue processing remaining documents if one fails

**Collection Naming**:

- Validate collection names to prevent conflicts with existing collections
- Consider namespace prefix: `agentic_{collection_name}` for automatic
  namespacing
- Add `--force` flag to allow overwriting existing collections

---

#### [NEW] `src/llmaven/agentic/__init__.py`

Create the `agentic` package with proper module structure.

**Package structure:**

```
agentic/
├── __init__.py
├── settings.py
├── vector_store/
│   ├── __init__.py
│   └── qdrant_manager.py
├── ingestion/
│   ├── __init__.py
│   └── pipeline.py
├── search/
│   ├── __init__.py
│   └── hybrid_searcher.py
└── agent/
    ├── __init__.py
    ├── rag_agent.py
    └── models.py
```

---

## Phase 3: Search Implementation

**Goal**: Implement high-accuracy hybrid retrieval with Prefetch (Dense +
Sparse) and Rerank (ColBERT).

### Proposed Changes

#### [NEW] `src/llmaven/agentic/search/hybrid_searcher.py`

Implement the `HybridSearcher` class.

**Key responsibilities:**

1. **Query Embedding**: Generate Dense, Sparse, and ColBERT vectors for the
   input query using `fastembed`.
2. **Prefetch**: Execute parallel Qdrant queries:
   - Dense: Top-K candidates from `dense` vector (configurable via
     `prefetch_top_k`).
   - Sparse: Top-K candidates from `sparse` vector (BM25).
   - **Combination Strategy**: Union of results, then deduplicate by point ID
3. **Rerank**: Use `colbert` vector with `MaxSim` to rerank the combined
   prefetch results (optional via `enable_rerank` flag).
4. **Return**: Final list of `SearchResult` objects (top `final_top_k` results).

**Prefetch Combination Strategy**:

- Take union of Dense and Sparse results
- Deduplicate by point ID (keep highest score)
- If reranking disabled, return top-K by combined score
- If reranking enabled, use ColBERT MaxSim for final ranking

**`SearchResult` model:**

```python
class SearchResult(BaseModel):
    text: str
    file_path: str
    heading_hierarchy: str | None
    score: float
    prefetch_score: float | None  # Original prefetch score before reranking
    rerank_score: float | None     # ColBERT rerank score if enabled
```

**Configuration**:

- `prefetch_top_k`: Number of candidates from each prefetch method (default: 20)
- `final_top_k`: Final number of results to return (default: 5)
- `enable_rerank`: Whether to apply ColBERT reranking (default: True)

---

## Phase 4: Basic Agent & CLI Integration

**Goal**: Expose the RAG capabilities via an interactive Agent and CLI commands.

### Proposed Changes

#### [NEW] `src/llmaven/agentic/agent/models.py`

Define Pydantic models for structured output.

**Key models:**

```python
class Citation(BaseModel):
    source_file: str
    quote: str
    relevance_score: float

class RAGResponse(BaseModel):
    answer: str
    citations: list[Citation]
    confidence: float
```

---

#### [NEW] `src/llmaven/agentic/agent/rag_agent.py`

Define `RAGAgent` using `pydantic-ai`.

**Key responsibilities:**

- Define `search_knowledge_base` tool that wraps `HybridSearcher`.
- Configure structured output using `RAGResponse` model.
- Use Dependency Injection for `QdrantManager` and `HybridSearcher`.

**⚠️ LLM Provider Integration Strategy**:

The current codebase uses HuggingFace models via `LanguageModel` class
(`src/llmaven/core/generator/language_model.py`). `pydantic-ai` primarily
supports OpenAI and Ollama out of the box.

**Options**:

1. **Option A (Recommended for MVP)**: Use `pydantic-ai` with OpenAI/Ollama for
   agentic features, keep HuggingFace separate for generation
2. **Option B**: Create custom `pydantic-ai` provider adapter for HuggingFace
   models
3. **Option C**: Use `pydantic-ai` for structured output only, call HuggingFace
   `LanguageModel` directly

**Implementation Notes**:

- If using OpenAI/Ollama: Configure via `AgenticConfig.llm_provider` and
  `llm_model`
- If using HuggingFace: Create adapter that wraps existing `LanguageModel` class
- Consider caching agent instances similar to `generation_service.py` model
  caching
- Handle API key requirements gracefully (warn if missing, provide clear error
  messages)

---

#### [MODIFY] `src/llmaven/cli.py`

Add new `typer` subcommands under an `agentic` group, following the existing
pattern.

**Implementation pattern** (consistent with `server_app` and `infra_app`):

```python
agentic_app = typer.Typer(
    name="agentic",
    help="Agentic RAG commands",
    add_completion=False,
)
app.add_typer(agentic_app)
```

**New commands:**

- `llmaven agentic ingest [DIRECTORIES]...`
  - Ingests documents from one or more directories.
  - Options:
    - `--collection` (name): Collection name (default: from config)
    - `--config` (path): Path to settings file
    - `--force`: Overwrite existing collection without confirmation
    - `--batch-size`: Number of documents to process per batch (default: 100)
- `llmaven agentic search <QUERY>`
  - Runs a single hybrid search query and prints results.
  - Options:
    - `--top-k`: Final number of results (default: 5)
    - `--prefetch-k`: Prefetch candidates per method (default: 20)
    - `--rerank/--no-rerank`: Enable/disable ColBERT reranking (default:
      enabled)
    - `--collection`: Collection name (default: from config)
- `llmaven agentic chat`
  - Launches an interactive REPL for conversing with the agent.
  - Options:
    - `--collection`: Collection name (default: from config)
    - `--provider`: LLM provider override (openai, ollama, huggingface)
    - `--model`: LLM model override

---

## Phase 4.5: OpenAI-Compatible Model Support

**Goal**: Extend the Agentic RAG system to support OpenAI-compatible model
providers, specifically LiteLLM (for unified model access) and Azure AI Foundry
(for enterprise Azure deployments).

### Background

`pydantic-ai` supports numerous OpenAI-compatible providers through the
`OpenAIProvider` class and specialized provider classes. This phase adds support
for:

1. **LiteLLM**: A unified interface to 100+ LLM providers (OpenAI, Anthropic,
   Cohere, etc.) via a proxy server or direct SDK
2. **Azure AI Foundry**: Microsoft's enterprise AI platform with Azure OpenAI
   deployments

### Proposed Changes

#### [MODIFY] `src/llmaven/agentic/settings.py`

Update `AgenticConfig` to support additional providers and their configuration:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal

class AgenticConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_prefix="AGENTIC_",
    )

    # Existing fields...
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    collection_name: str = "agentic-rag"
    dense_model: str = "sentence-transformers/all-MiniLM-L12-v2"
    sparse_model: str = "Qdrant/bm25"
    colbert_model: str = "colbert-ir/colbertv2.0"

    # Updated LLM provider configuration
    llm_provider: Literal["openai", "ollama", "huggingface", "litellm", "azure"] = "openai"
    llm_model: str = "gpt-4o-mini"

    # LiteLLM-specific configuration
    litellm_api_base: str | None = None  # e.g., "http://localhost:4000" for proxy
    litellm_api_key: str | None = None
    litellm_model_prefix: str = ""  # e.g., "openai/" or "anthropic/" or "custom/"

    # Azure AI Foundry configuration
    azure_endpoint: str | None = None  # e.g., "https://<resource>.openai.azure.com"
    azure_api_key: str | None = None
    azure_api_version: str = "2024-10-21"  # Default to stable API version
    azure_deployment_name: str | None = None  # Azure deployment name

    # Existing fields...
    huggingface_model: str | None = None
    enable_rerank: bool = True
    prefetch_top_k: int = 20
    final_top_k: int = 5
```

**Environment Variables:**

| Variable                        | Description              | Example                               |
| ------------------------------- | ------------------------ | ------------------------------------- |
| `AGENTIC_LLM_PROVIDER`          | Provider type            | `litellm`, `azure`                    |
| `AGENTIC_LITELLM_API_BASE`      | LiteLLM proxy URL        | `http://localhost:4000`               |
| `AGENTIC_LITELLM_API_KEY`       | LiteLLM API key          | `sk-...`                              |
| `AGENTIC_LITELLM_MODEL_PREFIX`  | Model prefix for LiteLLM | `openai/`, `anthropic/`, `custom/`    |
| `AGENTIC_AZURE_ENDPOINT`        | Azure OpenAI endpoint    | `https://myresource.openai.azure.com` |
| `AGENTIC_AZURE_API_KEY`         | Azure API key            | `abc123...`                           |
| `AGENTIC_AZURE_API_VERSION`     | Azure API version        | `2024-10-21`                          |
| `AGENTIC_AZURE_DEPLOYMENT_NAME` | Azure deployment name    | `gpt-4o-deployment`                   |

---

#### [NEW] `src/llmaven/agentic/providers/__init__.py`

Create a new `providers/` subpackage for provider management.

---

#### [NEW] `src/llmaven/agentic/providers/factory.py`

Implement a provider factory for dynamic provider selection:

```python
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.litellm import LiteLLMProvider

from llmaven.agentic.settings import config
from llmaven.agentic.exceptions import ProviderConfigurationError


def create_llm_model() -> OpenAIChatModel:
    """Create an LLM model based on the configured provider."""
    provider = config.llm_provider.lower()

    if provider == "openai":
        return _create_openai_model()
    elif provider == "ollama":
        return _create_ollama_model()
    elif provider == "litellm":
        return _create_litellm_model()
    elif provider == "azure":
        return _create_azure_model()
    elif provider == "huggingface":
        return _create_huggingface_model()
    else:
        raise ProviderConfigurationError(f"Unsupported provider: {provider}")


def _create_openai_model() -> OpenAIChatModel:
    """Create OpenAI model using default provider."""
    return OpenAIChatModel(config.llm_model)


def _create_ollama_model() -> OpenAIChatModel:
    """Create Ollama model using OpenAI-compatible endpoint."""
    import os
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    return OpenAIChatModel(
        config.llm_model,
        provider=OpenAIProvider(
            base_url=base_url,
            api_key=os.getenv("OLLAMA_API_KEY", "ollama"),  # Ollama doesn't require key
        ),
    )


def _create_litellm_model() -> OpenAIChatModel:
    """Create LiteLLM model for unified provider access."""
    if not config.litellm_api_base:
        raise ProviderConfigurationError(
            "AGENTIC_LITELLM_API_BASE is required for LiteLLM provider"
        )

    # Construct model name with prefix if specified
    model_name = f"{config.litellm_model_prefix}{config.llm_model}"

    return OpenAIChatModel(
        model_name,
        provider=LiteLLMProvider(
            api_base=config.litellm_api_base,
            api_key=config.litellm_api_key,
        ),
    )


def _create_azure_model() -> OpenAIChatModel:
    """Create Azure AI Foundry model."""
    from pydantic_ai.providers.azure import AzureProvider

    if not config.azure_endpoint:
        raise ProviderConfigurationError(
            "AGENTIC_AZURE_ENDPOINT is required for Azure provider"
        )
    if not config.azure_api_key:
        raise ProviderConfigurationError(
            "AGENTIC_AZURE_API_KEY is required for Azure provider"
        )

    # Use deployment name if specified, otherwise use model name
    deployment = config.azure_deployment_name or config.llm_model

    return OpenAIChatModel(
        deployment,
        provider=AzureProvider(
            azure_endpoint=config.azure_endpoint,
            api_key=config.azure_api_key,
            api_version=config.azure_api_version,
        ),
    )


def _create_huggingface_model():
    """Create HuggingFace model adapter."""
    # Placeholder for HuggingFace integration
    # Uses existing LanguageModel class as adapter
    raise NotImplementedError("HuggingFace provider not yet implemented")
```

---

#### [MODIFY] `src/llmaven/agentic/exceptions.py`

Add provider-specific exception:

```python
class ProviderConfigurationError(AgenticRAGError):
    """Provider configuration is invalid or incomplete."""
    pass
```

---

#### [MODIFY] `src/llmaven/agentic/agent/rag_agent.py`

Update `RAGAgent` to use the provider factory:

```python
from pydantic_ai import Agent
from llmaven.agentic.providers.factory import create_llm_model
from llmaven.agentic.agent.models import RAGResponse
from llmaven.agentic.search.hybrid_searcher import HybridSearcher


class RAGAgent:
    def __init__(self, searcher: HybridSearcher):
        self.searcher = searcher
        self.model = create_llm_model()
        self.agent = Agent(
            self.model,
            result_type=RAGResponse,
            system_prompt=self._get_system_prompt(),
        )
        self._register_tools()

    def _get_system_prompt(self) -> str:
        return """You are a helpful RAG assistant. Use the search_knowledge_base
        tool to find relevant information before answering questions. Always
        cite your sources with specific quotes from the retrieved documents."""

    def _register_tools(self):
        @self.agent.tool
        async def search_knowledge_base(ctx, query: str) -> list[dict]:
            """Search the knowledge base for relevant documents."""
            results = await self.searcher.search(query)
            return [
                {
                    "text": r.text,
                    "file_path": r.file_path,
                    "heading": r.heading_hierarchy,
                    "score": r.score,
                }
                for r in results
            ]

    async def query(self, question: str) -> RAGResponse:
        """Query the RAG agent with a question."""
        result = await self.agent.run(question)
        return result.data
```

---

#### [MODIFY] `src/llmaven/cli.py`

Update CLI commands with new provider options:

```python
@agentic_app.command("chat")
def agentic_chat(
    collection: str = typer.Option(None, help="Collection name"),
    provider: str = typer.Option(
        None,
        help="LLM provider override (openai, ollama, litellm, azure, huggingface)"
    ),
    model: str = typer.Option(None, help="LLM model override"),
    litellm_base: str = typer.Option(None, help="LiteLLM proxy base URL"),
    azure_endpoint: str = typer.Option(None, help="Azure AI Foundry endpoint"),
):
    """Launch an interactive chat session with the RAG agent."""
    # Override config with CLI options
    if provider:
        config.llm_provider = provider
    if model:
        config.llm_model = model
    if litellm_base:
        config.litellm_api_base = litellm_base
    if azure_endpoint:
        config.azure_endpoint = azure_endpoint

    # ... rest of implementation
```

---

### LiteLLM Configuration Examples

#### Using LiteLLM Proxy Server

LiteLLM can run as a proxy server that provides a unified OpenAI-compatible API
for multiple providers:

```bash
# Start LiteLLM proxy (separate process)
litellm --model gpt-4o-mini --port 4000

# Configure llmaven to use the proxy
export AGENTIC_LLM_PROVIDER=litellm
export AGENTIC_LITELLM_API_BASE=http://localhost:4000
export AGENTIC_LLM_MODEL=gpt-4o-mini
```

#### Direct LiteLLM SDK Usage

For models that require specific prefixes:

```bash
# Using Anthropic via LiteLLM
export AGENTIC_LLM_PROVIDER=litellm
export AGENTIC_LITELLM_API_BASE=https://api.anthropic.com
export AGENTIC_LITELLM_MODEL_PREFIX=anthropic/
export AGENTIC_LLM_MODEL=claude-3-sonnet-20240229
export ANTHROPIC_API_KEY=sk-...

# Using custom/local models
export AGENTIC_LITELLM_MODEL_PREFIX=custom/
export AGENTIC_LLM_MODEL=my-fine-tuned-model
```

---

### Azure AI Foundry Configuration Examples

#### Standard Azure OpenAI Deployment

```bash
export AGENTIC_LLM_PROVIDER=azure
export AGENTIC_AZURE_ENDPOINT=https://my-resource.openai.azure.com
export AGENTIC_AZURE_API_KEY=abc123...
export AGENTIC_AZURE_API_VERSION=2024-10-21
export AGENTIC_AZURE_DEPLOYMENT_NAME=gpt-4o-deployment
```

#### Using Azure with Managed Identity (Advanced)

For production deployments using Azure Managed Identity:

```python
from azure.identity import DefaultAzureCredential
from pydantic_ai.providers.azure import AzureProvider

# Custom provider with managed identity
credential = DefaultAzureCredential()
provider = AzureProvider(
    azure_endpoint=config.azure_endpoint,
    azure_ad_token_provider=credential.get_token,
    api_version=config.azure_api_version,
)
```

---

### Verification Plan for Phase 4.5

#### Automated Tests

| Test File                                   | Description                                      |
| ------------------------------------------- | ------------------------------------------------ |
| `tests/agentic/test_providers_factory.py`   | Test provider factory with all provider types    |
| `tests/agentic/test_litellm_provider.py`    | Test LiteLLM provider configuration and usage    |
| `tests/agentic/test_azure_provider.py`      | Test Azure provider configuration and auth       |
| `tests/agentic/test_provider_validation.py` | Test configuration validation and error handling |

#### Manual Verification

1. **LiteLLM Proxy**: Start LiteLLM proxy, configure llmaven, run
   `llmaven agentic chat` and verify responses
2. **Azure AI Foundry**: Configure Azure credentials, run search and chat
   commands
3. **Provider Switching**: Test switching between providers via CLI options
4. **Error Handling**: Verify clear error messages for missing configuration

---

### Updated Package Structure

```
agentic/
├── __init__.py
├── settings.py
├── exceptions.py
├── providers/              # NEW
│   ├── __init__.py
│   └── factory.py
├── vector_store/
│   ├── __init__.py
│   └── qdrant_manager.py
├── ingestion/
│   ├── __init__.py
│   └── pipeline.py
├── search/
│   ├── __init__.py
│   └── hybrid_searcher.py
└── agent/
    ├── __init__.py
    ├── rag_agent.py
    └── models.py
```

---

## API Integration Strategy

### Coexistence with Existing Endpoints

**Current Endpoints**:

- `POST /v1/retrieve` - Uses legacy `Retriever` class
- `POST /v1/generate` - Uses `LanguageModel` class

**Recommended Approach**: Add new endpoints alongside existing ones during
transition period.

#### [NEW] `src/llmaven/v1/endpoints/agentic_retrieve.py`

Create new endpoint for agentic retrieval:

- `POST /v1/agentic/retrieve` - Uses `HybridSearcher`
- Request schema similar to existing `/v1/retrieve` but with agentic-specific
  options
- Response includes `SearchResult` objects with scores

#### [NEW] `src/llmaven/v1/endpoints/agentic_chat.py`

Create new endpoint for agentic chat:

- `POST /v1/agentic/chat` - Uses `RAGAgent`
- Request:
  `{"query": str, "collection": str | None, "conversation_id": str | None}`
- Response: `RAGResponse` with structured citations

**Future Migration Path**:

- Phase 5+: Gradually migrate existing endpoints to use agentic system
- Add deprecation warnings to legacy endpoints
- Provide migration guide for API consumers

---

## Error Handling & Exception Hierarchy

### Custom Exceptions

Create `src/llmaven/agentic/exceptions.py`:

```python
class AgenticRAGError(Exception):
    """Base exception for agentic RAG errors."""
    pass

class IngestionError(AgenticRAGError):
    """Errors during document ingestion."""
    pass

class QdrantConnectionError(AgenticRAGError):
    """Qdrant connection or communication errors."""
    pass

class CollectionNotFoundError(AgenticRAGError):
    """Collection does not exist."""
    pass

class EmbeddingError(AgenticRAGError):
    """Errors during embedding generation."""
    pass

class SearchError(AgenticRAGError):
    """Errors during search operations."""
    pass
```

**Error Handling Patterns**:

- Use specific exceptions in services
- Convert to `HTTPException` in API endpoints
- Log errors with context (collection name, query, etc.)
- Provide user-friendly error messages

---

## Verification Plan

### Automated Tests

| Test File                               | Description                                                                |
| --------------------------------------- | -------------------------------------------------------------------------- |
| `tests/agentic/test_settings.py`        | Verify `Settings` loads from env and defaults.                             |
| `tests/agentic/test_ingestion.py`       | Test `IngestionPipeline` chunking and embedding logic (mocked embeddings). |
| `tests/agentic/test_qdrant_manager.py`  | Test `QdrantManager` collection creation/upsert (mocked client).           |
| `tests/agentic/test_hybrid_searcher.py` | Test `HybridSearcher` prefetch/rerank logic (mocked Qdrant).               |
| `tests/agentic/test_rag_agent.py`       | Test `RAGAgent` tool calling and structured output.                        |
| `tests/agentic/test_cli.py`             | Test CLI commands (ingest, search, chat).                                  |
| `tests/agentic/test_api_endpoints.py`   | Test new API endpoints (`/v1/agentic/retrieve`, `/v1/agentic/chat`).       |
| `tests/agentic/test_integration.py`     | Integration tests comparing agentic vs legacy retrieval.                   |

### Manual Verification

1. **Infrastructure**: Start Qdrant Docker
   (`docker run -p 6333:6333 qdrant/qdrant`).
2. **Ingestion**: Run `llmaven agentic ingest ./docs` on sample docs. Verify in
   Qdrant UI:
   - Collection `agentic-rag` exists.
   - Points have `dense`, `sparse`, `colbert` named vectors.
   - Payloads contain `text`, `file_path`, `heading_hierarchy`.
3. **Search**: Run `llmaven agentic search "explain the architecture"`. Manually
   inspect:
   - Results are relevant.
   - Keyword-heavy vs semantic-heavy queries return appropriate results.
   - Reranking improves result quality.
4. **Chat**: Run `llmaven agentic chat`. Verify:
   - Agent responds with `RAGResponse` structure.
   - Citations include correct `source_file` and `quote`.
5. **API Endpoints**: Test new endpoints via FastAPI docs (`/docs`):
   - `POST /v1/agentic/retrieve` returns `SearchResult` objects
   - `POST /v1/agentic/chat` returns `RAGResponse` with citations

---

## Documentation Requirements

### Required Updates

1. **`AGENTS.md`**: Add new section "Agentic RAG System" covering:
   - Architecture overview
   - Usage examples
   - Configuration options
   - Migration from legacy system

2. **`README.md`**: Update with:
   - New CLI commands (`llmaven agentic ingest/search/chat`)
   - New API endpoints
   - Quick start guide for agentic RAG

3. **API Documentation**: Auto-generated via FastAPI `/docs`, but ensure:
   - Request/response schemas are well-documented
   - Examples provided for each endpoint

4. **Migration Guide**: Create `MIGRATION_GUIDE.md` covering:
   - How to transition from legacy `Retriever` to `HybridSearcher`
   - Converting existing Qdrant collections to Named Vectors format
   - Updating API consumers to use new endpoints

---

## Implementation Checklist

### Phase 1: Project Scaffolding & Configuration

- [x] Verify all new dependencies support Python 3.12
- [x] Test Qdrant Named Vectors with current client version (1.11.2)
- [x] Add dependencies to `pyproject.toml` with proper version constraints
- [x] Create `agentic/` package structure with `__init__.py` files
- [x] Implement `AgenticConfig` following existing `config.py` pattern
- [x] Add environment variable support with `AGENTIC_` prefix
- [x] Create exception hierarchy in `agentic/exceptions.py`

### Phase 2: Qdrant Client & Ingestion Pipeline

- [x] Verify ColBERT `MaxSim` configuration with Qdrant 1.11.2
- [x] Implement `QdrantManager` with Named Vectors support
- [x] Add collection validation and conflict prevention
- [x] Implement `IngestionPipeline` with batch processing
- [x] Add progress indicators using `rich`
- [x] Implement error recovery and fallback parsing
- [x] Add content hashing for duplicate detection

### Phase 3: Search Implementation

- [x] Implement `HybridSearcher` with prefetch logic
- [x] Document and implement prefetch combination strategy
- [x] Add optional ColBERT reranking
- [x] Create `SearchResult` model with score metadata
- [x] Add configurable `top-k` parameters

### Phase 4: Basic Agent & CLI Integration

- [x] Decide on LLM provider integration strategy (OpenAI/Ollama vs HuggingFace)
- [x] Implement `RAGAgent` with `pydantic-ai` or adapter
- [x] Create `RAGResponse` and `Citation` models
- [x] Add CLI commands following existing Typer pattern
- [x] Create new API endpoints (`/v1/agentic/retrieve`, `/v1/agentic/chat`)
- [x] Add comprehensive test suite (test_rag_agent.py, test_cli.py,
      test_api_endpoints.py)
- [x] Update documentation (AGENTS.md, README.md)

### Phase 4.5: OpenAI-Compatible Model Support (LiteLLM & Azure AI Foundry)

- [x] Add LiteLLM provider support with proxy server configuration
- [x] Add Azure AI Foundry provider support with Azure authentication
- [x] Update `AgenticConfig` with new provider options and environment variables
- [x] Create provider factory for dynamic provider selection
- [x] Add configuration validation for provider-specific requirements
- [x] Update CLI commands with new provider options
- [x] Add tests for LiteLLM and Azure providers
- [x] Update documentation with provider configuration examples

---

## Summary of Plan Updates

This implementation plan has been updated based on comprehensive codebase
evaluation. Key improvements include:

### ✅ **Compatibility & Integration**

- Added Python 3.12 compatibility verification requirements
- Clarified Qdrant client version compatibility (1.11.2 supports Named Vectors)
- Defined API integration strategy (coexistence with legacy endpoints)
- Specified LLM provider integration options (OpenAI/Ollama vs HuggingFace)
- **Phase 4.5**: Added OpenAI-compatible model support for LiteLLM and Azure AI
  Foundry

### ✅ **Code Quality & Patterns**

- Updated settings to follow existing `config.py` pattern with
  `pydantic-settings`
- Added proper exception hierarchy for error handling
- Specified CLI command structure following existing Typer patterns
- Added collection naming conflict prevention

### ✅ **Technical Corrections**

- Updated dense model default to `all-MiniLM-L12-v2` (384-dim verified)
- Added prefetch combination strategy documentation
- Clarified ColBERT `MaxSim` configuration requirements
- Added configurable parameters (`prefetch_top_k`, `final_top_k`,
  `enable_rerank`)

### ✅ **Enhanced Features**

- Added batch processing for large document sets
- Implemented progress indicators using `rich`
- Added error recovery and fallback parsing
- Included content hashing for duplicate detection

### ✅ **Testing & Documentation**

- Expanded test coverage (integration tests, API endpoint tests)
- Added documentation requirements (AGENTS.md, README.md, Migration Guide)
- Included manual verification steps for all phases

### ✅ **Production Readiness**

- Added error handling patterns and exception hierarchy
- Specified retry logic for Qdrant operations
- Included validation and safety checks (collection overwrite prevention)
- Added comprehensive implementation checklist

This updated plan ensures seamless integration with the existing `llmaven`
codebase while maintaining code quality standards and production readiness.
