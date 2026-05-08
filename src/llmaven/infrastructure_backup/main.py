"""Pulumi program entry point for LLMaven backup infrastructure.

This module provides the inline Pulumi program for the 'infrastructure-backup'
project. It deploys an Azure Backup Vault in an isolated resource group, entirely
separate from the primary infrastructure stack, so that backups survive accidental
deletion of the primary resource group.

Resources created:
- Azure Backup Vault (Microsoft.DataProtection/backupVaults)
- Backup Policy (weekly schedule, configurable retention)
- Backup Instance (targets the primary PostgreSQL Flexible Server)
- Two cross-RG role assignments (Reader on primary RG, PostgreSQL LTR Backup Role)
"""

from pathlib import Path


def create_backup_program(config_path: Path):
    """Create an inline Pulumi program for backup infrastructure deployment.

    Args:
        config_path: Path to the llmaven-backup-config.yaml file

    Returns:
        A callable Pulumi program function
    """

    def llmaven_backup():
        """Main Pulumi program that deploys all backup infrastructure resources."""
        import pulumi

        from llmaven.infrastructure_backup.config.loader import (
            BackupConfigLoadError,
            load_backup_config,
        )
        from llmaven.infrastructure_backup.resources import (
            assign_backup_roles,
            create_backup_instance,
            create_backup_policy,
            create_backup_vault,
        )

        # Load and validate configuration
        try:
            config = load_backup_config(config_path)
            pulumi.log.info(f"✓ Loaded backup configuration from: {config_path}")
        except BackupConfigLoadError as e:
            pulumi.log.error(f"Failed to load backup configuration: {e}")
            raise

        environment = config.project.environment
        subscription_id = config.azure.subscription_id
        resource_group = config.azure.resource_group
        location = config.project.location
        primary_rg = config.primary_stack.resource_group_name
        postgres_server_name = config.primary_stack.postgres_server_name

        vault_name = f"llmaven-backup-vault-{environment}"
        policy_name = f"postgres-weekly-{environment}"

        pulumi.log.info(f"Deploying backup stack for environment: {environment}")
        pulumi.log.info(f"Backup resource group: {resource_group}")
        pulumi.log.info(
            f"Target PostgreSQL server: {postgres_server_name} in {primary_rg}"
        )

        # 1. Create Backup Vault
        pulumi.log.info("Creating Backup Vault...")
        vault = create_backup_vault(
            resource_group_name=resource_group,
            vault_name=vault_name,
            location=location,
            config=config,
            tags=config.tags,
        )

        # 2. Create Backup Policy
        pulumi.log.info("Creating Backup Policy...")
        policy = create_backup_policy(
            resource_group_name=resource_group,
            vault_name=vault.name,
            policy_name=policy_name,
            config=config,
        )

        # 3. Assign cross-RG roles to vault's managed identity
        pulumi.log.info("Assigning cross-RG roles to vault managed identity...")
        role_assignments = assign_backup_roles(
            vault_principal_id=vault.identity.principal_id,
            subscription_id=subscription_id,
            primary_rg_name=primary_rg,
            postgres_server_name=postgres_server_name,
            environment=environment,
        )

        # 4. Create Backup Instance (depends on role assignments)
        pulumi.log.info("Creating Backup Instance...")
        create_backup_instance(
            resource_group_name=resource_group,
            vault_name=vault.name,
            policy_id=policy.id,
            subscription_id=subscription_id,
            primary_rg_name=primary_rg,
            postgres_server_name=postgres_server_name,
            location=location,
            environment=environment,
            role_assignments=role_assignments,
        )

        # Export stack outputs
        pulumi.export("backup_resource_group", resource_group)
        pulumi.export("backup_vault_name", vault.name)
        pulumi.export("environment", environment)
        pulumi.export("primary_postgres_server", postgres_server_name)
        pulumi.export("primary_resource_group", primary_rg)

        pulumi.log.info("✓ Backup infrastructure deployment complete")

    return llmaven_backup
