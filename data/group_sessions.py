"""group_sessions.py — turn raw LiteLLM spend-log requests into per-session conversations.

Each raw record is a single request/response pair, and re-sends the full
conversation history seen so far. This script groups those requests by
``session_id`` and reconstructs, for each session, the single full ordered
conversation (using the last/most-complete request in that session) plus
session-level stats (request count, spend, tokens, time span).

Usage
-----
    python data/group_sessions.py path/to/jan-feb-march-2026.zip -o sessions.jsonl
    python data/group_sessions.py path/to/adls/logs/ --format parquet

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
from reader import last_request_per_session, load_messages_from_records

logger = logging.getLogger(__name__)


def _epoch_to_iso(ts: float | None) -> str | None:
    """Convert a Unix epoch timestamp to the same ISO-8601 string format
    used by the litellm_spend_logs JSONL export (e.g. "2026-01-02T23:41:18.414000Z")."""
    if ts is None:
        return None
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


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
                        with jsonlines.Reader(io.TextIOWrapper(fh, encoding="utf-8")) as reader:
                            yield from reader
                elif name.endswith(".json"):
                    with zf.open(name) as fh:
                        record = json.load(fh)
                    yield _adls_record_to_spend_log_shape(record, Path(name).stem)
    elif input_path.suffix == ".jsonl":
        if input_path.stat().st_size == 0:
            return
        with jsonlines.open(input_path) as reader:
            yield from reader
    elif input_path.suffix == ".json":
        if input_path.stat().st_size == 0:
            return
        with open(input_path) as f:
            record = json.load(f)
        yield _adls_record_to_spend_log_shape(record, input_path.stem)
    else:
        logger.warning("Skipping file with unrecognized extension: %s", input_path)


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
                    row["tool_input"] = json.dumps(input_val) if input_val is not None else None
                else:
                    row["text"] = json.dumps(block)
                rows.append(row)
    return rows


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
    args = parser.parse_args()
    output = args.output or Path(f"sessions.{args.format}")

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
        logger.info("Skipped %d requests with no session_id (could not be grouped)", n_skipped)


if __name__ == "__main__":
    main()
