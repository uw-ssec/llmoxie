"""Unit tests for llmaven.ops.spend."""

from __future__ import annotations

import json
import zipfile
from datetime import date
from pathlib import Path

import pytest

from llmaven.ops.spend import (
    GroupBy,
    aggregate,
    baseline_window,
    compare,
    group_label,
    iter_extract_records,
    record_day,
)

HASHED_KEY = "a" * 64


class TestRecordDay:
    @pytest.mark.parametrize(
        "start_time",
        [
            "2026-03-01T23:30:00Z",
            "2026-03-01T23:30:00+00:00",
            "2026-03-02T01:30:00+02:00",
            "2026-03-01T23:30:00",
        ],
    )
    def test_record_day_formats(self, start_time):
        assert record_day({"startTime": start_time}) == date(2026, 3, 1)

    @pytest.mark.parametrize("start_time", [None, "", "garbage"])
    def test_record_day_unparseable(self, start_time):
        assert record_day({"startTime": start_time}) is None

    def test_record_day_missing_field(self):
        assert record_day({}) is None


class TestGroupLabel:
    @pytest.mark.parametrize(
        ("record", "by", "expected"),
        [
            # key: alias first, then the three fallbacks
            (
                {
                    "metadata": {"user_api_key_alias": "ssec-prod"},
                    "api_key": HASHED_KEY,
                },
                GroupBy.key,
                "ssec-prod",
            ),
            ({"api_key": "sk-abcdef0123456789"}, GroupBy.key, "(unhashed key)"),
            ({"api_key": HASHED_KEY}, GroupBy.key, "key:aaaaaaaa"),
            ({"api_key": ""}, GroupBy.key, "(no key)"),
            ({}, GroupBy.key, "(no key)"),
            # user
            ({"user": "alice"}, GroupBy.user, "alice"),
            ({"user": ""}, GroupBy.user, "(no user)"),
            ({}, GroupBy.user, "(no user)"),
            # model
            ({"model": "gpt-4o"}, GroupBy.model, "gpt-4o"),
            ({"model": None}, GroupBy.model, "(no model)"),
            ({}, GroupBy.model, "(no model)"),
            # team: team_id, then the alias, then the fallback.  LiteLLM writes
            # team_id as "" when a request has no team (verified fact 1).
            ({"team_id": "team-123"}, GroupBy.team, "team-123"),
            (
                {"team_id": "", "metadata": {"user_api_key_team_alias": "research"}},
                GroupBy.team,
                "research",
            ),
            ({"team_id": "", "metadata": {}}, GroupBy.team, "(no team)"),
            ({}, GroupBy.team, "(no team)"),
        ],
    )
    def test_group_label(self, record, by, expected):
        assert group_label(record, by) == expected

    def test_group_label_never_contains_the_full_hash(self):
        label = group_label({"api_key": HASHED_KEY}, GroupBy.key)
        assert HASHED_KEY not in label
        assert len(label) < len(HASHED_KEY)


class TestAggregate:
    START = date(2026, 3, 8)
    END = date(2026, 3, 14)

    def _record(self, day: date, **extra):
        record = {"startTime": f"{day.isoformat()}T12:00:00Z", "user": "alice"}
        record.update(extra)
        return record

    def test_aggregate_window_and_missing_spend(self):
        records = [
            self._record(date(2026, 3, 7), spend=100.0),  # start - 1 day
            self._record(self.START, spend=1.5),
            self._record(self.END, spend=2.5),
            self._record(date(2026, 3, 15), spend=100.0),  # end + 1 day
            self._record(self.START, user="bob", spend=None),
            self._record(self.START, user="carol"),  # no spend key at all
            {"user": "dave", "spend": 9.0},  # no startTime at all
        ]
        assert aggregate(records, GroupBy.user, self.START, self.END) == {
            "alice": 4.0,
            "bob": 0.0,
            "carol": 0.0,
        }

    def test_aggregate_drops_unparseable_days(self):
        records = [
            {"startTime": "garbage", "user": "alice", "spend": 5.0},
            self._record(self.START, spend=1.0),
        ]
        assert aggregate(records, GroupBy.user, self.START, self.END) == {"alice": 1.0}


