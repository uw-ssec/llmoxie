# Infrastructure Guide

LLMaven uses Pulumi for Azure infrastructure deployment.

## Prerequisites

- Pulumi CLI installed
- Azure CLI authenticated (`az login`)
- Configuration file: `llmaven-config.yaml` (gitignored)

---

## Infrastructure Commands

### Initialize

```bash
llmaven infra init
```

Creates the initial configuration file.

### Validate

```bash
llmaven infra validate --strict
```

Validates configuration before deployment.

### Preview Changes

```bash
llmaven infra deploy --preview
```

Shows what will be deployed without making changes.

### Deploy

```bash
llmaven infra deploy --yes
```

Deploys all infrastructure resources.

### Check Status

```bash
llmaven infra status
```

Shows current deployment status.

### Destroy

```bash
llmaven infra destroy --yes
```

Tears down all infrastructure (use with caution).

---

## Key Files

| Path                          | Purpose                                   |
| ----------------------------- | ----------------------------------------- |
| `src/llmaven/infrastructure/` | Pulumi Azure resource definitions         |
| `src/llmaven/deployment/`     | Deployment utilities                      |
| `llmaven-config.yaml`         | Infrastructure configuration (gitignored) |

---

## Deployed Resources

The infrastructure includes:

- Azure Container Apps (API hosting)
- Azure Blob Storage (document storage)
- Azure Key Vault (secrets management)
- Qdrant vector database instance
