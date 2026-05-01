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
│  PostgreSQL (request logs, metadata) · MinIO (artifacts)       │
├─────────────────────────────────────────────────────────────────┤
│  Layer 1 — Inference Engine (Compute)                           │
│  Azure Foundry Models · AWS Bedrock · GCP Vertex AI · vLLM    │
└─────────────────────────────────────────────────────────────────┘

         CLI (Typer)                    Docker Compose
    llmaven infra [init|               (local dev stack)
     validate|deploy]        mirrors
                            ←──────→   PostgreSQL:5432
    deployment/                        MinIO:9000/9001
    infrastructure/                    MLflow:8080
      (Pulumi → Azure)                LiteLLM:4000
                                       Qdrant:6333
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

| Service           | Image                | Port(s)    | Role                                 |
| ----------------- | -------------------- | ---------- | ------------------------------------ |
| **Qdrant**        | qdrant/qdrant:latest | 6333       | Vector DB for semantic search        |
| **PostgreSQL**    | postgres:16          | 5432       | Relational store (3 databases)       |
| **MinIO**         | minio/minio:latest   | 9000, 9001 | S3-compatible object storage         |
| **MLflow**        | Custom (v3.6.0)      | 8080       | Experiment tracking & model registry |
| **LiteLLM**       | Custom (v1.79.1)     | 4000       | Unified AI gateway proxy             |
| **CreateBuckets** | quay.io/minio/mc     | --         | Init container (creates S3 buckets)  |

**Startup order:** PostgreSQL, MinIO, Qdrant start in parallel. CreateBuckets
waits for MinIO. MLflow waits for PostgreSQL, MinIO, and CreateBuckets. LiteLLM
waits for PostgreSQL and MLflow.

**Service UIs:**

| Service          | URL                               |
| ---------------- | --------------------------------- |
| LiteLLM          | <http://localhost:4000>           |
| MLflow           | <http://localhost:8080>           |
| MinIO Console    | <http://localhost:9001>           |
| Qdrant Dashboard | <http://localhost:6333/dashboard> |

## CLI Reference

LLMaven provides a CLI built with Typer:

```bash
llmaven version                           # Show version

# Infrastructure commands
llmaven infra init --environment dev      # Generate llmaven-config.yaml
llmaven infra validate --config llmaven-config.yaml  # Validate config + cost estimate
llmaven infra deploy --preview            # Dry run (no resources created)
llmaven infra deploy --yes                # Deploy to Azure
llmaven infra status                      # View deployment status
llmaven infra destroy --yes               # Tear down resources

# Backup infrastructure commands (separate Pulumi project, isolated resource group)
llmaven infra backup init -e prod --from-primary-stack llmaven-config.yaml
llmaven infra backup deploy --preview     # Dry run
llmaven infra backup deploy --yes         # Deploy Azure Backup Vault
llmaven infra backup status               # View backup deployment status
llmaven infra backup refresh              # Sync Pulumi state with Azure
llmaven infra backup destroy --yes        # Remove backup vault (deletes recovery points)
```

## Azure Infrastructure Deployment

The local Docker services map directly to Azure managed equivalents, deployed
via Pulumi Automation API:

| Local Service          | Azure Equivalent                              |
| ---------------------- | --------------------------------------------- |
| PostgreSQL (db:5432)   | Azure Database for PostgreSQL Flexible Server |
| MinIO (minio:9000)     | Azure Blob Storage (ADLS Gen2)                |
| MLflow (mlflow:8080)   | Azure Container App (MLflow)                  |
| LiteLLM (litellm:4000) | Azure Container App (LiteLLM)                 |

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

## Database Backup (Azure Backup Vault)

LLMaven uses a separate `infrastructure-backup` Pulumi project to protect the
PostgreSQL Flexible Server with Azure Backup Vault. Backups are stored in
Microsoft-managed storage outside your subscription — they survive accidental
deletion of the primary resource group, including `pulumi destroy` on the main
stack.

**How it works**: A weekly full backup (pg_dump) is triggered by the vault via
Azure Resource Manager APIs. No database credentials are stored. Recovery points
are retained according to the configured schedule.

**Restore note**: Recovery currently produces `.sql` dump files in a target
storage account ("Restore as Files"). Use `pg_restore` on a new server to
reconstruct the database. "Restore as Server" is on the Azure roadmap.

### First-Time Backup Setup

Run these steps once per environment, **after** the primary infrastructure is
deployed:

**1. Generate the backup config:**

