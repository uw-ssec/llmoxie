# Infrastructure Setup

This directory contains Pulumi infrastructure-as-code for setting up Azure resources needed by the LLMaven proxy service.

## Prerequisites

- Azure CLI installed and logged in (`az login`)
- Python 3.11+
- Pulumi CLI `curl -fsSL https://get.pulumi.com | sh`

## Manual Setup

```bash
# Start the pixi shell in the infra environment
pixi shell -e infra

cd infra

# Login to Pulumi (local backend)
pulumi login --local

# Create or select stack
pulumi stack init dev
# or
pulumi stack select dev

# Deploy
pulumi up
```

## Exporting Environment Variables

After deployment, you can export the credentials to your shell:

```bash
cd infra
source <(pulumi stack output envVars)
```

## Destroying Resources

To tear down all Azure resources:

```bash
cd infra
pulumi destroy
```

**Warning**: This will delete the storage account and all data including user keys!
