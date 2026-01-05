"""Hybrid search implementation with multi-vector retrieval.

This module provides HybridSearcher class for executing hybrid search
using Dense, Sparse, and ColBERT vectors with prefetch and rerank.
"""

from __future__ import annotations

import logging
import os
from typing import Any

# Suppress HuggingFace Hub progress bars globally
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["HF_HUB_DISABLE_TQDM"] = "1"
os.environ["TQDM_DISABLE"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["DISABLE_TQDM"] = "1"

# Disable progress bars via API
try:
    from huggingface_hub.utils import disable_progress_bars

    disable_progress_bars()
except ImportError:
    try:
        from huggingface_hub import disable_progress_bars

        disable_progress_bars()
    except ImportError:
        pass

from fastembed import TextEmbedding, SparseTextEmbedding, LateInteractionTextEmbedding

from llmaven.agentic.settings import config
from llmaven.agentic.vector_store.qdrant_manager import QdrantManager
from llmaven.agentic.search.models import SearchResult
from llmaven.agentic.exceptions import SearchError, EmbeddingError

logger = logging.getLogger(__name__)


class HybridSearcher:
    """Hybrid search with multi-vector retrieval and reranking.

    This class implements a three-stage hybrid search:
    1. Query Embedding: Generate Dense, Sparse, and ColBERT vectors
    2. Prefetch: Query Dense and Sparse vectors in parallel, combine results
    3. Rerank: Use ColBERT MaxSim to rerank prefetch candidates (optional)

    Attributes:
        collection_name: Name of the Qdrant collection to search
        qdrant_manager: QdrantManager instance for vector operations
        enable_rerank: Whether to apply ColBERT reranking
        prefetch_top_k: Number of candidates from each prefetch method
        final_top_k: Final number of results to return
    """

    def __init__(
        self,
        collection_name: str | None = None,
        qdrant_manager: QdrantManager | None = None,
        enable_rerank: bool | None = None,
        prefetch_top_k: int | None = None,
        final_top_k: int | None = None,
    ):
        """Initialize HybridSearcher.

        Args:
            collection_name: Collection to search (defaults to config)
            qdrant_manager: QdrantManager instance (creates new if None)
            enable_rerank: Enable ColBERT reranking (defaults to config)
            prefetch_top_k: Candidates per prefetch method (defaults to config)
            final_top_k: Final results to return (defaults to config)
        """
        self.collection_name = collection_name or config.collection_name
        self.qdrant_manager = qdrant_manager or QdrantManager()
        self.enable_rerank = (
            enable_rerank if enable_rerank is not None else config.enable_rerank
        )
        self.prefetch_top_k = prefetch_top_k or config.prefetch_top_k
        self.final_top_k = final_top_k or config.final_top_k

        # Initialize embedding models (lazy loading)
        self._dense_model: TextEmbedding | None = None
        self._sparse_model: SparseTextEmbedding | None = None
        self._colbert_model: LateInteractionTextEmbedding | None = None
        self._models_initialized = False

        logger.info(
            f"HybridSearcher initialized for collection '{self.collection_name}' "
            f"(rerank={self.enable_rerank}, prefetch_k={self.prefetch_top_k}, final_k={self.final_top_k})"
        )

    def _ensure_models_loaded(self) -> None:
        """Ensure embedding models are loaded."""
        if self._models_initialized:
            return

        try:
            logger.info("Loading embedding models...")

            if self._dense_model is None:
                logger.debug(f"Loading dense model: {config.dense_model}")
                self._dense_model = TextEmbedding(model_name=config.dense_model)

            if self._sparse_model is None:
                logger.debug(f"Loading sparse model: {config.sparse_model}")
                self._sparse_model = SparseTextEmbedding(model_name=config.sparse_model)

            if self._colbert_model is None and self.enable_rerank:
                logger.debug(f"Loading ColBERT model: {config.colbert_model}")
                self._colbert_model = LateInteractionTextEmbedding(
                    model_name=config.colbert_model
                )

            logger.info("Embedding models loaded successfully")
            self._models_initialized = True

        except Exception as e:
            raise EmbeddingError(f"Failed to initialize embedding models: {e}") from e

    def _generate_query_embeddings(self, query: str) -> dict[str, Any]:
        """Generate embeddings for a query.

        Args:
            query: Query text to embed

        Returns:
            Dict with 'dense', 'sparse', and optionally 'colbert' embeddings

        Raises:
            EmbeddingError: If embedding generation fails
        """
        if not query.strip():
            raise SearchError("Query cannot be empty")

        try:
            # Ensure models are loaded
            if not self._models_initialized:
                self._ensure_models_loaded()

            query_vectors = {}

            # Generate dense embedding
            logger.debug("Generating dense embedding for query")
            dense_vec = list(self._dense_model.embed([query]))[0]
            if hasattr(dense_vec, "tolist"):
                dense_vec = dense_vec.tolist()
            query_vectors["dense"] = dense_vec

            # Generate sparse embedding
            logger.debug("Generating sparse embedding for query")
            sparse_embedding = list(self._sparse_model.embed([query]))[0]
            if hasattr(sparse_embedding, "indices"):
                sparse_vec = {
                    "indices": sparse_embedding.indices.tolist(),
                    "values": sparse_embedding.values.tolist(),
                }
            else:
                sparse_vec = sparse_embedding
            query_vectors["sparse"] = sparse_vec

            # Generate ColBERT embedding if reranking enabled
            if self.enable_rerank:
                logger.debug("Generating ColBERT embedding for query")
                colbert_vec = list(self._colbert_model.embed([query]))[0]
                if hasattr(colbert_vec, "tolist"):
                    colbert_vec = colbert_vec.tolist()
                query_vectors["colbert"] = colbert_vec

            return query_vectors

        except Exception as e:
            raise EmbeddingError(f"Failed to generate query embeddings: {e}") from e

    def search(
        self,
        query: str,
        limit: int | None = None,
        enable_rerank: bool | None = None,
        prefetch_top_k: int | None = None,
    ) -> list[SearchResult]:
        """Execute hybrid search with prefetch and optional reranking.

        Search pipeline:
        1. Generate query embeddings (dense, sparse, colbert)
        2. Prefetch: Query dense and sparse vectors in parallel
        3. Combine: Union prefetch results, deduplicate by point ID
        4. Rerank: Use ColBERT MaxSim to rerank (if enabled)

        Args:
            query: Search query text
            limit: Number of results to return (defaults to final_top_k)
            enable_rerank: Override reranking setting (defaults to instance setting)
            prefetch_top_k: Override prefetch candidates (defaults to instance setting)

        Returns:
            List of SearchResult objects, sorted by score (highest first)

        Raises:
            SearchError: If search execution fails
            EmbeddingError: If query embedding generation fails
        """
        # Use instance settings as defaults
        final_limit = limit or self.final_top_k
        use_rerank = enable_rerank if enable_rerank is not None else self.enable_rerank
        prefetch_k = prefetch_top_k or self.prefetch_top_k

        logger.info(
            f"Executing hybrid search for query: '{query[:50]}...' "
            f"(limit={final_limit}, rerank={use_rerank}, prefetch_k={prefetch_k})"
        )

        try:
            # Step 1: Generate query embeddings
            logger.debug("Step 1: Generating query embeddings")
            query_vectors = self._generate_query_embeddings(query)

            # Step 2-4: Execute search via QdrantManager
            logger.debug("Step 2-4: Executing prefetch and rerank")
            scored_points = self.qdrant_manager.search(
                collection_name=self.collection_name,
                query_vectors=query_vectors,
                limit=final_limit,
                enable_rerank=use_rerank,
                prefetch_top_k=prefetch_k,
            )

            # Convert ScoredPoints to SearchResult objects
            logger.debug(
                f"Converting {len(scored_points)} results to SearchResult objects"
            )
            results = []
            for point in scored_points:
                payload = point.payload or {}

                # Determine prefetch and rerank scores
                # If reranking was enabled, the final score is the rerank score
                # and we don't have the original prefetch score from Qdrant
                # (this is a limitation of the current implementation)
                if use_rerank:
                    rerank_score = point.score
                    prefetch_score = None  # Not available after reranking
                else:
                    rerank_score = None
                    prefetch_score = point.score

                result = SearchResult(
                    text=payload.get("text", ""),
                    file_path=payload.get("file_path", ""),
                    heading_hierarchy=payload.get("heading_hierarchy"),
                    score=point.score,
                    prefetch_score=prefetch_score,
                    rerank_score=rerank_score,
                    chunk_index=payload.get("chunk_index", 0),
                    content_hash=payload.get("content_hash"),
                )
                results.append(result)

            logger.info(f"Search completed: {len(results)} results returned")
            return results

        except (EmbeddingError, SearchError):
            raise
        except Exception as e:
            raise SearchError(f"Search execution failed: {e}") from e
