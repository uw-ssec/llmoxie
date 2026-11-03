"""Azure Managed Redis resource module.

LiteLLM keeps rate limits, budgets and router state per replica unless the
replicas share a Redis. This module provisions Azure Managed Redis
(``Microsoft.Cache/redisEnterprise``) behind a private endpoint and rewrites the
LiteLLM config so its router uses it.

Azure Cache for Redis (``azure_native.cache.Redis``) is being retired, so it is
deliberately not used here.
"""

import io
from dataclasses import dataclass
from typing import Dict

import pulumi
import pulumi_azure_native as azure_native
from pulumi import Output
from ruamel.yaml import YAML

from ..config.schema import LLMavenConfig

# Azure Managed Redis serves TLS only on this port for every clustering policy
# that presents a single endpoint (EnterpriseCluster, NoCluster).
REDIS_PORT = 10000

# Private DNS zone for Azure Managed Redis private endpoints. Clients still
# connect to <name>.<region>.redis.azure.net; the public zone CNAMEs to this one.
REDIS_PRIVATE_DNS_ZONE = "privatelink.redis.azure.net"

# Env var -> Key Vault secret name for the LiteLLM container app.
REDIS_KEY_VAULT_SECRET_REFS: Dict[str, str] = {
    "REDIS_HOST": "redis-host",
    "REDIS_PORT": "redis-port",
    "REDIS_PASSWORD": "redis-password",
}

# redis-py reads REDIS_<kwarg> through LiteLLM, so this turns on TLS for every
# Redis client LiteLLM creates.
REDIS_ENV_VARS: Dict[str, str] = {"REDIS_SSL": "true"}

REDIS_ROUTER_SETTINGS: Dict[str, str] = {
    "redis_host": "os.environ/REDIS_HOST",
    "redis_port": "os.environ/REDIS_PORT",
    "redis_password": "os.environ/REDIS_PASSWORD",
}


@dataclass
class RedisResources:
    """Resources and connection details created for Azure Managed Redis."""

    cluster: azure_native.redisenterprise.RedisEnterprise
    database: azure_native.redisenterprise.Database
    private_endpoint: azure_native.network.PrivateEndpoint
    # Last networking resource; it depends on the endpoint and the VNet link, so
    # once it exists the host name resolves privately inside the VNet.
    dns_zone_group: azure_native.network.PrivateDnsZoneGroup
    host_name: Output[str]
    primary_key: Output[str]


