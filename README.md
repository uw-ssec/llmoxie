# LLMaven

A platform for building and deploying AI-powered research tools. LLMaven is made
of two components: **infrastructure** (CLI, Docker services stack, and
Pulumi-based Azure deployment) and **application** (built as
[RSE-Plugins](https://github.com/uw-ssec/rse-plugins)).

## Overview

LLMaven combines a **Typer CLI**, a **Docker Compose services stack**
(PostgreSQL, MinIO, MLflow, LiteLLM, Qdrant), and **Pulumi-based Azure
deployment** into a single workflow. The local stack mirrors the cloud
architecture: the same databases, object storage, AI gateway, and experiment
tracking services run locally via Docker and deploy to Azure as managed
resources. Application logic is developed as RSE-Plugins on top of this
infrastructure. Dependency management is handled by [pixi](https://pixi.sh)
with multi-environment support.

## Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                         CLI (Typer)                            │
│   llmaven version | infra [init|validate|deploy] | agentic    │
└────────┬──────────────────────────────────────────┬────────────┘
         │                                          │
         ▼                                          ▼
┌──────────────────────┐               ┌──────────────────────┐
│  Infrastructure      │               │  Docker Compose      │
│  (Pulumi → Azure)    │               │  Stack (local dev)   │
│                      │               │                      │
│  deployment/         │               │  Qdrant:6333         │
│    init.py           │  mirrors      │  PostgreSQL:5432     │
│    validate.py       │ ←──────────→  │  MinIO:9000/9001     │
│    deploy.py         │               │  MLflow:8080         │
│                      │               │  LiteLLM:4000        │
│  infrastructure/     │               │                      │
│    main.py (Pulumi)  │               │  (llmaven-network)   │
│    config/           │               │                      │
│    resources/        │               └──────────────────────┘
│    utils/            │
└──────────────────────┘
```

## Quick Start

### Prerequisites

- [Pixi](https://pixi.sh) package manager
- Docker and Docker Compose
- Azure CLI (for infrastructure deployment)

### Installation

```bash
git clone https://github.com/uw-ssec/llmaven.git
cd llmaven
pixi install
```

### Start Local Services

The Docker Compose stack provides a full local development environment:

```bash
# Copy and configure environment variables
cp docker/.env.example docker/.env
# Edit docker/.env with your API keys

# Start all services
pixi run -e llmaven up

# Check service status
pixi run -e llmaven status

# View logs
pixi run -e llmaven logs

# Stop services
pixi run -e llmaven down
```

## Docker Services

The local stack runs 6 services on a shared bridge network (`llmaven-network`):

| Service | Image | Port(s) | Role |
|---------|-------|---------|------|
| **Qdrant** | qdrant/qdrant:latest | 6333 | Vector DB for semantic search |
| **PostgreSQL** | postgres:16 | 5432 | Relational store (3 databases) |
| **MinIO** | minio/minio:latest | 9000, 9001 | S3-compatible object storage |
| **MLflow** | Custom (v3.6.0) | 8080 | Experiment tracking & model registry |
| **LiteLLM** | Custom (v1.79.1) | 4000 | Unified AI gateway proxy |
| **CreateBuckets** | quay.io/minio/mc | -- | Init container (creates S3 buckets) |

**Startup order:** PostgreSQL, MinIO, Qdrant start in parallel. CreateBuckets waits for MinIO. MLflow waits for PostgreSQL, MinIO, and CreateBuckets. LiteLLM waits for PostgreSQL and MLflow.

**Service UIs:**

<<<<<<< Updated upstream
```bash
# Start interactive RAG chat
llmaven agentic chat

# Use custom collection or LLM provider
llmaven agentic chat --collection my-docs --provider ollama --model llama2
```

#### Configuration

Set environment variables with `AGENTIC_` prefix:

```bash
# Qdrant configuration
export AGENTIC_QDRANT_URL=http://localhost:6333
export AGENTIC_COLLECTION_NAME=agentic-rag

# LLM configuration
export AGENTIC_LLM_PROVIDER=openai
export AGENTIC_LLM_MODEL=gpt-4o-mini

# Search configuration
export AGENTIC_ENABLE_RERANK=true
export AGENTIC_PREFETCH_TOP_K=20
export AGENTIC_FINAL_TOP_K=5
```

See [AGENTS.md](AGENTS.md) for complete configuration options and architecture
details.

### Option 2: Local Development (API and UI)

The primary way to use LLMaven is through its FastAPI backend and Streamlit
frontend.

#### 1. Start the API Server

```bash
# Using the pixi environment (recommended)
pixi shell -e llmaven

# Start in development mode with auto-reload
llmaven server serve --env development --reload

# Or start in production mode with multiple workers
llmaven server serve --env production --workers 4
```

The API will be available at:

- API: http://localhost:8000
- API Documentation: http://localhost:8000/docs
- Alternative Docs: http://localhost:8000/redoc

#### 2. Start the Streamlit UI

In a separate terminal:

```bash
# Using the pixi environment (recommended)
pixi shell -e llmaven

# Launch the UI
llmaven server ui

# Or customize host and port
llmaven server ui --host 0.0.0.0 --port 8080 --no-browser
```

The UI will open automatically in your browser at http://localhost:8501

#### 3. Using the UI

1. **Upload Documents**: Use the file uploader to add PDF documents
2. **Ask Questions**: Type your question in the chat input
3. **View Results**: See retrieved document chunks and AI-generated answers
4. **Chat History**: All interactions are stored in the session

### Option 2: Azure Infrastructure Deployment

LLMaven provides a comprehensive infrastructure deployment system for production
workloads.

#### 1. Initialize Configuration

```bash
# Enter the llmaven environment
pixi shell -e llmaven

# Initialize deployment configuration
llmaven infra init --environment dev

# This creates llmaven-config.yaml with sensible defaults
```

#### 2. Configure Infrastructure

Edit the generated `llmaven-config.yaml` file:

```yaml
project:
  name: llmaven
  environment: dev
  location: eastus

azure:
  subscription_id: "your-subscription-id"
  # tenant_id is auto-detected

database:
  admin_login: llmaven_admin
  sku_name: "B_Standard_B1ms"
  databases: [llmaven, mlflow_db, litellm_db]

mlflow:
  enabled: true
  image: "ghcr.io/mlflow/mlflow:latest"

litellm:
  enabled: true
  image: "ghcr.io/berriai/litellm:latest"
```

#### 3. Set Secrets

Secrets are provided via environment variables:

```bash
# Generate a secure master key
export LLMAVEN_SECRETS_LITELLM_MASTER_KEY="$(openssl rand -base64 32)"

# Add your API keys
export LLMAVEN_SECRETS_AZURE_OPENAI_API_KEY="your-azure-openai-key"
export LLMAVEN_SECRETS_ANTHROPIC_API_KEY="your-anthropic-key"

# Or create a .env file
cat > .env.secrets <<EOF
LLMAVEN_SECRETS_LITELLM_MASTER_KEY=your-master-key
LLMAVEN_SECRETS_AZURE_OPENAI_API_KEY=your-azure-openai-key
LLMAVEN_SECRETS_ANTHROPIC_API_KEY=your-anthropic-key
EOF
```

#### 4. Validate Configuration

```bash
# Validate with strict mode (recommended for production)
llmaven infra validate --config llmaven-config.yaml --strict

# Or validate with secrets from .env file
llmaven infra validate --env-file .env.secrets --strict
```

This validates:

- Configuration syntax and schema
- Azure subscription and permissions
- Resource quotas and limits
- Secret presence
- Cost estimation

#### 5. Deploy Infrastructure

```bash
# Preview what will be deployed
llmaven infra deploy --preview

# Deploy infrastructure
llmaven infra deploy --yes

# Or deploy with .env file
llmaven infra deploy --env-file .env.secrets --yes
```

#### 6. Check Deployment Status

```bash
# View deployment status and resource URLs
llmaven infra status

# Outputs include:
# - MLflow URL: https://llmaven-dev-mlflow.{region}.azurecontainerapps.io
# - LiteLLM URL: https://llmaven-dev-litellm.{region}.azurecontainerapps.io
# - Resource names (Key Vault, Storage Account, PostgreSQL, etc.)
```

#### 7. Destroy Infrastructure (when done)

```bash
# Destroy all resources
llmaven infra destroy --yes
```

### Deployed Azure Resources

When you deploy infrastructure, LLMaven creates:

1. **Resource Group**: Container for all resources
2. **Virtual Network**: With subnets for Container Apps and PostgreSQL
3. **Key Vault**: Centralized secret management with RBAC
4. **PostgreSQL Flexible Server**: Managed database with:
   - Databases: llmaven, mlflow_db, litellm_db
   - Auto-generated admin password stored in Key Vault
5. **Storage Account**: With ADLS Gen2 support
   - Containers: mlflow, llmaven
6. **Container Apps Environment**: For container orchestration
7. **Managed Identities**: For secure Key Vault access
8. **Container Apps** (optional):
   - **MLflow**: Experiment tracking and model registry
   - **LiteLLM**: OpenAI-compatible API gateway
9. **Log Analytics Workspace**: (optional) For monitoring

### Cost Estimation

**Development Environment** (~$20-30/month):

- PostgreSQL: B_Standard_B1ms
- Storage: Standard LRS
- Container Apps: Consumption plan

**Production Environment** (~$400-600/month):

- PostgreSQL: GP_Standard_D2s_v3
- Storage: Standard GRS
- Container Apps: Dedicated plan
- High Availability enabled

## API Endpoints

### Agentic RAG Endpoints (NEW)

**POST** `/v1/agentic/retrieve`

Hybrid search with multi-vector retrieval (Dense, Sparse, ColBERT).

```bash
curl -X POST http://localhost:8000/v1/agentic/retrieve \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is machine learning?",
    "collection": "agentic-rag",
    "top_k": 5,
    "enable_rerank": true
  }'
```

**POST** `/v1/agentic/chat`

RAG chat with structured responses and citations.

```bash
curl -X POST http://localhost:8000/v1/agentic/chat \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Explain transformers",
    "collection": "agentic-rag",
    "message_history": []
  }'
```

### Legacy Endpoints

**POST** `/v1/retrieve`

Retrieve relevant documents based on a query.

```bash
curl -X POST http://localhost:8000/v1/retrieve \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is the Rubin telescope?",
    "embedding_model": "sentence-transformers/all-MiniLM-L12-v2",
    "existing_collection": "rubin_telescope",
    "existing_qdrant_path": "data/vector_stores/rubin_qdrant"
  }'
