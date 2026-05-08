"""Configuration schema for LLMaven backup infrastructure deployment.

This module defines the Pydantic models for validating llmaven-backup-config.yaml.
"""

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator


class BackupProjectConfig(BaseModel):
    """Project information for the backup infrastructure."""

    name: str = Field(default="llmaven-backup", description="Backup project name")
    environment: str = Field(
        default="dev",
        description="Environment (dev, staging, prod) — must match primary",
    )
    location: str = Field(default="westus2", description="Azure region")
    enable_passphrase: bool = Field(
        default=False,
        description="Enable Pulumi passphrase protection (requires PULUMI_CONFIG_PASSPHRASE)",
    )
    pulumi_state_store: Optional[str] = Field(
        default=None,
        description="Azure Blob Storage account for backup Pulumi state (auto-set by init)",
    )

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        """Validate environment value."""
        allowed = ["dev", "staging", "prod"]
        if v not in allowed:
            raise ValueError(f"Environment must be one of {allowed}")
        return v


class BackupAzureConfig(BaseModel):
    """Azure subscription configuration for backup infrastructure."""

    subscription_id: str = Field(
        default="", description="Azure subscription ID (same as primary)"
    )
    tenant_id: Optional[str] = Field(
        default=None, description="Azure AD tenant ID (optional, auto-detected)"
    )
    resource_group: Optional[str] = Field(
        default=None,
        description="Backup resource group name (auto-created by init, e.g. rg-llmaven-backup-eastus)",
    )


class PrimaryStackConfig(BaseModel):
    """References to resources in the primary infrastructure stack.

    These values are auto-populated by 'llmaven infra backup init --from-primary-stack'
    and should not be changed manually unless the primary stack resources were renamed.
    """

    resource_group_name: str = Field(
        default="",
        description="Primary resource group name (for Reader role assignment)",
    )
    postgres_server_name: str = Field(
        default="",
        description="Primary PostgreSQL server name (for BackupInstance and role assignments)",
    )
    pulumi_state_store: str = Field(
        default="",
        description="Primary Pulumi state storage account (used to read stack outputs during init)",
    )


class BackupVaultResourceConfig(BaseModel):
    """Configuration for the Azure Backup Vault resource."""

    redundancy: str = Field(
        default="LocallyRedundant",
        description="Storage redundancy: 'LocallyRedundant' or 'GeoRedundant'",
    )
    immutability_enabled: bool = Field(
        default=True,
        description="Prevent deletion of recovery points (recommended: True for production)",
    )
    soft_delete_retention_days: float = Field(
        default=14.0,
        description="Days to retain soft-deleted backup data before permanent removal (min 14)",
        ge=14,
        le=180,
    )
    backup_schedule_utc: str = Field(
        default="R/2024-01-01T02:00:00Z/P1W",
        description="ISO 8601 recurring interval for weekly backups (default: Sundays at 02:00 UTC)",
    )
    retention_weeks: int = Field(
        default=4,
        description="Number of weekly recovery points to retain",
        ge=1,
        le=52,
    )

    @field_validator("redundancy")
    @classmethod
    def validate_redundancy(cls, v: str) -> str:
        """Validate redundancy type."""
        allowed = ["LocallyRedundant", "GeoRedundant"]
        if v not in allowed:
            raise ValueError(f"Redundancy must be one of {allowed}")
        return v


class LLMavenBackupConfig(BaseModel):
    """Root configuration model for LLMaven backup infrastructure."""

    project: BackupProjectConfig = Field(
        default_factory=BackupProjectConfig, description="Backup project settings"
    )
    azure: BackupAzureConfig = Field(
        default_factory=BackupAzureConfig, description="Azure subscription settings"
    )
    primary_stack: PrimaryStackConfig = Field(
        default_factory=PrimaryStackConfig,
        description="References to primary stack resources",
    )
    backup: BackupVaultResourceConfig = Field(
        default_factory=BackupVaultResourceConfig, description="Backup vault settings"
    )
    tags: Dict[str, str] = Field(
        default_factory=lambda: {
            "Environment": "dev",
            "Project": "llmaven",
            "ManagedBy": "Pulumi",
            "Purpose": "DatabaseBackup",
        },
        description="Resource tags",
    )

    def model_post_init(self, __context: Any) -> None:
        """Post-initialization: sync environment and project tags."""
        if "Environment" in self.tags:
            self.tags["Environment"] = self.project.environment
        if "Project" in self.tags:
            self.tags["Project"] = self.project.name
