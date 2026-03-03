# Section 1: CLI Walkthrough

**Timing:** ~10 minutes
**Prerequisites:** pixi installed, `llmaven` environment available (`pixi install -e llmaven`)

## Overview

LLMaven provides a command-line interface built with [Typer](https://typer.tiangolo.com/) and [Rich](https://github.com/Textualize/rich) for managing infrastructure deployments. The CLI is the entry point defined in `pyproject.toml` (`llmaven = "llmaven.cli:main"`).

This section demonstrates the core CLI commands: version checking, help output, config generation, and config validation.

---

## Step 1: Check the version

```bash
pixi run -e llmaven llmaven version
```

**Expected output:**
```
LLMaven version 0.1.0
```

> **Presenter note:** The version comes from `pyproject.toml`. The entry point at `pyproject.toml:71` maps the `llmaven` command to `llmaven.cli:main`.

---

## Step 2: Explore top-level commands

```bash
pixi run -e llmaven llmaven --help
```

**Expected output:**
```
Usage: llmaven [OPTIONS] COMMAND [ARGS]...

  LLMaven CLI - AI Infrastructure Management Tool

Options:
  --help  Show this message and exit.

Commands:
  agentic  Agentic RAG system commands
  infra    Infrastructure management commands
  serve    Start the LLMaven API server
  ui       Start the LLMaven Streamlit UI
  version  Show LLMaven version
```

> **Presenter note:** Point out the `infra` subgroup — that's the focus of this demo. The `serve`, `ui`, and `agentic` commands are for the application layer (out of scope today).

---

## Step 3: Explore infrastructure subcommands

```bash
pixi run -e llmaven llmaven infra --help
```

**Expected output:**
```
Usage: llmaven infra [OPTIONS] COMMAND [ARGS]...

  Infrastructure management commands

Options:
  --help  Show this message and exit.

Commands:
  cancel    Cancel any pending infrastructure operations
  deploy    Deploy LLMaven infrastructure to Azure
  destroy   Destroy LLMaven infrastructure
  init      Initialize LLMaven configuration
  refresh   Refresh infrastructure state from Azure
  status    Show current infrastructure status
  validate  Validate LLMaven configuration
```

> **Presenter note:** We'll use `init`, `validate`, and `deploy --preview` today. The full lifecycle (deploy, status, refresh, destroy, cancel) supports day-2 operations.

---

## Step 4: Generate a configuration file

```bash
pixi run -e llmaven llmaven infra init --environment dev --output demo/generated-config.yaml
```

**Expected output:**
```
Configuration generated successfully!
Output: demo/generated-config.yaml

Next steps:
  1. Review and edit the configuration file
  2. Set required secrets as environment variables
  3. Run 'llmaven infra validate' to check your configuration
  4. Run 'llmaven infra deploy' to provision resources
```

> **Presenter note:** Walk through the generated YAML structure:
> - `project:` — name, environment, location, passphrase setting
> - `azure:` — subscription_id, tenant_id (auto-detected from `az account show` if authenticated, otherwise placeholders)
> - `networking:` — VNet address space, subnets for container apps and postgres
> - `database:` — PostgreSQL SKU, storage, the same 3 databases as the Docker stack
> - `storage:` — account tier, replication, ADLS Gen2, the same 2 containers as MinIO buckets
> - `container_registry:` — GHCR (not ACR — saves cost!)
> - `monitoring:` — Log Analytics, Application Insights
> - `mlflow:` / `litellm:` — Container App configurations with Key Vault secret references

---

## Step 5: Validate the configuration

```bash
pixi run -e llmaven llmaven infra validate --config demo/llmaven-config.yaml --skip-secrets
```

**Expected output:**
```
Validating configuration...

  1. Configuration syntax .............. PASSED
  2. Security check .................... PASSED
  3. Azure prerequisites ............... [may fail without auth]
  4. Secrets ........................... SKIPPED (--skip-secrets)
  5. Cost estimation ................... ~$50-100/month (dev)
  6. Production checks ................. N/A (dev environment)

Validation complete.
```

> **Presenter note:**
> - Explain the 6 validation checks and what each one does
> - `--skip-secrets` skips checking for `LLMAVEN_SECRETS_*` environment variables — useful when you don't have secrets configured
> - The cost estimate shows a breakdown by resource type (PostgreSQL, storage, container apps, monitoring)
> - If Azure CLI is not authenticated, the Azure prerequisites check will fail with a warning — that's OK, explain what it would check (subscription access, provider registration, etc.)

**Fallback:** If Azure CLI is not authenticated, some checks will show warnings. This is expected in a demo environment without Azure access.

---

## Cleanup

Remove the file generated in Step 4:

```bash
rm -f demo/generated-config.yaml
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `pixi: command not found` | Install pixi: `curl -fsSL https://pixi.sh/install.sh \| bash` |
| `llmaven: command not found` | Run `pixi install -e llmaven` to set up the environment |
| Import errors | Ensure you're using the `llmaven` pixi environment: `pixi run -e llmaven ...` |
| Validation crashes | Check that `demo/llmaven-config.yaml` exists and has valid YAML syntax |
