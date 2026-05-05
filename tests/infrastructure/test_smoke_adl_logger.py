"""Smoke test for AdlLogger integration with LiteLLM and Azurite.

Sends a chat completion request through the LiteLLM proxy, then reads back
the JSON log file that AdlLogger wrote to Azurite.

Prerequisites:
  cd docker && docker compose up -d
  Valid Azure OpenAI credentials in docker/.env

Run:
  pytest tests/infrastructure/test_smoke_adl_logger.py -v
"""

import json
import os
import time
from datetime import datetime

import httpx
from azure.storage.blob import BlobClient

# Environment configuration
LITELLM_URL = os.environ.get("LITELLM_URL", "http://localhost:4000")
LITELLM_KEY = os.environ.get("LITELLM_KEY", "sk-1234")
MODEL = os.environ.get("MODEL", "azure/gpt-5-mini")
ADLS_CONTAINER = os.environ.get("ADLS_CONTAINER", "litellm-logs")
AZURITE_CONN_STR = os.environ.get(
    "AZURITE_CONN_STR",
    "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://localhost:10000/devstoreaccount1;",
)


def send_chat_completion_request() -> dict:
    """Send a chat completion request to LiteLLM and return the response."""
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            f"{LITELLM_URL}/v1/chat/completions",
            headers={"Authorization": f"Bearer {LITELLM_KEY}"},
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": "Say hello in one word."}],
                "max_tokens": 120,
            },
        )
        response.raise_for_status()
        return response.json()


def read_log_from_azurite(request_id: str, date_str: str) -> dict:
    """Read the logged request from Azurite blob storage."""
    blob_name = f"logs/{date_str}/{request_id}.json"
    blob_client = BlobClient.from_connection_string(
        AZURITE_CONN_STR,
        container_name=ADLS_CONTAINER,
        blob_name=blob_name,
    )
    blob_data = blob_client.download_blob().readall()
    return json.loads(blob_data)


def test_adl_logger_smoke_test():
    """Verify AdlLogger successfully logs LiteLLM requests to Azurite."""
    # 1. Send request
    print(f"→ POST {LITELLM_URL}/v1/chat/completions (model: {MODEL})")
    response = send_chat_completion_request()
    print(f"← Response: {json.dumps(response, indent=2)[:500]}...")

    # 2. Extract request ID and build expected path
    request_id = response["id"]
    today = datetime.utcnow().strftime("%Y/%m/%d")
    expected_blob = f"logs/{today}/{request_id}.json"

    print(f"Request ID: {request_id}")
    print(f"Expected blob: {expected_blob}")

    # 3. Wait for async logger to complete
    time.sleep(1)

    # 4. Read log from Azurite
    print(f"→ Reading log from Azurite...")
    log_data = read_log_from_azurite(request_id, today)
    print(f"✓ Log record for {request_id}:")
    print(json.dumps(log_data, indent=2, default=str)[:1000])

    # 5. Verify structure
    assert "timestamp_start" in log_data, "Missing timestamp_start"
    assert "timestamp_end" in log_data, "Missing timestamp_end"
    assert "kwargs" in log_data, "Missing kwargs"
    assert "response" in log_data, "Missing response"
    assert "cost" in log_data, "Missing cost"
    assert log_data["response"]["id"] == request_id, "Request ID mismatch"


if __name__ == "__main__":
    test_adl_logger_smoke_test()
