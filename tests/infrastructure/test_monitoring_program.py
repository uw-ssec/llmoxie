"""Run the whole Pulumi program under mocks to check the monitoring wiring."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pulumi
import pytest
import yaml

from llmaven.infrastructure.config.schema import ALL_ALERTS
from llmaven.infrastructure.main import create_pulumi_program
from llmaven.infrastructure import resources as resources_pkg
from llmaven.infrastructure.resources import helpers, monitoring

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
        # A real resource, so the edge can list the apps in depends_on.
        app = pulumi.ComponentResource("test:index:App", kwargs["app_name"])
        app.id = pulumi.Output.from_input(f"{kwargs['app_name']}-id")
        app.configuration = pulumi.Output.from_input(
            SimpleNamespace(ingress=SimpleNamespace(fqdn="app.internal.test"))
        )
        return app

    monkeypatch.setattr(
        helpers, "create_container_app_with_key_vault_secrets", fake_create_app
    )

    # The backup job is stubbed for the same reason: the mock serializer cannot
    # round-trip its identity output. Only its Azure job name matters here.
    def fake_create_backup_job(**kwargs):
        config = kwargs["config"]
        job_name = f"{config.project.name}-backup-{config.project.environment}"
        return SimpleNamespace(
            id=pulumi.Output.from_input("backup-job-id"),
            name=pulumi.Output.from_input(job_name),
        )

    monkeypatch.setattr(resources_pkg, "create_backup_job", fake_create_backup_job)

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


def test_replica_restarts_uses_maximum_per_pod(tmp_path, monkeypatch):
    # RestartCount is cumulative per replica since it was created, so a Total
    # over the window latches once any replica has ever restarted. Maximum,
    # split per pod, means "a replica has restarted more than max_count times".
    resources, _, _ = _run(tmp_path, monkeypatch, ALL_ON)
    restart_alerts = [
        r
        for r in _by_type(resources, "azure-native:monitor:MetricAlert")
        if r.name.startswith("alert-replica-restarts-")
    ]
    assert {r.name for r in restart_alerts} == {
        "alert-replica-restarts-litellm",
        "alert-replica-restarts-mlflow",
    }
    for alert in restart_alerts:
        crit = alert.inputs["criteria"]["allOf"][0]
        assert crit["metricName"] == "RestartCount"
        assert crit["timeAggregation"] == "Maximum"
        assert crit["operator"] == "GreaterThan"
        assert crit["threshold"] == 3
        [dim] = crit["dimensions"]
        assert dim["name"] == monitoring.CONTAINER_APP_POD_DIMENSION == "podName"
        assert dim["operator"] == "Include"
        assert dim["values"] == ["*"]
        assert alert.inputs["windowSize"] == "PT30M"


@pytest.mark.parametrize(
    "minutes,expected",
    [(1, "PT1M"), (5, "PT5M"), (15, "PT15M"), (30, "PT30M")]
    + [(60, "PT1H"), (360, "PT6H"), (720, "PT12H"), (1440, "PT24H")],
)
def test_window_size_uses_hour_notation_above_an_hour(minutes, expected):
    assert monitoring._window_size(minutes) == expected


def test_long_window_gets_hourly_evaluation_frequency(tmp_path, monkeypatch):
    # Azure pairs evaluation frequency with window size; PT1H is the safe
    # pairing for windows of 6 hours and above.
    overrides = {
        "monitoring": {
            "enable_log_analytics": True,
            "alerts": {
                "email_receivers": ["ops@llmoxie.test"],
                "enabled_alerts": ["gateway_errors"],
                "gateway_errors": {"max_5xx_count": 10, "window_minutes": 720},
            },
        }
    }
    resources, _, _ = _run(tmp_path, monkeypatch, overrides)
    [alert] = _by_type(resources, "azure-native:monitor:MetricAlert")
    assert alert.inputs["windowSize"] == "PT12H"
    assert alert.inputs["evaluationFrequency"] == "PT1H"


def test_default_evaluation_frequency_is_five_minutes(tmp_path, monkeypatch):
    resources, _, _ = _run(tmp_path, monkeypatch, ALL_ON)
    alerts = {
        r.name: r.inputs
        for r in _by_type(resources, "azure-native:monitor:MetricAlert")
    }
    assert alerts["alert-gateway-errors"]["evaluationFrequency"] == "PT5M"


def test_one_minute_window_gets_one_minute_evaluation_frequency(tmp_path, monkeypatch):
    # Azure rejects a window shorter than the evaluation frequency.
    overrides = {
        "monitoring": {
            "enable_log_analytics": True,
            "alerts": {
                "email_receivers": ["ops@example.org"],
                "enabled_alerts": ["gateway_errors"],
                "gateway_errors": {"max_5xx_count": 10, "window_minutes": 1},
            },
        }
    }
    resources, _, _ = _run(tmp_path, monkeypatch, overrides)
    [alert] = [
        r
        for r in _by_type(resources, "azure-native:monitor:MetricAlert")
        if r.name == "alert-gateway-errors"
    ]
    assert alert.inputs["windowSize"] == "PT1M"
    assert alert.inputs["evaluationFrequency"] == "PT1M"


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


def _edge_config(**litellm):
    return {
        **ALL_ON,
        "edge": {
            "enabled": True,
            "custom_domains": [
                {"name": "ai.example.org", "certificate_name": "cert-0"},
                {"name": "mlflow.example.org", "certificate_name": "cert-1"},
            ],
        },
        "litellm": {"hostname": "ai.example.org"},
        "mlflow": {"hostname": "mlflow.example.org"},
    }


def test_replica_restart_alert_covers_edge(tmp_path, monkeypatch):
    resources, _, _ = _run(tmp_path, monkeypatch, _edge_config())
    names = {r.name for r in _by_type(resources, "azure-native:monitor:MetricAlert")}
    assert "alert-replica-restarts-edge" in names
    [alert] = [r for r in resources if r.name == "alert-replica-restarts-edge"]
    assert alert.inputs["criteria"]["allOf"][0]["metricName"] == "RestartCount"


def test_no_edge_means_no_edge_restart_alert_or_warning(tmp_path, monkeypatch):
    resources, _, warnings = _run(tmp_path, monkeypatch, ALL_ON)
    names = {r.name for r in _by_type(resources, "azure-native:monitor:MetricAlert")}
    assert "alert-replica-restarts-edge" not in names
    assert not any("edge" in w.lower() for w in warnings)


@pytest.fixture(autouse=True)
def _reset_pulumi_mocks():
    yield
    pulumi.runtime.settings.configure(pulumi.runtime.Settings(project="", stack=""))


FULL = {
    "monitoring": {
        "enable_log_analytics": True,
        "alerts": {
            "email_receivers": ["ops@example.org"],
            "enabled_alerts": list(ALL_ALERTS),
            "cloud_budget": {"monthly_usd": 300, "notify_at_percent": [50, 100]},
        },
    },
    "backup_job": {"enabled": True},
}


def test_backup_failure_rule_targets_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("LLMAVEN_SECRETS_BACKUP_STORAGE_CONNECTION_STRING", "x")
    resources, _, _ = _run(tmp_path, monkeypatch, FULL)
    [rule] = _by_type(resources, "azure-native:monitor:ScheduledQueryRule")
    assert rule.name == "alert-backup-job-failures"
    assert rule.inputs["scopes"] == ["log-analytics-id"]
    assert rule.inputs["actions"]["actionGroups"] == ["alerts-action-group-id"]


def test_backup_failure_rule_query_and_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("LLMAVEN_SECRETS_BACKUP_STORAGE_CONNECTION_STRING", "x")
    resources, _, _ = _run(tmp_path, monkeypatch, FULL)
    [rule] = _by_type(resources, "azure-native:monitor:ScheduledQueryRule")
    assert rule.inputs["kind"] == "LogAlert"
    assert rule.inputs["severity"] == 1
    assert rule.inputs["evaluationFrequency"] == "PT1H"
    # The window overlaps the frequency to tolerate ingestion delay, and the
    # stateful rule doesn't email again while the same alert stays fired.
    assert rule.inputs["windowSize"] == "PT2H"
    assert rule.inputs["autoMitigate"] is True
    [condition] = rule.inputs["criteria"]["allOf"]
    assert condition["timeAggregation"] == "Count"
    assert condition["operator"] == "GreaterThan"
    assert condition["threshold"] == 0
    # A fresh workspace has no ContainerAppSystemLogs_CL table yet, so Azure's
    # create-time query validation would reject the rule.
    assert rule.inputs["skipQueryValidation"] is True
    query = condition["query"]
    assert "ContainerAppSystemLogs_CL" in query
    assert 'JobName_s == "llmaven-backup-dev"' in query
    # Every run logs ContainerTerminated, including successful ones, so only
    # terminal failure events count, and a retry that completed cancels them.
    assert "ContainerTerminated" not in query
    assert 'Type_s == "Error"' not in query
    assert '"BackoffLimitExceeded", "DeadlineExceeded"' in query
    assert 'countif(Reason_s == "Completed")' in query
    assert "by ExecutionName_s" in query
    assert "Failed > 0 and Completed == 0" in query
    assert "{" not in query


def test_backup_disabled_skips_rule_with_warning(tmp_path, monkeypatch):
    cfg = {**FULL, "backup_job": {"enabled": False}}
    resources, _, warnings = _run(tmp_path, monkeypatch, cfg)
    assert not _by_type(resources, "azure-native:monitor:ScheduledQueryRule")
    assert any("backup_job_failures" in w for w in warnings)


def test_budget_notifies_action_group_and_ignores_time_period(tmp_path, monkeypatch):
    monkeypatch.setenv("LLMAVEN_SECRETS_BACKUP_STORAGE_CONNECTION_STRING", "x")
    resources, ignore, _ = _run(tmp_path, monkeypatch, FULL)
    [budget] = _by_type(resources, "azure-native:consumption:Budget")
    assert budget.inputs["amount"] == 300
    assert budget.inputs["timePeriod"]["startDate"].endswith("-01T00:00:00Z")
    notes = budget.inputs["notifications"]
    assert set(notes) == {"actual_50", "actual_100"}
    assert notes["actual_100"]["contactGroups"] == ["alerts-action-group-id"]
    # The action group is the single place receivers live; listing them in
    # contactEmails too would send every budget alert twice. The provider
    # requires the field, so it is present but empty.
    assert notes["actual_100"].get("contactEmails") == []
    assert budget.inputs["scope"] == (
        "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test"
    )
    assert "timePeriod" in ignore["budget-monthly"]


@pytest.mark.parametrize(
    "subscription_id,resource_group,missing",
    [
        ("", "rg-test", "azure.subscription_id"),
        ("00000000-0000-0000-0000-000000000000", "", "resource group"),
    ],
)
def test_budget_scope_requires_subscription_and_resource_group(
    subscription_id, resource_group, missing
):
    from llmaven.infrastructure.resources.monitoring import _cloud_budget, _Context
    from llmaven.infrastructure.config.schema import AlertsConfig

    ctx = _Context(
        alerts_config=AlertsConfig(
            email_receivers=["ops@llmoxie.test"], enabled_alerts=["cloud_budget"]
        ),
        resource_group_name=resource_group,
        action_group=None,
        litellm_app=None,
        mlflow_app=None,
        postgres_server=None,
        tags={},
        location="eastus",
        log_analytics_workspace=None,
        backup_job=None,
        subscription_id=subscription_id,
        project_name="llmaven",
        environment="dev",
    )
    with pytest.raises(ValueError, match=missing):
        _cloud_budget(ctx)
