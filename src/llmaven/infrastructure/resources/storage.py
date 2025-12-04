"""Azure Blob Storage resource module.

This module creates and configures Azure Blob Storage (ADLS Gen2) with
lifecycle management policies, encryption, and container creation.
"""

from typing import Dict, List

import pulumi
import pulumi_azure_native as azure_native
from pulumi import Output

from ..config.schema import LLMavenConfig


def create_storage_account(
    resource_group_name: Output[str],
    location: str,
    config: LLMavenConfig,
    tags: Dict[str, str],
) -> azure_native.storage.StorageAccount:
    """
    Create Azure Storage Account with ADLS Gen2 support.

    Args:
        resource_group_name: Name of the resource group
        location: Azure region
        config: LLMaven configuration
        tags: Resource tags

    Returns:
        Storage Account resource
    """
    storage_config = config.storage
    project_name = config.project.name
    environment = config.project.environment

    # Storage account name (must be globally unique, lowercase, no hyphens, 3-24 chars)
    # Format: {project}{environment}{region}st (max 24 chars)
    # Add region suffix to ensure global uniqueness
    region_suffix = location[:4].replace("-", "").lower()  # e.g., "westus2" -> "west"
    storage_account_name = f"{project_name}{environment}{region_suffix}st".lower().replace(
        "-", ""
    )[:24]

    # Create Storage Account
    storage_account = azure_native.storage.StorageAccount(
        f"storage-account-{environment}",
        resource_group_name=resource_group_name,
        account_name=storage_account_name,
        location=location,
        tags=tags,
        # SKU configuration
        sku=azure_native.storage.SkuArgs(
            name=_get_sku_name(storage_config.account_tier, storage_config.account_replication),
        ),
        kind=azure_native.storage.Kind.STORAGE_V2,
        # Enable hierarchical namespace for ADLS Gen2
        is_hns_enabled=storage_config.enable_hierarchical_namespace,
        # Security configuration
        enable_https_traffic_only=True,
        minimum_tls_version=azure_native.storage.MinimumTlsVersion.TLS1_2,
        allow_blob_public_access=False,
        # Encryption configuration
        encryption=azure_native.storage.EncryptionArgs(
            services=azure_native.storage.EncryptionServicesArgs(
                blob=azure_native.storage.EncryptionServiceArgs(
                    enabled=True,
                    key_type=azure_native.storage.KeyType.ACCOUNT,
                ),
                file=azure_native.storage.EncryptionServiceArgs(
                    enabled=True,
                    key_type=azure_native.storage.KeyType.ACCOUNT,
                ),
            ),
            key_source=azure_native.storage.KeySource.MICROSOFT_STORAGE,
        ),
        # Network configuration
        network_rule_set=azure_native.storage.NetworkRuleSetArgs(
            default_action=azure_native.storage.DefaultAction.ALLOW
            if not config.security.enable_private_endpoints
            else azure_native.storage.DefaultAction.DENY,
            bypass=azure_native.storage.Bypass.AZURE_SERVICES,
        ),
        # Access tier
        access_tier=azure_native.storage.AccessTier.HOT,
    )

    pulumi.export(f"storage_account_name_{environment}", storage_account.name)
    pulumi.export(
        f"storage_account_primary_endpoint_{environment}",
        storage_account.primary_endpoints,
    )

    return storage_account


def create_blob_containers(
    resource_group_name: Output[str],
    storage_account_name: Output[str],
    container_names: List[str],
    environment: str,
) -> List[azure_native.storage.BlobContainer]:
    """
    Create blob containers in the storage account.

    Args:
        resource_group_name: Name of the resource group
        storage_account_name: Storage account name
        container_names: List of container names to create
        environment: Environment name

    Returns:
        List of BlobContainer resources
    """
    containers = []

    for container_name in container_names:
        container = azure_native.storage.BlobContainer(
            f"blob-container-{container_name}-{environment}",
            resource_group_name=resource_group_name,
            account_name=storage_account_name,
            container_name=container_name,
            # Private access level (no anonymous access)
            public_access=azure_native.storage.PublicAccess.NONE,
        )
        containers.append(container)

        pulumi.export(
            f"blob_container_{container_name}_{environment}", container.name
        )

    return containers


