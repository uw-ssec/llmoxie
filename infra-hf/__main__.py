"""
Pulumi program: LLMaven HuggingFace PostgreSQL deployment.

Creates:
- Resource group: rg-llmaven-hf
- Key Vault: kv-llmaven-hf
- PostgreSQL Flexible Server (GeneralPurpose, public access)
- Database: llmaven
- Key Vault secrets: postgres-admin-password, postgres-connection-string

Usage:
    cd infra-hf
    pulumi stack init hf-prod
    pulumi config set location westus2   # optional, westus2 is the default
    pulumi preview
    pulumi up
"""

import pulumi
import pulumi_azure_native as azure_native
from pulumi import Output
from pulumi_azure_native import authorization

from llmaven.infrastructure.resources.database import (
    configure_firewall_rules,
    create_databases,
)
from llmaven.infrastructure.resources.key_vault import create_secret
from llmaven.infrastructure.utils.secrets import (
    build_postgres_connection_string,
    generate_secure_password,
)

# ── Configuration ─────────────────────────────────────────────────────────────
cfg = pulumi.Config()
location: str = cfg.get("location") or "westus2"

ADMIN_LOGIN = "pgadmin"
ENVIRONMENT = "hf"
TAGS = {
    "project": "llmaven",
    "env": "prod",
    "component": "hf",
    "managed-by": "pulumi",
}

# Azure caller identity (needed for Key Vault access policy)
client_config = authorization.get_client_config()

# ── Resource Group ────────────────────────────────────────────────────────────
resource_group = azure_native.resources.ResourceGroup(
    "rg-llmaven-hf",
    resource_group_name="rg-llmaven-hf",
    location=location,
    tags=TAGS,
)

# ── Key Vault ─────────────────────────────────────────────────────────────────
# Name must be globally unique, 3-24 alphanumeric/hyphen characters.
# Rename if this conflicts with an existing vault in another subscription.
key_vault = azure_native.keyvault.Vault(
    "kv-llmaven-hf",
    vault_name="kv-llmaven-hf",
    resource_group_name=resource_group.name,
    location=location,
    tags=TAGS,
    properties=azure_native.keyvault.VaultPropertiesArgs(
        tenant_id=client_config.tenant_id,
        sku=azure_native.keyvault.SkuArgs(
            family="A",
            name=azure_native.keyvault.SkuName.STANDARD,
        ),
        enable_rbac_authorization=False,
        enable_soft_delete=False,
        # Grant the deploying principal full secrets access
        access_policies=[
            azure_native.keyvault.AccessPolicyEntryArgs(
                tenant_id=client_config.tenant_id,
                object_id=client_config.object_id,
                permissions=azure_native.keyvault.PermissionsArgs(
                    secrets=[
                        azure_native.keyvault.SecretPermissions.GET,
                        azure_native.keyvault.SecretPermissions.LIST,
                        azure_native.keyvault.SecretPermissions.SET,
                        azure_native.keyvault.SecretPermissions.DELETE,
                        azure_native.keyvault.SecretPermissions.RECOVER,
                        azure_native.keyvault.SecretPermissions.BACKUP,
                        azure_native.keyvault.SecretPermissions.RESTORE,
                    ],
                ),
            )
        ],
        network_acls=azure_native.keyvault.NetworkRuleSetArgs(
            bypass=azure_native.keyvault.NetworkRuleBypassOptions.AZURE_SERVICES,
            default_action=azure_native.keyvault.NetworkRuleAction.ALLOW,
        ),
        public_network_access=azure_native.keyvault.PublicNetworkAccess.ENABLED,
    ),
)

# ── Admin Password ────────────────────────────────────────────────────────────
admin_password = Output.secret(generate_secure_password())

create_secret(
    resource_group_name=resource_group.name,
    vault_name=key_vault.name,
    secret_name="postgres-admin-password",
    secret_value=admin_password,
    environment=ENVIRONMENT,
    tags=TAGS,
)

# ── PostgreSQL Flexible Server ────────────────────────────────────────────────
pg_server = azure_native.dbforpostgresql.Server(
    "pg-llmaven-hf",
    server_name="pg-llmaven-hf",
    resource_group_name=resource_group.name,
    location=location,
    sku=azure_native.dbforpostgresql.SkuArgs(
        name="Standard_D2ds_v4",
        tier="GeneralPurpose",
    ),
    storage=azure_native.dbforpostgresql.StorageArgs(
        storage_size_gb=64,
    ),
    backup=azure_native.dbforpostgresql.BackupArgs(
        backup_retention_days=14,
        geo_redundant_backup="Disabled",
    ),
    high_availability=azure_native.dbforpostgresql.HighAvailabilityArgs(
        mode="Disabled",
    ),
    version="16",
    administrator_login=ADMIN_LOGIN,
    administrator_login_password=admin_password,
    tags=TAGS,
)

# ── Firewall: allow all public IPs (HuggingFace Spaces use dynamic IPs) ───────
configure_firewall_rules(
    resource_group_name=resource_group.name,
    server_name=pg_server.name,
    environment=ENVIRONMENT,
    allow_azure_services=True,
    allowed_ip_ranges=[
        {"name": "AllPublicIPs", "start": "0.0.0.0", "end": "255.255.255.255"},
    ],
)

# ── Database ──────────────────────────────────────────────────────────────────
create_databases(
    resource_group_name=resource_group.name,
    server_name=pg_server.name,
    database_names=["llmaven"],
    environment=ENVIRONMENT,
    tags=TAGS,
)

# ── Connection String Secret ──────────────────────────────────────────────────
# admin_password is already secret-tagged, so the .apply result inherits that.
connection_string: Output[str] = Output.all(
    pg_server.fully_qualified_domain_name, admin_password
).apply(
    lambda args: build_postgres_connection_string(
        server_fqdn=args[0],
        database_name="llmaven",
        admin_login=ADMIN_LOGIN,
        admin_password=args[1],
    )
)

create_secret(
    resource_group_name=resource_group.name,
    vault_name=key_vault.name,
    secret_name="postgres-connection-string",
    secret_value=connection_string,
    environment=ENVIRONMENT,
    tags=TAGS,
)

# ── Exports ───────────────────────────────────────────────────────────────────
pulumi.export("resource_group", resource_group.name)
pulumi.export("postgres_server_name", pg_server.name)
pulumi.export("postgres_server_fqdn", pg_server.fully_qualified_domain_name)
pulumi.export("key_vault_name", key_vault.name)
pulumi.export("key_vault_uri", key_vault.properties.vault_uri)