```bash
# Auto-populates postgres_server_name and resource_group_name from your
# deployed primary stack:
llmaven infra backup init \
  --environment prod \
  --from-primary-stack llmaven-config.yaml \
  --output llmaven-backup-config.yaml
```

If the primary stack is not yet deployed, omit `--from-primary-stack` and fill
in `primary_stack.*` manually after deploying:

```bash
llmaven infra backup init --environment prod
# then edit llmaven-backup-config.yaml
```

**2. Set your subscription ID** in `llmaven-backup-config.yaml`:

```yaml
azure:
  subscription_id: "your-subscription-id"
```

**3. Review backup settings** (optional):

```yaml
backup:
  redundancy: GeoRedundant        # prod: GeoRedundant; dev/staging: LocallyRedundant
  immutability_enabled: true      # prevents deletion of recovery points
  soft_delete_retention_days: 30  # days to recover soft-deleted backups
  backup_schedule_utc: "R/2024-01-01T02:00:00Z/P1W"  # weekly, Sundays 02:00 UTC
  retention_weeks: 52             # keep 1 year of weekly backups (prod default)
```

**4. Preview and deploy:**

```bash
llmaven infra backup deploy --config llmaven-backup-config.yaml --preview
llmaven infra backup deploy --config llmaven-backup-config.yaml --yes
```

This creates an isolated Azure resource group (e.g., `rg-llmaven-backup-prod-eastus`)
containing:

```
rg-llmaven-backup-prod-eastus
├── Backup Vault (system-assigned MSI)
│   ├── Backup Policy (weekly, configurable retention)
│   └── Backup Instance → PostgreSQL Flexible Server
└── Storage Account (Pulumi state for the backup stack)

Cross-RG role assignments (managed by backup stack):
  Vault MSI → Reader on rg-llmaven-prod-eastus
  Vault MSI → PostgreSQL Flexible Server Long Term Retention Backup Role (on server)
```

**5. Verify the role definition GUID** before deploying (one-time check):

```bash
az role definition list \
  --name "PostgreSQL Flexible Server Long Term Retention Backup Role" \
  --query "[0].name" \
  --output tsv
```

The GUID is hardcoded in
`src/llmaven/infrastructure_backup/resources/backup.py` as
`_POSTGRES_LTR_BACKUP_ROLE_ID`. Update it if the output differs.

### Updating Backup Configuration

To change retention, redundancy, or schedule after the initial deployment:

**1. Edit `llmaven-backup-config.yaml`** with the new values.

**2. Preview the changes:**

```bash
llmaven infra backup deploy --config llmaven-backup-config.yaml --preview
```

**3. Apply:**

```bash
llmaven infra backup deploy --config llmaven-backup-config.yaml --yes
```

> **Immutability note**: Once `immutability_enabled: true` has been deployed and
> the vault is in "Locked" state, it cannot be disabled via Pulumi. To destroy the
> vault you must first manually remove the lock in the Azure Portal.

### Backup CLI Reference

```bash
# Initialize backup config (auto-populate from deployed primary stack)
llmaven infra backup init -e prod --from-primary-stack llmaven-config.yaml

# Preview changes
llmaven infra backup deploy --config llmaven-backup-config.yaml --preview

# Deploy backup infrastructure
llmaven infra backup deploy --config llmaven-backup-config.yaml --yes

# Show backup deployment status
llmaven infra backup status --config llmaven-backup-config.yaml

# Refresh Pulumi state from actual cloud resources
llmaven infra backup refresh --config llmaven-backup-config.yaml

# Destroy backup infrastructure (requires disabling immutability first if enabled)
llmaven infra backup destroy --config llmaven-backup-config.yaml
```

### Restoring from Backup

When you need to restore (e.g., after the primary RG was accidentally deleted):

1. **Create a new PostgreSQL Flexible Server** (via `llmaven infra deploy` with a
   fresh config, or manually in the Azure Portal).

2. **Create a target storage account** to receive the dump files (can be any
   storage account you own).

3. **Initiate restore** in the Azure Portal:
   - Navigate to the Backup Vault → Backup Instances
   - Select the PostgreSQL instance → Restore
   - Choose "Restore as Files" → select the target storage account and container

4. **Download the `.sql` dump files** from the storage container.

5. **Restore using `pg_restore`**:

   ```bash
   pg_restore \
     --host=<new-server-fqdn> \
     --port=5432 \
     --username=<admin-login> \
     --dbname=<database-name> \
     --no-owner \
     <dump-file.sql>
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
