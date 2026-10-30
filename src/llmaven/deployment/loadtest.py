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
        return self.status_code == 200 and self.error is None


class LoadTestError(Exception):
    """Raised when the load test cannot start or encounters a fatal error."""


@dataclass
class LoadTestResults:
    model: str
    total_requests: int
    failed_requests: int
    content_policy_errors: int
    fallback_requests: int
    # None when any successful response could not be classified, so a saved
    # rate is never a false 0%.
    fallback_rate_pct: float | None
    fallback_unclassified_requests: int
    served_model_counts_json: str
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
    unsent_requests: int


_ANTHROPIC_API_PATH = "/v1/messages"
_REQUEST_TIMEOUT_SECONDS = 90.0

_ANTHROPIC_SAFE_FIELDS = {
    "model",
    "messages",
    "system",
    "max_tokens",
    "temperature",
    "stop_sequences",
    "top_p",
    "top_k",
    "tools",
    "tool_choice",
}


def _attempted_fallbacks(headers: Any) -> int:
    """Return LiteLLM's ``x-litellm-attempted-fallbacks`` count (0 if absent)."""
    try:
        return int(headers.get("x-litellm-attempted-fallbacks") or 0)
    except (TypeError, ValueError):
        return 0


def _served_group(headers: Any, deployment_groups: dict[str, str]) -> str | None:
    """Map LiteLLM's ``x-litellm-model-id`` header to its model group name."""
    model_id = headers.get("x-litellm-model-id")
    return deployment_groups.get(model_id) if model_id else None


def _classify_fallback(
    headers: Any, deployment_groups: dict[str, str], requested_model: Any
) -> bool | None:
    """Return whether a successful response was served by a fallback.

    The response ``model`` cannot signal a fallback: it is the requested alias
    on /v1/messages and the underlying model elsewhere. Use LiteLLM's fallback
    header when present, else the serving model group. Returns ``None`` when
    neither is available, so the caller can report the result as unknown.
    """
    if _attempted_fallbacks(headers) > 0:
        return True
    group = _served_group(headers, deployment_groups)
    if group is None:
        return None
    return group != requested_model


