"""Tests that an expired Azure CLI login is reported, not hidden (#203)."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from llmaven.deployment import deploy, validate
from llmaven.deployment.deploy import DeploymentError

SUB = "11111111-1111-1111-1111-111111111111"
EXPIRED = (
    "ERROR: AADSTS700082: The refresh token has expired due to inactivity.\n"
    "Interactive authentication is needed. Please run:\naz login"
)
STORAGE_NOT_FOUND = (
    "ERROR: (ResourceNotFound) The Resource "
    "'Microsoft.Storage/storageAccounts/pulumistatetest' under resource group "
    "'rg-test' was not found."
)
RG_NOT_FOUND = (
    "ERROR: (ResourceGroupNotFound) Resource group 'rg-test' could not be found."
)


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(["az"], returncode, stdout=stdout, stderr=stderr)


def _fake_az(show_stderr=None, keys_error=None):
    """Fake deploy._run_az_command for `storage account show` / `keys list`."""

    def run(args, check=True, subscription_id=None):
        if args[:3] == ["storage", "account", "show"]:
            if show_stderr is not None:
                return _completed(returncode=1, stderr=show_stderr)
            return _completed(stdout="{}")
        if args[:3] == ["storage", "account", "keys"]:
            if keys_error is not None:
                raise DeploymentError(f"Azure CLI command failed: {keys_error}")
            return _completed(stdout=json.dumps([{"value": "secret-key"}]))
        raise AssertionError(f"unexpected az call: {args}")

    return run


class TestGetStorageKey:
    def test_expired_login_raises_with_az_error(self):
        with patch.object(deploy, "_run_az_command", side_effect=_fake_az(EXPIRED)):
            with pytest.raises(DeploymentError) as excinfo:
                deploy._get_storage_key("rg-test", "pulumistatetest", SUB)

        message = str(excinfo.value)
        assert "pulumistatetest" in message
        assert "AADSTS700082" in message

    @pytest.mark.parametrize("stderr", [STORAGE_NOT_FOUND, RG_NOT_FOUND])
    def test_not_found_returns_none(self, stderr):
        with patch.object(deploy, "_run_az_command", side_effect=_fake_az(stderr)):
            assert deploy._get_storage_key("rg-test", "pulumistatetest", SUB) is None

    def test_failed_key_list_raises_with_account_name(self):
        with patch.object(
            deploy, "_run_az_command", side_effect=_fake_az(keys_error=EXPIRED)
        ):
            with pytest.raises(DeploymentError) as excinfo:
                deploy._get_storage_key("rg-test", "pulumistatetest", SUB)

        message = str(excinfo.value)
        assert "pulumistatetest" in message
        assert "AADSTS700082" in message


class TestGetStackExpiredLogin:
    def test_reports_az_error_instead_of_nonetype(self, monkeypatch):
        for name in ("PULUMI_BACKEND_URL", "AZURE_STORAGE_ACCOUNT", "AZURE_STORAGE_KEY"):
            monkeypatch.delenv(name, raising=False)
        config = MagicMock()
        config.azure.subscription_id = SUB
        config.azure.resource_group = "rg-test"
        config.project.pulumi_state_store = "pulumistatetest"
        with (
            patch.object(deploy, "create_pulumi_program"),
            patch.object(deploy, "load_config", return_value=config),
            patch.object(deploy.auto, "create_or_select_stack") as create_stack,
            patch.object(deploy, "_run_az_command", side_effect=_fake_az(EXPIRED)),
        ):
            with pytest.raises(DeploymentError) as excinfo:
                deploy.get_stack("llmaven-test", "llmaven", "llmaven-config.yaml")

        message = str(excinfo.value)
        assert "pulumistatetest" in message
        assert "AADSTS700082" in message
        assert "NoneType" not in message
        create_stack.assert_not_called()


class TestCheckSubscriptionAccess:
    def test_probes_a_token_for_the_configured_subscription(self):
        with patch.object(
            validate.subprocess, "run", return_value=_completed(stdout="2026-11-02")
        ) as run:
            success, _ = validate.check_subscription_access(SUB)

        assert success
        args = run.call_args.args[0]
        assert args[:3] == ["az", "account", "get-access-token"]
        assert args[args.index("--subscription") + 1] == SUB

    def test_expired_login_fails_with_az_login_hint(self):
        with patch.object(
            validate.subprocess,
            "run",
            return_value=_completed(returncode=1, stderr=EXPIRED),
        ):
            success, message = validate.check_subscription_access(SUB)

        assert not success
        assert "AADSTS700082" in message
        assert "az login" in message


class TestCheckAzureCli:
    def test_does_not_probe_the_default_subscription_token(self):
        # A token probe here would test the CLI default subscription, which may
        # be expired while the configured subscription is fine.
        with patch.object(validate.subprocess, "run", return_value=_completed()) as run:
            success, _ = validate.check_azure_cli()

        assert success
        commands = [call.args[0] for call in run.call_args_list]
        assert ["az", "--version"] in commands
        assert ["az", "account", "show"] in commands
        assert not any("get-access-token" in command for command in commands)


class TestInitializeAzureInfraExpiredLogin:
    def test_auth_failure_aborts_before_creating_resources(self):
        config = MagicMock()
        config.azure.subscription_id = SUB
        config.project.pulumi_state_store = None
        config.project.name = "llmaven"
        config.project.location = "westus2"
        with (
            patch.object(deploy, "load_config", return_value=config),
            patch.object(deploy, "update_config_fields") as update_config,
            patch.object(
                deploy, "_run_az_command", side_effect=_fake_az(EXPIRED)
            ) as run_az,
        ):
            with pytest.raises(DeploymentError) as excinfo:
                deploy.initialize_azure_infra("llmaven-config.yaml")

        assert "AADSTS700082" in str(excinfo.value)
        commands = [call.args[0][:3] for call in run_az.call_args_list]
        assert commands == [["storage", "account", "show"]]
        update_config.assert_not_called()


class TestExpiredDefaultSubscription:
    def test_valid_configured_subscription_passes(self):
        """The CLI default's session is expired; the configured one is fine."""

        def run(args, **kwargs):
            if "get-access-token" in args and SUB not in args:
                return _completed(returncode=1, stderr=EXPIRED)
            return _completed(stdout="2026-11-02")

        with patch.object(validate.subprocess, "run", side_effect=run):
            assert validate.check_azure_cli()[0]
            assert validate.check_subscription_access(SUB)[0]
