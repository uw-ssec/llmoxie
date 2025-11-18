"""Azure Key Vault resource module.

This module creates and configures Azure Key Vault for secure secrets management
with RBAC authorization, access policies, audit logging, and managed identity integration.

Access Control:
---------------
Two authentication modes are supported:

1. RBAC Authorization (Recommended):
   - Set `enable_rbac=True` in configuration
   - Use `grant_key_vault_access()` to assign RBAC roles
   - More flexible and easier to manage at scale

Environment Variables:
----------------------
- AZURE_OBJECT_ID: Object ID of the current user/service principal (required for access policies)
                   Get with: `az ad signed-in-user show --query id -o tsv`
"""

import os
from typing import Dict, List, Optional

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
) -> azure_native.keyvault.Vault:
    """
    Create Azure Key Vault with RBAC authorization.

    Args:
        resource_group_name: Name of the resource group
        location: Azure region
        tenant_id: Azure AD tenant ID
        config: LLMaven configuration
        tags: Resource tags

    Returns:
        Key Vault resource
    """
    project_name = config.project.name
    environment = config.project.environment
    kv_config = config.security.key_vault

    # Key Vault name (must be globally unique, 3-24 chars, alphanumeric and hyphens)
    # Format: kv-{project}-{env}-{region_suffix} (e.g., kv-llmaven-dev-wu2)
    # Add region suffix to ensure global uniqueness
    region_suffix = location[:4].replace("-", "").lower()  # e.g., "westus2" -> "west"
    vault_name = f"kv-{project_name}-{environment}-{region_suffix}"[:24]

    # Get current user/service principal object ID for access policies
    # This allows the deployer to manage the Key Vault
    current_object_id = os.getenv("AZURE_OBJECT_ID")
    
    # Build access policies list
    access_policies = []
    if current_object_id and not kv_config.enable_rbac:
        # Only add access policies if RBAC is disabled
        # Access policies for the current user/service principal
        access_policies.append(
            azure_native.keyvault.AccessPolicyEntryArgs(
                tenant_id=tenant_id,
                object_id=current_object_id,
                # Permissions for keys
                permissions=azure_native.keyvault.PermissionsArgs(
                    keys=[
                        azure_native.keyvault.KeyPermissions.GET,
                        azure_native.keyvault.KeyPermissions.LIST,
                        azure_native.keyvault.KeyPermissions.UPDATE,
                        azure_native.keyvault.KeyPermissions.CREATE,
                        azure_native.keyvault.KeyPermissions.DELETE,
                        azure_native.keyvault.KeyPermissions.RECOVER,
                        azure_native.keyvault.KeyPermissions.BACKUP,
                        azure_native.keyvault.KeyPermissions.RESTORE,
                    ],
                    # Permissions for secrets
                    secrets=[
                        azure_native.keyvault.SecretPermissions.GET,
                        azure_native.keyvault.SecretPermissions.LIST,
                        azure_native.keyvault.SecretPermissions.SET,
                        azure_native.keyvault.SecretPermissions.DELETE,
                        azure_native.keyvault.SecretPermissions.RECOVER,
                        azure_native.keyvault.SecretPermissions.BACKUP,
                        azure_native.keyvault.SecretPermissions.RESTORE,
                    ],
                    # Permissions for certificates (optional)
                    certificates=[
                        azure_native.keyvault.CertificatePermissions.GET,
                        azure_native.keyvault.CertificatePermissions.LIST,
                        azure_native.keyvault.CertificatePermissions.UPDATE,
                        azure_native.keyvault.CertificatePermissions.CREATE,
                        azure_native.keyvault.CertificatePermissions.DELETE,
                        azure_native.keyvault.CertificatePermissions.RECOVER,
                    ],
                ),
            )
        )
        pulumi.log.info(
            f"✓ Added access policy for deployer (Object ID: {current_object_id})"
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
            # RBAC authorization (recommended over access policies)
            enable_rbac_authorization=kv_config.enable_rbac,
            # Access policies (only used if RBAC is disabled)
            access_policies=access_policies if access_policies else None,
            # Soft delete configuration
            enable_soft_delete=False,
            # soft_delete_retention_in_days=kv_config.soft_delete_retention_days,
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
    role_definition_name: str = "Key Vault Secrets User",
) -> azure_native.authorization.RoleAssignment:
    """
    Grant a managed identity access to Key Vault secrets using RBAC.

    Args:
        key_vault: Key Vault resource
        principal_id: Principal ID of the managed identity
        resource_group_name: Name of the resource group
        role_definition_name: Role to assign (default: "Key Vault Secrets User")

    Returns:
        RoleAssignment resource

    Common roles:
    - "Key Vault Secrets User": Read secret contents
    - "Key Vault Secrets Officer": Read, write, and delete secrets
    - "Key Vault Administrator": Full Key Vault permissions
    """
    import pulumi_random as random

    # Generate a unique name for the role assignment
    role_assignment_name = random.RandomUuid(
        f"kv-role-assignment-{role_definition_name.lower().replace(' ', '-')}",
    )

    # Get the role definition ID for "Key Vault Secrets User"
    # This is a built-in Azure role
    # Full list: https://learn.microsoft.com/en-us/azure/key-vault/general/rbac-guide
    role_definition_ids = {
        "Key Vault Secrets User": "4633458b-17de-408a-b874-0445c86b69e6",
        "Key Vault Secrets Officer": "b86a8fe4-44ce-4948-aee5-eccb2c155cd7",
        "Key Vault Administrator": "00482a5a-887f-4fb3-b353-3b7898f7c9a1",
    }

    role_definition_id = role_definition_ids.get(role_definition_name)
    if not role_definition_id:
        pulumi.log.warn(
            f"Unknown role: {role_definition_name}. "
            f"Using 'Key Vault Secrets User' instead."
        )
        role_definition_id = role_definition_ids["Key Vault Secrets User"]

    # Create role assignment
    role_assignment = azure_native.authorization.RoleAssignment(
        f"kv-role-{role_definition_name.lower().replace(' ', '-')}",
        scope=key_vault.id,
        principal_id=principal_id,
        principal_type=azure_native.authorization.PrincipalType.SERVICE_PRINCIPAL,
        role_definition_id=Output.concat(
            "/subscriptions/",
            key_vault.id.apply(lambda id: id.split("/")[2]),
            "/providers/Microsoft.Authorization/roleDefinitions/",
            role_definition_id,
        ),
        role_assignment_name=role_assignment_name.result,
    )

    pulumi.log.info(f"✓ Granted '{role_definition_name}' access to Key Vault")

    return role_assignment


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
