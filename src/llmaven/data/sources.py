"""sources.py — normalize records from either raw source into one common shape.

LLMaven logs every request via two paths with different schemas and data
completeness guarantees (see epic #153):

- ADLS via ``AdlLogger`` (``src/llmaven/infrastructure/resources/adl_logger.py``):
  one JSON file per request, message content never truncated. Preferred.
- LiteLLM's PostgreSQL spend logs, queried via ``llmaven infra extract``:
  may truncate long messages. Fallback for deployments predating AdlLogger.

This module maps both into the same "common" shape: the litellm
spend-log record shape that ``reader.py``'s row-building already expects.
Every later pipeline stage (``reader.load_messages``,
``last_request_per_session``, ``deduplicate_messages``, ``group_sessions``)
only ever has to deal with that one shape.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Protocol

logger = logging.getLogger(__name__)


def _epoch_to_iso(ts: float | None) -> str | None:
    """Convert a Unix epoch timestamp to the same ISO-8601 string format
    used by the litellm_spend_logs JSONL export (e.g. "2026-01-02T23:41:18.414000Z")."""
    if ts is None:
        return None
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def from_adls(record: dict) -> dict:
    """Map one ADLS per-request JSON record to the common record shape.

    ADLS records (see ``adl_logger.py``) look like
    ``{"timestamp_start", "timestamp_end", "kwargs", "response", "cost"}``.
    The reliable source within them is ``kwargs["standard_logging_object"]``,
    litellm's own normalized per-request log object, verified against a real
    sample from the ``litellm-logs`` container. It already uses the same
    field names (``end_user``, ``messages``, ``model``, ``total_tokens``,
    ...) as the litellm_spend_logs JSONL export, just with epoch-float
    timestamps instead of ISO strings, which this converts.

    ``standard_logging_object["id"]`` is usually present, but when it's
    missing (or for a record with no id at all) the caller may want to fill
    in ``request_id`` itself, e.g. from the blob's filename -- this function
    only sees the record content, not where it came from.

    Known gap: ``standard_logging_object["response"]`` keeps the raw
    provider-shaped response. For Chat Completions calls that's the
    ``{"choices": [...]}`` shape reader.py already parses. For Responses-API
    calls (seen from GitHub Copilot / gpt-5.3-codex traffic) the reply is
    shaped as ``{"output": [...]}`` instead, which reader.py does not yet
    parse -- it logs a warning and that request's final reply is simply
    missing from the session.
    """
    kw = record.get("kwargs") or {}
    slo = kw.get("standard_logging_object") or {}
    metadata = slo.get("metadata") or {}

    return {
        "request_id": slo.get("id"),
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


def from_litellm(record: dict) -> dict:
    """Map one litellm_spend_logs record to the common record shape.

    This is a pass-through: litellm_spend_logs records (the format
    ``llmaven infra extract`` produces) are already shaped exactly like the
    common format -- ``reader.py`` was written against this shape first --
    so there's nothing to transform.
    """
    return record


class _BlobProperties(Protocol):
    name: str


class AdlsFilesystem(Protocol):
    """Duck-typed interface :func:`iter_source` expects for ADLS access.

    Matches the shape of ``azure.storage.blob.ContainerClient`` (the same
    client ``adl_logger.py`` already uses, for writing) so a real
    ``ContainerClient`` pointed at the ``litellm-logs`` container can be
    passed directly. Tests can pass any object providing these two methods.
    """

    def list_blobs(self, name_starts_with: str) -> Iterator[_BlobProperties]: ...

    def download_blob(self, blob_name: str) -> Any:
        """Return an object with a ``.readall() -> bytes`` method."""
        ...


class LitellmClient(Protocol):
    """Duck-typed interface :func:`iter_source` expects for the LiteLLM
    spend-logs API.

    Matches the shape of ``httpx.Client`` (the same client
    ``llmaven infra extract`` already builds in ``cli.py``), already
    configured with the proxy's ``base_url`` and auth header, so a real,
    pre-configured ``httpx.Client`` can be passed directly.
    """

    def get(self, url: str, *, params: dict) -> Any:
        """Return a response object with ``.raise_for_status()`` and ``.json()``."""
        ...


def iter_source(
    day: date,
    mode: Literal["adls", "litellm", "auto"],
    adls_fs: AdlsFilesystem | None,
    litellm_client: LitellmClient | None,
) -> Iterator[tuple[dict, str]]:
    """Yield ``(common_record, source_type)`` for every request logged on ``day``.

    Parameters
    ----------
    day:
        The calendar day to fetch requests for.
    mode:
        - ``"adls"``: always read from ADLS (``adls_fs`` required).
        - ``"litellm"``: always query the LiteLLM spend-logs API
          (``litellm_client`` required).
        - ``"auto"``: use ADLS if ``logs/<yyyy>/<mm>/<dd>/`` has any
          ``.json`` files for this day, otherwise fall back to the LiteLLM
          API. This is how a deployment that only recently turned on
          AdlLogger can still get full history for older days.
    adls_fs:
        See :class:`AdlsFilesystem`. Required for mode ``"adls"`` or
        ``"auto"``.
    litellm_client:
        See :class:`LitellmClient`. Required for mode ``"litellm"``, or as
        the ``"auto"`` fallback.

    Yields
    ------
    (common_record, source_type)
        ``common_record`` is in the shape ``reader.py`` expects (see
        :func:`from_adls` / :func:`from_litellm`); ``source_type`` is
        ``"adls"`` or ``"litellm"``, for recording which source served each
        day in run stats.
    """
    if mode not in ("adls", "litellm", "auto"):
        raise ValueError(f"mode must be 'adls', 'litellm', or 'auto', got {mode!r}")

    adls_blob_names: list[str] = []
    if mode in ("adls", "auto"):
        if adls_fs is None:
            raise ValueError(f"mode={mode!r} requires adls_fs")
        prefix = f"logs/{day.year}/{day.month:02d}/{day.day:02d}/"
        adls_blob_names = [
            b.name
            for b in adls_fs.list_blobs(name_starts_with=prefix)
            if b.name.endswith(".json")
        ]

    if mode == "adls" or (mode == "auto" and adls_blob_names):
        logger.info("%s: reading %d ADLS file(s)", day.isoformat(), len(adls_blob_names))
        for name in adls_blob_names:
            raw = json.loads(adls_fs.download_blob(name).readall())
            common = from_adls(raw)
            common["request_id"] = common.get("request_id") or Path(name).stem
            yield common, "adls"
        return

    if litellm_client is None:
        raise ValueError(f"mode={mode!r} requires litellm_client")
    if mode == "auto":
        logger.info("%s: no ADLS files found, falling back to litellm", day.isoformat())
    else:
        logger.info("%s: reading from litellm", day.isoformat())
    start = day.isoformat()
    end = (day + timedelta(days=1)).isoformat()
    response = litellm_client.get(
        "/spend/logs", params={"start_date": start, "end_date": end, "summarize": "false"}
    )
    response.raise_for_status()
    for raw in response.json():
        yield from_litellm(raw), "litellm"
