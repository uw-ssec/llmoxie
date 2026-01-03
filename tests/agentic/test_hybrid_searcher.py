"""Tests for HybridSearcher class.

This module tests the HybridSearcher functionality including query embedding
generation, prefetch logic, combination strategy, reranking, and error handling.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
import numpy as np

from llmaven.agentic.search.hybrid_searcher import HybridSearcher
from llmaven.agentic.search.models import SearchResult
from llmaven.agentic.exceptions import SearchError, EmbeddingError
from qdrant_client.models import ScoredPoint


class MockSparseEmbedding:
    """Mock sparse embedding object with indices and values."""

    def __init__(self, indices, values):
        self.indices = np.array(indices)
        self.values = np.array(values)


class TestHybridSearcherInitialization:
    """Test HybridSearcher initialization."""

    def test_init_with_default_config(self):
        """Test initialization with default config."""
        with patch("llmaven.agentic.search.hybrid_searcher.QdrantManager"):
            searcher = HybridSearcher()
            assert searcher.collection_name == "agentic-rag"
            assert searcher.enable_rerank is True
            assert searcher.prefetch_top_k == 20
            assert searcher.final_top_k == 5
            assert searcher._models_initialized is False

    def test_init_with_custom_settings(self):
        """Test initialization with custom settings."""
        with patch("llmaven.agentic.search.hybrid_searcher.QdrantManager"):
            searcher = HybridSearcher(
                collection_name="custom-collection",
                enable_rerank=False,
                prefetch_top_k=30,
                final_top_k=10,
            )
            assert searcher.collection_name == "custom-collection"
            assert searcher.enable_rerank is False
            assert searcher.prefetch_top_k == 30
            assert searcher.final_top_k == 10

    def test_init_with_custom_manager(self):
        """Test initialization with custom QdrantManager."""
        mock_manager = Mock()
        searcher = HybridSearcher(qdrant_manager=mock_manager)
        assert searcher.qdrant_manager == mock_manager


class TestHybridSearcherModelLoading:
    """Test embedding model loading."""

    @patch("llmaven.agentic.search.hybrid_searcher.LateInteractionTextEmbedding")
    @patch("llmaven.agentic.search.hybrid_searcher.SparseTextEmbedding")
    @patch("llmaven.agentic.search.hybrid_searcher.TextEmbedding")
    @patch("llmaven.agentic.search.hybrid_searcher.QdrantManager")
    def test_ensure_models_loaded(
        self, mock_manager, mock_dense, mock_sparse, mock_colbert
    ):
        """Test that models are loaded correctly."""
        searcher = HybridSearcher()
        searcher._ensure_models_loaded()

        mock_dense.assert_called_once()
        mock_sparse.assert_called_once()
        mock_colbert.assert_called_once()
        assert searcher._models_initialized is True

    @patch("llmaven.agentic.search.hybrid_searcher.LateInteractionTextEmbedding")
    @patch("llmaven.agentic.search.hybrid_searcher.SparseTextEmbedding")
    @patch("llmaven.agentic.search.hybrid_searcher.TextEmbedding")
    @patch("llmaven.agentic.search.hybrid_searcher.QdrantManager")
    def test_ensure_models_loaded_skip_colbert_when_rerank_disabled(
        self, mock_manager, mock_dense, mock_sparse, mock_colbert
    ):
        """Test that ColBERT model is not loaded when reranking is disabled."""
        searcher = HybridSearcher(enable_rerank=False)
        searcher._ensure_models_loaded()

        mock_dense.assert_called_once()
        mock_sparse.assert_called_once()
        mock_colbert.assert_not_called()
        assert searcher._models_initialized is True

    @patch("llmaven.agentic.search.hybrid_searcher.TextEmbedding")
    @patch("llmaven.agentic.search.hybrid_searcher.QdrantManager")
    def test_ensure_models_loaded_raises_on_error(self, mock_manager, mock_dense):
        """Test that model loading errors are caught and wrapped."""
        mock_dense.side_effect = Exception("Model loading failed")

        searcher = HybridSearcher()
        with pytest.raises(EmbeddingError):
            searcher._ensure_models_loaded()

    @patch("llmaven.agentic.search.hybrid_searcher.TextEmbedding")
    @patch("llmaven.agentic.search.hybrid_searcher.QdrantManager")
    def test_ensure_models_loaded_only_once(self, mock_manager, mock_dense):
        """Test that models are only loaded once (lazy loading)."""
        searcher = HybridSearcher()
        searcher._models_initialized = True

        # Should not call model constructors
        searcher._ensure_models_loaded()
        mock_dense.assert_not_called()


class TestHybridSearcherQueryEmbedding:
    """Test query embedding generation."""

    @patch("llmaven.agentic.search.hybrid_searcher.LateInteractionTextEmbedding")
    @patch("llmaven.agentic.search.hybrid_searcher.SparseTextEmbedding")
    @patch("llmaven.agentic.search.hybrid_searcher.TextEmbedding")
    @patch("llmaven.agentic.search.hybrid_searcher.QdrantManager")
    def test_generate_query_embeddings_success(
        self, mock_manager, mock_dense_cls, mock_sparse_cls, mock_colbert_cls
    ):
        """Test successful query embedding generation."""
        # Setup mocks
        mock_dense = Mock()
        mock_dense.embed.return_value = [np.array([0.1, 0.2, 0.3])]
        mock_dense_cls.return_value = mock_dense

        mock_sparse = Mock()
        mock_sparse.embed.return_value = [MockSparseEmbedding([0, 5, 10], [0.5, 0.3, 0.2])]
        mock_sparse_cls.return_value = mock_sparse

        mock_colbert = Mock()
        mock_colbert.embed.return_value = [np.array([[0.1, 0.2], [0.3, 0.4]])]
        mock_colbert_cls.return_value = mock_colbert

        # Execute
        searcher = HybridSearcher(enable_rerank=True)
        query_vectors = searcher._generate_query_embeddings("test query")

        # Verify
        assert "dense" in query_vectors
        assert "sparse" in query_vectors
        assert "colbert" in query_vectors

        assert query_vectors["dense"] == [0.1, 0.2, 0.3]
        assert query_vectors["sparse"]["indices"] == [0, 5, 10]
        assert query_vectors["sparse"]["values"] == [0.5, 0.3, 0.2]
        assert query_vectors["colbert"] == [[0.1, 0.2], [0.3, 0.4]]

    @patch("llmaven.agentic.search.hybrid_searcher.SparseTextEmbedding")
    @patch("llmaven.agentic.search.hybrid_searcher.TextEmbedding")
    @patch("llmaven.agentic.search.hybrid_searcher.QdrantManager")
    def test_generate_query_embeddings_without_rerank(
        self, mock_manager, mock_dense_cls, mock_sparse_cls
    ):
        """Test query embedding generation without reranking."""
        # Setup mocks
        mock_dense = Mock()
        mock_dense.embed.return_value = [np.array([0.1, 0.2, 0.3])]
        mock_dense_cls.return_value = mock_dense

        mock_sparse = Mock()
        mock_sparse.embed.return_value = [MockSparseEmbedding([0, 5, 10], [0.5, 0.3, 0.2])]
        mock_sparse_cls.return_value = mock_sparse

        # Execute
        searcher = HybridSearcher(enable_rerank=False)
        query_vectors = searcher._generate_query_embeddings("test query")

        # Verify - should not include ColBERT
        assert "dense" in query_vectors
        assert "sparse" in query_vectors
        assert "colbert" not in query_vectors

    @patch("llmaven.agentic.search.hybrid_searcher.QdrantManager")
    def test_generate_query_embeddings_empty_query(self, mock_manager):
        """Test that empty query raises SearchError."""
        searcher = HybridSearcher()
        with pytest.raises(SearchError, match="Query cannot be empty"):
            searcher._generate_query_embeddings("")

    @patch("llmaven.agentic.search.hybrid_searcher.TextEmbedding")
    @patch("llmaven.agentic.search.hybrid_searcher.QdrantManager")
    def test_generate_query_embeddings_raises_on_error(
        self, mock_manager, mock_dense_cls
    ):
        """Test that embedding generation errors are caught and wrapped."""
        mock_dense = Mock()
        mock_dense.embed.side_effect = Exception("Embedding failed")
        mock_dense_cls.return_value = mock_dense

        searcher = HybridSearcher()
        with pytest.raises(EmbeddingError):
            searcher._generate_query_embeddings("test query")


class TestHybridSearcherSearch:
    """Test hybrid search execution."""

    @patch("llmaven.agentic.search.hybrid_searcher.LateInteractionTextEmbedding")
    @patch("llmaven.agentic.search.hybrid_searcher.SparseTextEmbedding")
    @patch("llmaven.agentic.search.hybrid_searcher.TextEmbedding")
    @patch("llmaven.agentic.search.hybrid_searcher.QdrantManager")
    def test_search_success_with_rerank(
        self, mock_manager_cls, mock_dense_cls, mock_sparse_cls, mock_colbert_cls
    ):
        """Test successful search with reranking."""
        # Setup embedding mocks
        mock_dense = Mock()
        mock_dense.embed.return_value = [np.array([0.1, 0.2, 0.3])]
        mock_dense_cls.return_value = mock_dense

        mock_sparse = Mock()
        mock_sparse.embed.return_value = [MockSparseEmbedding([0, 5, 10], [0.5, 0.3, 0.2])]
        mock_sparse_cls.return_value = mock_sparse

        mock_colbert = Mock()
        mock_colbert.embed.return_value = [np.array([[0.1, 0.2], [0.3, 0.4]])]
        mock_colbert_cls.return_value = mock_colbert

        # Setup QdrantManager mock
        mock_manager = Mock()
        mock_point1 = Mock(spec=ScoredPoint)
        mock_point1.id = 1
        mock_point1.score = 0.95
        mock_point1.payload = {
            "text": "Test result 1",
            "file_path": "/docs/test1.md",
            "heading_hierarchy": "Section 1",
            "chunk_index": 0,
            "content_hash": "abc123",
        }

        mock_point2 = Mock(spec=ScoredPoint)
        mock_point2.id = 2
        mock_point2.score = 0.85
        mock_point2.payload = {
            "text": "Test result 2",
            "file_path": "/docs/test2.md",
            "heading_hierarchy": "Section 2",
            "chunk_index": 1,
            "content_hash": "def456",
        }

        mock_manager.search.return_value = [mock_point1, mock_point2]
        mock_manager_cls.return_value = mock_manager

        # Execute
        searcher = HybridSearcher(enable_rerank=True)
        results = searcher.search("test query", limit=5)

        # Verify
        assert len(results) == 2
        assert all(isinstance(r, SearchResult) for r in results)

        # Check first result
        assert results[0].text == "Test result 1"
        assert results[0].file_path == "/docs/test1.md"
        assert results[0].score == 0.95
        assert results[0].rerank_score == 0.95
        assert results[0].prefetch_score is None  # Not available after reranking

        # Verify QdrantManager.search was called with correct params
        mock_manager.search.assert_called_once()
        call_kwargs = mock_manager.search.call_args[1]
        assert call_kwargs["collection_name"] == "agentic-rag"
        assert call_kwargs["limit"] == 5
        assert call_kwargs["enable_rerank"] is True
        assert call_kwargs["prefetch_top_k"] == 20
        assert "dense" in call_kwargs["query_vectors"]
        assert "sparse" in call_kwargs["query_vectors"]
        assert "colbert" in call_kwargs["query_vectors"]

    @patch("llmaven.agentic.search.hybrid_searcher.SparseTextEmbedding")
    @patch("llmaven.agentic.search.hybrid_searcher.TextEmbedding")
    @patch("llmaven.agentic.search.hybrid_searcher.QdrantManager")
    def test_search_success_without_rerank(
        self, mock_manager_cls, mock_dense_cls, mock_sparse_cls
    ):
        """Test successful search without reranking."""
        # Setup embedding mocks
        mock_dense = Mock()
        mock_dense.embed.return_value = [np.array([0.1, 0.2, 0.3])]
        mock_dense_cls.return_value = mock_dense

        mock_sparse = Mock()
        mock_sparse.embed.return_value = [MockSparseEmbedding([0, 5, 10], [0.5, 0.3, 0.2])]
        mock_sparse_cls.return_value = mock_sparse

        # Setup QdrantManager mock
        mock_manager = Mock()
        mock_point = Mock(spec=ScoredPoint)
        mock_point.id = 1
        mock_point.score = 0.75
        mock_point.payload = {
            "text": "Test result",
            "file_path": "/docs/test.md",
            "chunk_index": 0,
        }
        mock_manager.search.return_value = [mock_point]
        mock_manager_cls.return_value = mock_manager

        # Execute
        searcher = HybridSearcher(enable_rerank=False)
        results = searcher.search("test query", limit=5)

        # Verify
        assert len(results) == 1
        assert results[0].score == 0.75
        assert results[0].prefetch_score == 0.75
        assert results[0].rerank_score is None

        # Verify QdrantManager.search was called without ColBERT
        call_kwargs = mock_manager.search.call_args[1]
        assert call_kwargs["enable_rerank"] is False
        # ColBERT vector should not be generated when rerank is disabled
        assert "colbert" not in call_kwargs["query_vectors"]

    @patch("llmaven.agentic.search.hybrid_searcher.QdrantManager")
    def test_search_with_custom_parameters(self, mock_manager_cls):
        """Test search with custom override parameters."""
        mock_manager = Mock()
        mock_manager.search.return_value = []
        mock_manager_cls.return_value = mock_manager

        searcher = HybridSearcher()

        # Mock the embedding generation to avoid model loading
        with patch.object(searcher, "_generate_query_embeddings") as mock_embed:
            mock_embed.return_value = {"dense": [], "sparse": {}}
            searcher.search(
                "test query",
                limit=10,
                enable_rerank=False,
                prefetch_top_k=50,
            )

        # Verify parameters were passed through
        call_kwargs = mock_manager.search.call_args[1]
        assert call_kwargs["limit"] == 10
        assert call_kwargs["enable_rerank"] is False
        assert call_kwargs["prefetch_top_k"] == 50

    @patch("llmaven.agentic.search.hybrid_searcher.QdrantManager")
    def test_search_empty_results(self, mock_manager_cls):
        """Test search with no results."""
        mock_manager = Mock()
        mock_manager.search.return_value = []
        mock_manager_cls.return_value = mock_manager

        searcher = HybridSearcher()

        with patch.object(searcher, "_generate_query_embeddings") as mock_embed:
            mock_embed.return_value = {"dense": [], "sparse": {}}
            results = searcher.search("test query")

        assert results == []

    @patch("llmaven.agentic.search.hybrid_searcher.QdrantManager")
    def test_search_raises_on_embedding_error(self, mock_manager_cls):
        """Test that embedding errors are propagated."""
        mock_manager_cls.return_value = Mock()

        searcher = HybridSearcher()

        with patch.object(searcher, "_generate_query_embeddings") as mock_embed:
            mock_embed.side_effect = EmbeddingError("Embedding failed")
            with pytest.raises(EmbeddingError):
                searcher.search("test query")

    @patch("llmaven.agentic.search.hybrid_searcher.QdrantManager")
    def test_search_raises_on_qdrant_error(self, mock_manager_cls):
        """Test that Qdrant search errors are wrapped in SearchError."""
        mock_manager = Mock()
        mock_manager.search.side_effect = Exception("Qdrant failed")
        mock_manager_cls.return_value = mock_manager

        searcher = HybridSearcher()

        with patch.object(searcher, "_generate_query_embeddings") as mock_embed:
            mock_embed.return_value = {"dense": [], "sparse": {}}
            with pytest.raises(SearchError):
                searcher.search("test query")


class TestHybridSearcherResultConversion:
    """Test conversion of ScoredPoint to SearchResult."""

    @patch("llmaven.agentic.search.hybrid_searcher.QdrantManager")
    def test_result_with_all_fields(self, mock_manager_cls):
        """Test result conversion with all payload fields."""
        mock_manager = Mock()
        mock_point = Mock(spec=ScoredPoint)
        mock_point.id = 1
        mock_point.score = 0.95
        mock_point.payload = {
            "text": "Full test result",
            "file_path": "/docs/full.md",
            "heading_hierarchy": "Chapter 1 > Section 2",
            "chunk_index": 3,
            "content_hash": "xyz789",
        }
        mock_manager.search.return_value = [mock_point]
        mock_manager_cls.return_value = mock_manager

        searcher = HybridSearcher()

        with patch.object(searcher, "_generate_query_embeddings") as mock_embed:
            mock_embed.return_value = {"dense": [], "sparse": {}}
            results = searcher.search("test")

        result = results[0]
        assert result.text == "Full test result"
        assert result.file_path == "/docs/full.md"
        assert result.heading_hierarchy == "Chapter 1 > Section 2"
        assert result.chunk_index == 3
        assert result.content_hash == "xyz789"

    @patch("llmaven.agentic.search.hybrid_searcher.QdrantManager")
    def test_result_with_minimal_fields(self, mock_manager_cls):
        """Test result conversion with minimal payload fields."""
        mock_manager = Mock()
        mock_point = Mock(spec=ScoredPoint)
        mock_point.id = 1
        mock_point.score = 0.85
        mock_point.payload = {}  # Empty payload
        mock_manager.search.return_value = [mock_point]
        mock_manager_cls.return_value = mock_manager

        searcher = HybridSearcher()

        with patch.object(searcher, "_generate_query_embeddings") as mock_embed:
            mock_embed.return_value = {"dense": [], "sparse": {}}
            results = searcher.search("test")

        result = results[0]
        assert result.text == ""
        assert result.file_path == ""
        assert result.heading_hierarchy is None
        assert result.chunk_index == 0
        assert result.content_hash is None
