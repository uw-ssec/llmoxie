# Section 5: Logging & Observability

**Timing:** ~10 minutes **Prerequisites:** Docker services running (from Section
2), MLflow callbacks enabled in `docker/config.yaml`

## Overview

Walk through the logging and observability capabilities of the LLMaven stack:
container logs, LiteLLM spend tracking, and MLflow experiment tracking for LLM
interactions.

> **Tip:** This section can also be woven throughout the demo as a "second
> terminal" showing live logs alongside other actions. The guide covers both
> standalone presentation and integrated use.

### Recommended terminal setup

```
┌─────────────────────────┬─────────────────────────┐
│  Terminal 1              │  Terminal 2              │
│  Demo commands           │  pixi run -e demo     │
│  (Sections 1-4)          │  logs                    │
│                          │  (live service logs)     │
└─────────────────────────┴─────────────────────────┘
```

---

## Part 1: Container Logs During Startup (~3 min)

### View all logs

```bash
pixi run -e demo logs
# or from docker/ directory:
# docker compose logs -f --tail=100
```

### What to point out

As you scroll through the logs, highlight:

1. **PostgreSQL startup:**
   - Database initialization and `create_service_dbs.sql` execution
   - Creating `mlflow_db` and `litellm_db` databases
   - `database system is ready to accept connections`

2. **MinIO startup:**
   - Server initialization and data directory setup
   - `createbuckets` init container creating the `mlflow` and `llmaven` buckets

3. **MLflow startup:**
   - Waits for PostgreSQL and MinIO health checks
   - Connects to PostgreSQL backend store
   - `Serving on http://0.0.0.0:8080`

4. **LiteLLM startup:**
   - Connects to PostgreSQL (`litellm_db`) for spend tracking
   - Connects to MLflow for logging callbacks
   - Loads model configuration from `config.yaml`
   - `LiteLLM Proxy started on 0.0.0.0:4000`

### Per-service logs

Filter to individual services:

```bash
docker compose logs -f litellm    # LiteLLM only
docker compose logs -f mlflow     # MLflow only
docker compose logs -f db         # PostgreSQL only
docker compose logs -f minio      # MinIO only
```

---

## Part 2: LiteLLM Observability (~3 min)

### LiteLLM UI

Open http://localhost:4000 in a browser.

**What to show:**

- Model list — all registered models from `docker/config.yaml`
- The proxy dashboard with request counts and latency (if available)

### API documentation

Open http://localhost:4000/docs — the OpenAI-compatible API spec.

> **Presenter note:** LiteLLM exposes the same API as OpenAI, so any OpenAI SDK
> client can use it by pointing to `http://localhost:4000`.

### LiteLLM configuration

Show the relevant settings in `docker/config.yaml`:

```yaml
# Every LLM interaction is logged to MLflow
litellm_settings:
  success_callback: ["mlflow"]
  failure_callback: ["mlflow"]

# Spend logs and model config stored in PostgreSQL
general_settings:
  store_prompts_in_spend_logs: true
  store_model_in_db: true
```

### Test request (optional — requires API keys)

If LLM provider API keys are configured in `docker/.env`, make a test request:

```bash
curl http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-1234" \
  -d '{
    "model": "gpt-5-mini",
    "messages": [{"role": "user", "content": "Hello from the NAIRR demo!"}]
  }'
```

> **Presenter note:** The `sk-1234` is the `LITELLM_MASTER_KEY` from
> `docker/.env`. Watch the LiteLLM logs (Terminal 2) to see the request being
> processed and logged.

If API keys are not configured, explain what would happen:

- LiteLLM receives the request and routes to the correct provider
- The request and response are logged to PostgreSQL (spend logs)
- The interaction is logged to MLflow as an experiment run

---

## Part 3: MLflow Experiment Tracking (~3 min)

### Open MLflow UI

Open http://localhost:8080 in a browser.

**What to show:**

- The **"Default"** experiment (or the experiment name from
  `MLFLOW_EXPERIMENT_NAME`)
- If a test request was made in Part 2 and MLflow callbacks are working:
  - Click on the logged run
  - Show metrics: model name, token counts (prompt + completion), latency,
    estimated cost
  - Show the request/response payload stored as an artifact
- If no test request was made:
  - Explain what would appear: each LLM interaction logged as a run with metrics
    and artifacts

### How it works

The flow:

```
User request → LiteLLM Proxy → LLM Provider (Azure/Anthropic/Bedrock)
                    │
                    ├── success_callback: ["mlflow"]
                    │   → MLflow logs: model, tokens, latency, cost, request/response
                    │
                    └── general_settings.store_prompts_in_spend_logs: true
                        → PostgreSQL logs: full prompt, model, timestamp
```

> **Presenter note:** Explain how `success_callback: ["mlflow"]` and
> `failure_callback: ["mlflow"]` in `docker/config.yaml` drive this. Every
> successful LLM call creates an MLflow run. Failed calls are also logged (with
> error info) for debugging.

---

## Part 4: CLI Verbose Output (~1 min)

The CLI itself provides detailed output during validation:

```bash
pixi run -e demo llmaven infra validate --config demo/llmaven-config.yaml --skip-secrets
```

Each validation check prints its status, timing, and any warnings — see the
output from [Section 1](01_cli_demo.md) for details.

---

## Troubleshooting

| Issue                                      | Solution                                                                                                                       |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------ |
| MLflow not showing runs after test request | Verify `litellm_settings` callbacks are uncommented in `docker/config.yaml`. Restart LiteLLM: `docker compose restart litellm` |
| LiteLLM logs showing API errors            | Check API keys in `docker/.env`. Ensure the model name in the request matches one in `config.yaml`                             |
| MLflow UI not loading                      | Check `pixi run -e demo status` — MLflow may still be starting. Wait for health check to pass                                  |
| No data in MLflow                          | The test request in Part 2 is required to generate data. Without API keys, MLflow will be empty                                |
| Logs too verbose                           | Filter to specific services: `docker compose logs -f litellm`                                                                  |
