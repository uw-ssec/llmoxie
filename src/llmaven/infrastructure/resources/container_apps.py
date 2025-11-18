"""Azure Container Apps Environment resource module.

This module creates and configures Azure Container Apps Environment with
VNet integration, monitoring, and workload profiles.
"""

from typing import Dict, Optional

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


def create_container_app(
    resource_group_name: Output[str],
    location: str,
    managed_environment_id: Output[str],
    app_name: str,
    container_image: str,
    container_port: int,
    cpu: float,
    memory: str,
    min_replicas: int,
    max_replicas: int,
    env_vars: Optional[Dict[str, str]] = None,
    secrets: Optional[Dict[str, Output[str]]] = None,
    environment: str = "dev",
    tags: Optional[Dict[str, str]] = None,
    enable_ingress: bool = True,
    ingress_external: bool = True,
) -> azure_native.app.ContainerApp:
    """
    Create Azure Container App.

    Args:
        resource_group_name: Name of the resource group
        location: Azure region
        managed_environment_id: Container Apps Environment ID
        app_name: Name of the container app
        container_image: Container image URL
        container_port: Container port
        cpu: CPU cores (0.25, 0.5, 0.75, 1.0, etc.)
        memory: Memory allocation (e.g., "0.5Gi", "1Gi", "2Gi")
        min_replicas: Minimum number of replicas
        max_replicas: Maximum number of replicas
        env_vars: Non-sensitive environment variables
        secrets: Sensitive environment variables (from Key Vault)
        environment: Environment name
        tags: Resource tags
        enable_ingress: Enable HTTP ingress
        ingress_external: Make ingress externally accessible

    Returns:
        ContainerApp resource
    """
    # Build environment variables list
    env_list = []

    # Add non-sensitive environment variables
    if env_vars:
        for key, value in env_vars.items():
            env_list.append(
                azure_native.app.EnvironmentVarArgs(
                    name=key,
                    value=value,
                )
            )

    # Add secrets as environment variables
    if secrets:
        for key, secret_ref in secrets.items():
            env_list.append(
                azure_native.app.EnvironmentVarArgs(
                    name=key.upper().replace("-", "_"),
                    secret_ref=key,  # Reference to secret name
                )
            )

    # Build secrets list for Container App
    secrets_list = []
    if secrets:
        for secret_name, secret_value in secrets.items():
            secrets_list.append(
                azure_native.app.SecretArgs(
                    name=secret_name,
                    value=secret_value,  # Can be from Key Vault or direct value
                )
            )

    # Ingress configuration
    ingress_config = None
    if enable_ingress:
        ingress_config = azure_native.app.IngressArgs(
            external=ingress_external,
            target_port=container_port,
            transport="auto",  # Supports both HTTP/1 and HTTP/2
            allow_insecure=False,  # Enforce HTTPS
            traffic=[
                # 100% traffic to latest revision
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
            # secrets=secrets_list if secrets_list else None,
            # Active revisions mode (single revision at a time)
            active_revisions_mode="Single",
        ),
        # Template (container specification)
        template=azure_native.app.TemplateArgs(
            containers=[
                azure_native.app.ContainerArgs(
                    name=app_name,
                    image=container_image,
                    resources=azure_native.app.ContainerResourcesArgs(
                        cpu=cpu,
                        memory=memory,
                    ),
                    # env=env_list if env_list else None,
                )
            ],
            # Scaling configuration
            scale=azure_native.app.ScaleArgs(
                min_replicas=min_replicas,
                max_replicas=max_replicas,
                rules=[
                    # HTTP-based autoscaling
                    azure_native.app.ScaleRuleArgs(
                        name="http-scaling",
                        http=azure_native.app.HttpScaleRuleArgs(
                            metadata={
                                "concurrentRequests": "50",  # Scale up when >50 concurrent requests
                            },
                        ),
                    ),
                ],
            ),
        ),
        # System-assigned managed identity for Key Vault access
        identity=azure_native.app.ManagedServiceIdentityArgs(
            type=azure_native.app.ManagedServiceIdentityType.SYSTEM_ASSIGNED,
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
        environment: Environment name
        tags: Resource tags
        enable_ingress: Enable HTTP ingress
        ingress_external: Make ingress externally accessible

    Returns:
        ContainerApp resource
    """
    # Build environment variables list
    env_list = []

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
    secrets_list = None
    if key_vault_secret_refs:
        # We need to collect all secret URIs first, then create the secrets list
        # This ensures that Output values are properly resolved
        def create_secrets_list(vault_uri: str):
            """Create secrets list with resolved Key Vault URI."""
            result = []
            for secret_name in key_vault_secret_refs.values():
                # Build Key Vault secret URL - ensure no trailing slash in vault_uri
                vault_base = vault_uri.rstrip('/')
                secret_uri = f"{vault_base}/secrets/{secret_name}"

                result.append(
                    azure_native.app.SecretArgs(
                        name=secret_name,
                        key_vault_url=secret_uri,
                        identity="system",  # Use system-assigned managed identity
                    )
                )
            return result

        # Apply the function to the key_vault_uri Output
        secrets_list = key_vault_uri.apply(create_secrets_list)

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
            # secrets=secrets_list,
            active_revisions_mode="Single",
        ),
        # Template
        template=azure_native.app.TemplateArgs(
            containers=[
                azure_native.app.ContainerArgs(
                    name=app_name,
                    image=container_image,
                    resources=azure_native.app.ContainerResourcesArgs(
                        cpu=cpu,
                        memory=memory,
                    ),
                    # env=env_list if env_list else None,
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
        ),
        # System-assigned managed identity
        identity=azure_native.app.ManagedServiceIdentityArgs(
            type=azure_native.app.ManagedServiceIdentityType.SYSTEM_ASSIGNED,
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
