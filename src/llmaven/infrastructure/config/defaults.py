"""Default configuration templates for different environments.

This module provides functions to generate default configurations
for dev, staging, and production environments.
"""

from .schema import (
    AzureConfig,
    ContainerRegistryConfig,
    DatabaseConfig,
    KeyVaultConfig,
    LiteLLMConfig,
    LLMavenAPIConfig,
    LLMavenConfig,
    MLflowConfig,
    MonitoringConfig,
    NetworkingConfig,
    NetworkSecurityConfig,
    ProjectConfig,
    SecurityConfig,
    StorageConfig,
)


def generate_default_config(environment: str = "dev") -> LLMavenConfig:
    """Generate default configuration for specified environment.

    Args:
        environment: Environment name (dev, staging, prod)

    Returns:
        LLMavenConfig with environment-specific defaults
    """
    if environment not in ["dev", "staging", "prod"]:
        environment = "dev"

    # Base configuration that's common to all environments
    base_config = {
        "project": ProjectConfig(
            name="llmaven",
            environment=environment,
            location="eastus",
            enable_passphrase=False,
        ),
        "azure": AzureConfig(
            subscription_id="",  # User must provide
            tenant_id=None,
        ),
        "networking": NetworkingConfig(
            vnet_address_space="10.0.0.0/16",
            container_apps_subnet="10.0.1.0/24",
            postgres_subnet="10.0.2.0/24",
        ),
        "container_registry": ContainerRegistryConfig(
            type="ghcr",
            repository="ghcr.io/uw-ssec/llmaven",
        ),
        "storage": StorageConfig(
            account_tier="Standard",
            account_replication="LRS",
            enable_hierarchical_namespace=True,
            containers=["mlflow", "llmaven"],
        ),
        "mlflow": MLflowConfig(
            enabled=True,
            image="ghcr.io/uw-ssec/llmaven-mlflow:latest",
            port=8080,
            cpu=0.5,
            memory="1Gi",
            min_replicas=1,
            max_replicas=2,
            env_vars={"MLFLOW_HOST": "0.0.0.0"},
            secrets=["db-connection-string", "storage-account-key"],
        ),
        "litellm": LiteLLMConfig(
            enabled=True,
            image="ghcr.io/uw-ssec/llmaven-litellm:latest",
            port=4000,
            cpu=0.5,
            memory="1Gi",
            min_replicas=1,
            max_replicas=2,
            config_file="docker/config.yaml",
            env_vars={"LITELLM_HOST": "0.0.0.0"},
            secrets=[
                "litellm-master-key",
                "azure-openai-api-key",
                "anthropic-api-key",
                "db-connection-string",
                "mlflow-tracking-uri",
            ],
        ),
        "llmaven_api": LLMavenAPIConfig(
            enabled=False,
            image="ghcr.io/uw-ssec/llmaven-api:latest",
            port=8000,
            cpu=1.0,
            memory="2Gi",
            min_replicas=1,
            max_replicas=3,
            env_vars={},
            secrets=[],
        ),
        "tags": {
            "Environment": environment,
            "Project": "llmaven",
            "ManagedBy": "Pulumi",
            "CostCenter": "",
            "Owner": "",
        },
    }

    # Environment-specific configurations
    if environment == "dev":
        config = {
            **base_config,
            "database": DatabaseConfig(
                sku_name="B_Standard_B1ms",  # Burstable tier for dev
                storage_size_gb=32,
                backup_retention_days=7,
                geo_redundant_backup=False,
                high_availability=False,
                postgresql_version="16",
                databases=["llmaven", "mlflow_db", "litellm_db"],
            ),
            "monitoring": MonitoringConfig(
                retention_days=90,
                enable_application_insights=True,
                enable_log_analytics=True,
                daily_data_cap_gb=1.0,  # 1GB cap for dev
            ),
            "security": SecurityConfig(
                enable_private_endpoints=False,
                key_vault=KeyVaultConfig(
                    soft_delete_retention_days=7,  # Minimum for dev
                    enable_rbac=False,  # Use access policies instead of RBAC
                ),
                network_security=NetworkSecurityConfig(
                    allow_azure_services=True,
                    allowed_ip_ranges=[],
                ),
            ),
        }

    elif environment == "staging":
        config = {
            **base_config,
            "database": DatabaseConfig(
                sku_name="GP_Standard_D2s_v3",  # General purpose for staging
                storage_size_gb=128,
                backup_retention_days=14,
                geo_redundant_backup=False,
                high_availability=False,
                postgresql_version="16",
                databases=["llmaven", "mlflow_db", "litellm_db"],
            ),
            "monitoring": MonitoringConfig(
                retention_days=90,
                enable_application_insights=True,
                enable_log_analytics=True,
                daily_data_cap_gb=5.0,  # 5GB cap for staging
            ),
            "security": SecurityConfig(
                enable_private_endpoints=False,
                key_vault=KeyVaultConfig(
                    soft_delete_retention_days=30,
                    enable_rbac=False,  # Use access policies instead of RBAC
                ),
                network_security=NetworkSecurityConfig(
                    allow_azure_services=True,
                    allowed_ip_ranges=[],
                ),
            ),
        }
        # Increase replica counts for staging
        config["mlflow"].min_replicas = 1
        config["mlflow"].max_replicas = 3
        config["litellm"].min_replicas = 1
        config["litellm"].max_replicas = 3
        config["storage"].account_replication = "GRS"  # Geo-redundant for staging

    else:  # production
        config = {
            **base_config,
            "database": DatabaseConfig(
                sku_name="GP_Standard_D4s_v3",  # Larger instance for production
                storage_size_gb=256,
                backup_retention_days=35,  # Maximum retention
                geo_redundant_backup=True,
                high_availability=True,  # HA required for production
                postgresql_version="16",
                databases=["llmaven", "mlflow_db", "litellm_db"],
            ),
            "monitoring": MonitoringConfig(
                retention_days=365,  # 1 year retention for production
                enable_application_insights=True,
                enable_log_analytics=True,
                daily_data_cap_gb=None,  # No cap for production
            ),
            "security": SecurityConfig(
                enable_private_endpoints=True,  # Required for production
                key_vault=KeyVaultConfig(
                    soft_delete_retention_days=90,  # Maximum for production
                    enable_rbac=False,  # Use access policies instead of RBAC
                ),
                network_security=NetworkSecurityConfig(
                    allow_azure_services=True,
                    allowed_ip_ranges=[],
                ),
            ),
        }
        # Higher replica counts for production
        config["mlflow"].min_replicas = 2
        config["mlflow"].max_replicas = 5
        config["mlflow"].cpu = 1.0
        config["mlflow"].memory = "2Gi"
        config["litellm"].min_replicas = 2
        config["litellm"].max_replicas = 5
        config["litellm"].cpu = 1.0
        config["litellm"].memory = "2Gi"
        config["storage"].account_replication = "GZRS"  # Zone-redundant for production

    return LLMavenConfig(**config)


