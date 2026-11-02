"""Configuration schema for LLMaven Azure deployment.

This module defines the Pydantic models for validating llmaven-config.yaml.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class ProjectConfig(BaseModel):
    """Project information configuration."""

    name: str = Field(default="llmaven", description="Project name")
    environment: str = Field(
        default="dev", description="Environment (dev, staging, prod)"
    )
    location: str = Field(default="eastus", description="Azure region")
    enable_passphrase: bool = Field(
        default=False,
        description="Enable Pulumi passphrase protection (requires PULUMI_CONFIG_PASSPHRASE)",
    )
    pulumi_state_store: Optional[str] = Field(
        default=None,
        description="Azure Blob Storage account for Pulumi state storage (optional)",
    )

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        """Validate environment value."""
        allowed = ["dev", "staging", "prod"]
        if v not in allowed:
            raise ValueError(f"Environment must be one of {allowed}")
        return v


class AzureConfig(BaseModel):
    """Azure subscription configuration."""

    subscription_id: str = Field(
        default="", description="Azure subscription ID (required)"
    )
    tenant_id: Optional[str] = Field(
        default=None, description="Azure AD tenant ID (optional, auto-detected)"
    )
    resource_group: Optional[str] = Field(
        default=None, description="Resource group name (optional, auto-created)"
    )


class NetworkingConfig(BaseModel):
    """Networking configuration."""

    vnet_address_space: str = Field(
        default="10.0.0.0/16", description="VNet address space"
    )
    container_apps_subnet: str = Field(
        default="10.0.1.0/24", description="Container Apps subnet"
    )
    postgres_subnet: str = Field(default="10.0.2.0/24", description="PostgreSQL subnet")


class DatabaseConfig(BaseModel):
    """Database configuration."""

    admin_login: str = Field(
        default="llmaven_admin",
        description="PostgreSQL administrator login name",
    )
    sku_name: str = Field(
        default="B_Standard_B1ms",
        description="SKU name (B_Standard_B1ms, GP_Standard_D2s_v3, etc.)",
    )
    storage_size_gb: int = Field(default=32, description="Storage size in GB", ge=32)
    storage_type: Optional[str] = Field(
        default=None,
        description="Storage type (e.g., Premium_LRS); Azure default if unset",
    )
    backup_retention_days: int = Field(
        default=7, description="Backup retention in days", ge=7, le=35
    )
    geo_redundant_backup: bool = Field(
        default=False, description="Enable geo-redundant backup"
    )
    high_availability: bool = Field(
        default=False, description="Enable high availability"
    )
    postgresql_version: str = Field(default="16", description="PostgreSQL version")
    databases: List[str] = Field(
        default=["llmaven", "mlflow_db", "litellm_db"], description="Database names"
    )


class StorageConfig(BaseModel):
    """Storage configuration."""

    account_tier: str = Field(default="Standard", description="Storage account tier")
    account_replication: str = Field(
        default="LRS", description="Storage replication type"
    )
    enable_hierarchical_namespace: bool = Field(
        default=True, description="Enable ADLS Gen2"
    )
    containers: List[str] = Field(
        default=["mlflow", "llmaven", "litellm-logs"],
        description="Storage container names",
    )

    @field_validator("account_tier")
    @classmethod
    def validate_account_tier(cls, v: str) -> str:
        """Validate account tier."""
        allowed = ["Standard", "Premium"]
        if v not in allowed:
            raise ValueError(f"Account tier must be one of {allowed}")
        return v

    @field_validator("account_replication")
    @classmethod
    def validate_account_replication(cls, v: str) -> str:
        """Validate account replication."""
        allowed = ["LRS", "GRS", "ZRS", "GZRS"]
        if v not in allowed:
            raise ValueError(f"Account replication must be one of {allowed}")
        return v


class ContainerRegistryConfig(BaseModel):
    """Container registry configuration."""

    type: str = Field(default="ghcr", description="Registry type (ghcr or acr)")
    repository: str = Field(
        default="ghcr.io/uw-ssec/llmaven",
        description="Container repository base path",
    )

    @field_validator("type")
    @classmethod
    def validate_registry_type(cls, v: str) -> str:
        """Validate registry type."""
        allowed = ["ghcr", "acr"]
        if v not in allowed:
            raise ValueError(f"Registry type must be one of {allowed}")
        return v


class MonitoringConfig(BaseModel):
    """Monitoring configuration."""

    retention_days: int = Field(
        default=90, description="Log retention in days", ge=30, le=730
    )
    enable_application_insights: bool = Field(
        default=True, description="Enable Application Insights"
    )
    enable_log_analytics: bool = Field(default=True, description="Enable Log Analytics")
    daily_data_cap_gb: Optional[float] = Field(
        default=None, description="Daily data cap in GB (null for unlimited)"
    )


class CustomDomainConfig(BaseModel):
    """Custom hostname bound to a container app's ingress."""

    name: str = Field(description="Hostname, e.g. ai-gateway.example.org")
    certificate_name: str = Field(
        description="Name of an existing managed certificate in the Container Apps "
        "environment for this hostname"
    )


