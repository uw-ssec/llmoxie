"""Hybrid search implementation for Agentic RAG.

This module provides hybrid search with Dense, Sparse, and ColBERT vectors.
"""

__all__ = [
    "HybridSearcher",
    "SearchResult",
]

# SearchResult is a pure data model with no heavy deps — keep eager
from llmaven.agentic.search.models import SearchResult


def __getattr__(name: str):
    """Lazy import for ML-dependent HybridSearcher."""
    if name == "HybridSearcher":
        from llmaven.agentic.search.hybrid_searcher import HybridSearcher

        return HybridSearcher
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
