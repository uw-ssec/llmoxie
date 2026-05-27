"""Azure Key Vault resource module.

This module creates and configures Azure Key Vault for secure secrets management
with access policies, audit logging, and managed identity integration.

Prerequisites:
--------------
The deploying user needs the following permissions:

- "Key Vault Contributor" role (for Key Vault management)

These permissions are required to:
1. Create Key Vault resources
2. Configure access policies for managed identities
3. Create and manage secrets

To check your current roles:
    az role assignment list --assignee $(az ad signed-in-user show --query id -o tsv) \
        --scope /subscriptions/{SUBSCRIPTION_ID}

To request access from your Azure administrator:
    "I need Key Vault Contributor role to deploy LLMaven infrastructure"

Access Control:
---------------
Access Policies:
   - Key Vault is configured with access policies for secrets management
   - Use `grant_key_vault_access()` to add access policies for managed identities
   - Access policies define specific permissions (get, list, set secrets, etc.)

Usage:
------
1. Create Key Vault with `create_key_vault()`
2. Grant access to managed identities with `grant_key_vault_access()`
3. Create secrets with `create_secret()` or `create_secrets_from_environment()`
"""

import os
from typing import Dict, Optional

import pulumi
import pulumi_azure_native as azure_native
from pulumi import Output

from ..config.schema import LLMavenConfig


def create_key_vault(
    resource_group_name: Output[str],
    location: str,
    tenant_id: str,
    config: LLMavenConfig,
    tags: Dict[str, str],
    deployer_object_id: Optional[str] = None,
) -> azure_native.keyvault.Vault:
    """
    Create Azure Key Vault with access policies.

    Prerequisites:
        The deploying user must have "Key Vault Contributor" role

        This role is required to:
        1. Create the Key Vault resource
        2. Configure access policies for managed identities

        If you don't have this role, ask your Azure administrator to grant it.

    Args:
        resource_group_name: Name of the resource group
        location: Azure region
        tenant_id: Azure AD tenant ID
        config: LLMaven configuration
        tags: Resource tags
        deployer_object_id: Object ID of the deploying user (for access policy)

    Returns:
        Key Vault resource
    """
    project_name = config.project.name
    environment = config.project.environment
    kv_config = config.security.key_vault  # noqa: F841

    # Key Vault name (must be globally unique, 3-24 chars, alphanumeric and hyphens)
    # Format: kv-{project}-{env}-{region_suffix} (e.g., kv-llmaven-dev-wu2)
    # Add region suffix to ensure global uniqueness
    region_suffix = location[:4].replace("-", "").lower()  # e.g., "westus2" -> "west"
    vault_name = f"kv-{project_name}-{environment}-{region_suffix}"[:24]

    # Build access policies list
    access_policies = []

    # Add deployer access policy if object ID is provided
    if deployer_object_id:
        access_policies.append(
            azure_native.keyvault.AccessPolicyEntryArgs(
                tenant_id=tenant_id,
                object_id=deployer_object_id,
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
                    keys=[
                        azure_native.keyvault.KeyPermissions.GET,
                        azure_native.keyvault.KeyPermissions.LIST,
                        azure_native.keyvault.KeyPermissions.CREATE,
                        azure_native.keyvault.KeyPermissions.DELETE,
                        azure_native.keyvault.KeyPermissions.RECOVER,
                        azure_native.keyvault.KeyPermissions.WRAP_KEY,
                        azure_native.keyvault.KeyPermissions.UNWRAP_KEY,
                        azure_native.keyvault.KeyPermissions.SIGN,
                        azure_native.keyvault.KeyPermissions.VERIFY,
                        azure_native.keyvault.KeyPermissions.BACKUP,
                        azure_native.keyvault.KeyPermissions.RESTORE,
                    ],
                ),
            )
        )

    # Create Key Vault
    key_vault = azure_native.keyvault.Vault(
        f"key-vault-{environment}",
        resource_group_name=resource_group_name,
        vault_name=vault_name,
        location=location,
        tags=tags,
        properties=azure_native.keyvault.VaultPropertiesArgs(
            tenant_id=tenant_id,
            sku=azure_native.keyvault.SkuArgs(
                family="A",
                name=azure_native.keyvault.SkuName.STANDARD,
            ),
            # Access policies
            enable_rbac_authorization=False,
            access_policies=access_policies if access_policies else None,
            # Soft delete configuration
            enable_soft_delete=kv_config.enable_soft_delete,
            soft_delete_retention_in_days=kv_config.soft_delete_retention_days,
            enable_purge_protection=kv_config.enable_purge_protection,
            # Network ACLs
            network_acls=azure_native.keyvault.NetworkRuleSetArgs(
                bypass=azure_native.keyvault.NetworkRuleBypassOptions.AZURE_SERVICES,
                default_action=(
                    azure_native.keyvault.NetworkRuleAction.DENY
                    if config.security.enable_private_endpoints
                    else azure_native.keyvault.NetworkRuleAction.ALLOW
                ),
                ip_rules=(
                    [
                        azure_native.keyvault.IPRuleArgs(value=ip_range)
                        for ip_range in config.security.network_security.allowed_ip_ranges
                    ]
                    if config.security.network_security.allowed_ip_ranges
                    else None
                ),
            ),
            # Public network access
            public_network_access=(
                azure_native.keyvault.PublicNetworkAccess.DISABLED
                if config.security.enable_private_endpoints
                else azure_native.keyvault.PublicNetworkAccess.ENABLED
            ),
        ),
    )

    pulumi.export(f"key_vault_name_{environment}", key_vault.name)
    pulumi.export(f"key_vault_uri_{environment}", key_vault.properties.vault_uri)

    # Log information about access policies
    pulumi.log.info(
        "✓ Key Vault created with access policies.\n"
        "  To manage secrets and grant access to container apps, the deploying user\n"
        "  must have 'Key Vault Contributor' role.\n"
        "  \n"
        "  Access policies can be added using `grant_key_vault_access()` function."
    )

    return key_vault