def create_redis(
    resource_group_name: Output[str],
    location: str,
    vnet_id: Output[str],
    private_endpoints_subnet_id: Output[str],
    config: LLMavenConfig,
    tags: Dict[str, str],
) -> RedisResources:
    """Create Azure Managed Redis, its database and a private endpoint.

    Public network access is disabled; the Container Apps environment reaches
    the cache through the private endpoint and a private DNS zone linked to
    the VNet.

    Args:
        resource_group_name: Name of the resource group
        location: Azure region
        vnet_id: Virtual network ID
        private_endpoints_subnet_id: Subnet that hosts the private endpoint
        config: LLMaven configuration
        tags: Resource tags

    Returns:
        RedisResources with the host name and primary access key
    """
    redis_config = config.redis
    environment = config.project.environment
    cluster_name = f"{config.project.name}-redis-{environment}"

    cluster = azure_native.redisenterprise.RedisEnterprise(
        f"redis-{environment}",
        resource_group_name=resource_group_name,
        cluster_name=cluster_name,
        location=location,
        sku=azure_native.redisenterprise.SkuArgs(name=redis_config.sku_name),
        high_availability="Enabled" if redis_config.high_availability else "Disabled",
        minimum_tls_version="1.2",
        public_network_access="Disabled",
        tags=tags,
    )

    database = azure_native.redisenterprise.Database(
        f"redis-db-{environment}",
        resource_group_name=resource_group_name,
        cluster_name=cluster.name,
        # Azure Managed Redis supports a single database, which must be "default".
        database_name="default",
        client_protocol="Encrypted",
        port=REDIS_PORT,
        clustering_policy=redis_config.clustering_policy,
        eviction_policy="VolatileLRU",
        # Phase 1 authenticates with an access key; Entra ID auth is a follow-up.
        access_keys_authentication="Enabled",
        opts=pulumi.ResourceOptions(
            # The clustering policy can't change without deleting the database,
            # so a config change must replace it rather than fail an update.
            replace_on_changes=["clusteringPolicy"],
        ),
    )

    private_dns_zone = azure_native.privatedns.PrivateZone(
        f"redis-private-dns-zone-{environment}",
        resource_group_name=resource_group_name,
        private_zone_name=REDIS_PRIVATE_DNS_ZONE,
        location="global",
        tags=tags,
    )

    vnet_link = azure_native.privatedns.VirtualNetworkLink(
        f"redis-dns-vnet-link-{environment}",
        resource_group_name=resource_group_name,
        private_zone_name=private_dns_zone.name,
        virtual_network_link_name=f"{cluster_name}-vnet-link",
        location="global",
        registration_enabled=False,
        virtual_network=azure_native.privatedns.SubResourceArgs(id=vnet_id),
        tags=tags,
    )

    private_endpoint = azure_native.network.PrivateEndpoint(
        f"redis-private-endpoint-{environment}",
        resource_group_name=resource_group_name,
        private_endpoint_name=f"{cluster_name}-pe",
        location=location,
        subnet=azure_native.network.SubnetArgs(id=private_endpoints_subnet_id),
        private_link_service_connections=[
            azure_native.network.PrivateLinkServiceConnectionArgs(
                name=f"{cluster_name}-plsc",
                private_link_service_id=cluster.id,
                group_ids=["redisEnterprise"],
            )
        ],
        tags=tags,
        opts=pulumi.ResourceOptions(depends_on=[database]),
    )

    dns_zone_group = azure_native.network.PrivateDnsZoneGroup(
        f"redis-private-dns-zone-group-{environment}",
        resource_group_name=resource_group_name,
        private_endpoint_name=private_endpoint.name,
        private_dns_zone_group_name="default",
        private_dns_zone_configs=[
            azure_native.network.PrivateDnsZoneConfigArgs(
                name="redis",
                private_dns_zone_id=private_dns_zone.id,
            )
        ],
        opts=pulumi.ResourceOptions(depends_on=[vnet_link, private_endpoint]),
    )

    keys = azure_native.redisenterprise.list_database_keys_output(
        resource_group_name=resource_group_name,
        cluster_name=cluster.name,
        database_name=database.name,
    )
    primary_key = Output.secret(keys.primary_key)

    pulumi.export(f"redis_host_name_{environment}", cluster.host_name)

    return RedisResources(
        cluster=cluster,
        database=database,
        private_endpoint=private_endpoint,
        dns_zone_group=dns_zone_group,
        host_name=cluster.host_name,
        primary_key=primary_key,
    )


def apply_redis_router_settings(
    config_text: str, clustering_policy: str = "EnterpriseCluster"
) -> str:
    """Point the LiteLLM router at Redis through ``REDIS_*`` env vars.

    The LiteLLM config file is shared across environments, so the Redis block
    is added at deploy time only where Redis exists. Other ``router_settings``
    and ``litellm_settings`` keys and the rest of the file (including comments)
    are kept.

    With ``EnterpriseCluster`` the data is sharded even though clients see one
    endpoint, so multi-key Lua scripts must keep their keys in one hash slot.
    LiteLLM's rate limiter only groups keys by slot for a cluster client or
    when ``litellm_settings.force_redis_hash_tag_grouping`` is true; without it
    the limiter's Redis scripts fail with CROSSSLOT and it silently falls back
    to per-replica counters.

    Args:
        config_text: LiteLLM config YAML
        clustering_policy: The Redis database clustering policy

    Returns:
        The config YAML with ``router_settings.redis_*`` set
    """
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    data = yaml.load(config_text)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError("LiteLLM config must be a YAML mapping")

    router_settings = data.get("router_settings")
    if router_settings is None:
        data["router_settings"] = dict(REDIS_ROUTER_SETTINGS)
    elif isinstance(router_settings, dict):
        router_settings.update(REDIS_ROUTER_SETTINGS)
    else:
        raise ValueError("LiteLLM config router_settings must be a mapping")

    if clustering_policy != "NoCluster":
        litellm_settings = data.get("litellm_settings")
        if litellm_settings is None:
            data["litellm_settings"] = {"force_redis_hash_tag_grouping": True}
        elif isinstance(litellm_settings, dict):
            litellm_settings["force_redis_hash_tag_grouping"] = True
        else:
            raise ValueError("LiteLLM config litellm_settings must be a mapping")

    out = io.StringIO()
    yaml.dump(data, out)
    return out.getvalue()
