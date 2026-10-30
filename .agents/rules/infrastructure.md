# Infrastructure (Pulumi on Azure)

**Load when:** working on `src/llmaven/infrastructure/`,
`src/llmaven/infrastructure_backup/` or `src/llmaven/deployment/`, or running
any `llmaven infra` / `llmaven backup-infra` command.

## Safety First

`deploy`, `destroy`, `refresh`, `cancel` and `backup-infra deploy` change real
Azure resources or Pulumi state. **Get explicit human approval before running
any of them**, including `deploy --preview`. `--preview` skips the Pulumi
update, but first `initialize_azure_infra()` (`deployment/deploy.py`) creates
the resource group and Pulumi state storage if the config doesn't name existing
ones. `deploy --expect-no-changes` refuses to run when those aren't set.

## Prerequisites

- Pulumi CLI: `pixi run -e llmaven install-pulumi`
- Azure CLI authenticated: `az login`
- A config file, `llmaven-config.yaml` by default. It is gitignored and holds
  secrets; never commit it. Real environment configs live in the private
  `uw-ssec/llmaven-deploy` repository.

## Commands

Run them as `pixi run -e llmaven llmaven infra <command>`. `--config/-c` selects
the config file.

| Command    | What it does                                                                             |
| ---------- | ---------------------------------------------------------------------------------------- |
| `init`     | Writes a config with defaults (`-e dev\|staging\|prod`, `-o <path>`, `--no-interactive`) |
| `validate` | Checks the config (`--strict` fails on warnings, `--env-file` for secrets)               |
| `deploy`   | Deploys (`--preview`, `--yes`, `--expect-no-changes`, `--env-file`)                      |
| `status`   | Shows the deployed stack's status                                                        |
| `refresh`  | Refreshes Pulumi state from Azure (`--yes`)                                              |
| `cancel`   | Cancels a stuck Pulumi update                                                            |
| `destroy`  | Tears down **all** resources (`--yes`)                                                   |
| `extract`  | Downloads LiteLLM spend logs to a zip (`--source`, `--out`)                              |

The separate backup stack has its own commands: `llmaven backup-infra deploy`
and `llmaven backup-infra output`.

## Key Files

| Path                                    | Purpose                                      |
| --------------------------------------- | -------------------------------------------- |
| `src/llmaven/infrastructure/main.py`    | Pulumi program for the main stack            |
| `src/llmaven/infrastructure/resources/` | Container apps, database, Key Vault, storage |
| `src/llmaven/infrastructure/config/`    | Config models loaded from the YAML           |
| `src/llmaven/infrastructure_backup/`    | Pulumi program for the backup stack          |
| `src/llmaven/deployment/`               | `init`, `validate`, `deploy` logic           |

## Deployed Resources

- Resource group, virtual network and subnets, private DNS zone
- Container Apps managed environment, with the LiteLLM and MLflow container apps
  and the scheduled backup job
- Azure Database for PostgreSQL flexible server and its databases
- Storage account and blob containers, with lifecycle management
- Key Vault for secrets, plus a user-assigned managed identity
- Log Analytics workspace

The container images come from GHCR. See
[repository-map.md](repository-map.md#deployment) for how they're built.
