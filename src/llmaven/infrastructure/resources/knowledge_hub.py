"""The knowledge hub's identity, Key Vault, secrets, storage and app.

The hub gets its own user-assigned identity and its own access-policy vault
holding the three secrets it reads. The master key is kept out of the main vault
(the generic LLMAVEN_SECRETS_* upload skips it), so only the hub can read it; the
database password is also written to the main vault for the console-db job. Policies
are set inline when the vault is created; no role assignment is ever made.

The master key comes from the deploy environment and is never generated here:
losing it would make the hub's stored data unreadable. The database password is
generated and written to this vault (inside the database URL) and to the main
vault, which is where the console-db job reads every role password.

The hub has its own storage account, kept when the hub or the console is
turned off, so its bundles outlive both alongside the retained database. The
console-db job needs the hub's database password, so the secrets that need no
storage are made before the console, and the storage, the connection string and
the app after it.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass

import pulumi
import pulumi_azure_native as azure_native

from ..config.schema import (
    KNOWLEDGE_HUB_APP_SUFFIX,
    KNOWLEDGE_HUB_DB,
    KNOWLEDGE_HUB_MASTER_KEY_ENV,
    KNOWLEDGE_HUB_PORT,
    LLMavenConfig,
    container_app_environment,
    container_app_name,
    knowledge_hub_storage_account_name,
    knowledge_hub_vault_name,
)
from .console_secrets import _password
from .container_apps import create_container_app_with_key_vault_secrets
from .helpers import create_user_assigned_managed_identity
from .key_vault import deployer_access_policy

HUB_DB_ROLE = "okf_hub"
BLOB_CONTAINER = "okf-hub"
MASTER_KEY_SECRET = "okf-hub-master-key"
DATABASE_URL_SECRET = "okf-hub-database-url"
STORAGE_CONNECTION_SECRET = "okf-hub-storage-connection"
# The main-vault copy of the database password, read by the console-db job.
DB_PASSWORD_SECRET = "okf-hub-db-password"
HEALTH_PATH = "/healthz"
# REFRESH_TRIGGER when knowledge_hub.refresh_trigger is unset: a constant, so a
# deploy that changes nothing else does not roll a new revision.
REFRESH_TRIGGER = "okf-hub"
# Who may do what, read by the hub: each OIDC actor writes its own bundle, and
# the knowledge-reader role reads every organization's bundle.
OIDC_GRANTS = (
    '[{"bundle":"orgs/oidc-{actor}","access":"write"},'
    '{"role":"knowledge-reader","bundle":"orgs/*","access":"read"}]'
)

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
    # The main-vault secrets the console-db job reads, for its depends_on.
    job_secrets: list[pulumi.Resource]


def _put_secret(
    config: LLMavenConfig,
    resource_group_name: pulumi.Input[str],
    target: azure_native.keyvault.Vault,
    label: str,
    name: str,
    value: pulumi.Input,
) -> azure_native.keyvault.Secret:
    return azure_native.keyvault.Secret(
        f"kv-secret-okf-hub-{label}-{name}-{config.project.environment}",
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


def create_knowledge_hub_secrets(
    config: LLMavenConfig,
    resource_group_name: pulumi.Input[str],
    location: str,
    tenant_id: str,
    deployer_object_id: str | None,
    main_vault: azure_native.keyvault.Vault,
    postgres_host: pulumi.Input[str],
    master_key: str,
) -> KnowledgeHubSecrets:
    """Create the hub's identity, vault and the secrets that need no storage.

    The Blob connection string, the third name in ``secret_names``, is written
    by ``create_knowledge_hub_storage_secret`` once the hub's storage account
    exists.
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

    db_password = _password("okf-hub-db-password", environment)
    database_url = pulumi.Output.all(db_password, postgres_host).apply(
        lambda a: (
            f"postgresql://{HUB_DB_ROLE}:{a[0]}@{a[1]}:5432/{KNOWLEDGE_HUB_DB}"
            # The server's certificate must chain to a trusted root and name this host.
            "?sslmode=verify-full&sslrootcert=system"
        )
    )

    def put(target, label, name, value):
        return _put_secret(config, resource_group_name, target, label, name, value)

    hub_secrets = [
        put(vault, "hub", MASTER_KEY_SECRET, master_key),
        put(vault, "hub", DATABASE_URL_SECRET, database_url),
    ]
    main_password = put(main_vault, "main", DB_PASSWORD_SECRET, db_password)

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
        resources=[identity, vault, *hub_secrets, main_password],
        job_secrets=[main_password],
    )


