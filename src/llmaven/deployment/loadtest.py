from __future__ import annotations

import csv
import dataclasses
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


@dataclass
class PreflightResult:
    url: str
    status_code: int | None
    response_body: str
    error: str | None

    @property
    def ok(self) -> bool:
        return self.status_code == 200


class LoadTestError(Exception):
    """Raised when the load test cannot start or encounters a fatal error."""


@dataclass
class LoadTestResults:
    model: str
    total_requests: int
    failed_requests: int
    content_policy_errors: int
    error_rate_pct: float
    throughput_rps: float
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    latency_avg_ms: float
    tokens_in_total: int
    tokens_out_total: int
    tokens_in_avg: float
    tokens_out_avg: float
    workers: int
    dataset_size: int


_ANTHROPIC_API_PATH = "/v1/messages"

_ANTHROPIC_SAFE_FIELDS = {
    "model",
    "messages",
    "system",
    "max_tokens",
    "top_p",
    "top_k",
    "tools",
    "tool_choice",
}


def _is_anthropic_call_type(call_type: str) -> bool:
    return call_type == "anthropic_messages"


def _extract_request(
    raw: dict[str, Any],
    model: str,
) -> dict[str, Any] | None:
    """Extract a replayable Anthropic request from a LiteLLM proxy log entry.

    Filters ``proxy_server_request`` to safe Anthropic fields. The ``model``
    field is overridden with *model* so the same dataset can be used to
    benchmark different models. Returns ``None`` if the entry has no messages.
    """
    msgs = raw.get("messages") or raw.get("input") or []
    if not isinstance(msgs, list) or not msgs:
        return None

    request = {k: v for k, v in raw.items() if k in _ANTHROPIC_SAFE_FIELDS}

    # Strip thinking content blocks (signatures are time-limited and invalid on
    # replay) and image blocks from tool_result content (base64 data is often
    # corrupt or truncated in logs).
    filtered_msgs = []
    for msg in msgs:
        if not isinstance(msg, dict):
            filtered_msgs.append(msg)
            continue
        msg_copy = {**msg}
        content = msg_copy.get("content")
        if isinstance(content, list):
            cleaned = []
            for block in content:
                if not isinstance(block, dict):
                    cleaned.append(block)
                    continue
                if block.get("type") == "thinking":
                    continue
                if block.get("type") == "tool_result":
                    block = {**block}
                    inner = block.get("content")
                    if isinstance(inner, list):
                        stripped = [
                            b
                            for b in inner
                            if not (isinstance(b, dict) and b.get("type") == "image")
                        ]
                        # Keep at least a text placeholder so the tool_result is
                        # never empty — an empty result is rejected as "no tool
                        # output found".
                        block["content"] = stripped or [
                            {"type": "text", "text": "[image removed]"}
                        ]
                cleaned.append(block)
            msg_copy["content"] = cleaned
        filtered_msgs.append(msg_copy)
    request["messages"] = filtered_msgs

    # Strip cache_control from tool definitions — it's a prompt-caching
    # annotation that is rejected when replaying against some configurations.
    tools = request.get("tools")
    if isinstance(tools, list):
        request["tools"] = [
            (
                {k: v for k, v in t.items() if k != "cache_control"}
                if isinstance(t, dict)
                else t
            )
            for t in tools
        ]

    request["model"] = model
    # Drop stream so token usage is always present in the response body.
    request.pop("stream", None)

    return request


def _load_requests(requests_file: Path, model: str) -> list[dict[str, Any]]:
    dataset: list[dict[str, Any]] = []
    skipped = 0
    with requests_file.open() as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Line %s: invalid JSON, skipping", lineno)
                skipped += 1
                continue

            call_type = entry.get("call_type", "")
            if not _is_anthropic_call_type(call_type):
                # raise LoadTestError(

                logger.warning(
                    f"Line {lineno}: expected Anthropic data (call_type='anthropic_messages')"
                    f" but got call_type={call_type!r}. Only Anthropic requests are supported."
                )
                skipped += 1
                continue
                # )

            raw_req = entry.get("proxy_server_request")
            if not raw_req:
                skipped += 1
                continue

            result = _extract_request(raw_req, model)
            if result is None:
                skipped += 1
                continue

            dataset.append(result)

    if skipped:
        logger.warning("Skipped %s line(s) in %s", skipped, requests_file)
    return dataset


def preflight_check(
    base_url: str,
    api_key: str,
    api_path: str,
    sample_request: dict[str, Any],
) -> PreflightResult:
    """Fire a single request and return diagnostic info without touching Locust."""
    import httpx

    url = base_url.rstrip("/") + api_path
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json=sample_request, headers=headers)
        return PreflightResult(
            url=url,
            status_code=resp.status_code,
            response_body=resp.text[:2000],
            error=None,
        )
    except httpx.ConnectError as exc:
        return PreflightResult(
            url=url,
            status_code=None,
            response_body="",
            error=f"Connection refused: {exc}",
        )
    except httpx.TimeoutException as exc:
        return PreflightResult(
            url=url,
            status_code=None,
            response_body="",
            error=f"Request timed out: {exc}",
        )
    except Exception as exc:
        return PreflightResult(
            url=url, status_code=None, response_body="", error=str(exc)
        )


