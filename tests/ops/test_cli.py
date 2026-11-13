"""CLI tests for ``llmaven ops spend-report``."""

from __future__ import annotations

import csv
import json
import zipfile
from datetime import date
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from llmaven.cli import app
from llmaven.ops import build_ops_app
from llmaven.ops.spend import SpendFetchError, fetch_spend_records

HASHED_KEY = "a" * 64


def _record(day: date, label: str, spend: float) -> dict:
    """Build one spend-log record grouped under ``label`` by key alias."""
    return {
        "startTime": f"{day}T12:00:00Z",
        "spend": spend,
        "api_key": HASHED_KEY,
        "metadata": {"user_api_key_alias": label},
    }


def _write_zip(path: Path, records: list[dict]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "spend/2026-03.jsonl",
            "".join(json.dumps(record) + "\n" for record in records),
        )
    return path


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_spend_report_from_zip_writes_csv(tmp_path, runner):
    """A spike against the baseline window reaches both the table and the CSV."""
    archive = _write_zip(
        tmp_path / "extract.zip",
        [
            # Baseline window: 2026-03-01..2026-03-02.
            _record(date(2026, 3, 1), "alpha", 1.0),
            _record(date(2026, 3, 2), "alpha", 1.0),
            # Report window: 2026-03-03..2026-03-04.
            _record(date(2026, 3, 3), "alpha", 5.0),
            _record(date(2026, 3, 4), "alpha", 5.0),
        ],
    )
    csv_path = tmp_path / "rows.csv"

    result = runner.invoke(
        app,
        [
            "ops",
            "spend-report",
            "--start",
            "2026-03-03",
            "--end",
            "2026-03-04",
            "--from-zip",
            str(archive),
            "--csv",
            str(csv_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "alpha" in result.stdout
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    assert [(row["label"], row["flag"]) for row in rows] == [("alpha", "spike")]
    assert str(csv_path) in result.stderr


def test_spend_report_from_zip_without_baseline_notes_it(tmp_path, runner):
    """No baseline records leaves the flag blank and says so on stderr."""
    archive = _write_zip(
        tmp_path / "extract.zip",
        [_record(date(2026, 3, 3), "alpha", 5.0)],
    )
    csv_path = tmp_path / "rows.csv"

    result = runner.invoke(
        app,
        [
            "ops",
            "spend-report",
            "--start",
            "2026-03-03",
            "--end",
            "2026-03-04",
            "--from-zip",
            str(archive),
            "--csv",
            str(csv_path),
        ],
    )

    assert result.exit_code == 0, result.output
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    assert [(row["label"], row["flag"], row["prior_usd"]) for row in rows] == [
        ("alpha", "", "")
    ]
    assert "baseline" in result.stderr.lower()


def test_spend_report_start_after_end_fails(monkeypatch, runner):
    """A reversed window is a usage error, before any fetch or credential read."""

    def fail(*args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("credentials or records must not be read")

    monkeypatch.setattr("llmaven.ops.fetch_spend_records", fail)
    monkeypatch.setattr("llmaven.cli._get_litellm_credentials", fail)

    result = runner.invoke(
        app,
        ["ops", "spend-report", "--start", "2026-03-04", "--end", "2026-03-03"],
    )

    assert result.exit_code == 2


def test_spend_report_rejects_non_positive_top(runner):
    """``--top 0`` is a usage error rather than an empty table."""
    result = runner.invoke(
        app,
        [
            "ops",
            "spend-report",
            "--start",
            "2026-03-03",
            "--end",
            "2026-03-04",
            "--top",
            "0",
        ],
    )

    assert result.exit_code == 2


def test_spend_report_fetch_error_exits_1(monkeypatch, runner):
    """A failed fetch exits 1 with a ✗ message and never names the key."""

    def boom(*args, **kwargs):
        raise SpendFetchError("LiteLLM returned HTTP 401 for spend logs.")
        yield  # pragma: no cover - generator marker

    monkeypatch.setattr("llmaven.ops.fetch_spend_records", boom)
    ops_app = build_ops_app(lambda env_file: ("https://litellm.test", "sk-secret"))

    result = runner.invoke(
        ops_app,
        ["spend-report", "--start", "2026-03-03", "--end", "2026-03-04"],
    )

    assert result.exit_code == 1
    assert "✗" in result.stderr
    assert "sk-secret" not in result.output


def test_spend_report_transport_error_never_prints_the_key(monkeypatch, runner):
    """A transport error quoting the Authorization header is never echoed."""
    secret = "sk-SECRET\n"

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise httpx.ConnectError(f"Illegal header value b'Bearer {secret}'")

    def fetch(base_url, api_key, start, end):
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            yield from fetch_spend_records(
                base_url, api_key, start, end, client=client, sleep=lambda _: None
            )

    monkeypatch.setattr("llmaven.ops.fetch_spend_records", fetch)
    ops_app = build_ops_app(lambda env_file: ("https://litellm.test", secret))

    result = runner.invoke(
        ops_app,
        ["spend-report", "--start", "2026-03-03", "--end", "2026-03-04"],
    )

    assert result.exit_code == 1
    assert "✗" in result.stderr
    assert "sk-SECRET" not in result.output


def test_spend_report_invalid_base_url_never_prints_the_key(runner):
    """A malformed base URL fails cleanly and the key never reaches output."""
    secret = "sk-SECRET-master-key"
    ops_app = build_ops_app(lambda env_file: ("https://litellm.test:notaport", secret))

    result = runner.invoke(
        ops_app,
        ["spend-report", "--start", "2026-03-03", "--end", "2026-03-04"],
    )

    assert result.exit_code == 1, result.output
    assert "✗" in result.stderr
    assert secret not in result.output


def test_typer_apps_hide_traceback_locals():
    """Pretty tracebacks must not dump frame locals such as api_key."""
    from llmaven.cli import backup_infra_app, infra_app

    ops_app = build_ops_app(lambda env_file: ("https://litellm.test", "k"))
    for typer_app in (app, infra_app, backup_infra_app, ops_app):
        assert typer_app.pretty_exceptions_show_locals is False


def test_spend_report_rejects_threshold_below_one(runner):
    """``--threshold 0`` would flag every row; it is a usage error."""
    result = runner.invoke(
        app,
        [
            "ops",
            "spend-report",
            "--start",
            "2026-03-03",
            "--end",
            "2026-03-04",
            "--threshold",
            "0",
        ],
    )

    assert result.exit_code == 2


def test_spend_report_csv_path_with_brackets_is_verbatim(tmp_path, runner):
    """Square brackets in a path are not read as Rich markup on stderr."""
    archive = _write_zip(
        tmp_path / "extract.zip",
        [_record(date(2026, 3, 3), "alpha", 5.0)],
    )
    csv_path = tmp_path / "rows[x].csv"

    result = runner.invoke(
        app,
        [
            "ops",
            "spend-report",
            "--start",
            "2026-03-03",
            "--end",
            "2026-03-04",
            "--from-zip",
            str(archive),
            "--csv",
            str(csv_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "rows[x].csv" in result.stderr


def test_spend_report_failure_message_keeps_brackets(tmp_path, runner):
    """A path with markup-like text survives the ✗ error line intact."""
    archive = tmp_path / "extract[x].zip"
    archive.write_bytes(b"not a zip file at all")

    result = runner.invoke(
        app,
        [
            "ops",
            "spend-report",
            "--start",
            "2026-03-03",
            "--end",
            "2026-03-04",
            "--from-zip",
            str(archive),
        ],
    )

    assert result.exit_code == 1
    assert "extract[x].zip" in result.stderr


def test_spend_report_unreadable_source_exits_1(tmp_path, runner):
    """A corrupt --from-zip file fails cleanly instead of raising."""
    archive = tmp_path / "extract.zip"
    archive.write_bytes(b"not a zip file at all")

    result = runner.invoke(
        app,
        [
            "ops",
            "spend-report",
            "--start",
            "2026-03-03",
            "--end",
            "2026-03-04",
            "--from-zip",
            str(archive),
        ],
    )

    assert result.exit_code == 1
    assert "✗" in result.stderr
