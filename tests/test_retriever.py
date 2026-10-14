from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from llmaven.main import app

client = TestClient(app)

sample_documents = [
    {
        "page_content": "FastAPI is a modern web framework for building APIs with Python.",
        "metadata": {"source": "doc1", "author": "John Doe"},
    },
    {
        "page_content": "Vector databases are optimized for similarity search using embeddings.",
        "metadata": {"source": "doc2", "author": "Jane Smith"},
    },
]


@pytest.mark.parametrize(
    "query,expected_status",
    [
        ("What is FastAPI?", 200),
        ("Explain vector databases", 200),
    ],
)
def test_retrieve_endpoint(query: str, expected_status: int) -> None:
    """Verify the retrieve endpoint contract without spinning up Qdrant or embeddings."""
    fake_response = {
        "docs": [
            {"metadata": doc["metadata"], "page_content": doc["page_content"][:500]}
            for doc in sample_documents
        ],
        "status_code": 200,
    }

    embedding_model = "sentence-transformers/all-MiniLM-L12-v2"
    payload = {
        "documents": sample_documents,
        "query": query,
        "existing_collection": None,
        "existing_qdrant_path": None,
        "embedding_model": embedding_model,
    }

    with patch(
        "llmaven.v1.endpoints.retrieve.perform_retrieval",
        return_value=fake_response,
    ) as mock_retrieve:
        response = client.post("/v1/retrieve", json=payload)

    assert response.status_code == expected_status
    body = response.json()
    assert "docs" in body
    assert isinstance(body["docs"], list)
    assert body["status_code"] == 200
    assert len(body["docs"]) > 0
    for doc in body["docs"]:
        assert "metadata" in doc
        assert "page_content" in doc
        assert len(doc["page_content"]) > 0

    mock_retrieve.assert_called_once_with(
        sample_documents,
        query,
        None,
        None,
        embedding_model,
    )


if __name__ == "__main__":
    pytest.main()
