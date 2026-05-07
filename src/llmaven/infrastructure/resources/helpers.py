"""Helper functions for creating Azure resources with LLMaven configuration."""

from pathlib import Path
from typing import Dict, List, Optional

import pulumi
import pulumi_azure_native as azure_native
from pulumi import Output

from .container_apps import create_container_app_with_key_vault_secrets


def create_user_assigned_managed_identity(
    name: str,
    resource_group_name: Output[str],
    location: str,
    tags: Optional[Dict[str, str]] = None,
) -> azure_native.managedidentity.UserAssignedIdentity:
    """Create a user-assigned managed identity.

    Args:
        name: Managed identity name
        resource_group_name: Resource group name
        location: Azure region
        tags: Resource tags

    Returns:
        UserAssignedIdentity resource
    """
    identity = azure_native.managedidentity.UserAssignedIdentity(
        f"managed-identity-{name}",
        resource_name_=name,
        resource_group_name=resource_group_name,
        location=location,
        tags=tags,
    )

    return identity


def create_resource_group(
    name: str,
    location: str,
    tags: Optional[Dict[str, str]] = None,
) -> azure_native.resources.ResourceGroup:
    """Create an Azure Resource Group.

    Args:
        name: Resource group name
        location: Azure region
        tags: Resource tags

    Returns:
        ResourceGroup resource
    """
    return azure_native.resources.ResourceGroup(
        "resource-group",
        resource_group_name=name,
        location=location,
        tags=tags,
    )


def create_virtual_network(
    name: str,
    resource_group_name: Output[str],
    location: str,
    address_space: str,
    tags: Optional[Dict[str, str]] = None,
) -> azure_native.network.VirtualNetwork:
    """Create an Azure Virtual Network.

    Args:
        name: Virtual network name
        resource_group_name: Resource group name
        location: Azure region
        address_space: VNet address space (e.g., "10.0.0.0/16")
        tags: Resource tags

    Returns:
        VirtualNetwork resource
    """
    return azure_native.network.VirtualNetwork(
        "vnet",
        virtual_network_name=name,
        resource_group_name=resource_group_name,
        location=location,
        address_space=azure_native.network.AddressSpaceArgs(
            address_prefixes=[address_space],
        ),
        tags=tags,
    )


def create_log_analytics_workspace(
    name: str,
    resource_group_name: Output[str],
    location: str,
    retention_days: int = 90,
    tags: Optional[Dict[str, str]] = None,
) -> azure_native.operationalinsights.Workspace:
    """Create a Log Analytics Workspace for monitoring.

    Args:
        name: Workspace name
        resource_group_name: Resource group name
        location: Azure region
        retention_days: Data retention in days
        tags: Resource tags

    Returns:
        Workspace resource
    """
    return azure_native.operationalinsights.Workspace(
        "log-analytics",
        workspace_name=name,
        resource_group_name=resource_group_name,
        location=location,
        retention_in_days=retention_days,
        sku=azure_native.operationalinsights.WorkspaceSkuArgs(
            name="PerGB2018",
        ),
        tags=tags,
    )


def create_postgres_flexible_server(
    resource_group_name: Output[str],
    location: str,
    sku_name: str,
    storage_size_gb: int,
    postgresql_version: str,
    subnet_id: Output[str],
    high_availability: bool,
    backup_retention_days: int,
    geo_redundant_backup: bool,
    databases: List[str],
    key_vault: azure_native.keyvault.Vault,
    tags: Optional[Dict[str, str]] = None,
) -> azure_native.dbforpostgresql.Server:
    """Create a PostgreSQL Flexible Server with databases.

    This is a wrapper function that provides a simplified interface for the
    database creation functions from database.py module. It is not fully
    implemented and exists for API compatibility.

    Args:
        resource_group_name: Resource group name
        location: Azure region
        sku_name: SKU name (e.g., "B_Standard_B1ms")
        storage_size_gb: Storage size in GB
        postgresql_version: PostgreSQL version
        subnet_id: Subnet ID for VNet integration
        high_availability: Enable high availability
        backup_retention_days: Backup retention days
        geo_redundant_backup: Enable geo-redundant backup
        databases: List of database names to create
        key_vault: Key Vault for storing admin password
        tags: Resource tags

    Returns:
        PostgreSQL Server resource

    Note:
        This function signature does not match the actual create_postgres_server
        from database.py which requires vnet_id, config, and admin_password.
        The caller (__main__.py) should be updated to use create_postgres_server
        and create_databases directly from database.py module.
    """
    # This function cannot be properly implemented without config and admin_password
    # which are required by the actual create_postgres_server function
    raise NotImplementedError(
        "create_postgres_flexible_server is a deprecated helper function. "
        "Please use create_postgres_server from database.py module instead, "
        "which requires: vnet_id, postgres_subnet_id, config (LLMavenConfig), "
        "admin_password, and tags."
    )


