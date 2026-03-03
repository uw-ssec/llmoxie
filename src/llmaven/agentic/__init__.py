"""Agentic RAG system for LLMaven.

This package provides advanced RAG capabilities with multi-vector embeddings
(Dense, Sparse, ColBERT) and hybrid search using Qdrant Named Vectors.
"""

__all__ = [
    "config",
    "AgenticRAGError",
    "QdrantManager",
    "IngestionPipeline",
    "HybridSearcher",
    "SearchResult",
    "RAGAgent",
    "RAGResponse",
    "Citation",
]

# Eager imports for lightweight modules only
from llmaven.agentic.settings import config
from llmaven.agentic.exceptions import AgenticRAGError
from llmaven.agentic.vector_store import QdrantManager
from llmaven.agentic.search.models import SearchResult
from llmaven.agentic.agent.models import RAGResponse, Citation

# Lazy imports for names whose modules pull in fastembed/torch
_LAZY_IMPORTS = {
    "IngestionPipeline": "llmaven.agentic.ingestion.pipeline",
    "HybridSearcher": "llmaven.agentic.search.hybrid_searcher",
    "RAGAgent": "llmaven.agentic.agent.rag_agent",
    "RAGAgentDependencies": "llmaven.agentic.agent.rag_agent",
}


def __getattr__(name: str):
    """Lazy import for ML-dependent modules."""
    if name in _LAZY_IMPORTS:
        import importlib

        module = importlib.import_module(_LAZY_IMPORTS[name])
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