```

**Request Schema:**

```json
{
  "documents": [],
  "query": "string",
  "existing_collection": "string",
  "existing_qdrant_path": "string",
  "embedding_model": "string"
}
```

**Response:**

```json
{
  "docs": [
    {
      "page_content": "Document text...",
      "metadata": {}
    }
  ],
  "status_code": 200
}
```

### Generation Endpoint

**POST** `/v1/generate`

Generate text based on a prompt.

```bash
curl -X POST http://localhost:8000/v1/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Based on the context: ... Answer the question: ...",
    "generation_model": "allenai/OLMo-2-1124-7B-Instruct"
  }'
```

**Request Schema:**

```json
{
  "prompt": "string",
  "generation_model": "string"
}
```

**Response:**

```json
{
  "answer": "Generated text...",
  "status_code": 200
}
```

## Configuration

### Environment Variables

Create a `.env` file in the root directory:

```bash
# API Configuration
API_TITLE="LLMaven API"
API_VERSION="0.1.0"
API_CORS_ORIGINS=["*"]

# Frontend Configuration
FRONTEND_API_BASE_URL="http://localhost:8000/v1"
FRONTEND_EMBEDDING_MODEL="sentence-transformers/all-MiniLM-L12-v2"
FRONTEND_GENERATION_MODEL="allenai/OLMo-2-1124-7B-Instruct"
FRONTEND_EXISTING_COLLECTION="rubin_telescope"
FRONTEND_EXISTING_QDRANT_PATH="data/vector_stores/rubin_qdrant"
FRONTEND_RETRIEVAL_K=2