class TestBaselineWindow:
    @pytest.mark.parametrize(
        ("start", "end", "expected"),
        [
            # A seven-day report window looks back at the seven days before it.
            (date(2026, 3, 8), date(2026, 3, 14), (date(2026, 3, 1), date(2026, 3, 7))),
            # A single day looks back at the day before.
            (date(2026, 3, 8), date(2026, 3, 8), (date(2026, 3, 7), date(2026, 3, 7))),
        ],
    )
    def test_baseline_window(self, start, end, expected):
        assert baseline_window(start, end) == expected


class TestCompare:
    def test_compare_flags(self):
        current = {
            "spiker": 20.0,  # exactly threshold * prior
            "newcomer": 15.0,  # no baseline spend
            "zeroed": 13.0,  # in the baseline, but with a prior of exactly 0.0
            "steady": 12.0,  # below threshold
            "quiet": 0.0,  # no spend, no prior: not "new"
        }
        baseline = {"spiker": 10.0, "steady": 11.0, "zeroed": 0.0, "gone": 50.0}

        rows = compare(current, baseline, threshold=2.0)

        # Rows come only from current, sorted by spend descending.
        assert [row.label for row in rows] == [
            "spiker",
            "newcomer",
            "zeroed",
            "steady",
            "quiet",
        ]
        assert [row.flag for row in rows] == ["spike", "new", "new", "", ""]
        assert [row.prior for row in rows] == [10.0, 0.0, 0.0, 11.0, 0.0]
        assert rows[0].ratio == 2.0
        assert rows[1].ratio is None  # prior == 0, so no ratio
        assert rows[2].ratio is None  # prior of exactly 0.0 is still no ratio
        assert rows[3].ratio == pytest.approx(12.0 / 11.0)
        assert rows[4].ratio is None

    def test_compare_spike_at_decimal_boundary(self):
        # 134.01 == 3.0 * 44.67 exactly in binary floating point, but the
        # ratio rounds down to 2.9999999999999996, so comparing the ratio
        # against the threshold would miss this spike.
        rows = compare({"spiker": 134.01}, {"spiker": 44.67}, threshold=3.0)
        assert rows[0].flag == "spike"
        assert rows[0].ratio == pytest.approx(3.0)

    def test_compare_no_spike_just_under_decimal_boundary(self):
        # The reverse: the ratio rounds up to exactly 1.5 while the spend is
        # below 1.5 * 4.7, so comparing the ratio would flag a false spike.
        rows = compare({"creeper": 7.05}, {"creeper": 4.7}, threshold=1.5)
        assert rows[0].flag == ""

    def test_compare_sorts_ties_by_label(self):
        current = {"beta": 5.0, "alpha": 5.0, "gamma": 9.0}
        rows = compare(current, {}, threshold=2.0)
        assert [row.label for row in rows] == ["gamma", "alpha", "beta"]

    def test_compare_blank_baseline(self):
        rows = compare({"alice": 10.0, "bob": 0.0}, None, threshold=2.0)
        assert [row.label for row in rows] == ["alice", "bob"]
        assert all(row.prior is None for row in rows)
        assert all(row.ratio is None for row in rows)
        assert all(row.flag == "" for row in rows)

    def test_compare_empty_current(self):
        assert compare({}, {"alice": 1.0}, threshold=2.0) == []


DAY_ONE_RECORDS = [
    {"startTime": "2026-03-01T01:00:00Z", "spend": 1.0, "model": "gpt-4o"},
    {"startTime": "2026-03-01T02:00:00Z", "spend": 2.0, "model": "gpt-4o-mini"},
]
DAY_TWO_RECORDS = [
    {"startTime": "2026-03-02T03:00:00Z", "spend": 4.0, "model": "gpt-4o"},
]
ALL_RECORDS = DAY_ONE_RECORDS + DAY_TWO_RECORDS


def _jsonl(records: list[dict]) -> str:
    return "".join(f"{json.dumps(record)}\n" for record in records)


