# LLMaven Docker Infrastructure

LLMaven provides a complete containerized infrastructure for AI-powered
scientific discovery, featuring LLM proxy services, experiment tracking,
observability, and storage solutions.

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Prerequisites](#prerequisites)
4. [Quick Start](#quick-start)
5. [Services](#services)
6. [Configuration](#configuration)
7. [Usage](#usage)
8. [Pixi Integration](#pixi-integration)
9. [Monitoring and Logging](#monitoring-and-logging)
10. [Troubleshooting](#troubleshooting)
11. [Advanced Topics](#advanced-topics)
12. [Resources](#resources)

## Overview

This Docker setup provides a production-ready infrastructure for LLMaven that
includes:

- **LiteLLM Proxy**: Unified interface for 100+ LLMs with load balancing,
  fallbacks, and cost tracking
- **MLflow**: Experiment tracking and model registry for machine learning
  workflows
- **PostgreSQL**: Relational database for storing configurations, metrics, and
  experiment data
- **Azurite**: Local Azure Blob Storage emulator for MLflow artifacts and
  LiteLLM request logs

All services are orchestrated using Docker Compose and can be managed either
directly with `docker-compose` commands or through convenient Pixi tasks.

### Directory Structure

```
docker/
├── docker-compose.yml          # Main orchestration file
├── .env.example                # Template for environment variables
├── config.yaml                 # LiteLLM proxy configuration
├── create_service_dbs.sql      # PostgreSQL database initialization
├── ensure_blob_container.py    # Creates the MLflow blob container in Azurite
├── dockerfiles/
│   ├── litellm.dockerfile      # Custom LiteLLM image with mlflow
│   └── mlflow.dockerfile       # Custom MLflow image with dependencies
└── README.md                   # This file
```

**Important**: Copy `.env.example` to `.env` and configure your credentials
before starting services.

## Architecture

```mermaid
graph TB
    subgraph "LLMaven Docker Stack"
        subgraph "Application Layer"
            LiteLLM["🤖 LiteLLM Proxy<br/>Port 4000<br/><br/>OpenAI-compatible API<br/>Multi-provider support<br/>Request logging"]
            MLflow["📊 MLflow Tracking<br/>Port 8080<br/><br/>Experiment tracking<br/>Model registry<br/>Metrics visualization"]
        end

        subgraph "Data Layer"
            PostgreSQL["🗄️ PostgreSQL<br/>Port 5432<br/><br/>Databases:<br/>• mlflow_db<br/>• litellm_db<br/>• llmaven"]
            Azurite["💾 Azurite Blob Storage<br/>Port 10000<br/><br/>Containers:<br/>• mlflow (artifacts)<br/>• litellm-logs (request logs)"]
        end

        subgraph "External"
            Apps["📱 Applications<br/><br/>Python SDK<br/>cURL<br/>LangChain"]
            Providers["☁️ LLM Providers<br/><br/>Azure OpenAI<br/>OpenAI<br/>Anthropic"]
        end
    end

    Apps -->|"Chat Completions<br/>HTTP POST"| LiteLLM
    LiteLLM -->|"Route requests"| Providers
    LiteLLM -->|"Log requests/<br/>responses"| MLflow
    LiteLLM -->|"Store config<br/>& metrics"| PostgreSQL
    LiteLLM -->|"Write request<br/>logs"| Azurite
    MLflow -->|"Store artifacts<br/>(models, plots)"| Azurite
    MLflow -->|"Store metadata<br/>(runs, params)"| PostgreSQL

    style LiteLLM fill:#e1f5ff,stroke:#01579b,stroke-width:2px
    style MLflow fill:#fff3e0,stroke:#e65100,stroke-width:2px
    style PostgreSQL fill:#f3e5f5,stroke:#4a148c,stroke-width:2px
    style Azurite fill:#e8f5e9,stroke:#1b5e20,stroke-width:2px
    style Apps fill:#fff,stroke:#666,stroke-width:2px,stroke-dasharray: 5 5
    style Providers fill:#fff,stroke:#666,stroke-width:2px,stroke-dasharray: 5 5
```

### Data Flow

1. **LLM Requests**: Applications send chat completion requests to LiteLLM Proxy
   (port 4000) using OpenAI-compatible API
2. **Request Routing**: LiteLLM routes requests to configured LLM providers
   (Azure OpenAI, OpenAI, Anthropic, etc.)
3. **Automatic Logging**: All requests and responses are automatically logged to
   MLflow for experiment tracking and analysis, and written as JSON request logs
   to the Azurite `litellm-logs` blob container
4. **Artifact Storage**: MLflow stores model artifacts, plots, and experiment
   data in the Azurite `mlflow` blob container (real Azure Blob Storage in
   production)
5. **Metadata Storage**: Configuration, metrics, and run metadata are stored in
   PostgreSQL databases (mlflow_db, litellm_db)

## Prerequisites

### Required Software

- **Docker**: Version 20.10 or higher
- **Docker Compose**: Version 2.0 or higher

### Optional Software

- **Pixi**: For convenient task management (recommended)
  - Install from [pixi.sh](https://pixi.sh)
  - Provides simplified commands for managing the stack

### System Requirements

- **Minimum**: 4GB RAM, 10GB disk space
- **Recommended**: 8GB RAM, 20GB disk space
- **Ports**: Ensure the following ports are available:
  - 4000: LiteLLM Proxy
  - 5432: PostgreSQL
  - 8080: MLflow
  - 10000: Azurite Blob service

## Quick Start

### 1. Environment Setup

Copy the example environment file and configure your credentials:

```bash
# Navigate to the docker directory
cd docker
cp .env.example .env
```

Edit `.env` and configure at minimum:

```bash
# Required: Azure OpenAI credentials
AZURE_API_KEY=your-azure-api-key
AZURE_API_BASE=https://your-resource.openai.azure.com/
AZURE_API_VERSION=2024-12-01-preview

# Optional: Change default passwords (recommended for production)
POSTGRES_PASSWORD=your-secure-password
LITELLM_MASTER_KEY=your-master-key
```

### 2. Start Services

Choose one of the following methods:

#### Option A: Using Pixi (Recommended)

```bash
# From the project root directory
pixi run -e llmaven up
```

#### Option B: Using Docker Compose Directly

```bash
# From the docker directory
docker-compose up -d
```

**Note**: The first time you run this command, Docker will build custom images
for LiteLLM and MLflow. This may take a few minutes. Subsequent starts will be
much faster.

### 3. Verify Services

Check that all services are running:

```bash
# Using Pixi
pixi run -e llmaven status

# Using Docker Compose
docker-compose ps
```

Expected output should show all services as "healthy" or "running".

### 4. Access Services

Once all services are healthy:

- **LiteLLM UI**: http://localhost:4000
- **LiteLLM API Documentation**: http://localhost:4000/docs
- **MLflow UI**: http://localhost:8080
- **Azurite Blob endpoint**: http://127.0.0.1:10000/devstoreaccount1 (no web UI;
  see [Managing Storage with Azurite](#managing-storage-with-azurite))

## Services

### LiteLLM Proxy

**Purpose**: Unified API gateway for multiple LLM providers

**Image**: Custom build from `dockerfiles/litellm.dockerfile`

- Base image: `ghcr.io/berriai/litellm:v1.106.6` (pinned by digest)
- Pre-installed packages: `mlflow-skinny==3.6.0`

**Ports**:

- `4000:4000`: LiteLLM Proxy API - hardcoded mapping

**Features**:

- OpenAI-compatible API interface
- Support for 100+ LLM providers
- Request/response logging to MLflow
- Cost tracking and usage monitoring
- Load balancing and fallback support
- API key management with master key authentication

**Configuration**: `config.yaml` in the docker directory

- Copied into the image at build time at `/app/config.yaml`

**Container Name**: `llmaven_litellm`

**Network**: `llmaven-network`

**Dependencies**: Waits for PostgreSQL (healthy), MLflow (healthy), and Azurite
(healthy)

**Startup Command**:

- `litellm --config /app/config.yaml`

**Restart Policy**: Not explicitly set (defaults to `no` - doesn't restart
automatically)

**Health Check**:

- Interval: 30s
- Timeout: 10s
- Retries: 3
- Start period: 40s (grace period before first check)
- Uses Python urllib to check the `/health/liveliness` endpoint (the image has
  no `wget` or `curl`)

**Key Environment Variables**:

- `LITELLM_MASTER_KEY`: Master authentication key
- `DATABASE_URL`: PostgreSQL connection string for LiteLLM data
- `MLFLOW_TRACKING_URI`: MLflow server endpoint for logging
- `AZURE_STORAGE_CONNECTION_STRING`: Azurite connection for request logs
- `ADLS_CONTAINER`: Blob container for request logs (default: `litellm-logs`)

### MLflow

**Purpose**: Experiment tracking, model registry, and ML lifecycle management

**Image**: Custom build from `dockerfiles/mlflow.dockerfile`

- Base image: `ghcr.io/mlflow/mlflow:v3.6.0`
- Pre-installed packages: `psycopg2-binary==2.9.11`,
  `azure-storage-blob==12.31.0`

**Ports**:

- `${MLFLOW_PORT}:${MLFLOW_PORT}`: MLflow UI/API (default: 8080:8080) - uses
  environment variable

**Features**:

- Experiment tracking and comparison
- Model versioning and registry
- Artifact storage in Azure Blob Storage (Azurite locally)
- Metrics visualization
- Model deployment capabilities
- CORS enabled for cross-origin requests
- Allows connections from all hosts

**Database**: Uses `mlflow_db` in PostgreSQL for backend storage

**Artifact Storage**: Uses the Azurite blob container `mlflow` for artifacts

**Container Name**: `llmaven_mlflow`

**Network**: `llmaven-network`

**Dependencies**: Waits for PostgreSQL (healthy) and Azurite (healthy)

**Startup Command**: The compose file overrides the entrypoint to run
`ensure_blob_container.py` (mounted read-only at `/opt/llmaven/`), which creates
the `mlflow` blob container if it is missing, then `exec mlflow server` with:

- `--allowed-hosts '*'`: Accepts connections from any hostname
- `--cors-allowed-origins '*'`: Enables CORS for all origins

**Restart Policy**: `always` - automatically restarts if the container stops

**Health Check**:

- Interval: 10s
- Timeout: 5s
- Retries: 30
- Uses Python urllib to check `/health` endpoint

**Key Environment Variables**:

- `MLFLOW_BACKEND_STORE_URI`: PostgreSQL connection for metadata
- `MLFLOW_DEFAULT_ARTIFACT_ROOT`: Blob path for artifacts
  (`wasbs://mlflow@devstoreaccount1.blob.core.windows.net/`)
- `AZURE_STORAGE_CONNECTION_STRING`: Azurite connection string; supplies the
  real blob endpoint (`http://azurite:10000/devstoreaccount1`)

### PostgreSQL

**Purpose**: Relational database for service metadata and configurations

**Image**: `postgres:16`

**Ports**:

- `${POSTGRES_PORT}:5432`: PostgreSQL database (default: 5432:5432) - uses
  environment variable

**Volume Mounts**:

- `postgres_data:/var/lib/postgresql/data`: PostgreSQL data directory
- `./create_service_dbs.sql:/docker-entrypoint-initdb.d/create_service_dbs.sql`:
  Database initialization script

**Databases Created**:

- `llmaven`: Main database (default)
- `mlflow_db`: MLflow backend storage
- `litellm_db`: LiteLLM proxy storage

**Initialization**: Automatically runs
`/Users/lsetiawan/Repos/SSEC/llmaven/docker/create_service_dbs.sql` on first
startup

**Data Persistence**: Uses named volume `llmaven_postgres_data`

**Container Name**: `llmaven_db`

**Network**: `llmaven-network` (bridge driver)

**Restart Policy**: `always` - automatically restarts if the container stops

**Health Check**:

- Interval: 10s
- Timeout: 5s
- Retries: 5
- Command: `pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}`

**Key Environment Variables**:

- `POSTGRES_USER`: Database admin user (default: llmaven-admin)
- `POSTGRES_PASSWORD`: Database password
- `POSTGRES_DB`: Default database name
- `POSTGRES_PORT`: Exposed port (default: 5432)

### Azurite

**Purpose**: Local Azure Blob Storage emulator for MLflow artifacts and LiteLLM
request logs. Production uses the same Blob mechanism against real Azure
Storage.

**Image**: `mcr.microsoft.com/azure-storage/azurite`

**Blob Containers**:

- `mlflow`: MLflow artifacts (models, plots, data), created by
  `ensure_blob_container.py` before MLflow starts
- `litellm-logs`: LiteLLM request logs (`ADLS_CONTAINER`), created by the
  LiteLLM ADLS logger on startup

**Ports**:

- `10000:10000`: Blob service - hardcoded mapping

**Volume Mounts**:

- `azurite_data:/data`: Azurite data directory

**Server Command**:
`azurite-blob --blobHost 0.0.0.0 --blobPort 10000 --location /data --skipApiVersionCheck`

- Runs only the Blob service on port 10000
- Persists data in `/data`

**Data Persistence**: Uses named volume `llmaven_azurite_data`

**Container Name**: `llmaven_azurite`

**Network**: `llmaven-network` (bridge driver)

**Restart Policy**: Not explicitly set (defaults to `no` - doesn't restart
automatically)

**Health Check**:

- Interval: 5s
- Timeout: 3s
- Retries: 10
- Start period: 5s
- Command: `nc -z 127.0.0.1 10000`

**Credentials**: Azurite uses the well-known development account
`devstoreaccount1` and its public account key (see `.env.example`). Services
connect through `AZURE_STORAGE_CONNECTION_STRING`, whose `BlobEndpoint` uses the
compose hostname `azurite`.

## Configuration

### Environment Variables

The `.env` file contains all configuration for the Docker stack. See
`.env.example` for a complete reference.

**Important**: All services load environment variables from the `.env` file
using `env_file: - .env` in their Docker Compose configuration. Make sure the
`.env` file exists before starting services.

#### Core Database Configuration

```bash
# Postgres Configuration
POSTGRES_HOST=${POSTGRES_HOST:-db}  # Database hostname (defaults to 'db')
POSTGRES_DB=llmaven                 # Default database
POSTGRES_USER=llmaven-admin         # Admin user
POSTGRES_PASSWORD=dbpassword9090    # Change in production!
POSTGRES_PORT=5432                  # PostgreSQL port
```

#### Azurite Configuration

```bash
# Azurite — MLflow artifacts and the ADLS logger
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=<well-known Azurite key>;BlobEndpoint=http://azurite:10000/devstoreaccount1;
ADLS_CONTAINER=litellm-logs                                    # Blob container for LiteLLM request logs
```

**Note**: The account key is the well-known public Azurite development key; the
full value is in `.env.example`. The `azurite` hostname resolves only inside the
compose network. From the host, use
`BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1` with the same account
name and key.

#### MLflow Configuration

```bash
# MLflow Configuration
MLFLOW_HOST=${MLFLOW_HOST:-mlflow}                                                              # MLflow hostname (defaults to 'mlflow')
MLFLOW_PORT=8080                                                                                 # MLflow UI/API port
MLFLOW_BACKEND_STORE_URI=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/mlflow_db
MLFLOW_DEFAULT_ARTIFACT_ROOT=wasbs://mlflow@devstoreaccount1.blob.core.windows.net/
```

**Note**: MLflow's parser requires the account hostname form
(`devstoreaccount1.blob.core.windows.net`) in the artifact URI. The real
endpoint comes from `AZURE_STORAGE_CONNECTION_STRING`, which points at Azurite
locally.

**Note**: The MLflow Docker image is built with `psycopg2-binary` and
`azure-storage-blob` pre-installed (see `dockerfiles/mlflow.dockerfile`).

#### LiteLLM Configuration

```bash
# LiteLLM Configuration
LITELLM_DB=litellm_db
LITELLM_DATABASE_URL=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/litellm_db
DATABASE_URL=${LITELLM_DATABASE_URL}                                  # Required by LiteLLM
MLFLOW_TRACKING_URI=http://${MLFLOW_HOST}:${MLFLOW_PORT}             # Uses MLflow variables
MLFLOW_EXPERIMENT_NAME="Default"
LITELLM_MASTER_KEY=                                                   # Required, see below
```

**Master key**: LiteLLM 1.106+ refuses to start when `LITELLM_MASTER_KEY` is
unset, empty, or one of the publicly known defaults (including `sk-1234`).
Generate a key before the first start, only if `.env` doesn't already have one
(a new key on an existing database needs the migration below):

```bash
echo "LITELLM_MASTER_KEY=sk-$(openssl rand -hex 32)" >> .env
```

Docker Compose reads `.env` for the containers, but it doesn't set anything in
your host shell. The client examples under [Usage](#usage) read
`LITELLM_MASTER_KEY` from your shell, so export the configured key there first:

```bash
export LITELLM_MASTER_KEY="$(sed -n 's/^LITELLM_MASTER_KEY=\([^[:space:]#]*\).*/\1/p' .env | tail -n 1)"
```

When `LITELLM_SALT_KEY` is unset, the master key also encrypts the provider
credentials stored in the database. Changing it on an existing database is a
migration, not a config edit:

1. Set `LITELLM_MIGRATE_FROM_MASTER_KEY=<old key>` next to the new
   `LITELLM_MASTER_KEY`.
2. Start the proxy once. It re-encrypts the stored values and logs that the old
   key can be removed.
3. Remove `LITELLM_MIGRATE_FROM_MASTER_KEY`.

A local database created with `sk-1234` needs these steps, or can be recreated
by stopping the stack and removing the `llmaven_postgres_data` volume (this
deletes all local Postgres data).

**Note**: The LiteLLM Docker image is built with `mlflow-skinny` pre-installed
(see `dockerfiles/litellm.dockerfile`).

#### LLM Provider API Keys

```bash
# Azure OpenAI (Required for default config.yaml)
AZURE_API_KEY=your-azure-api-key
AZURE_API_BASE=https://your-resource.openai.azure.com/
AZURE_API_VERSION=2024-12-01-preview

# OpenAI (Optional)
# OPENAI_API_KEY=your-openai-api-key

# Anthropic (Optional)
# ANTHROPIC_API_KEY=your-anthropic-api-key
```

### LiteLLM Model Configuration

The file `config.yaml` defines LLM models and routing:

```yaml
model_list:
  # Azure OpenAI Models
  - model_name: gpt-5-mini
    litellm_params:
      model: azure/gpt-5-mini
      api_base: os.environ/AZURE_API_BASE
      api_key: os.environ/AZURE_API_KEY
      api_version: os.environ/AZURE_API_VERSION

# Logging Configuration - Push to MLflow
litellm_settings:
  success_callback: ["mlflow"]
  failure_callback: ["mlflow"]
  callbacks: adl_logger.proxy_handler_instance

# General settings
general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  database_url: os.environ/DATABASE_URL
  store_prompts_in_spend_logs: true
  store_model_in_db: true
```

#### Adding More Models

To add additional models or providers, edit `config.yaml`:

```yaml
model_list:
  # Add OpenAI GPT-4
  - model_name: gpt-4
    litellm_params:
      model: openai/gpt-4
      api_key: os.environ/OPENAI_API_KEY

  # Add Anthropic Claude
  - model_name: claude-3-sonnet
    litellm_params:
      model: anthropic/claude-3-sonnet-20240229
      api_key: os.environ/ANTHROPIC_API_KEY
```

Then add the corresponding API keys to your `.env` file.

#### Request Logging to Azure Blob Storage

In addition to MLflow, `config.yaml` registers the ADLS logger
(`src/llmaven/infrastructure/resources/adl_logger.py`, mounted into the LiteLLM
container at `/app/adl_logger.py`):

```yaml
litellm_settings:
  callbacks: adl_logger.proxy_handler_instance
```

It writes one JSON file per request to the `ADLS_CONTAINER` blob container
(default `litellm-logs`) using `AZURE_STORAGE_CONNECTION_STRING`, which points
at Azurite locally.

### Custom Docker Images

LLMaven uses custom Docker images for LiteLLM and MLflow to pre-install required
dependencies, improving startup time and reliability.

#### MLflow Dockerfile

Located at `dockerfiles/mlflow.dockerfile`:

```dockerfile
FROM ghcr.io/mlflow/mlflow:v3.6.0

RUN pip install --no-cache-dir "psycopg2-binary==2.9.11" "azure-storage-blob==12.31.0"

ENTRYPOINT ["mlflow", "server"]
```

Pre-installs PostgreSQL database adapter and Azure Blob Storage client for
artifact storage. The image's `ENTRYPOINT` is unchanged; only the local compose
file overrides it to run `ensure_blob_container.py` first.

#### LiteLLM Dockerfile

Located at `dockerfiles/litellm.dockerfile`:

```dockerfile
FROM ghcr.io/berriai/litellm:v1.106.6@sha256:37e2dafb088a7723beb998590682957386dfc83ffea1848486f8e0e5cfac0b06

RUN python -m ensurepip \
 && python -m pip install --no-cache-dir \
      "litellm==1.106.6" "mlflow-skinny==3.6.0" "azure-storage-blob>=12.0.0,<13" "azure-identity>=1.0.0,<2"
```

The base image has no `pip` executable, so the build bootstraps it with the
bundled `ensurepip`. Pinning `litellm==1.106.6` again makes the build fail if
the add-on packages would replace it. The image uses `mlflow-skinny` because the
full `mlflow==3.6.0` package caps `cryptography<47`, which would downgrade the
base image's patched `cryptography`.

Pre-installs MLflow for logging integration and copies the LiteLLM configuration
file into the image.

**Building the Images**: The images are automatically built when you run
`docker-compose up` or `pixi run -e llmaven up`. To rebuild after changes:

```bash
# Rebuild all custom images
docker-compose build

# Rebuild specific service
docker-compose build mlflow
docker-compose build litellm

# Force rebuild without cache
docker-compose build --no-cache
```

### Database Initialization

The file `create_service_dbs.sql` automatically creates required databases on
first startup:

- Creates `mlflow_db` for MLflow backend storage
- Creates `litellm_db` for LiteLLM proxy data
- Grants appropriate privileges to the configured user
- Script is idempotent (safe to run multiple times)

## Usage

### Making LLM Requests

These examples read `LITELLM_MASTER_KEY` from your shell. In a new shell, run
the `export` from [LiteLLM Configuration](#litellm-configuration) in the
`docker/` directory first.

#### Using cURL

```bash
curl http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{
    "model": "gpt-5-mini",
    "messages": [
      {"role": "user", "content": "Explain quantum entanglement"}
    ]
  }'
```

#### Using OpenAI Python SDK

```python
import os

from openai import OpenAI

# Configure client to use LiteLLM proxy
client = OpenAI(
    base_url="http://localhost:4000",
    api_key=os.environ["LITELLM_MASTER_KEY"],
)

# Make a chat completion request
response = client.chat.completions.create(
    model="gpt-5-mini",
    messages=[
        {"role": "system", "content": "You are a helpful scientific assistant."},
        {"role": "user", "content": "What is the significance of the Higgs boson?"}
    ]
)

print(response.choices[0].message.content)
```

#### Using LangChain

```python
import os

from langchain_openai import ChatOpenAI

# Configure LangChain to use LiteLLM proxy
llm = ChatOpenAI(
    model="gpt-5-mini",
    openai_api_key=os.environ["LITELLM_MASTER_KEY"],
    openai_api_base="http://localhost:4000"
)

# Make a request
response = llm.invoke("Explain the theory of relativity")
print(response.content)
```

### Tracking Experiments with MLflow

All LLM requests are automatically logged to MLflow. Access the UI at
http://localhost:8080 to:

- View request/response history
- Compare model performance
- Track costs and token usage
- Analyze response patterns

**Note**: By default, LiteLLM logs to the "Default" experiment. You can
customize this by setting `MLFLOW_EXPERIMENT_NAME` in your `.env` file.

#### Programmatic MLflow Access

```python
import mlflow

# Set tracking URI
mlflow.set_tracking_uri("http://localhost:8080")

# Get experiment by name
experiment = mlflow.get_experiment_by_name("Default")

# Search runs
runs = mlflow.search_runs(experiment_ids=[experiment.experiment_id])
print(runs[['run_id', 'metrics.total_cost', 'params.model']])
```

### Managing Storage with Azurite

Azurite has no web console. Use the Azure CLI, Azure Storage Explorer, or the
Python SDK against the host endpoint. The connection string in `.env` uses the
hostname `azurite`, which resolves only inside the compose network; from the
host, use `127.0.0.1` instead:

```bash
export AZURITE_CONN="DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
```

The account key is the well-known public Azurite development key from
`.env.example`.

#### Using Azure CLI

```bash
# List blob containers
az storage container list --connection-string "$AZURITE_CONN" -o table

# List MLflow artifacts
az storage blob list --container-name mlflow --connection-string "$AZURITE_CONN" -o table

# List LiteLLM request logs
az storage blob list --container-name litellm-logs --connection-string "$AZURITE_CONN" -o table
```

#### Using Python azure-storage-blob

```python
import os

from azure.storage.blob import BlobServiceClient

client = BlobServiceClient.from_connection_string(os.environ["AZURITE_CONN"])

# List containers
for container in client.list_containers():
    print(container.name)

# List MLflow artifacts
for blob in client.get_container_client("mlflow").list_blobs():
    print(blob.name)
```

#### Upgrading from MinIO

Earlier versions of this stack stored MLflow artifacts in MinIO. Two things do
not change on their own when you pull this version:

- Your existing `docker/.env` still sets
  `MLFLOW_DEFAULT_ARTIFACT_ROOT=s3://mlflow/`. Updating `.env.example` does not
  touch it, and with that value even new experiments get an `s3://` location
  that the MLflow image can no longer write to.
- Existing MLflow experiments, including `Default`, keep the `s3://mlflow/...`
  artifact location stored in Postgres. Changing the default root only affects
  experiments created afterwards.

Upgrade in this order:

1. Edit your existing `docker/.env` in place, keeping your API keys and other
   credentials. Set
   `MLFLOW_DEFAULT_ARTIFACT_ROOT=wasbs://mlflow@devstoreaccount1.blob.core.windows.net/`
   and check that `AZURE_STORAGE_CONNECTION_STRING` matches `.env.example`
   (`BlobEndpoint=http://azurite:10000/devstoreaccount1`). The old `MINIO_*`,
   `S3_ENDPOINT_URL`, `MLFLOW_S3_*` and `AWS_*` lines are unused and can be
   removed.
2. Rebuild MLflow and recreate the stack. `pixi run -e llmaven up` runs
   `docker-compose up -d` without `--build`, so build explicitly from `docker/`:

   ```bash
   docker-compose up -d --build --remove-orphans
   ```

   `--remove-orphans` removes the leftover MinIO containers only. It does not
   delete volumes, so the old MinIO data stays on disk unless you deliberately
   remove that volume yourself.

3. Create a new experiment in the MLflow UI (<http://localhost:8080> by default,
   or your `MLFLOW_PORT`) and check that its artifact location starts with
   `wasbs://mlflow@`.
4. Point LiteLLM at it: set `MLFLOW_EXPERIMENT_NAME` in `docker/.env` to the new
   experiment's name, then run `docker-compose up -d litellm` to recreate
   LiteLLM with the new value.

Runs in the old experiments keep their metadata, but MLflow can no longer read
their artifacts. Keep the old MinIO running separately if you need them.

## Docker Compose Infrastructure

### Volumes

The Docker Compose setup uses two persistent volumes:

```yaml
volumes:
  postgres_data:
    name: llmaven_postgres_data # Named volume for Postgres data persistence
  azurite_data:
    name: llmaven_azurite_data # Named volume for Azurite blob data (MLflow artifacts, LiteLLM logs)
```

- **llmaven_postgres_data**: Named volume for PostgreSQL database files
  - Persists database data across container restarts and recreations
  - Explicitly named as `llmaven_postgres_data`
  - Contains all PostgreSQL databases (`llmaven`, `mlflow_db`, `litellm_db`)

- **llmaven_azurite_data**: Named volume for Azurite blob storage
  - Mounted at `/data` (Azurite `--location /data`)
  - Persists blob data (MLflow artifacts, LiteLLM request logs)
  - Contains the `mlflow` and `litellm-logs` blob containers

### Networks

All services communicate through a single bridge network:

```yaml
networks:
  llmaven-network:
    driver: bridge # Bridge network for service communication
```

- **llmaven-network**: Bridge network connecting all services
  - Driver: `bridge` (default Docker network driver)
  - Enables container-to-container communication
  - Services can reference each other by service name (e.g., `db`, `azurite`,
    `mlflow`, `litellm`)
  - Internal DNS resolution provided by Docker
  - Isolated from host network for security

### Service Dependencies

The services have the following startup order enforced by `depends_on`:

1. **PostgreSQL (`db`)**: Starts first (no dependencies)
2. **Azurite (`azurite`)**: Starts first, in parallel with PostgreSQL (no
   dependencies)
3. **MLflow (`mlflow`)**: Waits for PostgreSQL (healthy) and Azurite (healthy);
   creates the `mlflow` blob container before the server starts
4. **LiteLLM (`litellm`)**: Waits for PostgreSQL (healthy), MLflow (healthy),
   and Azurite (healthy)

This dependency chain ensures all required infrastructure is ready before
dependent services start.

## Pixi Integration

LLMaven integrates with [Pixi](https://pixi.sh), a modern package manager for
reproducible development environments. The docker infrastructure is managed
through the `llmaven` Pixi environment.

### Available Pixi Tasks

From the `pixi.toml` configuration in the project root:

```bash
# Start all services
pixi run -e llmaven up

# Stop all services
pixi run -e llmaven down

# View service logs (follow mode)
pixi run -e llmaven logs

# Check service status
pixi run -e llmaven status

# Restart all services
pixi run -e llmaven restart

# Clean up (stops services and removes volumes - WARNING: deletes data)
pixi run -e llmaven clean
```

### How Pixi Tasks Work

Each task is defined in `pixi.toml` under the `[feature.docker.tasks]` section:

```toml
[feature.docker.tasks]
up = { cmd = "docker-compose up -d", cwd = "docker" }
down = { cmd = "docker-compose down", cwd = "docker" }
logs = { cmd = "docker-compose logs -f", cwd = "docker" }
status = { cmd = "docker-compose ps", cwd = "docker" }
restart = { cmd = "docker-compose restart", cwd = "docker" }
clean = { cmd = "docker-compose down -v", cwd = "docker" }
```

The `cwd = "docker"` ensures commands run from the correct directory.

### Installing Pixi

If you don't have Pixi installed:

```bash
# macOS/Linux
curl -fsSL https://pixi.sh/install.sh | bash

# Or using Homebrew (macOS)
brew install pixi

# Windows
iwr -useb https://pixi.sh/install.ps1 | iex
```

After installation, initialize the environment:

```bash
# Navigate to the project root
cd path/to/llmaven
pixi install
```

## Monitoring and Logging

### Service Health Checks

All services include health checks configured in `docker-compose.yml`:

#### PostgreSQL Health Check

```bash
# Check database health
docker-compose exec db pg_isready -U llmaven-admin -d llmaven

# Connect to database
docker-compose exec db psql -U llmaven-admin -d llmaven
```

#### LiteLLM Health Check

```bash
# Check liveness (used by Docker health check)
curl http://localhost:4000/health/liveliness

# Inside the container (as used by Docker health check)
docker exec llmaven_litellm python -c "import urllib.request; urllib.request.urlopen('http://localhost:4000/health/liveliness', timeout=5)"
```

#### MLflow Health Check

```bash
# Check MLflow health endpoint
curl http://localhost:8080/health

# Using Python (as used by Docker health check)
python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"
```

#### Azurite Health Check

```bash
# Check the Blob port (as used by Docker health check)
docker-compose exec azurite nc -z 127.0.0.1 10000

# From the host
nc -z 127.0.0.1 10000
```

### Viewing Logs

#### All Services

```bash
# Using Pixi
pixi run -e llmaven logs

# Using Docker Compose
docker-compose logs -f
```

#### Specific Service

```bash
# LiteLLM logs
docker-compose logs -f litellm

# MLflow logs
docker-compose logs -f mlflow

# PostgreSQL logs
docker-compose logs -f db

# Azurite logs
docker-compose logs -f azurite
```

#### Last N Lines

```bash
# Last 100 lines of LiteLLM logs
docker-compose logs --tail=100 litellm
```

### MLflow Experiment Tracking

All LiteLLM requests are automatically logged to MLflow:

1. Open MLflow UI: http://localhost:8080
2. Navigate to the experiment (default: "Default", or custom name set via
   `MLFLOW_EXPERIMENT_NAME`)
3. View runs showing:
   - Model used
   - Prompt and completion
   - Token counts
   - Response time
   - Estimated cost

## Troubleshooting

### Services Fail to Start

**Symptom**: Services exit or restart repeatedly

**Diagnosis**:

```bash
# Check service status
docker-compose ps

# View logs for failing service
docker-compose logs <service-name>
```

**Common Causes**:

1. **Port conflicts**: Another service using required ports

   ```bash
   # Check port usage
   lsof -i :4000
   lsof -i :5432
   lsof -i :8080
   lsof -i :10000
   ```

   **Solution**: Stop conflicting services or change ports in `.env`

2. **Missing environment variables**: Required variables not set in `.env`

   **Solution**: Ensure all required variables from `.env.example` are set

3. **Database initialization failure**: PostgreSQL startup issues

   ```bash
   # Check PostgreSQL logs
   docker-compose logs db
   ```

   **Solution**: Verify database credentials in `.env`

### LiteLLM Connection Errors

**Symptom**: 500 errors when calling LiteLLM API

**Diagnosis**:

```bash
# Check LiteLLM logs
docker-compose logs litellm

# Test health endpoint
curl http://localhost:4000/health/liveliness
```

**Common Causes**:

1. **Invalid API keys**: Azure/OpenAI credentials incorrect

   **Solution**: Verify API keys in `.env` are correct

2. **Database connection failure**: Cannot connect to PostgreSQL

   **Solution**: Ensure PostgreSQL is healthy and credentials match

3. **MLflow connection failure**: Cannot connect to MLflow

   **Solution**: Verify MLflow is running and healthy

### MLflow Cannot Store Artifacts

**Symptom**: MLflow logs show Azure Blob connection errors

**Diagnosis**:

```bash
# Check MLflow logs (includes ensure_blob_container.py output)
docker-compose logs mlflow

# Verify Azurite is running
docker-compose ps azurite

# Check Azurite logs
docker-compose logs azurite
```

**Common Causes**:

1. **Azurite not ready**: Azurite is not healthy, so MLflow does not start

   **Solution**: Check `docker-compose logs azurite` and ensure port 10000 is
   free

2. **Wrong connection string**: `AZURE_STORAGE_CONNECTION_STRING` missing or
   incorrect

   **Solution**: Ensure it matches `.env.example` and that `BlobEndpoint` uses
   the `azurite` hostname (not `127.0.0.1`) inside the compose stack

3. **Missing container**: The `mlflow` blob container doesn't exist

   **Solution**: `ensure_blob_container.py` creates it on every MLflow start;
   restart MLflow and check its logs:

   ```bash
   docker-compose restart mlflow
   docker-compose logs mlflow | grep -i "blob container"
   ```

4. **Old experiments still point at MinIO**: Experiments created before the
   switch keep their old artifact location

   **Solution**: See [Upgrading from MinIO](#upgrading-from-minio)

### Database Connection Refused

**Symptom**: Services cannot connect to PostgreSQL

**Diagnosis**:

```bash
# Check PostgreSQL is running
docker-compose ps db

# Test connection
docker-compose exec db psql -U llmaven-admin -d llmaven -c "SELECT 1;"
```

**Common Causes**:

1. **PostgreSQL not started**: Database container not running

   **Solution**: Start database:

   ```bash
   docker-compose up -d db
   ```

2. **Wrong credentials**: Username/password mismatch

   **Solution**: Verify `POSTGRES_USER` and `POSTGRES_PASSWORD` in `.env`

3. **Database not initialized**: Service databases not created

   **Solution**: Check initialization logs:

   ```bash
   docker-compose logs db | grep -A 10 "create_service_dbs"
   ```

### Complete Reset

If all else fails, perform a complete reset:

```bash
# Stop all services and remove volumes
pixi run -e llmaven clean

# Or using Docker Compose
docker-compose down -v

# Remove any orphaned volumes
docker volume prune

# Start fresh
pixi run -e llmaven up
```

**WARNING**: This deletes all data including:

- PostgreSQL databases
- MLflow experiments
- Azurite blob data (MLflow artifacts, LiteLLM request logs)

## Advanced Topics

### Production Deployment Considerations

#### Security Hardening

1. **Change Default Passwords**:

   ```bash
   # In .env
   POSTGRES_PASSWORD=<strong-random-password>
   LITELLM_MASTER_KEY=sk-<strong-random-key>
   ```

2. **Use Secret Management**:
   - Store credentials in HashiCorp Vault, AWS Secrets Manager, or Azure Key
     Vault
   - Mount secrets as files instead of environment variables

3. **Enable TLS/HTTPS**:
   - Configure reverse proxy (nginx, Traefik) with SSL certificates
   - Enable HTTPS for all services

4. **Network Isolation**:
   - Use Docker networks to isolate services
   - Expose only necessary ports to host
   - Use firewall rules to restrict access

#### Scaling Considerations

1. **PostgreSQL**:
   - Use managed database service (AWS RDS, Azure Database, Google Cloud SQL)
   - Configure connection pooling
   - Set up replication for high availability

2. **Azurite**:
   - Local development only; use Azure Blob Storage in production (same
     `wasbs://` artifact root and connection-string mechanism)

3. **LiteLLM**:
   - Run multiple instances behind load balancer
   - Use Redis for shared caching
   - Configure rate limiting and quotas

4. **MLflow**:
   - Use managed artifact store
   - Deploy MLflow on Kubernetes for auto-scaling
   - Configure authentication and authorization

#### Backup Strategies

1. **PostgreSQL Backup**:

   ```bash
   # Backup all databases
   docker-compose exec db pg_dumpall -U llmaven-admin > backup_$(date +%Y%m%d).sql

   # Restore
   docker-compose exec -T db psql -U llmaven-admin < backup_20240101.sql
   ```

2. **Azurite Backup**:

   ```bash
   # Download MLflow artifacts from Azurite to a local directory
   az storage blob download-batch --source mlflow --destination ./mlflow-backup \
     --connection-string "$AZURITE_CONN"
   ```

3. **Automated Backups**:
   - Set up cron jobs for regular backups
   - Use volume snapshots for quick recovery
   - Store backups in separate location/region

### Custom Model Integration

#### Adding Local LLaMA Model

1. Download model weights
2. Update `config.yaml`:

   ```yaml
   model_list:
     - model_name: llama-2-7b
       litellm_params:
         model: ollama/llama2
         api_base: http://ollama:11434
   ```

3. Add Ollama service to `docker-compose.yml`:
   ```yaml
   ollama:
     image: ollama/ollama:latest
     container_name: llmaven_ollama
     ports:
       - "11434:11434"
     volumes:
       - ollama_data:/root/.ollama
     networks:
       - llmaven-network
   ```

#### Adding HuggingFace Model

Update `config.yaml`:

```yaml
model_list:
  - model_name: falcon-7b
    litellm_params:
      model: huggingface/tiiuae/falcon-7b-instruct
      api_key: os.environ/HUGGINGFACE_API_KEY
```

Add `HUGGINGFACE_API_KEY` to `.env`.

### Custom Logging and Callbacks

LiteLLM supports multiple callback integrations. Edit `config.yaml`:

```yaml
litellm_settings:
  # Multiple callbacks
  success_callback: ["mlflow", "s3", "langfuse"]
  failure_callback: ["mlflow", "s3"]

  # Langfuse configuration
  langfuse_public_key: os.environ/LANGFUSE_PUBLIC_KEY
  langfuse_secret_key: os.environ/LANGFUSE_SECRET_KEY

  # Weights & Biases
  wandb_api_key: os.environ/WANDB_API_KEY
  wandb_project: "llmaven"
```

### Performance Tuning

#### PostgreSQL Optimization

Create `postgres.conf` and mount it:

```ini
# Performance tuning
shared_buffers = 256MB
effective_cache_size = 1GB
work_mem = 16MB
maintenance_work_mem = 128MB
max_connections = 100

# Logging
log_statement = 'all'
log_duration = on
```

Mount in `docker-compose.yml`:

```yaml
db:
  volumes:
    - ./postgres.conf:/etc/postgresql/postgresql.conf
  command: postgres -c config_file=/etc/postgresql/postgresql.conf
```

#### LiteLLM Caching

Enable Redis caching in `config.yaml`:

```yaml
litellm_settings:
  cache: true
  cache_params:
    type: "redis"
    host: "redis"
    port: 6379
```

Add Redis service to `docker-compose.yml`:

```yaml
redis:
  image: redis:7-alpine
  container_name: llmaven_redis
  ports:
    - "6379:6379"
  volumes:
    - redis_data:/data
  networks:
    - llmaven-network
```

### Integration with LLMaven Applications

#### Environment Variables for Applications

When running LLMaven applications that need to connect to these services (with
`LITELLM_MASTER_KEY` exported as in
[LiteLLM Configuration](#litellm-configuration)):

```bash
# LiteLLM Proxy
export LITELLM_API_BASE=http://localhost:4000
export LITELLM_API_KEY="$LITELLM_MASTER_KEY"

# MLflow Tracking
export MLFLOW_TRACKING_URI=http://localhost:8080

# Azurite Blob Storage (host endpoint, well-known Azurite account key)
export AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
```

#### Using with Jupyter Notebooks

```python
import os

# Configure environment
os.environ['LITELLM_API_BASE'] = 'http://localhost:4000'
os.environ['LITELLM_API_KEY'] = os.environ['LITELLM_MASTER_KEY']
os.environ['MLFLOW_TRACKING_URI'] = 'http://localhost:8080'

from openai import OpenAI
import mlflow

# Use LiteLLM
client = OpenAI(
    base_url=os.environ['LITELLM_API_BASE'],
    api_key=os.environ['LITELLM_API_KEY']
)

# Track with MLflow
mlflow.set_tracking_uri(os.environ['MLFLOW_TRACKING_URI'])
with mlflow.start_run():
    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[{"role": "user", "content": "Hello!"}]
    )
    mlflow.log_param("model", "gpt-5-mini")
    mlflow.log_metric("response_length", len(response.choices[0].message.content))
```

## Resources

### Official Documentation

- **LiteLLM**: https://docs.litellm.ai/
  - [Proxy Server](https://docs.litellm.ai/docs/proxy/quick_start)
  - [Supported Models](https://docs.litellm.ai/docs/providers)
  - [Logging & Observability](https://docs.litellm.ai/docs/proxy/logging)

- **MLflow**: https://mlflow.org/docs/latest/index.html
  - [Tracking](https://mlflow.org/docs/latest/tracking.html)
  - [Models](https://mlflow.org/docs/latest/models.html)
  - [Model Registry](https://mlflow.org/docs/latest/model-registry.html)

- **Azurite**:
  https://learn.microsoft.com/en-us/azure/storage/common/storage-use-azurite
  - [Connect to Azurite](https://learn.microsoft.com/en-us/azure/storage/common/storage-connect-azurite?tabs=blob-storage)

- **PostgreSQL**: https://www.postgresql.org/docs/16/
  - [Docker Official Images](https://hub.docker.com/_/postgres)
  - [Performance Tuning](https://wiki.postgresql.org/wiki/Performance_Optimization)

### LLMaven Project

- **Main Repository**: https://github.com/uw-ssec/llmaven
- **Pixi Documentation**: https://pixi.sh/latest/
- **Issue Tracker**: https://github.com/uw-ssec/llmaven/issues

### Community and Support

- **LiteLLM Discord**: https://discord.com/invite/wuPM9dRgDw
- **MLflow Slack**: https://mlflow.org/slack

---

**Note**: This documentation is for the LLMaven Docker infrastructure. For
information about the main LLMaven application and features, see the
[root README](../README.md).