def create_mlflow_app(
    name: str,
    resource_group_name: Output[str],
    location: str,
    container_env_id: Output[str],
    image: str,
    port: int,
    cpu: float,
    memory: str,
    min_replicas: int,
    max_replicas: int,
    env_vars: Dict[str, str],
    key_vault: azure_native.keyvault.Vault,
    key_vault_secret_refs: Dict[str, str],
    managed_identity_id: Optional[Output[str]] = None,
    tags: Optional[Dict[str, str]] = None,
    opts: Optional[pulumi.ResourceOptions] = None,
) -> azure_native.app.ContainerApp:
    """Create MLflow Container App.

    Args:
        name: Container app name
        resource_group_name: Resource group name
        location: Azure region
        container_env_id: Container Apps Environment ID
        image: Container image URL
        port: Container port
        cpu: CPU allocation
        memory: Memory allocation
        min_replicas: Minimum replicas
        max_replicas: Maximum replicas
        env_vars: Environment variables
        key_vault: Key Vault for secrets
        managed_identity_id: Resource ID of user-assigned managed identity with Key Vault access
        tags: Resource tags

    Returns:
        ContainerApp resource

    Note:
        This function expects the following secrets to already exist in Key Vault:
        - "db-connection-string-mlflow-db": Database connection string for MLflow database
        - "mlflow-artifact-root": Azure Blob Storage artifact root URL (wasbs://...)
        - "storage-connection-string": Azure Storage connection string for authentication

        The MLflow container app will use:
        - PostgreSQL backend for tracking metadata (MLFLOW_BACKEND_STORE_URI)
        - Azure Blob Storage for artifact storage (MLFLOW_DEFAULT_ARTIFACT_ROOT)
        - Azure Storage connection string for blob authentication (AZURE_STORAGE_CONNECTION_STRING)
    """
    # Extract environment from name if present (format: "project-mlflow" or "project-env-mlflow")
    # Default to "dev" if not found
    environment = "dev"
    if "-" in name:
        parts = name.split("-")
        # Try to find environment in the name parts
        for part in parts:
            if part in ["dev", "staging", "prod", "test"]:
                environment = part
                break

    # key_vault_secret_refs is passed as an argument

    # Create container app
    return create_container_app_with_key_vault_secrets(
        app_name=name,
        resource_group_name=resource_group_name,
        location=location,
        managed_environment_id=container_env_id,
        key_vault_uri=key_vault.properties.vault_uri,
        container_image=image,
        container_port=port,
        cpu=cpu,
        memory=memory,
        min_replicas=min_replicas,
        max_replicas=max_replicas,
        env_vars=env_vars,
        key_vault_secret_refs=key_vault_secret_refs,
        managed_identity_id=managed_identity_id,
        environment=environment,
        tags=tags,
        enable_ingress=True,
        ingress_external=True,
        opts=opts,
    )


