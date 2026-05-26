from __future__ import annotations

import csv
import dataclasses
import json
import logging
import random
import re
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
    duration_s: int
    dataset_size: int


_USER_ROLES = {"user", "person"}

_OPERATIONAL_TAG_RE = re.compile(
    r"<([a-z][a-z0-9_-]*)(?:\s[^>]*)?>.*?</\1>",
    re.DOTALL,
)


def _strip_operational_tags(text: str) -> str:
    """Remove XML-like operational context tags (e.g. <system-reminder>) injected by agent frameworks."""
    return _OPERATIONAL_TAG_RE.sub("", text).strip()


def _extract_user_text(messages: list[Any]) -> str | None:
    """Return the text of the most recent human turn that contains text.

    Iterates backwards so that in multi-turn tool-use conversations (where the
    last user message is a tool_result block with no text) we fall through to
    the earlier turn that contains the actual prompt.

    Handles ``role: "user"`` and the non-standard ``role: "person"`` variant.
    Content may be a plain string or a list of content blocks; only
    ``type: "text"`` blocks are extracted.
    """
    for msg in reversed(messages):
        if not isinstance(msg, dict) or msg.get("role") not in _USER_ROLES:
            continue
        content = msg.get("content")
        if isinstance(content, str):
            text = _strip_operational_tags(content)
            if text:
                return text
        if isinstance(content, list):
            parts = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            text = _strip_operational_tags(" ".join(p for p in parts if p))
            if text:
                return text
        # this user turn has no text (e.g. tool_result only) — keep looking
    return None


def _to_openai_request(
    raw: dict[str, Any],
    log_entry: dict[str, Any],
    model: str,
) -> dict[str, Any] | None:
    """Build a minimal OpenAI chat/completions request from a log entry.

    Handles two proxy_server_request shapes:
    - Standard chat (``messages`` list) — anthropic_messages, acompletion
    - Responses API (``input`` list)     — aresponses

    Only the last user message text is kept; system prompts, tools, and
    provider-specific fields are discarded so the same dataset works against
    any model via any OpenAI-compatible endpoint.

    Returns None if no user message text can be extracted.
    """
    # Responses API uses "input" instead of "messages"
    msgs = raw.get("messages") or raw.get("input") or []
    if not isinstance(msgs, list):
        return None

    user_text = _extract_user_text(msgs)
    if not user_text:
        return None

    max_tokens = (
        raw.get("max_tokens")
        or raw.get("max_output_tokens")  # Responses API field name
        or log_entry.get("max_tokens")
        or 1024
    )

    return {
        "model": model,
        "messages": [{"role": "user", "content": user_text}],
        "max_tokens": max_tokens,
        "stream": False,
    }


def _load_requests(requests_file: Path, model: str) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
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

            req = _to_openai_request(raw_req, entry, model)
            if req is None:
                # logger.warning("Line %s: no user message found, skipping", lineno)
                skipped += 1
                continue

            requests.append(req)

    if skipped:
        logger.warning("Skipped %s line(s) in %s", skipped, requests_file)
    return requests


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
    duration: int,
    ramp_up: int,
    api_path: str = "/chat/completions",
    error_log: Path | None = None,
    max_errors_logged: int = 50,
) -> LoadTestResults:
    """Run a headless Locust load test against a LiteLLM proxy.

    Requests are randomly sampled from *requests_file* (JSONL of LiteLLM proxy
    log entries).  Each request is extracted from the ``proxy_server_request``
    field and replayed against ``{base_url}{api_path}``.  Streaming is always
    disabled so that token usage can be read directly from the response body.

    Args:
        requests_file: Path to the JSONL file of proxy log entries.
        base_url: LiteLLM proxy base URL (e.g. ``http://proxy:4000``).
        api_key: Proxy API key (``LLMAVEN_SECRETS_LITELLM_MASTER_KEY``).
        workers: Number of concurrent virtual users.
        duration: Test duration in seconds (excluding ramp-up).
        ramp_up: Seconds to ramp up to full concurrency.
        api_path: API endpoint path to send requests to.

    Returns:
        A :class:`LoadTestResults` dataclass with throughput, latency, and
        token metrics.

    Raises:
        LoadTestError: If no valid requests are found or the runner fails.
    """
    try:
        import gevent
        from locust import HttpUser, constant, task
        from locust.env import Environment
    except ImportError as exc:
        raise LoadTestError(
            "locust is not installed. Install it with: pip install 'llmaven[loadtest]'"
        ) from exc

    dataset = _load_requests(requests_file, model=model)
    if not dataset:
        raise LoadTestError(f"No valid requests found in {requests_file}")

    # Shared accumulators — safe under gevent's cooperative multitasking.
    token_acc: dict[str, int] = {"in": 0, "out": 0, "n": 0}
    error_acc: dict[str, int] = {"n": 0}
    content_policy_acc: dict[str, int] = {"n": 0}

    # Capture locals for use inside the inner class.
    _dataset = dataset
    _api_key = api_key
    _api_path = api_path
    _token_acc = token_acc
    _error_acc = error_acc
    _content_policy_acc = content_policy_acc
    _error_log = error_log
    _max_errors = max_errors_logged

    class LiteLLMUser(HttpUser):
        wait_time = constant(0)

        @task
        def replay(self) -> None:
            req = random.choice(_dataset)
            headers = {
                "Authorization": f"Bearer {_api_key}",
                "Content-Type": "application/json",
            }
            with self.client.post(
                _api_path,
                json=req,
                headers=headers,
                catch_response=True,
            ) as resp:
                if resp.status_code == 200:
                    try:
                        usage = resp.json().get("usage", {})
                        _token_acc["in"] += usage.get("prompt_tokens", 0)
                        _token_acc["out"] += usage.get("completion_tokens", 0)
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
                        with _error_log.open("a") as fh:
                            fh.write(json.dumps(entry) + "\n")

    env = Environment(user_classes=[LiteLLMUser], host=base_url.rstrip("/"))
    runner = env.create_local_runner()

    spawn_rate = workers / max(ramp_up, 1)
    runner.start(user_count=workers, spawn_rate=spawn_rate)
    gevent.sleep(ramp_up + duration)
    runner.quit()

    stats = env.stats.total
    total = stats.num_requests
    failed = stats.num_failures
    n_tokens = token_acc["n"]

    return LoadTestResults(
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
        duration_s=duration,
        dataset_size=len(dataset),
    )


def save_results(results: LoadTestResults, output: Path) -> None:
    """Persist *results* to *output* as JSON or CSV based on file extension."""
    data = dataclasses.asdict(results)
    if output.suffix.lower() == ".csv":
        with output.open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(data.keys()))
            writer.writeheader()
            writer.writerow(data)
    else:
        with output.open("w") as fh:
            json.dump(data, fh, indent=2)
