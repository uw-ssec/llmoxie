from __future__ import annotations

import json
from pathlib import Path

import pytest

from llmaven.deployment.loadtest import (
    _attempted_fallbacks,
    _extract_request,
    _load_requests,
    _parse_success_body,
    _run_deadline_seconds,
    _served_group,
    preflight_check,
)


def test_extract_request_overrides_model_and_keeps_generation_settings() -> None:
    raw = {
        "model": "old-model",
        "messages": [{"role": "user", "content": "Hello"}],
        "system": "you are helpful",
        "max_tokens": 256,
        "temperature": 0.1,
        "stop_sequences": ["END"],
        "stream": True,
        "metadata": {"user_id": "someone"},
    }

    request = _extract_request(raw, model="new-model")

    assert request == {
        "model": "new-model",
        "messages": [{"role": "user", "content": "Hello"}],
        "system": "you are helpful",
        "max_tokens": 256,
        "temperature": 0.1,
        "stop_sequences": ["END"],
    }


def test_extract_request_strips_thinking_and_images() -> None:
    raw = {
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "Q"}]},
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "hidden", "signature": "s"},
                    {"type": "redacted_thinking", "data": "x"},
                    {"type": "text", "text": "Answer"},
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t1",
                        "content": [{"type": "image", "source": {}}],
                    },
                    {"type": "image", "source": {}},
                ],
            },
        ],
        "max_tokens": 10,
    }

    request = _extract_request(raw, model="m")

    assert request is not None
    assert request["messages"][1]["content"] == [{"type": "text", "text": "Answer"}]
    assert request["messages"][2]["content"] == [
        {
            "type": "tool_result",
            "tool_use_id": "t1",
            "content": [{"type": "text", "text": "[image removed]"}],
        }
    ]


def test_extract_request_drops_messages_emptied_by_filtering() -> None:
    raw = {
        "messages": [
            {"role": "user", "content": "Q"},
            {"role": "assistant", "content": [{"type": "thinking", "thinking": "x"}]},
            {"role": "user", "content": "Again"},
        ],
        "max_tokens": 10,
    }

    request = _extract_request(raw, model="m")

    assert request is not None
    assert [m["content"] for m in request["messages"]] == ["Q", "Again"]


def test_extract_request_returns_none_when_nothing_replayable() -> None:
    assert _extract_request({"messages": []}, model="m") is None
    only_thinking = {
        "messages": [{"role": "user", "content": [{"type": "thinking"}]}],
    }
    assert _extract_request(only_thinking, model="m") is None


def test_extract_request_strips_tool_cache_control() -> None:
    raw = {
        "messages": [{"role": "user", "content": "Q"}],
        "tools": [{"name": "t", "cache_control": {"type": "ephemeral"}}],
    }

    request = _extract_request(raw, model="m")

    assert request is not None
    assert request["tools"] == [{"name": "t"}]


def test_load_requests_keeps_only_anthropic_entries(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    anthropic = {
        "call_type": "anthropic_messages",
        "proxy_server_request": {"messages": [{"role": "user", "content": "Hi"}]},
    }
    lines = [
        json.dumps(anthropic),
        json.dumps({"call_type": "acompletion", "proxy_server_request": {}}),
        json.dumps({"call_type": "acompletion", "proxy_server_request": {}}),
        "not json",
        "",
        json.dumps({"call_type": "anthropic_messages"}),
    ]
    requests_file = tmp_path / "requests.jsonl"
    requests_file.write_text("\n".join(lines) + "\n")

    dataset = _load_requests(requests_file, model="m")

    assert dataset == [
        {"messages": [{"role": "user", "content": "Hi"}], "model": "m"},
    ]
    assert '{"acompletion": 2}' in caplog.text
    assert "Skipped 4 line(s)" in caplog.text


def test_parse_success_body_accepts_a_message() -> None:
    body = json.dumps(
        {
            "type": "message",
            "model": "claude-haiku-4-5-20251001",
            "usage": {"input_tokens": 12, "output_tokens": 3},
        }
    )

    assert _parse_success_body(body) == ("claude-haiku-4-5-20251001", 12, 3)


@pytest.mark.parametrize(
    "body",
    [
        "not json",
        json.dumps(["a list"]),
        json.dumps({"type": "error", "error": {"type": "overloaded_error"}}),
        json.dumps({"error": {"message": "boom"}}),
        json.dumps({"type": "message", "model": "m"}),
        json.dumps(
            {"type": "message", "usage": {"input_tokens": "12", "output_tokens": 3}}
        ),
        json.dumps(
            {"type": "message", "usage": {"input_tokens": -1, "output_tokens": 3}}
        ),
    ],
)
def test_parse_success_body_rejects_unusable_responses(body: str) -> None:
    assert isinstance(_parse_success_body(body), str)


def test_attempted_fallbacks_reads_litellm_header() -> None:
    assert _attempted_fallbacks({"x-litellm-attempted-fallbacks": "2"}) == 2
    assert _attempted_fallbacks({}) == 0
    assert _attempted_fallbacks({"x-litellm-attempted-fallbacks": "n/a"}) == 0


def test_run_deadline_covers_every_request_timing_out() -> None:
    # 10 requests over 3 workers: the busiest worker sends 4 back to back.
    assert _run_deadline_seconds(10, 3) == 4 * 90.0 + 60.0


@pytest.mark.parametrize(
    ("status", "body", "ok"),
    [
        (200, {"model": "m", "usage": {"input_tokens": 1, "output_tokens": 1}}, True),
        (200, {"type": "error", "error": {"type": "overloaded_error"}}, False),
        (500, {"error": "boom"}, False),
    ],
)
def test_preflight_requires_a_usable_message(
    monkeypatch: pytest.MonkeyPatch, status: int, body: dict, ok: bool
) -> None:
    import httpx

    transport = httpx.MockTransport(lambda request: httpx.Response(status, json=body))
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: real_client(transport=transport, **kwargs)
    )

    result = preflight_check("http://proxy", "key", "/v1/messages", {"model": "m"})

    assert result.ok is ok
    assert result.status_code == status


def test_served_group_maps_deployment_id_to_model_group() -> None:
    groups = {"dep-1": "primary", "dep-2": "backup"}

    assert _served_group({"x-litellm-model-id": "dep-2"}, groups) == "backup"
    assert _served_group({"x-litellm-model-id": "unknown"}, groups) is None
    assert _served_group({}, groups) is None
