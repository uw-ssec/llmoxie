"""RAG Agent implementation using pydantic-ai.

This module provides the RAG agent with structured output and tool calling.
"""

__all__ = [
    "RAGAgent",
    "RAGAgentDependencies",
    "Citation",
    "RAGResponse",
]

# Models are pure pydantic with no heavy deps — keep eager
from llmaven.agentic.agent.models import Citation, RAGResponse


def __getattr__(name: str):
    """Lazy import for ML-dependent RAGAgent (imports HybridSearcher -> fastembed)."""
    if name in ("RAGAgent", "RAGAgentDependencies"):
        from llmaven.agentic.agent.rag_agent import RAGAgent, RAGAgentDependencies

        # Cache in module globals so __getattr__ isn't called again
        globals()["RAGAgent"] = RAGAgent
        globals()["RAGAgentDependencies"] = RAGAgentDependencies
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
