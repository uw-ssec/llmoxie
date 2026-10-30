"""Tests for `llmaven infra deploy --expect-no-changes`.

stack.up() runs with --skip-preview, so Pulumi's own expect_no_changes only
errors after changes are applied. The deploy must preview first and refuse to
call up() when the preview plans any change.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from llmaven.cli import app
from llmaven.deployment import deploy
from llmaven.deployment.deploy import DeploymentError, _raise_if_changes


def _config(resource_group="rg-test", state_store="pulumistatetest"):
    config = MagicMock()
    config.project.name = "llmaven"
    config.project.environment = "test"
    config.project.enable_passphrase = False
    config.project.pulumi_state_store = state_store
    config.azure.resource_group = resource_group
    return config


def _stack(change_summary):
    stack = MagicMock()
    stack.preview.return_value = MagicMock(change_summary=change_summary)
    stack.up.return_value = MagicMock(outputs={})
    return stack


@pytest.fixture()
def patched_deploy():
    """Patch everything around the Pulumi stack in deploy_infrastructure."""
    with (
        patch.object(deploy, "validate_config"),
        patch.object(deploy, "initialize_azure_infra") as init_infra,
        patch.object(deploy, "load_config") as load_config,
        patch.object(deploy, "get_stack") as get_stack,
    ):
        yield init_infra, load_config, get_stack


class TestRaiseIfChanges:
    def test_same_and_read_are_not_changes(self):
        _raise_if_changes({"same": 36, "read": 2})

    def test_zero_counts_are_not_changes(self):
        _raise_if_changes({"same": 36, "update": 0})

    def test_any_change_raises_with_summary(self):
        with pytest.raises(DeploymentError, match=r"delete: 3, update: 8"):
            _raise_if_changes({"same": 25, "update": 8, "delete": 3})


class TestDeployExpectNoChanges:
    def test_refuses_to_deploy_when_preview_plans_changes(self, patched_deploy):
        _, load_config, get_stack = patched_deploy
        load_config.return_value = _config()
        stack = _stack({"same": 35, "update": 1})
        get_stack.return_value = stack

        with pytest.raises(DeploymentError, match="Nothing was deployed"):
            deploy.deploy_infrastructure(
                Path("cfg.yaml"), auto_approve=True, expect_no_changes=True
            )

        stack.preview.assert_called_once()
        stack.up.assert_not_called()

    def test_deploys_with_backstop_when_preview_is_clean(self, patched_deploy):
        _, load_config, get_stack = patched_deploy
        load_config.return_value = _config()
        stack = _stack({"same": 36})
        get_stack.return_value = stack

        deploy.deploy_infrastructure(
            Path("cfg.yaml"), auto_approve=True, expect_no_changes=True
        )

        stack.up.assert_called_once()
        assert stack.up.call_args.kwargs["expect_no_changes"] is True

    def test_preview_mode_fails_when_changes_are_planned(self, patched_deploy):
        _, load_config, get_stack = patched_deploy
        load_config.return_value = _config()
        get_stack.return_value = _stack({"same": 35, "create": 1})

        with pytest.raises(DeploymentError, match="create: 1"):
            deploy.deploy_infrastructure(
                Path("cfg.yaml"), preview=True, expect_no_changes=True
            )

    def test_requires_existing_backend_before_initializing_azure(self, patched_deploy):
        init_infra, load_config, get_stack = patched_deploy
        load_config.return_value = _config(state_store=None)

        with pytest.raises(DeploymentError, match="requires an existing deployment"):
            deploy.deploy_infrastructure(
                Path("cfg.yaml"), auto_approve=True, expect_no_changes=True
            )

        init_infra.assert_not_called()
        get_stack.assert_not_called()

    def test_default_deploy_does_not_preview_first(self, patched_deploy):
        _, load_config, get_stack = patched_deploy
        load_config.return_value = _config()
        stack = _stack({"same": 36})
        get_stack.return_value = stack

        deploy.deploy_infrastructure(Path("cfg.yaml"), auto_approve=True)

        stack.preview.assert_not_called()
        assert stack.up.call_args.kwargs["expect_no_changes"] is None


class TestCliFlag:
    @patch("llmaven.deployment.deploy.deploy_infrastructure")
    def test_flag_is_passed_through(self, mock_deploy):
        result = CliRunner().invoke(
            app, ["infra", "deploy", "--yes", "--expect-no-changes"]
        )

        assert result.exit_code == 0
        assert mock_deploy.call_args.kwargs["expect_no_changes"] is True

    @patch("llmaven.deployment.deploy.deploy_infrastructure")
    def test_flag_defaults_to_false(self, mock_deploy):
        result = CliRunner().invoke(app, ["infra", "deploy", "--yes"])

        assert result.exit_code == 0
        assert mock_deploy.call_args.kwargs["expect_no_changes"] is False
