from __future__ import annotations

from llmaven.deployment.loadtest import (
    _ANTHROPIC_API_PATH,
    _OPENAI_API_PATH,
    _count_requests_by_endpoint,
    _extract_request,
)


def test_extract_request_openai_strips_thinking_blocks() -> None:
    raw = {
        "model": "old-model",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "thinking", "text": "hidden"},
                    {"type": "text", "text": "Hello"},
                ],
            }
        ],
        "temperature": 0.2,
        "system": "should-be-dropped-for-openai",
        "stream": True,
    }
    entry = {"call_type": "acompletion"}

    result = _extract_request(raw, entry, model="new-model")

    assert result is not None
    api_path, request = result
    assert api_path == _OPENAI_API_PATH
    assert request["model"] == "new-model"
    assert "system" not in request
    assert "stream" not in request
    assert request["messages"][0]["content"] == [{"type": "text", "text": "Hello"}]


def test_extract_request_anthropic_keeps_system_and_thinking() -> None:
    raw = {
        "model": "old-model",
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "text": "internal"},
                    {"type": "text", "text": "Answer"},
                ],
            }
        ],
        "system": "you are helpful",
        "temperature": 0.1,
    }
    entry = {"call_type": "anthropic_messages"}

    result = _extract_request(raw, entry, model="new-model")

    assert result is not None
    api_path, request = result
    assert api_path == _ANTHROPIC_API_PATH
    assert request["model"] == "new-model"
    assert request["system"] == "you are helpful"
    assert request["messages"][0]["content"][0] == {
        "type": "thinking",
        "text": "internal",
    }


def test_count_requests_by_endpoint_splits_openai_and_anthropic() -> None:
    dataset = [
        (_OPENAI_API_PATH, {"messages": [1]}),
        (_ANTHROPIC_API_PATH, {"messages": [2]}),
        (_OPENAI_API_PATH, {"messages": [3]}),
    ]

    anthropic_count, openai_count = _count_requests_by_endpoint(dataset)

    assert anthropic_count == 1
    assert openai_count == 2
