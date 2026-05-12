"""Pulumi program entry point for LLMaven infrastructure.

This module provides the main entry point for deploying LLMaven infrastructure
using Pulumi. It reads configuration from the llmaven-config.yaml file and
orchestrates the creation of Azure resources including:
- Resource groups and virtual networks
- Key Vault for secrets management
- PostgreSQL Flexible Server and databases
- Storage accounts and blob containers
- Container Apps for MLflow and LiteLLM
- Log Analytics for monitoring
"""

from pathlib import Path


def create_pulumi_program(config_path: Path):
    """Create an inline Pulumi program for infrastructure deployment.

    This function creates and returns a Pulumi program that deploys the complete
    LLMaven infrastructure stack based on the provided configuration file.

    Args:
        config_path: Path to the LLMaven YAML configuration file

    Returns:
        A callable Pulumi program function that can be executed by Pulumi
    """

    def llmaven_infra():
        """Main Pulumi program that deploys all LLMaven infrastructure resources.

        This function orchestrates the deployment of Azure resources in the following order:
        1. Resource Group and Virtual Network with subnets
        2. Key Vault for secrets management
        3. Secrets Manager initialization
        4. PostgreSQL Flexible Server and databases
        5. Storage Account with blob containers
        6. Log Analytics Workspace (if enabled)
        7. Container Apps Environment
        8. Managed Identities for services
        9. Container Apps (MLflow and LiteLLM)
        """
        import os

        import pulumi
        import pulumi_azure_native as azure_native

        from llmaven.infrastructure.config.loader import ConfigLoadError, load_config
        from llmaven.infrastructure.resources import (
            SecretsManager,
            create_backup_job,
            create_container_apps_environment,
            create_databases,
            create_key_vault,
            create_litellm_app,
            create_log_analytics_workspace,
            create_mlflow_app,
            create_postgres_server,
            create_storage_account,
            create_virtual_network,
        )

        # Load configuration
        try:
            config = load_config(config_path)
            pulumi.log.info(f"✓ Loaded configuration from: {config_path}")
        except ConfigLoadError as e:
            pulumi.log.error(f"Failed to load configuration: {e}")
            raise

        # Project information
        project_name = config.project.name
        environment = config.project.environment
        location = config.project.location
        resource_group = config.azure.resource_group
        stack_name = f"{project_name}-{environment}"

        pulumi.log.info(f"Deploying stack: {stack_name}")
        pulumi.log.info(f"Environment: {environment}")
        pulumi.log.info(f"Location: {location}")

        # 1. Create Virtual Network
        pulumi.log.info("Creating virtual network...")
        vnet = create_virtual_network(
            name=f"vnet-{stack_name}",
            resource_group_name=resource_group,
            location=location,
            address_space=config.networking.vnet_address_space,
            tags=config.tags,
        )

        # Create subnets
        pulumi.log.info("Setting up for container apps subnet...")
        container_apps_subnet = azure_native.network.Subnet(
            "container-apps-subnet",
            resource_group_name=resource_group,
            virtual_network_name=vnet.name,
            subnet_name="container-apps-subnet",
            address_prefix=config.networking.container_apps_subnet,
            delegations=[
                azure_native.network.DelegationArgs(
                    name="container-apps-delegation",
                    service_name="Microsoft.App/environments",
                )
            ],
        )

        pulumi.log.info("Setting up for postgres subnet...")
        postgres_subnet = azure_native.network.Subnet(
            "postgres-subnet",
            resource_group_name=resource_group,
            virtual_network_name=vnet.name,
            subnet_name="postgres-subnet",
            address_prefix=config.networking.postgres_subnet,
            delegations=[
                azure_native.network.DelegationArgs(
                    name="postgres-delegation",
                    service_name="Microsoft.DBforPostgreSQL/flexibleServers",
                )
            ],
        )

        # 2. Create Key Vault
        pulumi.log.info("Creating Key Vault...")

        # Get current Azure client configuration to retrieve deployer's object ID
        client_config = azure_native.authorization.get_client_config()
        deployer_object_id = client_config.object_id

        key_vault = create_key_vault(
            resource_group_name=resource_group,
            location=location,
            tenant_id=config.azure.tenant_id,
            config=config,
            tags=config.tags,
            deployer_object_id=deployer_object_id,
        )

        # 3. Create Secrets Manager
        pulumi.log.info("Initializing Secrets Manager...")
        secrets_manager = SecretsManager(
            resource_group_name=resource_group,
            vault_name=key_vault.name,
            config=config,
            environment=environment,
        )

        # 3.1. Create user-provided secrets from environment variables
        secrets_manager.create_user_provided_secrets()

        # 3.2. Generate PostgreSQL admin password
        pulumi.log.info("Generating PostgreSQL admin password...")
        admin_password = secrets_manager.create_postgres_admin_password()

        # 4. Create PostgreSQL Flexible Server
        pulumi.log.info("Creating PostgreSQL Flexible Server...")
        postgres_server = create_postgres_server(
            resource_group_name=resource_group,
            location=location,
            vnet_id=vnet.id,
            postgres_subnet_id=postgres_subnet.id,
            config=config,
            admin_password=admin_password,
            tags=config.tags,
        )

        # 4.1. Create databases
        pulumi.log.info("Creating PostgreSQL databases...")
        create_databases(
            resource_group_name=resource_group,
            server_name=postgres_server.name,
            database_names=config.database.databases,
            environment=environment,
            tags=config.tags,
        )

        # 4.2. Create database connection strings
        pulumi.log.info("Creating database connection strings...")
        secrets_manager.create_database_connection_strings(
            postgres_server_fqdn=postgres_server.fully_qualified_domain_name,
            admin_login=config.database.admin_login,
            admin_password=admin_password,
            database_names=config.database.databases,
        )

        # 5. Create Storage Account
        pulumi.log.info("Creating Storage Account...")
        storage_account = create_storage_account(
            resource_group_name=resource_group,
            location=location,
            config=config,
            tags=config.tags,
        )

        # Store storage account primary endpoints
        storage_account_primary_endpoints = storage_account.primary_endpoints

        pulumi.log.info("Storing blob endpoint URL in Key Vault...")
        secrets_manager.create_blob_endpoint_url_secret(
            blob_endpoint_url=storage_account_primary_endpoints.blob,
        )

        # 5.1. Get storage account key and create connection string
        from llmaven.infrastructure.resources.storage import get_storage_account_key

        pulumi.log.info("Retrieving storage account key...")
        storage_account_key = get_storage_account_key(
            resource_group_name=resource_group,
            storage_account_name=storage_account.name,
        )

        pulumi.log.info("Creating storage connection string secret...")
        secrets_manager.create_storage_connection_string_secret(
            storage_account_name=storage_account.name,
            storage_account_key=storage_account_key,
        )

        # 5.2. Create blob containers for storage
        from llmaven.infrastructure.resources.storage import create_blob_containers

        pulumi.log.info("Creating blob containers...")
        create_blob_containers(
            resource_group_name=resource_group,
            storage_account_name=storage_account.name,
            container_names=config.storage.containers,
            environment=environment,
        )

        # 5.5. Create MLflow artifact root URL
        pulumi.log.info("Creating MLflow artifact root secret...")
        secrets_manager.create_mlflow_artifact_root_secret(
            storage_account_name=storage_account.name,
            container_name="mlflow",
        )

        # 6. Create Log Analytics Workspace (for monitoring)
        if config.monitoring.enable_log_analytics:
            pulumi.log.info("Creating Log Analytics workspace...")
            log_analytics = create_log_analytics_workspace(
                name=f"log-{stack_name}",
                resource_group_name=resource_group,
                location=location,
                retention_days=config.monitoring.retention_days,
                tags=config.tags,
            )
        else:
            log_analytics = None

        # 7. Create Container Apps Environment
        pulumi.log.info("Creating Container Apps environment...")
        container_env = create_container_apps_environment(
            resource_group_name=resource_group,
            location=location,
            container_apps_subnet_id=container_apps_subnet.id,
            log_analytics_workspace=log_analytics,
            config=config,
            tags=config.tags,
        )

        # 7.1. Create User-Assigned Managed Identities for Key Vault access
        pulumi.log.info("Creating user-assigned managed identities...")
        from llmaven.infrastructure.resources import (
            create_user_assigned_managed_identity,
            grant_key_vault_access,
        )

        # 7.1.1. Create managed identity for MLflow
        mlflow_managed_identity = None
        mlflow_kv_access_policy = None
        if config.mlflow and config.mlflow.enabled:
            mlflow_managed_identity = create_user_assigned_managed_identity(
                name=f"{stack_name}-mlflow-identity",
                resource_group_name=resource_group,
                location=location,
                tags=config.tags,
            )

            # Grant Key Vault access to the managed identity
            mlflow_kv_access_policy = grant_key_vault_access(
                key_vault=key_vault,
                principal_id=mlflow_managed_identity.principal_id,
                resource_group_name=resource_group,
                tenant_id=config.azure.tenant_id,
                permissions_level="read",
                principal_name="mlflow-identity",
            )

        # 7.1.2. Create managed identity for LiteLLM
        litellm_managed_identity = None
        litellm_kv_access_policy = None
        if config.litellm and config.litellm.enabled:
            litellm_managed_identity = create_user_assigned_managed_identity(
                name=f"{stack_name}-litellm-identity",
                resource_group_name=resource_group,
                location=location,
                tags=config.tags,
            )

            # Grant Key Vault access to the managed identity
            litellm_kv_access_policy = grant_key_vault_access(
                key_vault=key_vault,
                principal_id=litellm_managed_identity.principal_id,
                resource_group_name=resource_group,
                tenant_id=config.azure.tenant_id,
                permissions_level="read",
                principal_name="litellm-identity",
            )

        # 8. Deploy Container Apps

        # 8.1. MLflow Container App
        if config.mlflow and config.mlflow.enabled:
            pulumi.log.info("Creating MLflow Container App...")

            mlflow_app = create_mlflow_app(
                name=f"{stack_name}-mlflow",
                resource_group_name=resource_group,
                location=location,
                container_env_id=container_env.id,
                image=config.mlflow.image,
                port=config.mlflow.port,
                cpu=config.mlflow.cpu,
                memory=config.mlflow.memory,
                min_replicas=config.mlflow.min_replicas,
                max_replicas=config.mlflow.max_replicas,
                env_vars=config.mlflow.env_vars,
                key_vault=key_vault,
                key_vault_secret_refs=config.mlflow.key_vault_secret_refs,
                managed_identity_id=(
                    mlflow_managed_identity.id if mlflow_managed_identity else None
                ),
                tags=config.tags,
                opts=pulumi.ResourceOptions(
                    depends_on=(
                        [mlflow_kv_access_policy] if mlflow_kv_access_policy else []
                    )
                ),
            )

            mlflow_fqdn = mlflow_app.configuration.apply(
                lambda c: c.ingress.fqdn if c and c.ingress else None
            )

            # Create MLflow tracking URI secret
            secrets_manager.create_mlflow_tracking_uri_secret(mlflow_fqdn)

            # Export MLflow URL
            pulumi.export(
                "mlflow_url",
                mlflow_app.configuration.apply(
                    lambda c: f"https://{c.ingress.fqdn}" if c and c.ingress else None
                ),
            )

        # 8.2. LiteLLM Container App
        if config.litellm and config.litellm.enabled:
            pulumi.log.info("Creating LiteLLM Container App...")
            config_file_path = None

            # Interpret config file path relative to the configuration file location
            if hasattr(config.litellm, "config_file") and config.litellm.config_file:
                config_file_path = Path(config.litellm.config_file)
                if not config_file_path.is_absolute():
                    config_file_path = (config_path.parent / config_file_path).resolve()
            pulumi.log.info(f"Using LiteLLM config file: {config_file_path}")

            # Add the adl_logger.py as an extra module
            adl_logger_path = Path(__file__).parent / Path("resources/adl_logger.py")

            litellm_app = create_litellm_app(
                name=f"{stack_name}-litellm",
                resource_group_name=resource_group,
                location=location,
                container_env_id=container_env.id,
                container_env_name=container_env.name,
                image=config.litellm.image,
                port=config.litellm.port,
                cpu=config.litellm.cpu,
                memory=config.litellm.memory,
                min_replicas=config.litellm.min_replicas,
                max_replicas=config.litellm.max_replicas,
                env_vars=config.litellm.env_vars,
                key_vault=key_vault,
                key_vault_secret_refs=config.litellm.key_vault_secret_refs,
                config_file=config_file_path,
                managed_identity_id=(
                    litellm_managed_identity.id if litellm_managed_identity else None
                ),
                tags=config.tags,
                opts=pulumi.ResourceOptions(
                    depends_on=(
                        [litellm_kv_access_policy] if litellm_kv_access_policy else []
                    )
                ),
                extra_modules=[adl_logger_path],
            )

            # Export LiteLLM URL
            pulumi.export(
                "litellm_url",
                litellm_app.configuration.apply(
                    lambda c: f"https://{c.ingress.fqdn}" if c and c.ingress else None
                ),
            )

        # 9. Backup Container Apps Job
        if config.backup_job and config.backup_job.enabled:
            pulumi.log.info("Creating backup Container Apps Job...")
            storage_conn_str = os.environ.get(config.backup_job.connection_string_env)
            if not storage_conn_str:
                pulumi.log.warn(
                    f"backup_job.enabled=true but {config.backup_job.connection_string_env} "
                    "is not set — skipping backup job"
                )
            else:
                # Reconstruct DB URL from Pulumi Outputs already in scope
                db_url = pulumi.Output.all(
                    postgres_server.fully_qualified_domain_name, admin_password
                ).apply(
                    lambda args: (
                        f"postgresql://{config.database.admin_login}:{args[1]}"
                        f"@{args[0]}/llmaven"
                    )
                )
                create_backup_job(
                    resource_group_name=resource_group,
                    location=location,
                    managed_environment_id=container_env.id,
                    db_url=db_url,
                    storage_conn_str=storage_conn_str,
                    config=config,
                    tags=config.tags,
                )

        # Export common outputs
        pulumi.export("resource_group_name", resource_group)
        pulumi.export("location", location)
        pulumi.export("environment", environment)
        pulumi.export("postgres_server_name", postgres_server.name)
        pulumi.export("storage_account_name", storage_account.name)
        pulumi.export("key_vault_name", key_vault.name)

        pulumi.log.info("✓ Infrastructure deployment complete")

    return llmaven_infra
