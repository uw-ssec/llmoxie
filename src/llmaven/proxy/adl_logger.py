"""Custom LiteLLM callback that writes request/response JSON to Azure Data Lake Storage Gen2.

Required env vars:
  AZURE_STORAGE_CONNECTION_STRING  - Full connection string
Optional env vars:
  ADLS_CONTAINER                   - Blob container name (default: litellm-logs)

Log path layout: <container>/logs/<yyyy>/<mm>/<dd>/<request_id>.json

One file per request, written atomically via BlobClient.upload_blob().
The filename is the standard_logging_object["id"] (e.g. "chatcmpl-abc123"),
guaranteeing uniqueness without any coordination across workers or replicas.
"""

import json
import logging
import os
import sys
from datetime import datetime
from typing import Any

import litellm
from azure.core.exceptions import ResourceExistsError
from azure.storage.blob.aio import BlobClient
from azure.storage.blob import ContainerClient
from litellm.integrations.custom_logger import CustomLogger

# Configure logger with a StreamHandler so output appears in `docker compose logs`
_handler = logging.StreamHandler(sys.stderr)
_handler.setFormatter(logging.Formatter("[AdlLogger] %(levelname)s - %(message)s"))
logger = logging.getLogger(__name__)
logger.addHandler(_handler)
logger.setLevel(logging.INFO)
logger.propagate = False  # Don't propagate to root logger


class AdlLogger(CustomLogger):
    """
    CustomLogger implementation that writes logs to Azure Data Lake Storage Gen2.
    """

    def __init__(self) -> None:
        self._container = os.environ.get("ADLS_CONTAINER", "litellm-logs")
        self._connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")

        if not self._connection_string:
            raise ValueError(
                "AZURE_STORAGE_CONNECTION_STRING must be set for AdlLogger to authenticate with Azure Storage"
            )
        # Local dev: Azurite with connection string
        logger.info("AdlLogger initialized with AZURE_STORAGE_CONNECTION_STRING")
        # Create container synchronously on startup (not in async context)
        self._ensure_container_sync(self._connection_string)

    def _ensure_container_sync(self, connection_string: str) -> None:
        """Create container if it doesn't exist (sync, called during __init__)."""
        try:
            container_client = ContainerClient.from_connection_string(
                connection_string, self._container
            )
            container_client.create_container()
            logger.info("Container '%s' created", self._container)
        except ResourceExistsError:
            pass  # Already exists — fine
        except Exception as e:
            logger.error("Could not create container '%s': %s", self._container, e)

    def _record_path(self, request_id: str, start_time: datetime) -> str:
        return (
            f"logs/{start_time.year}/{start_time.month:02d}"
            f"/{start_time.day:02d}/{request_id}.json"
        )

    async def _get_blob_client(self, blob_name: str) -> BlobClient:
        """Get a BlobClient for the given blob name using the configured auth method."""
        return BlobClient.from_connection_string(
            self._connection_string,
            container_name=self._container,
            blob_name=blob_name,
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
            logger.info("Logging request_id '%s' to ADLS", request_id)
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
            blob_data = json.dumps(record, default=str).encode("utf-8")

            async with await self._get_blob_client(
                self._record_path(request_id, start_time)
            ) as blob_client:
                await blob_client.upload_blob(blob_data, overwrite=True)
        except Exception as exc:
            logger.error("Failed to write to ADLS: %s", exc)


proxy_handler_instance = AdlLogger()
