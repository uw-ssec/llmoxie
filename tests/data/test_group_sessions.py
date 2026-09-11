"""Unit and integration tests for llmaven.data.group_sessions."""

from __future__ import annotations

import json
import logging
import zipfile
from pathlib import Path

import pytest
from llmaven.data.group_sessions import (
    _iter_raw_records,
    _load_all,
    _sessions_to_flat_rows,
    build_sessions,
    main,
)

FIXTURES = Path(__file__).parent / "fixtures"


class TestIterRawRecords:
    def test_single_jsonl_file(self, tmp_path):
        p = tmp_path / "log.jsonl"
        p.write_text(json.dumps({"request_id": "r1"}) + "\n")
        records = list(_iter_raw_records(p))
        assert [r["request_id"] for r in records] == ["r1"]

    def test_empty_jsonl_file_yields_nothing(self, tmp_path):
        p = tmp_path / "empty.jsonl"
        p.write_text("")
        assert list(_iter_raw_records(p)) == []

    def test_empty_json_file_warns_and_skips_instead_of_crashing(
        self, tmp_path, caplog
    ):
        # Unlike an empty .jsonl file, json.load() raises on an empty file,
        # so this needs to be handled explicitly rather than left to "naturally
        # yield nothing".
        p = tmp_path / "empty.json"
        p.write_text("")
        with caplog.at_level(logging.WARNING):
            records = list(_iter_raw_records(p))
        assert records == []
        assert "Skipping unparsable" in caplog.text

    def test_single_adls_json_file_uses_filename_as_request_id(self, tmp_path):
        p = tmp_path / "req-abc.json"
        p.write_text(json.dumps({"kwargs": {"standard_logging_object": {}}}))
        records = list(_iter_raw_records(p))
        assert len(records) == 1
        assert records[0]["request_id"] == "req-abc"

    def test_directory_recurses_nested_date_folders(self, tmp_path):
        nested = tmp_path / "logs" / "2026" / "03" / "28"
        nested.mkdir(parents=True)
        (nested / "req-1.json").write_text(json.dumps({"kwargs": {}}))
        (tmp_path / "top.jsonl").write_text(json.dumps({"request_id": "r-top"}) + "\n")

        records = list(_iter_raw_records(tmp_path))
        request_ids = {r["request_id"] for r in records}
        assert "req-1" in request_ids
        assert "r-top" in request_ids

    def test_zip_reads_in_memory_without_leftover_files(self, tmp_path):
        zip_path = tmp_path / "data.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr(
                "litellm_spend_logs_2026-01-01.jsonl",
                json.dumps({"request_id": "r1"}) + "\n",
            )
            zf.writestr("logs/2026/01/01/req-2.json", json.dumps({"kwargs": {}}))

        before = set(tmp_path.iterdir())
        records = list(_iter_raw_records(zip_path))
        after = set(tmp_path.iterdir())

        assert {r["request_id"] for r in records} == {"r1", "req-2"}
        assert before == after  # nothing extracted to disk


class TestSessionsToFlatRows:
    def test_explodes_messages_to_one_row_per_block(self):
        sessions = [
            {
                "session_id": "s1",
                "n_requests": 2,
                "total_spend": 0.1,
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": "hi"}]},
                    {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": "sure"},
                            {
                                "type": "tool_use",
                                "id": "t1",
                                "name": "Bash",
                                "input": {"command": "ls"},
                            },
                        ],
                    },
                ],
            }
        ]
        rows = _sessions_to_flat_rows(sessions)
        assert len(rows) == 3
        assert (
            rows[0]["msg_idx"] == 0
            and rows[0]["role"] == "user"
            and rows[0]["text"] == "hi"
        )
        assert rows[2]["type"] == "tool_use" and rows[2]["tool_name"] == "Bash"
        assert json.loads(rows[2]["tool_input"]) == {"command": "ls"}
        # session-level fields repeated onto every row
        assert all(r["session_id"] == "s1" and r["n_requests"] == 2 for r in rows)


class TestBuildSessionsIntegration:
    """Uses tests/data/fixtures/test.jsonl: two real, hand-checked sessions
    extracted from the Jan-Mar 2026 dump (see data/README.md)."""

    @pytest.fixture(scope="class")
    def sessions(self):
        df = _load_all(FIXTURES / "test.jsonl")
        sessions, n_skipped = build_sessions(df)
        assert n_skipped == 0  # every record in this fixture has a session_id
        return {s["session_id"]: s for s in sessions}

    def test_two_sessions_found(self, sessions):
        assert set(sessions) == {
            "bb784243-3e0d-40d9-bc48-9568f4adc10b",
            "f7500aa9-8bc0-4165-a106-99b053224e03",
        }

    def test_venv_session_reconstructed_in_order(self, sessions):
        s = sessions["bb784243-3e0d-40d9-bc48-9568f4adc10b"]
        assert s["n_requests"] == 5
        roles = [m["role"] for m in s["messages"]]
        assert roles == ["user", "assistant", "user", "assistant", "user", "assistant"]
        # conversation starts with the user's actual request, not a stray reply
        assert s["messages"][0]["content"][0]["type"] == "text"
        # ends with the assistant's final reply
        assert s["messages"][-1]["role"] == "assistant"

    def test_numpy_session_tool_use_tool_result_pairing(self, sessions):
        s = sessions["f7500aa9-8bc0-4165-a106-99b053224e03"]
        assert s["n_requests"] == 12
        assert len(s["messages"]) == 10
        # every tool_use in an assistant message is answered by a tool_result
        # in the very next (user) message
        for i, m in enumerate(s["messages"][:-1]):
            tool_use_ids = [
                c["id"] for c in m["content"] if c.get("type") == "tool_use"
            ]
            if not tool_use_ids:
                continue
            next_msg = s["messages"][i + 1]
            result_ids = [c.get("tool_use_id") for c in next_msg["content"]]
            assert set(tool_use_ids) <= set(result_ids)

    def test_session_stats_are_positive(self, sessions):
        for s in sessions.values():
            assert s["total_spend"] > 0
            assert s["total_tokens"] > 0
            assert s["start_time"] < s["end_time"]


class TestMainRefusesToOverwriteOutput:
    def test_exits_if_output_already_exists(self, tmp_path, monkeypatch):
        existing_output = tmp_path / "sessions.jsonl"
        existing_output.write_text("not touching this\n")

        monkeypatch.setattr(
            "sys.argv",
            [
                "group_sessions.py",
                str(FIXTURES / "test.jsonl"),
                "-o",
                str(existing_output),
            ],
        )

        with pytest.raises(SystemExit, match="already exists"):
            main()

        # the pre-existing file must be untouched
        assert existing_output.read_text() == "not touching this\n"
