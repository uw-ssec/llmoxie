# AGENTS.md - LLMaven AI Assistant Guide

> Essential context for AI coding assistants. See `agent_docs/` for detailed
> guides.

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

| Path                          | Purpose                  | Notes                             |
| ----------------------------- | ------------------------ | --------------------------------- |
| `src/llmaven/`                | Main installable package | Core development                  |
| `src/llmaven/v1/`             | REST API v1 endpoints    | Route handlers                    |
| `src/llmaven/core/`           | ML/AI components         | Embeddings, retrieval, generation |
| `src/llmaven/services/`       | Business logic           | Service orchestration             |
| `src/llmaven/schemas/`        | Pydantic models          | API contracts                     |
| `src/llmaven/frontend/`       | Streamlit UI             | User interface                    |
| `src/llmaven/agentic/`        | Agentic RAG system       | Ingestion, agents, vector store   |
| `src/llmaven/infrastructure/` | Pulumi resources         | Azure deployment                  |
| `archive/`                    | Archived code            | **DO NOT MODIFY**                 |
| `tests/`                      | Test suite               | pytest                            |

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

| Category        | Technology              | Purpose                                    |
| --------------- | ----------------------- | ------------------------------------------ |
| API             | FastAPI                 | REST endpoints                             |
| UI              | Streamlit               | Interactive frontend                       |
| Vector DB       | Qdrant                  | Semantic search                            |
| LLM             | LangChain + HuggingFace | RAG orchestration                          |
| Agentic RAG     | pydantic-ai + fastembed | Hybrid search with multi-vector embeddings |
| Infra           | Pulumi                  | Azure deployment                           |
| Package Manager | Pixi                    | Dependencies                               |

---

## Documentation Index

Before starting work, review relevant docs in `agent_docs/`:

| Document                                                | When to Read                     |
| ------------------------------------------------------- | -------------------------------- |
| [`adding_endpoints.md`](agent_docs/adding_endpoints.md) | Adding new API endpoints         |
| [`code_conventions.md`](agent_docs/code_conventions.md) | Naming patterns, style questions |
| [`commit_messages.md`](agent_docs/commit_messages.md)   | Writing commit messages          |
| [`infrastructure.md`](agent_docs/infrastructure.md)     | Pulumi/Azure deployment          |
| [`troubleshooting.md`](agent_docs/troubleshooting.md)   | Debugging common issues          |

---

## Critical Reminders

- **Never modify `archive/`** — Contains legacy code for reference only
- **Run `pre-commit run --all-files`** before committing
- **Configuration file `llmaven-config.yaml`** is gitignored (contains secrets)

---

## Agentic RAG System

The Agentic RAG system is a next-generation retrieval and question-answering
system that combines hybrid search (Dense + Sparse + ColBERT) with intelligent
agent-based answer generation. It provides superior retrieval accuracy compared
to the legacy single-vector search system.

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

The agentic RAG system coexists with the legacy `core/retriever/` and
`core/embeddings/` modules. During the transition period:

1. **Legacy endpoints remain functional**: `/v1/retrieve` and `/v1/generate`
   continue to work
2. **New endpoints available**: `/v1/agentic/retrieve` and `/v1/agentic/chat`
   provide enhanced capabilities
3. **Separate collections**: Agentic system uses its own Qdrant collections
   (default: `agentic-rag`)
4. **No breaking changes**: Existing code continues to work unchanged

**Key Differences:**

| Feature             | Legacy System         | Agentic System                          |
| ------------------- | --------------------- | --------------------------------------- |
| Embeddings          | Single dense vector   | Multi-vector (Dense + Sparse + ColBERT) |
| Search              | Single method         | Hybrid (Prefetch + Rerank)              |
| Document Processing | Basic text extraction | `docling` with structure preservation   |
| Answer Generation   | Simple prompt         | Agent-based with citations              |
| Vector Store        | Standard Qdrant       | Named Vectors support                   |

**Migration Path:**

1. Start using agentic CLI commands for new document collections
2. Test agentic endpoints alongside legacy endpoints
3. Gradually migrate API consumers to new endpoints
4. Legacy modules will be deprecated in Phase 5+ with migration utilities

---

## Recovering Lost Pulumi State

If the Pulumi state file is empty (e.g. after a failed deploy created a fresh
stack, or the blob was accidentally reset), all resources will show as `+create`
in the preview even though they exist in Azure. Fix this by importing each
resource before deploying.

### Symptoms

- `llmaven infra deploy --preview` shows 30+ resources to create
- The state blob exists at `.pulumi/stacks/llmaven/<stack-name>.json` but has 0
  resources
- Azure portal shows all resources already exist

### Verify the state is empty