# Model Configuration
EMBEDDING_MODEL_NAME="intfloat/multilingual-e5-large-instruct"
```

### Model Configuration

#### Embedding Models

LLMaven supports any HuggingFace sentence-transformers model:

- `sentence-transformers/all-MiniLM-L12-v2` (default, lightweight)
- `intfloat/multilingual-e5-large-instruct` (multilingual)
- `sentence-transformers/all-mpnet-base-v2` (higher quality)

#### Generation Models

Supports HuggingFace Transformers models:

- `allenai/OLMo-2-1124-7B-Instruct` (default, 7B parameters)
- Any causal LM from HuggingFace

**Quantization Options:**

- 8-bit: Good balance of quality and memory
- 4-bit: Lower memory, slightly reduced quality

Models are cached locally in `src/llmaven/models/` directory.

## Project Structure

```
llmaven/
├── src/llmaven/              # Main application package
│   ├── __init__.py
│   ├── cli.py                # Command-line interface
│   ├── config.py             # API configuration
│   ├── main.py               # FastAPI application
│   ├── core/                 # Core RAG components (legacy)
│   │   ├── embeddings/       # Embedding model wrapper
│   │   ├── generator/        # Language model wrapper
│   │   └── retriever/        # Vector retrieval logic
│   ├── agentic/              # Agentic RAG system (NEW)
│   │   ├── agent/            # RAG agent with pydantic-ai
│   │   ├── ingestion/        # Document ingestion pipeline
│   │   ├── search/           # Hybrid search implementation
│   │   ├── vector_store/     # Qdrant manager with Named Vectors
│   │   └── settings.py       # Configuration management
│   ├── frontend/             # Streamlit UI
│   │   ├── app.py            # Main UI application
│   │   └── config.py         # Frontend configuration
│   ├── schemas/              # Pydantic models
│   │   ├── retrieve.py       # Retrieval request/response
│   │   └── generate.py       # Generation request/response
│   ├── services/             # Business logic
│   │   ├── retrieval_service.py
│   │   └── generation_service.py
│   ├── v1/                   # API v1 endpoints
│   │   ├── router.py         # Main router
│   │   └── endpoints/        # Endpoint implementations
│   │       ├── retrieve.py
│   │       └── generate.py
│   ├── deployment/           # Deployment utilities
│   │   ├── init.py           # Configuration initialization
│   │   ├── validate.py       # Configuration validation
│   │   └── deploy.py         # Deployment orchestration
│   └── infrastructure/       # Infrastructure as Code
│       ├── main.py           # Pulumi program entry point
│       ├── config/           # Configuration schema and loaders
│       ├── resources/        # Azure resource modules
│       └── utils/            # Infrastructure utilities
├── archive/                  # Archived code (unused)
│   ├── proxy/                # OpenAI API proxy service (archived)
│   ├── infra/                # Infrastructure as code (archived)
│   └── legacy/               # Legacy Panel application (archived)
├── tests/                    # Test suite
│   ├── test_retriever.py
│   └── test_generator.py
├── pixi.toml                 # Pixi configuration
├── pyproject.toml            # Python package configuration
└── README.md                 # This file
```

## Development

### Running Tests

```bash
# Run all tests
pixi shell -e llmaven
pytest

