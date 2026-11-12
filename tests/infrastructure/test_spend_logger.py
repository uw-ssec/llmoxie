"""Tests for the LiteLLM spend logger callback (loaded without LiteLLM)."""

import asyncio
import io
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

LOGGER_PATH = (
    Path(__file__).parents[2] / "src/llmaven/infrastructure/resources/spend_logger.py"
)
HEX_HASH = "a" * 64


@pytest.fixture
def spend_logger(monkeypatch):
    custom_logger = types.ModuleType("litellm.integrations.custom_logger")
    custom_logger.CustomLogger = type("CustomLogger", (), {})
    monkeypatch.setitem(sys.modules, "litellm", types.ModuleType("litellm"))
    monkeypatch.setitem(
        sys.modules, "litellm.integrations", types.ModuleType("litellm.integrations")
    )
    monkeypatch.setitem(
        sys.modules, "litellm.integrations.custom_logger", custom_logger
    )
    spec = importlib.util.spec_from_file_location("spend_logger", LOGGER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _payload(**overrides):
    payload = {
        "id": "req-1",
        "model": "gpt-4o",
        "response_cost": 0.0123,
        "total_tokens": 4567,
        "messages": [{"role": "user", "content": "SECRET PROMPT"}],
        "response": {"choices": [{"message": {"content": "SECRET RESPONSE"}}]},
        "metadata": {
            "user_api_key_alias": "alice-key",
            "user_api_key_hash": HEX_HASH,
            "user_api_key_user_id": "alice",
            "user_api_key_team_alias": "team-a",
        },
    }
    payload.update(overrides)
    return payload


def _emit(module, kwargs):
    asyncio.run(
        module.proxy_handler_instance.async_log_success_event(kwargs, None, None, None)
    )


def _only_line(out: str) -> dict:
    [line] = out.splitlines()
    assert line.startswith("LLMOXIE_SPEND ")
    return json.loads(line[len("LLMOXIE_SPEND ") :])


def test_prefix_is_fourteen_characters(spend_logger):
    assert len(spend_logger.SPEND_LINE_PREFIX) == 14


def test_success_prints_one_spend_line(spend_logger, capsys):
    _emit(spend_logger, {"standard_logging_object": _payload(), "api_key": "sk-raw"})
    record = _only_line(capsys.readouterr().out)
    assert set(record) == {
        "ts",
        "request_id",
        "key_alias",
        "key_hash",
        "user_id",
        "team_alias",
        "model",
        "spend",
        "total_tokens",
    }
    assert record["request_id"] == "req-1"
    assert record["key_alias"] == "alice-key"
    assert record["key_hash"] == HEX_HASH
    assert record["user_id"] == "alice"
    assert record["team_alias"] == "team-a"
    assert record["model"] == "gpt-4o"
    assert record["spend"] == pytest.approx(0.0123)
    assert record["total_tokens"] == 4567


def test_line_never_carries_prompt_response_or_raw_key(spend_logger, capsys):
    _emit(spend_logger, {"standard_logging_object": _payload(), "api_key": "sk-raw"})
    out = capsys.readouterr().out
    for secret in ("SECRET PROMPT", "SECRET RESPONSE", "sk-raw", "messages"):
        assert secret not in out


@pytest.mark.parametrize(
    "raw",
    ["litellm_proxy_master_key", "my-raw-bearer-token", "A" * 64, "a" * 63, 123],
)
def test_non_sha256_key_hash_is_dropped(spend_logger, capsys, raw):
    payload = _payload()
    payload["metadata"]["user_api_key_hash"] = raw
    _emit(spend_logger, {"standard_logging_object": payload})
    out = capsys.readouterr().out
    record = _only_line(out)
    assert record["key_hash"] is None
    assert record["key_alias"] == "alice-key"
    if isinstance(raw, str):
        assert raw not in out


def test_missing_metadata_and_cost_do_not_raise(spend_logger, capsys):
    payload = _payload(response_cost=None, metadata=None)
    del payload["total_tokens"]
    _emit(spend_logger, {"standard_logging_object": payload})
    record = _only_line(capsys.readouterr().out)
    assert record["spend"] == 0.0
    assert record["total_tokens"] == 0
    assert record["key_alias"] is None
    assert record["key_hash"] is None


def test_no_standard_logging_object_prints_nothing(spend_logger, capsys):
    _emit(spend_logger, {})
    assert capsys.readouterr().out == ""


def test_exception_is_logged_not_raised(spend_logger, capsys, monkeypatch):
    def boom(_payload):
        raise RuntimeError("boom")

    err = io.StringIO()
    monkeypatch.setattr(spend_logger._handler, "stream", err)
    monkeypatch.setattr(spend_logger, "spend_record", boom)
    _emit(spend_logger, {"standard_logging_object": _payload()})
    assert capsys.readouterr().out == ""
    assert "boom" in err.getvalue()
