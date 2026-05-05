"""Custom LiteLLM callback that writes request/response JSON to Azure Data Lake Storage Gen2.

Authentication:
  - Production: DefaultAzureCredential (managed identity in Azure Container Apps)
  - Local dev:  AZURE_STORAGE_CONNECTION_STRING pointing at Azurite

Required env vars (production):
  ADLS_ACCOUNT_NAME  - Azure Storage account name (ignored when
                       AZURE_STORAGE_CONNECTION_STRING is set)

Optional env vars:
  AZURE_STORAGE_CONNECTION_STRING  - Full connection string; takes precedence
                                     over ADLS_ACCOUNT_NAME + managed identity
  ADLS_CONTAINER                   - Blob container name (default: litellm-logs)

Log path layout: <container>/logs/<yyyy>/<mm>/<dd>/<request_id>.json

One file per request, written atomically via BlobClient.upload_blob().
The filename is the standard_logging_object["id"] (e.g. "chatcmpl-abc123"),
guaranteeing uniqueness without any coordination across workers or replicas.
Uses the official Azure SDK (azure-storage-blob) directly — native async,
no private APIs, no fsspec event loop conflicts.
"""

import json
import logging
import os
import sys
from datetime import datetime
from typing import Any

import litellm
from azure.core.exceptions import ResourceExistsError
from azure.identity.aio import DefaultAzureCredential as AsyncDefaultAzureCredential
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

        if self._connection_string:
            # Local dev: Azurite with connection string
            logger.info("AdlLogger initialized with AZURE_STORAGE_CONNECTION_STRING")
            # Create container synchronously on startup (not in async context)
            self._ensure_container_sync(self._connection_string)
        else:
            # Production: managed identity via AsyncDefaultAzureCredential
            self._account_name = os.environ["ADLS_ACCOUNT_NAME"]
            self._credential = AsyncDefaultAzureCredential()
            logger.info(
                "AdlLogger initialized with ADLS_ACCOUNT_NAME '%s'", self._account_name
            )
            # Container is pre-created by Pulumi; no need to create it here

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
        if self._connection_string:
            return BlobClient.from_connection_string(
                self._connection_string,
                container_name=self._container,
                blob_name=blob_name,
            )
        else:
            # managed_identity
            assert self._credential and self._account_name, (
                "Credential and account name must be set for managed identity auth"
            )
            return BlobClient(
                account_url=f"https://{self._account_name}.blob.core.windows.net",
                container_name=self._container,
                blob_name=blob_name,
                credential=self._credential,
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
