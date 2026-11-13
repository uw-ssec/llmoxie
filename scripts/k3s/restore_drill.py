"""Restore drill for the local stack (prototype for #236).

Answers one question: after the main cluster is lost, can the LiteLLM service be
brought back from the backup cluster, and what else has to be kept to do it?

WARNING: this deletes the main local cluster (``llmoxie``) and its data. The
backup cluster (``llmoxie-backup``) is left alone.

Steps:

1. Seed LiteLLM: a virtual key, and a model stored in the database with a
   provider credential (LiteLLM encrypts that with the salt key).
2. Run the backup job, so the dump lands in the backup cluster.
3. Delete the main cluster and build a new one. The chart generates a new
   master key and a new salt key there.
4. Restore ``litellm_db`` from the dump, with LiteLLM stopped.
5. Check what works with both keys new, then put only the old salt key back
   and check again. The master key stays new throughout.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error

from smoke import (
    LITELLM_URL,
    RELEASE,
    ROOT,
    backup_store,
    http,
    kubectl,
    list_objects,
    secret_value,
)

KEYS_SECRET = f"{RELEASE}-litellm-keys"
DB_MODEL = "db-mock"
DB_MODEL_REPLY = "Hello from a model stored in the database"

RESTORE_SCRIPT = """
set -e
python -c "
import os, s3fs
fs = s3fs.S3FileSystem(client_kwargs={'endpoint_url': os.environ['AWS_ENDPOINT_URL']})
fs.get(os.environ['DUMP_KEY'], '/tmp/restore.dump')
print('downloaded', os.path.getsize('/tmp/restore.dump'), 'bytes')
"
pg_restore --clean --if-exists --no-owner --no-privileges \\
    --dbname "$DATABASE_URL" /tmp/restore.dump
echo restore finished
"""


def say(message: str) -> None:
    print(f"\n== {message}", flush=True)


def wait_live(timeout: int = 600) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            http(f"{LITELLM_URL}/health/liveliness")
            return
        except Exception:
            time.sleep(3)
    raise RuntimeError("LiteLLM did not come up")


def chat(key: str, model: str) -> str:
    """Return the reply, or a short description of the failure."""
    try:
        reply = json.loads(
            http(
                f"{LITELLM_URL}/v1/chat/completions",
                body={
                    "model": model,
                    "messages": [{"role": "user", "content": "ping"}],
                },
                key=key,
            )
        )
        return "OK: " + reply["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace").replace("\n", " ")
        return f"HTTP {exc.code}: {detail[:160]}"
    except (urllib.error.URLError, ConnectionError) as exc:
        # A pod being replaced can drop the connection; callers retry.
        return f"no connection: {exc}"


def chat_when_ready(key: str, model: str, attempts: int = 20) -> str:
    """A model added to the database takes a moment to reach the router."""
    result = ""
    for _ in range(attempts):
        result = chat(key, model)
        if result.startswith("OK"):
            break
        time.sleep(3)
    return result


def seed(master_key: str) -> str:
    alias = f"restore-drill-{int(time.time())}"
    key = json.loads(
        http(f"{LITELLM_URL}/key/generate", body={"key_alias": alias}, key=master_key)
    )["key"]
    http(
        f"{LITELLM_URL}/model/new",
        body={
            "model_name": DB_MODEL,
            "litellm_params": {
                "model": f"openai/{DB_MODEL}",
                "api_key": "provider-credential-for-the-drill",
                "mock_response": DB_MODEL_REPLY,
            },
        },
        key=master_key,
    )
    print(f"virtual key alias: {alias}")
    print("virtual key, config model:   ", chat(key, "mock-gpt"))
    print("virtual key, database model: ", chat_when_ready(key, DB_MODEL))
    return key


def run_backup() -> str:
    store = backup_store()
    before = list_objects("backups", "litellm_db/", *store)
    job = f"drill-backup-{int(time.time())}"
    kubectl("create", "job", job, f"--from=cronjob/{RELEASE}-backup-litellm")
    wait_for_job(job)
    kubectl("delete", "job", job, "--wait=false")
    dump = sorted(list_objects("backups", "litellm_db/", *store) - before)[0]
    print(f"dump: backups/{dump}")
    return f"backups/{dump}"


def rebuild_main_cluster() -> None:
    subprocess.run(["k3d", "cluster", "delete", "llmoxie"], check=True)
    subprocess.run(["bash", str(ROOT / "scripts" / "k3s" / "up.sh")], check=True)
    wait_live()


def scale_litellm(replicas: int) -> None:
    kubectl("scale", f"deployment/{RELEASE}-litellm", f"--replicas={replicas}")
    if replicas:
        kubectl("rollout", "status", f"deployment/{RELEASE}-litellm", "--timeout=600s")
        wait_live()
    else:
        try:
            kubectl(
                "wait",
                "pod",
                "--selector=app.kubernetes.io/component=litellm",
                "--for=delete",
                "--timeout=120s",
            )
        except RuntimeError:
            pass  # kubectl reports an error when the pods are already gone


def wait_for_job(job: str, timeout: int = 300) -> None:
    """Return when the job succeeds; raise as soon as it fails."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = json.loads(kubectl("get", "job", job, "--output", "json"))["status"]
        if status.get("succeeded"):
            return
        if status.get("failed"):
            raise RuntimeError(f"job {job} failed")
        time.sleep(3)
    raise RuntimeError(f"job {job} did not finish in {timeout} s")


