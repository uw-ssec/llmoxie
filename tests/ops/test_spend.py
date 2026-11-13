"""Unit tests for llmaven.ops.spend."""

from __future__ import annotations

import csv
import json
import zipfile
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest
from rich.console import Console

from llmaven.ops import spend as spend_module
from llmaven.ops.spend import (
    CSV_COLUMNS,
    GroupBy,
    SpendFetchError,
    SpendRow,
    aggregate,
    baseline_window,
    compare,
    fetch_spend_records,
    group_label,
    iter_extract_records,
    record_day,
    render_table,
    write_csv,
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

    def test_zip_skips_macos_metadata_entries(self, tmp_path):
        """Finder-made archives carry AppleDouble entries that are not UTF-8."""
        record = {"startTime": "2026-03-01T01:00:00Z", "spend": 1.0}
        archive = tmp_path / "extract.zip"
        junk = b"\x00\x05\x16\x07\xff\xfe\x80 not utf-8"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("__MACOSX/._spend.jsonl", junk)
            zf.writestr("__MACOSX/spend/other.jsonl", junk)
            zf.writestr("spend/._litellm.jsonl", junk)
            zf.writestr("spend/litellm.jsonl", _jsonl([record]))

        assert list(iter_extract_records(archive)) == [record]


API_KEY = "sk-fetch-test-secret"
BASE_URL = "https://litellm.example.test"


def _record(day: date, index: int = 0) -> dict:
    return {
        "startTime": f"{day}T0{index % 10}:00:00Z",
        "spend": 1.0,
        "model": "gpt-4o",
    }


def _page_body(records: list[dict], **extra) -> dict:
    body = {
        "data": records,
        "total": len(records),
        "page": 1,
        "page_size": spend_module.PAGE_SIZE,
        "total_pages": 1,
        "total_is_capped": False,
    }
    body.update(extra)
    return body


class TestFetchSpendRecords:
    """`fetch_spend_records` against a mocked httpx transport."""

    def _client(self, handler) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler))

    def test_fetch_one_request_per_day(self):
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            day = date.fromisoformat(request.url.params["start_date"].split(" ")[0])
            return httpx.Response(200, json=_page_body([_record(day)]))

        start, end = date(2026, 3, 1), date(2026, 3, 3)
        with self._client(handler) as client:
            records = list(
                fetch_spend_records(
                    BASE_URL, API_KEY, start, end, client=client, sleep=lambda _: None
                )
            )

        assert len(requests) == 3
        assert len(records) == 3
        for offset, request in enumerate(requests):
            day = start + timedelta(days=offset)
            assert request.url.path == "/spend/logs/v2"
            assert request.url.params["start_date"] == f"{day} 00:00:00"
            assert (
                request.url.params["end_date"] == f"{day + timedelta(days=1)} 00:00:00"
            )
            assert request.url.params["page"] == "1"
            assert request.url.params["page_size"] == str(spend_module.PAGE_SIZE)
            assert request.headers["Authorization"] == f"Bearer {API_KEY}"

    def test_fetch_pages_until_short_page(self, monkeypatch):
        monkeypatch.setattr(spend_module, "PAGE_SIZE", 2)
        day = date(2026, 3, 1)
        pages = [[_record(day, 0), _record(day, 1)], [_record(day, 2)]]
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            page = int(request.url.params["page"])
            return httpx.Response(200, json={"data": pages[page - 1]})

        with self._client(handler) as client:
            records = list(
                fetch_spend_records(
                    BASE_URL, API_KEY, day, day, client=client, sleep=lambda _: None
                )
            )

        assert [request.url.params["page"] for request in requests] == ["1", "2"]
        assert records == pages[0] + pages[1]

    def test_fetch_ignores_capped_totals(self):
        day = date(2026, 3, 1)
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            body = _page_body(
                [_record(day)],
                total=10000,
                total_pages=10,
                total_is_capped=True,
            )
            return httpx.Response(200, json=body)

        with self._client(handler) as client:
            records = list(
                fetch_spend_records(
                    BASE_URL, API_KEY, day, day, client=client, sleep=lambda _: None
                )
            )

        assert len(requests) == 1
        assert len(records) == 1

    def test_fetch_drops_records_from_next_day(self):
        day = date(2026, 3, 1)
        keep = _record(day)
        # The upper bound is the next day's midnight, so the server may return
        # a record stamped exactly 00:00:00 on the following day.
        drop = {"startTime": "2026-03-02T00:00:00Z", "spend": 9.0, "model": "gpt-4o"}

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_page_body([keep, drop]))

        with self._client(handler) as client:
            records = list(
                fetch_spend_records(
                    BASE_URL, API_KEY, day, day, client=client, sleep=lambda _: None
                )
            )

        assert records == [keep]

    def test_fetch_retries_5xx_then_succeeds(self):
        day = date(2026, 3, 1)
        responses = [
            httpx.Response(503, text="upstream down"),
            httpx.Response(200, json=_page_body([_record(day)])),
        ]
        slept: list[float] = []

        def handler(request: httpx.Request) -> httpx.Response:
            return responses.pop(0)

        with self._client(handler) as client:
            records = list(
                fetch_spend_records(
                    BASE_URL, API_KEY, day, day, client=client, sleep=slept.append
                )
            )

        assert responses == []
        assert len(records) == 1
        assert slept == [2.0]

    @pytest.mark.parametrize(
        "body",
        [
            {"detail": "Internal Server Error"},
            {"data": {"not": "a list"}},
        ],
    )
    def test_fetch_bad_body_raises(self, body):
        day = date(2026, 3, 1)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=body)

        with self._client(handler) as client, pytest.raises(SpendFetchError) as excinfo:
            list(
                fetch_spend_records(
                    BASE_URL, API_KEY, day, day, client=client, sleep=lambda _: None
                )
            )

        message = str(excinfo.value)
        assert API_KEY not in message
        assert str(day) in message

    def test_fetch_transport_error_never_names_the_key(self):
        """A transport error's own text may quote the header; it is not shown."""
        day = date(2026, 3, 1)

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError(f"Illegal header value b'Bearer {API_KEY}'")

        with self._client(handler) as client, pytest.raises(SpendFetchError) as excinfo:
            list(
                fetch_spend_records(
                    BASE_URL, API_KEY, day, day, client=client, sleep=lambda _: None
                )
            )

        message = str(excinfo.value)
        assert API_KEY not in message
        assert "ConnectError" in message
        assert str(day) in message

    def test_fetch_4xx_raises_without_retry(self):
        day = date(2026, 3, 1)
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(401, json={"detail": "Invalid proxy key"})

        with self._client(handler) as client, pytest.raises(SpendFetchError) as excinfo:
            list(
                fetch_spend_records(
                    BASE_URL, API_KEY, day, day, client=client, sleep=lambda _: None
                )
            )

        assert len(requests) == 1
        assert API_KEY not in str(excinfo.value)

    def test_fetch_invalid_base_url_raises_without_the_key(self):
        """httpx.InvalidURL is not an HTTPError; it must not escape raw."""
        day = date(2026, 3, 1)

        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("no request should be sent")

        with self._client(handler) as client, pytest.raises(SpendFetchError) as excinfo:
            list(
                fetch_spend_records(
                    "https://litellm.example.test:notaport",
                    API_KEY,
                    day,
                    day,
                    client=client,
                    sleep=lambda _: None,
                )
            )

        message = str(excinfo.value)
        assert API_KEY not in message
        assert "notaport" not in message
        assert "invalid LiteLLM base URL" in message

    def test_fetch_stops_at_page_cap(self, monkeypatch):
        """A server that never returns a short page cannot loop forever."""
        monkeypatch.setattr(spend_module, "PAGE_SIZE", 2)
        day = date(2026, 3, 1)
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200, json={"data": [_record(day, 0), _record(day, 1)]}
            )

        with self._client(handler) as client, pytest.raises(SpendFetchError) as excinfo:
            list(
                fetch_spend_records(
                    BASE_URL,
                    API_KEY,
                    day,
                    day,
                    client=client,
                    sleep=lambda _: None,
                    max_pages_per_day=3,
                )
            )

        assert len(requests) == 3
        message = str(excinfo.value)
        assert str(day) in message
        assert "3" in message
        assert API_KEY not in message

    def test_default_page_cap(self):
        assert spend_module.MAX_PAGES_PER_DAY == 1000


