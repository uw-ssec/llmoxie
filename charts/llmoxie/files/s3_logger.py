"""Custom LiteLLM callback that writes request/response JSON to S3-compatible storage.

PROTOTYPE for #236. It writes the same record under the same key layout as
adl_logger.py does on Azure Blob, so tools that read those logs work on either
store.

Required env vars:
  LLMOXIE_LOG_BUCKET  - Bucket name
The standard AWS variables supply the rest: AWS_ACCESS_KEY_ID,
AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION and, for an S3-compatible server such
as RustFS, AWS_ENDPOINT_URL.

Key layout: <bucket>/logs/<yyyy>/<mm>/<dd>/<request_id>.json
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from typing import Any

import boto3
import litellm
from botocore.exceptions import ClientError
from litellm.integrations.custom_logger import CustomLogger

_handler = logging.StreamHandler(sys.stderr)
_handler.setFormatter(logging.Formatter("[S3Logger] %(levelname)s - %(message)s"))
logger = logging.getLogger(__name__)
logger.addHandler(_handler)
logger.setLevel(logging.INFO)
logger.propagate = False


class S3Logger(CustomLogger):
    """CustomLogger implementation that writes one object per request to S3."""

    def __init__(self) -> None:
        self._bucket = os.environ["LLMOXIE_LOG_BUCKET"]
        self._client = boto3.client("s3")
        try:
            self._ensure_bucket()
        except Exception as exc:
            # Storage may still be starting; _put retries the bucket later.
            logger.error("Could not check bucket '%s': %s", self._bucket, exc)

    def _ensure_bucket(self) -> None:
        """Create the bucket only when it is missing."""
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in ("404", "NoSuchBucket"):
                raise
            self._client.create_bucket(Bucket=self._bucket)
            logger.info("Bucket '%s' created", self._bucket)

    def _put(self, key: str, body: bytes) -> None:
        try:
            self._client.put_object(
                Bucket=self._bucket, Key=key, Body=body, ContentType="application/json"
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "NoSuchBucket":
                raise
            self._ensure_bucket()
            self._client.put_object(
                Bucket=self._bucket, Key=key, Body=body, ContentType="application/json"
            )

    async def async_log_success_event(
        self,
        kwargs: dict,
        response_obj: Any,
        start_time: datetime,
        end_time: datetime,
    ) -> None:
        try:
            slo = kwargs.get("standard_logging_object") or {}
            request_id = (
                slo.get("id") or f"{os.getpid()}_{start_time.strftime('%H%M%S%f')}"
            )
            record = {
                "timestamp_start": start_time.isoformat(),
                "timestamp_end": end_time.isoformat(),
                "kwargs": kwargs,
                "response": (
                    response_obj.model_dump()
                    if hasattr(response_obj, "model_dump")
                    else None
                ),
                "cost": litellm.completion_cost(completion_response=response_obj),
            }
            key = (
                f"logs/{start_time.year}/{start_time.month:02d}"
                f"/{start_time.day:02d}/{request_id}.json"
            )
            body = json.dumps(record, default=str).encode("utf-8")
            # boto3 is synchronous; keep the upload off the event loop.
            await asyncio.to_thread(self._put, key, body)
        except Exception as exc:
            logger.error("Failed to write to S3: %s", exc)


proxy_handler_instance = S3Logger()
