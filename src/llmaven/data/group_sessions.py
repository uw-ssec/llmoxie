"""group_sessions.py — turn raw LiteLLM spend-log requests into per-session conversations.

Each raw record is a single request/response pair, and re-sends the full
conversation history seen so far. This script groups those requests by
``session_id`` and reconstructs, for each session, the single full ordered
conversation (using the last/most-complete request in that session) plus
session-level stats (request count, spend, tokens, time span).

Usage
-----
    python -m llmaven.data.group_sessions path/to/jan-feb-march-2026.zip -o sessions.jsonl
    python -m llmaven.data.group_sessions path/to/adls/logs/ --format parquet

``path`` may be a single ``.jsonl`` file (the ``litellm_spend_logs_*.jsonl``
format from ``llmaven infra extract``), a single ``.json`` file (one request
per file, the ADLS format from ``adl_logger.py``), a directory containing
either (searched recursively, so nested ``<yyyy>/<mm>/<dd>/`` layouts work),
or a ``.zip`` of them.

Output defaults to JSONL, one JSON object per line, one line per session.
Pass ``--format parquet`` for a flat table instead (one row per message
block, session fields repeated per row):

    {
      "session_id": "...",
      "device_id": "...",
      "account_uuid": "...",
      "user_api_key_alias": "...",
      "models": ["claude-sonnet-4.6"],
      "n_requests": 4,
      "total_spend": 0.0192,
      "total_tokens": 1320,
      "start_time": "2026-03-28T02:46:57.632000Z",
      "end_time": "2026-03-28T02:51:10.221000Z",
      "messages": [
        {"role": "user", "content": [{"type": "text", "text": "..."}]},
        {"role": "assistant", "content": [{"type": "tool_use", "name": "...", "id": "...", "input": {...}}]},
        ...
      ]
    }
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import zipfile
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

import jsonlines
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from tqdm import tqdm

from .reader import (
    _parse_end_user,
    _rows_from_record,
    last_request_per_session,
    load_messages_from_records,
)

logger = logging.getLogger(__name__)


def _epoch_to_iso(ts: float | None) -> str | None:
    """Convert a Unix epoch timestamp to the same ISO-8601 string format
    used by the litellm_spend_logs JSONL export (e.g. "2026-01-02T23:41:18.414000Z")."""
    if ts is None:
        return None
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )


def _adls_record_to_spend_log_shape(record: dict, fallback_request_id: str) -> dict:
    """Adapt one ADLS per-request JSON record (see adl_logger.py) into the
    litellm spend-log record shape that reader.py's row-building expects.

    Sourced from ``kwargs["standard_logging_object"]``, litellm's own
    normalized per-request log object — verified against a real sample from
    the ``litellm-logs`` container (a GitHub Copilot / gpt-5.3-codex request
    via the Responses API), which has the same field names
    (``end_user``, ``messages``, ``model``, ``total_tokens``, ...) as the
    litellm_spend_logs JSONL export, just with epoch-float timestamps
    instead of ISO strings.

    Known gap: ``standard_logging_object["response"]`` keeps the raw
    provider-shaped response. For Chat Completions calls that's the
    ``{"choices": [...]}`` shape reader.py already parses. For Responses-API
    calls (``call_type == "responses"``, seen from Copilot/gpt-5.3-codex
    traffic) the reply is shaped as ``{"output": [...]}`` instead, which
    reader.py does not yet parse — reader.py logs a warning and the
    session's messages simply won't include that request's final reply.
    Follow-up work if Responses-API output needs to be included.
    """
    kw = record.get("kwargs") or {}
    slo = kw.get("standard_logging_object") or {}
    metadata = slo.get("metadata") or {}

    return {
        "request_id": slo.get("id") or fallback_request_id,
        "startTime": _epoch_to_iso(slo.get("startTime")),
        "endTime": _epoch_to_iso(slo.get("endTime")),
        "end_user": slo.get("end_user"),
        "model": slo.get("model"),
        "spend": slo.get("response_cost"),
        "total_tokens": slo.get("total_tokens"),
        "api_key": metadata.get("user_api_key_hash"),
        "metadata": {"user_api_key_alias": metadata.get("user_api_key_alias")},
        "proxy_server_request": {"messages": slo.get("messages") or []},
        "response": slo.get("response") or {},
    }


def _iter_raw_records(input_path: Path) -> Iterable[dict]:
    """Yield raw record dicts from a file, directory, or zip.

    Supports ``.jsonl`` (the ``litellm_spend_logs_*.jsonl`` format from
    ``llmaven infra extract``) and individual ``.json`` files (one request
    per file, the ADLS format written by ``adl_logger.py``, e.g.
    ``logs/<yyyy>/<mm>/<dd>/<request_id>.json``). A directory is searched
    recursively so that nested date folders are picked up. Zip members are
    read directly from the archive without extracting to disk.
    """
    if input_path.is_dir():
        for p in sorted(input_path.rglob("*")):
            if p.suffix in (".jsonl", ".json"):
                yield from _iter_raw_records(p)
    elif input_path.suffix == ".zip":
        with zipfile.ZipFile(input_path) as zf:
            for name in sorted(zf.namelist()):
                if name.endswith(".jsonl"):
                    with zf.open(name) as fh:
                        with jsonlines.Reader(
                            io.TextIOWrapper(fh, encoding="utf-8")
                        ) as reader:
                            yield from reader
                elif name.endswith(".json"):
                    yield from _load_adls_json(zf.open(name), name)
    elif input_path.suffix == ".jsonl":
        # An empty .jsonl file just yields no records below; no special-casing needed.
        with jsonlines.open(input_path) as reader:
            yield from reader
    elif input_path.suffix == ".json":
        with open(input_path, "rb") as f:
            yield from _load_adls_json(f, str(input_path))
    else:
        logger.warning("Skipping file with unrecognized extension: %s", input_path)


def _load_adls_json(fh, name: str) -> Iterable[dict]:
    """Parse one ADLS .json file, skipping (with a warning) if it's empty or corrupt.

    Unlike an empty .jsonl file, json.load() raises on an empty/corrupt file
    rather than quietly yielding nothing, so this needs an explicit guard.
    """
    try:
        record = json.load(fh)
    except json.JSONDecodeError as exc:
        logger.warning("Skipping unparsable ADLS json file %s: %s", name, exc)
        return
    yield _adls_record_to_spend_log_shape(record, Path(name).stem)


def _load_all(input_path: Path) -> pd.DataFrame:
    """Load every raw record under input_path into one tidy DataFrame."""
    records = list(_iter_raw_records(input_path))
    if not records:
        return pd.DataFrame()
    return load_messages_from_records(records)


def _block_to_content(row: pd.Series) -> dict:
    """Convert one flattened block row back into an Anthropic-style content block."""
    if row["type"] == "text":
        return {"type": "text", "text": row["text"]}
    if row["type"] == "thinking":
        return {"type": "thinking", "thinking": row["thinking"]}
    if row["type"] == "tool_use":
        try:
            tool_input = json.loads(row["tool_input"]) if row["tool_input"] else None
        except (json.JSONDecodeError, TypeError):
            tool_input = row["tool_input"]
        return {
            "type": "tool_use",
            "id": row["tool_use_id"],
            "name": row["tool_name"],
            "input": tool_input,
        }
    # Fallback for any other block type (e.g. tool_result), row["text"] holds
    # the JSON-serialised block from reader.py's fallback path.
    if row["text"] is not None:
        try:
            return json.loads(row["text"])
        except (json.JSONDecodeError, TypeError):
            pass
    return {"type": row["type"]}


def _blocks_to_message(block_rows: pd.DataFrame) -> dict:
    """Merge a group of same-message block rows into one {role, content} message."""
    role = block_rows["role"].iloc[0]
    content = [_block_to_content(row) for _, row in block_rows.iterrows()]
    return {"role": role, "content": content}


def _reconstruct_conversation(last_request_rows: pd.DataFrame) -> list[dict]:
    """Reconstruct one session's ordered message list from its last request.

    The last (most complete) request already resent the full input history,
    so its input blocks in msg_idx order are the conversation so far; its
    output blocks are the final assistant turn.
    """
    messages = []
    input_rows = last_request_rows[
        last_request_rows["direction"] == "input"
    ].sort_values(["msg_idx", "block_idx"])
    for _, block_rows in input_rows.groupby("msg_idx", sort=True):
        messages.append(_blocks_to_message(block_rows))

    output_rows = last_request_rows[
        last_request_rows["direction"] == "output"
    ].sort_values("block_idx")
    if not output_rows.empty:
        messages.append(_blocks_to_message(output_rows))

    return messages


def build_sessions(df: pd.DataFrame) -> tuple[list[dict], int]:
    """Group a raw messages DataFrame into per-session conversation records.

    Parameters
    ----------
    df:
        DataFrame produced by :func:`reader.load_messages`, concatenated
        across all input files.

    Returns
    -------
    (sessions, n_requests_skipped)
        ``sessions`` is a list of per-session dicts ready to serialise to
        JSONL. ``n_requests_skipped`` is the count of requests with no
        ``session_id`` that could not be grouped.
    """
    raw_input_df = df[df["direction"] == "input"]
    n_requests_skipped = raw_input_df.loc[
        raw_input_df["session_id"] == "", "request_id"
    ].nunique()

    # Keep the raw (non-deduped) data: last_request_per_session needs each
    # request's own full resent history intact. deduplicate_messages would
    # strip most of that history away, attributing each message to whichever
    # request first introduced it rather than the request we're about to pick.
    df = df[df["session_id"] != ""]
    input_df = df[df["direction"] == "input"]

    per_request = input_df.drop_duplicates(subset=["session_id", "request_id"])
    stats = per_request.groupby("session_id").agg(
        device_id=("device_id", "first"),
        account_uuid=("account_uuid", "first"),
        user_api_key_alias=("user_api_key_alias", "first"),
        n_requests=("request_id", "nunique"),
        total_spend=("spend", "sum"),
        total_tokens=("total_tokens", "sum"),
        start_time=("start_time", "min"),
        end_time=("end_time", "max"),
    )
    models = per_request.groupby("session_id")["model"].apply(
        lambda s: sorted(set(s.dropna()))
    )

    last_df = last_request_per_session(df)

    sessions = []
    for session_id, group in last_df.groupby("session_id"):
        row = stats.loc[session_id]
        sessions.append(
            {
                "session_id": session_id,
                "device_id": row["device_id"],
                "account_uuid": row["account_uuid"],
                "user_api_key_alias": row["user_api_key_alias"],
                "models": models.loc[session_id],
                "n_requests": int(row["n_requests"]),
                "total_spend": float(row["total_spend"])
                if pd.notna(row["total_spend"])
                else None,
                "total_tokens": int(row["total_tokens"])
                if pd.notna(row["total_tokens"])
                else None,
                "start_time": row["start_time"],
                "end_time": row["end_time"],
                "messages": _reconstruct_conversation(group),
            }
        )

    sessions.sort(key=lambda s: s["start_time"] or "")
    return sessions, int(n_requests_skipped)


def _sessions_to_flat_rows(sessions: list[dict]) -> list[dict]:
    """Explode session records into one flat row per message content block.

    Same row shape as the block-level DataFrame ``_load_all`` produces (one
    row = one block), but built from the reconstructed session messages
    rather than raw request rows, with session-level fields (spend, tokens,
    time span, ...) repeated onto every row. Meant as an alternative,
    non-nested output format for tools that work better with flat tables
    (e.g. loading into a DataFrame or parquet) than with nested JSON.
    """
    rows = []
    for session in sessions:
        session_meta = {k: v for k, v in session.items() if k != "messages"}
        if isinstance(session_meta.get("models"), list):
            session_meta["models"] = ", ".join(session_meta["models"])

        for msg_idx, message in enumerate(session["messages"]):
            for block_idx, block in enumerate(message["content"]):
                row = {
                    **session_meta,
                    "msg_idx": msg_idx,
                    "role": message["role"],
                    "block_idx": block_idx,
                    "type": block.get("type"),
                    "text": None,
                    "thinking": None,
                    "tool_name": None,
                    "tool_input": None,
                    "tool_use_id": None,
                }
                if block.get("type") == "text":
                    row["text"] = block.get("text")
                elif block.get("type") == "thinking":
                    row["thinking"] = block.get("thinking")
                elif block.get("type") == "tool_use":
                    row["tool_name"] = block.get("name")
                    row["tool_use_id"] = block.get("id")
                    input_val = block.get("input")
                    row["tool_input"] = (
                        json.dumps(input_val) if input_val is not None else None
                    )
                else:
                    row["text"] = json.dumps(block)
                rows.append(row)
    return rows


_PARQUET_COLS = (
    "request_id",
    "session_id",
    "direction",
    "msg_idx",
    "block_idx",
    "role",
    "type",
    "text",
    "thinking",
    "tool_name",
    "tool_input",
    "tool_use_id",
)

# Explicit schema prevents PyArrow from inferring `null` type for columns whose
# first batch happens to contain only None values (e.g. thinking, tool_name).
_PARQUET_SCHEMA = pa.schema(
    [
        pa.field("request_id", pa.string()),
        pa.field("session_id", pa.string()),
        pa.field("direction", pa.string()),
        pa.field("msg_idx", pa.int64()),
        pa.field("block_idx", pa.int64()),
        pa.field("role", pa.string()),
        pa.field("type", pa.string()),
        pa.field("text", pa.string()),
        pa.field("thinking", pa.string()),
        pa.field("tool_name", pa.string()),
        pa.field("tool_input", pa.string()),
        pa.field("tool_use_id", pa.string()),
    ]
)

_PARQUET_BATCH_SIZE = 10_000


def _stream_to_parquet(
    input_path: Path,
    parquet_path: Path,
) -> tuple[dict, set[str], int]:
    """Stream all records from input_path into a compact Parquet file.

    Accumulates per-session stats in memory (O(n_sessions)) without building a
    full block-level DataFrame.  Writes only the 12 columns needed for session
    reconstruction to the Parquet — all other columns go into the returned
    session_stats dict.

    Returns
    -------
    (session_stats, last_request_ids, n_skipped)
        session_stats maps session_id → aggregated stats dict.
        last_request_ids is the set of request_ids that are the "last" (longest
        input history, tie-broken by start_time) for their session.
        n_skipped is the count of records with an unparsable session_id.
    """
    session_stats: dict[str, dict] = {}
    n_skipped = 0
    n_no_content = 0

    writer = pq.ParquetWriter(parquet_path, _PARQUET_SCHEMA, compression="snappy")
    batch: list[dict] = []

    def _flush(final: bool = False) -> None:
        nonlocal batch
        if not batch:
            return
        arrays = {col: [row.get(col) for row in batch] for col in _PARQUET_COLS}
        table = pa.table(arrays, schema=_PARQUET_SCHEMA)
        writer.write_table(table)
        batch = []

    # Suppress per-record reader warnings during streaming; count and report in aggregate.
    # Use __module__ rather than a hard-coded name so it works regardless of how the
    # package was imported (e.g. 'llmaven.data.reader' vs 'src.llmaven.data.reader').
    _reader_logger = logging.getLogger(_rows_from_record.__module__)
    _saved_level = _reader_logger.level
    _reader_logger.setLevel(logging.ERROR)
    try:
        for record in tqdm(
            _iter_raw_records(input_path), unit="rec", desc="Pass 1: scanning"
        ):
            eu = _parse_end_user(record.get("end_user"))
            session_id = eu["session_id"] or record.get("session_id")

            if not session_id:
                n_skipped += 1
                continue

            request_id = record.get("request_id") or ""
            start_time = record.get("startTime") or ""
            end_time = record.get("endTime") or ""
            spend = record.get("spend") or 0.0
            total_tokens = record.get("total_tokens") or 0
            model = record.get("model")
            metadata = record.get("metadata") or {}
            alias = metadata.get("user_api_key_alias")
            n_messages = len(
                (record.get("proxy_server_request") or {}).get("messages") or []
            )

            if session_id not in session_stats:
                session_stats[session_id] = {
                    "device_id": eu["device_id"],
                    "account_uuid": eu["account_uuid"],
                    "user_api_key_alias": alias,
                    "n_requests": 1,
                    "total_spend": spend,
                    "total_tokens": total_tokens,
                    "start_time": start_time,
                    "end_time": end_time,
                    "models": {model} if model else set(),
                    "_best_request_id": request_id,
                    "_best_n_messages": n_messages,
                    "_best_start_time": start_time,
                }
            else:
                s = session_stats[session_id]
                s["n_requests"] += 1
                s["total_spend"] += spend
                s["total_tokens"] += total_tokens
                if start_time and (not s["start_time"] or start_time < s["start_time"]):
                    s["start_time"] = start_time
                if end_time and end_time > s["end_time"]:
                    s["end_time"] = end_time
                if model:
                    s["models"].add(model)
                if n_messages > s["_best_n_messages"] or (
                    n_messages == s["_best_n_messages"]
                    and start_time > s["_best_start_time"]
                ):
                    s["_best_request_id"] = request_id
                    s["_best_n_messages"] = n_messages
                    s["_best_start_time"] = start_time

            block_rows = _rows_from_record(
                record, include_thinking=True, include_tool_use=True
            )
            if not block_rows:
                n_no_content += 1
            for row in block_rows:
                batch.append({col: row.get(col) for col in _PARQUET_COLS})
                if len(batch) >= _PARQUET_BATCH_SIZE:
                    _flush()

    finally:
        _reader_logger.setLevel(_saved_level)

    _flush(final=True)
    writer.close()

    if n_no_content:
        logger.info(
            "%d records yielded no content blocks (empty messages or Responses-API format)",
            n_no_content,
        )

    last_request_ids = {s["_best_request_id"] for s in session_stats.values()}
    return session_stats, last_request_ids, n_skipped


def _build_sessions_from_parquet(
    parquet_path: Path,
    session_stats: dict,
    last_request_ids: set[str],
) -> list[dict]:
    """Read the block Parquet, reconstruct one session record per session_id.

    Filters to last-request rows in memory, then calls _reconstruct_conversation
    for each session and merges with the pre-computed session_stats.
    """
    df = pd.read_parquet(parquet_path)
    df = df[df["request_id"].isin(last_request_ids)]

    sessions = []
    for session_id, group in tqdm(
        df.groupby("session_id"),
        total=len(session_stats),
        unit="session",
        desc="Pass 2: building sessions",
    ):
        s = session_stats.get(session_id)
        if s is None:
            continue
        sessions.append(
            {
                "session_id": session_id,
                "device_id": s["device_id"],
                "account_uuid": s["account_uuid"],
                "user_api_key_alias": s["user_api_key_alias"],
                "models": sorted(m for m in s["models"] if m),
                "n_requests": s["n_requests"],
                "total_spend": float(s["total_spend"]) if s["total_spend"] else None,
                "total_tokens": int(s["total_tokens"]) if s["total_tokens"] else None,
                "start_time": s["start_time"],
                "end_time": s["end_time"],
                "messages": _reconstruct_conversation(group),
            }
        )

    sessions.sort(key=lambda s: s["start_time"] or "")
    return sessions


def main() -> None:
    """CLI entry point: parse args, load the input, build sessions, write the output."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "input",
        type=Path,
        help=(
            "Raw data: a .jsonl file, a .json file, a directory of either "
            "(searched recursively), or a .zip of them"
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output path (default: sessions.jsonl or sessions.parquet, depending on --format)",
    )
    parser.add_argument(
        "--format",
        choices=["jsonl", "parquet"],
        default="jsonl",
        help="Output format: jsonl (one nested session per line) or parquet (flat, one row per message block)",
    )
    parser.add_argument(
        "--parquet-cache",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Path for the intermediate block Parquet kept after pass 1 "
            "(default: <output>.blocks.parquet).  If the file already exists, "
            "pass 1 is skipped and the cached Parquet is reused "
            "(a <PATH>.stats.json sidecar must also exist)."
        ),
    )
    args = parser.parse_args()
    output = args.output or Path(f"sessions.{args.format}")
    if output.exists():
        raise SystemExit(
            f"{output} already exists, pass a different -o/--output to avoid overwriting it"
        )

    use_streaming = args.input.suffix == ".jsonl"

    if use_streaming:
        parquet_path = args.parquet_cache or output.with_suffix(".blocks.parquet")
        stats_path = parquet_path.with_suffix(parquet_path.suffix + ".stats.json")

        if parquet_path.exists():
            if not stats_path.exists():
                raise SystemExit(
                    f"Parquet cache found at {parquet_path} but sidecar {stats_path} is missing"
                )
            logger.info("Reusing cached Parquet at %s", parquet_path)
            with open(stats_path) as f:
                raw_stats = json.load(f)
            session_stats = {
                sid: {**s, "models": set(s["models"])}
                for sid, s in raw_stats["sessions"].items()
            }
            last_request_ids = {s["_best_request_id"] for s in session_stats.values()}
            n_skipped = raw_stats.get("n_skipped", 0)
        else:
            session_stats, last_request_ids, n_skipped = _stream_to_parquet(
                args.input, parquet_path
            )
            serialisable = {
                "n_skipped": n_skipped,
                "sessions": {
                    sid: {**s, "models": sorted(s["models"])}
                    for sid, s in session_stats.items()
                },
            }
            with open(stats_path, "w") as f:
                json.dump(serialisable, f)
            logger.info("Saved Parquet at %s", parquet_path)

        logger.info("Scanning complete: %d sessions found", len(session_stats))
        if not session_stats:
            raise SystemExit(
                "No sessions found — all records had an unparsable or missing end_user field. "
                f"({n_skipped} records skipped)"
            )

        sessions = _build_sessions_from_parquet(
            parquet_path, session_stats, last_request_ids
        )
    else:
        df = _load_all(args.input)
        if df.empty:
            raise SystemExit(f"No records found at {args.input}")
        n_requests = df.loc[df["direction"] == "input", "request_id"].nunique()
        logger.info("Loaded %d requests from %s", n_requests, args.input)
        sessions, n_skipped = build_sessions(df)

    if args.format == "jsonl":
        with jsonlines.open(output, mode="w") as writer:
            for record in sessions:
                writer.write(record)
    else:
        pd.DataFrame(_sessions_to_flat_rows(sessions)).to_parquet(output, index=False)

    logger.info("Wrote %d sessions to %s", len(sessions), output)
    if n_skipped:
        logger.info(
            "Skipped %d requests with no session_id (could not be grouped)", n_skipped
        )


if __name__ == "__main__":
    main()
