"""Keep backup output safe for shell capture while using Rich at the CLI boundary."""

from unittest.mock import patch

import pytest
from rich.console import Console
from typer.testing import CliRunner

from llmaven.cli import app
from llmaven.deployment.deploy_backup import DeploymentError


@pytest.mark.parametrize("option", ["--name", "--secret"])
@pytest.mark.parametrize("width", [20, 80])
def test_backup_output_preserves_raw_value(monkeypatch, option, width):
    value = "https://example.test/" + "a" * 180 + "?[red]=true\tend"
    monkeypatch.setattr("llmaven.cli.console", Console(width=width))
    with patch(
        "llmaven.deployment.deploy_backup.get_backup_stack_output", return_value=value
    ) as get_output:
        result = CliRunner().invoke(app, ["backup-infra", "output", option, "output"])

    assert result.exit_code == 0
    assert result.stdout == value + "\n"
    assert result.stderr == ""
    assert get_output.call_args.kwargs["reveal_secret"] == (option == "--secret")


@pytest.mark.parametrize(
    "error", [DeploymentError("missing output"), RuntimeError("failed")]
)
def test_backup_output_failure_goes_to_stderr(error):
    with patch(
        "llmaven.deployment.deploy_backup.get_backup_stack_output", side_effect=error
    ):
        result = CliRunner().invoke(app, ["backup-infra", "output", "--name", "output"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert str(error) in result.stderr
