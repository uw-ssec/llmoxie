"""Pytest configuration and fixtures for llmaven tests.

This module provides shared fixtures for testing, including a Qdrant
testcontainer for integration tests.
"""

import os
import pytest
from testcontainers.qdrant import QdrantContainer


@pytest.fixture(scope="session")
def qdrant_container():
    """Provide a Qdrant container for the test session.

    This fixture starts a Qdrant container using testcontainers-python
    and provides the connection URL for tests. The container is automatically
    cleaned up at the end of the test session.

    Yields:
        str: The Qdrant REST API URL (e.g., "http://localhost:6333")
    """
    # Start Qdrant container
    with QdrantContainer() as qdrant:
        # Get the connection URL
        qdrant_url = qdrant.get_api_url()

        # Set environment variable so tests can access it
        # The agentic config uses AGENTIC_ prefix
        os.environ["AGENTIC_QDRANT_URL"] = qdrant_url

        yield qdrant_url

        # Cleanup happens automatically when the context manager exits


@pytest.fixture
def qdrant_url(qdrant_container):
    """Provide the Qdrant URL for individual tests.

    This is a convenience fixture that can be used by tests that need
    the Qdrant URL without managing the container lifecycle.

    Args:
        qdrant_container: The session-scoped Qdrant container fixture

    Returns:
        str: The Qdrant REST API URL
    """
    return qdrant_container
