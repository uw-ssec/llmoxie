from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from llmaven.main import app

client = TestClient(app)


@pytest.mark.parametrize(
    "prompt,generation_model,expected_status",
    [
        ("What is the capital of France?", "allenai/OLMo-2-1124-7B-Instruct", 200),
        (
            "Explain quantum computing in simple terms.",
            "allenai/OLMo-2-1124-7B-Instruct",
            200,
        ),
    ],
)
def test_generate_endpoint(
    prompt: str, generation_model: str, expected_status: int
) -> None:
    """Verify the generate endpoint contract without invoking a real LLM."""
    fake_response = {"answer": f"mocked answer for: {prompt}", "status_code": 200}

    with patch(
        "llmaven.v1.endpoints.generate.generate_answer",
        return_value=fake_response,
    ) as mock_generate:
        response = client.post(
            "/v1/generate",
            json={"prompt": prompt, "generation_model": generation_model},
        )

    assert response.status_code == expected_status
    body = response.json()
    assert "answer" in body
    assert isinstance(body["answer"], str)
    assert len(body["answer"]) > 0
    mock_generate.assert_called_once_with(prompt, generation_model)


if __name__ == "__main__":
    pytest.main()