def create_lifecycle_management_policy(
    resource_group_name: Output[str],
    storage_account_name: Output[str],
    environment: str,
) -> azure_native.storage.ManagementPolicy:
    """
    Create blob lifecycle management policy.

    This policy implements the following rules:
    - Move blobs to Cool tier after 30 days of no access
    - Move blobs to Archive tier after 90 days of no access
    - Delete old snapshots after 180 days
    - Delete soft-deleted blobs after 30 days

    Args:
        resource_group_name: Name of the resource group
        storage_account_name: Storage account name
        environment: Environment name

    Returns:
        ManagementPolicy resource
    """
    # Different policies for different environments
    if environment == "prod":
        # Production: More aggressive cost optimization
        rules = [
            # Rule 1: Tier optimization for base blobs
            azure_native.storage.ManagementPolicyRuleArgs(
                name="tierOptimization",
                enabled=True,
                type=azure_native.storage.RuleType.LIFECYCLE,
                definition=azure_native.storage.ManagementPolicyDefinitionArgs(
                    actions=azure_native.storage.ManagementPolicyActionArgs(
                        base_blob=azure_native.storage.ManagementPolicyBaseBlobArgs(
                            tier_to_cool=azure_native.storage.DateAfterModificationArgs(
                                days_after_modification_greater_than=30,
                            ),
                            tier_to_archive=azure_native.storage.DateAfterModificationArgs(
                                days_after_modification_greater_than=90,
                            ),
                            delete=azure_native.storage.DateAfterModificationArgs(
                                days_after_modification_greater_than=365,  # Delete after 1 year
                            ),
                        ),
                    ),
                    filters=azure_native.storage.ManagementPolicyFilterArgs(
                        blob_types=["blockBlob"],
                        prefix_match=["mlflow/", "llmaven/"],
                    ),
                ),
            ),
            # Rule 2: Snapshot cleanup
            azure_native.storage.ManagementPolicyRuleArgs(
                name="snapshotCleanup",
                enabled=True,
                type=azure_native.storage.RuleType.LIFECYCLE,
                definition=azure_native.storage.ManagementPolicyDefinitionArgs(
                    actions=azure_native.storage.ManagementPolicyActionArgs(
                        snapshot=azure_native.storage.ManagementPolicySnapShotArgs(
                            delete=azure_native.storage.DateAfterCreationArgs(
                                days_after_creation_greater_than=180,
                            ),
                        ),
                    ),
                    filters=azure_native.storage.ManagementPolicyFilterArgs(
                        blob_types=["blockBlob"],
                    ),
                ),
            ),
            # Rule 3: Delete soft-deleted blobs
            azure_native.storage.ManagementPolicyRuleArgs(
                name="softDeleteCleanup",
                enabled=True,
                type=azure_native.storage.RuleType.LIFECYCLE,
                definition=azure_native.storage.ManagementPolicyDefinitionArgs(
                    actions=azure_native.storage.ManagementPolicyActionArgs(
                        base_blob=azure_native.storage.ManagementPolicyBaseBlobArgs(
                            delete=azure_native.storage.DateAfterModificationArgs(
                                days_after_modification_greater_than=30,
                            ),
                        ),
                    ),
                    filters=azure_native.storage.ManagementPolicyFilterArgs(
                        blob_types=["blockBlob"],
                    ),
                ),
            ),
        ]
    else:
        # Dev/Staging: Less aggressive, shorter retention
        rules = [
            # Rule 1: Basic tier optimization
            azure_native.storage.ManagementPolicyRuleArgs(
                name="tierOptimization",
                enabled=True,
                type=azure_native.storage.RuleType.LIFECYCLE,
                definition=azure_native.storage.ManagementPolicyDefinitionArgs(
                    actions=azure_native.storage.ManagementPolicyActionArgs(
                        base_blob=azure_native.storage.ManagementPolicyBaseBlobArgs(
                            tier_to_cool=azure_native.storage.DateAfterModificationArgs(
                                days_after_modification_greater_than=7,
                            ),
                            delete=azure_native.storage.DateAfterModificationArgs(
                                days_after_modification_greater_than=90,  # Delete after 90 days
                            ),
                        ),
                    ),
                    filters=azure_native.storage.ManagementPolicyFilterArgs(
                        blob_types=["blockBlob"],
                        prefix_match=["mlflow/", "llmaven/"],
                    ),
                ),
            ),
            # Rule 2: Snapshot cleanup (shorter retention)
            azure_native.storage.ManagementPolicyRuleArgs(
                name="snapshotCleanup",
                enabled=True,
                type=azure_native.storage.RuleType.LIFECYCLE,
                definition=azure_native.storage.ManagementPolicyDefinitionArgs(
                    actions=azure_native.storage.ManagementPolicyActionArgs(
                        snapshot=azure_native.storage.ManagementPolicySnapShotArgs(
                            delete=azure_native.storage.DateAfterCreationArgs(
                                days_after_creation_greater_than=30,
                            ),
                        ),
                    ),
                    filters=azure_native.storage.ManagementPolicyFilterArgs(
                        blob_types=["blockBlob"],
                    ),
                ),
            ),
        ]

    # Create lifecycle management policy
    lifecycle_policy = azure_native.storage.ManagementPolicy(
        f"blob-lifecycle-policy-{environment}",
        resource_group_name=resource_group_name,
        account_name=storage_account_name,
        management_policy_name="default",
        policy=azure_native.storage.ManagementPolicySchemaArgs(
            rules=rules,
        ),
    )

    pulumi.export(
        f"storage_lifecycle_policy_{environment}", lifecycle_policy.name
    )

    return lifecycle_policy


