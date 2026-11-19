"""Tests for the ADLS request logger callback (loaded without LiteLLM or Azure SDKs)."""

import asyncio
import importlib.util
import json
import sys
import types
from datetime import datetime
from pathlib import Path

import pytest

LOGGER_PATH = (
    Path(__file__).parents[2] / "src/llmaven/infrastructure/resources/adl_logger.py"
)
PROVIDER_KEY = "sk-provider-secret-0123456789"
VIRTUAL_KEY = "sk-litellm-virtual-key-abcdef"
HASHED_KEY = "a" * 64


@pytest.fixture
def adl_logger(monkeypatch):
    """The module, with its uploads captured in `module.uploaded`."""
    uploaded: dict[str, bytes] = {}

    class BlobClient:
        def __init__(self, name):
            self.name = name

        @classmethod
        def from_connection_string(cls, conn, container_name, blob_name):
            return cls(blob_name)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def upload_blob(self, data, overwrite):
            uploaded[self.name] = data

    class ContainerClient:
        @classmethod
        def from_connection_string(cls, conn, container):
            return cls()

        def create_container(self):
            pass

    stubs = {
        "litellm": types.ModuleType("litellm"),
        "litellm.integrations": types.ModuleType("litellm.integrations"),
        "litellm.integrations.custom_logger": types.ModuleType(
            "litellm.integrations.custom_logger"
        ),
        "azure": types.ModuleType("azure"),
        "azure.core": types.ModuleType("azure.core"),
        "azure.core.exceptions": types.ModuleType("azure.core.exceptions"),
        "azure.storage": types.ModuleType("azure.storage"),
        "azure.storage.blob": types.ModuleType("azure.storage.blob"),
        "azure.storage.blob.aio": types.ModuleType("azure.storage.blob.aio"),
    }
    stubs["litellm"].completion_cost = lambda completion_response: 0.0
    stubs["litellm.integrations.custom_logger"].CustomLogger = type(
        "CustomLogger", (), {}
    )
    stubs["azure.core.exceptions"].ResourceExistsError = type(
        "ResourceExistsError", (Exception,), {}
    )
    stubs["azure.storage.blob"].ContainerClient = ContainerClient
    stubs["azure.storage.blob.aio"].BlobClient = BlobClient
    for name, module in stubs.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "UseDevelopmentStorage=true")

    spec = importlib.util.spec_from_file_location("adl_logger", LOGGER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.uploaded = uploaded
    return module


def _log(module, kwargs) -> str:
    start = datetime(2026, 11, 18, 12, 0, 0)
    # A private loop: asyncio.run() would leave no current loop behind, which
    # breaks the Pulumi tests that run after this file.
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(
            module.proxy_handler_instance.async_log_success_event(
                kwargs, None, start, start
            )
        )
    finally:
        loop.close()
    (data,) = module.uploaded.values()
    return data.decode("utf-8")


def _kwargs():
    """The parts of LiteLLM's callback kwargs that carry credentials, after a real call."""
    return {
        "model": "openai/gpt-x",
        "messages": [{"role": "user", "content": "PROMPT-MARKER"}],
        "api_key": PROVIDER_KEY,
        "litellm_params": {
            "api_key": PROVIDER_KEY,
            "api_base": "https://api.example.org/v1",
            "metadata": {
                "user_api_key": HASHED_KEY,
                "user_api_key_hash": HASHED_KEY,
                "user_api_key_alias": "alice-key",
                "headers": {"authorization": f"Bearer {VIRTUAL_KEY}"},
            },
        },
        "optional_params": {"extra_headers": {"x-api-key": PROVIDER_KEY}},
        "proxy_server_request": {
            "headers": {"Authorization": f"Bearer {VIRTUAL_KEY}"},
            "body": {"model": "gpt-x"},
        },
        # A credential that also ends up inside a field with an innocent name.
        "original_response": f"request sent with api_key='{PROVIDER_KEY}'",
        "standard_logging_object": {"id": "chatcmpl-1"},
        "usage": {"total_tokens": 12, "completion_tokens": 4},
    }


def test_record_holds_no_credential(adl_logger):
    text = _log(adl_logger, _kwargs())
    assert PROVIDER_KEY not in text
    assert VIRTUAL_KEY not in text
    assert "[redacted]" in text


def test_record_keeps_what_the_logs_are_for(adl_logger):
    record = json.loads(_log(adl_logger, _kwargs()))
    kwargs = record["kwargs"]
    assert kwargs["messages"][0]["content"] == "PROMPT-MARKER"
    assert kwargs["litellm_params"]["api_base"] == "https://api.example.org/v1"
    # LiteLLM's own hashed key ids stay, so records can still be grouped by key.
    metadata = kwargs["litellm_params"]["metadata"]
    assert metadata["user_api_key_hash"] == HASHED_KEY
    assert metadata["user_api_key"] == HASHED_KEY
    assert metadata["user_api_key_alias"] == "alice-key"
    assert kwargs["usage"] == {"total_tokens": 12, "completion_tokens": 4}


def test_record_path_is_unchanged(adl_logger):
    _log(adl_logger, _kwargs())
    assert list(adl_logger.uploaded) == ["logs/2026/11/18/chatcmpl-1.json"]
