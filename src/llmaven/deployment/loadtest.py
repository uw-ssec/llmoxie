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
    anthropic_requests: int
    openai_requests: int


# Maps LiteLLM call_type → the proxy endpoint that originally handled the request.
_OPENAI_API_PATH = "/chat/completions"
_ANTHROPIC_API_PATH = "/v1/messages"

_CALL_TYPE_PATH: dict[str, str] = {
    "acompletion": _OPENAI_API_PATH,
    "anthropic_messages": _ANTHROPIC_API_PATH,
}

# Fields safe to pass through for each endpoint type.
_OPENAI_SAFE_FIELDS = {
    "model",
    "messages",
    "max_tokens",
    "temperature",
    "top_p",
    "top_k",
    "frequency_penalty",
    "presence_penalty",
    "stop",
    "tools",
    "tool_choice",
    "seed",
}

_ANTHROPIC_SAFE_FIELDS = {
    "model",
    "messages",
    "system",
    "max_tokens",
    "temperature",
    "top_p",
    "top_k",
    "tools",
    "tool_choice",
}


def _is_anthropic_path(api_path: str) -> bool:
    return api_path == _ANTHROPIC_API_PATH


def _count_requests_by_endpoint(
    dataset: list[tuple[str, dict[str, Any]]],
) -> tuple[int, int]:
    anthropic_count = sum(1 for api_path, _ in dataset if _is_anthropic_path(api_path))
    openai_count = len(dataset) - anthropic_count
    return anthropic_count, openai_count


def _extract_request(
    raw: dict[str, Any],
    log_entry: dict[str, Any],
    model: str,
) -> tuple[str, dict[str, Any]] | None:
    """Extract a replayable request from a LiteLLM proxy log entry.

    Filters ``proxy_server_request`` to only safe fields for the target endpoint,
    ensuring no unknown fields cause rejections. The ``model`` field is overridden
    with *model* so the same dataset can be used to benchmark different models.

    The LiteLLM ``call_type`` field determines which proxy endpoint to target,
    ensuring the request arrives at the same handler that processed it originally.

    For OpenAI endpoints, removes thinking content blocks from messages since they
    are Anthropic-specific and cause validation errors.

    Returns ``(api_path, request_body)`` or ``None`` if the entry cannot be
    replayed (unknown call_type, missing messages).
    """
    call_type = log_entry.get("call_type", "")
    api_path = _CALL_TYPE_PATH.get(call_type)
    if api_path is None:
        return None

    msgs = raw.get("messages") or raw.get("input") or []
    if not isinstance(msgs, list) or not msgs:
        return None

    # Select safe fields based on endpoint type.
    is_anthropic = _is_anthropic_path(api_path)
    safe_fields = _ANTHROPIC_SAFE_FIELDS if is_anthropic else _OPENAI_SAFE_FIELDS

    request = {k: v for k, v in raw.items() if k in safe_fields}

    # For OpenAI endpoints, strip thinking content blocks from messages.
    if not is_anthropic:
        filtered_msgs = []
        for msg in msgs:
            if not isinstance(msg, dict):
                filtered_msgs.append(msg)
                continue
            msg_copy = {**msg}
            content = msg_copy.get("content")
            if isinstance(content, list):
                # Remove thinking blocks from content arrays.
                msg_copy["content"] = [
                    block
                    for block in content
                    if not (isinstance(block, dict) and block.get("type") == "thinking")
                ]
            filtered_msgs.append(msg_copy)
        request["messages"] = filtered_msgs
    else:
        request["messages"] = msgs

    request["model"] = model
    # Drop stream so token usage is always present in the response body.
    request.pop("stream", None)

    return api_path, request


def _load_requests(requests_file: Path, model: str) -> list[tuple[str, dict[str, Any]]]:
    dataset: list[tuple[str, dict[str, Any]]] = []
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

            raw_req = entry.get("proxy_server_request")
            if not raw_req:
                skipped += 1
                continue

            result = _extract_request(raw_req, entry, model)
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

    # Count requests by endpoint type.
    anthropic_count, openai_count = _count_requests_by_endpoint(dataset)

    # Shared queue and accumulators — safe under gevent's cooperative multitasking.
    request_queue: gevent.queue.Queue = gevent.queue.Queue()
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
            api_path, req = item

            headers = {
                "Authorization": f"Bearer {_api_key}",
                "Content-Type": "application/json",
            }
            with self.client.post(
                api_path,
                json=req,
                headers=headers,
                catch_response=True,
            ) as resp:
                if resp.status_code == 200:
                    try:
                        usage = resp.json().get("usage", {})
                        # Handle both OpenAI and Anthropic response shapes.
                        _token_acc["in"] += usage.get("prompt_tokens") or usage.get(
                            "input_tokens", 0
                        )
                        _token_acc["out"] += usage.get(
                            "completion_tokens"
                        ) or usage.get("output_tokens", 0)
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
            print(f"{left} requests left...")
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
        anthropic_requests=anthropic_count,
        openai_requests=openai_count,
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
