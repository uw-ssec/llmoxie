"""reader.py — flatten LiteLLM spend-log JSONL files into a tidy DataFrame.

Each row in the output corresponds to one content block within a message
(or the entire message content when it is a plain string).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import jsonlines
import pandas as pd


def _parse_end_user(raw: Any) -> dict[str, str]:
    """Return device_id/account_uuid/session_id from the end_user field.

    The field is usually a JSON-encoded string but may already be a dict
    or missing entirely.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            m = re.fullmatch(
                r"user_(?P<device_id>[0-9a-f]*)_account_(?P<account_uuid>.*?)_session_(?P<session_id>[0-9a-f-]+)",
                raw,
            )
            if m:
                return m.groupdict()
    if isinstance(raw, dict):
        return {
            "device_id": raw.get("device_id", ""),
            "account_uuid": raw.get("account_uuid", ""),
            "session_id": raw.get("session_id", ""),
        }
    return {"device_id": "", "account_uuid": "", "session_id": ""}


def _base_row(record: dict) -> dict:
    """Extract record-level metadata shared by every block row."""
    eu = _parse_end_user(record.get("end_user"))
    metadata = record.get("metadata") or {}
    return {
        "request_id": record.get("request_id"),
        "start_time": record.get("startTime"),
        "device_id": eu["device_id"],
        "account_uuid": eu["account_uuid"],
        "session_id": eu["session_id"],
        "model": record.get("model"),
        "spend": record.get("spend"),
        "total_tokens": record.get("total_tokens"),
        "user_api_key": record.get("api_key"),
        "user_api_key_alias": metadata.get("user_api_key_alias"),
    }


def _rows_from_block(
    base: dict,
    direction: str,
    msg_idx: int | None,
    role: str,
    block_idx: int,
    block: dict | str,
    *,
    include_thinking: bool,
    include_tool_use: bool,
) -> list[dict]:
    """Convert one content block into zero or one row dicts."""
    if isinstance(block, str):
        return [
            {
                **base,
                "direction": direction,
                "msg_idx": msg_idx,
                "block_idx": block_idx,
                "role": role,
                "type": "text",
                "text": block,
                "thinking": None,
                "tool_name": None,
                "tool_input": None,
                "tool_use_id": None,
                "cache_control": None,
            }
        ]

    btype = block.get("type", "unknown")

    if btype == "thinking" and not include_thinking:
        return []
    if btype == "tool_use" and not include_tool_use:
        return []

    cache = block.get("cache_control")
    cache_control = cache.get("type") if isinstance(cache, dict) else None

    row = {
        **base,
        "direction": direction,
        "msg_idx": msg_idx,
        "block_idx": block_idx,
        "role": role,
        "type": btype,
        "text": None,
        "thinking": None,
        "tool_name": None,
        "tool_input": None,
        "tool_use_id": None,
        "cache_control": cache_control,
    }

    if btype == "text":
        row["text"] = block.get("text")
    elif btype == "thinking":
        row["thinking"] = block.get("thinking")
    elif btype == "tool_use":
        row["tool_name"] = block.get("name")
        row["tool_use_id"] = block.get("id")
        input_val = block.get("input")
        row["tool_input"] = json.dumps(input_val) if input_val is not None else None
    else:
        # Fallback: serialise unknown block types so no data is lost
        row["text"] = json.dumps(block)

    return [row]


def load_messages(
    path: str | Path,
    *,
    include_thinking: bool = False,
    include_tool_use: bool = True,
) -> pd.DataFrame:
    """Read a LiteLLM spend log JSONL file and return a tidy DataFrame.

    Each row corresponds to one content block within a message.  Both the
    input conversation (``proxy_server_request.messages``) and the model
    output (``response.choices[0].message``) are included, distinguished by
    the ``direction`` column (``"input"`` / ``"output"``).

    Parameters
    ----------
    path:
        Path to the ``.jsonl`` file.
    include_thinking:
        If *False* (default), blocks with ``type="thinking"`` are dropped.
    include_tool_use:
        If *False*, blocks with ``type="tool_use"`` are dropped.

    Returns
    -------
    pd.DataFrame
        Columns: request_id, start_time, device_id, account_uuid, session_id,
        model, spend, total_tokens, user_api_key, user_api_key_alias,
        direction, msg_idx, block_idx, role, type, text, thinking, tool_name,
        tool_input, tool_use_id, cache_control.
    """
    rows: list[dict] = []
    kwargs = {
        "include_thinking": include_thinking,
        "include_tool_use": include_tool_use,
    }

    with jsonlines.open(Path(path)) as reader:
        for record in reader:
            base = _base_row(record)

            # ── Input messages ────────────────────────────────────────────
            messages = record.get("proxy_server_request", {}).get("messages", [])
            for msg_idx, message in enumerate(messages):
                role = message.get("role", "")
                content = message.get("content", "")

                if isinstance(content, str):
                    rows.extend(
                        _rows_from_block(
                            base, "input", msg_idx, role, 0, content, **kwargs
                        )
                    )
                elif isinstance(content, list):
                    for block_idx, block in enumerate(content):
                        rows.extend(
                            _rows_from_block(
                                base, "input", msg_idx, role, block_idx, block, **kwargs
                            )
                        )

            # ── Output message ────────────────────────────────────────────
            try:
                out_msg = record["response"]["choices"][0]["message"]
            except (KeyError, IndexError, TypeError):
                out_msg = None

            if out_msg:
                role = out_msg.get("role", "assistant")
                content = out_msg.get("content", "")
                if isinstance(content, str):
                    rows.extend(
                        _rows_from_block(
                            base, "output", None, role, 0, content, **kwargs
                        )
                    )
                elif isinstance(content, list):
                    for block_idx, block in enumerate(content):
                        rows.extend(
                            _rows_from_block(
                                base, "output", None, role, block_idx, block, **kwargs
                            )
                        )

    return pd.DataFrame(rows)


