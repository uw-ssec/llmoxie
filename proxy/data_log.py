"""
Data logging module for proxy requests and responses.

Supports logging to local filesystem or Azure Blob Storage using fsspec.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import fsspec  # type: ignore

handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter(
    '[DataLogger] %(levelname)s - %(message)s'
))

logger = logging.getLogger(__name__)
logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False  # Don't propagate to root logger


class DataLogger:
    """Handles logging of request/response data to storage."""

    def __init__(self):
        """Initialize the data logger with configuration from environment."""
        self.storage_type = os.getenv("STORAGE_TYPE", "local")

        logger.info("Initializing DataLogger with storage type: %s", self.storage_type)
        # Build storage path
        if self.storage_type == "azure":
            azure_account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
            azure_account_key = os.getenv("AZURE_STORAGE_ACCOUNT_KEY")
            azure_container = os.getenv("AZURE_STORAGE_CONTAINER", "proxy-logs")
            if not azure_account_name:
                raise ValueError(
                    "AZURE_STORAGE_ACCOUNT_NAME is required when STORAGE_TYPE=azure"
                )
            # fsspec Azure path format
            self.base_path = f"az://{azure_container}"
            self.storage_options = {
                "account_name": azure_account_name,
            }
            if azure_account_key:
                self.storage_options["account_key"] = azure_account_key
        else:
            self.base_path = os.getenv("LOCAL_LOG_DIR", "logs")
            self.storage_options = {}

        # Create filesystem instance
        self.fs = fsspec.filesystem(
            "az" if self.storage_type == "azure" else "file",
            **self.storage_options
        )

        # Ensure base directory/container exists
        try:
            self.fs.makedirs(self.base_path, exist_ok=True)
        except (OSError, IOError) as e:
            # Some filesystems or remote providers may raise OS-related errors
            # when the directory/container already exists or cannot be created;
            # log at debug level so it can be inspected if needed.
            logger.debug("Could not create base path '%s': %s", self.base_path, e)

    def _get_log_filename(self, model: Optional[str] = None, user_id: Optional[str] = None) -> str:
        """
        Generate log filename based on user, model and date.

        Args:
            model: Model name from request (e.g., "gpt-4")
            user_id: Optional user ID from authentication

        Returns:
            Filename in format: {user_id}_{model}_{YYYYMMDD}.jsonl (if user_id provided)
                           or: {model}_{YYYYMMDD}.jsonl (if no user_id)
        """
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        model_name = model.replace("/", "_") if model else "unknown"
        
        if user_id:
            return f"{user_id}_{model_name}_{date_str}.jsonl"
        else:
            return f"{model_name}_{date_str}.jsonl"

    def _get_full_path(self, filename: str) -> str:
        return f"{self.base_path}/{filename}"

    def log_entry(self, log_entry: Dict[str, Any]) -> None:
        """
        Append a log entry to storage.

        Args:
            log_entry: Dictionary containing request/response data
        """
        logger.debug("Logging entry: %s", log_entry)
        # Extract model from request body
        model = None
        if log_entry.get("request", {}).get("body"):
            body = log_entry["request"]["body"]
            if isinstance(body, dict):
                model = body.get("model")
        
        # Extract user_id if present
        user_id = log_entry.get("user_id")

        filename = self._get_log_filename(model, user_id)
        full_path = self._get_full_path(filename)
        log_line = json.dumps(log_entry) + '\n'

        try:
            # Append to file (fsspec handles both local and Azure)
            with self.fs.open(full_path, 'a', encoding='utf-8') as f:
                f.write(log_line)
        except (OSError, IOError) as e:
            logger.error("Error logging to storage: %s", e)

    def create_log_entry(
        self,
        method: str,
        path: str,
        request_headers: Dict[str, str],
        request_body: Any,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a log entry structure for a request.

        Args:
            method: HTTP method
            path: Request path
            request_headers: Request headers
            request_body: Parsed request body
            user_id: Optional user ID from authentication

        Returns:
            Log entry dictionary with request data
        """
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "request": {
                "method": method,
                "path": path,
                "headers": request_headers,
                "body": request_body,
            },
            "response": {},
        }
        
        # Add user_id if provided
        if user_id:
            entry["user_id"] = user_id
        
        return entry

    def add_response_to_entry(
        self,
        log_entry: Dict[str, Any],
        status_code: int,
        response_headers: Dict[str, str],
        response_body: Any,
        streaming: bool = False,
    ) -> None:
        """
        Add response data to an existing log entry.

        Args:
            log_entry: Log entry to update
            status_code: HTTP status code
            response_headers: Response headers
            response_body: Parsed response body
            streaming: Whether the response was streamed
        """
        log_entry["response"] = {
            "status_code": status_code,
            "headers": response_headers,
            "body": response_body,
            "streaming": streaming,
        }
