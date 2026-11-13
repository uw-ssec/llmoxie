"""Smoke-test the llmoxie chart on the local k3s cluster (prototype for #236).

Run it with ``pixi run -e llmaven k3s-smoke`` after ``k3s-up``. It checks that:

1. LiteLLM answers its liveness route.
2. A chat completion through the mock model succeeds with the master key.
3. MLflow answers its health route.
4. LiteLLM recorded a trace for that request in MLflow.
5. MLflow stores an artifact in object storage.
6. The request logger wrote that request to object storage.
7. LiteLLM holds a connection to Redis.
8. A manual run of the backup CronJob writes a dump to the backup store, which
   runs in a second cluster.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KUBECTL = str(Path(__file__).resolve().parent / "bin" / "kubectl")
NAMESPACE = "llmoxie"
RELEASE = "llmoxie"
LITELLM_URL = "http://127.0.0.1:4000"
MLFLOW_URL = "http://127.0.0.1:8080"

# Filled in by check_chat, so later checks only accept what this run produced.
before_chat: dict = {}

LIST_OBJECTS = """
import sys
import boto3
from botocore.exceptions import ClientError
# Optional endpoint, access key and secret key select another store.
other = dict(zip(("endpoint_url", "aws_access_key_id", "aws_secret_access_key"), sys.argv[3:6]))
try:
    pages = boto3.client("s3", **other).get_paginator("list_objects_v2").paginate(
        Bucket=sys.argv[1], Prefix=sys.argv[2]
    )
    print("\\n".join(obj["Key"] for page in pages for obj in page.get("Contents", [])))
except ClientError as exc:
    if exc.response["Error"]["Code"] != "NoSuchBucket":
        raise
"""

LOG_ARTIFACT = """
import mlflow
mlflow.set_tracking_uri("http://127.0.0.1:8080")
with mlflow.start_run() as run:
    mlflow.log_text("llmoxie smoke test", "smoke.txt")
