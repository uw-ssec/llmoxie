from __future__ import annotations

import csv
import dataclasses
import json
import random
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class LoadTestError(Exception):
    """Raised when the load test cannot start or encounters a fatal error."""


@dataclass
class LoadTestResults:
    total_requests: int
    failed_requests: int
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


def _load_requests(requests_file: Path) -> list[dict[str, Any]]:
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
                warnings.warn(f"Line {lineno}: invalid JSON, skipping", stacklevel=2)
                skipped += 1
                continue

            req = entry.get("proxy_server_request")
            if not req:
                warnings.warn(
                    f"Line {lineno}: missing 'proxy_server_request', skipping",
                    stacklevel=2,
                )
                skipped += 1
                continue

            # Force non-streaming so the full response body is available for token counting.
            req = dict(req)
            req["stream"] = False
            requests.append(req)

    if skipped:
        warnings.warn(
            f"Skipped {skipped} malformed line(s) in {requests_file}", stacklevel=2
        )
    return requests


def run_load_test(
    requests_file: Path,
    base_url: str,
    api_key: str,
    workers: int,
    duration: int,
    ramp_up: int,
    api_path: str = "/v1/messages",
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
        from locust import HttpUser, between, task
        from locust.env import Environment
    except ImportError as exc:
        raise LoadTestError(
            "locust is not installed. Install it with: pip install 'llmaven[loadtest]'"
        ) from exc

    dataset = _load_requests(requests_file)
    if not dataset:
        raise LoadTestError(f"No valid requests found in {requests_file}")

    # Shared accumulators — safe under gevent's cooperative multitasking.
    token_acc: dict[str, int] = {"in": 0, "out": 0, "n": 0}

    # Capture locals for use inside the inner class.
    _dataset = dataset
    _api_key = api_key
    _api_path = api_path
    _token_acc = token_acc

    class LiteLLMUser(HttpUser):
        wait_time = between(0, 0)

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
                    resp.failure(f"HTTP {resp.status_code}: {resp.text[:200]}")

    env = Environment(user_classes=[LiteLLMUser], host=base_url)
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
