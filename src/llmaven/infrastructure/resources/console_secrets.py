"""The console's identities, per-app Key Vaults and secrets.

Each console app gets its own user-assigned identity and its own access-policy
vault holding only the secrets that app reads, so the web app can never read the
broker's or LiteLLM's secrets. Policies are set inline when the vault is
created; no role assignment or AccessPolicy resource is ever made.

Generated values are Pulumi secrets written only as Key Vault secrets and never
exported. Database passwords are generated without special characters, so they
can sit unescaped in the ``postgresql://`` URLs.
"""

from dataclasses import dataclass
from typing import Literal

import pulumi
import pulumi_azure_native as azure_native
import pulumi_random as random

from ..config.schema import CONSOLE_DB, LLMavenConfig, console_vault_name
from .helpers import create_user_assigned_managed_identity
from .key_vault import deployer_access_policy
from .secrets_manager import KEYCLOAK_SECRET_NAMES

WEB_DB_ROLE = "console_web"
BROKER_DB_ROLE = "console_broker"

OIDC_SECRET = KEYCLOAK_SECRET_NAMES["client_console"]
CALLER_SECRET = "console-broker-caller-secret"
WEB_DB_URL = "console-web-db-url"
BROKER_DB_URL = "console-broker-db-url"
ACS_SECRET = "console-mail-connection"
WEB_DB_PASSWORD = "console-web-db-password"
BROKER_DB_PASSWORD = "console-broker-db-password"
# The console-db job's copy of the server admin password, so the job never
# depends on which name the operator gave that secret.
DB_ADMIN_PASSWORD = "console-db-admin-password"

PASSWORD_LENGTH = 40


@dataclass
class ConsoleSecrets:
    web_identity: azure_native.managedidentity.UserAssignedIdentity
    broker_identity: azure_native.managedidentity.UserAssignedIdentity
    web_vault: azure_native.keyvault.Vault
    broker_vault: azure_native.keyvault.Vault
    web_secret_names: dict[str, str]  # env var -> secret name in web_vault
    broker_secret_names: dict[str, str]  # env var -> secret name in broker_vault
    # env var -> secret name in the main vault (console-db job)
    job_secret_names: dict[str, str]
    resources: list[pulumi.Resource]  # for depends_on


def _password(name: str, environment: str) -> pulumi.Output[str]:
    return random.RandomPassword(
        f"console-{name}-{environment}",
        length=PASSWORD_LENGTH,
        special=False,
        min_lower=1,
        min_upper=1,
        min_numeric=1,
    ).result


def _vault(
    which: Literal["web", "broker"],
    config: LLMavenConfig,
    resource_group_name: pulumi.Input[str],
    location: str,
    tenant_id: str,
    deployer_object_id: str | None,
    identity: azure_native.managedidentity.UserAssignedIdentity,
) -> azure_native.keyvault.Vault:
    environment = config.project.environment
    kv_config = config.security.key_vault
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
    return azure_native.keyvault.Vault(
        f"console-{which}-vault-{environment}",
        resource_group_name=resource_group_name,
        vault_name=console_vault_name(config.project.name, environment, which),
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


def create_console_secrets(
    config: LLMavenConfig,
    resource_group_name: pulumi.Input[str],
    location: str,
    tenant_id: str,
    deployer_object_id: str | None,
    main_vault: azure_native.keyvault.Vault,
    postgres_host: pulumi.Input[str],
    admin_password: pulumi.Input[str],
    mail_connection_string: pulumi.Input[str],
) -> ConsoleSecrets:
    """Create the console's identities, vaults and secrets (spec section 6)."""
    project = config.project.name
    environment = config.project.environment

    web_identity = create_user_assigned_managed_identity(
        f"{project}-{environment}-console-web",
        resource_group_name,
        location,
        config.tags,
    )
    broker_identity = create_user_assigned_managed_identity(
        f"{project}-{environment}-console-broker",
        resource_group_name,
        location,
        config.tags,
    )
    web_vault = _vault(
        "web",
        config,
        resource_group_name,
        location,
        tenant_id,
        deployer_object_id,
        web_identity,
    )
    broker_vault = _vault(
        "broker",
        config,
        resource_group_name,
        location,
        tenant_id,
        deployer_object_id,
        broker_identity,
    )

    secrets: list[pulumi.Resource] = []

    def put(
        vault: azure_native.keyvault.Vault, label: str, name: str, value: pulumi.Input
    ) -> None:
        # The resource name carries the vault: one value is written to two
        # vaults under one secret name, and Pulumi names are program-unique.
        secrets.append(
            azure_native.keyvault.Secret(
                f"kv-secret-console-{label}-{name}-{environment}",
                resource_group_name=resource_group_name,
                vault_name=vault.name,
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

    oidc = _password("oidc-client-secret", environment)
    caller = _password("broker-caller-secret", environment)
    web_pw = _password("web-db-password", environment)
    broker_pw = _password("broker-db-password", environment)

    def db_url(role: str, password: pulumi.Output[str]) -> pulumi.Output[str]:
        return pulumi.Output.all(password, postgres_host).apply(
            lambda a: (
                f"postgresql://{role}:{a[0]}@{a[1]}:5432/{CONSOLE_DB}?sslmode=require"
            )
        )

    put(web_vault, "web", OIDC_SECRET, oidc)
    put(web_vault, "web", CALLER_SECRET, caller)
    put(web_vault, "web", WEB_DB_URL, db_url(WEB_DB_ROLE, web_pw))
    put(broker_vault, "broker", CALLER_SECRET, caller)
    put(broker_vault, "broker", BROKER_DB_URL, db_url(BROKER_DB_ROLE, broker_pw))
    put(broker_vault, "broker", ACS_SECRET, mail_connection_string)
    put(main_vault, "main", OIDC_SECRET, oidc)
    put(main_vault, "main", WEB_DB_PASSWORD, web_pw)
    put(main_vault, "main", BROKER_DB_PASSWORD, broker_pw)
    put(main_vault, "main", DB_ADMIN_PASSWORD, admin_password)

    return ConsoleSecrets(
        web_identity=web_identity,
        broker_identity=broker_identity,
        web_vault=web_vault,
        broker_vault=broker_vault,
        web_secret_names={
            "CONSOLE_WEB_DATABASE_URL": WEB_DB_URL,
            "CONSOLE_BROKER_CALLER_SECRET": CALLER_SECRET,
            "OIDC_CLIENT_SECRET": OIDC_SECRET,
        },
        broker_secret_names={
            "CONSOLE_BROKER_DATABASE_URL": BROKER_DB_URL,
            "CONSOLE_BROKER_CALLER_SECRET": CALLER_SECRET,
            "ACS_CONNECTION_STRING": ACS_SECRET,
        },
        job_secret_names={
            "PGPASSWORD": DB_ADMIN_PASSWORD,
            "CONSOLE_WEB_DB_PASSWORD": WEB_DB_PASSWORD,
            "CONSOLE_BROKER_DB_PASSWORD": BROKER_DB_PASSWORD,
        },
        resources=[
            web_identity,
            broker_identity,
            web_vault,
            broker_vault,
            *secrets,
        ],
    )
