"""PostgreSQL Flexible Server resource module.

This module creates and configures Azure Database for PostgreSQL - Flexible Server
with support for high availability, backups, and VNet integration.
"""

from typing import Dict, List, Optional

import pulumi
import pulumi_azure_native as azure_native
from pulumi import Output

from ..config.schema import LLMavenConfig


def create_postgres_server(
    resource_group_name: Output[str],
    location: str,
    vnet_id: Output[str],
    postgres_subnet_id: Output[str],
    config: LLMavenConfig,
    admin_password: Output[str],
    tags: Dict[str, str],
) -> azure_native.dbforpostgresql.Server:
    """
    Create Azure PostgreSQL Flexible Server.

    Args:
        resource_group_name: Name of the resource group
        location: Azure region
        vnet_id: Virtual network ID
        postgres_subnet_id: PostgreSQL subnet ID
        config: LLMaven configuration
        admin_password: Admin password from Key Vault
        tags: Resource tags

    Returns:
        PostgreSQL Flexible Server resource
    """
    db_config = config.database
    project_name = config.project.name
    environment = config.project.environment

    # Server name
    server_name = f"{project_name}-postgres-{environment}"

    # Create Private DNS Zone for PostgreSQL
    private_dns_zone = azure_native.privatedns.PrivateZone(
        f"postgres-private-dns-zone-{environment}",
        resource_group_name=resource_group_name,
        private_zone_name=f"{server_name}.private.postgres.database.azure.com",
        location="global",
        tags=tags,
    )

    # Link Private DNS Zone to VNet
    vnet_link = azure_native.privatedns.VirtualNetworkLink(
        f"postgres-dns-vnet-link-{environment}",
        resource_group_name=resource_group_name,
        private_zone_name=private_dns_zone.name,
        virtual_network_link_name=f"{server_name}-vnet-link",
        location="global",
        registration_enabled=False,
        virtual_network=azure_native.privatedns.SubResourceArgs(
            id=vnet_id,
        ),
        tags=tags,
    )

    # Create PostgreSQL Flexible Server
    postgres_server = azure_native.dbforpostgresql.Server(
        f"postgres-server-{environment}",
        resource_group_name=resource_group_name,
        server_name=server_name,
        location=location,
        # SKU configuration
        sku=azure_native.dbforpostgresql.SkuArgs(
            name=db_config.sku_name,
            tier=_get_sku_tier(db_config.sku_name),
        ),
        # Storage configuration
        storage=azure_native.dbforpostgresql.StorageArgs(
            storage_size_gb=db_config.storage_size_gb,
        ),
        # Backup configuration
        backup=azure_native.dbforpostgresql.BackupArgs(
            backup_retention_days=db_config.backup_retention_days,
            geo_redundant_backup="Enabled" if db_config.geo_redundant_backup else "Disabled",
        ),
        # High availability configuration
        high_availability=azure_native.dbforpostgresql.HighAvailabilityArgs(
            mode="ZoneRedundant" if db_config.high_availability else "Disabled",
        ),
        # Network configuration
        network=azure_native.dbforpostgresql.NetworkArgs(
            delegated_subnet_resource_id=postgres_subnet_id,
            private_dns_zone_arm_resource_id=private_dns_zone.id,
        ),
        # PostgreSQL version
        version=db_config.postgresql_version,
        # Administrator credentials
        administrator_login=db_config.admin_login,
        administrator_login_password=admin_password,
        opts=pulumi.ResourceOptions(depends_on=[vnet_link]),
        tags=tags,
    )

    pulumi.export(f"postgres_server_name_{environment}", postgres_server.name)
    pulumi.export(
        f"postgres_server_fqdn_{environment}",
        postgres_server.fully_qualified_domain_name,
    )

    return postgres_server


def create_databases(
    resource_group_name: Output[str],
    server_name: Output[str],
    database_names: List[str],
    environment: str,
    tags: Dict[str, str],
) -> List[azure_native.dbforpostgresql.Database]:
    """
    Create PostgreSQL databases.

    Args:
        resource_group_name: Name of the resource group
        server_name: PostgreSQL server name
        database_names: List of database names to create
        environment: Environment name
        tags: Resource tags

    Returns:
        List of PostgreSQL Database resources
    """
    databases = []

    for db_name in database_names:
        database = azure_native.dbforpostgresql.Database(
            f"postgres-db-{db_name}-{environment}",
            resource_group_name=resource_group_name,
            server_name=server_name,
            database_name=db_name,
            charset="UTF8",
            collation="en_US.utf8",
        )
        databases.append(database)

        pulumi.export(f"postgres_database_{db_name}_{environment}", database.name)

    return databases