def enable_blob_versioning(
    resource_group_name: Output[str],
    storage_account_name: Output[str],
    environment: str,
) -> azure_native.storage.BlobServiceProperties:
    """
    Enable blob versioning and soft delete.

    Args:
        resource_group_name: Name of the resource group
        storage_account_name: Storage account name
        environment: Environment name

    Returns:
        BlobServiceProperties resource
    """
    # Different retention for different environments
    soft_delete_days = 30 if environment == "prod" else 7

    blob_service_properties = azure_native.storage.BlobServiceProperties(
        f"blob-service-properties-{environment}",
        resource_group_name=resource_group_name,
        account_name=storage_account_name,
        blob_services_name="default",
        # Enable versioning
        is_versioning_enabled=True,
        # Enable soft delete for blobs
        delete_retention_policy=azure_native.storage.DeleteRetentionPolicyArgs(
            enabled=True,
            days=soft_delete_days,
        ),
        # Enable soft delete for containers
        container_delete_retention_policy=azure_native.storage.DeleteRetentionPolicyArgs(
            enabled=True,
            days=soft_delete_days,
        ),
        # Enable change feed for auditing (production only)
        change_feed=azure_native.storage.ChangeFeedArgs(
            enabled=(environment == "prod"),
            retention_in_days=90 if environment == "prod" else None,
        ),
    )

    pulumi.export(
        f"blob_service_versioning_{environment}",
        "enabled",
    )

    return blob_service_properties


def get_storage_account_key(
    resource_group_name: Output[str],
    storage_account_name: Output[str],
) -> Output[str]:
    """
    Retrieve the primary access key for the storage account.

    Args:
        resource_group_name: Name of the resource group
        storage_account_name: Storage account name

    Returns:
        Primary storage account key
    """
    keys = azure_native.storage.list_storage_account_keys_output(
        resource_group_name=resource_group_name,
        account_name=storage_account_name,
    )

    return keys.keys[0].value


def get_blob_connection_string(
    storage_account_name: Output[str],
    storage_account_key: Output[str],
) -> Output[str]:
    """
    Generate blob storage connection string.

    Args:
        storage_account_name: Storage account name
        storage_account_key: Storage account key

    Returns:
        Blob storage connection string
    """
    return Output.all(storage_account_name, storage_account_key).apply(
        lambda args: (
            f"DefaultEndpointsProtocol=https;"
            f"AccountName={args[0]};"
            f"AccountKey={args[1]};"
            f"EndpointSuffix=core.windows.net"
        )
    )


def _get_sku_name(tier: str, replication: str) -> str:
    """
    Get SKU name from tier and replication type.

    Args:
        tier: Storage account tier (Standard or Premium)
        replication: Replication type (LRS, GRS, ZRS, GZRS)

    Returns:
        SKU name (e.g., Standard_LRS, Premium_ZRS)
    """
    return f"{tier}_{replication}"
