# Section 3: Infrastructure Deployment (Dry Run)

**Timing:** ~15 minutes **Prerequisites:** Azure CLI installed and authenticated
(`az login`), Pulumi installed (`pixi run -e demo install-pulumi`)

## Overview

LLMaven uses the
[Pulumi Automation API](https://www.pulumi.com/docs/using-pulumi/automation-api/)
to deploy infrastructure to Azure. This section walks through config generation,
validation, and a deployment preview — without actually provisioning any
resources.

The code lives in `src/llmaven/deployment/` (CLI wrappers) and
`src/llmaven/infrastructure/` (Pulumi program + config schema).

> **Note:** If Azure CLI is not authenticated, this section still works —
> pre-captured fallback output is included for all commands.

---

## Part 1: Generate Config (~3 min)

```bash
pixi run -e demo llmaven infra init --environment dev
```

> **Presenter note:** Explain the three environments (`dev`, `staging`, `prod`)
> and how defaults differ:
>
> - `dev`: Small SKUs, no HA, LRS replication, low retention
> - `staging`: Medium SKUs, optional HA, ZRS replication
> - `prod`: Large SKUs, HA enabled, GZRS replication, geo-redundant backup

Walk through the generated `llmaven-config.yaml` structure section by section:

| Section               | Purpose               | Key Fields                                                                  |
| --------------------- | --------------------- | --------------------------------------------------------------------------- |
| `project:`            | Deployment identity   | name, environment, location, passphrase                                     |
| `azure:`              | Subscription/tenant   | Auto-detected from `az account show`                                        |
| `networking:`         | VNet/subnets          | Address space, container apps subnet, postgres subnet (delegated)           |
| `database:`           | PostgreSQL config     | SKU, storage, 3 databases (same as Docker: llmaven, mlflow_db, litellm_db)  |
| `storage:`            | Storage account       | Tier, replication, ADLS Gen2, 2 containers (same as MinIO: mlflow, llmaven) |
| `container_registry:` | Image registry        | GHCR (not ACR — saves cost!)                                                |
| `monitoring:`         | Observability         | Log Analytics, Application Insights                                         |
| `mlflow:`             | MLflow Container App  | Image, CPU/memory, Key Vault secret refs                                    |
| `litellm:`            | LiteLLM Container App | Image, CPU/memory, Key Vault secret refs                                    |

> **Presenter note:** Highlight the local-to-Azure mapping — the Docker services
> from Section 2 map directly to these Azure resources.

---

## Part 2: Validate Config (~5 min)

```bash
pixi run -e demo llmaven infra validate --config llmaven-config.yaml
```

The validator runs 6 checks sequentially:

| #   | Check                   | What It Does                                                                  |
| --- | ----------------------- | ----------------------------------------------------------------------------- |
| 1   | **Config syntax**       | Pydantic schema validation — all required fields present, types correct       |
| 2   | **Security**            | Scans for hardcoded secrets (regex for `sk-*`, passwords, connection strings) |
| 3   | **Azure prerequisites** | Checks `az` CLI auth, subscription access, provider registration              |
| 4   | **Secrets**             | Verifies `LLMAVEN_SECRETS_*` environment variables are set                    |
| 5   | **Cost estimation**     | Estimates monthly cost by environment tier                                    |
| 6   | **Production checks**   | HA, private endpoints, geo-redundant backup (prod only)                       |

> **Presenter note:** Show the cost estimate breakdown — dev environment is
> ~$50-100/month. Point out how the validator catches issues before deployment.

### Pre-captured fallback output

If Azure CLI is not available, the output will look similar to:

```
Validating configuration...

  1. Configuration syntax .............. PASSED
     Schema validation passed. All fields valid.

  2. Security check .................... PASSED
     No hardcoded secrets found in configuration.

  3. Azure prerequisites ............... FAILED
     Azure CLI not authenticated. Run 'az login' to authenticate.
     (Expected in demo without Azure access)

  4. Secrets ........................... WARNING
     LLMAVEN_SECRETS_* environment variables not set.
     (Expected without deployment configuration)

  5. Cost estimation ................... INFO
     Estimated monthly cost (dev): ~$50-100/month
       - PostgreSQL (B1ms): ~$25/month
       - Storage (Standard LRS): ~$5/month
       - Container Apps: ~$15-50/month (usage-based)
       - Monitoring: ~$5-20/month

  6. Production checks ................. N/A
     Skipped for dev environment.
```

---

## Part 3: Deployment Preview (~5 min)

```bash
pixi run -e demo llmaven infra deploy --preview --config llmaven-config.yaml
```

> **Presenter note:** Explain that `--preview` runs Pulumi's `stack.preview()` —
> it shows what resources would be created without actually provisioning
> anything. No Azure resources are touched.

### Pre-captured fallback output

The expected resource tree:

```
Previewing update (llmaven-dev):

Resources:
  + 18 to create

  Type                                          Name
  pulumi:pulumi:Stack                           llmaven-llmaven-dev
  ├── azure-native:resources:ResourceGroup      rg-llmaven-dev
  ├── azure-native:network:VirtualNetwork       vnet-llmaven-dev
  │   ├── Subnet (container-apps)
  │   └── Subnet (postgres, delegated)
  ├── azure-native:keyvault:Vault               kv-llmaven-dev-westus2
  │   └── Secrets (auto-generated + user-provided)
  ├── azure-native:dbforpostgresql:Server       llmaven-dev-postgres
  │   ├── Database: llmaven
  │   ├── Database: mlflow_db
  │   └── Database: litellm_db
  ├── azure-native:storage:StorageAccount       llmavendevwestus2sa
  │   ├── BlobContainer: mlflow
  │   └── BlobContainer: llmaven
  ├── azure-native:operationalinsights:Workspace
  ├── azure-native:app:ManagedEnvironment
  └── azure-native:app:ContainerApp             litellm-dev
      └── ManagedIdentity → Key Vault access
```

> **Presenter note:**
>
> - Resource Group contains everything — easy to tear down
> - VNet with two subnets: one for Container Apps, one delegated for PostgreSQL
> - Key Vault stores all secrets (API keys, connection strings) — no hardcoded
>   secrets in container configs
> - PostgreSQL Flexible Server with the same 3 databases as Docker
> - Storage Account with the same 2 containers as MinIO buckets
> - Container Apps Environment with LiteLLM (MLflow currently `enabled: false`)
> - Managed Identity on the LiteLLM container app grants Key Vault access — no
>   passwords in environment variables

---

## Connecting the Dots

| Local Docker (Section 2)         | Azure Resource (this section)                 |
| -------------------------------- | --------------------------------------------- |
| `llmaven_db` (postgres:16)       | Azure Database for PostgreSQL Flexible Server |
| `llmaven_minio` (minio:latest)   | Azure Storage Account (ADLS Gen2)             |
| `llmaven_mlflow` (custom)        | Azure Container App (when enabled)            |
| `llmaven_litellm` (custom)       | Azure Container App                           |
| `llmaven_qdrant` (qdrant:latest) | Azure Container App (future)                  |
| Docker bridge network            | Azure VNet + subnets                          |
| `docker/.env` secrets            | Azure Key Vault                               |

The configuration structure is intentionally identical so applications work the
same locally and in the cloud.

---

## Troubleshooting

| Issue                       | Solution                                                                            |
| --------------------------- | ----------------------------------------------------------------------------------- |
| `az: command not found`     | Install Azure CLI: `curl -sL https://aka.ms/InstallAzureCLIDeb \| sudo bash`        |
| `pulumi: command not found` | Run `pixi run -e demo install-pulumi`                                               |
| Azure auth errors           | Run `az login` and select the correct subscription                                  |
| Config validation failures  | Check `demo/llmaven-config.yaml` syntax. Use `--skip-secrets` to skip secret checks |
| Preview hangs               | Pulumi may need to initialize state. Check network connectivity                     |