def create_knowledge_hub_storage_account(
    config: LLMavenConfig,
    resource_group_name: pulumi.Input[str],
    location: str,
    tags: dict[str, str],
    opts: pulumi.ResourceOptions | None = None,
) -> azure_native.storage.StorageAccount:
    """The hub's own storage account, kept when the stack is destroyed.

    Set like the console's account (StorageV2, LRS, https only, TLS 1.2, no
    public blob access), with shared-key access on, since the hub reads its
    Blob container through a connection string. It is the hub's own, so turning
    the console off cannot delete the bundles the retained database points at.
    """
    return azure_native.storage.StorageAccount(
        f"okf-hub-storage-{config.project.environment}",
        resource_group_name=resource_group_name,
        account_name=knowledge_hub_storage_account_name(
            config.project.name, config.project.environment, location
        ),
        location=location,
        tags=tags,
        sku=azure_native.storage.SkuArgs(
            name=azure_native.storage.SkuName.STANDARD_LRS
        ),
        kind=azure_native.storage.Kind.STORAGE_V2,
        is_hns_enabled=False,
        enable_https_traffic_only=True,
        minimum_tls_version=azure_native.storage.MinimumTlsVersion.TLS1_2,
        allow_blob_public_access=False,
        allow_shared_key_access=True,
        opts=pulumi.ResourceOptions.merge(
            opts, pulumi.ResourceOptions(retain_on_delete=True)
        ),
    )


def create_knowledge_hub_storage_secret(
    config: LLMavenConfig,
    resource_group_name: pulumi.Input[str],
    secrets: KnowledgeHubSecrets,
    storage_account_name: pulumi.Input[str],
) -> azure_native.keyvault.Secret:
    """Write the Blob connection string for the hub's storage account.

    Pass the account's ``name`` Output, so the key lookup runs once the account
    exists.
    """
    keys = azure_native.storage.list_storage_account_keys_output(
        resource_group_name=resource_group_name,
        account_name=storage_account_name,
    )
    connection_string = pulumi.Output.all(
        storage_account_name, keys.keys[0].value
    ).apply(
        lambda a: (
            f"DefaultEndpointsProtocol=https;AccountName={a[0]};AccountKey={a[1]};"
            "EndpointSuffix=core.windows.net"
        )
    )
    return _put_secret(
        config,
        resource_group_name,
        secrets.vault,
        "hub",
        STORAGE_CONNECTION_SECRET,
        connection_string,
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


def hub_url(
    container_env: azure_native.app.ManagedEnvironment, project: str, environment: str
) -> pulumi.Output[str]:
    """The hub's internal https URL: its audience, and where the console calls it.

    It is the FQDN Container Apps gives an app with internal ingress, so it is
    known before the app exists and never changes for a stack.
    """
    name = container_app_name(project, environment, KNOWLEDGE_HUB_APP_SUFFIX)
    return pulumi.Output.concat(
        "https://", name, ".internal.", container_env.default_domain
    )


def create_knowledge_hub_app(
    config: LLMavenConfig,
    resource_group_name: pulumi.Input[str],
    location: str,
    container_env: azure_native.app.ManagedEnvironment,
    secrets: KnowledgeHubSecrets,
    keycloak_fqdn: pulumi.Input[str],
    tags: dict[str, str],
    opts: pulumi.ResourceOptions | None = None,
) -> azure_native.app.ContainerApp:
    """The hub's Container App: internal ingress, one replica, its own vault.

    One replica, so every call for a vault runs through one engine (the spec
    leaves more replicas until okf's handling of a 409 is known). Its probes
    are HTTP checks of ``/healthz``: Container Apps ignores the image's
    HEALTHCHECK, and the startup probe gives the database migration and the
    Blob container check time to finish.
    """
    project = config.project.name
    environment = config.project.environment
    realm = config.keycloak.realm.name
    base_name = f"{project}-{environment}-{KNOWLEDGE_HUB_APP_SUFFIX}"
    return create_container_app_with_key_vault_secrets(
        app_name=base_name,
        resource_group_name=resource_group_name,
        location=location,
        managed_environment_id=container_env.id,
        key_vault_uri=secrets.vault.properties.vault_uri,
        container_image=config.knowledge_hub.image,
        container_port=KNOWLEDGE_HUB_PORT,
        cpu=config.knowledge_hub.cpu,
        memory=config.knowledge_hub.memory,
        min_replicas=1,
        max_replicas=1,
        env_vars={
            # Tokens name the public issuer; the keys are fetched internally.
            "OIDC_ISSUER": f"https://{config.keycloak.hostname}/realms/{realm}",
            "OIDC_JWKS_URL": pulumi.Output.concat(
                "https://",
                keycloak_fqdn,
                f"/realms/{realm}/protocol/openid-connect/certs",
            ),
            "OIDC_AUDIENCE": hub_url(container_env, project, environment),
            "OIDC_GRANTS": OIDC_GRANTS,
            "BLOB_CONTAINER": BLOB_CONTAINER,
            "PORT": str(KNOWLEDGE_HUB_PORT),
        },
        key_vault_secret_refs=secrets.secret_names,
        managed_identity_id=secrets.identity.id,
        environment=container_app_environment(base_name),
        tags=tags,
        enable_ingress=True,
        ingress_external=False,
        health_probe_port=KNOWLEDGE_HUB_PORT,
        health_probe_path=HEALTH_PATH,
        refresh_trigger=config.knowledge_hub.refresh_trigger or REFRESH_TRIGGER,
        opts=pulumi.ResourceOptions.merge(
            opts, pulumi.ResourceOptions(depends_on=secrets.resources)
        ),
    )