class TestWriteCsv:
    def test_write_csv_columns_and_blanks(self, tmp_path):
        path = tmp_path / "spend.csv"
        write_csv(
            [
                SpendRow("alpha", 2.5, 1.0, 2.5, "spike"),
                SpendRow("beta", 1.0, None, None, ""),
            ],
            path,
        )

        rows = list(csv.reader(path.read_text(encoding="utf-8").splitlines()))
        assert rows[0] == list(CSV_COLUMNS)
        assert rows[1] == ["alpha", "2.5", "1.0", "2.5", "spike"]
        assert rows[2] == ["beta", "1.0", "", "", ""]

    def test_csv_has_no_raw_key(self, tmp_path):
        record = {"api_key": HASHED_KEY, "spend": 1.0}
        label = group_label(record, GroupBy.key)
        path = tmp_path / "spend.csv"

        write_csv([SpendRow(label, 1.0, None, None, "")], path)

        text = path.read_text(encoding="utf-8")
        assert HASHED_KEY not in text
        assert HASHED_KEY[:8] in text

    @pytest.mark.parametrize(
        "label",
        ['=HYPERLINK("x")', "+1", "-1", "@SUM(A1)", "\tcmd", "\rcmd"],
    )
    def test_csv_neutralises_formula_labels(self, tmp_path, label):
        path = tmp_path / "spend.csv"

        write_csv([SpendRow(label, -1.5, -2.0, 0.75, "")], path)

        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        # Only the text label is prefixed; numeric cells stay plain numbers.
        assert rows[1] == [f"'{label}", "-1.5", "-2.0", "0.75", ""]

    def test_csv_raw_key_label_is_unhashed_placeholder(self, tmp_path):
        """The sk- mapping happens in group_label, before write_csv sees it."""
        raw = "sk-raw-secret-key"
        label = group_label({"api_key": raw, "spend": 1.0}, GroupBy.key)
        path = tmp_path / "spend.csv"

        write_csv([SpendRow(label, 1.0, None, None, "")], path)

        text = path.read_text(encoding="utf-8")
        assert raw not in text
        assert "(unhashed key)" in text


