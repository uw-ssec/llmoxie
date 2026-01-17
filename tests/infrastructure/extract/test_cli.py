"""CLI tests for LiteLLM log extraction."""

from datetime import datetime
from unittest.mock import Mock, patch

import pytest
import typer

from llmaven.cli import extract


def _mock_console_pair(mock_console_cls):
    console = Mock()
    console_err = Mock()
    mock_console_cls.side_effect = [console, console_err]
    return console, console_err


@patch("rich.console.Console")
def test_extract_rejects_invalid_date_format(mock_console_cls):
    _mock_console_pair(mock_console_cls)

    with pytest.raises(typer.Exit):
        extract(
            source="litellm",
            from_date="2026-99-01",
            to_date="2026-01-02",
            output_path="/tmp/out.zip",
            db_password="test",
        )


@patch("rich.console.Console")
def test_extract_rejects_inverted_date_range(mock_console_cls):
    _mock_console_pair(mock_console_cls)

    with pytest.raises(typer.Exit):
        extract(
            source="litellm",
            from_date="2026-01-03",
            to_date="2026-01-02",
            output_path="/tmp/out.zip",
            db_password="test",
        )


@patch("rich.console.Console")
def test_extract_rejects_unknown_source(mock_console_cls):
    _mock_console_pair(mock_console_cls)

    with pytest.raises(typer.Exit):
        extract(
            source="mlflow",
            from_date="2026-01-01",
            to_date="2026-01-02",
            output_path="/tmp/out.zip",
            db_password="test",
        )


@patch("pathlib.Path")
@patch("rich.console.Console")
def test_extract_rejects_unwritable_output_path(mock_console_cls, mock_path_cls):
    _mock_console_pair(mock_console_cls)

    mock_path = Mock()
    mock_path.parent.mkdir.side_effect = PermissionError("denied")
    mock_path_cls.return_value = mock_path

    with pytest.raises(typer.Exit):
        extract(
            source="litellm",
            from_date="2026-01-01",
            to_date="2026-01-02",
            output_path="/restricted/out.zip",
            db_password="test",
        )


@patch("pathlib.Path")
@patch("rich.console.Console")
def test_extract_declines_overwrite(mock_console_cls, mock_path_cls):
    console, _ = _mock_console_pair(mock_console_cls)

    mock_path = Mock()
    mock_path.parent.mkdir.return_value = None
    mock_path.exists.return_value = True
    mock_path.stat.return_value = None
    mock_path_cls.return_value = mock_path

    with patch("llmaven.cli.typer.confirm", return_value=False):
        with pytest.raises(typer.Exit):
            extract(
                source="litellm",
                from_date="2026-01-01",
                to_date="2026-01-02",
                output_path="/tmp/out.zip",
                db_password="test",
            )

    console.print.assert_called()


@patch("pathlib.Path")
@patch("rich.console.Console")
@patch("llmaven.cli.LiteLLMLogExtractor")
def test_extract_calls_extractor(mock_extractor_cls, mock_console_cls, mock_path_cls):
    _mock_console_pair(mock_console_cls)

    mock_path = Mock()
    mock_path.parent.mkdir.return_value = None
    mock_path.exists.return_value = False
    mock_path.stat.return_value = Mock(st_size=1024)
    mock_path_cls.return_value = mock_path

    extractor = Mock()
    mock_extractor_cls.return_value = extractor

    extract(
        source="litellm",
        from_date="2026-01-01",
        to_date="2026-01-02",
        output_path="/tmp/out.zip",
        db_host="localhost",
        db_port=5432,
        db_name="litellm_db",
        db_user="postgres",
        db_password="test",
    )

    mock_extractor_cls.assert_called_once_with(
        host="localhost",
        port=5432,
        database="litellm_db",
        user="postgres",
        password="test",
    )
    extractor.connect_to_postgres.assert_called_once()
    extractor.extract_to_zip.assert_called_once_with(
        datetime(2026, 1, 1),
        datetime(2026, 1, 2),
        mock_path,
    )
    extractor.disconnect_from_postgres.assert_called_once()


@patch("pathlib.Path")
@patch("rich.console.Console")
@patch("llmaven.cli.LiteLLMLogExtractor")
def test_extract_handles_extraction_error(
    mock_extractor_cls, mock_console_cls, mock_path_cls
):
    console, console_err = _mock_console_pair(mock_console_cls)

    mock_path = Mock()
    mock_path.parent.mkdir.return_value = None
    mock_path.exists.return_value = False
    mock_path_cls.return_value = mock_path

    extractor = Mock()
    extractor.connect_to_postgres.return_value = None
    extractor.extract_to_zip.side_effect = Exception("boom")
    mock_extractor_cls.return_value = extractor

    with pytest.raises(typer.Exit):
        extract(
            source="litellm",
            from_date="2026-01-01",
            to_date="2026-01-02",
            output_path="/tmp/out.zip",
            db_password="test",
        )

    console.print.assert_called()
    console_err.print.assert_called()
