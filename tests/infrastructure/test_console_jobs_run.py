"""Tests for running the console jobs after the realm job on each deploy."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from llmaven.deployment import deploy
from llmaven.deployment.deploy import DeploymentError, run_job

SUB = "00000000-0000-0000-0000-000000000000"


def _cfg(console_enabled=True, hub_enabled=False):
    config = MagicMock()
    config.project.name = "llmaven"
    config.project.environment = "test"
    config.project.enable_passphrase = False
    config.project.pulumi_state_store = "pulumistatetest"
    config.azure.resource_group = "rg-test"
    config.azure.subscription_id = SUB
    config.keycloak.enabled = True
    config.keycloak.realm.name = "llmoxie"
    config.console.enabled = console_enabled
    config.knowledge_hub.enabled = hub_enabled
    return config


def _az(statuses):
    statuses = iter(statuses)
    calls = []

    def fake(args, check=True, subscription_id=None):
        calls.append(args)
        if args[:3] == ["containerapp", "job", "start"]:
            out = json.dumps({"name": "exec-1"})
        else:
            out = json.dumps({"properties": {"status": next(statuses)}})
        return subprocess.CompletedProcess(args, 0, stdout=out, stderr="")

    return fake, calls


class TestRunJob:
    def test_purpose_is_printed_and_confirmed(self, capsys):
        fake, _ = _az(["Succeeded"])
        with patch.object(deploy, "_run_az_command", side_effect=fake):
            run_job(
                _cfg(),
                "db-job",
                "Setting up the console database",
                container="console-db",
            )
        out = capsys.readouterr().out
        assert "Setting up the console database (job db-job, execution exec-1)" in out
        assert "✓ Setting up the console database" in out

    def test_failure_names_the_purpose_and_hints_with_its_container(self):
        fake, _ = _az(["Failed"])
        with (
            patch.object(deploy, "_run_az_command", side_effect=fake),
            pytest.raises(DeploymentError) as exc,
        ):
            run_job(
                _cfg(),
                "db-job",
                "Setting up the console database",
                container="console-db",
            )
        msg = str(exc.value)
        assert "Setting up the console database" in msg
        assert "db-job" in msg and "exec-1" in msg
        assert (
            "az containerapp job logs show --name db-job --resource-group rg-test "
            f"--execution exec-1 --container console-db --subscription {SUB}"
        ) in msg


def _stack(up_outputs=None):
    stack = MagicMock()
    stack.outputs.return_value = {}
    stack.preview.return_value = MagicMock(change_summary={"same": 3})
    outputs = {
        "keycloak_realm_job": MagicMock(value="realm-job"),
        "console_db_job": MagicMock(value="db-job"),
        "console_init_job": MagicMock(value="init-job"),
    }
    stack.up.return_value = MagicMock(outputs=up_outputs or outputs)
    return stack


@pytest.fixture()
def patched_deploy():
    order = MagicMock()
    with (
        patch.object(deploy, "validate_config"),
        patch.object(deploy, "initialize_azure_infra"),
        patch.object(deploy, "load_config") as load_config,
        patch.object(deploy, "get_stack") as get_stack,
        patch.object(deploy, "run_realm_job", order.realm),
        patch.object(deploy, "run_job", order.job),
    ):
        yield load_config, get_stack, order


class TestDeployRunsConsoleJobs:
    def test_order_is_realm_then_db_then_init(self, patched_deploy):
        load_config, get_stack, order = patched_deploy
        config = _cfg()
        load_config.return_value = config
        get_stack.return_value = _stack()

        deploy.deploy_infrastructure(Path("c.yaml"), auto_approve=True)

        names = [c[0] for c in order.mock_calls]
        assert names == ["realm", "job", "job"]
        db, init = order.job.call_args_list
        assert db.args[:2] == (config, "db-job")
        assert "console database" in db.args[2]
        assert db.kwargs["container"] == "console-db"
        assert init.args[:2] == (config, "init-job")
        assert "LiteLLM key" in init.args[2]
        assert init.kwargs["container"] == "console-init"
        assert order.realm.call_args == call(config, "realm-job")

    def test_console_off_runs_only_the_realm_job(self, patched_deploy):
        load_config, get_stack, order = patched_deploy
        load_config.return_value = _cfg(console_enabled=False)
        get_stack.return_value = _stack()

        deploy.deploy_infrastructure(Path("c.yaml"), auto_approve=True)

        order.realm.assert_called_once()
        order.job.assert_not_called()

    def test_db_failure_stops_before_init_and_names_the_database(self, patched_deploy):
        load_config, get_stack, order = patched_deploy
        load_config.return_value = _cfg()
        get_stack.return_value = _stack()
        order.job.side_effect = DeploymentError("db blew up")

        with pytest.raises(
            DeploymentError,
            match="Infrastructure deployed, but setting up the console database "
            "did not finish: db blew up",
        ):
            deploy.deploy_infrastructure(Path("c.yaml"), auto_approve=True)

        assert order.job.call_count == 1

    def test_init_failure_names_the_broker_key(self, patched_deploy):
        load_config, get_stack, order = patched_deploy
        load_config.return_value = _cfg()
        get_stack.return_value = _stack()
        order.job.side_effect = [None, DeploymentError("init blew up")]

        with pytest.raises(
            DeploymentError,
            match="Infrastructure deployed, but creating the broker's LiteLLM key "
            "did not finish: init blew up",
        ):
            deploy.deploy_infrastructure(Path("c.yaml"), auto_approve=True)

    def test_realm_failure_skips_the_console_jobs(self, patched_deploy):
        load_config, get_stack, order = patched_deploy
        load_config.return_value = _cfg()
        get_stack.return_value = _stack()
        order.realm.side_effect = DeploymentError("realm blew up")

        with pytest.raises(
            DeploymentError,
            match="Keycloak realm was not applied: realm blew up. The console "
            "database and key jobs did not run",
        ):
            deploy.deploy_infrastructure(Path("c.yaml"), auto_approve=True)

        order.job.assert_not_called()

    @pytest.mark.parametrize("missing", ["console_db_job", "console_init_job"])
    def test_missing_export_is_an_error(self, patched_deploy, missing):
        load_config, get_stack, order = patched_deploy
        load_config.return_value = _cfg()
        outputs = {
            "keycloak_realm_job": MagicMock(value="realm-job"),
            "console_db_job": MagicMock(value="db-job"),
            "console_init_job": MagicMock(value="init-job"),
        }
        del outputs[missing]
        get_stack.return_value = _stack(outputs)

        with pytest.raises(DeploymentError, match=missing):
            deploy.deploy_infrastructure(Path("c.yaml"), auto_approve=True)


KNOW_OUTPUTS = {
    "keycloak_realm_job": MagicMock(value="realm-job"),
    "console_db_job": MagicMock(value="db-job"),
    "console_init_job": MagicMock(value="init-job"),
    "console_knowledge_job": MagicMock(value="know-job"),
}


class TestDeployRunsTheKnowledgeJob:
    def test_with_the_hub_it_runs_third(self, patched_deploy):
        load_config, get_stack, order = patched_deploy
        config = _cfg(hub_enabled=True)
        load_config.return_value = config
        get_stack.return_value = _stack(dict(KNOW_OUTPUTS))

        deploy.deploy_infrastructure(Path("c.yaml"), auto_approve=True)

        names = [c[0] for c in order.mock_calls]
        assert names == ["realm", "job", "job", "job"]
        db, init, know = order.job.call_args_list
        assert db.kwargs["container"] == "console-db"
        assert init.kwargs["container"] == "console-init"
        assert know.args == (
            config,
            "know-job",
            "Setting up knowledge for existing organizations",
        )
        assert know.kwargs["container"] == "console-know"

    def test_without_the_hub_it_is_not_expected(self, patched_deploy):
        load_config, get_stack, order = patched_deploy
        load_config.return_value = _cfg(hub_enabled=False)
        get_stack.return_value = _stack(dict(KNOW_OUTPUTS))

        deploy.deploy_infrastructure(Path("c.yaml"), auto_approve=True)

        containers = [c.kwargs["container"] for c in order.job.call_args_list]
        assert containers == ["console-db", "console-init"]

    def test_failure_names_the_backfill(self, patched_deploy):
        load_config, get_stack, order = patched_deploy
        load_config.return_value = _cfg(hub_enabled=True)
        get_stack.return_value = _stack(dict(KNOW_OUTPUTS))
        order.job.side_effect = [None, None, DeploymentError("know blew up")]

        with pytest.raises(
            DeploymentError,
            match="Infrastructure deployed, but setting up knowledge for existing "
            "organizations did not finish: know blew up",
        ):
            deploy.deploy_infrastructure(Path("c.yaml"), auto_approve=True)

    def test_with_the_hub_a_missing_export_is_an_error(self, patched_deploy):
        load_config, get_stack, order = patched_deploy
        load_config.return_value = _cfg(hub_enabled=True)
        outputs = dict(KNOW_OUTPUTS)
        del outputs["console_knowledge_job"]
        get_stack.return_value = _stack(outputs)

        with pytest.raises(DeploymentError, match="console_knowledge_job"):
            deploy.deploy_infrastructure(Path("c.yaml"), auto_approve=True)
        assert order.job.call_count == 2
