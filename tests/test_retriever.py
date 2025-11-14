import pytest
import httpx
from fastapi.testclient import TestClient
from llmaven.main import app

client = TestClient(app)

# Sample documents for testing
sample_documents = [
    {
        "page_content": "FastAPI is a modern web framework for building APIs with Python.",
        "metadata": {"source": "doc1", "author": "John Doe"}
    },
    {
        "page_content": "Vector databases are optimized for similarity search using embeddings.",
        "metadata": {"source": "doc2", "author": "Jane Smith"}
    }
]

# Define test cases
@pytest.mark.parametrize("query,expected_status", [
    ("What is FastAPI?", 200),
    ("Explain vector databases", 200),
])
def test_retrieve_endpoint(query, expected_status):
    """
    Test the retrieval API endpoint.
    """
    payload = {
        "documents": sample_documents,
        "query": query,
        "existing_collection": None,
        "existing_qdrant_path": None,
        "embedding_model": "sentence-transformers/all-MiniLM-L12-v2"
    }

    response = client.post("/api/retrieve/", json=payload)
    
    assert response.status_code == expected_status
    assert "docs" in response.json()
    assert isinstance(response.json()["docs"], list)
    assert response.json()["status_code"] == 200

    retrieved_docs = response.json()["docs"]
    assert len(retrieved_docs) > 0  # Ensure that some documents are retrieved

    for doc in retrieved_docs:
        assert "metadata" in doc
        assert "page_content" in doc
        assert len(doc["page_content"]) > 0  # Check content preview is non-empty

if __name__ == "__main__":
    pytest.main()