def run_load_test(
    requests_file: Path,
    base_url: str,
    api_key: str,
    model: str,
    workers: int,
    error_log: Path | None = None,
    max_errors_logged: int = 50,
) -> LoadTestResults:
    """Run a headless Locust load test against a LiteLLM proxy.

    Each request from *requests_file* (JSONL of LiteLLM proxy log entries) is
    sent exactly once. Requests are pulled from a shared queue by workers,
    ensuring full replay. Requests are replayed against the same endpoint type
    they were originally sent to, as determined by each entry's ``call_type``
    field. Streaming is always disabled so token usage can be read from the
    response.

    Args:
        requests_file: Path to the JSONL file of proxy log entries.
        base_url: LiteLLM proxy base URL (e.g. ``http://proxy:4000``).
        api_key: Proxy API key (``LLMAVEN_SECRETS_LITELLM_MASTER_KEY``).
        model: Model to use for replay.
        workers: Number of concurrent virtual users.
        error_log: Optional path to log errors to.
        max_errors_logged: Maximum number of errors to log.

    Returns:
        A :class:`LoadTestResults` dataclass with throughput, latency, and
        token metrics.

    Raises:
        LoadTestError: If no valid requests are found or the runner fails.
    """
    import gevent
    import gevent.queue
    from locust import HttpUser, constant, task
    from locust.env import Environment

    dataset = _load_requests(requests_file, model=model)
    if not dataset:
        raise LoadTestError(f"No valid requests found in {requests_file}")

    # Shared queue and accumulators — safe under gevent's cooperative multitasking.
    request_queue: gevent.queue.Queue[dict[str, Any] | None] = gevent.queue.Queue()
    for item in dataset:
        request_queue.put(item)

    token_acc: dict[str, int] = {"in": 0, "out": 0, "n": 0}
    error_acc: dict[str, int] = {"n": 0}
    content_policy_acc: dict[str, int] = {"n": 0}

    # Capture locals for use inside the inner class.
    _request_queue = request_queue
    _api_key = api_key
    _token_acc = token_acc
    _error_acc = error_acc
    _content_policy_acc = content_policy_acc
    _error_log = error_log
    _max_errors = max_errors_logged

    class LiteLLMUser(HttpUser):
        wait_time = constant(0)

        @task
        def replay(self) -> None:

            item = None
            try:
                item = _request_queue.get_nowait()
            except gevent.queue.Empty:
                self.stop()
                return

            assert item is not None
            req = item

            headers = {
                "Authorization": f"Bearer {_api_key}",
                "Content-Type": "application/json",
            }
            with self.client.post(
                _ANTHROPIC_API_PATH,
                json=req,
                headers=headers,
                catch_response=True,
            ) as resp:
                if resp.status_code == 200:
                    try:
                        usage = resp.json().get("usage", {})
                        _token_acc["in"] += usage.get("input_tokens", 0)
                        _token_acc["out"] += usage.get("output_tokens", 0)
                        _token_acc["n"] += 1
                    except Exception:
                        pass
                    resp.success()
                else:
                    if (
                        resp.status_code == 400
                        and "ContentPolicyViolationError" in resp.text
                    ):
                        _content_policy_acc["n"] += 1
                    resp.failure(f"HTTP {resp.status_code}: {resp.text[:200]}")
                    if _error_log is not None and _error_acc["n"] < _max_errors:
                        import datetime

                        _error_acc["n"] += 1
                        entry = {
                            "ts": datetime.datetime.now(
                                datetime.timezone.utc
                            ).isoformat(),
                            "status_code": resp.status_code,
                            "model": req.get("model"),
                            "request_preview": str(
                                (req.get("messages") or [{}])[0].get("content", "")
                            )[:200],
                            "response": resp.text[:500],
                        }
                        with _error_log.open("a", encoding="utf-8") as fh:
                            fh.write(json.dumps(entry) + "\n")

    env = Environment(user_classes=[LiteLLMUser], host=base_url.rstrip("/"))
    runner = env.create_local_runner()
    runner.start(user_count=workers, spawn_rate=workers, wait=True)
    gevent.sleep(2)
    n = 0  # Wait for ramp-up to finish
    while runner.user_count > 0:
        if n % 20 == 0:
            left = len(_request_queue)
            print(f"{left} requests left... {runner.user_count} users active")
        n += 1
        gevent.sleep(0.1)
    runner.stop()

    stats = env.stats.total
    total = stats.num_requests
    failed = stats.num_failures
    n_tokens = token_acc["n"]

    return LoadTestResults(
        model=model,
        total_requests=total,
        failed_requests=failed,
        content_policy_errors=content_policy_acc["n"],
        error_rate_pct=(failed / total * 100) if total else 0.0,
        throughput_rps=stats.total_rps,
        latency_p50_ms=stats.get_response_time_percentile(0.50) or 0.0,
        latency_p95_ms=stats.get_response_time_percentile(0.95) or 0.0,
        latency_p99_ms=stats.get_response_time_percentile(0.99) or 0.0,
        latency_avg_ms=stats.avg_response_time or 0.0,
        tokens_in_total=token_acc["in"],
        tokens_out_total=token_acc["out"],
        tokens_in_avg=token_acc["in"] / n_tokens if n_tokens else 0.0,
        tokens_out_avg=token_acc["out"] / n_tokens if n_tokens else 0.0,
        workers=workers,
        dataset_size=len(dataset),
    )


def save_results(results: LoadTestResults, output: Path) -> None:
    """Persist *results* to *output* as JSON or CSV based on file extension.

    CSV files are appended to on every run; the header row is written only when
    the file does not yet exist (or is empty).
    """
    data = dataclasses.asdict(results)
    if output.suffix.lower() == ".csv":
        write_header = not output.exists() or output.stat().st_size == 0
        with output.open("a", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(data.keys()))
            if write_header:
                writer.writeheader()
            writer.writerow(data)
    else:
        with output.open("w") as fh:
            json.dump(data, fh, indent=2)