# Run specific test file
pytest tests/test_retriever.py

# Run with verbose output
pytest -v

# Run with coverage
pytest --cov=llmaven
```

### Code Quality

The project uses pre-commit hooks for code quality:

```bash
# Install pre-commit hooks
pixi shell -e llmaven
pre-commit install

# Run manually
pre-commit run --all-files
```

Configured linters:

- flake8 (Python linting)
- prettier (YAML/Markdown formatting)
- codespell (spell checking)

### Development Mode

Run the API server with auto-reload for development:

```bash
llmaven server serve --env development --reload
```

Changes to Python files will automatically restart the server.
=======
| Service | URL |
|---------|-----|
| LiteLLM | http://localhost:4000 |
| MLflow | http://localhost:8080 |
| MinIO Console | http://localhost:9001 |
| Qdrant Dashboard | http://localhost:6333/dashboard |
>>>>>>> Stashed changes

## CLI Reference

LLMaven provides a CLI built with Typer. Key commands:

```bash
# Show version
llmaven version

# Infrastructure commands
llmaven infra init --environment dev      # Generate llmaven-config.yaml
llmaven infra validate --config llmaven-config.yaml  # Validate config + cost estimate
llmaven infra deploy --preview            # Dry run (no resources created)
llmaven infra deploy --yes                # Deploy to Azure
llmaven infra status                      # View deployment status
llmaven infra destroy --yes               # Tear down resources