def configure_firewall_rules(
    resource_group_name: Output[str],
    server_name: Output[str],
    environment: str,
    allow_azure_services: bool = True,
    allowed_ip_ranges: Optional[List[Dict[str, str]]] = None,
) -> List[azure_native.dbforpostgresql.FirewallRule]:
    """
    Configure PostgreSQL firewall rules.

    Args:
        resource_group_name: Name of the resource group
        server_name: PostgreSQL server name
        environment: Environment name
        allow_azure_services: Allow Azure services to access server
        allowed_ip_ranges: List of allowed IP ranges (format: [{"name": "rule1", "start": "1.2.3.4", "end": "1.2.3.4"}])

    Returns:
        List of firewall rules
    """
    firewall_rules = []

    # Allow Azure services (required for Container Apps access)
    if allow_azure_services:
        azure_services_rule = azure_native.dbforpostgresql.FirewallRule(
            f"postgres-fw-azure-services-{environment}",
            resource_group_name=resource_group_name,
            server_name=server_name,
            firewall_rule_name="AllowAllAzureServicesAndResourcesWithinAzureIps",
            start_ip_address="0.0.0.0",
            end_ip_address="0.0.0.0",
        )
        firewall_rules.append(azure_services_rule)

    # Add custom IP ranges
    if allowed_ip_ranges:
        for idx, ip_range in enumerate(allowed_ip_ranges):
            rule = azure_native.dbforpostgresql.FirewallRule(
                f"postgres-fw-custom-{idx}-{environment}",
                resource_group_name=resource_group_name,
                server_name=server_name,
                firewall_rule_name=ip_range.get("name", f"CustomRule{idx}"),
                start_ip_address=ip_range["start"],
                end_ip_address=ip_range["end"],
            )
            firewall_rules.append(rule)

    return firewall_rules


def configure_server_parameters(
    resource_group_name: Output[str],
    server_name: Output[str],
    environment: str,
) -> List[azure_native.dbforpostgresql.Configuration]:
    """
    Configure PostgreSQL server parameters for optimal performance.

    Args:
        resource_group_name: Name of the resource group
        server_name: PostgreSQL server name
        environment: Environment name

    Returns:
        List of server configuration resources
    """
    configurations = []

    # Production-optimized parameters
    if environment == "prod":
        params = {
            "max_connections": "200",
            "shared_buffers": "512MB",
            "effective_cache_size": "1536MB",
            "maintenance_work_mem": "128MB",
            "checkpoint_completion_target": "0.9",
            "wal_buffers": "16MB",
            "default_statistics_target": "100",
            "random_page_cost": "1.1",
            "effective_io_concurrency": "200",
            "work_mem": "2621kB",
            "min_wal_size": "1GB",
            "max_wal_size": "4GB",
        }
    else:
        # Development/staging parameters
        params = {
            "max_connections": "100",
            "shared_buffers": "256MB",
            "effective_cache_size": "768MB",
            "maintenance_work_mem": "64MB",
        }

    for param_name, param_value in params.items():
        config = azure_native.dbforpostgresql.Configuration(
            f"postgres-config-{param_name.replace('_', '-')}-{environment}",
            resource_group_name=resource_group_name,
            server_name=server_name,
            configuration_name=param_name,
            value=param_value,
            source="user-override",
        )
        configurations.append(config)

    return configurations


def get_connection_string(
    server_fqdn: Output[str],
    database_name: str,
    admin_login: str,
    admin_password: Output[str],
    ssl_mode: str = "require",
) -> Output[str]:
    """
    Generate PostgreSQL connection string.

    Args:
        server_fqdn: Fully qualified domain name of the server
        database_name: Database name
        admin_login: Admin username
        admin_password: Admin password
        ssl_mode: SSL mode (require, verify-ca, verify-full)

    Returns:
        PostgreSQL connection string
    """
    return Output.all(server_fqdn, admin_password).apply(
        lambda args: (
            f"postgresql://{admin_login}:{args[1]}@{args[0]}:5432/{database_name}?sslmode={ssl_mode}"
        )
    )


def _get_sku_tier(sku_name: str) -> str:
    """
    Extract SKU tier from SKU name.

    Args:
        sku_name: SKU name (e.g., Standard_B1ms, Standard_D2s_v3, Standard_E4s_v3)

    Returns:
        SKU tier (Burstable, GeneralPurpose, MemoryOptimized)
    """
    # Azure PostgreSQL Flexible Server uses Standard_* format
    # Determine tier based on the VM series letter after Standard_
    if "_B" in sku_name:  # Standard_B1ms, Standard_B2s, etc.
        return "Burstable"
    elif "_D" in sku_name or "_E" in sku_name:  # Standard_D2s_v3, Standard_E4s_v3, etc.
        return "GeneralPurpose"
    elif "_M" in sku_name:  # Standard_M* series
        return "MemoryOptimized"
    else:
        # Default to GeneralPurpose for unknown SKUs
        pulumi.log.warn(
            f"Unknown SKU tier for {sku_name}, defaulting to GeneralPurpose. "
            "Expected format: Standard_B*, Standard_D*, Standard_E*, or Standard_M*"
        )
        return "GeneralPurpose"
