"""Tests for QdrantManager class.

This module tests the QdrantManager functionality including collection creation,
point upsertion, search operations, and error handling.
"""

import pytest
from unittest.mock import MagicMock, patch
from qdrant_client.models import (
    Distance,
    MultiVectorComparator,
    PointStruct,
    ScoredPoint,
)

from llmaven.agentic.vector_store.qdrant_manager import QdrantManager
from llmaven.agentic.exceptions import (
    QdrantConnectionError,
    CollectionNotFoundError,
)


class TestQdrantManagerInitialization:
    """Test QdrantManager initialization."""

    def test_init_with_default_config(self):
        """Test initialization with default config."""
        with patch(
            "llmaven.agentic.vector_store.qdrant_manager.QdrantClient"
        ) as mock_client:
            manager = QdrantManager()
            assert manager.qdrant_url == "http://localhost:6333"
            assert manager.qdrant_api_key is None
            mock_client.assert_called_once_with(
                url="http://localhost:6333", api_key=None
            )

    def test_init_with_custom_url(self):
        """Test initialization with custom Qdrant URL."""
        with patch(
            "llmaven.agentic.vector_store.qdrant_manager.QdrantClient"
        ) as mock_client:
            manager = QdrantManager(qdrant_url="http://custom:6333")
            assert manager.qdrant_url == "http://custom:6333"
            mock_client.assert_called_once_with(url="http://custom:6333", api_key=None)

    def test_init_with_api_key(self):
        """Test initialization with API key."""
        with patch(
            "llmaven.agentic.vector_store.qdrant_manager.QdrantClient"
        ) as mock_client:
            manager = QdrantManager(qdrant_api_key="test-key")
            assert manager.qdrant_api_key == "test-key"
            mock_client.assert_called_once_with(
                url="http://localhost:6333", api_key="test-key"
            )

    def test_init_connection_error(self):
        """Test that connection errors are caught and wrapped."""
        with patch(
            "llmaven.agentic.vector_store.qdrant_manager.QdrantClient"
        ) as mock_client:
            mock_client.side_effect = Exception("Connection failed")
            with pytest.raises(QdrantConnectionError):
                QdrantManager()


class TestQdrantManagerEnsureCollection:
    """Test collection creation and validation."""

    def test_ensure_collection_creates_new_collection(self):
        """Test that ensure_collection creates a new collection if it doesn't exist."""
        mock_client = MagicMock()
        mock_client.get_collection.return_value = None
        mock_client.collection_exists.return_value = False

        with patch(
            "llmaven.agentic.vector_store.qdrant_manager.QdrantClient",
            return_value=mock_client,
        ):
            manager = QdrantManager()
            manager.ensure_collection("test-collection")

            # Verify create_collection was called with correct config
            mock_client.create_collection.assert_called_once()
            call_kwargs = mock_client.create_collection.call_args[1]
            assert call_kwargs["collection_name"] == "test-collection"

            # Verify vectors config
            vectors_config = call_kwargs["vectors_config"]
            assert "dense" in vectors_config
            assert "colbert" in vectors_config
            assert vectors_config["dense"].size == 384
            assert vectors_config["dense"].distance == Distance.COSINE
            assert vectors_config["colbert"].size == 128
            assert vectors_config["colbert"].distance == Distance.COSINE
            assert (
                vectors_config["colbert"].multivector_config.comparator
                == MultiVectorComparator.MAX_SIM
            )

            # Verify sparse vectors config
            sparse_config = call_kwargs["sparse_vectors_config"]
            assert "sparse" in sparse_config

    def test_ensure_collection_skips_if_exists(self):
        """Test that ensure_collection skips creation if collection exists."""
        mock_client = MagicMock()
        mock_client.collection_exists.return_value = True

        with patch(
            "llmaven.agentic.vector_store.qdrant_manager.QdrantClient",
            return_value=mock_client,
        ):
            manager = QdrantManager()
            manager.ensure_collection("existing-collection")

            # Should not create collection
            mock_client.create_collection.assert_not_called()

    def test_ensure_collection_with_force_overwrites(self):
        """Test that ensure_collection with force=True deletes and recreates."""
        mock_client = MagicMock()
        mock_client.collection_exists.return_value = True

        with patch(
            "llmaven.agentic.vector_store.qdrant_manager.QdrantClient",
            return_value=mock_client,
        ):
            manager = QdrantManager()
            manager.ensure_collection("test-collection", force=True)

            # Should delete existing collection
            mock_client.delete_collection.assert_called_once_with("test-collection")
            # Should create new collection
            mock_client.create_collection.assert_called_once()


class TestQdrantManagerUpsertPoints:
    """Test point upsertion."""

    def test_upsert_points_success(self):
        """Test successful point upsertion."""
        mock_client = MagicMock()
        mock_client.upsert.return_value = None  # Success

        with patch(
            "llmaven.agentic.vector_store.qdrant_manager.QdrantClient",
            return_value=mock_client,
        ):
            manager = QdrantManager()
            points = [
                PointStruct(
                    id=1,
                    vector={
                        "dense": [0.1] * 384,
                        "sparse": {"indices": [1], "values": [0.5]},
                        "colbert": [[0.1] * 128] * 5,
                    },
                    payload={"text": "test"},
                )
            ]
            manager.upsert_points("test-collection", points)

            mock_client.upsert.assert_called_once_with(
                collection_name="test-collection",
                points=points,
            )

    def test_upsert_points_batch(self):
        """Test batch upsertion of multiple points."""
        mock_client = MagicMock()

        with patch(
            "llmaven.agentic.vector_store.qdrant_manager.QdrantClient",
            return_value=mock_client,
        ):
            manager = QdrantManager()
            points = [
                PointStruct(
                    id=i,
                    vector={
                        "dense": [0.1] * 384,
                        "sparse": {"indices": [i], "values": [0.5]},
                        "colbert": [[0.1] * 128] * 5,
                    },
                    payload={"text": f"test {i}"},
                )
                for i in range(10)
            ]
            manager.upsert_points("test-collection", points)

            mock_client.upsert.assert_called_once()
            assert len(mock_client.upsert.call_args[1]["points"]) == 10

    def test_upsert_points_collection_not_found(self):
        """Test that upsert raises CollectionNotFoundError if collection doesn't exist."""
        mock_client = MagicMock()
        mock_client.upsert.side_effect = Exception("Collection not found")

        with patch(
            "llmaven.agentic.vector_store.qdrant_manager.QdrantClient",
            return_value=mock_client,
        ):
            manager = QdrantManager()
            points = [PointStruct(id=1, vector={"dense": [0.1] * 384}, payload={})]

            with pytest.raises(CollectionNotFoundError):
                manager.upsert_points("nonexistent-collection", points)


