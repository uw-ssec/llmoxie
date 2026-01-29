# tests/infrastructure/test_cli.py

"""CLI tests for LiteLLM log extraction (infra extract).

These tests patch _get_llmaven_secrets() so we never import the real secrets module,
avoiding event-loop / async / grpc side effects during unit tests.
"""

from __future__ import annotations

import json
from unittest.mock import Mock, patch

import pytest
import typer


def _mock_console_pair(mock_console_cls):
    console = Mock()
    console_err = Mock()
    mock_console_cls.side_effect = [console, console_err]
    return console, console_err


def _make_path_mock(
    *,
    exists: bool = False,
    is_dir: bool = False,
    mkdir_raises: Exception | None = None,
):
    p = Mock()
    p.exists.return_value = exists
    p.is_dir.return_value = is_dir

    parent = Mock()
    if mkdir_raises is not None:
        parent.mkdir.side_effect = mkdir_raises
    else:
        parent.mkdir.return_value = None

    p.parent = parent
    p.__str__ = Mock(return_value="/tmp/out.zip")
    return p


class TestInfraExtract:
    @patch("rich.console.Console")
    def test_rejects_invalid_date_format(self, mock_console_cls):
        _mock_console_pair(mock_console_cls)
        from llmaven.cli import extract

        with pytest.raises(typer.Exit):
            extract(from_date="2026-99-01", to_date="2026-01-02")

    @patch("rich.console.Console")
    def test_rejects_inverted_date_range(self, mock_console_cls):
        _mock_console_pair(mock_console_cls)
        from llmaven.cli import extract

        with pytest.raises(typer.Exit):
            extract(from_date="2026-01-03", to_date="2026-01-02")

    @patch("rich.console.Console")
    @patch("llmaven.cli.Path")
    def test_rejects_output_directory(self, mock_path_cls, mock_console_cls):
        _mock_console_pair(mock_console_cls)
        from llmaven.cli import extract

        mock_path_cls.return_value = _make_path_mock(exists=True, is_dir=True)

        with pytest.raises(typer.Exit):
            extract(
                from_date="2026-01-01", to_date="2026-01-01", output_file="/tmp/out.zip"
            )

    @patch("rich.console.Console")
    @patch("llmaven.cli.Path")
    def test_mkdir_failure_exits(self, mock_path_cls, mock_console_cls):
        _mock_console_pair(mock_console_cls)
        from llmaven.cli import extract

        mock_path_cls.return_value = _make_path_mock(
            exists=False, is_dir=False, mkdir_raises=PermissionError("denied")
        )

        with pytest.raises(typer.Exit):
            extract(
                from_date="2026-01-01", to_date="2026-01-01", output_file="/tmp/out.zip"
            )

    @patch("rich.console.Console")
    @patch("llmaven.cli.Path")
    @patch("llmaven.cli.typer.confirm", return_value=False)
    def test_declines_overwrite(self, mock_confirm, mock_path_cls, mock_console_cls):
        console, _ = _mock_console_pair(mock_console_cls)
        from llmaven.cli import extract

        mock_path_cls.return_value = _make_path_mock(exists=True, is_dir=False)

        with pytest.raises(typer.Exit) as e:
            extract(
                from_date="2026-01-01", to_date="2026-01-01", output_file="/tmp/out.zip"
            )
        assert e.value.exit_code == 0
        console.print.assert_called()

    @patch("rich.console.Console")
    @patch("llmaven.cli.Path")
    @patch(
        "llmaven.cli._get_llmaven_secrets",
        return_value={"litellm-base-url": "http://x"},
    )
    def test_missing_master_key(self, _mock_secrets, mock_path_cls, mock_console_cls):
        _mock_console_pair(mock_console_cls)
        from llmaven.cli import extract

        mock_path_cls.return_value = _make_path_mock(exists=False, is_dir=False)

        with pytest.raises(typer.Exit) as e:
            extract(
                from_date="2026-01-01", to_date="2026-01-01", output_file="/tmp/out.zip"
            )
        assert e.value.exit_code == 1

    @patch("rich.console.Console")
    @patch("llmaven.cli.Path")
    @patch(
        "llmaven.cli._get_llmaven_secrets", return_value={"litellm-master-key": "mk"}
    )
    def test_missing_base_url(self, _mock_secrets, mock_path_cls, mock_console_cls):
        _mock_console_pair(mock_console_cls)
        from llmaven.cli import extract

        mock_path_cls.return_value = _make_path_mock(exists=False, is_dir=False)

        with pytest.raises(typer.Exit) as e:
            extract(
                from_date="2026-01-01", to_date="2026-01-01", output_file="/tmp/out.zip"
            )
        assert e.value.exit_code == 1

    @patch("rich.console.Console")
    @patch("llmaven.cli.Path")
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
        mock_path_cls,
        mock_console_cls,
    ):
        console, _ = _mock_console_pair(mock_console_cls)
        from llmaven.cli import extract

        mock_path_cls.return_value = _make_path_mock(exists=False, is_dir=False)

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

        extract(
            from_date="2026-01-01", to_date="2026-01-02", output_file="/tmp/out.zip"
        )

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
        assert '"request_id": "a"' in payload0  # basic content check
        name1, payload1 = zipf.writestr.call_args_list[1][0]
        assert name1 == "litellm_spend_logs_2026-01-02.jsonl"
        assert payload1 == ""  # empty day => empty file contents

        # Total record summary should be printed
        printed = " ".join(
            str(c[0][0]) for c in console.print.call_args_list if c and c[0]
        )
        assert "1 total records" in printed

    @patch("rich.console.Console")
    @patch("llmaven.cli.Path")
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
        mock_path_cls,
        mock_console_cls,
    ):
        _mock_console_pair(mock_console_cls)
        from llmaven.cli import extract

        mock_path_cls.return_value = _make_path_mock(exists=False, is_dir=False)

        resp = Mock()
        import httpx

        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "boom", request=Mock(), response=Mock()
        )

        http_client = Mock()
        http_client.get.return_value = resp
        mock_httpx_client_cls.return_value.__enter__.return_value = http_client
        mock_zip_cls.return_value.__enter__.return_value = Mock()

        with pytest.raises(typer.Exit) as e:
            extract(
                from_date="2026-01-01", to_date="2026-01-01", output_file="/tmp/out.zip"
            )
        assert e.value.exit_code == 1

    @patch("rich.console.Console")
    @patch("llmaven.cli.Path")
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
        mock_path_cls,
        mock_console_cls,
    ):
        _mock_console_pair(mock_console_cls)
        from llmaven.cli import extract

        mock_path_cls.return_value = _make_path_mock(exists=False, is_dir=False)

        resp = Mock()
        resp.raise_for_status.return_value = None
        resp.json.side_effect = json.JSONDecodeError("bad", "doc", 0)

        http_client = Mock()
        http_client.get.return_value = resp
        mock_httpx_client_cls.return_value.__enter__.return_value = http_client
        mock_zip_cls.return_value.__enter__.return_value = Mock()

        with pytest.raises(typer.Exit) as e:
            extract(
                from_date="2026-01-01", to_date="2026-01-01", output_file="/tmp/out.zip"
            )
        assert e.value.exit_code == 1

    @patch("rich.console.Console")
    @patch("llmaven.cli.Path")
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
        mock_path_cls,
        mock_console_cls,
    ):
        _mock_console_pair(mock_console_cls)
        from llmaven.cli import extract

        mock_path_cls.return_value = _make_path_mock(exists=False, is_dir=False)

        resp = Mock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"not": "a list"}

        http_client = Mock()
        http_client.get.return_value = resp
        mock_httpx_client_cls.return_value.__enter__.return_value = http_client
        mock_zip_cls.return_value.__enter__.return_value = Mock()

        with pytest.raises(typer.Exit) as e:
            extract(
                from_date="2026-01-01", to_date="2026-01-01", output_file="/tmp/out.zip"
            )
        assert e.value.exit_code == 1