def fetch_deployment_groups(base_url: str, api_key: str) -> dict[str, str]:
    """Return ``{deployment id: model group}`` from the proxy's ``/model/info``.

    On ``/v1/messages`` LiteLLM echoes the requested alias as the response
    ``model`` and omits the attempted-fallbacks header, so the deployment id
    header is the only evidence of which model group served a request. Returns
    an empty mapping (and logs a warning) if the endpoint is unavailable; the
    run then reports its fallback rate as unknown rather than 0%.
    """
    import httpx

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(
                base_url.rstrip("/") + "/model/info",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        resp.raise_for_status()
        groups = {
            entry["model_info"]["id"]: entry["model_name"]
            for entry in resp.json().get("data", [])
        }
    except Exception as exc:
        logger.warning(
            "Could not read /model/info (%s); fallbacks served on "
            "/v1/messages will not be detected",
            exc,
        )
        return {}
    return groups


def _is_token_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _parse_success_body(text: str) -> tuple[str | None, int, int] | str:
    """Validate an HTTP 200 Anthropic Messages response body.

    Returns ``(served_model, input_tokens, output_tokens)`` for a usable
    response, or a failure reason string when the body is not a successful
    message (invalid JSON, an error object, or missing token usage).
    """
    try:
        payload = json.loads(text)
    except ValueError:
        return "HTTP 200 with invalid JSON body"
    if not isinstance(payload, dict):
        return "HTTP 200 with a non-object JSON body"
    if payload.get("type") == "error" or "error" in payload:
        return f"HTTP 200 with an error body: {text[:200]}"
    usage = payload.get("usage")
    if not isinstance(usage, dict) or not (
        _is_token_count(usage.get("input_tokens"))
        and _is_token_count(usage.get("output_tokens"))
    ):
        return "HTTP 200 without valid token usage"
    served_model = payload.get("model")
    if not isinstance(served_model, str) or not served_model:
        served_model = None
    return served_model, usage["input_tokens"], usage["output_tokens"]


def _run_deadline_seconds(dataset_size: int, workers: int) -> float:
    """Upper bound on a full replay: each worker sends its share of requests
    back to back, and each request can take up to the request timeout."""
    per_worker = -(-dataset_size // workers)  # ceiling division
    return per_worker * _REQUEST_TIMEOUT_SECONDS + 60.0


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
                if block.get("type") in ("thinking", "redacted_thinking"):
                    continue
                if block.get("type") == "image":
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
            if not cleaned:
                # A message holding only thinking/image blocks would be sent
                # with empty content, which the API rejects; drop it.
                continue
            msg_copy["content"] = cleaned
        filtered_msgs.append(msg_copy)
    if not filtered_msgs:
        return None
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
    non_anthropic: dict[str, int] = {}
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
                non_anthropic[call_type] = non_anthropic.get(call_type, 0) + 1
                skipped += 1
                continue

            raw_req = entry.get("proxy_server_request")
            if not raw_req:
                skipped += 1
                continue

            result = _extract_request(raw_req, model)
            if result is None:
                skipped += 1
                continue

            dataset.append(result)

    if non_anthropic:
        logger.warning(
            "Skipped non-Anthropic entries (only call_type='anthropic_messages' "
            "is supported): %s",
            json.dumps(non_anthropic, sort_keys=True),
        )
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
        error = None
        if resp.status_code == 200:
            parsed = _parse_success_body(resp.text)
            if isinstance(parsed, str):
                error = parsed
        return PreflightResult(
            url=url,
            status_code=resp.status_code,
            response_body=resp.text[:2000],
            error=error,
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

    Each Anthropic Messages entry from *requests_file* (JSONL of LiteLLM proxy
    log entries) is sent exactly once to ``/v1/messages``. Requests are pulled
    from a shared queue by workers, ensuring full replay; other ``call_type``
    entries are skipped. Streaming is always disabled so token usage can be
    read from the response. An HTTP 200 counts as a success only when its body
    is a message with valid token usage. If the run exceeds its deadline, the
    requests never sent are reported in ``unsent_requests``.

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
    fallback_acc: dict[str, int] = {"n": 0, "unclassified": 0}
    served_model_acc: dict[str, int] = {}

    # Capture locals for use inside the inner class.
    _request_queue = request_queue
    _api_key = api_key
    _token_acc = token_acc
    _error_acc = error_acc
    _content_policy_acc = content_policy_acc
    _fallback_acc = fallback_acc
    _served_model_acc = served_model_acc
    _deployment_groups = fetch_deployment_groups(base_url, api_key)
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
                timeout=_REQUEST_TIMEOUT_SECONDS,
                catch_response=True,
            ) as resp:
                if resp.status_code == 200:
                    parsed = _parse_success_body(resp.text)
                    if isinstance(parsed, str):
                        failure = parsed
                    else:
                        resp.success()
                        served_model, tokens_in, tokens_out = parsed
                        group = _served_group(resp.headers, _deployment_groups)
                        served = group or served_model
                        if served:
                            _served_model_acc[served] = (
                                _served_model_acc.get(served, 0) + 1
                            )
                        fell_back = _classify_fallback(
                            resp.headers, _deployment_groups, req.get("model")
                        )
                        if fell_back is None:
                            _fallback_acc["unclassified"] += 1
                        elif fell_back:
                            _fallback_acc["n"] += 1
                        _token_acc["in"] += tokens_in
                        _token_acc["out"] += tokens_out
                        _token_acc["n"] += 1
                        return
                else:
                    if (
                        resp.status_code == 400
                        and "ContentPolicyViolationError" in resp.text
                    ):
                        _content_policy_acc["n"] += 1
                    failure = f"HTTP {resp.status_code}: {resp.text[:200]}"
                resp.failure(failure)
                if _error_log is not None and _error_acc["n"] < _max_errors:
                    import datetime

                    _error_acc["n"] += 1
                    entry = {
                        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
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
    deadline = _run_deadline_seconds(len(dataset), workers)
    n = 0  # Wait for every worker to drain the queue and stop.
    while runner.user_count > 0:
        if n % 20 == 0:
            left = len(_request_queue)
            print(f"{left} requests left... {runner.user_count} users active")
        gevent.sleep(0.1)
        n += 1
        if n * 0.1 > deadline:
            logger.warning(
                "Load test exceeded its %.0fs deadline; stopping with "
                "%s request(s) still queued",
                deadline,
                len(_request_queue),
            )
            break
    runner.stop()

    stats = env.stats.total
    total = stats.num_requests
    failed = stats.num_failures
    successful = max(total - failed, 0)
    n_tokens = token_acc["n"]

    return LoadTestResults(
        model=model,
        total_requests=total,
        failed_requests=failed,
        content_policy_errors=content_policy_acc["n"],
        fallback_requests=fallback_acc["n"],
        fallback_rate_pct=_fallback_rate_pct(
            fallback_acc["n"], fallback_acc["unclassified"], successful
        ),
        fallback_unclassified_requests=fallback_acc["unclassified"],
        served_model_counts_json=json.dumps(served_model_acc, sort_keys=True),
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
        unsent_requests=max(len(dataset) - total, 0),
    )


def _fallback_rate_pct(
    fallbacks: int, unclassified: int, successful: int
) -> float | None:
    """Return the fallback rate, or ``None`` if any success was unclassified."""
    if unclassified:
        return None
    return (fallbacks / successful * 100) if successful else 0.0


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
