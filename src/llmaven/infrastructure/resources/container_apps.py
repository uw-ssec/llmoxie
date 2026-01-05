"""Azure Container Apps Environment resource module.

This module creates and configures Azure Container Apps Environment with
VNet integration, monitoring, and workload profiles.
"""

from typing import Dict, Optional
import datetime

import pulumi
import pulumi_azure_native as azure_native
from pulumi import Output

from ..config.schema import LLMavenConfig


def create_container_apps_environment(
    resource_group_name: Output[str],
    location: str,
    container_apps_subnet_id: Output[str],
    log_analytics_workspace: azure_native.operationalinsights.Workspace,
    config: LLMavenConfig,
    tags: Dict[str, str],
) -> azure_native.app.ManagedEnvironment:
    """
    Create Azure Container Apps Managed Environment.

    Args:
        resource_group_name: Name of the resource group
        location: Azure region
        container_apps_subnet_id: Subnet ID for Container Apps
        log_analytics_workspace: Log Analytics workspace resource for monitoring
        config: LLMaven configuration
        tags: Resource tags

    Returns:
        ManagedEnvironment resource
    """
    project_name = config.project.name
    environment = config.project.environment

    # Environment name
    env_name = f"{project_name}-containerenv-{environment}"

    # Create Container Apps Environment
    managed_environment = azure_native.app.ManagedEnvironment(
        f"container-apps-env-{environment}",
        resource_group_name=resource_group_name,
        environment_name=env_name,
        location=location,
        tags=tags,
        # VNet configuration
        vnet_configuration=azure_native.app.VnetConfigurationArgs(
            infrastructure_subnet_id=container_apps_subnet_id,
            internal=False,  # External ingress enabled (set to True for private environments)
        ),
        # Monitoring configuration
        app_logs_configuration=(
            azure_native.app.AppLogsConfigurationArgs(
                destination="log-analytics",
                log_analytics_configuration=azure_native.app.LogAnalyticsConfigurationArgs(
                    customer_id=log_analytics_workspace.customer_id,
                    shared_key=pulumi.Output.all(
                        resource_group_name, log_analytics_workspace.name
                    ).apply(
                        lambda args: azure_native.operationalinsights.get_shared_keys(
                            resource_group_name=args[0],
                            workspace_name=args[1],
                        ).primary_shared_key
                    ),
                ),
            )
            if log_analytics_workspace
            else None
        ),
        # Zone redundancy for production
        zone_redundant=True if environment == "prod" else False,
        # Workload profiles - omitted to use default Consumption profile
        # Consumption is the default workload profile type (serverless, pay-per-use)
        # No need to explicitly specify it
    )

    pulumi.export(
        f"container_apps_environment_name_{environment}",
        managed_environment.name,
    )
    pulumi.export(
        f"container_apps_environment_id_{environment}",
        managed_environment.id,
    )
    pulumi.export(
        f"container_apps_default_domain_{environment}",
        managed_environment.default_domain,
    )

    return managed_environment