def create_secret(
    resource_group_name: Output[str],
    vault_name: Output[str],
    secret_name: str,
    secret_value: Output[str],
    environment: str,
    tags: Optional[Dict[str, str]] = None,
) -> azure_native.keyvault.Secret:
    """
    Create or update a secret in Key Vault.

    This function is idempotent - it will create the secret if it doesn't exist,
    or update it if it already exists. This prevents errors when re-running
    deployments where secrets may already exist.

    Args:
        resource_group_name: Name of the resource group
        vault_name: Key Vault name
        secret_name: Name of the secret
        secret_value: Secret value
        environment: Environment name
        tags: Secret tags (metadata)

    Returns:
        Secret resource
    """
    secret = azure_native.keyvault.Secret(
        f"kv-secret-{secret_name}-{environment}",
        resource_group_name=resource_group_name,
        vault_name=vault_name,
        secret_name=secret_name,
        properties=azure_native.keyvault.SecretPropertiesArgs(
            value=secret_value,
            content_type="text/plain",
            attributes=azure_native.keyvault.SecretAttributesArgs(
                enabled=True,
            ),
        ),
        tags=tags,
        opts=pulumi.ResourceOptions(
            additional_secret_outputs=["properties"],
            # This allows Pulumi to import existing secrets instead of failing
            # when they already exist (idempotent behavior)
            retain_on_delete=False,
        ),
    )

    pulumi.log.info(f"✓ Created/Updated Key Vault secret: {secret_name}")

    return secret


def get_llmaven_secrets_from_env() -> Dict[str, str]:
    """
    Read all environment variables with LLMAVEN_SECRETS_ prefix.

    This function implements the secrets management pattern where users set
    environment variables with the LLMAVEN_SECRETS_ prefix, which are then
    automatically stored in Azure Key Vault.

    Transformation rules:
    1. Remove LLMAVEN_SECRETS_ prefix
    2. Convert to lowercase
    3. Replace underscores with hyphens

    Returns:
        Dictionary mapping secret names to values
        Example: {"litellm-master-key": "sk-123...", "azure-openai-api-key": "abc..."}
    """
    secrets = {}
    prefix = "LLMAVEN_SECRETS_"

    for key, value in os.environ.items():
        if key.startswith(prefix):
            # Transform environment variable name to Key Vault secret name
            secret_name = transform_env_var_to_secret_name(key)
            secrets[secret_name] = value

            # Log secret discovery (value is redacted for security)
            pulumi.log.info(f"✓ Found secret: {secret_name} (from {key})")

    return secrets


def transform_env_var_to_secret_name(env_var_name: str) -> str:
    """
    Transform environment variable name to Key Vault secret name.

    Transformation rules:
    1. Remove LLMAVEN_SECRETS_ prefix
    2. Convert to lowercase
    3. Replace underscores with hyphens

    Args:
        env_var_name: Environment variable name (e.g., LLMAVEN_SECRETS_LITELLM_MASTER_KEY)

    Returns:
        Key Vault secret name (e.g., litellm-master-key)

    Examples:
        >>> transform_env_var_to_secret_name("LLMAVEN_SECRETS_LITELLM_MASTER_KEY")
        "litellm-master-key"
        >>> transform_env_var_to_secret_name("LLMAVEN_SECRETS_AZURE_OPENAI_API_KEY")
        "azure-openai-api-key"
    """
    prefix = "LLMAVEN_SECRETS_"

    if not env_var_name.startswith(prefix):
        raise ValueError(f"Environment variable must start with {prefix}")

    # Remove prefix and transform
    secret_name = env_var_name[len(prefix) :].lower().replace("_", "-")

    return secret_name


