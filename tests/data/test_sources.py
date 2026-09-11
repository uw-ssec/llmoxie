"""Unit tests for llmaven.data.sources."""

from __future__ import annotations

import json
import logging
from datetime import date
from unittest.mock import Mock

import pytest
from llmaven.data.reader import load_messages_from_records
from llmaven.data.sources import _epoch_to_iso, from_adls, from_litellm, iter_source


class TestEpochToIso:
    def test_converts_to_matching_format(self):
        # 2026-01-02T23:41:18.414000Z, matching the litellm_spend_logs JSONL format
        assert _epoch_to_iso(1767397278.414) == "2026-01-02T23:41:18.414000Z"

    def test_none_passthrough(self):
        assert _epoch_to_iso(None) is None


class TestFromAdls:
    def test_maps_standard_logging_object_fields(self):
        record = {
            "kwargs": {
                "standard_logging_object": {
                    "id": "req-123",
                    "startTime": 1767397278.414,
                    "endTime": 1767397280.0,
                    "end_user": "user_dev1_account_acc1_session_sess1",
                    "model": "gpt-5.3-codex",
                    "response_cost": 0.05,
                    "total_tokens": 500,
                    "metadata": {
                        "user_api_key_alias": "carlos-api",
                        "user_api_key_hash": "hash1",
                    },
                    "messages": [{"role": "user", "content": "hi"}],
                    "response": {
                        "choices": [
                            {"message": {"role": "assistant", "content": "hello"}}
                        ]
                    },
                }
            }
        }
        common = from_adls(record)

        assert common["request_id"] == "req-123"
        assert common["startTime"] == "2026-01-02T23:41:18.414000Z"
        assert common["end_user"] == "user_dev1_account_acc1_session_sess1"
        assert common["model"] == "gpt-5.3-codex"
        assert common["spend"] == 0.05
        assert common["total_tokens"] == 500
        assert common["metadata"]["user_api_key_alias"] == "carlos-api"
        assert common["proxy_server_request"]["messages"] == [
            {"role": "user", "content": "hi"}
        ]
        assert common["response"]["choices"][0]["message"]["content"] == "hello"

    def test_missing_id_leaves_request_id_none(self):
        # from_adls only sees record content, not the blob's filename, so it
        # can't fill in a fallback id itself -- callers that know the
        # filename (e.g. group_sessions._load_adls_json) do that themselves.
        record = {"kwargs": {"standard_logging_object": {}}}
        common = from_adls(record)
        assert common["request_id"] is None

    def test_responses_api_shape_does_not_crash(self, caplog):
        # Real shape seen from a GitHub Copilot / gpt-5.3-codex request: reply is
        # under "output", not "choices" -- reader.py should warn, not crash.
        record = {
            "kwargs": {
                "standard_logging_object": {
                    "id": "req-1",
                    "end_user": "",
                    "messages": [{"role": "user", "content": "hi"}],
                    "response": {"output": [{"type": "message"}]},
                }
            }
        }
        common = from_adls(record)
        with caplog.at_level(logging.WARNING):
            df = load_messages_from_records([common])
        assert len(df[df["direction"] == "input"]) == 1
        assert len(df[df["direction"] == "output"]) == 0


class TestFromLitellm:
    def test_is_a_pure_passthrough(self):
        record = {
            "request_id": "r1",
            "startTime": "2026-01-01T00:00:00Z",
            "end_user": "user_abc123_account_acc1_session_dead1",
            "model": "claude-sonnet-4-6",
            "proxy_server_request": {"messages": [{"role": "user", "content": "hi"}]},
        }
        assert from_litellm(record) is record


class TestAdaptersProduceEquivalentOutput:
    """Acceptance criteria from #155: from_adls and from_litellm should
    produce the same common-format fields for the same underlying request,
    just described in each source's own raw shape."""

    def test_same_request_different_raw_shapes_converge(self):
        adls_raw = {
            "kwargs": {
                "standard_logging_object": {
                    "id": "req-xyz",
                    "startTime": 1767397278.414,
                    "endTime": 1767397280.0,
                    "end_user": "user_abc123_account_acc1_session_dead1",
                    "model": "claude-sonnet-4-6",
                    "response_cost": 0.02,
                    "total_tokens": 250,
                    "metadata": {"user_api_key_alias": "carlos-api"},
                    "messages": [{"role": "user", "content": "hello"}],
                    "response": {
                        "choices": [{"message": {"role": "assistant", "content": "hi"}}]
                    },
                }
            }
        }
        litellm_raw = {
            "request_id": "req-xyz",
            "startTime": "2026-01-02T23:41:18.414000Z",
            "endTime": "2026-01-02T23:41:20.000000Z",
            "end_user": "user_abc123_account_acc1_session_dead1",
            "model": "claude-sonnet-4-6",
            "spend": 0.02,
            "total_tokens": 250,
            "metadata": {"user_api_key_alias": "carlos-api"},
            "proxy_server_request": {"messages": [{"role": "user", "content": "hello"}]},
            "response": {
                "choices": [{"message": {"role": "assistant", "content": "hi"}}]
            },
        }

        from_adls_common = from_adls(adls_raw)
        from_litellm_common = from_litellm(litellm_raw)

        shared_fields = [
            "request_id",
            "startTime",
            "endTime",
            "end_user",
            "model",
            "spend",
            "total_tokens",
            "metadata",
            "proxy_server_request",
            "response",
        ]
        for field in shared_fields:
            assert from_adls_common[field] == from_litellm_common[field], field


