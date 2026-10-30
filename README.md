# LLMaven

[![ssec](https://img.shields.io/badge/SSEC-Project-purple?logo=data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAA0AAAAOCAQAAABedl5ZAAAACXBIWXMAAAHKAAABygHMtnUxAAAAGXRFWHRTb2Z0d2FyZQB3d3cuaW5rc2NhcGUub3Jnm+48GgAAAMNJREFUGBltwcEqwwEcAOAfc1F2sNsOTqSlNUopSv5jW1YzHHYY/6YtLa1Jy4mbl3Bz8QIeyKM4fMaUxr4vZnEpjWnmLMSYCysxTcddhF25+EvJia5hhCudULAePyRalvUteXIfBgYxJufRuaKuprKsbDjVUrUj40FNQ11PTzEmrCmrevPhRcVQai8m1PRVvOPZgX2JttWYsGhD3atbHWcyUqX4oqDtJkJiJHUYv+R1JbaNHJmP/+Q1HLu2GbNoSm3Ft0+Y1YMdPSTSwQAAAABJRU5ErkJggg==&style=plastic)](https://escience.washington.edu/software-engineering/ssec/)
[![BSD License](https://badgen.net/badge/license/BSD-3-Clause/blue)](LICENSE)
[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/uw-ssec/llmaven/main.svg)](https://results.pre-commit.ci/latest/github/uw-ssec/llmaven/main)
[![CI](https://github.com/uw-ssec/llmaven/actions/workflows/ci.yml/badge.svg)](https://github.com/uw-ssec/llmaven/actions/workflows/ci.yml)

An open-source AI control plane developed under NSF NAIRR award
[#240292](https://nairrpilot.org/projects/awarded?_requestNumber=NAIRR240292) by
[UW SSEC](https://escience.washington.edu/software-engineering/ssec/) under
Schmidt Sciences
[Virtual Institutes for Scientific Software](https://www.schmidtsciences.org/viss/)
program.

LLMaven provides open, transparent, and useful AI-based software for scientific
discovery by providing AI infrastructure that can be installed on cloud and HPC
systems to access large language models, observability features, and an
[agentic framework](https://github.com/uw-ssec/rse-plugins) for AI assisted
coding for Research Software Engineering.

## Overview

LLMaven leverages CLI and Pulumi-based Infrastructure as Code configurations
into a single workflow. A local stack utilizing docker mirrors the cloud
architecture: the same databases, object storage, AI gateway, and experiment
tracking services run locally. AI harness that defines coding subagents and
skills are developed, now, as Claude Code RSE-Plugins on top of this
infrastructure.

Key Components

The architecture has three layers:

Layer 1 — Inference Engine: The inference engine is provided by each cloud
provider or HPC. Azure via Microsoft Foundry Models, AWS via Amazon Bedrock, and
GCP via Vertex AI. For local inference in HPC GPU nodes, users can utilize vLLM.
This is the compute layer.

Layer 2 — API Gateway (LiteLLM + MLFlow): A lightweight proxy that provides
unified access to the various models from the inference engine. It provides a
single OpenAI-compatible endpoint for all researchers, handling authentication,
rate limiting (RPM/TPM), per-user and per-team budgets, spend tracking, PII
masking via Microsoft Presidio, and request logging to PostgreSQL as well as
MLFlow. The MLFlow application allows for evaluations of AI Agents and
observability. This is the main control plane layer that llmaven provides.

Layer 3 — [RSE-Plugins](https://github.com/uw-ssec/rse-plugins): Claude Code
plugins for domain-specific research workflows. This is the application
augmentation layer that emphasizes best research software engineering practices
including reproducibility, testing rigor, and adherence to Scientific Python
ecosystem conventions. RSE-Plugins provides specialized AI agents and reusable
knowledge modules organized in a Plugin → Agent → Skill hierarchy — covering
scientific Python development (packaging, pytest, pixi environments), scientific
domain application (astronomy, climate science, Earth science), structured AI
research workflows (/research, /plan, /implement, /validate), project management
and onboarding, and HoloViz visualization. Together these give Claude Code the
context needed to guide complex feature development through documented
decision-making phases while following community best practices.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 3 — RSE-Plugins (Application)                            │
│  Claude Code agents & skills for research workflows             │
│  /research → /plan → /implement → /validate                    │
├─────────────────────────────────────────────────────────────────┤
│  Layer 2 — API Gateway (Control Plane)                          │
│  LiteLLM (unified endpoint, auth, budgets, spend tracking)     │
│  MLflow (experiment tracking, agent evaluation, observability) │
│  PostgreSQL (request logs, metadata) · Blob (artifacts)        │
├─────────────────────────────────────────────────────────────────┤
│  Layer 1 — Inference Engine (Compute)                           │
│  Azure Foundry Models · AWS Bedrock · GCP Vertex AI · vLLM    │
└─────────────────────────────────────────────────────────────────┘

         CLI (Typer)                    Docker Compose
    llmaven infra [init|               (local dev stack)
     validate|deploy]        mirrors
                            ←──────→   PostgreSQL:5432
    deployment/                        MLflow:8080
    infrastructure/                    LiteLLM:4000
      (Pulumi → Azure)                Azurite:10000
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

### Upgrading from a RAG-era checkout

The agentic RAG system now lives in
[uw-ssec/llmoxie-rag](https://github.com/uw-ssec/llmoxie-rag):
`llmaven agentic ...` is now `llmoxie-rag ...` there. Run this once to clear an
old `llmaven_qdrant` container:

```bash
pixi run -e llmaven docker-compose -f docker/docker-compose.yml down --remove-orphans
```

### Upgrading from a MinIO-era checkout

The local stack no longer runs MinIO. New MLflow artifacts go to the `mlflow`
container in Azurite, which keeps its data in the `llmaven_azurite_data` volume.
No volumes are deleted, so your old MinIO data stays on disk.

Your existing `docker/.env` still points MLflow at `s3://mlflow/`, and
`pixi run -e llmaven up` does not rebuild images. Until you update both, even
new experiments get an `s3://` location that MLflow can no longer write to.
Follow the ordered steps in
[docker/README.md](docker/README.md#upgrading-from-minio): update `.env`,
rebuild MLflow, create a new experiment and point LiteLLM at it. Experiments
created before the switch, including `Default`, keep their old `s3://` location.

## Docker Services

The local stack runs 4 services on a shared bridge network (`llmaven-network`):

| Service        | Image            | Port(s) | Role                                           |
| -------------- | ---------------- | ------- | ---------------------------------------------- |
| **PostgreSQL** | postgres:16      | 5432    | Relational store (3 databases)                 |
| **MLflow**     | Custom (v3.6.0)  | 8080    | Experiment tracking & model registry           |
| **Azurite**    | Azurite (MCR)    | 10000   | Blob storage emulator (MLflow artifacts, logs) |
| **LiteLLM**    | Custom (v1.79.1) | 4000    | Unified AI gateway proxy                       |

**Startup order:** PostgreSQL and Azurite start in parallel. MLflow waits for
both, then creates its `mlflow` blob container if it is missing. LiteLLM waits
for PostgreSQL, MLflow, and Azurite.

**Service UIs:**

| Service | URL                     |
| ------- | ----------------------- |
| LiteLLM | <http://localhost:4000> |
| MLflow  | <http://localhost:8080> |

## CLI Reference

LLMaven provides a CLI built with Typer:

```bash
llmaven version                           # Show version

# Infrastructure commands
llmaven infra init --environment dev      # Generate llmaven-config.yaml
llmaven infra validate --config llmaven-config.yaml  # Validate config + cost estimate
llmaven infra deploy --preview            # Dry run (may still create the resource group and state storage)
llmaven infra deploy --yes                # Deploy to Azure
llmaven infra status                      # View deployment status
llmaven infra extract --from 2026-01-01 --to 2026-01-31  # Logs/traces to a JSONL zip
llmaven infra destroy --yes               # Tear down resources

# Backup storage commands
llmaven backup-infra deploy --yes         # Deploy the backup storage infrastructure
llmaven backup-infra output --name <key>  # Print a backup stack output value
```

## Azure Infrastructure Deployment

The local Docker services map directly to Azure managed equivalents, deployed
via Pulumi Automation API:

| Local Service           | Azure Equivalent                              |
| ----------------------- | --------------------------------------------- |
| PostgreSQL (db:5432)    | Azure Database for PostgreSQL Flexible Server |
| Azurite (azurite:10000) | Azure Blob Storage (ADLS Gen2)                |
| MLflow (mlflow:8080)    | Azure Container App (MLflow)                  |
| LiteLLM (litellm:4000)  | Azure Container App (LiteLLM)                 |

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
   llmaven infra deploy --preview   # Dry run (may create the resource group and state storage)
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

- [University of Washington Scientific Software Engineering Center (SSEC)](https://escience.washington.edu/software-engineering/ssec/)
- [NSF National Artificial Intelligence Research Resource (NAIRR)](https://nairrpilot.org/)
  — Award
  [#240292](https://nairrpilot.org/projects/awarded?_requestNumber=NAIRR240292)
- [Schmidt Sciences Virtual Institutes for Scientific Software (VISS)](https://www.schmidtsciences.org/viss/)

## Additional Resources

- [RSE-Plugins](https://github.com/uw-ssec/rse-plugins) - Claude Code plugins
  for research software engineering workflows
- [AGENTS.md](AGENTS.md) - Technical reference for developers and AI assistants
- [GitHub Issues](https://github.com/uw-ssec/llmaven/issues)
- [SSEC Tutorials](https://github.com/uw-ssec/tutorials)