def create_litellm_app(
    name: str,
    resource_group_name: Output[str],
    location: str,
    container_env_id: Output[str],
    container_env_name: Output[str],
    image: str,
    port: int,
    cpu: float,
    memory: str,
    min_replicas: int,
    max_replicas: int,
    env_vars: Dict[str, str],
    key_vault: azure_native.keyvault.Vault,
    key_vault_secret_refs: Dict[str, str],
    config_file: Optional[str] = None,
    managed_identity_id: Optional[Output[str]] = None,
    tags: Optional[Dict[str, str]] = None,
    opts: Optional[pulumi.ResourceOptions] = None,
    extra_modules: Optional[List[Path]] = None,
) -> azure_native.app.ContainerApp:
    """Create LiteLLM Container App.

    Args:
        name: Container app name
        resource_group_name: Resource group name
        location: Azure region
        container_env_id: Container Apps Environment ID
        container_env_name: Container Apps Environment name
        image: Container image URL
        port: Container port
        cpu: CPU allocation
        memory: Memory allocation
        min_replicas: Minimum replicas
        max_replicas: Maximum replicas
        env_vars: Environment variables
        key_vault: Key Vault for secrets
        config_file: Path to LiteLLM config file (will be read and mounted as a secret volume)
        managed_identity_id: Resource ID of user-assigned managed identity with Key Vault access
        tags: Resource tags
        opts: Pulumi resource options
        extra_modules: List of additional local Python modules to read and mount as secrets (for custom callbacks, etc.)

    Returns:
        ContainerApp resource

    Note:
        This function expects the following secrets to already exist in Key Vault:
        - "db-connection-string-litellm-db": Database connection string for LiteLLM database
        - "litellm-master-key": LiteLLM master key
        - "azure-api-base": Azure OpenAI API base URL
        - "azure-api-key": Azure OpenAI API key
        - "azure-api-version": Azure OpenAI API version
        - "mlflow-experiment-name": MLflow experiment name
        - "mlflow-tracking-uri": MLflow tracking URI
        These secrets should be created before calling this function.

        If config_file is provided:
        - The config file content is read and stored as an inline secret
        - A secret volume is created mounting the config as /app/config/config.yaml
        - The container is configured with --config /app/config/config.yaml argument
    """
    # Extract environment from name if present (format: "project-litellm" or "project-env-litellm")
    # Default to "dev" if not found
    environment = "dev"
    if "-" in name:
        parts = name.split("-")
        # Try to find environment in the name parts
        for part in parts:
            if part in ["dev", "staging", "prod", "test"]:
                environment = part
                break

    # key_vault_secret_refs is passed as an argument

    # Prepare volumes, volume mounts, and inline secrets if config file is provided
    volumes = None
    volume_mounts = None
    command_args = None
    inline_secrets = None

    if config_file:

        def read_file_content(file_path: Path) -> str:
            """Read file content and return as string."""
            if not file_path.exists():
                raise FileNotFoundError(f"File not found: {file_path}")
            with open(file_path, "r") as f:
                return f.read()

        # Both config.yaml and custom modules need to be mounted into the same volume
        # so LiteLLM can find the callback module in the same directory as config
        inline_secrets = {}
        secret_volume_items = []
        all_files = (extra_modules or []) + [Path(config_file)]

        for file_path in all_files:
            secret_name = (
                file_path.name.replace(".", "-").replace(" ", "-").replace("_", "-")
            )
            inline_secrets[secret_name] = read_file_content(file_path)
            secret_volume_items.append(
                azure_native.app.SecretVolumeItemArgs(
                    secret_ref=secret_name,
                    path=file_path.name,
                )
            )

        # Configure volume and volume mount that references the secret
        volumes = [
            azure_native.app.VolumeArgs(
                name="litellm-config-volume",
                storage_type="Secret",
                secrets=secret_volume_items,
            )
        ]

        volume_mounts = [
            azure_native.app.VolumeMountArgs(
                volume_name="litellm-config-volume",
                mount_path="/app/config",  # Mount directory
            )
        ]

        # LiteLLM expects: --config /app/config/config.yaml
        command_args = ["--config", "/app/config/config.yaml"]

    # Create container app
    return create_container_app_with_key_vault_secrets(
        app_name=name,
        resource_group_name=resource_group_name,
        location=location,
        managed_environment_id=container_env_id,
        key_vault_uri=key_vault.properties.vault_uri,
        container_image=image,
        container_port=port,
        cpu=cpu,
        memory=memory,
        min_replicas=min_replicas,
        max_replicas=max_replicas,
        env_vars=env_vars,
        key_vault_secret_refs=key_vault_secret_refs,
        inline_secrets=inline_secrets,
        managed_identity_id=managed_identity_id,
        command_args=command_args,
        volumes=volumes,
        volume_mounts=volume_mounts,
        environment=environment,
        tags=tags,
        enable_ingress=True,
        ingress_external=True,
        opts=opts,
    )
