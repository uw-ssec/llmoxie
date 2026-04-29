"""Azure Backup Vault resources for PostgreSQL Flexible Server.

Creates and configures an Azure Backup Vault (Microsoft.DataProtection/backupVaults)
with a weekly backup policy and a backup instance targeting the primary PostgreSQL
Flexible Server. Role assignments are created cross-RG so the vault's managed identity
can trigger backups without credentials.

Backup data is stored in Microsoft-managed storage outside the customer's subscription,
so it survives deletion of the primary resource group.

Recovery: backups restore as .sql files to a target storage account. Use pg_restore
to reconstruct the database on a new server.
"""

import uuid
from typing import List

import pulumi
import pulumi_azure_native as azure_native
from pulumi import Output

from ..config.schema import LLMavenBackupConfig

# Azure built-in role definition GUIDs (consistent across all subscriptions/tenants).
# Verify with: az role definition list --name "Reader" --query "[0].name"
_READER_ROLE_ID = "acdd72a7-3385-48ef-bd42-f606fba81ae7"

# Verify with:
# az role definition list \
#   --name "PostgreSQL Flexible Server Long Term Retention Backup Role" \
#   --query "[0].name"
_POSTGRES_LTR_BACKUP_ROLE_ID = "c088a766-074b-43ba-90d4-1fb21feae531"


