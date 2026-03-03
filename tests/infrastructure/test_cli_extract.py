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


class MockPagedList(list):
    def __init__(self, items, token=None):
        super().__init__(items)
        self.token = token


class DummyExperiment:
    def __init__(self, experiment_id: str):
        self.experiment_id = experiment_id


def _make_trace_payload(
    trace_id: str,
    experiment_id: str = "0",
    message: str = "hello from MLflow trace",
) -> dict:
    return {
        "info": {
            "trace_id": trace_id,
            "trace_location": {
                "type": "MLFLOW_EXPERIMENT",
                "mlflow_experiment": {"experiment_id": experiment_id},
            },
            "request_time": "2026-03-03T03:43:59.047Z",
            "state": "OK",
            "trace_metadata": {
                "mlflow.trace_schema.version": "3",
                "mlflow.traceInputs": "{}",
                "mlflow.traceOutputs": f'{{"message": "{message}", "status": "ok"}}',
                "mlflow.user": "layomia",
            },
            "tags": {
                "mlflow.traceName": "my_test_trace",
            },
            "request_preview": "{}",
            "response_preview": f'{{"message": "{message}", "status": "ok"}}',
            "execution_duration_ms": 122,
        },
        "data": {
            "spans": [
                {
                    "name": "my_test_trace",
                    "attributes": {
                        "mlflow.spanOutputs": f'{{"message": "{message}", "status": "ok"}}'
                    },
                }
            ]
        },
    }


class DummyTrace:
    def __init__(self, payload: dict):
        self._payload = payload

    def to_dict(self):
        return self._payload


class TestInfraExtractSources:
    @patch("llmaven.cli._extract_mlflow_logs")
    @patch("llmaven.cli._extract_litellm_logs")
    def test_extract_defaults_to_litellm_source(
        self,
        mock_litellm_extract,
        mock_mlflow_extract,
        runner: CliRunner,
    ):
        with runner.isolated_filesystem():
            result = runner.invoke(
                app,
                [
                    "infra",
                    "extract",
                    "--from",
                    "2026-01-01",
                    "--to",
                    "2026-01-01",
                ],
            )

        assert result.exit_code == 0
        mock_litellm_extract.assert_called_once()
        mock_mlflow_extract.assert_not_called()

        called_args = mock_litellm_extract.call_args[0]
        assert (
            called_args[2].name
            == "llmaven_litellm_spend_logs_2026-01-01_to_2026-01-01.zip"
        )

    @patch("llmaven.cli._extract_mlflow_logs")
    @patch("llmaven.cli._extract_litellm_logs")
    def test_extract_source_litellm_dispatches_to_litellm_backend(
        self,
        mock_litellm_extract,
        mock_mlflow_extract,
        runner: CliRunner,
    ):
        with runner.isolated_filesystem():
            result = runner.invoke(
                app,
                [
                    "infra",
                    "extract",
                    "--source",
                    "litellm",
                    "--from",
                    "2026-01-01",
                    "--to",
                    "2026-01-01",
                ],
            )

        assert result.exit_code == 0
        mock_litellm_extract.assert_called_once()
        mock_mlflow_extract.assert_not_called()

        called_args = mock_litellm_extract.call_args[0]
        assert (
            called_args[2].name
            == "llmaven_litellm_spend_logs_2026-01-01_to_2026-01-01.zip"
        )

    @patch("llmaven.cli._extract_mlflow_logs")
    @patch("llmaven.cli._extract_litellm_logs")
    def test_extract_source_mlflow_dispatches_to_mlflow_backend(
        self,
        mock_litellm_extract,
        mock_mlflow_extract,
        runner: CliRunner,
    ):
        with runner.isolated_filesystem():
            result = runner.invoke(
                app,
                [
                    "infra",
                    "extract",
                    "--source",
                    "mlflow",
                    "--from",
                    "2026-01-01",
                    "--to",
                    "2026-01-01",
                ],
            )

        assert result.exit_code == 0
        mock_mlflow_extract.assert_called_once()
        mock_litellm_extract.assert_not_called()

        called_args = mock_mlflow_extract.call_args[0]
        assert (
            called_args[2].name
            == "llmaven_mlflow_spend_logs_2026-01-01_to_2026-01-01.zip"
        )