class TestQdrantManagerSearch:
    """Test search operations."""

    def test_search_with_prefetch_and_rerank(self):
        """Test search with prefetch and rerank."""
        mock_client = MagicMock()

        # Mock prefetch results (QueryResponse objects)
        mock_dense_response = MagicMock()
        mock_dense_response.points = [
            ScoredPoint(id=1, score=0.9, payload={"text": "doc1"}, version=0),
            ScoredPoint(id=2, score=0.8, payload={"text": "doc2"}, version=0),
        ]

        mock_sparse_response = MagicMock()
        mock_sparse_response.points = [
            ScoredPoint(id=2, score=0.85, payload={"text": "doc2"}, version=0),
            ScoredPoint(id=3, score=0.75, payload={"text": "doc3"}, version=0),
        ]

        # Mock rerank results
        mock_rerank_response = MagicMock()
        mock_rerank_response.points = [
            ScoredPoint(id=2, score=0.95, payload={"text": "doc2"}, version=0),
            ScoredPoint(id=1, score=0.85, payload={"text": "doc1"}, version=0),
        ]

        mock_client.query_points.side_effect = [
            mock_dense_response,  # Dense query
            mock_sparse_response,  # Sparse query
            mock_rerank_response,  # ColBERT rerank query
        ]

        with patch(
            "llmaven.agentic.vector_store.qdrant_manager.QdrantClient",
            return_value=mock_client,
        ):
            manager = QdrantManager()
            query_vectors = {
                "dense": [0.1] * 384,
                "sparse": {"indices": [1], "values": [0.5]},
                "colbert": [[0.1] * 128] * 10,
            }

            results = manager.search("test-collection", query_vectors, limit=5)

            assert len(results) == 2
            assert results[0].id == 2  # Reranked order

    def test_search_without_rerank(self):
        """Test search without reranking."""
        mock_client = MagicMock()

        # Mock prefetch results
        mock_dense_response = MagicMock()
        mock_dense_response.points = [
            ScoredPoint(id=1, score=0.9, payload={"text": "doc1"}, version=0),
            ScoredPoint(id=2, score=0.8, payload={"text": "doc2"}, version=0),
        ]

        mock_sparse_response = MagicMock()
        mock_sparse_response.points = [
            ScoredPoint(id=2, score=0.85, payload={"text": "doc2"}, version=0),
        ]

        mock_client.query_points.side_effect = [
            mock_dense_response,  # Dense query
            mock_sparse_response,  # Sparse query
        ]

        with patch(
            "llmaven.agentic.vector_store.qdrant_manager.QdrantClient",
            return_value=mock_client,
        ):
            manager = QdrantManager()
            query_vectors = {
                "dense": [0.1] * 384,
                "sparse": {"indices": [1], "values": [0.5]},
            }

            results = manager.search(
                "test-collection", query_vectors, limit=5, enable_rerank=False
            )

            assert len(results) <= 5


class TestQdrantManagerValidation:
    """Test collection validation methods."""

    def test_validate_collection_exists_true(self):
        """Test validate_collection_exists returns True when collection exists."""
        mock_client = MagicMock()
        mock_client.collection_exists.return_value = True

        with patch(
            "llmaven.agentic.vector_store.qdrant_manager.QdrantClient",
            return_value=mock_client,
        ):
            manager = QdrantManager()
            assert manager.validate_collection_exists("test-collection") is True

    def test_validate_collection_exists_false(self):
        """Test validate_collection_exists returns False when collection doesn't exist."""
        mock_client = MagicMock()
        mock_client.collection_exists.return_value = False

        with patch(
            "llmaven.agentic.vector_store.qdrant_manager.QdrantClient",
            return_value=mock_client,
        ):
            manager = QdrantManager()
            assert manager.validate_collection_exists("nonexistent") is False

    def test_delete_collection_with_confirmation(self):
        """Test delete_collection with confirmation."""
        mock_client = MagicMock()

        with patch(
            "llmaven.agentic.vector_store.qdrant_manager.QdrantClient",
            return_value=mock_client,
        ):
            manager = QdrantManager()
            manager.delete_collection("test-collection", confirm=True)

            mock_client.delete_collection.assert_called_once_with("test-collection")

    def test_delete_collection_without_confirmation(self):
        """Test delete_collection raises error without confirmation."""
        mock_client = MagicMock()

        with patch(
            "llmaven.agentic.vector_store.qdrant_manager.QdrantClient",
            return_value=mock_client,
        ):
            manager = QdrantManager()

            with pytest.raises(ValueError, match="explicit confirmation"):
                manager.delete_collection("test-collection", confirm=False)

            mock_client.delete_collection.assert_not_called()
