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

| Service | URL |
|---------|-----|
| LiteLLM | http://localhost:4000 |
| MLflow | http://localhost:8080 |
| MinIO Console | http://localhost:9001 |
| Qdrant Dashboard | http://localhost:6333/dashboard |

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
