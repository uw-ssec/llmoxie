# Server lifecycle management

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastmcp import FastMCP

from llmaven.agentic.settings import config
from llmaven.agentic.search.hybrid_searcher import HybridSearcher


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict]:
    """Manage server lifecycle - initialize HybridSearcher on startup."""
    # Initialize HybridSearcher (lazy loads embedding models on first search)
    hybrid_searcher = HybridSearcher(collection_name=config.collection_name)

    yield {"hybrid_searcher": hybrid_searcher}

    # Cleanup (if needed)