class TestRenderTable:
    @staticmethod
    def _render(table) -> str:
        console = Console(record=True, width=120)
        console.print(table)
        return console.export_text()

    def test_render_table_top_and_total(self):
        rows = [
            SpendRow("alpha", 3.0, 1.0, 3.0, "spike"),
            SpendRow("beta", 2.0, None, None, "new"),
            SpendRow("gamma", 1.0, 1.0, 1.0, ""),
        ]

        text = self._render(render_table(rows, title="Spend", top=1))

        assert "alpha" in text
        assert "beta" not in text
        assert "gamma" not in text
        assert "6.00" in text

    def test_render_table_without_top_shows_every_row(self):
        rows = [
            SpendRow("alpha", 3.0, 1.0, 3.0, "spike"),
            SpendRow("beta", 2.0, None, None, "new"),
        ]

        text = self._render(render_table(rows, title="Spend report", top=None))

        assert "Spend report" in text
        assert "alpha" in text
        assert "beta" in text
        assert "5.00" in text

    @pytest.mark.parametrize("label", ["model[beta]", "a[bold]b", "team[/x]"])
    def test_render_table_shows_square_brackets_in_labels_verbatim(self, label):
        rows = [SpendRow(label, 1.0, None, None, "")]

        text = self._render(render_table(rows, title="Spend", top=None))

        assert label in text

    def test_render_table_shows_square_brackets_in_title_verbatim(self):
        title = "Spend by model[beta] [/x]"

        text = self._render(render_table([], title=title, top=None))

        assert title in text

    def test_render_table_empty_rows_totals_zero(self):
        assert "0.00" in self._render(render_table([], title="Spend", top=None))

    def test_render_table_top_zero_shows_only_total(self):
        rows = [SpendRow("alpha", 3.0, None, None, "")]

        text = self._render(render_table(rows, title="Spend", top=0))

        assert "alpha" not in text
        assert "3.00" in text

    def test_render_table_strips_control_characters_from_labels(self):
        rows = [SpendRow("\x1b]0;evil\x07alias", 1.0, None, None, "")]
        console = Console(record=True, width=120)

        console.print(render_table(rows, title="Spend", top=None))
        text = console.export_text(styles=False)

        assert "\x1b" not in text
        assert "\x07" not in text
        assert "]0;evilalias" in text