def _fake_adls_fs(files: dict[str, dict]) -> Mock:
    """Build a Mock matching the AdlsFilesystem protocol: list_blobs()
    returns objects with a .name, download_blob(name).readall() returns
    that blob's JSON-encoded bytes."""
    fs = Mock()

    def list_blobs(name_starts_with: str):
        # Mock(name=...) is reserved for the mock's own repr, not an
        # attribute -- set .name explicitly instead.
        blobs = []
        for name in files:
            if name.startswith(name_starts_with):
                blob = Mock()
                blob.name = name
                blobs.append(blob)
        return blobs

    def download_blob(blob_name: str):
        downloader = Mock()
        downloader.readall.return_value = json.dumps(files[blob_name]).encode()
        return downloader

    fs.list_blobs.side_effect = list_blobs
    fs.download_blob.side_effect = download_blob
    return fs


def _fake_litellm_client(records: list[dict]) -> Mock:
    """Build a Mock matching the LitellmClient protocol: get(...) returns a
    response whose .json() is the given records."""
    client = Mock()
    response = Mock()
    response.json.return_value = records
    client.get.return_value = response
    return client


class TestIterSource:
    def test_adls_mode_lists_and_downloads_matching_day(self):
        day = date(2026, 3, 28)
        files = {
            "logs/2026/03/28/req-1.json": {"kwargs": {"standard_logging_object": {"id": "req-1"}}},
            "logs/2026/03/28/req-2.json": {"kwargs": {"standard_logging_object": {"id": "req-2"}}},
            "logs/2026/03/29/req-3.json": {"kwargs": {"standard_logging_object": {"id": "req-3"}}},
        }
        adls_fs = _fake_adls_fs(files)

        results = list(iter_source(day, "adls", adls_fs, None))

        adls_fs.list_blobs.assert_called_once_with(name_starts_with="logs/2026/03/28/")
        assert {r["request_id"] for r, _ in results} == {"req-1", "req-2"}
        assert all(source == "adls" for _, source in results)

    def test_adls_mode_ignores_non_json_blobs(self):
        day = date(2026, 3, 28)
        files = {
            "logs/2026/03/28/req-1.json": {"kwargs": {"standard_logging_object": {"id": "req-1"}}},
            "logs/2026/03/28/readme.txt": {},
        }
        adls_fs = _fake_adls_fs(files)

        results = list(iter_source(day, "adls", adls_fs, None))
        assert [r["request_id"] for r, _ in results] == ["req-1"]

    def test_litellm_mode_queries_correct_date_range(self):
        day = date(2026, 3, 28)
        records = [
            {"request_id": "r1", "proxy_server_request": {"messages": []}},
            {"request_id": "r2", "proxy_server_request": {"messages": []}},
        ]
        litellm_client = _fake_litellm_client(records)

        results = list(iter_source(day, "litellm", None, litellm_client))

        litellm_client.get.assert_called_once_with(
            "/spend/logs",
            params={"start_date": "2026-03-28", "end_date": "2026-03-29", "summarize": "false"},
        )
        assert [r["request_id"] for r, _ in results] == ["r1", "r2"]
        assert all(source == "litellm" for _, source in results)

    def test_auto_mode_uses_adls_when_files_exist(self):
        day = date(2026, 3, 28)
        adls_fs = _fake_adls_fs(
            {"logs/2026/03/28/req-1.json": {"kwargs": {"standard_logging_object": {"id": "req-1"}}}}
        )
        litellm_client = _fake_litellm_client([])

        results = list(iter_source(day, "auto", adls_fs, litellm_client))

        assert [r["request_id"] for r, _ in results] == ["req-1"]
        assert all(source == "adls" for _, source in results)
        litellm_client.get.assert_not_called()

    def test_auto_mode_falls_back_to_litellm_when_no_adls_files(self):
        day = date(2026, 3, 28)
        adls_fs = _fake_adls_fs({})  # no files for this day
        litellm_client = _fake_litellm_client(
            [{"request_id": "r1", "proxy_server_request": {"messages": []}}]
        )

        results = list(iter_source(day, "auto", adls_fs, litellm_client))

        adls_fs.list_blobs.assert_called_once_with(name_starts_with="logs/2026/03/28/")
        assert [r["request_id"] for r, _ in results] == ["r1"]
        assert all(source == "litellm" for _, source in results)

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="mode must be"):
            list(iter_source(date(2026, 3, 28), "bogus", None, None))

    def test_adls_mode_without_adls_fs_raises(self):
        with pytest.raises(ValueError, match="requires adls_fs"):
            list(iter_source(date(2026, 3, 28), "adls", None, None))

    def test_litellm_mode_without_client_raises(self):
        with pytest.raises(ValueError, match="requires litellm_client"):
            list(iter_source(date(2026, 3, 28), "litellm", None, None))
