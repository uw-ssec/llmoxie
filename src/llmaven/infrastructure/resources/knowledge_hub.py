"""The knowledge hub's identity, Key Vault, secrets and Blob container.

The hub gets its own user-assigned identity and its own access-policy vault
holding only the three secrets it reads, so no other app can read them. Policies
are set inline when the vault is created; no role assignment is ever made.

The master key comes from the deploy environment and is never generated here:
losing it would make the hub's stored data unreadable. The database password is
generated and written to this vault (inside the database URL) and to the main
vault, which is where the console-db job reads every role password.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass

import pulumi
import pulumi_azure_native as azure_native

from ..config.schema import (
    KNOWLEDGE_HUB_DB,
    KNOWLEDGE_HUB_MASTER_KEY_ENV,
    LLMavenConfig,
    knowledge_hub_vault_name,
)
from .console_secrets import _password
from .helpers import create_user_assigned_managed_identity
from .key_vault import deployer_access_policy

HUB_DB_ROLE = "okf_hub"
BLOB_CONTAINER = "okf-hub"
MASTER_KEY_SECRET = "okf-hub-master-key"
DATABASE_URL_SECRET = "okf-hub-database-url"
STORAGE_CONNECTION_SECRET = "okf-hub-storage-connection"
# The main-vault copy of the database password, read by the console-db job.
DB_PASSWORD_SECRET = "okf-hub-db-password"

_MASTER_KEY = re.compile(r"[0-9a-f]{64}")


def master_key_from_env(env: Mapping[str, str]) -> str:
    """The hub's vault master key: 64 lowercase hex characters from the environment."""
    value = env.get(KNOWLEDGE_HUB_MASTER_KEY_ENV, "")
    if not _MASTER_KEY.fullmatch(value):
        raise ValueError(
            f"{KNOWLEDGE_HUB_MASTER_KEY_ENV} must be set to 64 lowercase hex "
            "characters (for example from `openssl rand -hex 32`)"
        )
    return value


@dataclass
class KnowledgeHubSecrets:
    identity: azure_native.managedidentity.UserAssignedIdentity
    vault: azure_native.keyvault.Vault
    secret_names: dict[str, str]  # env var -> secret name in the hub vault
    # env var -> secret name in the main vault (console-db job)
    job_secret_names: dict[str, str]
    db_password: pulumi.Output[str]
    resources: list[pulumi.Resource]  # for depends_on


