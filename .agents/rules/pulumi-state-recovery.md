# Recovering Lost Pulumi State

**Load when:** reviewing or planning recovery after losing Pulumi state.

Recovery imports, deployments, and password updates change live resources or
state and require explicit human approval under
[infrastructure.md](infrastructure.md).

If the Pulumi state file is empty (e.g. after a failed deploy created a fresh
stack, or the blob was accidentally reset), all resources will show as `+create`
in the preview even though they exist in Azure. Fix this by importing each
resource before deploying.

### Symptoms

- `llmaven infra deploy --preview` shows 30+ resources to create
- The state blob exists at `.pulumi/stacks/llmaven/<stack-name>.json` but has 0
  resources
- Azure portal shows all resources already exist

### Verify the state is empty

```bash
az storage blob download \
  --account-name <pulumi_state_store> \
  --container-name pulumi-state \
  --name ".pulumi/stacks/llmaven/<stack-name>.json" \
  --file /tmp/state.json
python3 -c "import json; s=json.load(open('/tmp/state.json')); print(len(s['checkpoint']['latest']['resources']), 'resources')"
```

### Import resources

Set these env vars before every `pulumi import` call:

```bash
export PULUMI_BACKEND_URL="azblob://pulumi-state?storage_account=<pulumi_state_store>"
export AZURE_STORAGE_ACCOUNT="<pulumi_state_store>"
export AZURE_STORAGE_KEY=$(az storage account keys list \
  --resource-group <resource_group> \
  --account-name <pulumi_state_store> \
  --query "[0].value" -o tsv)
export PULUMI_CONFIG_PASSPHRASE=""
```

Then import each resource using its Pulumi logical name (from the code) and
Azure resource ID:

```bash
pixi run -e llmaven pulumi import <pulumi-type> <logical-name> <azure-resource-id> \
  --stack <stack-name> --yes
```

### Resource map for this deployment

Stack name: `{project.name}-{project.environment}` (e.g. `llmaven-iss-prod`)

| Pulumi type                                         | Logical name                             | Azure resource                                 |
| --------------------------------------------------- | ---------------------------------------- | ---------------------------------------------- |
| `azure-native:network:VirtualNetwork`               | `vnet`                                   | `vnet-{stack}`                                 |
| `azure-native:network:Subnet`                       | `container-apps-subnet`                  | `.../subnets/container-apps-subnet`            |
| `azure-native:network:Subnet`                       | `postgres-subnet`                        | `.../subnets/postgres-subnet`                  |
| `azure-native:privatedns:PrivateZone`               | `postgres-private-dns-zone-{env}`        | `{server}.private.postgres.database.azure.com` |
| `azure-native:privatedns:VirtualNetworkLink`        | `postgres-dns-vnet-link-{env}`           | `{server}-vnet-link`                           |
| `azure-native:keyvault:Vault`                       | `key-vault-{env}`                        | `kv-{project}-{env}-{region}`                  |
| `azure-native:storage:StorageAccount`               | `storage-account-{env}`                  | `{project}{env}...`                            |
| `azure-native:storage:BlobContainer`                | `blob-container-{name}-{env}`            | container name                                 |
| `azure-native:operationalinsights:Workspace`        | `log-analytics`                          | `log-{stack}`                                  |
| `azure-native:managedidentity:UserAssignedIdentity` | `managed-identity-{stack}-apps-identity` | `{stack}-apps-identity`                        |
| `azure-native:dbforpostgresql:Server`               | `postgres-server-{env}`                  | `{project}-postgres-{env}`                     |
| `azure-native:dbforpostgresql:Database`             | `postgres-db-{db}-{env}`                 | database name                                  |
| `azure-native:keyvault:Secret`                      | `kv-secret-{name}-{env}`                 | secret name in vault                           |
| `azure-native:app:ManagedEnvironment`               | `container-apps-env-{env}`               | `{project}-containerenv-{env}`                 |
| `azure-native:app:ContainerApp`                     | `container-app-{app}-{env}`              | `{app}-{env}`                                  |
| `azure-native:app:Job`                              | `backup-job-{env}`                       | `{project}-backup-{env}`                       |

### Known ignore_changes requirements

Some resources have properties that Azure populates automatically and that
Pulumi will incorrectly try to replace or update on import. These
`ignore_changes` entries are already in the code:

- **PostgreSQL Server** (`database.py`): `administratorLoginPassword`,
  `authConfig`, `availabilityZone`, `dataEncryption`, `highAvailability`,
  `maintenanceWindow`, `network`, `replica`, `replicationRole`, `storage`
- **ManagedEnvironment** (`container_apps.py`): `appLogsConfiguration`,
  `vnetConfiguration`, `zoneRedundant`, `workloadProfiles`,
  `infrastructureResourceGroup`, `peerAuthentication`, `availabilityZones`,
  `peerTrafficConfiguration`, `publicNetworkAccess`
- **Backup Job** (`container_apps.py`): `configuration`, `identity`, `template`,
  `workloadProfileName`

### Post-import: password sync

After a fresh deploy following state recovery, Pulumi generates a **new** admin
password and stores it in Key Vault, but the existing PostgreSQL server still
has the old password. Sync them:

```bash
NEW_PASS=$(az keyvault secret show \
  --vault-name <key-vault-name> \
  --name postgresql-admin-password \
  --query "value" -o tsv)
az postgres flexible-server update \
  --name <server-name> \
  --resource-group <resource-group> \
  --admin-password "$NEW_PASS"
```
