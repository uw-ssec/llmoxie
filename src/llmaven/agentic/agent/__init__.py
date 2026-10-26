"""RAG Agent implementation using pydantic-ai.

This module provides the RAG agent with structured output and tool calling.
"""

__all__ = [
    "Citation",
    "RAGAgent",
    "RAGAgentDependencies",
    "RAGResponse",
]

from llmaven.agentic.agent.models import Citation, RAGResponse
from llmaven.agentic.agent.rag_agent import RAGAgent, RAGAgentDependencies
