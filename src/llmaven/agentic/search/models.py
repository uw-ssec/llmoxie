"""Data models for search results and queries.

This module defines Pydantic models for structured search results
with metadata about scores and sources.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, ConfigDict


class SearchResult(BaseModel):
    """Result from hybrid search with multi-vector retrieval.

    Attributes:
        text: The text content of the retrieved chunk
        file_path: Path to the source file
        heading_hierarchy: Optional heading hierarchy from document structure
        score: Final score (rerank score if reranking enabled, else prefetch score)
        prefetch_score: Original score from prefetch phase (dense/sparse)
        rerank_score: Optional ColBERT rerank score (if reranking enabled)
        chunk_index: Index of the chunk within the source document
        content_hash: MD5 hash of the chunk content
    """

    text: str = Field(..., description="Text content of the retrieved chunk")
    file_path: str = Field(..., description="Path to the source file")
    heading_hierarchy: str | None = Field(
        None, description="Heading hierarchy from document structure"
    )
    score: float = Field(..., description="Final relevance score")
    prefetch_score: float | None = Field(
        None, description="Original prefetch score before reranking"
    )
    rerank_score: float | None = Field(
        None, description="ColBERT rerank score if enabled"
    )
    chunk_index: int = Field(0, description="Index of chunk within source document")
    content_hash: str | None = Field(None, description="MD5 hash of chunk content")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "text": "Machine learning is a subset of artificial intelligence...",
                "file_path": "/docs/ml-intro.md",
                "heading_hierarchy": "Introduction > Machine Learning Basics",
                "score": 0.89,
                "prefetch_score": 0.75,
                "rerank_score": 0.89,
                "chunk_index": 2,
                "content_hash": "a1b2c3d4e5f6...",
            }
        }
    )
