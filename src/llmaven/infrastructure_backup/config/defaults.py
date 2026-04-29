"""Environment-specific defaults for backup infrastructure configuration."""

from .schema import (
    BackupAzureConfig,
    BackupProjectConfig,
    BackupVaultResourceConfig,
    LLMavenBackupConfig,
    PrimaryStackConfig,
)


def generate_default_backup_config(environment: str) -> LLMavenBackupConfig:
    """Generate environment-appropriate backup configuration defaults.

    Args:
        environment: Target environment (dev, staging, prod)

    Returns:
        LLMavenBackupConfig with environment-specific defaults
    """
    if environment == "prod":
        backup = BackupVaultResourceConfig(
            redundancy="GeoRedundant",
            immutability_enabled=True,
            soft_delete_retention_days=30.0,
            backup_schedule_utc="R/2024-01-01T02:00:00Z/P1W",
            retention_weeks=52,  # 1 year of weekly backups
        )
    elif environment == "staging":
        backup = BackupVaultResourceConfig(
            redundancy="LocallyRedundant",
            immutability_enabled=True,
            soft_delete_retention_days=14.0,
            backup_schedule_utc="R/2024-01-01T02:00:00Z/P1W",
            retention_weeks=12,  # 3 months of weekly backups
        )
    else:  # dev
        backup = BackupVaultResourceConfig(
            redundancy="LocallyRedundant",
            immutability_enabled=False,
            soft_delete_retention_days=7.0,
            backup_schedule_utc="R/2024-01-01T02:00:00Z/P1W",
            retention_weeks=4,
        )

    return LLMavenBackupConfig(
        project=BackupProjectConfig(
            name="llmaven-backup",
            environment=environment,
            location="eastus",
        ),
        azure=BackupAzureConfig(
            subscription_id="",
            tenant_id=None,
            resource_group=None,
        ),
        primary_stack=PrimaryStackConfig(
            resource_group_name="",
            postgres_server_name="",
            pulumi_state_store="",
        ),
        backup=backup,
        tags={
            "Environment": environment,
            "Project": "llmaven",
            "ManagedBy": "Pulumi",
            "Purpose": "DatabaseBackup",
        },
    )


def get_backup_config_template_yaml(environment: str) -> str:
    """Generate a YAML template with comments for the backup config file.

    Args:
        environment: Target environment

    Returns:
        YAML string with inline documentation comments
    """
    cfg = generate_default_backup_config(environment)
    redundancy = cfg.backup.redundancy
    immutability = str(cfg.backup.immutability_enabled).lower()
    soft_delete = cfg.backup.soft_delete_retention_days
    retention = cfg.backup.retention_weeks

    return f"""\
# LLMaven Backup Infrastructure Configuration
# Generated for environment: {environment}
#
# This file configures the separate 'infrastructure-backup' Pulumi project which
# deploys an Azure Backup Vault in an isolated resource group. Backups survive
# deletion of the primary infrastructure resource group.
#
# SETUP STEPS:
#   1. Fill in azure.subscription_id
#   2. Run: llmaven infra backup init --from-primary-stack -c llmaven-config.yaml
#      (auto-populates primary_stack.* from your deployed primary stack)
#   3. Review and adjust backup settings below
#   4. Run: llmaven infra backup deploy -c llmaven-backup-config.yaml

project:
  name: llmaven-backup
  environment: {environment}
  location: eastus           # Must match primary stack location
  enable_passphrase: false
  pulumi_state_store:        # Auto-set by 'llmaven infra backup init'

azure:
  subscription_id: ""        # Required: same subscription as primary stack
  tenant_id:                 # Optional: auto-detected from Azure CLI
  resource_group:            # Auto-set by 'llmaven infra backup init'

# References to the primary infrastructure stack.
# Auto-populated by: llmaven infra backup init --from-primary-stack
primary_stack:
  resource_group_name: ""    # Primary resource group (Reader role will be granted here)
  postgres_server_name: ""   # PostgreSQL Flexible Server name
  pulumi_state_store: ""     # Primary stack Pulumi state storage account

backup:
  # Storage redundancy for backup data
  # LocallyRedundant: 3 copies in one datacenter (cheaper)
  # GeoRedundant: replicated to paired region (recommended for prod)
  redundancy: {redundancy}

  # Prevent deletion of recovery points even by vault administrators.
  # Recommended: true for production. Once locked, cannot be disabled.
  immutability_enabled: {immutability}

  # Soft-delete: how long (days) deleted backups are recoverable before permanent removal
  soft_delete_retention_days: {soft_delete}

  # Weekly backup schedule in ISO 8601 recurring interval format
  # Default: every Sunday at 02:00 UTC
  backup_schedule_utc: "R/2024-01-01T02:00:00Z/P1W"

  # Number of weekly recovery points to keep
  retention_weeks: {retention}

tags:
  Environment: {environment}
  Project: llmaven
  ManagedBy: Pulumi
  Purpose: DatabaseBackup
"""
