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

# Operator reports
llmaven ops spend-report --start 2026-01-01 --end 2026-01-07  # Spend by key/user/model/team vs prior window

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
├── Action group + alert rules + budget (only for alerts in monitoring.alerts.enabled_alerts)
├── Azure AI Foundry account + model deployments (only with foundry.enabled)
└── Container Apps Environment
    ├── MLflow Container App (managed identity → Key Vault)
    └── LiteLLM Container App (managed identity → Key Vault)
```

#### Alerting

Alerts are email-only and created only for names listed in
`monitoring.alerts.enabled_alerts`. One action group (`alerts-action-group`)
emails every address in `monitoring.alerts.email_receivers`, which is required
when any alert is enabled. An alert whose target isn't deployed (for example
`backup_job_failures` with the backup job disabled) is skipped with a warning.

| Alert                 | Watches                                                       | Default threshold                      |
| --------------------- | ------------------------------------------------------------- | -------------------------------------- |
| `gateway_errors`      | LiteLLM 5xx responses                                         | more than 10 in 15 minutes             |
| `gateway_latency`     | LiteLLM average response time                                 | above 300000 ms over 15 minutes        |
| `replica_restarts`    | Restarts of a single LiteLLM (and MLflow, if enabled) replica | more than 3 since the replica started  |
| `db_storage`          | PostgreSQL storage used                                       | above 80%                              |
| `db_cpu`              | PostgreSQL CPU                                                | above 85% over 30 minutes              |
| `backup_job_failures` | Failed backup job executions (Log Analytics query)            | any failure                            |
| `llm_spend`           | Model-provider spend logged by LiteLLM (Log Analytics)        | more than $50 per day                  |
| `cloud_budget`        | Azure cost for the resource group, actual monthly spend       | notifies at 80% and 100% of the budget |

Thresholds are absolute values, not baselines. Override them under
`monitoring.alerts` in your config. `cloud_budget.monthly_usd` defaults to 200
(dev), 300 (staging) and 500 (prod); these are placeholders, so set your own.

`replica_restarts` watches each replica separately. Azure's `RestartCount` is
the cumulative number of restarts of one replica since it was created, so the
threshold means "a single replica has restarted more than `max_count` times
since it started", not "this many restarts across the app in the window".

`backup_job_failures` fires on an execution that timed out or used up its
retries, and a run that recovers on retry doesn't count. It reads Log Analytics
hourly over a two-hour window, so an email can arrive up to an hour or so after
the failure. `cloud_budget.notify_at_percent` takes at most five distinct
values, which is Azure's limit.

`cloud_budget` is scoped to the whole resource group, with no tag filter: it
measures every resource in the group, including ones this stack didn't create.
The default resource group name is `rg-{project}-{location}` and contains no
environment, so **dev, staging and prod in the same region share one resource
group and therefore one budget** — each environment's `monthly_usd` is then
compared against the combined spend of all of them. Set a distinct
`azure.resource_group` per environment (for example `rg-llmaven-eastus-prod`) if
you want per-environment budgets.

Per-environment defaults: dev enables no alerts (`[]`); staging and prod enable
all eight. The generated `email_receivers` entry is the placeholder
`ops@example.org`; replace it before deploying. `llmaven infra validate` warns
(and fails under `--strict`) if a receiver still uses a placeholder domain.

`monitoring.daily_data_cap_gb` is applied to the Log Analytics workspace. Once
the daily cap is reached the workspace stops ingesting, so the log-based
`backup_job_failures` and `llm_spend` alerts go blind until the cap resets at
the start of the next daily cycle. `monitoring.enable_application_insights` is
deprecated and does nothing.

The Azure budget covers Azure charges only. `llm_spend` covers model-provider
spend (for example Anthropic) recorded by LiteLLM. Both are best effort:
`llm_spend` reads console log lines that can be dropped or delayed, so it can
under-report. The Postgres spend logs are the source of truth.

`llm_spend` is set under `monitoring.alerts.llm_spend`: `max_usd_per_hour`
(default `null`) and `max_usd_per_day` (default `50`). Set at least one; both
`null` is invalid. Each threshold creates its own rule (`alert-llm-spend-hourly`
and `alert-llm-spend-daily`), evaluated hourly over a one-hour or one-day
window. The alert needs the LiteLLM app and is skipped with a warning when
LiteLLM is disabled. It reads a `LLMOXIE_SPEND` line that the LiteLLM callback
`spend_logger.proxy_handler_instance` prints for each successful request.
`llmaven infra validate` and the deploy warn, but don't fail, when `llm_spend`
is enabled and the LiteLLM config has no `spend_logger.` callback.

Rolling out the spend logger: running gateways only pick it up on a new
revision. If you pin `litellm.refresh_trigger`, change it; if you set
`litellm.revision_suffix`, change that. Otherwise the deploy timestamp already
forces a new revision.

#### Azure AI Foundry models (optional)

With `foundry.enabled: true` the stack creates an `AIServices` account and one
deployment per `foundry.deployments` entry, then writes `azure-api-base`,
`azure-api-key` and `azure-api-version` to Key Vault. Don't set the matching
`LLMAVEN_SECRETS_AZURE_API_*` variables; validate and deploy fail if you do.
Every `azure/<name>` model in the LiteLLM config must name a deployment.

The account's network ACL denies everything except the Container Apps
environment subnet (service endpoint plus one virtual network rule, no IP rules,
no trusted-service bypass). Every workload in that environment (LiteLLM, MLflow,
the backup job) can reach it; nothing outside the subnet can, including your
laptop. Quota and regional model availability are checked by Azure at deploy
time, not by `infra validate`.

With `foundry.enabled: false` (the default) nothing changes: bring your own
endpoint through the `azure-api-*` secrets.

### Restricting LiteLLM admin routes (optional Traefik proxy)

LiteLLM serves the inference API and its admin surface (UI, key, team, model and
MCP management) on one port, and Container Apps ingress can only filter by IP
for the whole app. Setting `litellm.proxy.enabled` adds a Traefik sidecar to the
LiteLLM app. Ingress sends every hostname (the platform FQDN and custom domains)
to Traefik, and LiteLLM then listens on `127.0.0.1` only.

- **Public:** exact inference paths (`/v1/chat/completions`, `/v1/messages`,
  `/v1/responses`, `/v1/embeddings`, `/v1/models`, … and their aliases; see
  `DEFAULT_PUBLIC_PATHS`), rate limited per client IP.
- **Health:** `/health/liveliness` and `/health/liveness`, public and not rate
  limited. The platform probes reach LiteLLM through these paths.
- **Everything else:** only from `admin_allowed_ips`. Leave the list empty and
  the admin surface is closed to everyone.

```yaml
litellm:
  cpu: 2
  memory: 4Gi # LiteLLM + proxy must total a valid pair, here 2.25 / 4.5Gi
  proxy:
    enabled: true
    admin_allowed_ips:
      - 203.0.113.0/24 # e.g. campus or VPN egress
    # trusted_proxy_ips defaults to networking.container_apps_subnet
    rate_limit_average: 50 # requests/s per client IP, per replica
    rate_limit_burst: 100
  # Optional, independent of the proxy: Container Apps IP rules for all paths
  # ip_security_restrictions:
  #   - name: campus
  #     ip_address_range: 198.51.100.0/24
  #     action: Allow
