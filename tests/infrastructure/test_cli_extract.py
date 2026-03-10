# tests/infrastructure/test_cli.py

"""CLI tests for LiteLLM log extraction (infra extract).

These tests patch _get_llmaven_secrets() so we never import the real secrets module,
avoiding event-loop / async / grpc side effects during unit tests.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from typer.testing import CliRunner

from llmaven.cli import app


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


class TestInfraExtract:
    def test_rejects_invalid_date_format(self, runner: CliRunner):
        result = runner.invoke(
            app,
            ["infra", "extract", "--from", "2026-99-01", "--to", "2026-01-02"],
        )

        assert result.exit_code == 1
        assert "Invalid date format" in result.output

    def test_rejects_inverted_date_range(self, runner: CliRunner):
        result = runner.invoke(
            app,
            ["infra", "extract", "--from", "2026-01-03", "--to", "2026-01-02"],
        )

        assert result.exit_code == 1
        assert "--from must be <= --to" in result.output

    def test_rejects_output_directory(self, runner: CliRunner, tmp_path: Path):
        out_dir = tmp_path / "output-dir"
        out_dir.mkdir()

        result = runner.invoke(
            app,
            [
                "infra",
                "extract",
                "--from",
                "2026-01-01",
                "--to",
                "2026-01-01",
                "--out",
                str(out_dir),
            ],
        )

        assert result.exit_code == 2
        assert "Invalid value for '--out'" in result.output

    def test_mkdir_failure_exits(self, runner: CliRunner, tmp_path: Path):
        base_dir = tmp_path / "no-write"
        base_dir.mkdir()
        os.chmod(base_dir, 0o500)
        output_file = base_dir / "nested" / "out.zip"

        try:
            result = runner.invoke(
                app,
                [
                    "infra",
                    "extract",
                    "--from",
                    "2026-01-01",
                    "--to",
                    "2026-01-01",
                    "--out",
                    str(output_file),
                ],
            )
        finally:
            os.chmod(base_dir, 0o700)

        assert result.exit_code == 1
        assert "Cannot create output directory" in result.output

    def test_declines_overwrite(self, runner: CliRunner, tmp_path: Path):
        output_file = tmp_path / "out.zip"
        output_file.write_text("already exists", encoding="utf-8")

        result = runner.invoke(
            app,
            [
                "infra",
                "extract",
                "--from",
                "2026-01-01",
                "--to",
                "2026-01-01",
                "--out",
                str(output_file),
            ],
            input="n\n",
        )

        assert result.exit_code == 0
        assert "Extraction cancelled" in result.output

    @patch(
        "llmaven.cli._get_llmaven_secrets",
        return_value={"litellm-base-url": "http://x"},
    )
    def test_missing_master_key(
        self,
        _mock_secrets,
        runner: CliRunner,
        tmp_path: Path,
    ):
        output_file = tmp_path / "out.zip"

        result = runner.invoke(
            app,
            [
                "infra",
                "extract",
                "--from",
                "2026-01-01",
                "--to",
                "2026-01-01",
                "--out",
                str(output_file),
            ],
        )

        assert result.exit_code == 1
        assert "Missing: LLMAVEN_SECRETS_LITELLM_MASTER_KEY" in result.output

    @patch(
        "llmaven.cli._get_llmaven_secrets", return_value={"litellm-master-key": "mk"}
    )
    def test_missing_base_url(
        self,
        _mock_secrets,
        runner: CliRunner,
        tmp_path: Path,
    ):
        output_file = tmp_path / "out.zip"

        result = runner.invoke(
            app,
            [
                "infra",
                "extract",
                "--from",
                "2026-01-01",
                "--to",
                "2026-01-01",
                "--out",
                str(output_file),
            ],
        )

        assert result.exit_code == 1
        assert "Missing: LLMAVEN_SECRETS_LITELLM_BASE_URL" in result.output

    @patch(
        "llmaven.cli._get_llmaven_secrets",
        return_value={"litellm-master-key": "mk", "litellm-base-url": "http://litellm"},
    )
    @patch("zipfile.ZipFile")
    @patch("httpx.Client")
    def test_happy_path_and_headers_and_totals(
        self,
        mock_httpx_client_cls,
        mock_zip_cls,
        _mock_secrets,
        runner: CliRunner,
        tmp_path: Path,
    ):
        output_file = tmp_path / "out.zip"

        # httpx client mock
        resp1 = Mock()
        resp1.raise_for_status.return_value = None
        resp1.json.return_value = [
            {
                "request_id": "a",
                "api_key": "SECRET",
                "startTime": "2026-01-01T00:00:00Z",
            }
        ]

        resp2 = Mock()
        resp2.raise_for_status.return_value = None
        resp2.json.return_value = []  # no records day 2

        http_client = Mock()
        http_client.get.side_effect = [resp1, resp2]
        mock_httpx_client_cls.return_value.__enter__.return_value = http_client

        # zipfile mock
        zipf = Mock()
        mock_zip_cls.return_value.__enter__.return_value = zipf

        result = runner.invoke(
            app,
            [
                "infra",
                "extract",
                "--from",
                "2026-01-01",
                "--to",
                "2026-01-02",
                "--out",
                str(output_file),
            ],
        )

        assert result.exit_code == 0

        # Verify request calls (endpoint + headers + params)
        assert http_client.get.call_count == 2
        (url0,), kwargs0 = http_client.get.call_args_list[0]
        assert url0 == "http://litellm/spend/logs"
        assert kwargs0["headers"] == {"Authorization": "Bearer mk"}
        assert kwargs0["params"]["start_date"] == "2026-01-01"
        assert kwargs0["params"]["end_date"] == "2026-01-02"
        assert kwargs0["params"]["summarize"] == "false"

        # Verify zip writes (one jsonl per date)
        assert zipf.writestr.call_count == 2
        name0, payload0 = zipf.writestr.call_args_list[0][0]
        assert name0 == "litellm_spend_logs_2026-01-01.jsonl"
        assert '"request_id": "a"' in payload0
        name1, payload1 = zipf.writestr.call_args_list[1][0]
        assert name1 == "litellm_spend_logs_2026-01-02.jsonl"
        assert payload1 == ""

        assert "1 total records" in result.output

    @patch(
        "llmaven.cli._get_llmaven_secrets",
        return_value={"litellm-master-key": "mk", "litellm-base-url": "http://litellm"},
    )
    @patch("zipfile.ZipFile")
    @patch("httpx.Client")
    def test_http_error_exits(
        self,
        mock_httpx_client_cls,
        mock_zip_cls,
        _mock_secrets,
        runner: CliRunner,
        tmp_path: Path,
    ):
        output_file = tmp_path / "out.zip"

        resp = Mock()
        import httpx

        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "boom", request=Mock(), response=Mock()
        )

        http_client = Mock()
        http_client.get.return_value = resp
        mock_httpx_client_cls.return_value.__enter__.return_value = http_client
        mock_zip_cls.return_value.__enter__.return_value = Mock()

        result = runner.invoke(
            app,
            [
                "infra",
                "extract",
                "--from",
                "2026-01-01",
                "--to",
                "2026-01-01",
                "--out",
                str(output_file),
            ],
        )

        assert result.exit_code == 1
        assert "LiteLLM /spend/logs failed for 2026-01-01" in result.output

    @patch(
        "llmaven.cli._get_llmaven_secrets",
        return_value={"litellm-master-key": "mk", "litellm-base-url": "http://litellm"},
    )
    @patch("zipfile.ZipFile")
    @patch("httpx.Client")
    def test_json_decode_error_exits(
        self,
        mock_httpx_client_cls,
        mock_zip_cls,
        _mock_secrets,
        runner: CliRunner,
        tmp_path: Path,
    ):
        output_file = tmp_path / "out.zip"

        resp = Mock()
        resp.raise_for_status.return_value = None
        resp.json.side_effect = json.JSONDecodeError("bad", "doc", 0)

        http_client = Mock()
        http_client.get.return_value = resp
        mock_httpx_client_cls.return_value.__enter__.return_value = http_client
        mock_zip_cls.return_value.__enter__.return_value = Mock()

        result = runner.invoke(
            app,
            [
                "infra",
                "extract",
                "--from",
                "2026-01-01",
                "--to",
                "2026-01-01",
                "--out",
                str(output_file),
            ],
        )

        assert result.exit_code == 1
        assert "Invalid JSON response for 2026-01-01" in result.output

    @patch(
        "llmaven.cli._get_llmaven_secrets",
        return_value={"litellm-master-key": "mk", "litellm-base-url": "http://litellm"},
    )
    @patch("zipfile.ZipFile")
    @patch("httpx.Client")
    def test_non_list_json_exits(
        self,
        mock_httpx_client_cls,
        mock_zip_cls,
        _mock_secrets,
        runner: CliRunner,
        tmp_path: Path,
    ):
        output_file = tmp_path / "out.zip"

        resp = Mock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"not": "a list"}

        http_client = Mock()
        http_client.get.return_value = resp
        mock_httpx_client_cls.return_value.__enter__.return_value = http_client
        mock_zip_cls.return_value.__enter__.return_value = Mock()

        result = runner.invoke(
            app,
            [
                "infra",
                "extract",
                "--from",
                "2026-01-01",
                "--to",
                "2026-01-01",
                "--out",
                str(output_file),
            ],
        )

        assert result.exit_code == 1
        assert "Invalid JSON response for 2026-01-01" in result.output
