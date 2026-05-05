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
        default=["mlflow", "llmaven", "litellm-logs"], description="Storage container names"
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
            "ADLS_ACCOUNT_NAME": "adls-account-name",
            "ADLS_CONTAINER": "adls-litellm-logs-container",
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
