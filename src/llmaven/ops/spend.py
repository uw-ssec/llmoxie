"""spend.py — group and aggregate LiteLLM spend-log records.

The functions here are pure: they take raw record dicts as LiteLLM returns them
from ``/spend/logs/v2`` (or as ``llmaven infra extract`` writes them) and return
plain Python values. Nothing in this module touches the network or the console.

Per okf ``cli-output-data-safety``, no label ever carries a raw or whole API
key: ``api_key`` in spend logs is already a SHA-256 hash, and only a short
prefix of it is used.
"""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import Enum
from pathlib import Path

# How much of the hashed api_key goes into a label when the key has no alias.
KEY_LABEL_PREFIX_LEN = 8

# LiteLLM spend logs store a SHA-256 hash of the key, never the key itself. A
# value that still looks like a raw key is labelled, not shown.
RAW_KEY_PREFIX = "sk-"


class GroupBy(str, Enum):
    key = "key"
    user = "user"
    model = "model"
    team = "team"


def record_day(record: dict) -> date | None:
    """Return the UTC date of ``startTime``, or None if it is missing or bad.

    A naive timestamp is read as UTC; an aware one is converted to UTC first,
    so an offset that crosses midnight lands on the right day.
    """
    raw = record.get("startTime")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.date()
    return parsed.astimezone(UTC).date()


def _field(record: dict, name: str) -> str:
    """Return a non-empty top-level string field, or an empty string."""
    value = record.get(name)
    return value.strip() if isinstance(value, str) else ""


def _metadata_field(record: dict, name: str) -> str:
    """Return a non-empty string from the record's metadata, or an empty one."""
    metadata = record.get("metadata")
    if not isinstance(metadata, dict):
        return ""
    value = metadata.get(name)
    return value.strip() if isinstance(value, str) else ""


def _key_label(record: dict) -> str:
    """Label a record by its key: alias first, then a prefix of the hash."""
    alias = _metadata_field(record, "user_api_key_alias")
    if alias:
        return alias
    api_key = _field(record, "api_key")
    if not api_key:
        return "(no key)"
    if api_key.startswith(RAW_KEY_PREFIX):
        # Spend logs should only ever hold hashes; show nothing of a raw key.
        return "(unhashed key)"
    return f"key:{api_key[:KEY_LABEL_PREFIX_LEN]}"


def _team_label(record: dict) -> str:
    """Label a record by its team.

    LiteLLM's ``get_logging_payload`` writes ``team_id=""`` when a request has
    no team, so an empty string falls through like a missing value.
    """
    return (
        _field(record, "team_id")
        or _metadata_field(record, "user_api_key_team_alias")
        or "(no team)"
    )


def group_label(record: dict, by: GroupBy) -> str:
    """Return the label one record is grouped under for the given dimension."""
    if by is GroupBy.key:
        return _key_label(record)
    if by is GroupBy.team:
        return _team_label(record)
    return _field(record, by.value) or f"(no {by.value})"


def _record_spend(record: dict) -> float:
    """Return the record's spend in USD; a missing or bad value counts as 0."""
    try:
        return float(record.get("spend") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def aggregate(
    records: Iterable[dict],
    by: GroupBy,
    start: date,
    end: date,
) -> dict[str, float]:
    """Sum spend by label over the records whose UTC day falls in [start, end].

    Records without a usable ``startTime`` are dropped. A record inside the
    window with no spend still contributes its label, at 0.0.
    """
    totals: dict[str, float] = {}
    for record in records:
        day = record_day(record)
        if day is None or day < start or day > end:
            continue
        label = group_label(record, by)
        totals[label] = totals.get(label, 0.0) + _record_spend(record)
    return totals


@dataclass(frozen=True)
class SpendRow:
    """One label's spend in the report window, set against its baseline.

    ``prior`` and ``ratio`` are None when there is nothing to compare against:
    no baseline data at all, or no baseline spend for this label.
    """

    label: str
    spend: float
    prior: float | None
    ratio: float | None
    flag: str


def baseline_window(start: date, end: date) -> tuple[date, date]:
    """Return the window of the same length ending the day before ``start``."""
    n_days = (end - start).days + 1
    return start - timedelta(days=n_days), start - timedelta(days=1)


def compare(
    current: dict[str, float],
    baseline: dict[str, float] | None,
    threshold: float,
) -> list[SpendRow]:
    """Flag each label in ``current`` against its baseline spend.

    ``baseline=None`` means no baseline data was available, so every row comes
    back unflagged with blank comparison columns. Otherwise a label is ``new``
    when it spent in the report window and nothing in the baseline, and
    ``spike`` when its spend is at least ``threshold`` times its baseline
    spend. Rows come only from ``current``, sorted by spend descending and then
    by label.
    """
    rows: list[SpendRow] = []
    for label, spend in current.items():
        if baseline is None:
            rows.append(SpendRow(label, spend, None, None, ""))
            continue
        prior = baseline.get(label, 0.0)
        ratio: float | None = spend / prior if prior > 0 else None
        if prior > 0:
            # Compare against the product rather than the ratio: dividing
            # first can round across the threshold in either direction.
            flag = "spike" if spend >= threshold * prior else ""
        else:
            flag = "new" if spend > 0 else ""
        rows.append(SpendRow(label, spend, prior, ratio, flag))
    rows.sort(key=lambda row: (-row.spend, row.label))
    return rows


def _iter_jsonl_lines(lines: Iterable[str]) -> Iterator[dict]:
    """Yield one record dict per line, skipping blanks and non-object lines.

    A line that is blank, that is not valid JSON, or that decodes to anything
    other than an object is dropped. Nothing about a skipped line is logged:
    extract records carry prompt and response content.
    """
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            yield record


def iter_extract_records(path: Path) -> Iterator[dict]:
    """Yield spend-log records from ``llmaven infra extract`` output.

    ``path`` may be a ``.zip`` archive (every ``*.jsonl`` entry, in name
    order), a directory (every ``*.jsonl`` file in it, in name order) or a
    single ``.jsonl`` file. Anything else raises ``ValueError``.
    """
    if path.is_dir():
        for jsonl_path in sorted(path.glob("*.jsonl")):
            with jsonl_path.open(encoding="utf-8") as handle:
                yield from _iter_jsonl_lines(handle)
        return
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            for name in sorted(archive.namelist()):
                if not name.endswith(".jsonl"):
                    continue
                with archive.open(name) as entry:
                    # Iterate a text handle rather than decoding the whole
                    # entry and calling str.splitlines(): splitlines() also
                    # splits on U+2028/U+2029/U+0085, which extract writes raw
                    # inside record strings, which would break the JSON and
                    # silently drop the record.
                    yield from _iter_jsonl_lines(
                        io.TextIOWrapper(entry, encoding="utf-8")
                    )
        return
    if path.suffix == ".jsonl":
        with path.open(encoding="utf-8") as handle:
            yield from _iter_jsonl_lines(handle)
        return
    raise ValueError(
        f"Expected a .zip archive, a directory or a .jsonl file, got: {path}"
    )
