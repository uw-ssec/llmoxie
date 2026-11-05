"""Default configuration templates for different environments.

This module provides functions to generate default configurations
for dev, staging, and production environments.
"""

from .schema import (
    ALL_ALERTS,
    AlertsConfig,
    AzureConfig,
    CloudBudgetAlert,
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
    RedisConfig,
    SecurityConfig,
    StorageConfig,
)

# Placeholder so staging/prod defaults validate; operators must replace it.
_PLACEHOLDER_ALERT_RECEIVER = "ops@example.org"


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
            pulumi_state_store=None,
        ),
        "azure": AzureConfig(
            subscription_id="",  # User must provide
            tenant_id=None,
            resource_group=None,
        ),
        "networking": NetworkingConfig(
            vnet_address_space="10.0.0.0/16",
            container_apps_subnet="10.0.1.0/24",
            postgres_subnet="10.0.2.0/24",
            private_endpoints_subnet="10.0.3.0/24",
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
        ),
        "litellm": LiteLLMConfig(
            enabled=True,
            image="ghcr.io/uw-ssec/llmaven-litellm:latest",
            port=4000,
            cpu=2,
            memory="4Gi",  # litellm fails to start with only 1Gi of memory, defaulting to 4Gi
            min_replicas=1,
            max_replicas=2,
            config_file="docker/config.yaml",
            env_vars={"LITELLM_HOST": "0.0.0.0"},
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
                enable_application_insights=False,
                enable_log_analytics=True,
                daily_data_cap_gb=1.0,  # 1GB cap for dev
                alerts=AlertsConfig(
                    cloud_budget=CloudBudgetAlert(monthly_usd=200),
                ),
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
                enable_application_insights=False,
                enable_log_analytics=True,
                daily_data_cap_gb=5.0,  # 5GB cap for staging
                alerts=AlertsConfig(
                    email_receivers=[_PLACEHOLDER_ALERT_RECEIVER],
                    enabled_alerts=list(ALL_ALERTS),
                    cloud_budget=CloudBudgetAlert(monthly_usd=300),
                ),
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
                enable_application_insights=False,
                enable_log_analytics=True,
                daily_data_cap_gb=None,  # No cap for production
                alerts=AlertsConfig(
                    email_receivers=[_PLACEHOLDER_ALERT_RECEIVER],
                    enabled_alerts=list(ALL_ALERTS),
                    cloud_budget=CloudBudgetAlert(monthly_usd=500),
                ),
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
        # Two-node Redis so rate limits and budgets survive a node failure
        config["redis"] = RedisConfig(high_availability=True)

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

    alerts = config.monitoring.alerts
    receivers_yaml = "\n".join(f"      - {r}" for r in alerts.email_receivers)
    enabled_alerts_yaml = "\n".join(f"      - {a}" for a in alerts.enabled_alerts)
    receivers_block = f"\n{receivers_yaml}" if receivers_yaml else " []"
    enabled_block = f"\n{enabled_alerts_yaml}" if enabled_alerts_yaml else " []"

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
  pulumi_state_store: null  # Azure Storage account for Pulumi states (auto-generated during deployment)

# Azure Subscription
azure:
  subscription_id: ""  # Azure subscription ID (required)
  tenant_id: null  # Azure AD tenant ID (optional, auto-detected)
  resource_group: null  # Resource group name (auto-generated during deployment)

# Networking Configuration
networking:
  vnet_address_space: {config.networking.vnet_address_space}
  container_apps_subnet: {config.networking.container_apps_subnet}
  postgres_subnet: {config.networking.postgres_subnet}
  private_endpoints_subnet: {config.networking.private_endpoints_subnet}  # Used by Redis

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

# Azure Managed Redis, shared by LiteLLM replicas for rate limits, budgets and
# router state. Required when litellm.max_replicas > 1; defaults to on then.
redis:
  enabled: {str(config.redis.enabled).lower()}
  sku_name: {config.redis.sku_name}  # Balanced_B0, Balanced_B1, Balanced_B3, ...
  high_availability: {str(config.redis.high_availability).lower()}  # Two nodes; recommended for prod
  clustering_policy: {config.redis.clustering_policy}  # Can't be changed after creation

# Container Registry Configuration
# Images are hosted on GitHub Container Registry (GHCR)
# No Azure Container Registry needed - saves cost!
container_registry:
  type: ghcr  # Use GitHub Container Registry
  repository: ghcr.io/uw-ssec/llmaven  # GitHub org/repo (base path)

# Monitoring Configuration
monitoring:
  retention_days: {config.monitoring.retention_days}
  enable_log_analytics: {str(config.monitoring.enable_log_analytics).lower()}
  daily_data_cap_gb: {config.monitoring.daily_data_cap_gb if config.monitoring.daily_data_cap_gb else "null"}  # null for unlimited
  # Alerts are off unless enabled_alerts is non-empty. Thresholds not listed here
  # use the schema defaults (see docs/superpowers/specs/2026-11-05-monitoring-alerting-design.md).
  alerts:
    # Replace the placeholder address with a real one before deploying.
    email_receivers:{receivers_block}
    # gateway_errors, gateway_latency, replica_restarts, db_storage, db_cpu,
    # backup_job_failures, cloud_budget
    enabled_alerts:{enabled_block}
    cloud_budget:
      monthly_usd: {alerts.cloud_budget.monthly_usd:g}

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

  # Key Vault Secret References (Env Var -> Secret Name)
  key_vault_secret_refs:
    MLFLOW_BACKEND_STORE_URI: "db-connection-string-mlflow-db"
    MLFLOW_DEFAULT_ARTIFACT_ROOT: "mlflow-artifact-root"
    AZURE_STORAGE_CONNECTION_STRING: "storage-connection-string"

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

  # Key Vault Secret References (Env Var -> Secret Name)
  key_vault_secret_refs:
    DATABASE_URL: "db-connection-string-litellm-db"
    LITELLM_MASTER_KEY: "litellm-master-key"
    AZURE_API_BASE: "azure-api-base"
    AZURE_API_KEY: "azure-api-key"
    AZURE_API_VERSION: "azure-api-version"
    ANTHROPIC_API_KEY: "anthropic-api-key"
    MLFLOW_EXPERIMENT_NAME: "mlflow-experiment-name"
    MLFLOW_TRACKING_URI: "mlflow-tracking-uri"

  # Optional Traefik sidecar: keeps inference paths public and limits every
  # other path (admin UI, key/team/model management) to admin_allowed_ips.
  # LiteLLM cpu/memory plus the proxy's 0.25 / 0.5Gi must be a valid pair.
  # proxy:
  #   enabled: true
  #   admin_allowed_ips:
  #     - 203.0.113.0/24

# LLMaven API Container App (optional)
llmaven_api:
  enabled: false
  image: ghcr.io/uw-ssec/llmaven-api:latest  # Hosted on GHCR (if built)
  port: 8000
  cpu: 1.0
  memory: 2Gi
  min_replicas: 1
  max_replicas: 3

# Azure AI Foundry (optional)
# enabled: false -> bring your own endpoint via LLMAVEN_SECRETS_AZURE_API_BASE/KEY/VERSION.
# enabled: true  -> the stack creates the account and deployments and writes
#   azure-api-base, azure-api-key and azure-api-version to Key Vault itself
#   (do not set those LLMAVEN_SECRETS_* variables). The account only accepts
#   traffic from the Container Apps subnet. Every azure/<name> model in the
#   LiteLLM config must match a deployment name below.
foundry:
  enabled: false
  account_name: null  # Globally unique subdomain; default <project>-foundry-<environment>
  location: null  # Defaults to project.location
  sku: S0
  api_version: "2025-04-01-preview"
  deployments: []
  # deployments:
  #   - name: gpt-5-mini  # LiteLLM model: azure/gpt-5-mini
  #     model_name: gpt-5-mini
  #     model_format: OpenAI
  #     model_version: "2025-08-07"
  #     sku: GlobalStandard
  #     capacity: 10  # Thousands of tokens per minute
  #     version_upgrade_option: NoAutoUpgrade

# Security Configuration
security:
  enable_private_endpoints: {str(config.security.enable_private_endpoints).lower()}  # Enable for production
  key_vault:
    soft_delete_retention_days: {config.security.key_vault.soft_delete_retention_days}
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