def create_container_app_with_key_vault_secrets(
    resource_group_name: Output[str],
    location: str,
    managed_environment_id: Output[str],
    key_vault_uri: Output[str],
    app_name: str,
    container_image: str,
    container_port: int,
    cpu: float,
    memory: str,
    min_replicas: int,
    max_replicas: int,
    env_vars: Optional[Dict[str, str]] = None,
    key_vault_secret_refs: Optional[Dict[str, str]] = None,
    inline_secrets: Optional[Dict[str, str]] = None,
    command_args: Optional[list] = None,
    volumes: Optional[list] = None,
    volume_mounts: Optional[list] = None,
    managed_identity_id: Optional[Output[str]] = None,
    environment: str = "dev",
    tags: Optional[Dict[str, str]] = None,
    enable_ingress: bool = True,
    ingress_external: bool = True,
) -> azure_native.app.ContainerApp:
    """
    Create Azure Container App with Key Vault secret references.

    This function creates a Container App that references secrets stored in Azure Key Vault
    using managed identity authentication.

    Args:
        resource_group_name: Name of the resource group
        location: Azure region
        managed_environment_id: Container Apps Environment ID
        key_vault_uri: Key Vault URI (e.g., https://kv-name.vault.azure.net/)
        app_name: Name of the container app
        container_image: Container image URL
        container_port: Container port
        cpu: CPU cores
        memory: Memory allocation
        min_replicas: Minimum replicas
        max_replicas: Maximum replicas
        env_vars: Non-sensitive environment variables
        key_vault_secret_refs: Map of env var name to Key Vault secret name
        inline_secrets: Map of secret name to secret value (for non-Key Vault secrets like config files)
        command_args: Command arguments to pass to the container (e.g., ["--config", "/app/config.yaml"])
        volumes: List of Volume objects for the container app
        volume_mounts: List of VolumeMount objects for the container
        managed_identity_id: Resource ID of user-assigned managed identity with Key Vault access (optional)
        environment: Environment name
        tags: Resource tags
        enable_ingress: Enable HTTP ingress
        ingress_external: Make ingress externally accessible

    Returns:
        ContainerApp resource
    """
    # Build environment variables list
    env_list = []

    # Add refresh trigger environment variable
    env_list.append(
        azure_native.app.EnvironmentVarArgs(
            name="REFRESH_TRIGGER",
            value=datetime.datetime.utcnow().isoformat(),
        )
    )

    # Add non-sensitive environment variables
    if env_vars:
        for key, value in env_vars.items():
            env_list.append(
                azure_native.app.EnvironmentVarArgs(
                    name=key,
                    value=value,
                )
            )

    # Add Key Vault secret references as environment variables
    if key_vault_secret_refs:
        for env_var_name, secret_name in key_vault_secret_refs.items():
            env_list.append(
                azure_native.app.EnvironmentVarArgs(
                    name=env_var_name.upper().replace("-", "_"),
                    secret_ref=secret_name,
                )
            )

    # Build secrets list with Key Vault references
    secrets_list = []
    if key_vault_secret_refs:
        for secret_name in key_vault_secret_refs.values():
            # Fallback: construct URI from key_vault_uri (legacy behavior)
            secret_uri = key_vault_uri.apply(
                lambda vault_uri,
                sn=secret_name: f"{vault_uri.rstrip('/')}/secrets/{sn}"
            )

            # Use managed identity resource ID if provided, otherwise use system-assigned identity
            identity_ref = managed_identity_id if managed_identity_id else "system"

            secrets_list.append(
                azure_native.app.SecretArgs(
                    name=secret_name, key_vault_url=secret_uri, identity=identity_ref
                )
            )

    # Add inline secrets (non-Key Vault secrets like config files)
    if inline_secrets:
        for secret_name, secret_value in inline_secrets.items():
            # Check if secret already exists in list
            existing_names = [
                s.name if hasattr(s, "name") else None for s in secrets_list
            ]
            if secret_name not in existing_names:
                secrets_list.append(
                    azure_native.app.SecretArgs(
                        name=secret_name,
                        value=secret_value,
                    )
                )

    # Ingress configuration
    ingress_config = None
    if enable_ingress:
        ingress_config = azure_native.app.IngressArgs(
            external=ingress_external,
            target_port=container_port,
            transport="auto",
            allow_insecure=False,
            traffic=[
                azure_native.app.TrafficWeightArgs(
                    latest_revision=True,
                    weight=100,
                )
            ],
        )

    # Create Container App
    container_app = azure_native.app.ContainerApp(
        f"container-app-{app_name}-{environment}",
        resource_group_name=resource_group_name,
        container_app_name=f"{app_name}-{environment}",
        location=location,
        tags=tags or {},
        managed_environment_id=managed_environment_id,
        # Configuration
        configuration=azure_native.app.ConfigurationArgs(
            ingress=ingress_config,
            secrets=secrets_list if secrets_list else None,
            active_revisions_mode="Single",
        ),
        # Template
        template=azure_native.app.TemplateArgs(
            containers=[
                azure_native.app.ContainerArgs(
                    name=app_name,
                    image=container_image,
                    args=command_args if command_args else None,
                    volume_mounts=volume_mounts if volume_mounts else None,
                    resources=azure_native.app.ContainerResourcesArgs(
                        cpu=cpu,
                        memory=memory,
                    ),
                    env=env_list if env_list else None,
                )
            ],
            scale=azure_native.app.ScaleArgs(
                min_replicas=min_replicas,
                max_replicas=max_replicas,
                rules=[
                    azure_native.app.ScaleRuleArgs(
                        name="http-scaling",
                        http=azure_native.app.HttpScaleRuleArgs(
                            metadata={
                                "concurrentRequests": "50",
                            },
                        ),
                    ),
                ],
            ),
            volumes=volumes if volumes else None,
        ),
        # Managed identity configuration
        # Use system-assigned if no user-assigned identity provided
        # Otherwise, use both system and user-assigned (for backward compatibility)
        identity=azure_native.app.ManagedServiceIdentityArgs(
            type=(
                azure_native.app.ManagedServiceIdentityType.SYSTEM_ASSIGNED_USER_ASSIGNED
                if managed_identity_id
                else azure_native.app.ManagedServiceIdentityType.SYSTEM_ASSIGNED
            ),
            user_assigned_identities=(
                [managed_identity_id] if managed_identity_id else None
            ),
        ),
    )

    # Export outputs
    pulumi.export(
        f"container_app_{app_name}_name_{environment}",
        container_app.name,
    )
    pulumi.export(
        f"container_app_{app_name}_fqdn_{environment}",
        container_app.configuration.apply(
            lambda config: config.ingress.fqdn if config and config.ingress else None
        ),
    )
    pulumi.export(
        f"container_app_{app_name}_url_{environment}",
        container_app.configuration.apply(
            lambda config: (
                f"https://{config.ingress.fqdn}"
                if config and config.ingress and config.ingress.fqdn
                else None
            )
        ),
    )

    return container_app