class TestInfraExtractMLflow:
    @patch("llmaven.cli._get_llmaven_secrets", return_value={})
    def test_missing_mlflow_tracking_uri(
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
                "--source",
                "mlflow",
                "--from",
                "2026-01-01",
                "--to",
                "2026-01-01",
                "--out",
                str(output_file),
            ],
        )

        assert result.exit_code == 1
        assert "Missing: LLMAVEN_SECRETS_MLFLOW_TRACKING_URI" in result.output

    @patch(
        "llmaven.cli._get_llmaven_secrets",
        return_value={"mlflow-tracking-uri": "http://mlflow"},
    )
    @patch("llmaven.cli._fetch_all_mlflow_traces_for_window")
    @patch("llmaven.cli._fetch_all_mlflow_experiment_ids")
    @patch("zipfile.ZipFile")
    @patch("mlflow.MlflowClient")
    @patch("mlflow.set_tracking_uri")
    def test_mlflow_happy_path_and_totals(
        self,
        mock_set_tracking_uri,
        mock_mlflow_client_cls,
        mock_zip_cls,
        mock_fetch_experiment_ids,
        mock_fetch_traces,
        _mock_secrets,
        runner: CliRunner,
        tmp_path: Path,
    ):
        output_file = tmp_path / "out.zip"

        mock_fetch_experiment_ids.return_value = ["1", "2"]
        mock_fetch_traces.side_effect = [
            [
                DummyTrace(
                    _make_trace_payload("tr-1", experiment_id="1", message="hello")
                )
            ],
            [
                DummyTrace(
                    _make_trace_payload("tr-2", experiment_id="2", message="world")
                )
            ],
        ]

        zipf = Mock()
        mock_zip_cls.return_value.__enter__.return_value = zipf

        result = runner.invoke(
            app,
            [
                "infra",
                "extract",
                "--source",
                "mlflow",
                "--from",
                "2026-01-01",
                "--to",
                "2026-01-02",
                "--out",
                str(output_file),
            ],
        )

        assert result.exit_code == 0
        assert "Found 2 MLflow experiment(s)" in result.output

        mock_set_tracking_uri.assert_called_once_with("http://mlflow")
        mock_mlflow_client_cls.assert_called_once_with(tracking_uri="http://mlflow")
        mock_fetch_experiment_ids.assert_called_once_with(
            mock_mlflow_client_cls.return_value
        )

        assert mock_fetch_traces.call_count == 2

        first_kwargs = mock_fetch_traces.call_args_list[0].kwargs
        assert first_kwargs["client"] == mock_mlflow_client_cls.return_value
        assert first_kwargs["experiment_ids"] == ["1", "2"]
        assert first_kwargs["start_ms"] == 1767225600000
        assert first_kwargs["end_ms"] == 1767312000000

        second_kwargs = mock_fetch_traces.call_args_list[1].kwargs
        assert second_kwargs["start_ms"] == 1767312000000
        assert second_kwargs["end_ms"] == 1767398400000

        assert zipf.writestr.call_count == 2

        name0, payload0 = zipf.writestr.call_args_list[0][0]
        assert name0 == "mlflow_spend_logs_2026-01-01.jsonl"
        assert '"info":' in payload0
        assert '"data":' in payload0
        assert '"spans":' in payload0
        assert '"trace_id": "tr-1"' in payload0

        name1, payload1 = zipf.writestr.call_args_list[1][0]
        assert name1 == "mlflow_spend_logs_2026-01-02.jsonl"
        assert '"trace_id": "tr-2"' in payload1

        assert "2 total records" in result.output

    @patch(
        "llmaven.cli._get_llmaven_secrets",
        return_value={"mlflow-tracking-uri": "http://mlflow"},
    )
    @patch("llmaven.cli._fetch_all_mlflow_traces_for_window")
    @patch("llmaven.cli._fetch_all_mlflow_experiment_ids", return_value=[])
    @patch("zipfile.ZipFile")
    @patch("mlflow.MlflowClient")
    @patch("mlflow.set_tracking_uri")
    def test_mlflow_no_experiments_writes_empty_daily_files(
        self,
        mock_set_tracking_uri,
        mock_mlflow_client_cls,
        mock_zip_cls,
        mock_fetch_experiment_ids,
        mock_fetch_traces,
        _mock_secrets,
        runner: CliRunner,
        tmp_path: Path,
    ):
        output_file = tmp_path / "out.zip"
        mock_fetch_traces.return_value = []

        zipf = Mock()
        mock_zip_cls.return_value.__enter__.return_value = zipf

        result = runner.invoke(
            app,
            [
                "infra",
                "extract",
                "--source",
                "mlflow",
                "--from",
                "2026-01-01",
                "--to",
                "2026-01-02",
                "--out",
                str(output_file),
            ],
        )

        assert result.exit_code == 0
        mock_set_tracking_uri.assert_called_once_with("http://mlflow")
        mock_mlflow_client_cls.assert_called_once_with(tracking_uri="http://mlflow")
        mock_fetch_experiment_ids.assert_called_once_with(
            mock_mlflow_client_cls.return_value
        )

        assert mock_fetch_traces.call_count == 2
        first_kwargs = mock_fetch_traces.call_args_list[0].kwargs
        assert first_kwargs["experiment_ids"] == []

        second_kwargs = mock_fetch_traces.call_args_list[1].kwargs
        assert second_kwargs["experiment_ids"] == []

        assert zipf.writestr.call_count == 2

        name0, payload0 = zipf.writestr.call_args_list[0][0]
        assert name0 == "mlflow_spend_logs_2026-01-01.jsonl"
        assert payload0 == ""

        name1, payload1 = zipf.writestr.call_args_list[1][0]
        assert name1 == "mlflow_spend_logs_2026-01-02.jsonl"
        assert payload1 == ""

        assert "0 total records" in result.output

    @patch(
        "llmaven.cli._get_llmaven_secrets",
        return_value={"mlflow-tracking-uri": "http://mlflow"},
    )
    @patch("llmaven.cli._fetch_all_mlflow_traces_for_window")
    @patch("llmaven.cli._fetch_all_mlflow_experiment_ids", return_value=["1"])
    @patch("zipfile.ZipFile")
    @patch("mlflow.MlflowClient")
    @patch("mlflow.set_tracking_uri")
    def test_mlflow_empty_trace_day_writes_empty_jsonl(
        self,
        mock_set_tracking_uri,
        mock_mlflow_client_cls,
        mock_zip_cls,
        mock_fetch_experiment_ids,
        mock_fetch_traces,
        _mock_secrets,
        runner: CliRunner,
        tmp_path: Path,
    ):
        output_file = tmp_path / "out.zip"
        mock_fetch_traces.return_value = []

        zipf = Mock()
        mock_zip_cls.return_value.__enter__.return_value = zipf

        result = runner.invoke(
            app,
            [
                "infra",
                "extract",
                "--source",
                "mlflow",
                "--from",
                "2026-01-01",
                "--to",
                "2026-01-01",
                "--out",
                str(output_file),
            ],
        )

        assert result.exit_code == 0
        mock_fetch_traces.assert_called_once()

        name0, payload0 = zipf.writestr.call_args_list[0][0]
        assert name0 == "mlflow_spend_logs_2026-01-01.jsonl"
        assert payload0 == ""

        assert "0 total records" in result.output

    @patch(
        "llmaven.cli._get_llmaven_secrets",
        return_value={"mlflow-tracking-uri": "http://mlflow"},
    )
    @patch(
        "llmaven.cli._fetch_all_mlflow_traces_for_window",
        return_value=[DummyTrace({"bad": {1, 2, 3}})],
    )
    @patch("llmaven.cli._fetch_all_mlflow_experiment_ids", return_value=["1"])
    @patch("zipfile.ZipFile")
    @patch("mlflow.MlflowClient")
    @patch("mlflow.set_tracking_uri")
    def test_mlflow_json_serialize_error_exits(
        self,
        mock_set_tracking_uri,
        mock_mlflow_client_cls,
        mock_zip_cls,
        mock_fetch_experiment_ids,
        mock_fetch_traces,
        _mock_secrets,
        runner: CliRunner,
        tmp_path: Path,
    ):
        output_file = tmp_path / "out.zip"
        mock_zip_cls.return_value.__enter__.return_value = Mock()

        result = runner.invoke(
            app,
            [
                "infra",
                "extract",
                "--source",
                "mlflow",
                "--from",
                "2026-01-01",
                "--to",
                "2026-01-01",
                "--out",
                str(output_file),
            ],
        )

        assert result.exit_code == 1
        assert "Failed to JSON-serialize MLflow traces for 2026-01-01" in result.output

    @patch(
        "llmaven.cli._get_llmaven_secrets",
        return_value={"mlflow-tracking-uri": "http://mlflow"},
    )
    @patch(
        "llmaven.cli._fetch_all_mlflow_experiment_ids",
        side_effect=RuntimeError("boom"),
    )
    @patch("mlflow.MlflowClient")
    @patch("mlflow.set_tracking_uri")
    def test_mlflow_experiment_search_error_exits(
        self,
        mock_set_tracking_uri,
        mock_mlflow_client_cls,
        mock_fetch_experiment_ids,
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
                "--source",
                "mlflow",
                "--from",
                "2026-01-01",
                "--to",
                "2026-01-01",
                "--out",
                str(output_file),
            ],
        )

        assert result.exit_code == 1
        assert "MLflow experiment search failed: boom" in result.output

    @patch(
        "llmaven.cli._get_llmaven_secrets",
        return_value={"mlflow-tracking-uri": "http://mlflow"},
    )
    @patch(
        "llmaven.cli._fetch_all_mlflow_traces_for_window",
        side_effect=RuntimeError("boom"),
    )
    @patch("llmaven.cli._fetch_all_mlflow_experiment_ids", return_value=["1"])
    @patch("zipfile.ZipFile")
    @patch("mlflow.MlflowClient")
    @patch("mlflow.set_tracking_uri")
    def test_mlflow_trace_search_error_exits(
        self,
        mock_set_tracking_uri,
        mock_mlflow_client_cls,
        mock_zip_cls,
        mock_fetch_experiment_ids,
        mock_fetch_traces,
        _mock_secrets,
        runner: CliRunner,
        tmp_path: Path,
    ):
        output_file = tmp_path / "out.zip"
        mock_zip_cls.return_value.__enter__.return_value = Mock()

        result = runner.invoke(
            app,
            [
                "infra",
                "extract",
                "--source",
                "mlflow",
                "--from",
                "2026-01-01",
                "--to",
                "2026-01-01",
                "--out",
                str(output_file),
            ],
        )

        assert result.exit_code == 1
        assert "MLflow trace search failed for 2026-01-01: boom" in result.output

    def test_fetch_all_mlflow_experiment_ids_paginates(self):
        from llmaven.cli import _fetch_all_mlflow_experiment_ids

        client = Mock()
        client.search_experiments.side_effect = [
            MockPagedList([DummyExperiment("1")], token="next"),
            MockPagedList([DummyExperiment("2"), DummyExperiment("3")], token=None),
        ]

        experiment_ids = _fetch_all_mlflow_experiment_ids(client)

        assert experiment_ids == ["1", "2", "3"]
        assert client.search_experiments.call_count == 2

    def test_fetch_all_mlflow_traces_for_window_returns_empty_when_no_experiments(self):
        from llmaven.cli import _fetch_all_mlflow_traces_for_window

        client = Mock()

        traces = _fetch_all_mlflow_traces_for_window(
            client=client,
            experiment_ids=[],
            start_ms=1,
            end_ms=2,
        )

        assert traces == []
        client.search_traces.assert_not_called()

    def test_fetch_all_mlflow_traces_for_window_paginates_and_uses_expected_filter(
        self,
    ):
        from llmaven.cli import _fetch_all_mlflow_traces_for_window

        trace1 = DummyTrace(_make_trace_payload("tr-a", experiment_id="11"))
        trace2 = DummyTrace(_make_trace_payload("tr-b", experiment_id="22"))

        client = Mock()
        client.search_traces.side_effect = [
            MockPagedList([trace1], token="next"),
            MockPagedList([trace2], token=None),
        ]

        traces = _fetch_all_mlflow_traces_for_window(
            client=client,
            experiment_ids=["11", "22"],
            start_ms=1767225600000,
            end_ms=1767312000000,
        )

        assert traces == [trace1, trace2]
        assert client.search_traces.call_count == 2

        _, kwargs0 = client.search_traces.call_args_list[0]
        assert kwargs0["locations"] == ["11", "22"]
        assert (
            kwargs0["filter_string"]
            == "trace.timestamp_ms >= 1767225600000 AND trace.timestamp_ms < 1767312000000"
        )
        assert kwargs0["max_results"] == 500
        assert kwargs0["order_by"] == ["timestamp_ms ASC"]
        assert kwargs0["page_token"] is None
        assert kwargs0["include_spans"] is True

        _, kwargs1 = client.search_traces.call_args_list[1]
        assert kwargs1["page_token"] == "next"
