"""Pulumi program for the LLMaven backup storage stack.

Uses an existing resource group and provisions a storage account for PostgreSQL
backup dumps. Intentionally minimal — isolated from the main stack so that a
main-stack destroy does not affect backup data.

Outputs:
    backup_storage_connection_string  — storage account key-based connection
                                        string (secret); pass to the main stack
                                        as BACKUP_STORAGE_CONNECTION_STRING.
"""

from pathlib import Path


def create_backup_storage_program(config_path: Path):
    """Return an inline Pulumi program that provisions backup storage."""

    def backup_storage():

        import pulumi
        import pulumi_azure_native as azure_native
        import yaml

        from llmaven.infrastructure.resources.storage import (
            get_blob_connection_string,
            get_storage_account_key,
        )

        # Load raw config — backup config uses a lighter schema than main config
        with open(config_path) as f:
            cfg = yaml.safe_load(f)

        project_name = cfg["project"]["name"]
        environment = cfg["project"]["environment"]
        location = cfg["project"]["location"]
        rg_name = cfg["azure"]["resource_group"]
        tags = cfg.get("tags", {})

        # Storage account name: globally unique, lowercase, no hyphens, ≤24 chars
        region_suffix = location[:4].replace("-", "").lower()
        sa_name = f"{project_name.replace('-', '')}{environment}{region_suffix}bk"[:24]

        # Resource Group — created here so it survives a main-stack destroy
        rg = azure_native.resources.ResourceGroup(
            "backup-resource-group",
            resource_group_name=rg_name,
            location=location,
            tags=tags,
        )

        # Storage Account — Standard LRS, no ADLS Gen2 (plain blob storage)
        sa = azure_native.storage.StorageAccount(
            f"{project_name}-{environment}",
            resource_group_name=rg.name,
            account_name=sa_name,
            location=location,
            tags=tags,
            sku=azure_native.storage.SkuArgs(
                name=azure_native.storage.SkuName.STANDARD_LRS,
            ),
            kind=azure_native.storage.Kind.STORAGE_V2,
            is_hns_enabled=False,
            enable_https_traffic_only=True,
            minimum_tls_version=azure_native.storage.MinimumTlsVersion.TLS1_2,
            allow_blob_public_access=False,
        )

        # 3. Blob container for pg_dump files
        azure_native.storage.BlobContainer(
            f"pg-{project_name}-{environment}",
            resource_group_name=rg.name,
            account_name=sa.name,
            container_name="pg-backups",
            public_access=azure_native.storage.PublicAccess.NONE,
        )

        # 4. Output: connection string (secret) — operator copies this into
        #    BACKUP_STORAGE_CONNECTION_STRING before deploying the main stack.
        key = get_storage_account_key(
            resource_group_name=rg.name,
            storage_account_name=sa.name,
        )
        conn_str = get_blob_connection_string(
            storage_account_name=sa.name,
            storage_account_key=key,
        )

        pulumi.export("backup_storage_account_name", sa.name)
        pulumi.export("backup_resource_group", rg.name)
        pulumi.export(
            "backup_storage_connection_string", pulumi.Output.secret(conn_str)
        )

        pulumi.log.info("✓ Backup storage provisioned")

    return backup_storage
