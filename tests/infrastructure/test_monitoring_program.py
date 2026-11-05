"""Run the whole Pulumi program under mocks to check the monitoring wiring."""

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


def _run(
    tmp_path: Path, monkeypatch, config_overrides: dict
) -> tuple[list[pulumi.runtime.MockResourceArgs], dict[str, list[str]], list[str]]:
    """Run the program and return (resources, ignoreChanges by name, warnings)."""
    config = {
        "project": {"name": "llmaven", "environment": "dev", "location": "eastus"},
        "azure": {
            "subscription_id": "00000000-0000-0000-0000-000000000000",
            "tenant_id": "00000000-0000-0000-0000-000000000000",
            "resource_group": "rg-test",
        },
        "monitoring": {"enable_log_analytics": True},
        "litellm": {
            "config_file": str(REPO_ROOT / "docker" / "config.yaml"),
        },
    }
    for section, values in config_overrides.items():
        if isinstance(values, dict) and isinstance(config.get(section), dict):
            config[section] = {**config[section], **values}
        else:
            config[section] = values
    config_path = tmp_path / "llmaven-config.yaml"
    config_path.write_text(yaml.safe_dump(config))
    monkeypatch.delenv("PULUMI_CONFIG_PASSPHRASE", raising=False)

    # Container apps are stubbed: their identity input trips the mock
    # serializer, and what matters here is the surrounding program.
    def fake_create_app(**kwargs):
        return SimpleNamespace(
            id=pulumi.Output.from_input(f"{kwargs['app_name']}-id"),
            configuration=pulumi.Output.from_input(None),
        )

    monkeypatch.setattr(
        helpers, "create_container_app_with_key_vault_secrets", fake_create_app
    )

    # Record each resource's ignoreChanges by name.
    ignore_changes: dict[str, list[str]] = {}
    register = pulumi.runtime.mocks.MockMonitor.RegisterResource

    def recording_register(monitor, request):
        ignore_changes[request.name] = list(request.ignoreChanges)
        return register(monitor, request)

    monkeypatch.setattr(
        pulumi.runtime.mocks.MockMonitor, "RegisterResource", recording_register
    )

    warnings: list[str] = []
    monkeypatch.setattr(pulumi.log, "warn", lambda msg, *a, **k: warnings.append(msg))

    mocks = _Mocks()
    pulumi.runtime.set_mocks(mocks, project="llmaven", stack="dev", preview=False)
    program = create_pulumi_program(config_path)

    @pulumi.runtime.test
    def run():
        program()

    run()
    return mocks.resources, ignore_changes, warnings


def _by_type(resources, typ):
    return [r for r in resources if r.typ == typ]


def test_data_cap_is_applied_to_workspace(tmp_path, monkeypatch):
    resources, _, _ = _run(
        tmp_path, monkeypatch, {"monitoring": {"daily_data_cap_gb": 1.0}}
    )
    [ws] = _by_type(resources, "azure-native:operationalinsights:Workspace")
    assert ws.inputs["workspaceCapping"]["dailyQuotaGb"] == 1.0


def test_null_data_cap_leaves_capping_unset(tmp_path, monkeypatch):
    resources, _, _ = _run(
        tmp_path, monkeypatch, {"monitoring": {"daily_data_cap_gb": None}}
    )
    [ws] = _by_type(resources, "azure-native:operationalinsights:Workspace")
    assert "workspaceCapping" not in ws.inputs


def test_no_alerts_block_creates_no_monitoring_resources(tmp_path, monkeypatch):
    resources, _, _ = _run(tmp_path, monkeypatch, {})
    assert not [
        r
        for r in resources
        if r.typ.startswith(("azure-native:monitor:", "azure-native:consumption:"))
    ]


ALL_ON = {
    "monitoring": {
        "enable_log_analytics": True,
        "alerts": {
            "email_receivers": ["ops@example.org", "dev@example.org"],
            "enabled_alerts": [
                "gateway_errors",
                "gateway_latency",
                "replica_restarts",
                "db_storage",
                "db_cpu",
            ],
        },
    }
}


def test_action_group_emails_everyone_with_common_schema(tmp_path, monkeypatch):
    resources, _, _ = _run(tmp_path, monkeypatch, ALL_ON)
    [ag] = _by_type(resources, "azure-native:monitor:ActionGroup")
    assert ag.name == "alerts-action-group"
    assert [r["emailAddress"] for r in ag.inputs["emailReceivers"]] == [
        "ops@example.org",
        "dev@example.org",
    ]
    assert all(r["useCommonAlertSchema"] for r in ag.inputs["emailReceivers"])


def test_metric_alerts_target_metric_and_threshold(tmp_path, monkeypatch):
    resources, _, _ = _run(tmp_path, monkeypatch, ALL_ON)
    alerts = {
        r.name: r.inputs
        for r in _by_type(resources, "azure-native:monitor:MetricAlert")
    }
    assert set(alerts) == {
        "alert-gateway-errors",
        "alert-gateway-latency",
        "alert-replica-restarts-litellm",
        "alert-replica-restarts-mlflow",
        "alert-db-storage",
        "alert-db-cpu",
    }
    crit = alerts["alert-gateway-errors"]["criteria"]["allOf"][0]
    assert (crit["metricName"], crit["threshold"], crit["timeAggregation"]) == (
        "Requests",
        10,
        "Total",
    )
    assert crit["dimensions"][0]["values"] == ["5xx"]
    assert alerts["alert-gateway-errors"]["windowSize"] == "PT15M"
    assert alerts["alert-gateway-errors"]["scopes"] == ["llmaven-dev-litellm-id"]
    assert alerts["alert-db-cpu"]["criteria"]["allOf"][0]["threshold"] == 85
    assert alerts["alert-db-storage"]["scopes"] == ["postgres-server-dev-id"]
    for a in alerts.values():
        assert a["actions"][0]["actionGroupId"] == "alerts-action-group-id"


def test_mlflow_disabled_skips_only_mlflow_restart_alert(tmp_path, monkeypatch):
    resources, _, warnings = _run(
        tmp_path, monkeypatch, {**ALL_ON, "mlflow": {"enabled": False}}
    )
    names = {r.name for r in _by_type(resources, "azure-native:monitor:MetricAlert")}
    assert "alert-replica-restarts-litellm" in names
    assert "alert-replica-restarts-mlflow" not in names
    assert any("mlflow" in w.lower() for w in warnings)


def test_litellm_disabled_skips_gateway_alerts_without_crashing(tmp_path, monkeypatch):
    resources, _, warnings = _run(
        tmp_path, monkeypatch, {**ALL_ON, "litellm": {"enabled": False}}
    )
    names = {r.name for r in _by_type(resources, "azure-native:monitor:MetricAlert")}
    assert (
        not {
            "alert-gateway-errors",
            "alert-gateway-latency",
            "alert-replica-restarts-litellm",
        }
        & names
    )
    assert {"alert-db-storage", "alert-db-cpu"} <= names
    assert any("litellm" in w.lower() for w in warnings)


@pytest.fixture(autouse=True)
def _reset_pulumi_mocks():
    yield
    pulumi.runtime.settings.configure(pulumi.runtime.Settings(project="", stack=""))
