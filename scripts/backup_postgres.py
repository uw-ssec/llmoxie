"""Backup a PostgreSQL database to cloud storage (S3 or Azure Blob) via fsspec.

Streams pg_dump stdout directly to the destination — no local disk writes.
Destination URL controls the backend:
  az://container/prefix/     → Azure Blob (adlfs)
  s3://bucket/prefix/        → AWS S3 (s3fs)
"""

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse

import fsspec
import yaml


def _load_config(config_path: str) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def _parse_db_name(db_url: str) -> str:
    name = urlparse(db_url).path.lstrip("/")
    if not name:
        raise ValueError(f"Could not parse database name from connection string")
    return name


def _storage_options(destination: str) -> dict:
    """Build fsspec storage_options from env vars based on destination URL scheme."""
    scheme = destination.split("://")[0]
    if scheme in ("az", "abfs"):
        # AZURE_STORAGE_CONNECTION_STRING takes priority — used for Azurite and
        # other non-cloud endpoints where the endpoint URL differs from the default.
        conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        if conn_str:
            return {"connection_string": conn_str}
        opts = {}
        account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
        account_key = os.getenv("AZURE_STORAGE_ACCOUNT_KEY")
        if account_name:
            opts["account_name"] = account_name
        if account_key:
            opts["account_key"] = account_key
        return opts
    # S3: boto3 picks up AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY automatically.
    # AWS_ENDPOINT_URL overrides the endpoint — used for MinIO and other S3-compatible stores.
    endpoint_url = os.getenv("AWS_ENDPOINT_URL")
    if endpoint_url:
        return {"endpoint_url": endpoint_url}
    return {}


def backup(config_path: str | None = None) -> None:
    if config_path:
        config = _load_config(config_path)
        pg_cfg = config["pg_backup"]
        db_url_env = pg_cfg.get("database_url_env", "DATABASE_URL")
        db_url = os.environ[db_url_env]
        destination = pg_cfg["destination"].rstrip("/") + "/"
        keep_last_n = int(pg_cfg.get("keep_last_n", 7))
    else:
        # Env-var mode — used by the Container Apps Job
        db_url = os.environ["DATABASE_URL"]
        destination = os.environ["BACKUP_DESTINATION"].rstrip("/") + "/"
        keep_last_n = int(os.getenv("BACKUP_KEEP_LAST_N", "7"))

    db_name = _parse_db_name(db_url)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    dest_key = f"{destination}{db_name}/{timestamp}.dump"

    storage_opts = _storage_options(destination)

    print(f"Backing up '{db_name}' → {dest_key}")

    proc = subprocess.Popen(
        ["pg_dump", "--format=custom", "--no-password", db_url],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        with fsspec.open(dest_key, "wb", **storage_opts) as f:
            shutil.copyfileobj(proc.stdout, f)
    finally:
        proc.stdout.close()

    stderr_out = proc.stderr.read()
    proc.stderr.close()
    proc.wait()

    if proc.returncode != 0:
        raise RuntimeError(
            f"pg_dump exited {proc.returncode}:\n{stderr_out.decode(errors='replace')}"
        )

    print(f"Upload complete.")

    # Prune backups beyond keep_last_n
    fs, root = fsspec.core.url_to_fs(destination, **storage_opts)
    prefix = root.rstrip("/") + f"/{db_name}/"

    try:
        entries = sorted(fs.ls(prefix, detail=False))
    except FileNotFoundError:
        entries = []

    if len(entries) > keep_last_n:
        for old in entries[:-keep_last_n]:
            fs.rm(old)
            print(f"Deleted old backup: {old}")

    retained = min(len(entries), keep_last_n)
    print(f"Done. Retained {retained} backup(s) under {destination}{db_name}/")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stream a pg_dump backup to cloud storage (S3 or Azure Blob)"
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to YAML config file. Omit to read all settings from env vars "
             "(DATABASE_URL, BACKUP_DESTINATION, BACKUP_KEEP_LAST_N).",
    )
    args = parser.parse_args()

    try:
        backup(args.config)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