def _stable_uuid(seed: str) -> str:
    """Generate a deterministic UUID from a seed string.

    Used for role assignment names — Azure requires a UUID and rejects duplicates,
    so re-running Pulumi must produce the same name to be idempotent.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"llmaven-backup.{seed}"))


def create_backup_vault(
    resource_group_name: Output[str],
    vault_name: str,
    location: str,
    config: LLMavenBackupConfig,
    tags: dict,
) -> azure_native.dataprotection.BackupVault:
    """Create an Azure Backup Vault with system-assigned managed identity.

    The vault's MSI is used for cross-RG role assignments that authorize it
    to trigger backups on the PostgreSQL Flexible Server.

    Args:
        resource_group_name: Backup resource group name
        vault_name: Name of the backup vault
        location: Azure region
        config: LLMaven backup configuration
        tags: Resource tags

    Returns:
        Backup vault resource
    """
    environment = config.project.environment

    # Immutability state: "Unlocked" allows admin override; "Locked" is permanent.
    # We use "Unlocked" so that operators can still remove a misconfigured vault,
    # while still preventing accidental deletion during normal operations.
    immutability_state = (
        "Unlocked" if config.backup.immutability_enabled else "Disabled"
    )

    vault = azure_native.dataprotection.BackupVault(
        f"backup-vault-{environment}",
        resource_group_name=resource_group_name,
        vault_name=vault_name,
        location=location,
        identity=azure_native.dataprotection.DppIdentityDetailsArgs(
            type="SystemAssigned",
        ),
        properties=azure_native.dataprotection.BackupVaultArgs(
            storage_settings=[
                azure_native.dataprotection.StorageSettingArgs(
                    datastore_type="VaultStore",
                    type=config.backup.redundancy,
                )
            ],
            security_settings=azure_native.dataprotection.SecuritySettingsArgs(
                immutability_settings=azure_native.dataprotection.ImmutabilitySettingsArgs(
                    state=immutability_state,
                ),
                soft_delete_settings=azure_native.dataprotection.SoftDeleteSettingsArgs(
                    retention_duration_in_days=config.backup.soft_delete_retention_days,
                    state="On",
                ),
            ),
        ),
        tags=tags,
    )

    pulumi.export(f"backup_vault_name_{environment}", vault.name)
    pulumi.export(f"backup_vault_id_{environment}", vault.id)

    return vault


def create_backup_policy(
    resource_group_name: Output[str],
    vault_name: Output[str],
    policy_name: str,
    config: LLMavenBackupConfig,
) -> azure_native.dataprotection.BackupPolicy:
    """Create a weekly backup policy for PostgreSQL Flexible Server.

    The policy defines:
    - Schedule: weekly (configurable start time and day via backup_schedule_utc)
    - Retention: configurable number of weekly recovery points

    Args:
        resource_group_name: Backup resource group name
        vault_name: Backup vault name
        policy_name: Name of the backup policy
        config: LLMaven backup configuration

    Returns:
        Backup policy resource
    """
    environment = config.project.environment
    retention_duration = f"P{config.backup.retention_weeks}W"

    policy = azure_native.dataprotection.BackupPolicy(
        f"backup-policy-{environment}",
        resource_group_name=resource_group_name,
        vault_name=vault_name,
        backup_policy_name=policy_name,
        properties=azure_native.dataprotection.BackupPolicyArgs(
            datasource_types=["AzureDatabaseForPostgreSQLFlexibleServer"],
            object_type="BackupPolicy",
            policy_rules=[
                # Backup rule: trigger weekly full backups
                azure_native.dataprotection.AzureBackupRuleArgs(
                    name="BackupWeekly",
                    object_type="AzureBackupRule",
                    backup_parameters=azure_native.dataprotection.AzureBackupParamsArgs(
                        backup_type="Full",
                        object_type="AzureBackupParams",
                    ),
                    data_store=azure_native.dataprotection.DataStoreInfoBaseArgs(
                        data_store_type="VaultStore",
                        object_type="DataStoreInfoBase",
                    ),
                    trigger=azure_native.dataprotection.ScheduleBasedTriggerContextArgs(
                        object_type="ScheduleBasedTriggerContext",
                        schedule=azure_native.dataprotection.BackupScheduleArgs(
                            repeating_time_intervals=[
                                config.backup.backup_schedule_utc
                            ],
                            time_zone="UTC",
                        ),
                        tagging_criteria=[
                            azure_native.dataprotection.TaggingCriteriaArgs(
                                is_default=True,
                                tag_info=azure_native.dataprotection.RetentionTagArgs(
                                    tag_name="Default",
                                ),
                                tagging_priority=99,
                            ),
                        ],
                    ),
                ),
                # Retention rule: keep weekly backups for the configured duration
                azure_native.dataprotection.AzureRetentionRuleArgs(
                    name="Default",
                    object_type="AzureRetentionRule",
                    is_default=True,
                    lifecycles=[
                        azure_native.dataprotection.SourceLifeCycleArgs(
                            delete_after=azure_native.dataprotection.AbsoluteDeleteOptionArgs(
                                duration=retention_duration,
                                object_type="AbsoluteDeleteOption",
                            ),
                            source_data_store=azure_native.dataprotection.DataStoreInfoBaseArgs(
                                data_store_type="VaultStore",
                                object_type="DataStoreInfoBase",
                            ),
                        ),
                    ],
                ),
            ],
        ),
    )

    return policy


def assign_backup_roles(
    vault_principal_id: Output[str],
    subscription_id: str,
    primary_rg_name: str,
    postgres_server_name: str,
    environment: str,
) -> List[azure_native.authorization.RoleAssignment]:
    """Grant the vault's managed identity the permissions needed to back up PostgreSQL.

    Two role assignments are created, both scoped to resources in the primary stack's
    resource group:

    1. Reader on the primary resource group — allows the vault to enumerate resources.
    2. PostgreSQL Flexible Server Long Term Retention Backup Role on the server —
       allows the vault to trigger pg_dump-style backups via Azure Resource Manager.

    These are cross-RG assignments: the backup stack manages them, but they apply
    to resources owned by the primary stack. If the primary stack is destroyed,
    these assignments become orphaned (the target resources no longer exist) but
    the vault and its recovery points are unaffected.

    Args:
        vault_principal_id: Object ID of the vault's system-assigned managed identity
        subscription_id: Azure subscription ID
        primary_rg_name: Resource group name of the primary infrastructure
        postgres_server_name: Name of the PostgreSQL Flexible Server in the primary stack
        environment: Deployment environment (for stable UUID seeding)

    Returns:
        List of [rg_reader_assignment, server_backup_assignment]
    """
    rg_scope = f"/subscriptions/{subscription_id}/resourceGroups/{primary_rg_name}"
    server_scope = (
        f"/subscriptions/{subscription_id}"
        f"/resourceGroups/{primary_rg_name}"
        f"/providers/Microsoft.DBforPostgreSQL/flexibleServers/{postgres_server_name}"
    )

    def _role_definition_id(role_guid: str) -> str:
        return (
            f"/subscriptions/{subscription_id}"
            f"/providers/Microsoft.Authorization/roleDefinitions/{role_guid}"
        )

    # 1. Reader on the primary resource group
    rg_reader = azure_native.authorization.RoleAssignment(
        f"backup-vault-rg-reader-{environment}",
        scope=rg_scope,
        role_assignment_name=_stable_uuid(f"rg-reader-{environment}-{primary_rg_name}"),
        principal_id=vault_principal_id,
        principal_type="ServicePrincipal",
        role_definition_id=_role_definition_id(_READER_ROLE_ID),
    )

    # 2. PostgreSQL Flexible Server Long Term Retention Backup Role on the server
    pg_backup = azure_native.authorization.RoleAssignment(
        f"backup-vault-pg-backup-{environment}",
        scope=server_scope,
        role_assignment_name=_stable_uuid(
            f"pg-backup-{environment}-{primary_rg_name}-{postgres_server_name}"
        ),
        principal_id=vault_principal_id,
        principal_type="ServicePrincipal",
        role_definition_id=_role_definition_id(_POSTGRES_LTR_BACKUP_ROLE_ID),
    )

    return [rg_reader, pg_backup]


def create_backup_instance(
    resource_group_name: Output[str],
    vault_name: Output[str],
    policy_id: Output[str],
    subscription_id: str,
    primary_rg_name: str,
    postgres_server_name: str,
    location: str,
    environment: str,
    role_assignments: list,
) -> azure_native.dataprotection.BackupInstance:
    """Create the backup instance linking the vault to the PostgreSQL Flexible Server.

    The backup instance must be created after the role assignments exist, because
    Azure validates the vault's permissions during instance creation.

    Args:
        resource_group_name: Backup resource group name
        vault_name: Backup vault name
        policy_id: Resource ID of the backup policy
        subscription_id: Azure subscription ID
        primary_rg_name: Primary stack resource group name
        postgres_server_name: PostgreSQL Flexible Server name in primary stack
        location: Azure region of the PostgreSQL server
        environment: Deployment environment
        role_assignments: Role assignment resources (creates depends_on ordering)

    Returns:
        Backup instance resource
    """
    server_resource_id = (
        f"/subscriptions/{subscription_id}"
        f"/resourceGroups/{primary_rg_name}"
        f"/providers/Microsoft.DBforPostgreSQL/flexibleServers/{postgres_server_name}"
    )
    instance_name = f"postgres-{postgres_server_name}"

    instance = azure_native.dataprotection.BackupInstance(
        f"postgres-backup-instance-{environment}",
        resource_group_name=resource_group_name,
        vault_name=vault_name,
        backup_instance_name=instance_name,
        properties=azure_native.dataprotection.BackupInstanceArgs(
            object_type="BackupInstance",
            friendly_name=f"PostgreSQL {postgres_server_name} ({environment})",
            datasource_info=azure_native.dataprotection.DatasourceArgs(
                object_type="Datasource",
                resource_id=server_resource_id,
                resource_name=postgres_server_name,
                resource_type="Microsoft.DBforPostgreSQL/flexibleServers",
                resource_uri=server_resource_id,
                resource_location=location,
                datasource_type="AzureDatabaseForPostgreSQLFlexibleServer",
            ),
            policy_info=azure_native.dataprotection.PolicyInfoArgs(
                policy_id=policy_id,
            ),
        ),
        opts=pulumi.ResourceOptions(depends_on=role_assignments),
    )

    pulumi.export(f"backup_instance_name_{environment}", instance.name)

    return instance
