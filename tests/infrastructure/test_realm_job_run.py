"""Tests for running the Keycloak realm job after each deploy."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from llmaven.deployment import deploy
from llmaven.deployment.deploy import DeploymentError, run_realm_job

SUB = "00000000-0000-0000-0000-000000000000"


def _cfg(keycloak_enabled=True, realm="llmoxie"):
    config = MagicMock()
    config.project.name = "llmaven"
    config.project.environment = "test"
    config.project.enable_passphrase = False
    config.project.pulumi_state_store = "pulumistatetest"
    config.azure.resource_group = "rg-test"
    config.azure.subscription_id = SUB
    config.keycloak.enabled = keycloak_enabled
    config.keycloak.realm.name = realm
    return config


def _az(status_sequence, start_name="job-exec-1"):
    """A fake _run_az_command: start returns an execution, show walks statuses."""
    statuses = iter(status_sequence)
    calls = []

    def fake(args, check=True, subscription_id=None):
        calls.append((args, subscription_id))
        if args[:3] == ["containerapp", "job", "start"]:
            out = json.dumps({"name": start_name, "id": "/subscriptions/x"})
        else:
            out = json.dumps({"properties": {"status": next(statuses)}})
        return subprocess.CompletedProcess(args, 0, stdout=out, stderr="")

    return fake, calls


class TestRunRealmJob:
    def test_realm_job_runs_and_waits(self):
        fake, calls = _az(["Running", "Succeeded"])
        with (
            patch.object(deploy, "_run_az_command", side_effect=fake),
            patch.object(deploy.time, "sleep"),
        ):
            run_realm_job(_cfg(), "realm-job")

        start, show1, show2 = calls
        assert start[0][:3] == ["containerapp", "job", "start"]
        assert start[0][start[0].index("--name") + 1] == "realm-job"
        assert start[0][start[0].index("--resource-group") + 1] == "rg-test"
        assert show1[0][:4] == ["containerapp", "job", "execution", "show"]
        assert show1[0][show1[0].index("--job-execution-name") + 1] == "job-exec-1"
        assert show1[0][show1[0].index("--name") + 1] == "realm-job"
        assert len(calls) == 3
        assert {c[1] for c in calls} == {SUB}

    def test_realm_job_failure_fails_the_deploy(self):
        fake, _ = _az(["Failed"])
        with (
            patch.object(deploy, "_run_az_command", side_effect=fake),
            patch.object(deploy.time, "sleep"),
            pytest.raises(DeploymentError) as exc,
        ):
            run_realm_job(_cfg(), "realm-job")
        msg = str(exc.value)
        assert "realm-job" in msg
        assert "job-exec-1" in msg
        assert "az containerapp job logs show" in msg

    def test_realm_job_stopped_is_a_failure(self):
        fake, _ = _az(["Stopped"])
        with (
            patch.object(deploy, "_run_az_command", side_effect=fake),
            patch.object(deploy.time, "sleep"),
            pytest.raises(DeploymentError, match="Stopped"),
        ):
            run_realm_job(_cfg(), "realm-job")

    def test_realm_job_timeout(self):
        fake, _ = _az(["Running"] * 100)
        with (
            patch.object(deploy, "_run_az_command", side_effect=fake),
            patch.object(deploy.time, "sleep"),
            pytest.raises(DeploymentError, match="did not finish"),
        ):
            run_realm_job(_cfg(), "realm-job", timeout_s=30, poll_s=10)

    def test_start_without_execution_name_fails(self):
        def fake(args, check=True, subscription_id=None):
            return subprocess.CompletedProcess(args, 0, stdout="{}", stderr="")

        with (
            patch.object(deploy, "_run_az_command", side_effect=fake),
            pytest.raises(DeploymentError, match="execution name"),
        ):
            run_realm_job(_cfg(), "realm-job")

    def test_progress_is_printed_at_most_every_30_seconds(self, capsys):
        fake, _ = _az(["Running"] * 6 + ["Succeeded"])
        with (
            patch.object(deploy, "_run_az_command", side_effect=fake),
            patch.object(deploy.time, "sleep"),
        ):
            run_realm_job(_cfg(), "realm-job", poll_s=10)
        out = capsys.readouterr().out
        assert out.count("Running") <= 3


def _stack(outputs=None, up_outputs=None):
    stack = MagicMock()
    stack.outputs.return_value = outputs or {}
    stack.preview.return_value = MagicMock(change_summary={"same": 3})
    up_outputs = {"keycloak_realm_job": MagicMock(value="realm-job")} | (
        up_outputs or {}
    )
    stack.up.return_value = MagicMock(outputs=up_outputs)
    return stack


@pytest.fixture()
def patched_deploy():
    with (
        patch.object(deploy, "validate_config"),
        patch.object(deploy, "initialize_azure_infra"),
        patch.object(deploy, "load_config") as load_config,
        patch.object(deploy, "get_stack") as get_stack,
        patch.object(deploy, "run_realm_job") as run_job,
    ):
        yield load_config, get_stack, run_job


class TestDeployRunsRealmJob:
    def test_runs_after_up_with_exported_job_name(self, patched_deploy):
        load_config, get_stack, run_job = patched_deploy
        config = _cfg()
        load_config.return_value = config
        stack = _stack()
        get_stack.return_value = stack

        deploy.deploy_infrastructure(Path("c.yaml"), auto_approve=True)

        run_job.assert_called_once_with(config, "realm-job")

    def test_runs_even_when_expect_no_changes(self, patched_deploy):
        load_config, get_stack, run_job = patched_deploy
        config = _cfg()
        load_config.return_value = config
        get_stack.return_value = _stack()

        deploy.deploy_infrastructure(
            Path("c.yaml"), auto_approve=True, expect_no_changes=True
        )

        run_job.assert_called_once_with(config, "realm-job")

    def test_not_run_when_keycloak_off(self, patched_deploy):
        load_config, get_stack, run_job = patched_deploy
        load_config.return_value = _cfg(keycloak_enabled=False)
        stack = _stack()
        get_stack.return_value = stack

        deploy.deploy_infrastructure(Path("c.yaml"), auto_approve=True)

        run_job.assert_not_called()
        stack.outputs.assert_not_called()

    def test_not_run_on_preview(self, patched_deploy):
        load_config, get_stack, run_job = patched_deploy
        load_config.return_value = _cfg()
        get_stack.return_value = _stack()

        deploy.deploy_infrastructure(Path("c.yaml"), preview=True)

        run_job.assert_not_called()

    def test_not_run_when_up_fails(self, patched_deploy):
        load_config, get_stack, run_job = patched_deploy
        load_config.return_value = _cfg()
        stack = _stack()
        stack.up.side_effect = RuntimeError("boom")
        get_stack.return_value = stack

        with pytest.raises(DeploymentError):
            deploy.deploy_infrastructure(Path("c.yaml"), auto_approve=True)

        run_job.assert_not_called()

    def test_missing_job_output_fails(self, patched_deploy):
        load_config, get_stack, run_job = patched_deploy
        load_config.return_value = _cfg()
        stack = _stack()
        stack.up.return_value = MagicMock(outputs={})
        get_stack.return_value = stack

        with pytest.raises(DeploymentError, match="keycloak_realm_job"):
            deploy.deploy_infrastructure(Path("c.yaml"), auto_approve=True)

        run_job.assert_not_called()

    def test_realm_name_change_is_refused(self, patched_deploy):
        load_config, get_stack, run_job = patched_deploy
        load_config.return_value = _cfg(realm="newrealm")
        stack = _stack(outputs={"keycloak_realm": MagicMock(value="oldrealm")})
        get_stack.return_value = stack

        with pytest.raises(DeploymentError) as exc:
            deploy.deploy_infrastructure(Path("c.yaml"), auto_approve=True)

        msg = str(exc.value)
        assert "oldrealm" in msg and "newrealm" in msg
        assert "issuer" in msg
        stack.up.assert_not_called()

    def test_new_stack_without_realm_output_is_not_refused(self, patched_deploy):
        load_config, get_stack, run_job = patched_deploy
        load_config.return_value = _cfg(realm="newrealm")
        get_stack.return_value = _stack(outputs={})

        deploy.deploy_infrastructure(Path("c.yaml"), auto_approve=True)

        run_job.assert_called_once()
