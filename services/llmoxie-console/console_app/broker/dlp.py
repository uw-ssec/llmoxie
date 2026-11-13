"""What ceil-dlp found in requests to LiteLLM, for SSEC admins to look at in the console.

ceil-dlp appends one JSON line per detection to a file on a volume that LiteLLM writes and the broker
can only read. A line has the kind of data, what was done about it, a hash of each value, the LiteLLM
user and the request id. It never has the value itself, so neither does anything here.
"""

import json
import os
from collections import Counter
from pathlib import Path

_FILE = Path(os.environ["CONSOLE_DLP_AUDIT_FILE"]) if os.environ.get("CONSOLE_DLP_AUDIT_FILE") else None
_TAIL_BYTES = 2_000_000   # the end of the file is enough for a page of recent events
SHOWN = 300


def enabled() -> bool:
    return _FILE is not None


def _lines() -> list[dict]:
    """The events at the end of the file, oldest first. A file that is not there yet means none so far."""
    if _FILE is None or not _FILE.exists():
        return []
    with _FILE.open("rb") as file:
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(max(0, size - _TAIL_BYTES))
        data = file.read().decode("utf-8", errors="replace")
    lines = data.splitlines()
    if size > _TAIL_BYTES:
        lines = lines[1:]   # the first line was cut in the middle
    events = []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("event") in ("dlp_detection", "dlp_block"):
            events.append(event)
    return events


def recent() -> dict:
    """The latest events, newest first, and how often each kind of data met each action among all that were read."""
    events = _lines()
    rows, totals = [], Counter()
    for event in events:
        blocked = event["event"] == "dlp_block"
        kinds = event.get("pii_types") or [] if blocked else [event.get("pii_type") or "unknown"]
        count = 0 if blocked else int(event.get("count") or 0)
        for kind in kinds:   # a refused request is one line naming every kind that caused it
            totals[(str(kind), str(event.get("action") or ""))] += 1 if blocked else (count or 1)
        rows.append({
            "at": str(event.get("timestamp") or ""), "blocked": blocked, "kinds": [str(k) for k in kinds],
            "action": str(event.get("action") or ""), "count": count, "source": str(event.get("source") or "request"),
            "mode": str(event.get("mode") or ""), "user_id": event.get("user_id"),
            "request_id": str(event.get("request_id") or ""),
        })
    rows.reverse()
    return {
        "events": rows[:SHOWN], "read": len(rows),
        "totals": [{"kind": kind, "action": action, "count": n} for (kind, action), n in sorted(totals.items())],
    }
