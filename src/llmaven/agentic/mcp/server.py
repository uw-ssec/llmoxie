# FastMCP server entry point


from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastmcp import FastMCP, Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from llmaven.agentic.exceptions import (
    CollectionNotFoundError,
    QdrantConnectionError,
    SearchError,
)
from llmaven.agentic.settings import config
from llmaven.agentic.search.hybrid_searcher import HybridSearcher
from llmaven.agentic.mcp.tools.search import (
    SearchKnowledgeBaseOutput,
    SearchResultOutput,
)


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict]:
    """Manage server lifecycle - initialize HybridSearcher on startup."""
    # Initialize HybridSearcher (lazy loads embedding models on first search)
    hybrid_searcher = HybridSearcher(collection_name=config.collection_name)

    yield {"hybrid_searcher": hybrid_searcher}

    # Cleanup (if needed)


# Create FastMCP server
mcp = FastMCP(
    name="llmaven-search",
    lifespan=lifespan,
)


@mcp.resource("health://status")
async def health_check(ctx: Context) -> str:
    """Return server health status.

    Verifies Qdrant connectivity and reports embedding model load state.
    Models use lazy loading, so they will show as 'not yet loaded' until
    the first search request is made (section 9.2).
    """
    try:
        hybrid_searcher: HybridSearcher = ctx.lifespan_context["hybrid_searcher"]
        # Verify Qdrant connectivity with a lightweight collections list call
        hybrid_searcher.qdrant_manager.client.get_collections()
        models_status = (
            "loaded" if hybrid_searcher._models_initialized else "not yet loaded (lazy)"
        )
        return f"healthy: qdrant connected, embedding models {models_status}"
    except Exception as e:
        return f"unhealthy: {e}"


@mcp.tool()
async def search_knowledge_base(
    ctx: Context,
    query: str = Field(description="Search query to find relevant information"),
    limit: int = Field(
        default=5, description="Maximum number of results", ge=1, le=100
    ),
    collection_name: str | None = Field(
        default=None, description="Collection to search"
    ),
    enable_rerank: bool | None = Field(
        default=None, description="Enable ColBERT reranking"
    ),
) -> SearchKnowledgeBaseOutput:
    """
    Search the knowledge base for relevant information using hybrid search.

    Combines dense vector search, sparse BM25 search, and optional ColBERT reranking
    to find the most relevant documents for your query.
    """
    try:
        hybrid_searcher: HybridSearcher = ctx.lifespan_context["hybrid_searcher"]

        # Override collection if specified
        if collection_name:
            hybrid_searcher = HybridSearcher(collection_name=collection_name)

        # Execute search
        results = hybrid_searcher.search(
            query=query,
            limit=limit,
            enable_rerank=enable_rerank,
        )

        # Convert to output format
        output_results = [
            SearchResultOutput(
                text=r.text,
                source_file=r.file_path,
                heading_hierarchy=r.heading_hierarchy,
                score=r.score,
                chunk_index=r.chunk_index,
            )
            for r in results
        ]

        return SearchKnowledgeBaseOutput(
            results=output_results,
            total_results=len(output_results),
            query=query,
            collection_name=collection_name or config.collection_name,
        )
    except CollectionNotFoundError as e:
        raise ToolError(f"Collection not found: {e}")
    except QdrantConnectionError as e:
        raise ToolError(f"Cannot connect to Qdrant: {e}")
    except SearchError as e:
        raise ToolError(f"Search failed: {e}")