def get_config_template_yaml(environment: str = "dev") -> str:
    """Generate YAML configuration template as string.

    Args:
        environment: Environment name (dev, staging, prod)

    Returns:
        YAML configuration string with comments
    """
    # Generate base config
    config = generate_default_config(environment)

    # Create YAML with comments
    yaml_template = f"""# llmaven-config.yaml
# LLMaven Azure Deployment Configuration
# Environment: {environment}

# Project Information
project:
  name: llmaven
  environment: {environment}  # dev, staging, prod
  location: eastus  # Azure region
  enable_passphrase: false  # Set to true to require PULUMI_CONFIG_PASSPHRASE

# Azure Subscription
azure:
  subscription_id: ""  # Azure subscription ID (required)
  tenant_id: null  # Azure AD tenant ID (optional, auto-detected)

# Networking Configuration
networking:
  vnet_address_space: {config.networking.vnet_address_space}
  container_apps_subnet: {config.networking.container_apps_subnet}
  postgres_subnet: {config.networking.postgres_subnet}

# Database Configuration
database:
  sku_name: {config.database.sku_name}  # B_Standard_B1ms, GP_Standard_D2s_v3, GP_Standard_D4s_v3
  storage_size_gb: {config.database.storage_size_gb}
  backup_retention_days: {config.database.backup_retention_days}
  geo_redundant_backup: {str(config.database.geo_redundant_backup).lower()}
  high_availability: {str(config.database.high_availability).lower()}
  postgresql_version: "{config.database.postgresql_version}"
  databases:
    - llmaven
    - mlflow_db
    - litellm_db

# Storage Configuration
storage:
  account_tier: {config.storage.account_tier}  # Standard, Premium
  account_replication: {config.storage.account_replication}  # LRS, GRS, ZRS, GZRS
  enable_hierarchical_namespace: {str(config.storage.enable_hierarchical_namespace).lower()}  # ADLS Gen2
  containers:
    - mlflow
    - llmaven

# Container Registry Configuration
# Images are hosted on GitHub Container Registry (GHCR)
# No Azure Container Registry needed - saves cost!
container_registry:
  type: ghcr  # Use GitHub Container Registry
  repository: ghcr.io/uw-ssec/llmaven  # GitHub org/repo (base path)

# Monitoring Configuration
monitoring:
  retention_days: {config.monitoring.retention_days}
  enable_application_insights: {str(config.monitoring.enable_application_insights).lower()}
  enable_log_analytics: {str(config.monitoring.enable_log_analytics).lower()}
  daily_data_cap_gb: {config.monitoring.daily_data_cap_gb if config.monitoring.daily_data_cap_gb else "null"}  # null for unlimited

# MLflow Container App
mlflow:
  enabled: true
  image: {config.mlflow.image}  # Hosted on GHCR
  port: {config.mlflow.port}
  cpu: {config.mlflow.cpu}
  memory: {config.mlflow.memory}
  min_replicas: {config.mlflow.min_replicas}
  max_replicas: {config.mlflow.max_replicas}
  env_vars:
    MLFLOW_HOST: "0.0.0.0"
  # Secrets are NOT stored in this config file
  # Database and storage credentials are automatically generated and stored in Key Vault
  # Additional secrets can be set via LLMAVEN_SECRETS_ environment variables
  secrets:
    - db-connection-string
    - storage-account-key

# LiteLLM Container App
litellm:
  enabled: true
  image: {config.litellm.image}  # Hosted on GHCR
  port: {config.litellm.port}
  cpu: {config.litellm.cpu}
  memory: {config.litellm.memory}
  min_replicas: {config.litellm.min_replicas}
  max_replicas: {config.litellm.max_replicas}
  config_file: docker/config.yaml  # Path to LiteLLM config
  env_vars:
    LITELLM_HOST: "0.0.0.0"
  # Secrets are NOT stored in this config file
  # Instead, set environment variables with LLMAVEN_SECRETS_ prefix:
  #   export LLMAVEN_SECRETS_LITELLM_MASTER_KEY="your-key-here"
  #   export LLMAVEN_SECRETS_AZURE_OPENAI_API_KEY="your-key-here"
  #   export LLMAVEN_SECRETS_ANTHROPIC_API_KEY="your-key-here"
  # These will be automatically stored in Azure Key Vault during deployment
  secrets:
    - litellm-master-key
    - azure-openai-api-key
    - anthropic-api-key
    - db-connection-string
    - mlflow-tracking-uri

# LLMaven API Container App (optional)
llmaven_api:
  enabled: false
  image: ghcr.io/uw-ssec/llmaven-api:latest  # Hosted on GHCR (if built)
  port: 8000
  cpu: 1.0
  memory: 2Gi
  min_replicas: 1
  max_replicas: 3

# Security Configuration
security:
  enable_private_endpoints: {str(config.security.enable_private_endpoints).lower()}  # Enable for production
  key_vault:
    soft_delete_retention_days: {config.security.key_vault.soft_delete_retention_days}
    enable_rbac: {str(config.security.key_vault.enable_rbac).lower()}  # Use access policies (false) instead of RBAC (true)
  network_security:
    allow_azure_services: {str(config.security.network_security.allow_azure_services).lower()}
    allowed_ip_ranges: []  # Add IPs for access control

# Tags (applied to all resources)
tags:
  Environment: {environment}
  Project: llmaven
  ManagedBy: Pulumi
  CostCenter: ""
  Owner: ""
"""
    return yaml_template
