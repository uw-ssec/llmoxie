"""Tests that deploys use azure.subscription_id, not the Azure CLI default (#205)."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from llmaven.deployment import deploy
from llmaven.deployment.deploy import DeploymentError

SUB = "11111111-1111-1111-1111-111111111111"
OTHER_SUB = "22222222-2222-2222-2222-222222222222"


def _config(state_store="pulumistatetest", resource_group="rg-test"):
    config = MagicMock()
    config.azure.subscription_id = SUB
    config.azure.resource_group = resource_group
    config.project.pulumi_state_store = state_store
    config.project.name = "llmaven"
    config.project.location = "westus2"
    return config


def _az_result(returncode=0, stdout="{}"):
    return subprocess.CompletedProcess(["az"], returncode, stdout=stdout, stderr="")


def _keys_aware_az(args, check=True, subscription_id=None):
    """Fake _run_az_command that returns a storage key for `keys list`."""
    if args[:3] == ["storage", "account", "keys"]:
        return _az_result(stdout=json.dumps([{"value": "secret-key"}]))
    return _az_result()


@pytest.fixture()
def clean_env(monkeypatch):
    for name in (
        "PULUMI_BACKEND_URL",
        "AZURE_STORAGE_ACCOUNT",
        "AZURE_STORAGE_KEY",
        "ARM_SUBSCRIPTION_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


class TestRunAzCommand:
    def test_appends_subscription(self):
        with patch.object(deploy.subprocess, "run") as run:
            deploy._run_az_command(["group", "show"], subscription_id=SUB)
        assert run.call_args.args[0] == ["az", "group", "show", "--subscription", SUB]

    def test_omits_subscription_when_not_given(self):
        with patch.object(deploy.subprocess, "run") as run:
            deploy._run_az_command(["group", "show"])
        assert run.call_args.args[0] == ["az", "group", "show"]


class TestGetStorageKey:
    def test_every_call_targets_the_subscription(self):
        with patch.object(
            deploy, "_run_az_command", side_effect=_keys_aware_az
        ) as run_az:
            key = deploy._get_storage_key("rg-test", "pulumistatetest", SUB)

        assert key == "secret-key"
        assert run_az.call_count == 2
        for call in run_az.call_args_list:
            assert call.kwargs["subscription_id"] == SUB


class TestInitializeAzureInfra:
    def test_new_backend_targets_the_subscription_without_account_set(self):
        config = _config(state_store=None, resource_group=None)
        with (
            patch.object(deploy, "load_config", return_value=config),
            patch.object(deploy, "update_config_fields"),
            patch.object(deploy, "_get_storage_key", return_value=None) as get_key,
            patch.object(
                deploy, "_run_az_command", side_effect=_keys_aware_az
            ) as run_az,
        ):
            deploy.initialize_azure_infra("llmaven-config.yaml")

        assert get_key.call_args.args[2] == SUB
        commands = [call.args[0][:2] for call in run_az.call_args_list]
        assert ["account", "set"] not in commands
        assert run_az.call_count == 4
        for call in run_az.call_args_list:
            assert call.kwargs["subscription_id"] == SUB


class TestDeleteResourceGroup:
    def test_targets_the_subscription(self):
        with (
            patch.object(deploy, "load_config", return_value=_config()),
            patch.object(deploy, "_run_az_command") as run_az,
        ):
            deploy.delete_resource_group("llmaven-config.yaml")

        assert run_az.call_args.kwargs["subscription_id"] == SUB


@pytest.fixture()
def patched_get_stack():
    with (
        patch.object(deploy, "create_pulumi_program"),
        patch.object(deploy, "load_config", return_value=_config()),
        patch.object(deploy.auto, "create_or_select_stack") as create_stack,
    ):
        yield create_stack


class TestGetStack:
    def test_reads_key_from_the_configured_subscription(
        self, clean_env, patched_get_stack
    ):
        with patch.object(
            deploy, "_get_storage_key", return_value="secret-key"
        ) as get_key:
            deploy.get_stack("llmaven-test", "llmaven", "llmaven-config.yaml")

        get_key.assert_called_once_with("rg-test", "pulumistatetest", SUB)
        assert deploy.os.environ["AZURE_STORAGE_KEY"] == "secret-key"

    def test_pins_provider_subscription_in_stack_config(
        self, clean_env, patched_get_stack
    ):
        clean_env.setenv("ARM_SUBSCRIPTION_ID", OTHER_SUB)
        with patch.object(deploy, "_get_storage_key", return_value="secret-key"):
            stack = deploy.get_stack("llmaven-test", "llmaven", "llmaven-config.yaml")

        stack.set_config.assert_called_once()
        key, value = stack.set_config.call_args.args
        assert key == "azure-native:subscriptionId"
        assert value.value == SUB
        assert not value.secret

    def test_missing_key_raises_clear_error(self, clean_env, patched_get_stack):
        with patch.object(deploy, "_get_storage_key", return_value=None):
            with pytest.raises(DeploymentError) as excinfo:
                deploy.get_stack("llmaven-test", "llmaven", "llmaven-config.yaml")

        message = str(excinfo.value)
        assert "pulumistatetest" in message
        assert "rg-test" in message
        assert SUB in message
        assert "NoneType" not in message
        patched_get_stack.assert_not_called()

    def test_existing_storage_key_is_not_looked_up(self, clean_env, patched_get_stack):
        clean_env.setenv("AZURE_STORAGE_KEY", "from-env")
        with patch.object(deploy, "_get_storage_key") as get_key:
            deploy.get_stack("llmaven-test", "llmaven", "llmaven-config.yaml")

        get_key.assert_not_called()
        assert deploy.os.environ["AZURE_STORAGE_KEY"] == "from-env"
