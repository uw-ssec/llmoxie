"""Unit tests for data/reader.py."""

from __future__ import annotations

import logging

import pandas as pd
import pytest
from reader import (
    _parse_end_user,
    deduplicate_messages,
    last_request_per_session,
    load_messages_from_records,
    normalize_model_name,
)


class TestParseEndUser:
    def test_json_encoded_string(self):
        raw = '{"device_id": "abc", "account_uuid": "acc1", "session_id": "sess1"}'
        assert _parse_end_user(raw) == {
            "device_id": "abc",
            "account_uuid": "acc1",
            "session_id": "sess1",
        }

    def test_plain_dict(self):
        raw = {"device_id": "abc", "account_uuid": "acc1", "session_id": "sess1"}
        assert _parse_end_user(raw) == raw

    def test_regex_fallback_string(self):
        raw = "user_abc123_account_acc1_session_11111111-1111-1111-1111-111111111111"
        result = _parse_end_user(raw)
        assert result == {
            "device_id": "abc123",
            "account_uuid": "acc1",
            "session_id": "11111111-1111-1111-1111-111111111111",
        }

    def test_regex_fallback_empty_account(self):
        raw = "user_abc123_account__session_11111111-1111-1111-1111-111111111111"
        result = _parse_end_user(raw)
        assert result["account_uuid"] == ""
        assert result["session_id"] == "11111111-1111-1111-1111-111111111111"

    @pytest.mark.parametrize("raw", ["", None, "not a recognizable format", 42])
    def test_unparseable_returns_empty_and_warns(self, raw, caplog):
        with caplog.at_level(logging.WARNING):
            result = _parse_end_user(raw)
        assert result == {"device_id": "", "account_uuid": "", "session_id": ""}
        assert "Could not parse end_user" in caplog.text


class TestNormalizeModelName:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("bedrock/anthropic.claude-4-6-sonnet-20250929-v1:0", "claude-sonnet-4.6"),
            ("us.anthropic.claude-3-5-haiku-20241022-v1:0", "claude-haiku-3.5"),
            ("--model opus-4-6", "claude-opus-4.6"),
            (None, None),
            ("", ""),
        ],
    )
    def test_cases(self, raw, expected):
        assert normalize_model_name(raw) == expected


class TestLastRequestPerSession:
    def test_picks_request_with_most_input_messages(self):
        df = pd.DataFrame(
            [
                {
                    "session_id": "s1",
                    "request_id": "r1",
                    "start_time": "t1",
                    "direction": "input",
                    "msg_idx": 0,
                    "block_idx": 0,
                },
                {
                    "session_id": "s1",
                    "request_id": "r2",
                    "start_time": "t2",
                    "direction": "input",
                    "msg_idx": 1,
                    "block_idx": 0,
                },
                {
                    "session_id": "s1",
                    "request_id": "r2",
                    "start_time": "t2",
                    "direction": "output",
                    "msg_idx": None,
                    "block_idx": 0,
                },
            ]
        )
        result = last_request_per_session(df)
        assert set(result["request_id"]) == {"r2"}

    def test_ties_broken_by_latest_start_time(self):
        # Both requests have the same max msg_idx (0); r2 started later and should win.
        df = pd.DataFrame(
            [
                {
                    "session_id": "s1",
                    "request_id": "r1",
                    "start_time": "2026-01-01T00:00:00Z",
                    "direction": "input",
                    "msg_idx": 0,
                    "block_idx": 0,
                },
                {
                    "session_id": "s1",
                    "request_id": "r2",
                    "start_time": "2026-01-01T00:01:00Z",
                    "direction": "input",
                    "msg_idx": 0,
                    "block_idx": 0,
                },
            ]
        )
        result = last_request_per_session(df)
        assert set(result["request_id"]) == {"r2"}


class TestDeduplicateMessages:
    def test_keeps_earliest_input_and_all_output(self):
        df = pd.DataFrame(
            [
                # msg_idx 0 resent by two requests; earliest (t1) should win.
                {
                    "session_id": "s1",
                    "request_id": "r1",
                    "start_time": "t1",
                    "direction": "input",
                    "msg_idx": 0,
                    "block_idx": 0,
                },
                {
                    "session_id": "s1",
                    "request_id": "r2",
                    "start_time": "t2",
                    "direction": "input",
                    "msg_idx": 0,
                    "block_idx": 0,
                },
                {
                    "session_id": "s1",
                    "request_id": "r1",
                    "start_time": "t1",
                    "direction": "output",
                    "msg_idx": None,
                    "block_idx": 0,
                },
                {
                    "session_id": "s1",
                    "request_id": "r2",
                    "start_time": "t2",
                    "direction": "output",
                    "msg_idx": None,
                    "block_idx": 0,
                },
            ]
        )
        result = deduplicate_messages(df)
        input_rows = result[result["direction"] == "input"]
        assert len(input_rows) == 1
        assert input_rows.iloc[0]["request_id"] == "r1"
        # both output rows are kept (they're unique per request)
        assert len(result[result["direction"] == "output"]) == 2


class TestLoadMessagesFromRecords:
    def test_flattens_input_and_output(self):
        record = {
            "request_id": "r1",
            "startTime": "2026-01-01T00:00:00Z",
            "endTime": "2026-01-01T00:00:05Z",
            "end_user": "user_abc123_account_acc1_session_dead1",
            "model": "claude-sonnet-4-6",
            "spend": 0.01,
            "total_tokens": 100,
            "metadata": {"user_api_key_alias": "test-api"},
            "proxy_server_request": {
                "messages": [{"role": "user", "content": "hello"}]
            },
            "response": {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": [{"type": "text", "text": "hi there"}],
                        }
                    }
                ]
            },
        }
        df = load_messages_from_records([record])

        input_rows = df[df["direction"] == "input"]
        assert len(input_rows) == 1
        assert input_rows.iloc[0]["text"] == "hello"
        assert input_rows.iloc[0]["session_id"] == "dead1"

        output_rows = df[df["direction"] == "output"]
        assert len(output_rows) == 1
        assert output_rows.iloc[0]["text"] == "hi there"
        assert output_rows.iloc[0]["role"] == "assistant"

    def test_missing_response_choices_logs_warning_not_crash(self, caplog):
        record = {
            "request_id": "r1",
            "proxy_server_request": {
                "messages": [{"role": "user", "content": "hello"}]
            },
            "response": {
                "output": [{"type": "message"}]
            },  # Responses-API shape, no "choices"
        }
        with caplog.at_level(logging.WARNING):
            df = load_messages_from_records([record])

        assert "could not read response.choices" in caplog.text
        assert len(df[df["direction"] == "output"]) == 0
        assert len(df[df["direction"] == "input"]) == 1

    def test_no_input_or_output_logs_warning(self, caplog):
        record = {"request_id": "r1"}
        with caplog.at_level(logging.WARNING):
            df = load_messages_from_records([record])

        assert "yielded neither input nor output" in caplog.text
        assert df.empty
