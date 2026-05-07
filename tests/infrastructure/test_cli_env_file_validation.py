"""CLI tests for --env-file parameter validation (issue #90).

Ensures `llmaven infra validate` and `llmaven infra deploy` apply the same
Typer-level validation rules that were introduced for `llmaven infra extract`
in PR #79 (exists, file_okay, dir_okay=False, readable, resolve_path).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from llmaven.cli import app


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


class TestInfraValidateEnvFile:
    def test_rejects_missing_env_file(self, runner: CliRunner, tmp_path: Path):
        missing = tmp_path / "does-not-exist.env"

        result = runner.invoke(
            app,
            ["infra", "validate", "--env-file", str(missing)],
        )

        assert result.exit_code == 2
        assert "Invalid value for '--env-file'" in result.output

    def test_rejects_env_file_that_is_a_directory(
        self, runner: CliRunner, tmp_path: Path
    ):
        dir_path = tmp_path / "a-dir"
        dir_path.mkdir()

        result = runner.invoke(
            app,
            ["infra", "validate", "--env-file", str(dir_path)],
        )

        assert result.exit_code == 2
        assert "Invalid value for '--env-file'" in result.output

    @patch("llmaven.deployment.validate.validate_config")
    def test_accepts_valid_env_file_and_passes_path_through(
        self,
        mock_validate_config,
        runner: CliRunner,
        tmp_path: Path,
    ):
        env_file = tmp_path / ".env.secrets"
        env_file.write_text("LLMAVEN_SECRETS_FOO=bar\n", encoding="utf-8")

        result = runner.invoke(
            app,
            ["infra", "validate", "--env-file", str(env_file)],
        )

        assert result.exit_code == 0
        mock_validate_config.assert_called_once()

        kwargs = mock_validate_config.call_args.kwargs
        assert isinstance(kwargs["env_file_path"], Path)
        # resolve_path=True means the path is resolved to absolute form.
        assert kwargs["env_file_path"] == env_file.resolve()

    @patch("llmaven.deployment.validate.validate_config")
    def test_env_file_defaults_to_none(
        self,
        mock_validate_config,
        runner: CliRunner,
    ):
        with runner.isolated_filesystem():
            Path("llmaven-config.yaml").write_text("project: {}\n", encoding="utf-8")
            result = runner.invoke(app, ["infra", "validate"])

        assert result.exit_code == 0
        kwargs = mock_validate_config.call_args.kwargs
        assert kwargs["env_file_path"] is None


class TestInfraDeployEnvFile:
    def test_rejects_missing_env_file(self, runner: CliRunner, tmp_path: Path):
        missing = tmp_path / "does-not-exist.env"

        result = runner.invoke(
            app,
            ["infra", "deploy", "--yes", "--env-file", str(missing)],
        )

        assert result.exit_code == 2
        assert "Invalid value for '--env-file'" in result.output

    def test_rejects_env_file_that_is_a_directory(
        self, runner: CliRunner, tmp_path: Path
    ):
        dir_path = tmp_path / "a-dir"
        dir_path.mkdir()

        result = runner.invoke(
            app,
            ["infra", "deploy", "--yes", "--env-file", str(dir_path)],
        )

        assert result.exit_code == 2
        assert "Invalid value for '--env-file'" in result.output

    @patch("llmaven.deployment.deploy.deploy_infrastructure")
    def test_accepts_valid_env_file_and_passes_path_through(
        self,
        mock_deploy,
        runner: CliRunner,
        tmp_path: Path,
    ):
        env_file = tmp_path / ".env.secrets"
        env_file.write_text("LLMAVEN_SECRETS_FOO=bar\n", encoding="utf-8")

        result = runner.invoke(
            app,
            ["infra", "deploy", "--yes", "--env-file", str(env_file)],
        )

        assert result.exit_code == 0
        mock_deploy.assert_called_once()

        kwargs = mock_deploy.call_args.kwargs
        assert isinstance(kwargs["env_file_path"], Path)
        assert kwargs["env_file_path"] == env_file.resolve()

    @patch("llmaven.deployment.deploy.deploy_infrastructure")
    def test_env_file_defaults_to_none(
        self,
        mock_deploy,
        runner: CliRunner,
    ):
        result = runner.invoke(app, ["infra", "deploy", "--yes"])

        assert result.exit_code == 0
        kwargs = mock_deploy.call_args.kwargs
        assert kwargs["env_file_path"] is None