# Agentic RAG commands
llmaven agentic ingest ./docs             # Ingest documents
llmaven agentic search "query"            # Hybrid search
llmaven agentic chat                      # Interactive RAG chat
```

## Azure Infrastructure Deployment

LLMaven deploys to Azure using Pulumi Automation API. The local Docker services
map directly to Azure equivalents:

| Local Service | Azure Equivalent |
|---|---|
| PostgreSQL (db:5432) | Azure Database for PostgreSQL Flexible Server |
| MinIO (minio:9000) | Azure Blob Storage (ADLS Gen2) |
| MLflow (mlflow:8080) | Azure Container App (MLflow) |
| LiteLLM (litellm:4000) | Azure Container App (LiteLLM) |

### Deployment Workflow

1. **Initialize** configuration:
   ```bash
   pixi shell -e llmaven
   llmaven infra init --environment dev
   ```

2. **Configure** the generated `llmaven-config.yaml`:
   ```yaml
   project:
     name: llmaven
     environment: dev
     location: westus2
   azure:
     subscription_id: "your-subscription-id"
   database:
     sku_name: Standard_B1ms
     databases: [llmaven, mlflow_db, litellm_db]
   ```

3. **Set secrets** via environment variables:
   ```bash
   export LLMAVEN_SECRETS_LITELLM_MASTER_KEY="$(openssl rand -base64 32)"
   export LLMAVEN_SECRETS_AZURE_OPENAI_API_KEY="your-key"
   ```

4. **Validate** configuration (runs 6 checks: syntax, security, Azure prereqs,
   secrets, cost estimate, production readiness):
   ```bash
   llmaven infra validate --strict
   ```

5. **Deploy** (or preview first):
   ```bash
   llmaven infra deploy --preview   # Dry run
   llmaven infra deploy --yes       # Actual deployment
   ```

### Azure Resources Created

```
Resource Group
├── Virtual Network
│   ├── Container Apps Subnet
│   └── PostgreSQL Subnet
├── Key Vault (secrets + auto-generated credentials)
├── PostgreSQL Flexible Server (llmaven, mlflow_db, litellm_db)
├── Storage Account (ADLS Gen2: mlflow, llmaven containers)
├── Log Analytics Workspace
└── Container Apps Environment
    ├── MLflow Container App (managed identity → Key Vault)
    └── LiteLLM Container App (managed identity → Key Vault)
```

### Cost Estimates

| Environment | Estimate | DB SKU |
|---|---|---|
| Dev | ~$50-100/mo | B_Standard_B1ms |
| Staging | ~$200-400/mo | GP_Standard_D2s_v3 |
| Production | ~$400-800/mo | GP_Standard_D4s_v3 + HA |

## Development

```bash
# Run tests
pixi shell -e llmaven
pytest

# Run pre-commit hooks
pre-commit run --all-files

# Docker lifecycle
pixi run -e llmaven up        # Start services
pixi run -e llmaven down      # Stop services
pixi run -e llmaven clean     # Stop + delete all data volumes
```

## Contributing

Contributions are welcome! Please fork the repository, create a feature branch,
and submit a pull request.

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for community guidelines.

## License

BSD License - see [LICENSE](LICENSE) for details.

## Acknowledgments

University of Washington Scientific Software Engineering Center (SSEC)

## Additional Resources

- [AGENTS.md](AGENTS.md) - Technical reference for developers and AI assistants
- [GitHub Issues](https://github.com/uw-ssec/llmaven/issues)
- [SSEC Tutorials](https://github.com/uw-ssec/tutorials)