def create_secrets_from_environment(
    resource_group_name: Output[str],
    vault_name: Output[str],
    environment: str,
) -> Dict[str, azure_native.keyvault.Secret]:
    """
    Create Key Vault secrets from LLMAVEN_SECRETS_* environment variables.

    This function reads all environment variables with the LLMAVEN_SECRETS_ prefix
    and creates corresponding secrets in Azure Key Vault.

    Args:
        resource_group_name: Name of the resource group
        vault_name: Key Vault name
        environment: Environment name

    Returns:
        Dictionary mapping secret names to Secret resources
    """
    secrets = {}
    env_secrets = get_llmaven_secrets_from_env()

    if not env_secrets:
        pulumi.log.warn(
            "⚠ No LLMAVEN_SECRETS_* environment variables found. "
            "User-provided secrets will not be available in Key Vault."
        )

    for secret_name, secret_value in env_secrets.items():
        secret_resource = create_secret(
            resource_group_name=resource_group_name,
            vault_name=vault_name,
            secret_name=secret_name,
            secret_value=Output.secret(secret_value),
            environment=environment,
            tags={
                "ManagedBy": "Pulumi",
                "Source": "EnvironmentVariable",
            },
        )
        secrets[secret_name] = secret_resource

    pulumi.log.info(
        f"✓ Created {len(secrets)} user-provided secrets from environment variables"
    )

    return secrets


def grant_key_vault_access(
    key_vault: azure_native.keyvault.Vault,
    principal_id: Output[str],
    resource_group_name: Output[str],
    tenant_id: str,
    permissions_level: str = "read",
    principal_name: Optional[str] = None,
) -> azure_native.keyvault.AccessPolicy:
    """
    Grant a principal (user or managed identity) access to Key Vault using access policies.

    Args:
        key_vault: Key Vault resource
        principal_id: Principal ID (object ID) of the user or managed identity
        resource_group_name: Name of the resource group
        tenant_id: Azure AD tenant ID
        permissions_level: Permission level - "read" (get, list) or "write" (get, list, set, delete)
        principal_name: Optional name for the access policy resource (used for Pulumi resource naming)

    Returns:
        AccessPolicy resource

    Permission levels:
    - "read": Get and list secrets (for container apps reading secrets)
    - "write": Get, list, set, and delete secrets (for admin operations)
    """
    import pulumi_random as random

    # Generate a unique suffix for the access policy name
    suffix = random.RandomString(
        f"kv-access-policy-suffix-{principal_name}-{permissions_level}",
        length=8,
        special=False,
        upper=False,
    )

    # Define permissions based on level
    if permissions_level == "read":
        secret_permissions = [
            azure_native.keyvault.SecretPermissions.GET,
            azure_native.keyvault.SecretPermissions.LIST,
        ]
        description = "read access"
    elif permissions_level == "write":
        secret_permissions = [
            azure_native.keyvault.SecretPermissions.GET,
            azure_native.keyvault.SecretPermissions.LIST,
            azure_native.keyvault.SecretPermissions.SET,
            azure_native.keyvault.SecretPermissions.DELETE,
        ]
        description = "write access"
    else:
        pulumi.log.warn(
            f"Unknown permissions level: {permissions_level}. Using 'read' instead."
        )
        secret_permissions = [
            azure_native.keyvault.SecretPermissions.GET,
            azure_native.keyvault.SecretPermissions.LIST,
        ]
        description = "read access"

    # Create a descriptive resource name
    if principal_name:
        resource_name = f"kv-access-policy-{principal_name}-{permissions_level}"
    else:
        resource_name = f"kv-access-policy-{permissions_level}"

    # Add access policy to Key Vault
    # Note: This creates an AccessPolicy resource which adds to the existing policies
    def create_access_policy_args(args):
        vault_name_val, resource_group_val, principal_id_val, suffix_val = args
        return {
            "resource_group_name": resource_group_val,
            "vault_name": vault_name_val,
            "policy": azure_native.keyvault.AccessPolicyEntryArgs(
                tenant_id=tenant_id,
                object_id=principal_id_val,
                permissions=azure_native.keyvault.PermissionsArgs(
                    secrets=secret_permissions,
                ),
            ),
        }

    access_policy_args = Output.all(
        key_vault.name, resource_group_name, principal_id, suffix.result
    ).apply(create_access_policy_args)

    access_policy = azure_native.keyvault.AccessPolicy(
        resource_name,
        resource_group_name=access_policy_args["resource_group_name"],
        vault_name=access_policy_args["vault_name"],
        policy=access_policy_args["policy"],
    )

    pulumi.log.info(f"✓ Granted {description} to Key Vault for principal")

    return access_policy


def get_secret_reference(
    key_vault_uri: Output[str],
    secret_name: str,
) -> Output[str]:
    """
    Generate Key Vault secret reference URL for Container Apps.

    Args:
        key_vault_uri: Key Vault URI (e.g., https://kv-name.vault.azure.net/)
        secret_name: Secret name

    Returns:
        Secret reference URL (e.g., https://kv-name.vault.azure.net/secrets/secret-name)
    """
    return key_vault_uri.apply(lambda uri: f"{uri}secrets/{secret_name}")
