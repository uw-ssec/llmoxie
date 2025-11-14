import pytest
import httpx
from fastapi.testclient import TestClient
from llmaven.main import app

client = TestClient(app)

# Define test cases
@pytest.mark.parametrize("prompt,generation_model,expected_status", [
    ("What is the capital of France?", "allenai/OLMo-2-1124-7B-Instruct", 200),
    ("Explain quantum computing in simple terms.", "allenai/OLMo-2-1124-7B-Instruct", 200),
])
def test_generate_endpoint(prompt, generation_model, expected_status):
    """
    Test the text generation API endpoint.
    """
    payload = {
        "prompt": prompt,
        "generation_model": generation_model
    }

    response = client.post("/api/generate/", json=payload)
    
    assert response.status_code == expected_status
    assert "answer" in response.json()
    assert isinstance(response.json()["answer"], str)
    assert len(response.json()["answer"]) > 0  # Ensure the model generates text

    print(f"✅ Test passed for prompt: {prompt}")

if __name__ == "__main__":
    pytest.main()
