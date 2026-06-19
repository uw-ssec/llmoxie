# tests/infrastructure/test_cli.py

"""CLI tests for LiteLLM log extraction (infra extract).

These tests patch _get_llmaven_secrets() so we never import the real secrets module,
avoiding event-loop / async / grpc side effects during unit tests.
"""

from __future__ import annotations

from datetime import date
import json
import os
import re
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from click.testing import Result
from typer.testing import CliRunner

from llmaven.cli import _serialize_to_jsonl, _utc_date_to_epoch_ms, app


_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    """Remove ANSI color escape codes so substring asserts survive Typer's colorized output."""
    return _ANSI_ESCAPE_RE.sub("", text)


class TestSerializeToJsonl:
    def test_empty_list_returns_empty_string(self):
        result = _serialize_to_jsonl([])
        assert result == ""

    def test_two_records_each_on_own_line(self):
        records = [{"id": 1, "value": "a"}, {"id": 2, "value": "b"}]
        result = _serialize_to_jsonl(records)
        assert result == '{"id": 1, "value": "a"}\n{"id": 2, "value": "b"}\n'


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def invoke_extract(
    runner: CliRunner,
    *,
    from_date: str,
    to_date: str,
    source: str | None,
    output_file: Path | None = None,
    input: str | None = None,
) -> Result:
    args = ["infra", "extract"]
    if source is not None:
        args += ["--source", source]
    args += ["--from", from_date, "--to", to_date]
    if output_file is not None:
        args += ["--out", str(output_file)]

    return runner.invoke(app, args, input=input)