class ContainerAppConfig(BaseModel):
    """Container App configuration."""

    enabled: bool = Field(default=True, description="Enable this container app")
    image: str = Field(description="Container image URL")
    port: int = Field(description="Container port", ge=1, le=65535)
    cpu: float = Field(default=0.5, description="CPU cores", ge=0.25)
    memory: str = Field(default="1Gi", description="Memory allocation")
    min_replicas: int = Field(default=1, description="Minimum replicas", ge=0)
    max_replicas: int = Field(default=2, description="Maximum replicas", ge=1)
    env_vars: Dict[str, str] = Field(
        default_factory=dict, description="Environment variables"
    )
    key_vault_secret_refs: Dict[str, str] = Field(
        default_factory=dict, description="Key/Value mapping for Key Vault secrets"
    )
    revision_suffix: Optional[str] = Field(
        default=None,
        description="Revision name suffix (must change whenever the template changes)",
    )
    refresh_trigger: Optional[str] = Field(
        default=None,
        description="Fixed REFRESH_TRIGGER value; defaults to the deploy timestamp, "
        "which forces a new revision on every deploy",
    )
    custom_domains: List[CustomDomainConfig] = Field(
        default_factory=list,
        description="Custom hostnames to keep bound to the ingress; a deploy removes "
        "any hostname that isn't listed here",
    )


class MLflowConfig(ContainerAppConfig):
    """MLflow-specific configuration."""

    image: str = Field(
        default="ghcr.io/uw-ssec/llmaven-mlflow:latest",
        description="MLflow container image",
    )
    port: int = Field(default=8080, description="MLflow port")
    env_vars: Dict[str, str] = Field(
        default_factory=lambda: {"MLFLOW_HOST": "0.0.0.0"},
        description="MLflow environment variables",
    )

    key_vault_secret_refs: Dict[str, str] = Field(
        default_factory=lambda: {
            "MLFLOW_BACKEND_STORE_URI": "db-connection-string-mlflow-db",
            "MLFLOW_DEFAULT_ARTIFACT_ROOT": "mlflow-artifact-root",
            "AZURE_STORAGE_CONNECTION_STRING": "storage-connection-string",
        },
        description="MLflow Key Vault secret references",
    )


class LiteLLMConfig(ContainerAppConfig):
    """LiteLLM-specific configuration."""

    image: str = Field(
        default="ghcr.io/uw-ssec/llmaven-litellm:latest",
        description="LiteLLM container image",
    )
    port: int = Field(default=4000, description="LiteLLM port")
    config_file: str = Field(
        default="docker/config.yaml", description="Path to LiteLLM config file"
    )
    env_vars: Dict[str, str] = Field(
        default_factory=lambda: {"LITELLM_HOST": "0.0.0.0"},
        description="LiteLLM environment variables",
    )

    key_vault_secret_refs: Dict[str, str] = Field(
        default_factory=lambda: {
            "DATABASE_URL": "db-connection-string-litellm-db",
            "LITELLM_MASTER_KEY": "litellm-master-key",
            "AZURE_API_BASE": "azure-api-base",
            "AZURE_API_KEY": "azure-api-key",
            "AZURE_API_VERSION": "azure-api-version",
            "ANTHROPIC_API_KEY": "anthropic-api-key",
            "MLFLOW_EXPERIMENT_NAME": "mlflow-experiment-name",
            "MLFLOW_TRACKING_URI": "mlflow-tracking-uri",
            "AZURE_STORAGE_CONNECTION_STRING": "storage-connection-string",
        },
        description="LiteLLM Key Vault secret references",
    )


class LLMavenAPIConfig(ContainerAppConfig):
    """LLMaven API-specific configuration."""

    enabled: bool = Field(default=False, description="Enable LLMaven API")
    image: str = Field(
        default="ghcr.io/uw-ssec/llmaven-api:latest",
        description="LLMaven API container image",
    )
    port: int = Field(default=8000, description="LLMaven API port")
    cpu: float = Field(default=1.0, description="CPU cores")
    memory: str = Field(default="2Gi", description="Memory allocation")
    max_replicas: int = Field(default=3, description="Maximum replicas")