print(run.info.run_id)
"""


def kubectl(*args: str) -> str:
    env = {**os.environ, "KUBECONFIG": str(ROOT / ".kube" / "llmoxie-k3s.yaml")}
    result = subprocess.run(
        [KUBECTL, "--namespace", NAMESPACE, *args],
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"kubectl {' '.join(args)} failed:\n{result.stderr}")
    return result.stdout.strip()


def http(url: str, body: dict | None = None, key: str | None = None) -> bytes:
    request = urllib.request.Request(url)
    if key:
        request.add_header("Authorization", f"Bearer {key}")
    data = None
    if body is not None:
        request.add_header("Content-Type", "application/json")
        data = json.dumps(body).encode()
    with urllib.request.urlopen(request, data=data, timeout=60) as response:
        return response.read()


def list_objects(bucket: str, prefix: str, *store: str) -> set[str]:
    """List object keys from inside the LiteLLM pod, which has boto3.

    ``store`` is an optional endpoint, access key and secret key; without it the
    listing uses the release's own object storage.
    """
    out = kubectl(
        "exec",
        f"deploy/{RELEASE}-litellm",
        "--container",
        "litellm",
        "--",
        "python",
        "-c",
        LIST_OBJECTS,
        bucket,
        prefix,
        *store,
    )
    return set(out.split())


def check_liveness() -> str:
    http(f"{LITELLM_URL}/health/liveliness")
    return LITELLM_URL


def check_chat() -> str:
    key = base64.b64decode(
        kubectl(
            "get",
            "secret",
            f"{RELEASE}-litellm-keys",
            "--output",
            "jsonpath={.data.master-key}",
        )
    ).decode()
    before_chat["logs"] = list_objects("litellm-logs", "logs/")
    before_chat["time_ms"] = int(time.time() * 1000)
    reply = json.loads(
        http(
            f"{LITELLM_URL}/v1/chat/completions",
            body={
                "model": "mock-gpt",
                "messages": [{"role": "user", "content": "ping"}],
            },
            key=key,
        )
    )
    return reply["choices"][0]["message"]["content"]


def check_mlflow() -> str:
    return http(f"{MLFLOW_URL}/health").decode().strip()


def check_mlflow_trace() -> str:
    # Callbacks run after the response is returned, so allow them a moment.
    for _ in range(10):
        found = json.loads(
            http(f"{MLFLOW_URL}/api/2.0/mlflow/traces?experiment_ids=0&max_results=5")
        )
        # Allow a few seconds of clock difference between host and cluster.
        fresh = [
            trace
            for trace in found.get("traces", [])
            if trace["timestamp_ms"] >= before_chat["time_ms"] - 5000
        ]
        if fresh:
            return fresh[0]["request_id"]
        time.sleep(2)
    raise RuntimeError(
        "no trace for this request reached the MLflow Default experiment"
    )


def check_mlflow_artifact() -> str:
    run_id = kubectl(
        "exec",
        f"deploy/{RELEASE}-mlflow",
        "--container",
        "mlflow",
        "--",
        "python",
        "-c",
        LOG_ARTIFACT,
    ).splitlines()[-1]
    stored = [key for key in list_objects("mlflow", "") if run_id in key]
    if not stored:
        raise RuntimeError(f"run {run_id} left no object in the mlflow bucket")
    return f"mlflow/{stored[0]}"


def check_request_log() -> str:
    for _ in range(10):
        new = list_objects("litellm-logs", "logs/") - before_chat["logs"]
        if new:
            return f"litellm-logs/{sorted(new)[0]}"
        time.sleep(2)
    raise RuntimeError("no request log for this request reached litellm-logs/logs/")


def check_redis() -> str:
    info = kubectl(
        "exec",
        f"deploy/{RELEASE}-redis",
        "--",
        "sh",
        "-c",
        'valkey-cli --no-auth-warning -a "$REDIS_PASSWORD" client list',
    )
    # Every line is one connection; the valkey-cli call itself is one of them.
    others = [line for line in info.splitlines() if "cmd=client|list" not in line]
    if not others:
        raise RuntimeError("LiteLLM has no connection to Redis")
    return f"{len(others)} client connection(s) besides this check"


def secret_value(secret: str, key: str) -> str:
    encoded = kubectl("get", "secret", secret, "--output", f"jsonpath={{.data.{key}}}")
    return base64.b64decode(encoded).decode()


def backup_store() -> tuple[str, str, str]:
    """Endpoint and keys of the backup store, as the backup job is given them."""
    endpoint = kubectl(
        "get",
        "cronjob",
        f"{RELEASE}-backup-litellm",
        "--output",
        "jsonpath={.spec.jobTemplate.spec.template.spec.containers[0]"
        '.env[?(@.name=="AWS_ENDPOINT_URL")].value}',
    )
    return (
        endpoint,
        secret_value("llmoxie-backup-storage", "access-key"),
        secret_value("llmoxie-backup-storage", "secret-key"),
    )


def check_backup() -> str:
    job = f"smoke-backup-{int(time.time())}"
    store = backup_store()
    before = list_objects("backups", "litellm_db/", *store)
    kubectl("create", "job", job, f"--from=cronjob/{RELEASE}-backup-litellm")
    try:
        kubectl("wait", f"job/{job}", "--for=condition=complete", "--timeout=180s")
    except RuntimeError:
        logs = kubectl("logs", f"job/{job}", "--tail=20")
        raise RuntimeError(f"backup job did not complete:\n{logs}") from None
    finally:
        kubectl("delete", "job", job, "--ignore-not-found", "--wait=false")
    new = list_objects("backups", "litellm_db/", *store) - before
    if not new:
        raise RuntimeError("the backup job wrote nothing under backups/litellm_db/")
    return f"{store[0]} backups/{sorted(new)[0]}"


CHECKS = [
    ("LiteLLM is live", check_liveness),
    ("chat completion through the mock model", check_chat),
    ("MLflow is healthy", check_mlflow),
    ("MLflow recorded a trace", check_mlflow_trace),
    ("MLflow stored an artifact", check_mlflow_artifact),
    ("request log reached object storage", check_request_log),
    ("LiteLLM is connected to Redis", check_redis),
    ("backup job wrote a dump", check_backup),
]


def main() -> int:
    failed = 0
    for name, check in CHECKS:
        try:
            detail = check()
        except Exception as exc:  # report every check, then fail
            failed += 1
            print(f"FAIL  {name}: {exc}")
        else:
            print(f"ok    {name}: {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
