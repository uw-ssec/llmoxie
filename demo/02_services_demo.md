# Section 2: Services Architecture

**Timing:** ~20 minutes **Prerequisites:** Docker Desktop running, `docker/.env`
configured with API keys

## Overview

LLMaven uses a Docker Compose stack as the local development environment. This
stack mirrors the Azure cloud deployment — the same services, databases, and
storage buckets that are provisioned in the cloud run locally for development
and testing.

---

## Part 1: Architecture Overview (~5 min)

### Network Topology

All services communicate over a shared Docker bridge network:

```
                    llmaven-network (bridge)
    ┌──────────────────────────────────────────────────┐
    │                                                  │
    │  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
    │  │PostgreSQL │  │  MinIO   │  │  Qdrant  │       │
    │  │  :5432    │  │:9000/9001│  │  :6333   │       │
    │  └────┬─────┘  └────┬─────┘  └──────────┘       │
    │       │              │                           │
    │  ┌────┴──────────────┴───┐                       │
    │  │    createbuckets      │ (init container)      │
    │  └───────────┬───────────┘                       │
    │              │                                   │
    │  ┌───────────┴───────────┐                       │
    │  │       MLflow          │                       │
    │  │       :8080           │                       │
    │  └───────────┬───────────┘                       │
    │              │                                   │
    │  ┌───────────┴───────────┐                       │
    │  │      LiteLLM          │                       │
    │  │       :4000           │                       │
    │  └───────────────────────┘                       │
    └──────────────────────────────────────────────────┘
```

### Service Table

| Service           | Image                     | Port(s)                    | Role                                   |
| ----------------- | ------------------------- | -------------------------- | -------------------------------------- |
| **PostgreSQL**    | `postgres:16`             | 5432                       | Relational database (3 databases)      |
| **MinIO**         | `minio/minio:latest`      | 9000 (API), 9001 (Console) | S3-compatible object storage           |
| **Qdrant**        | `qdrant/qdrant:latest`    | 6333                       | Vector database for semantic search    |
| **createbuckets** | `quay.io/minio/mc:latest` | —                          | Init container: creates MinIO buckets  |
| **MLflow**        | Custom (built locally)    | 8080                       | Experiment tracking & artifact storage |
| **LiteLLM**       | Custom (built locally)    | 4000                       | AI gateway (OpenAI-compatible proxy)   |

### Startup Dependency Order

```
Phase 1 (parallel):  PostgreSQL, MinIO, Qdrant
         │
Phase 2: createbuckets (waits for MinIO)
         │
Phase 3: MLflow (waits for PostgreSQL healthy + createbuckets done)
         │
Phase 4: LiteLLM (waits for PostgreSQL healthy + MLflow healthy)
```

### Local to Azure Mapping

| Local (Docker)        | Azure Resource                                |
| --------------------- | --------------------------------------------- |
| PostgreSQL container  | Azure Database for PostgreSQL Flexible Server |
| MinIO                 | Azure Storage Account (Blob/ADLS Gen2)        |
| MLflow container      | Azure Container App                           |
| LiteLLM container     | Azure Container App                           |
| Qdrant container      | Azure Container App (or managed service)      |
| Docker bridge network | Azure VNet with subnets                       |

---

## Part 2: Configuration Walkthrough (~5 min)

### Environment variables (`docker/.env.example`)

```bash
# View the template
cat docker/.env.example
```

> **Presenter note:** Walk through the sections:
>
> - **Postgres:** host, database, user, password, port
> - **MinIO:** host, port, root user/password, S3 endpoint URL
> - **MLflow:** host, port, backend store URI (PostgreSQL), artifact root
>   (S3/MinIO), AWS credentials for MinIO
> - **LiteLLM:** database URL, MLflow tracking URI, master key, LLM provider API
>   keys (Azure OpenAI, Anthropic)

### LiteLLM model routing (`docker/config.yaml`)

```bash
# View the LiteLLM configuration
cat docker/config.yaml
```

> **Presenter note:** Highlight:
>
> - The `model_list:` defines available models — Azure OpenAI (gpt-5-mini,
>   gpt-oss-120b, embed-v-4-0, kimi-k2-thinking), Anthropic (claude-sonnet-4-6,
>   claude-haiku-4-5, claude-opus-4-6), and Bedrock
> - `litellm_settings:` with `success_callback: ["mlflow"]` and
>   `failure_callback: ["mlflow"]` — every LLM interaction is logged to MLflow
> - `general_settings:` stores prompts in spend logs and model config in the
>   database

### Database initialization (`docker/create_service_dbs.sql`)

```bash
# View the SQL init script
cat docker/create_service_dbs.sql
```

> **Presenter note:** PostgreSQL starts with the `llmaven` database (from env
> var). This init script creates two additional databases: `mlflow_db` and
> `litellm_db`. All three databases are needed by the stack.

### Docker Compose (`docker/docker-compose.yml`)

```bash
# View the compose file
cat docker/docker-compose.yml
```