class KeyVaultConfig(BaseModel):
    """Key Vault configuration."""

    soft_delete_retention_days: int = Field(
        default=90, description="Soft delete retention days", ge=7, le=90
    )
    enable_soft_delete: bool = Field(default=False, description="Enable soft delete")
    enable_purge_protection: Optional[bool] = Field(
        default=None, description="Enable purge protection"
    )


class NetworkSecurityConfig(BaseModel):
    """Network security configuration."""

    allow_azure_services: bool = Field(default=True, description="Allow Azure services")
    allowed_ip_ranges: List[str] = Field(
        default_factory=list, description="Allowed IP ranges for access control"
    )


class SecurityConfig(BaseModel):
    """Security configuration."""

    enable_private_endpoints: bool = Field(
        default=False,
        description="Enable private endpoints (recommended for production)",
    )
    key_vault: KeyVaultConfig = Field(
        default_factory=KeyVaultConfig, description="Key Vault configuration"
    )
    network_security: NetworkSecurityConfig = Field(
        default_factory=NetworkSecurityConfig,
        description="Network security configuration",
    )


class BackupJobConfig(BaseModel):
    """Container Apps Job configuration for scheduled PostgreSQL backups."""

    enabled: bool = Field(default=False, description="Enable the backup job")
    image: str = Field(
        default="ghcr.io/uw-ssec/llmaven-backup:latest",
        description="Backup container image",
    )
    # Daily at 10:00 AM UTC — every day of the week, every month
    schedule: str = Field(default="0 10 * * *", description="CRON schedule (UTC)")
    destination: str = Field(
        default="az://pg-backups/llmaven/",
        description="Azure Blob Storage destination URL (az://)",
    )
    keep_last_n: int = Field(default=7, ge=1, description="Number of backups to retain")
    cpu: float = Field(default=0.25, description="CPU cores", ge=0.25)
    memory: str = Field(default="0.5Gi", description="Memory allocation")
    replica_timeout: int = Field(
        default=1800, description="Max job runtime in seconds", ge=60
    )
    database: str = Field(
        default="llmaven",
        description="Name of the PostgreSQL database to back up (must match one of database.databases)",
    )
    connection_string_env: str = Field(
        default="LLMAVEN_SECRETS_BACKUP_STORAGE_CONNECTION_STRING",
        description="Env var holding the backup storage account connection string",
    )


FOUNDRY_DEPLOYMENT_SKUS = [
    "Standard",
    "GlobalStandard",
    "DataZoneStandard",
    "ProvisionedManaged",
    "GlobalProvisionedManaged",
    "DataZoneProvisionedManaged",
    "GlobalBatch",
    "DataZoneBatch",
    "DeveloperTier",
]

FOUNDRY_VERSION_UPGRADE_OPTIONS = [
    "NoAutoUpgrade",
    "OnceNewDefaultVersionAvailable",
    "OnceCurrentVersionExpired",
]

# Key Vault secrets the stack writes itself when it manages the Foundry account.
FOUNDRY_MANAGED_SECRETS = ["azure-api-base", "azure-api-key", "azure-api-version"]


def foundry_secret_collisions(
    foundry_enabled: bool, user_secret_names: List[str]
) -> List[str]:
    """Return user-provided Key Vault secret names the Foundry stack would overwrite.

    Args:
        foundry_enabled: Whether the stack manages the Foundry account
        user_secret_names: Final Key Vault names of LLMAVEN_SECRETS_* values

    Returns:
        Sorted colliding secret names (empty when Foundry is disabled)
    """
    if not foundry_enabled:
        return []
    return sorted(set(user_secret_names) & set(FOUNDRY_MANAGED_SECRETS))


class FoundryDeploymentConfig(BaseModel):
    """One model deployment in the Foundry account."""

    name: str = Field(
        description="Deployment name; LiteLLM model_list refers to it as azure/<name>",
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$",
    )
    model_name: str = Field(description="Model name, e.g. gpt-5-mini")
    model_format: str = Field(default="OpenAI", description="Model format/publisher")
    model_version: str = Field(description="Model version, e.g. 2025-08-07")
    sku: str = Field(default="GlobalStandard", description="Deployment SKU")
    capacity: int = Field(
        default=10,
        ge=1,
        description="Capacity units (thousands of tokens per minute for Standard SKUs)",
    )
    version_upgrade_option: str = Field(
        default="NoAutoUpgrade",
        description="What happens when Azure publishes or retires a model version",
    )

    @field_validator("model_name", "model_format", "model_version")
    @classmethod
    def validate_not_blank(cls, v: str) -> str:
        """Reject empty or whitespace-only model fields before they reach Azure."""
        if not v.strip():
            raise ValueError("must not be blank")
        return v

    @field_validator("sku")
    @classmethod
    def validate_sku(cls, v: str) -> str:
        """Validate deployment SKU."""
        if v not in FOUNDRY_DEPLOYMENT_SKUS:
            raise ValueError(f"Deployment sku must be one of {FOUNDRY_DEPLOYMENT_SKUS}")
        return v

    @field_validator("version_upgrade_option")
    @classmethod
    def validate_version_upgrade_option(cls, v: str) -> str:
        """Validate version upgrade option."""
        if v not in FOUNDRY_VERSION_UPGRADE_OPTIONS:
            raise ValueError(
                f"version_upgrade_option must be one of {FOUNDRY_VERSION_UPGRADE_OPTIONS}"
            )
        return v


