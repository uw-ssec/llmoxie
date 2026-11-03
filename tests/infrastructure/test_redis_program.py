"""Run the whole Pulumi program under mocks to check the Redis wiring (#211)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pulumi
import pytest
import yaml

from llmaven.infrastructure.main import create_pulumi_program
from llmaven.infrastructure.resources import helpers

REPO_ROOT = Path(__file__).resolve().parents[2]


class _Mocks(pulumi.runtime.Mocks):
    def __init__(self):
        self.resources: list[pulumi.runtime.MockResourceArgs] = []

    def new_resource(self, args: pulumi.runtime.MockResourceArgs):
        self.resources.append(args)
        # Only echo scalar inputs; nested input shapes differ from output types.
        outputs = {
            k: v for k, v in args.inputs.items() if isinstance(v, (str, int, bool))
        }
        if args.typ == "azure-native:storage:StorageAccount":
            outputs["primaryEndpoints"] = {"blob": "https://sa.blob.core.windows.net/"}
        if args.typ == "azure-native:redisenterprise:RedisEnterprise":
            outputs["hostName"] = "llmaven-redis-dev.eastus.redis.azure.net"
        if args.typ == "azure-native:keyvault:Vault":
            outputs["properties"] = {
                **outputs.get("properties", {}),
                "vaultUri": "https://kv.vault.azure.net/",
            }
        return f"{args.name}-id", outputs

    def call(self, args: pulumi.runtime.MockCallArgs):
        if args.token == "azure-native:redisenterprise:listDatabaseKeys":
            return {"primaryKey": "redis-key", "secondaryKey": "redis-key-2"}
        if args.token == "azure-native:storage:listStorageAccountKeys":
            return {"keys": [{"keyName": "key1", "value": "storage-key"}]}
        if args.token == "azure-native:authorization:getClientConfig":
            return {
                "clientId": "c",
                "objectId": "00000000-0000-0000-0000-000000000000",
                "subscriptionId": "s",
                "tenantId": "00000000-0000-0000-0000-000000000000",
            }
        return {}


def _run(tmp_path: Path, monkeypatch, max_replicas: int):
    config = {
        "project": {"name": "llmaven", "environment": "dev", "location": "eastus"},
        "azure": {
            "subscription_id": "00000000-0000-0000-0000-000000000000",
            "tenant_id": "00000000-0000-0000-0000-000000000000",
            "resource_group": "rg-test",
        },
        "monitoring": {"enable_log_analytics": False},
        "litellm": {
            "max_replicas": max_replicas,
            "config_file": str(REPO_ROOT / "docker" / "config.yaml"),
        },
    }
    config_path = tmp_path / "llmaven-config.yaml"
    config_path.write_text(yaml.safe_dump(config))
    monkeypatch.delenv("PULUMI_CONFIG_PASSPHRASE", raising=False)

    # Container apps are stubbed: their identity input trips the mock
    # serializer, and what matters here is what the program hands LiteLLM.
    apps = {}

    def fake_create_app(**kwargs):
        apps[kwargs["app_name"]] = kwargs
        return SimpleNamespace(configuration=pulumi.Output.from_input(None))

    monkeypatch.setattr(
        helpers, "create_container_app_with_key_vault_secrets", fake_create_app
    )

    # Record each resource's dependencies (explicit and through inputs) by name.
    graph: dict[str, set[str]] = {}
    register = pulumi.runtime.mocks.MockMonitor.RegisterResource

    def recording_register(monitor, request):
        urns = set(request.dependencies)
        for deps in request.propertyDependencies.values():
            urns.update(deps.urns)
        graph[request.name] = {urn.rsplit("::", 1)[-1] for urn in urns}
        return register(monitor, request)

    monkeypatch.setattr(
        pulumi.runtime.mocks.MockMonitor, "RegisterResource", recording_register
    )

    mocks = _Mocks()
    pulumi.runtime.set_mocks(mocks, project="llmaven", stack="dev", preview=False)
    program = create_pulumi_program(config_path)

    @pulumi.runtime.test
    def run():
        program()

    run()
    litellm = apps["llmaven-dev-litellm"]
    litellm["transitive_dependencies"] = _closure(
        graph, {r.pulumi_resource_name for r in litellm["opts"].depends_on}
    )
    return mocks.resources, litellm


def _closure(graph: dict[str, set[str]], names: set[str]) -> set[str]:
    seen: set[str] = set()
    pending = list(names)
    while pending:
        name = pending.pop()
        if name not in seen:
            seen.add(name)
            pending.extend(graph.get(name, ()))
    return seen


def _by_type(resources, typ):
    return [r for r in resources if r.typ == typ]


def _mounted_config(app) -> dict:
    return yaml.safe_load(app["inline_secrets"]["config-yaml"])


def test_multi_replica_program_provisions_private_redis_and_wires_litellm(
    tmp_path, monkeypatch
):
    resources, app = _run(tmp_path, monkeypatch, max_replicas=2)

    [cluster] = _by_type(resources, "azure-native:redisenterprise:RedisEnterprise")
    assert cluster.inputs["publicNetworkAccess"] == "Disabled"
    assert cluster.inputs["sku"]["name"] == "Balanced_B0"
    assert cluster.inputs["minimumTlsVersion"] == "1.2"

    [database] = _by_type(resources, "azure-native:redisenterprise:Database")
    assert database.inputs["clusteringPolicy"] == "EnterpriseCluster"
    assert database.inputs["port"] == 10000
    assert database.inputs["clientProtocol"] == "Encrypted"

    [endpoint] = _by_type(resources, "azure-native:network:PrivateEndpoint")
    [connection] = endpoint.inputs["privateLinkServiceConnections"]
    assert connection["groupIds"] == ["redisEnterprise"]

    zones = _by_type(resources, "azure-native:privatedns:PrivateZone")
    assert "privatelink.redis.azure.net" in {z.inputs["privateZoneName"] for z in zones}
    assert _by_type(resources, "azure-native:network:PrivateDnsZoneGroup")

    secrets = {
        r.inputs["secretName"]
        for r in _by_type(resources, "azure-native:keyvault:Secret")
    }
    assert {"redis-host", "redis-port", "redis-password"} <= secrets

    assert app["env_vars"]["REDIS_SSL"] == "true"
    # Credentials come from Key Vault secret refs, never plain env values.
    assert app["key_vault_secret_refs"]["REDIS_HOST"] == "redis-host"
    assert app["key_vault_secret_refs"]["REDIS_PORT"] == "redis-port"
    assert app["key_vault_secret_refs"]["REDIS_PASSWORD"] == "redis-password"
    assert not {"REDIS_HOST", "REDIS_PORT", "REDIS_PASSWORD"} & set(app["env_vars"])

    # LiteLLM's revision must wait until Redis resolves privately in the VNet.
    assert {
        "redis-dev",
        "redis-db-dev",
        "redis-private-endpoint-dev",
        "redis-dns-vnet-link-dev",
        "redis-private-dns-zone-dev",
        "redis-private-dns-zone-group-dev",
        "private-endpoints-subnet",
    } <= app["transitive_dependencies"]

    mounted = _mounted_config(app)
    assert mounted["router_settings"]["redis_host"] == "os.environ/REDIS_HOST"
    assert mounted["litellm_settings"]["force_redis_hash_tag_grouping"] is True


def test_single_replica_program_has_no_redis(tmp_path, monkeypatch):
    resources, app = _run(tmp_path, monkeypatch, max_replicas=1)

    assert not [
        r for r in resources if r.typ.startswith("azure-native:redisenterprise")
    ]
    assert not _by_type(resources, "azure-native:network:PrivateEndpoint")

    assert not [n for n in app["env_vars"] if n.startswith("REDIS_")]
    assert not [n for n in app["key_vault_secret_refs"] if n.startswith("REDIS_")]
    assert (
        app["inline_secrets"]["config-yaml"]
        == (REPO_ROOT / "docker" / "config.yaml").read_text()
    )


@pytest.fixture(autouse=True)
def _reset_pulumi_mocks():
    yield
    pulumi.runtime.settings.configure(pulumi.runtime.Settings(project="", stack=""))