```bash
az storage blob download \
  --account-name <pulumi_state_store> \
  --container-name pulumi-state \
  --name ".pulumi/stacks/llmaven/<stack-name>.json" \
  --file /tmp/state.json
python3 -c "import json; s=json.load(open('/tmp/state.json')); print(len(s['checkpoint']['latest']['resources']), 'resources')"
```

### Import resources

Set these env vars before every `pulumi import` call:

```bash
export PULUMI_BACKEND_URL="azblob://pulumi-state?storage_account=<pulumi_state_store>"
export AZURE_STORAGE_ACCOUNT="<pulumi_state_store>"
export AZURE_STORAGE_KEY=$(az storage account keys list \
  --resource-group <resource_group> \
  --account-name <pulumi_state_store> \
  --query "[0].value" -o tsv)
export PULUMI_CONFIG_PASSPHRASE=""
```

Then import each resource using its Pulumi logical name (from the code) and
Azure resource ID:

```bash
pixi run -e llmaven pulumi import <pulumi-type> <logical-name> <azure-resource-id> \
  --stack <stack-name> --yes
```

### Resource map for this deployment

Stack name: `{project.name}-{project.environment}` (e.g. `llmaven-iss-prod`)

| Pulumi type                                         | Logical name                             | Azure resource                                 |
| --------------------------------------------------- | ---------------------------------------- | ---------------------------------------------- |
| `azure-native:network:VirtualNetwork`               | `vnet`                                   | `vnet-{stack}`                                 |
| `azure-native:network:Subnet`                       | `container-apps-subnet`                  | `.../subnets/container-apps-subnet`            |
| `azure-native:network:Subnet`                       | `postgres-subnet`                        | `.../subnets/postgres-subnet`                  |
| `azure-native:privatedns:PrivateZone`               | `postgres-private-dns-zone-{env}`        | `{server}.private.postgres.database.azure.com` |
| `azure-native:privatedns:VirtualNetworkLink`        | `postgres-dns-vnet-link-{env}`           | `{server}-vnet-link`                           |
| `azure-native:keyvault:Vault`                       | `key-vault-{env}`                        | `kv-{project}-{env}-{region}`                  |
| `azure-native:storage:StorageAccount`               | `storage-account-{env}`                  | `{project}{env}...`                            |
| `azure-native:storage:BlobContainer`                | `blob-container-{name}-{env}`            | container name                                 |
| `azure-native:operationalinsights:Workspace`        | `log-analytics`                          | `log-{stack}`                                  |
| `azure-native:managedidentity:UserAssignedIdentity` | `managed-identity-{stack}-apps-identity` | `{stack}-apps-identity`                        |
| `azure-native:dbforpostgresql:Server`               | `postgres-server-{env}`                  | `{project}-postgres-{env}`                     |
| `azure-native:dbforpostgresql:Database`             | `postgres-db-{db}-{env}`                 | database name                                  |
| `azure-native:keyvault:Secret`                      | `kv-secret-{name}-{env}`                 | secret name in vault                           |
| `azure-native:app:ManagedEnvironment`               | `container-apps-env-{env}`               | `{project}-containerenv-{env}`                 |
| `azure-native:app:ContainerApp`                     | `container-app-{app}-{env}`              | `{app}-{env}`                                  |
| `azure-native:app:Job`                              | `backup-job-{env}`                       | `{project}-backup-{env}`                       |

### Known ignore_changes requirements

Some resources have properties that Azure populates automatically and that
Pulumi will incorrectly try to replace or update on import. These
`ignore_changes` entries are already in the code:

- **PostgreSQL Server** (`database.py`): `administratorLoginPassword`,
  `authConfig`, `availabilityZone`, `dataEncryption`, `highAvailability`,
  `maintenanceWindow`, `network`, `replica`, `replicationRole`, `storage`
- **ManagedEnvironment** (`container_apps.py`): `appLogsConfiguration`,
  `vnetConfiguration`, `zoneRedundant`, `workloadProfiles`,
  `infrastructureResourceGroup`, `peerAuthentication`, `availabilityZones`,
  `peerTrafficConfiguration`, `publicNetworkAccess`
- **Backup Job** (`container_apps.py`): `configuration`, `identity`, `template`,
  `workloadProfileName`

### Post-import: password sync

After a fresh deploy following state recovery, Pulumi generates a **new** admin
password and stores it in Key Vault, but the existing PostgreSQL server still
has the old password. Sync them:

```bash
NEW_PASS=$(az keyvault secret show \
  --vault-name <key-vault-name> \
  --name postgresql-admin-password \
  --query "value" -o tsv)
az postgres flexible-server update \
  --name <server-name> \
  --resource-group <resource-group> \
  --admin-password "$NEW_PASS"
```

---

**Last Updated**: 2026-05-30 | **Maintained By**: LLMaven Development Team (UW
SSEC)