class FoundryConfig(BaseModel):
    """Azure AI Foundry (AIServices) account and model deployments."""

    enabled: bool = Field(
        default=False,
        description="Provision the Foundry account and deployments in this stack; "
        "when false, bring your own endpoint through azure-api-* secrets",
    )
    account_name: Optional[str] = Field(
        default=None,
        description="Account name and custom subdomain (globally unique); "
        "defaults to <project>-foundry-<environment>",
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9-]{1,62}[a-zA-Z0-9]$",
    )
    location: Optional[str] = Field(
        default=None,
        description="Azure region for the account; defaults to project.location",
    )
    sku: str = Field(default="S0", description="Account SKU")
    api_version: str = Field(
        default="2025-04-01-preview",
        description="Azure OpenAI API version written to the azure-api-version secret",
    )
    deployments: List[FoundryDeploymentConfig] = Field(
        default_factory=list, description="Model deployments"
    )

    @field_validator("deployments")
    @classmethod
    def validate_unique_deployment_names(
        cls, v: List[FoundryDeploymentConfig]
    ) -> List[FoundryDeploymentConfig]:
        """Reject duplicate deployment names."""
        names = [d.name for d in v]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            raise ValueError(f"Duplicate foundry deployment names: {duplicates}")
        return v


class LLMavenConfig(BaseModel):
    """Root configuration model for LLMaven deployment."""

    project: ProjectConfig = Field(
        default_factory=ProjectConfig, description="Project information"
    )
    azure: AzureConfig = Field(
        default_factory=AzureConfig, description="Azure subscription"
    )
    networking: NetworkingConfig = Field(
        default_factory=NetworkingConfig, description="Networking configuration"
    )
    database: DatabaseConfig = Field(
        default_factory=DatabaseConfig, description="Database configuration"
    )
    storage: StorageConfig = Field(
        default_factory=StorageConfig, description="Storage configuration"
    )
    container_registry: ContainerRegistryConfig = Field(
        default_factory=ContainerRegistryConfig,
        description="Container registry configuration",
    )
    monitoring: MonitoringConfig = Field(
        default_factory=MonitoringConfig, description="Monitoring configuration"
    )
    mlflow: MLflowConfig = Field(
        default_factory=MLflowConfig, description="MLflow container app"
    )
    litellm: LiteLLMConfig = Field(
        default_factory=LiteLLMConfig, description="LiteLLM container app"
    )
    llmaven_api: LLMavenAPIConfig = Field(
        default_factory=LLMavenAPIConfig, description="LLMaven API container app"
    )
    security: SecurityConfig = Field(
        default_factory=SecurityConfig, description="Security configuration"
    )
    backup_job: BackupJobConfig = Field(
        default_factory=BackupJobConfig,
        description="Scheduled backup job configuration",
    )
    foundry: FoundryConfig = Field(
        default_factory=FoundryConfig,
        description="Azure AI Foundry account and model deployments",
    )
    tags: Dict[str, str] = Field(
        default_factory=lambda: {
            "Environment": "dev",
            "Project": "llmaven",
            "ManagedBy": "Pulumi",
            "CostCenter": "",
            "Owner": "",
        },
        description="Resource tags",
    )

    def model_post_init(self, __context: Any) -> None:
        """Post-initialization validation."""
        # Sync environment tag with project environment
        if "Environment" in self.tags:
            self.tags["Environment"] = self.project.environment

        # Sync project tag with project name
        if "Project" in self.tags:
            self.tags["Project"] = self.project.name

        if (
            self.backup_job.enabled
            and self.backup_job.database not in self.database.databases
        ):
            raise ValueError(
                f"backup_job.database '{self.backup_job.database}' is not in "
                f"database.databases {self.database.databases}"
            )
