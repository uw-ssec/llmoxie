"""Qdrant vector store manager for Agentic RAG.

This module provides QdrantManager class for managing Qdrant collections
with Named Vectors support (Dense, Sparse, ColBERT).
"""

from __future__ import annotations

from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    VectorParams,
    Distance,
    SparseVectorParams,
    MultiVectorConfig,
    MultiVectorComparator,
    PointStruct,
    ScoredPoint,
)

from llmaven.agentic.settings import config
from llmaven.agentic.exceptions import (
    QdrantConnectionError,
    CollectionNotFoundError,
)


class QdrantManager:
    """Manages Qdrant vector store operations with Named Vectors support.

    This class handles collection creation, point upsertion, and search operations
    using Qdrant's Named Vectors feature for multi-vector embeddings.

    Attributes:
        qdrant_url: Qdrant server URL
        qdrant_api_key: Optional API key for authentication
        client: QdrantClient instance
    """

    def __init__(
        self,
        qdrant_url: str | None = None,
        qdrant_api_key: str | None = None,
    ):
        """Initialize QdrantManager.

        Args:
            qdrant_url: Qdrant server URL (defaults to config value)
            qdrant_api_key: Optional API key (defaults to config value)

        Raises:
            QdrantConnectionError: If connection to Qdrant fails
        """
        self.qdrant_url = qdrant_url or config.qdrant_url
        self.qdrant_api_key = qdrant_api_key or config.qdrant_api_key

        try:
            self.client = QdrantClient(
                url=self.qdrant_url,
                api_key=self.qdrant_api_key,
            )
        except Exception as e:
            raise QdrantConnectionError(f"Failed to connect to Qdrant: {e}") from e

    def ensure_collection(
        self,
        collection_name: str,
        force: bool = False,
    ) -> None:
        """Create or verify collection exists with Named Vectors configuration.

        Creates a collection with three named vectors:
        - dense: 384-dimensional dense embeddings (Cosine distance)
        - sparse: Sparse BM25 vectors
        - colbert: 128-dimensional ColBERT vectors with MaxSim comparator

        Args:
            collection_name: Name of the collection
            force: If True, delete existing collection before creating

        Raises:
            QdrantConnectionError: If Qdrant operation fails
        """
        try:
            # Check if collection exists
            collection_exists = self.client.collection_exists(collection_name)

            if collection_exists:
                if force:
                    # Delete existing collection
                    self.client.delete_collection(collection_name)
                else:
                    # Collection exists and we're not forcing, skip creation
                    return

            # Create collection with Named Vectors configuration
            self.client.create_collection(
                collection_name=collection_name,
                vectors_config={
                    "dense": VectorParams(
                        size=384,
                        distance=Distance.COSINE,
                    ),
                    "colbert": VectorParams(
                        size=128,
                        distance=Distance.COSINE,
                        multivector_config=MultiVectorConfig(
                            comparator=MultiVectorComparator.MAX_SIM
                        ),
                    ),
                },
                sparse_vectors_config={
                    "sparse": SparseVectorParams(),
                },
            )
        except Exception as e:
            raise QdrantConnectionError(f"Failed to ensure collection: {e}") from e

    def upsert_points(
        self,
        collection_name: str,
        points: list[PointStruct],
    ) -> None:
        """Upsert points to collection.

        Args:
            collection_name: Name of the collection
            points: List of PointStruct objects to upsert

        Raises:
            CollectionNotFoundError: If collection doesn't exist
            QdrantConnectionError: If Qdrant operation fails
        """
        try:
            self.client.upsert(
                collection_name=collection_name,
                points=points,
            )
        except Exception as e:
            error_msg = str(e).lower()
            if "not found" in error_msg or "does not exist" in error_msg:
                raise CollectionNotFoundError(
                    f"Collection '{collection_name}' not found"
                ) from e
            raise QdrantConnectionError(f"Failed to upsert points: {e}") from e

    def search(
        self,
        collection_name: str,
        query_vectors: dict[str, Any],
        limit: int = 5,
        enable_rerank: bool = True,
        prefetch_top_k: int = 20,
    ) -> list[ScoredPoint]:
        """Search collection using hybrid search with prefetch and rerank.

        Performs hybrid search by:
        1. Prefetch: Query both dense and sparse vectors in parallel
        2. Combine: Union of results, deduplicated by point ID
        3. Rerank: Use ColBERT MaxSim to rerank prefetch results (optional)

        Args:
            collection_name: Name of the collection
            query_vectors: Dict with 'dense', 'sparse', and 'colbert' vectors
            limit: Final number of results to return
            enable_rerank: Whether to apply ColBERT reranking
            prefetch_top_k: Number of candidates from each prefetch method

        Returns:
            List of ScoredPoint objects, sorted by score (highest first)

        Raises:
            CollectionNotFoundError: If collection doesn't exist
            QdrantConnectionError: If Qdrant operation fails
        """
        try:
            # Prefetch: Query dense and sparse vectors
            prefetch_results = []

            # Dense query
            if "dense" in query_vectors:
                dense_results = self.client.query_points(
                    collection_name=collection_name,
                    query=query_vectors["dense"],
                    query_filter=None,
                    limit=prefetch_top_k,
                    using="dense",
                )
                prefetch_results.extend(dense_results.points)

            # Sparse query
            if "sparse" in query_vectors:
                sparse_results = self.client.query_points(
                    collection_name=collection_name,
                    query=query_vectors["sparse"],
                    query_filter=None,
                    limit=prefetch_top_k,
                    using="sparse",
                )
                prefetch_results.extend(sparse_results.points)

            # Deduplicate by point ID (keep highest score)
            seen_ids = {}
            for point in prefetch_results:
                point_id = point.id
                if point_id not in seen_ids or point.score > seen_ids[point_id].score:
                    seen_ids[point_id] = point

            deduplicated = list(seen_ids.values())

            # Rerank using ColBERT if enabled
            if enable_rerank and "colbert" in query_vectors and deduplicated:
                # Extract point IDs from prefetch results for filtering
                prefetch_ids = {point.id for point in deduplicated}
                
                # Query ColBERT for reranking (Qdrant will use MaxSim automatically)
                # Query more candidates than needed to ensure we get prefetch results
                rerank_results = self.client.query_points(
                    collection_name=collection_name,
                    query=query_vectors["colbert"],
                    query_filter=None,
                    limit=min(len(deduplicated) * 2, 100),  # Query more to get prefetch candidates
                    using="colbert",
                )
                
                # Filter to only include prefetch candidates and return top-K
                reranked_filtered = [
                    point for point in rerank_results.points
                    if point.id in prefetch_ids
                ]
                return reranked_filtered[:limit]

            # If reranking disabled, return top-K by prefetch score
            sorted_results = sorted(
                deduplicated,
                key=lambda x: x.score,
                reverse=True,
            )
            return sorted_results[:limit]

        except Exception as e:
            error_msg = str(e).lower()
            if "not found" in error_msg or "does not exist" in error_msg:
                raise CollectionNotFoundError(
                    f"Collection '{collection_name}' not found"
                ) from e
            raise QdrantConnectionError(f"Failed to search: {e}") from e

    def validate_collection_exists(self, collection_name: str) -> bool:
        """Check if collection exists.

        Args:
            collection_name: Name of the collection to check

        Returns:
            True if collection exists, False otherwise

        Raises:
            QdrantConnectionError: If Qdrant operation fails
        """
        try:
            return self.client.collection_exists(collection_name)
        except Exception as e:
            raise QdrantConnectionError(f"Failed to validate collection: {e}") from e

    def delete_collection(
        self,
        collection_name: str,
        confirm: bool = False,
    ) -> None:
        """Delete a collection.

        Args:
            collection_name: Name of the collection to delete
            confirm: Must be True to confirm deletion

        Raises:
            ValueError: If confirm is False
            CollectionNotFoundError: If collection doesn't exist
            QdrantConnectionError: If Qdrant operation fails
        """
        if not confirm:
            raise ValueError(
                "Collection deletion requires explicit confirmation. "
                "Set confirm=True to delete."
            )

        try:
            if not self.client.collection_exists(collection_name):
                raise CollectionNotFoundError(
                    f"Collection '{collection_name}' not found"
                )
            self.client.delete_collection(collection_name)
        except CollectionNotFoundError:
            raise
        except Exception as e:
            raise QdrantConnectionError(f"Failed to delete collection: {e}") from e

