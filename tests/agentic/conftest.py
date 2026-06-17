"""Pytest fixtures for agentic RAG tests.

This module provides shared fixtures for testing the agentic RAG system,
including testcontainers setup for Qdrant integration tests.
"""

from __future__ import annotations

import pytest
from testcontainers.qdrant import QdrantContainer


@pytest.fixture(scope="session")
def qdrant_container():
    """Provide a Qdrant testcontainer for integration tests.

    This fixture starts a Qdrant container once per test session and makes it
    available to all tests. The container is automatically cleaned up after
    all tests complete.

    Returns:
        QdrantContainer: A started Qdrant container instance.

    Example:
        ```python
        def test_qdrant_connection(qdrant_container):
            from qdrant_client import QdrantClient

            # Get connection URL from container
            qdrant_url = qdrant_container.get_api_url()

            # Create client
            client = QdrantClient(url=qdrant_url)

            # Use client for testing
            assert client.get_collections() is not None
        ```
    """
    with QdrantContainer() as container:
        yield container


@pytest.fixture
def qdrant_url(qdrant_container):
    """Provide the Qdrant HTTP API URL for tests.

    This fixture extracts the HTTP API URL from the Qdrant container,
    making it easy to configure Qdrant clients in tests.

    Args:
        qdrant_container: The Qdrant container fixture.

    Returns:
        str: The HTTP API URL (e.g., "http://localhost:6333").

    Example:
        ```python
        def test_collection_creation(qdrant_url):
            from qdrant_client import QdrantClient
            from qdrant_client.models import VectorParams, Distance

            client = QdrantClient(url=qdrant_url)

            # Create collection
            client.create_collection(
                collection_name="test",
                vectors_config=VectorParams(size=384, distance=Distance.COSINE)
            )

            # Verify collection exists
            collections = client.get_collections().collections
            assert any(c.name == "test" for c in collections)
        ```
    """
    return f"http://{qdrant_container.rest_host_address}"


@pytest.fixture
def qdrant_grpc_url(qdrant_container):
    """Provide the Qdrant gRPC URL for tests.

    This fixture extracts the gRPC URL from the Qdrant container,
    useful for tests that need to use the gRPC interface.

    Args:
        qdrant_container: The Qdrant container fixture.

    Returns:
        str: The gRPC URL (e.g., "http://localhost:6334").

    Example:
        ```python
        def test_grpc_connection(qdrant_grpc_url):
            from qdrant_client import QdrantClient

            client = QdrantClient(url=qdrant_grpc_url, prefer_grpc=True)
            assert client.get_collections() is not None
        ```
    """
    return f"http://{qdrant_container.grpc_host_address}"