> **Presenter note:** Highlight:
>
> - `depends_on` with `condition: service_healthy` ensures proper startup
>   ordering
> - Health checks on each service (PostgreSQL: `pg_isready`, MinIO: curl health
>   endpoint, MLflow: Python urllib, LiteLLM: wget)
> - Named volumes for PostgreSQL and MinIO data persistence
> - The `createbuckets` init container uses
>   `condition: service_completed_successfully`

---

## Part 3: Service-by-Service Walkthrough (~5 min)

### LiteLLM Proxy (port 4000)

The unified AI gateway. Provides an OpenAI-compatible API endpoint that routes
requests to multiple LLM providers based on the model name. Handles
authentication, rate limiting, cost tracking, and logging.

- Config: `docker/config.yaml` defines the model routing table
- Database: Uses `litellm_db` in PostgreSQL for spend tracking and model config
- Logging: Every request/response is logged to MLflow via the
  `success_callback`/`failure_callback`

### MLflow (port 8080)

Experiment tracking and artifact storage. Stores run metadata in PostgreSQL
(`mlflow_db`) and artifacts (model files, request/response payloads) in MinIO
via S3-compatible API.

- Backend store: `postgresql://...@db:5432/mlflow_db`
- Artifact store: `s3://mlflow/` (MinIO)
- The MLflow callbacks in LiteLLM automatically log every LLM interaction as an
  MLflow run

### PostgreSQL (port 5432)

Three databases created at startup:

1. `llmaven` — application database
2. `mlflow_db` — MLflow backend store (experiments, runs, metrics)
3. `litellm_db` — LiteLLM spend logs, model config, API keys

The `create_service_dbs.sql` init script runs on first container start.

### MinIO (ports 9000/9001)

S3-compatible object storage. The `createbuckets` init container creates two
buckets:

1. `mlflow` — MLflow artifact storage
2. `llmaven` — application storage

Console UI at port 9001 (login: `minioadmin` / `minioadmin`).

### Qdrant (port 6333)

Vector database for semantic search. Used by the Agentic RAG system (not covered
in this demo). Provides a dashboard at `/dashboard` and health endpoint at
`/health`.

---

## Part 4: Live Startup and Verification (~5 min)

### Start services

If not already running:

```bash
pixi run -e llmaven up
```

Or check if already running:

```bash
pixi run -e llmaven status
```

**Expected output (all healthy):**

```
NAME                IMAGE                    STATUS                   PORTS
llmaven_db          postgres:16              Up (healthy)             0.0.0.0:5432->5432/tcp
llmaven_minio       minio/minio:latest       Up (healthy)             0.0.0.0:9000-9001->9000-9001/tcp
llmaven_qdrant      qdrant/qdrant:latest      Up (healthy)             0.0.0.0:6333->6333/tcp
llmaven_mlflow      docker-mlflow             Up (healthy)             0.0.0.0:8080->8080/tcp
llmaven_litellm     docker-litellm            Up (healthy)             0.0.0.0:4000->4000/tcp
```

### Health checks

```bash
curl -s http://localhost:4000/health/liveliness  # LiteLLM
curl -s http://localhost:8080/health              # MLflow
curl -s http://localhost:6333/health              # Qdrant
curl -s http://localhost:9000/minio/health/live   # MinIO
```

### Web UIs

Open each in a browser (or Codespaces will auto-forward):

| Service          | URL                             | What to show                                                  |
| ---------------- | ------------------------------- | ------------------------------------------------------------- |
| LiteLLM          | http://localhost:4000           | Model list, proxy dashboard                                   |
| LiteLLM API docs | http://localhost:4000/docs      | OpenAI-compatible API spec                                    |
| MLflow           | http://localhost:8080           | Experiment tracking UI                                        |
| MinIO Console    | http://localhost:9001           | `mlflow` and `llmaven` buckets (login: minioadmin/minioadmin) |
| Qdrant           | http://localhost:6333/dashboard | Vector DB dashboard                                           |

### Live logs

```bash
pixi run -e llmaven logs
# or for specific services:
# docker compose logs -f litellm
# docker compose logs -f mlflow
```

> **Presenter note:** Point out inter-service communication in the logs —
> LiteLLM connecting to PostgreSQL, MLflow writing artifacts to MinIO, etc.

---

## Connecting the Dots

These local Docker services map directly to the Azure resources deployed in
[Section 3](03_infra_demo.md). The configuration structure (databases, storage
containers, service endpoints) is intentionally identical so that applications
work the same locally and in the cloud.

---

## Troubleshooting

| Issue                            | Solution                                                                                         |
| -------------------------------- | ------------------------------------------------------------------------------------------------ |
| Port conflicts                   | Stop conflicting services or change ports in `docker/.env`                                       |
| Missing `.env`                   | Run `cp docker/.env.example docker/.env` and edit with your API keys                             |
| Services failing to start        | Check `docker compose logs <service>` for errors. Common: missing env vars, PostgreSQL not ready |
| `createbuckets` keeps restarting | MinIO may not be healthy yet. Wait 30 seconds and check again                                    |
| MLflow not starting              | Ensure PostgreSQL and MinIO are healthy first (check `pixi run -e llmaven status`)               |
| LiteLLM not starting             | Ensure PostgreSQL and MLflow are healthy. Check API key env vars in `docker/.env`                |
