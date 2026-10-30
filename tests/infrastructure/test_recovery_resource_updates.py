"""Import tolerances must not suppress settings managed by the program."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pulumi

from llmaven.infrastructure.config.schema import LLMavenConfig
from llmaven.infrastructure.resources import container_apps, database


def test_postgres_settings_remain_managed_after_import():
    config = LLMavenConfig()
    with (
        patch.object(
            database.azure_native.privatedns,
            "PrivateZone",
            return_value=SimpleNamespace(name="zone", id="zone-id"),
        ),
        patch.object(
            database.azure_native.privatedns,
            "VirtualNetworkLink",
            return_value=Mock(spec=pulumi.Resource),
        ),
        patch.object(
            database.azure_native.dbforpostgresql,
            "Server",
            return_value=SimpleNamespace(
                name="db", fully_qualified_domain_name="db.example.test"
            ),
        ) as create_server,
        patch.object(database.pulumi, "export"),
    ):
        for size, ha, password in [(32, False, "old"), (64, True, "rotated")]:
            config.database.storage_size_gb = size
            config.database.high_availability = ha
            database.create_postgres_server(
                "rg", "eastus", "vnet", "subnet", config, password, {}
            )

    first, second = [call.kwargs for call in create_server.call_args_list]
    assert first["storage"].storage_size_gb == 32
    assert second["storage"].storage_size_gb == 64
    assert second["high_availability"].mode == "ZoneRedundant"
    assert second["administrator_login_password"] == "rotated"
    managed = {"storage", "highAvailability", "network", "administratorLoginPassword"}
    assert managed.isdisjoint(second["opts"].ignore_changes or [])
    assert second["opts"].depends_on


def test_environment_network_and_monitoring_remain_managed_after_import():
    config = LLMavenConfig()
    with (
        patch.object(
            container_apps.azure_native.app,
            "ManagedEnvironment",
            return_value=SimpleNamespace(
                name="env", id="env-id", default_domain="test"
            ),
        ) as create_environment,
        patch.object(
            container_apps.azure_native.operationalinsights,
            "get_shared_keys",
            return_value=SimpleNamespace(primary_shared_key="synthetic-key"),
        ),
        patch.object(container_apps.pulumi.Output, "all") as output_all,
        patch.object(container_apps.pulumi, "export"),
    ):
        output_all.return_value.apply.return_value = "synthetic-key"
        for suffix in ["old", "new"]:
            workspace = SimpleNamespace(name=f"logs-{suffix}", customer_id=suffix)
            container_apps.create_container_apps_environment(
                "rg", "eastus", f"subnet-{suffix}", workspace, config, {}
            )

    first, second = [call.kwargs for call in create_environment.call_args_list]
    assert first["vnet_configuration"].infrastructure_subnet_id == "subnet-old"
    assert second["vnet_configuration"].infrastructure_subnet_id == "subnet-new"
    assert (
        second["app_logs_configuration"].log_analytics_configuration.customer_id
        == "new"
    )
    managed = {"vnetConfiguration", "appLogsConfiguration", "zoneRedundant"}
    assert managed.isdisjoint(second["opts"].ignore_changes or [])


def test_backup_updates_remain_managed_and_preserve_caller_options():
    config = LLMavenConfig()
    caller_options = pulumi.ResourceOptions(protect=True, ignore_changes=["tags"])
    with (
        patch.object(
            container_apps.azure_native.app,
            "Job",
            return_value=SimpleNamespace(name="backup"),
        ) as create_job,
        patch.object(container_apps.pulumi, "export"),
    ):
        for hour, suffix in [(2, "old"), (3, "fixed")]:
            config.backup_job.schedule = f"0 {hour} * * *"
            config.backup_job.image = f"example.test/backup:{suffix}"
            container_apps.create_backup_job(
                "rg",
                "eastus",
                "env-id",
                None,
                {},
                f"synthetic-credential-{suffix}",
                config,
                {},
                managed_identity_id=f"identity-{suffix}",
                opts=caller_options,
            )

    first, second = [call.kwargs for call in create_job.call_args_list]
    assert first["configuration"].schedule_trigger_config.cron_expression == "0 2 * * *"
    assert (
        second["configuration"].schedule_trigger_config.cron_expression == "0 3 * * *"
    )
    assert second["template"].containers[0].image == "example.test/backup:fixed"
    assert second["configuration"].secrets[-1].value == "synthetic-credential-fixed"
    assert second["identity"].user_assigned_identities == ["identity-fixed"]
    managed = {"configuration", "template", "identity"}
    assert managed.isdisjoint(second["opts"].ignore_changes or [])
    assert second["opts"].protect is True
    assert "tags" in second["opts"].ignore_changes