@pytest.fixture
def extract_dir(tmp_path: Path) -> Path:
    """A directory of two days of extract output, as `infra extract` writes it."""
    directory = tmp_path / "extract"
    directory.mkdir()
    (directory / "litellm_spend_logs_2026-03-01.jsonl").write_text(
        _jsonl(DAY_ONE_RECORDS), encoding="utf-8"
    )
    (directory / "litellm_spend_logs_2026-03-02.jsonl").write_text(
        _jsonl(DAY_TWO_RECORDS), encoding="utf-8"
    )
    return directory


class TestIterExtractRecords:
    def test_iter_extract_records_zip(self, tmp_path: Path, extract_dir: Path):
        archive = tmp_path / "llmaven_litellm_spend_logs.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            for path in sorted(extract_dir.iterdir()):
                zf.write(path, arcname=path.name)
        assert list(iter_extract_records(archive)) == ALL_RECORDS

    def test_iter_extract_records_directory(self, extract_dir: Path):
        assert list(iter_extract_records(extract_dir)) == ALL_RECORDS

    def test_iter_extract_records_single_file(self, extract_dir: Path):
        path = extract_dir / "litellm_spend_logs_2026-03-01.jsonl"
        assert list(iter_extract_records(path)) == DAY_ONE_RECORDS

    def test_iter_extract_records_skips_blank_lines(self, tmp_path: Path):
        path = tmp_path / "litellm_spend_logs_2026-03-01.jsonl"
        path.write_text(
            "\n"
            f"{json.dumps(DAY_ONE_RECORDS[0])}\n"
            "   \n"
            f"{json.dumps(DAY_ONE_RECORDS[1])}\n"
            "\n",
            encoding="utf-8",
        )
        assert list(iter_extract_records(path)) == DAY_ONE_RECORDS

    def test_iter_extract_records_skips_non_dict_lines(self, tmp_path: Path):
        path = tmp_path / "litellm_spend_logs_2026-03-01.jsonl"
        path.write_text(
            f"{json.dumps(DAY_ONE_RECORDS[0])}\n"
            "[1, 2, 3]\n"
            '"a string"\n'
            "null\n"
            f"{json.dumps(DAY_ONE_RECORDS[1])}\n",
            encoding="utf-8",
        )
        assert list(iter_extract_records(path)) == DAY_ONE_RECORDS

    def test_iter_extract_records_zip_ignores_other_entries(self, tmp_path: Path):
        archive = tmp_path / "mixed.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("litellm_spend_logs_2026-03-01.jsonl", _jsonl(DAY_ONE_RECORDS))
            zf.writestr("README.md", "not a record\n")
        assert list(iter_extract_records(archive)) == DAY_ONE_RECORDS

    def test_iter_extract_records_directory_ignores_other_files(
        self, extract_dir: Path
    ):
        (extract_dir / "notes.txt").write_text("not a record\n", encoding="utf-8")
        assert list(iter_extract_records(extract_dir)) == ALL_RECORDS

    def test_iter_extract_records_rejects_other_paths(self, tmp_path: Path):
        path = tmp_path / "spend.csv"
        path.write_text("label,spend\n", encoding="utf-8")
        with pytest.raises(ValueError):
            list(iter_extract_records(path))

    @pytest.mark.parametrize("separator", ["\u2028", "\u2029", "\u0085"])
    def test_iter_extract_records_keeps_unicode_line_separators(
        self, tmp_path: Path, separator: str
    ):
        """All three input shapes keep records whose content holds U+2028/9/85.

        `infra extract` writes with `ensure_ascii=False`, so these characters
        land raw inside strings. `str.splitlines()` would split on them, break
        the JSON and silently drop the record (and its spend).
        """
        record = {
            "startTime": "2026-03-01T01:00:00Z",
            "spend": 1.0,
            "model": "gpt-4o",
            "messages": f"line one{separator}line two",
        }
        payload = f"{json.dumps(record, ensure_ascii=False)}\n"

        directory = tmp_path / "extract"
        directory.mkdir()
        single = directory / "litellm_spend_logs_2026-03-01.jsonl"
        single.write_text(payload, encoding="utf-8", newline="")
        archive = tmp_path / "llmaven_litellm_spend_logs.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr(single.name, payload)

        assert list(iter_extract_records(archive)) == [record]
        assert list(iter_extract_records(directory)) == [record]
        assert list(iter_extract_records(single)) == [record]
