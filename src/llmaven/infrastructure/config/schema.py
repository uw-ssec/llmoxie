"""Configuration schema for LLMaven Azure deployment.

This module defines the Pydantic models for validating llmaven-config.yaml.
"""

import ipaddress
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


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
    private_endpoints_subnet: Optional[str] = Field(
        default=None,
        description=(
            "Subnet for private endpoints (Azure Managed Redis). Defaults to the "
            "first /24 above the Container Apps and PostgreSQL subnets."
        ),
    )

    @model_validator(mode="after")
    def resolve_private_endpoints_subnet(self) -> "NetworkingConfig":
        """Derive the private endpoints subnet from the VNet when omitted.

        Existing configs predate this field and use their own VNet ranges
        (e.g. 172.16.0.0/16), so a fixed default would fall outside the VNet.
        """
        vnet = ipaddress.ip_network(self.vnet_address_space)
        taken = [
            ipaddress.ip_network(self.container_apps_subnet),
            ipaddress.ip_network(self.postgres_subnet),
        ]

        if self.private_endpoints_subnet is None:
            start = max(int(net.broadcast_address) for net in taken) + 1
            candidate = ipaddress.ip_network((start, 24), strict=False)
            if int(candidate.network_address) < start:
                candidate = ipaddress.ip_network(
                    (int(candidate.broadcast_address) + 1, 24)
                )
            # Left unset when the VNet has no room; LLMavenConfig only rejects
            # that when Redis actually needs the subnet.
            if candidate.subnet_of(vnet):
                self.private_endpoints_subnet = str(candidate)
            return self

        subnet = ipaddress.ip_network(self.private_endpoints_subnet)
        if not subnet.subnet_of(vnet):
            raise ValueError(
                f"networking.private_endpoints_subnet {subnet} is outside "
                f"vnet_address_space {vnet}"
            )
        for net in taken:
            if subnet.overlaps(net):
                raise ValueError(
                    f"networking.private_endpoints_subnet {subnet} overlaps {net}"
                )
        return self


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


class RedisConfig(BaseModel):
    """Azure Managed Redis configuration, shared by LiteLLM replicas.

    LiteLLM keeps rate limits, budgets and router state per replica unless the
    replicas share a Redis, so Redis is required when ``litellm.max_replicas > 1``.
    """

    enabled: Optional[bool] = Field(
        default=None,
        description="Provision Azure Managed Redis for LiteLLM. Defaults to true "
        "when LiteLLM runs more than one replica, false otherwise",
    )
    sku_name: str = Field(
        default="Balanced_B0",
        description="Azure Managed Redis SKU (Balanced_B0, Balanced_B1, ...)",
    )
    high_availability: Optional[bool] = Field(
        default=None,
        description="Replicate across two nodes. Defaults to true in prod, "
        "false otherwise",
    )
    clustering_policy: str = Field(
        default="EnterpriseCluster",
        description="Clustering policy. Can't be changed after the database is created",
    )

    @field_validator("clustering_policy")
    @classmethod
    def validate_clustering_policy(cls, v: str) -> str:
        """Allow only policies that present a single endpoint to LiteLLM."""
        # OSSCluster needs a cluster-aware client (REDIS_CLUSTER_NODES), which
        # the plain REDIS_HOST/REDIS_PORT wiring here doesn't provide.
        allowed = ["EnterpriseCluster", "NoCluster"]
        if v not in allowed:
            raise ValueError(f"Clustering policy must be one of {allowed}")
        return v


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
    redis: RedisConfig = Field(
        default_factory=RedisConfig, description="Azure Managed Redis for LiteLLM"
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

        # LiteLLM enforces rate limits and budgets per replica without a shared
        # Redis, so more than one replica requires Redis.
        litellm_multi_replica = self.litellm.enabled and self.litellm.max_replicas > 1
        if self.redis.enabled is None:
            self.redis.enabled = litellm_multi_replica
        elif litellm_multi_replica and not self.redis.enabled:
            raise ValueError(
                f"redis.enabled is false but litellm.max_replicas is "
                f"{self.litellm.max_replicas}. LiteLLM needs a shared Redis when it "
                "runs more than one replica, otherwise rate limits and budgets are "
                "enforced per replica. Enable redis or set litellm.max_replicas to 1."
            )
        # Existing prod configs predate the redis section and gain Redis
        # automatically, so an omitted HA setting follows the environment.
        if self.redis.high_availability is None:
            self.redis.high_availability = self.project.environment == "prod"
        if self.redis.enabled and self.networking.private_endpoints_subnet is None:
            raise ValueError(
                "Redis needs a private endpoints subnet, but there is no free /24 in "
                f"{self.networking.vnet_address_space} after the Container Apps and "
                "PostgreSQL subnets. Set networking.private_endpoints_subnet."
            )