def create_knowledge_hub_secrets(
    config: LLMavenConfig,
    resource_group_name: pulumi.Input[str],
    location: str,
    tenant_id: str,
    deployer_object_id: str | None,
    main_vault: azure_native.keyvault.Vault,
    postgres_host: pulumi.Input[str],
    storage_account_name: pulumi.Input[str],
    master_key: str,
    storage_depends_on: list[pulumi.Resource] | None = None,
) -> KnowledgeHubSecrets:
    """Create the hub's identity, vault and secrets.

    ``storage_account_name`` is the console's storage account. Pass an Output of
    the account, or its resources in ``storage_depends_on``, so the key lookup
    waits for the account to exist.
    """
    project = config.project.name
    environment = config.project.environment
    kv_config = config.security.key_vault

    identity = create_user_assigned_managed_identity(
        f"{project}-{environment}-okf-hub",
        resource_group_name,
        location,
        config.tags,
    )
    policies = [
        azure_native.keyvault.AccessPolicyEntryArgs(
            tenant_id=tenant_id,
            object_id=identity.principal_id,
            permissions=azure_native.keyvault.PermissionsArgs(
                secrets=[
                    azure_native.keyvault.SecretPermissions.GET,
                    azure_native.keyvault.SecretPermissions.LIST,
                ],
            ),
        )
    ]
    if deployer_object_id:
        policies.append(deployer_access_policy(tenant_id, deployer_object_id))
    vault = azure_native.keyvault.Vault(
        f"okf-hub-vault-{environment}",
        resource_group_name=resource_group_name,
        vault_name=knowledge_hub_vault_name(project, environment),
        location=location,
        tags=config.tags,
        properties=azure_native.keyvault.VaultPropertiesArgs(
            tenant_id=tenant_id,
            sku=azure_native.keyvault.SkuArgs(
                family="A", name=azure_native.keyvault.SkuName.STANDARD
            ),
            enable_rbac_authorization=False,
            access_policies=policies,
            enable_soft_delete=kv_config.enable_soft_delete,
            soft_delete_retention_in_days=kv_config.soft_delete_retention_days,
            enable_purge_protection=kv_config.enable_purge_protection,
        ),
    )

    secrets: list[pulumi.Resource] = []

    def put(
        target: azure_native.keyvault.Vault,
        label: str,
        name: str,
        value: pulumi.Input,
    ) -> None:
        secrets.append(
            azure_native.keyvault.Secret(
                f"kv-secret-okf-hub-{label}-{name}-{environment}",
                resource_group_name=resource_group_name,
                vault_name=target.name,
                secret_name=name,
                properties=azure_native.keyvault.SecretPropertiesArgs(
                    value=pulumi.Output.secret(value),
                    content_type="text/plain",
                    attributes=azure_native.keyvault.SecretAttributesArgs(enabled=True),
                ),
                tags=config.tags,
                opts=pulumi.ResourceOptions(additional_secret_outputs=["properties"]),
            )
        )

    db_password = _password("okf-hub-db-password", environment)
    database_url = pulumi.Output.all(db_password, postgres_host).apply(
        lambda a: (
            f"postgresql://{HUB_DB_ROLE}:{a[0]}@{a[1]}:5432/{KNOWLEDGE_HUB_DB}"
            # The server's certificate must chain to a trusted root and name this host.
            "?sslmode=verify-full&sslrootcert=system"
        )
    )
    keys = azure_native.storage.list_storage_account_keys_output(
        resource_group_name=resource_group_name,
        account_name=storage_account_name,
        opts=pulumi.InvokeOutputOptions(depends_on=storage_depends_on or []),
    )
    connection_string = pulumi.Output.all(storage_account_name, keys.keys[0].value).apply(
        lambda a: (
            f"DefaultEndpointsProtocol=https;AccountName={a[0]};AccountKey={a[1]};"
            "EndpointSuffix=core.windows.net"
        )
    )

    put(vault, "hub", MASTER_KEY_SECRET, master_key)
    put(vault, "hub", DATABASE_URL_SECRET, database_url)
    put(vault, "hub", STORAGE_CONNECTION_SECRET, connection_string)
    put(main_vault, "main", DB_PASSWORD_SECRET, db_password)

    return KnowledgeHubSecrets(
        identity=identity,
        vault=vault,
        secret_names={
            "VAULT_MASTER_KEY_HEX": MASTER_KEY_SECRET,
            "DATABASE_URL": DATABASE_URL_SECRET,
            "AZURE_STORAGE_CONNECTION_STRING": STORAGE_CONNECTION_SECRET,
        },
        job_secret_names={"OKF_HUB_DB_PASSWORD": DB_PASSWORD_SECRET},
        db_password=db_password,
        resources=[identity, vault, *secrets],
    )


def create_knowledge_hub_storage(
    config: LLMavenConfig,
    resource_group_name: pulumi.Input[str],
    storage_account_name: pulumi.Input[str],
    tags: dict[str, str],
    opts: pulumi.ResourceOptions | None = None,
) -> azure_native.storage.BlobContainer:
    """The hub's private Blob container, kept when the stack is destroyed.

    ``tags`` is accepted for symmetry with the other creators; a Blob container
    carries none.
    """
    return azure_native.storage.BlobContainer(
        f"okf-hub-blob-{config.project.environment}",
        resource_group_name=resource_group_name,
        account_name=storage_account_name,
        container_name=BLOB_CONTAINER,
        public_access=azure_native.storage.PublicAccess.NONE,
        opts=pulumi.ResourceOptions.merge(
            opts, pulumi.ResourceOptions(retain_on_delete=True)
        ),
    )