class TestInfraExtract:
    def test_rejects_invalid_date_format(self, runner: CliRunner):
        result = invoke_extract(
            runner, from_date="2026-99-01", to_date="2026-01-02", source=None
        )

        assert result.exit_code == 1
        assert "Invalid date format" in result.output

    def test_rejects_inverted_date_range(self, runner: CliRunner):
        result = invoke_extract(
            runner, from_date="2026-01-03", to_date="2026-01-02", source=None
        )

        assert result.exit_code == 1
        assert "--from must be <= --to" in result.output

    def test_rejects_output_directory(self, runner: CliRunner, tmp_path: Path):
        out_dir = tmp_path / "output-dir"
        out_dir.mkdir()

        result = invoke_extract(
            runner,
            from_date="2026-01-01",
            to_date="2026-01-01",
            source=None,
            output_file=out_dir,
        )

        assert result.exit_code == 2
        assert "Invalid value for '--out'" in _strip_ansi(result.output)

    def test_mkdir_failure_exits(self, runner: CliRunner, tmp_path: Path):
        base_dir = tmp_path / "no-write"
        base_dir.mkdir()
        os.chmod(base_dir, 0o500)
        output_file = base_dir / "nested" / "out.zip"

        try:
            result = invoke_extract(
                runner,
                from_date="2026-01-01",
                to_date="2026-01-01",
                source=None,
                output_file=output_file,
            )
        finally:
            os.chmod(base_dir, 0o700)

        assert result.exit_code == 1
        assert "Cannot create output directory" in result.output

    def test_declines_overwrite(self, runner: CliRunner, tmp_path: Path):
        output_file = tmp_path / "out.zip"
        output_file.write_text("already exists", encoding="utf-8")

        result = invoke_extract(
            runner,
            from_date="2026-01-01",
            to_date="2026-01-01",
            source=None,
            output_file=output_file,
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

        result = invoke_extract(
            runner,
            from_date="2026-01-01",
            to_date="2026-01-01",
            source=None,
            output_file=output_file,
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

        result = invoke_extract(
            runner,
            from_date="2026-01-01",
            to_date="2026-01-01",
            source=None,
            output_file=output_file,
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

        result = invoke_extract(
            runner,
            from_date="2026-01-01",
            to_date="2026-01-02",
            source=None,
            output_file=output_file,
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

        result = invoke_extract(
            runner,
            from_date="2026-01-01",
            to_date="2026-01-01",
            source=None,
            output_file=output_file,
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

        result = invoke_extract(
            runner,
            from_date="2026-01-01",
            to_date="2026-01-01",
            source=None,
            output_file=output_file,
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

        result = invoke_extract(
            runner,
            from_date="2026-01-01",
            to_date="2026-01-01",
            source=None,
            output_file=output_file,
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
            result = invoke_extract(
                runner, from_date="2026-01-01", to_date="2026-01-01", source=None
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
            result = invoke_extract(
                runner, from_date="2026-01-01", to_date="2026-01-01", source="litellm"
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
            result = invoke_extract(
                runner, from_date="2026-01-01", to_date="2026-01-01", source="mlflow"
            )

        assert result.exit_code == 0
        mock_mlflow_extract.assert_called_once()
        mock_litellm_extract.assert_not_called()

        called_args = mock_mlflow_extract.call_args[0]
        assert (
            called_args[2].name
            == "llmaven_mlflow_experiment_traces_2026-01-01_to_2026-01-01.zip"
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

        result = invoke_extract(
            runner,
            from_date="2026-01-01",
            to_date="2026-01-01",
            source="mlflow",
            output_file=output_file,
        )

        assert result.exit_code == 1
        assert "Missing: LLMAVEN_SECRETS_MLFLOW_TRACKING_URI" in result.output

    @patch(
        "llmaven.cli._get_llmaven_secrets",
        return_value={"mlflow-tracking-uri": "http://mlflow"},
    )
    @patch("llmaven.cli._fetch_mlflow_experiment_traces_in_date_range")
    @patch("llmaven.cli._fetch_mlflow_experiment_ids_for_date_range")
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

        result = invoke_extract(
            runner,
            from_date="2026-01-01",
            to_date="2026-01-02",
            source="mlflow",
            output_file=output_file,
        )

        assert result.exit_code == 0
        assert "Found 2 MLflow experiment(s)" in result.output

        mock_set_tracking_uri.assert_called_once_with("http://mlflow")
        mock_mlflow_client_cls.assert_called_once_with(tracking_uri="http://mlflow")
        mock_fetch_experiment_ids.assert_called_once_with(
            mock_mlflow_client_cls.return_value,
            date(2026, 1, 1),
            date(2026, 1, 2),
        )

        assert mock_fetch_traces.call_count == 2

        first_kwargs = mock_fetch_traces.call_args_list[0].kwargs
        assert first_kwargs["client"] == mock_mlflow_client_cls.return_value
        assert first_kwargs["experiment_ids"] == ["1", "2"]
        assert first_kwargs["start_ms"] == _utc_date_to_epoch_ms(date(2026, 1, 1))
        assert first_kwargs["end_ms"] == _utc_date_to_epoch_ms(date(2026, 1, 2))

        second_kwargs = mock_fetch_traces.call_args_list[1].kwargs
        assert second_kwargs["start_ms"] == _utc_date_to_epoch_ms(date(2026, 1, 2))
        assert second_kwargs["end_ms"] == _utc_date_to_epoch_ms(date(2026, 1, 3))

        assert zipf.writestr.call_count == 2

        name0, payload0 = zipf.writestr.call_args_list[0][0]
        assert name0 == "mlflow_traces_2026-01-01_experiment_1.jsonl"
        assert '"info":' in payload0
        assert '"data":' in payload0
        assert '"spans":' in payload0
        assert '"trace_id": "tr-1"' in payload0

        name1, payload1 = zipf.writestr.call_args_list[1][0]
        assert name1 == "mlflow_traces_2026-01-02_experiment_2.jsonl"
        assert '"trace_id": "tr-2"' in payload1

        assert "2 total records" in result.output

    @patch(
        "llmaven.cli._get_llmaven_secrets",
        return_value={"mlflow-tracking-uri": "http://mlflow"},
    )
    @patch("llmaven.cli._fetch_mlflow_experiment_traces_in_date_range")
    @patch("llmaven.cli._fetch_mlflow_experiment_ids_for_date_range", return_value=[])
    @patch("zipfile.ZipFile")
    @patch("mlflow.MlflowClient")
    @patch("mlflow.set_tracking_uri")
    def test_mlflow_no_experiments_writes_no_files(
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

        result = invoke_extract(
            runner,
            from_date="2026-01-01",
            to_date="2026-01-02",
            source="mlflow",
            output_file=output_file,
        )

        assert result.exit_code == 0
        assert zipf.writestr.call_count == 0
        assert "0 total records" in result.output

    @patch(
        "llmaven.cli._get_llmaven_secrets",
        return_value={"mlflow-tracking-uri": "http://mlflow"},
    )
    @patch("llmaven.cli._fetch_mlflow_experiment_traces_in_date_range")
    @patch(
        "llmaven.cli._fetch_mlflow_experiment_ids_for_date_range", return_value=["1"]
    )
    @patch("zipfile.ZipFile")
    @patch("mlflow.MlflowClient")
    @patch("mlflow.set_tracking_uri")
    def test_mlflow_empty_trace_day_writes_no_files(
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

        result = invoke_extract(
            runner,
            from_date="2026-01-01",
            to_date="2026-01-01",
            source="mlflow",
            output_file=output_file,
        )

        assert result.exit_code == 0
        mock_fetch_traces.assert_called_once()

        assert zipf.writestr.call_count == 0
        assert "0 total records" in result.output

    @patch(
        "llmaven.cli._get_llmaven_secrets",
        return_value={"mlflow-tracking-uri": "http://mlflow"},
    )
    @patch(
        "llmaven.cli._fetch_mlflow_experiment_traces_in_date_range",
    )
    @patch(
        "llmaven.cli._fetch_mlflow_experiment_ids_for_date_range",
        return_value=["1"],
    )
    @patch("zipfile.ZipFile")
    def test_mlflow_json_serialize_error_exits(
        self,
        mock_zip_cls,
        mock_fetch_experiment_ids,
        mock_fetch_traces,
        _mock_secrets,
        runner: CliRunner,
        tmp_path: Path,
    ):
        bad_payload = _make_trace_payload("tr-1", experiment_id="1")
        bad_payload["bad"] = {1, 2, 3}
        mock_fetch_traces.return_value = [DummyTrace(bad_payload)]

        output_file = tmp_path / "out.zip"
        mock_zip_cls.return_value.__enter__.return_value = Mock()

        result = invoke_extract(
            runner,
            from_date="2026-01-01",
            to_date="2026-01-01",
            source="mlflow",
            output_file=output_file,
        )

        assert result.exit_code == 1
        assert (
            "Failed to JSON-serialize MLflow traces for "
            "2026-01-01, experiment 1" in result.output
        )

    @patch(
        "llmaven.cli._get_llmaven_secrets",
        return_value={"mlflow-tracking-uri": "http://mlflow"},
    )
    @patch(
        "llmaven.cli._fetch_mlflow_experiment_ids_for_date_range",
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

        result = invoke_extract(
            runner,
            from_date="2026-01-01",
            to_date="2026-01-01",
            source="mlflow",
            output_file=output_file,
        )

        assert result.exit_code == 1
        assert "MLflow experiment search failed: boom" in result.output

    @patch(
        "llmaven.cli._get_llmaven_secrets",
        return_value={"mlflow-tracking-uri": "http://mlflow"},
    )
    @patch(
        "llmaven.cli._fetch_mlflow_experiment_traces_in_date_range",
        side_effect=RuntimeError("boom"),
    )
    @patch(
        "llmaven.cli._fetch_mlflow_experiment_ids_for_date_range", return_value=["1"]
    )
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

        result = invoke_extract(
            runner,
            from_date="2026-01-01",
            to_date="2026-01-01",
            source="mlflow",
            output_file=output_file,
        )

        assert result.exit_code == 1
        assert "MLflow trace search failed for 2026-01-01: boom" in result.output

    def test_fetch_mlflow_experiment_ids_for_date_range_paginates(self):
        from llmaven.cli import _fetch_mlflow_experiment_ids_for_date_range

        client = Mock()
        client.search_experiments.side_effect = [
            MockPagedList([DummyExperiment("1")], token="next"),
            MockPagedList([DummyExperiment("2"), DummyExperiment("3")], token=None),
        ]

        experiment_ids = _fetch_mlflow_experiment_ids_for_date_range(
            client, date(2026, 1, 1), date(2026, 1, 2)
        )

        assert experiment_ids == ["1", "2", "3"]
        assert client.search_experiments.call_count == 2

    def test_fetch_mlflow_experiment_traces_in_date_range_returns_empty_when_no_experiments(
        self,
    ):
        from llmaven.cli import _fetch_mlflow_experiment_traces_in_date_range

        client = Mock()

        traces = _fetch_mlflow_experiment_traces_in_date_range(
            client=client,
            experiment_ids=[],
            start_ms=1,
            end_ms=2,
        )

        assert traces == []
        client.search_traces.assert_not_called()

    def test_fetch_mlflow_experiment_traces_in_date_range_paginates_and_uses_expected_filter(
        self,
    ):
        from llmaven.cli import _fetch_mlflow_experiment_traces_in_date_range

        trace1 = DummyTrace(_make_trace_payload("tr-a", experiment_id="11"))
        trace2 = DummyTrace(_make_trace_payload("tr-b", experiment_id="22"))

        client = Mock()
        client.search_traces.side_effect = [
            MockPagedList([trace1], token="next"),
            MockPagedList([trace2], token=None),
        ]

        traces = _fetch_mlflow_experiment_traces_in_date_range(
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

    @patch(
        "llmaven.cli._get_llmaven_secrets",
        return_value={"mlflow-tracking-uri": "http://mlflow"},
    )
    @patch("llmaven.cli._fetch_mlflow_experiment_traces_in_date_range")
    @patch(
        "llmaven.cli._fetch_mlflow_experiment_ids_for_date_range",
        return_value=["1", "2"],
    )
    @patch("zipfile.ZipFile")
    @patch("mlflow.MlflowClient")
    @patch("mlflow.set_tracking_uri")
    def test_mlflow_same_day_traces_are_split_by_experiment(
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

        mock_fetch_traces.return_value = [
            DummyTrace(_make_trace_payload("tr-1", experiment_id="1", message="hello")),
            DummyTrace(_make_trace_payload("tr-2", experiment_id="2", message="world")),
        ]

        zipf = Mock()
        mock_zip_cls.return_value.__enter__.return_value = zipf

        result = invoke_extract(
            runner,
            from_date="2026-01-01",
            to_date="2026-01-01",
            source="mlflow",
            output_file=output_file,
        )

        assert result.exit_code == 0
        mock_fetch_traces.assert_called_once()
        assert zipf.writestr.call_count == 2

        written = {call.args[0]: call.args[1] for call in zipf.writestr.call_args_list}

        assert "mlflow_traces_2026-01-01_experiment_1.jsonl" in written
        assert "mlflow_traces_2026-01-01_experiment_2.jsonl" in written

        payload1 = written["mlflow_traces_2026-01-01_experiment_1.jsonl"]
        payload2 = written["mlflow_traces_2026-01-01_experiment_2.jsonl"]

        assert '"trace_id": "tr-1"' in payload1
        assert '"trace_id": "tr-2"' not in payload1

        assert '"trace_id": "tr-2"' in payload2
        assert '"trace_id": "tr-1"' not in payload2

        assert "2 total records" in result.output

    @patch(
        "llmaven.cli._get_llmaven_secrets",
        return_value={"mlflow-tracking-uri": "http://mlflow"},
    )
    @patch("llmaven.cli._fetch_mlflow_experiment_traces_in_date_range")
    @patch(
        "llmaven.cli._fetch_mlflow_experiment_ids_for_date_range",
        return_value=["1"],
    )
    @patch("zipfile.ZipFile")
    @patch("mlflow.MlflowClient")
    @patch("mlflow.set_tracking_uri")
    def test_mlflow_same_day_same_experiment_traces_are_grouped_into_one_file(
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

        mock_fetch_traces.return_value = [
            DummyTrace(_make_trace_payload("tr-1", experiment_id="1", message="hello")),
            DummyTrace(_make_trace_payload("tr-2", experiment_id="1", message="world")),
        ]

        zipf = Mock()
        mock_zip_cls.return_value.__enter__.return_value = zipf

        result = invoke_extract(
            runner,
            from_date="2026-01-01",
            to_date="2026-01-01",
            source="mlflow",
            output_file=output_file,
        )

        assert result.exit_code == 0
        mock_fetch_traces.assert_called_once()
        assert zipf.writestr.call_count == 1

        name0, payload0 = zipf.writestr.call_args_list[0][0]
        assert name0 == "mlflow_traces_2026-01-01_experiment_1.jsonl"
        assert '"trace_id": "tr-1"' in payload0
        assert '"trace_id": "tr-2"' in payload0

        # Two JSONL records should be present in the same file.
        assert len(payload0.strip().splitlines()) == 2

        assert "2 total records" in result.output

    @patch("llmaven.cli._extract_litellm_logs")
    def test_default_output_path_directory_exits_for_generated_litellm_filename(
        self,
        mock_litellm_extract,
        runner: CliRunner,
    ):
        with runner.isolated_filesystem():
            default_dir = Path(
                "llmaven_litellm_spend_logs_2026-01-01_to_2026-01-01.zip"
            )
            default_dir.mkdir()

            result = invoke_extract(
                runner, from_date="2026-01-01", to_date="2026-01-01", source=None
            )

        assert result.exit_code == 1
        assert "Default output path is a directory" in result.output
        mock_litellm_extract.assert_not_called()

    @patch("llmaven.cli._extract_mlflow_logs")
    def test_accepts_overwrite_and_continues(
        self,
        mock_mlflow_extract,
        runner: CliRunner,
        tmp_path: Path,
    ):
        output_file = tmp_path / "out.zip"
        output_file.write_text("already exists", encoding="utf-8")

        result = invoke_extract(
            runner,
            from_date="2026-01-01",
            to_date="2026-01-01",
            source="mlflow",
            output_file=output_file,
            input="y\n",
        )

        assert result.exit_code == 0
        mock_mlflow_extract.assert_called_once()

        called_args = mock_mlflow_extract.call_args[0]
        assert called_args[0] == date(2026, 1, 1)
        assert called_args[1] == date(2026, 1, 1)
        assert called_args[2] == output_file
        assert called_args[3] is None

    @patch(
        "llmaven.cli._get_llmaven_secrets",
        return_value={"mlflow-tracking-uri": "http://mlflow"},
    )
    @patch("llmaven.cli._fetch_mlflow_experiment_traces_in_date_range")
    @patch(
        "llmaven.cli._fetch_mlflow_experiment_ids_for_date_range",
        return_value=["1"],
    )
    @patch("zipfile.ZipFile")
    @patch("mlflow.MlflowClient")
    @patch("mlflow.set_tracking_uri")
    def test_mlflow_grouping_failure_when_trace_to_dict_raises(
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
        class BadTrace:
            def to_dict(self):
                raise RuntimeError("boom")

        output_file = tmp_path / "out.zip"
        mock_fetch_traces.return_value = [BadTrace()]
        mock_zip_cls.return_value.__enter__.return_value = Mock()

        result = invoke_extract(
            runner,
            from_date="2026-01-01",
            to_date="2026-01-01",
            source="mlflow",
            output_file=output_file,
        )

        assert result.exit_code == 1
        assert (
            "Failed to group MLflow traces by experiment for 2026-01-01: boom"
            in result.output
        )

    def test_fetch_mlflow_experiment_ids_for_date_range_uses_expected_filter_and_args(
        self,
    ):
        from mlflow.entities import ViewType
        from llmaven.cli import _fetch_mlflow_experiment_ids_for_date_range

        client = Mock()
        client.search_experiments.return_value = MockPagedList(
            [DummyExperiment("1")], token=None
        )

        start_date = date(2026, 1, 1)
        end_date = date(2026, 1, 2)

        experiment_ids = _fetch_mlflow_experiment_ids_for_date_range(
            client, start_date, end_date
        )

        assert experiment_ids == ["1"]
        client.search_experiments.assert_called_once()

        _, kwargs = client.search_experiments.call_args
        assert kwargs["view_type"] == ViewType.ACTIVE_ONLY
        assert kwargs["filter_string"] == (
            f"creation_time < {_utc_date_to_epoch_ms(end_date)}"
        )
        assert kwargs["max_results"] == 1000
        assert kwargs["page_token"] is None
