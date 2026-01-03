"""Agentic retrieve endpoint for hybrid search.

This module provides the API endpoint for executing hybrid search
with multi-vector retrieval (Dense, Sparse, ColBERT).
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from llmaven.agentic.search import HybridSearcher
from llmaven.agentic.search.models import SearchResult
from llmaven.agentic.exceptions import AgenticRAGError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agentic/retrieve", tags=["agentic"])


class AgenticRetrieveRequest(BaseModel):
    """Request schema for agentic retrieve endpoint.

    Attributes:
        query: Search query text
        collection: Collection name (optional, defaults to config)
        top_k: Number of results to return (optional, defaults to config)
        prefetch_k: Number of prefetch candidates per method (optional)
        enable_rerank: Whether to apply ColBERT reranking (optional)
    """

    query: str = Field(..., description="Search query text", min_length=1)
    collection: Optional[str] = Field(None, description="Collection name")
    top_k: Optional[int] = Field(None, description="Number of results to return", gt=0)
    prefetch_k: Optional[int] = Field(
        None, description="Number of prefetch candidates per method", gt=0
    )
    enable_rerank: Optional[bool] = Field(
        None, description="Whether to apply ColBERT reranking"
    )


class AgenticRetrieveResponse(BaseModel):
    """Response schema for agentic retrieve endpoint.

    Attributes:
        results: List of search results
        total_results: Total number of results returned
        reranking_enabled: Whether reranking was applied
    """

    results: list[SearchResult] = Field(..., description="Search results")
    total_results: int = Field(..., description="Total number of results returned")
    reranking_enabled: bool = Field(..., description="Whether reranking was applied")


@router.post("", response_model=AgenticRetrieveResponse)
async def agentic_retrieve(request: AgenticRetrieveRequest):
    """Execute hybrid search with multi-vector retrieval.

    This endpoint performs hybrid search using Dense, Sparse, and optionally
    ColBERT embeddings. The search pipeline includes:
    1. Query embedding generation (Dense, Sparse, ColBERT)
    2. Prefetch from Dense and Sparse vectors in parallel
    3. Optional reranking with ColBERT MaxSim

    Args:
        request: AgenticRetrieveRequest with query and search parameters

    Returns:
        AgenticRetrieveResponse with search results

    Raises:
        HTTPException: If search execution fails
    """
    try:
        logger.info(
            f"Agentic retrieve request: query='{request.query[:50]}...', "
            f"collection={request.collection}, top_k={request.top_k}"
        )

        # Create searcher with request parameters
        searcher = HybridSearcher(
            collection_name=request.collection,
            enable_rerank=request.enable_rerank,
            prefetch_top_k=request.prefetch_k,
            final_top_k=request.top_k,
        )

        # Execute search
        results = searcher.search(query=request.query)

        logger.info(f"Agentic retrieve completed: {len(results)} results")

        return AgenticRetrieveResponse(
            results=results,
            total_results=len(results),
            reranking_enabled=searcher.enable_rerank,
        )

    except AgenticRAGError as e:
        logger.error(f"Agentic retrieve failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error in agentic retrieve: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