def restore(dump_key: str) -> None:
    cronjob = json.loads(
        kubectl("get", "cronjob", f"{RELEASE}-backup-litellm", "--output", "json")
    )
    backup = cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    job = f"drill-restore-{int(time.time())}"
    manifest = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": job},
        "spec": {
            "backoffLimit": 0,
            "template": {
                "spec": {
                    "restartPolicy": "Never",
                    "enableServiceLinks": False,
                    "containers": [
                        {
                            "name": "restore",
                            "image": backup["image"],
                            "command": ["sh", "-c", RESTORE_SCRIPT],
                            # Same database and storage settings as the backup job.
                            "env": [
                                *backup["env"],
                                {"name": "DUMP_KEY", "value": dump_key},
                            ],
                        }
                    ],
                }
            },
        },
    }
    subprocess.run(
        [
            str(ROOT / "scripts" / "k3s" / "bin" / "kubectl"),
            "--kubeconfig",
            str(ROOT / ".kube" / "llmoxie-k3s.yaml"),
            "--namespace",
            "llmoxie",
            "apply",
            "--filename",
            "-",
        ],
        input=json.dumps(manifest),
        text=True,
        check=True,
    )
    try:
        wait_for_job(job)
    finally:
        print(kubectl("logs", f"job/{job}", "--tail=15"))


def set_salt_key(value: str) -> None:
    kubectl(
        "patch",
        "secret",
        KEYS_SECRET,
        "--type=merge",
        "--patch",
        json.dumps({"stringData": {"salt-key": value}}),
    )
    kubectl("rollout", "restart", f"deployment/{RELEASE}-litellm")
    kubectl("rollout", "status", f"deployment/{RELEASE}-litellm", "--timeout=600s")
    wait_live()


def main() -> int:
    say("1. Seed LiteLLM")
    old_master = secret_value(KEYS_SECRET, "master-key")
    old_salt = secret_value(KEYS_SECRET, "salt-key")
    virtual_key = seed(old_master)

    say("2. Back up litellm_db to the backup cluster")
    dump_key = run_backup()

    say("3. Delete the main cluster and build a new one")
    rebuild_main_cluster()
    print("master key changed:", secret_value(KEYS_SECRET, "master-key") != old_master)
    print("salt key changed:  ", secret_value(KEYS_SECRET, "salt-key") != old_salt)
    print("virtual key before restore:  ", chat(virtual_key, "mock-gpt"))

    say("4. Restore litellm_db with LiteLLM stopped")
    scale_litellm(0)
    restore(dump_key)
    scale_litellm(1)

    say("5a. After restore, with a NEW master key and a NEW salt key")
    print("virtual key, config model:   ", chat(virtual_key, "mock-gpt"))
    print(
        "virtual key, database model: ",
        chat_when_ready(virtual_key, DB_MODEL, attempts=8),
    )

    say("5b. After restore, with the OLD salt key put back (master key still new)")
    set_salt_key(old_salt)
    print(
        "master key still new:", secret_value(KEYS_SECRET, "master-key") != old_master
    )
    config_model = chat_when_ready(virtual_key, "mock-gpt")
    database_model = chat_when_ready(virtual_key, DB_MODEL)
    print("virtual key, config model:   ", config_model)
    print("virtual key, database model: ", database_model)

    recovered = config_model.startswith("OK") and database_model.startswith("OK")
    say(
        "LiteLLM service recovered"
        if recovered
        else "LiteLLM service NOT fully recovered"
    )
    return 0 if recovered else 1


if __name__ == "__main__":
    sys.exit(main())