```

The client IP is the last `X-Forwarded-For` entry, which the Container Apps
Envoy appends. Traefik keeps that header only from `trusted_proxy_ips`. Rate
limits are counted per replica.

**Rollout (staging first).** Steps 3 and 4 are gates: don't enable the proxy in
prod until both pass.

1. Enable the proxy in the staging config with `log_forwarded_for: true`, then
   run `llmaven infra deploy --preview`. Expect only the LiteLLM app to change:
   a second container, a new secret and volume, ingress `targetPort` 8080 and
   HTTP probes.
2. Deploy staging. From an allowlisted network, check that the admin UI works.
   From any other network, check that `/ui` returns 403 and that
   `/v1/chat/completions` works, including with `stream: true`.
3. **Peer and client IP.** In Log Analytics (`ContainerAppConsoleLogs_CL`,
   container `traefik`), the JSON access log shows `ClientAddr`, which is the
   raw TCP peer (Envoy), and `request_X-Forwarded-For`, which is the chain. No
   other headers are logged, so Authorization is never recorded. `ClientAddr`
   must fall inside `trusted_proxy_ips`, and the last X-Forwarded-For entry must
   be your real client address. If admin requests get 403 from an allowlisted
   network, the peer range is wrong.
4. **No spoofing from inside the environment.** Another workload in the same
   environment can connect straight to the replica's proxy port, skipping Envoy.
   Get the LiteLLM replica IP
   (`az containerapp exec -n <litellm-app> -g <rg> --container traefik --command "ip -4 addr show eth0"`).
   Then, from a shell in a different app in the environment, such as MLflow
   (`az containerapp exec -n <mlflow-app> -g <rg> --command sh`), request
   `http://<replica-ip>:8080/ui` with `X-Forwarded-For: <an allowlisted IP>`.
   The request must be refused (403, connection refused or timeout). A 200 means
   workloads in `trusted_proxy_ips` can impersonate allowlisted clients. In that
   case, narrow `trusted_proxy_ips` to the Envoy peers observed in step 3, or
   keep the proxy out of prod.
5. Set `log_forwarded_for: false`, redeploy staging, then repeat for prod.

Any proxy change rolls a new LiteLLM revision. That includes revoking
`admin_allowed_ips`, toggling `log_forwarded_for` and narrowing
`trusted_proxy_ips`. A digest of the proxy config is part of the sidecar
template. A pinned `litellm.revision_suffix` gets `-p<digest>` appended, so keep
a pinned suffix to 54 characters or fewer. You don't need a new suffix for
proxy-only changes.

To roll back, set `litellm.proxy.enabled: false` and deploy. Ingress returns to
port 4000 and the template matches the pre-proxy one. If
`litellm.revision_suffix` is pinned, change it as part of the rollback: the
plain suffix already names the pre-proxy revision, and Container Apps rejects a
reused suffix.

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
