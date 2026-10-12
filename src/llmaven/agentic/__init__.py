"""Agentic RAG system for LLMaven.

This package provides advanced RAG capabilities with multi-vector embeddings
(Dense, Sparse, ColBERT) and hybrid search using Qdrant Named Vectors.
"""

__all__ = [
    "AgenticRAGError",
    "Citation",
    "HybridSearcher",
    "IngestionPipeline",
    "QdrantManager",
    "RAGAgent",
    "RAGResponse",
    "SearchResult",
    "config",
]

from llmaven.agentic.agent import RAGAgent
from llmaven.agentic.agent.models import Citation, RAGResponse
from llmaven.agentic.exceptions import AgenticRAGError
from llmaven.agentic.ingestion import IngestionPipeline
from llmaven.agentic.search import HybridSearcher
from llmaven.agentic.search.models import SearchResult
from llmaven.agentic.settings import config
from llmaven.agentic.vector_store import QdrantManager