def last_request_per_session(df: pd.DataFrame) -> pd.DataFrame:
    """Filter a messages DataFrame to only the longest request per session.

    Each request in a session re-sends the full conversation history, so
    the request with the most input messages is the final (and most complete)
    one. Ties are broken by ``start_time`` (latest wins).

    Parameters
    ----------
    df:
        DataFrame produced by :func:`load_messages`.

    Returns
    -------
    pd.DataFrame
        Subset of *df* containing only rows from the longest request per
        ``session_id``.
    """
    longest = (
        df[df["direction"] == "input"]
        .groupby(["session_id", "request_id", "start_time"])["msg_idx"]
        .max()
        .reset_index()
        .sort_values(["msg_idx", "start_time"], ascending=[False, False])
        .groupby("session_id", as_index=False)
        .first()
    )[["request_id"]]

    return df.merge(longest, on="request_id")


def deduplicate_messages(df: pd.DataFrame) -> pd.DataFrame:
    """Deduplicate a messages DataFrame to one row per unique content block.

    Since each request re-sends the full conversation history, input blocks
    appear once per request. This keeps only the earliest occurrence of each
    ``(session_id, msg_idx, block_idx)``, so ``start_time`` reflects when
    that message was actually introduced rather than the last request's time.

    Output blocks (``direction="output"``) are unique per request and are
    kept as-is.

    Parameters
    ----------
    df:
        DataFrame produced by :func:`load_messages`.

    Returns
    -------
    pd.DataFrame
        Deduplicated DataFrame with one row per unique content block.
    """
    input_deduped = (
        df[df["direction"] == "input"]
        .sort_values(["start_time", "msg_idx", "block_idx"])
        .drop_duplicates(subset=["session_id", "msg_idx", "block_idx"])
    )
    return pd.concat(
        [input_deduped, df[df["direction"] == "output"]],
        ignore_index=True,
    )


def flatten_value(value: Any) -> Any:
    """Flatten a list or dict value into a comma-separated string.

    Leaves scalar values unchanged.

    Parameters
    ----------
    value:
        The value to flatten.

    Returns
    -------
    Any
        A comma-separated string for lists/dicts, or the original value otherwise.
    """
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    elif isinstance(value, dict):
        return ", ".join(f"{k}: {v}" for k, v in value.items())
    return value


def get_value(record: dict, keys: list[str]) -> Any:
    """Traverse a nested dict by a sequence of keys.

    Parameters
    ----------
    record:
        The top-level dict to traverse.
    keys:
        Ordered sequence of keys forming the path to the desired value.

    Returns
    -------
    Any
        The value at the end of the key path, or ``None`` if any key is missing.
    """
    current: Any = record
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return None
    return current


def inspect_keys(data: list[dict], keys: list[str]) -> None:
    """Print unique values found at a key path across a list of records.

    Prints up to 10 unique values; truncates output when more are found.

    Parameters
    ----------
    data:
        List of records (dicts) to inspect.
    keys:
        Key path passed to :func:`get_value` for each record.
    """
    print(f"Keys: {keys}")
    values = set(flatten_value(get_value(record, keys)) for record in data)

    print(f"Found {len(values)} unique values for keys {keys}")
    if len(values) > 10:
        print(f"Too many unique values to display ({len(values)})")
    else:
        print(f"Unique values: {values}")


def normalize_model_name(model: str | None) -> str | None:
    if not model:
        return model
    # Handle '--model X' CLI-style entries
    m = re.match(r"^--model\s+(.+)", model)
    if m:
        model = "claude-" + m.group(1)
    # Strip provider prefixes
    for pattern in [
        r"^bedrock/us\.anthropic\.",
        r"^bedrock/anthropic\.",
        r"^us\.anthropic\.",
        r"^anthropic/",
        r"^perplexity/",
        r"^bedrock/",
        r"^bedrock-",
    ]:
        sub = re.sub(pattern, "", model)
        if sub != model:
            model = sub
            break
    # Reorder 'claude-{major}-{minor}-{family}' → 'claude-{family}-{major}.{minor}'
    model = re.sub(r"^(claude)-(\d+)-(\d+)-(haiku|sonnet|opus)", r"\1-\4-\2.\3", model)
    # Strip date suffixes like -20250929
    model = re.sub(r"-20\d{6}", "", model)
    # Strip version suffixes like -v1:0 or -v1
    model = re.sub(r"-v\d+(?::\d+)?$", "", model)
    # Convert trailing hyphenated version numbers to dot notation: -4-6 → -4.6
    model = re.sub(r"-(\d+)-(\d+)$", r"-\1.\2", model)
    return model
