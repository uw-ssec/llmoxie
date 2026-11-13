"""Unit tests for llmaven.ops.spend."""

from __future__ import annotations

from datetime import date

import pytest

from llmaven.ops.spend import (
    GroupBy,
    aggregate,
    baseline_window,
    compare,
    group_label,
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
            "steady": 12.0,  # below threshold
            "quiet": 0.0,  # no spend, no prior: not "new"
        }
        baseline = {"spiker": 10.0, "steady": 11.0, "gone": 50.0}

        rows = compare(current, baseline, threshold=2.0)

        # Rows come only from current, sorted by spend descending.
        assert [row.label for row in rows] == ["spiker", "newcomer", "steady", "quiet"]
        assert [row.flag for row in rows] == ["spike", "new", "", ""]
        assert [row.prior for row in rows] == [10.0, 0.0, 11.0, 0.0]
        assert rows[0].ratio == 2.0
        assert rows[1].ratio is None  # prior == 0, so no ratio
        assert rows[2].ratio == pytest.approx(12.0 / 11.0)
        assert rows[3].ratio is None

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
