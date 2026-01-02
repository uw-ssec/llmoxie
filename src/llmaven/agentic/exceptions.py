"""Exception hierarchy for Agentic RAG system.

This module defines custom exceptions for the agentic RAG components,
providing clear error handling and user-friendly error messages.
"""


class AgenticRAGError(Exception):
    """Base exception for agentic RAG errors.

    All agentic RAG-specific exceptions should inherit from this class.
    """

    pass


class IngestionError(AgenticRAGError):
    """Errors during document ingestion.

    Raised when document loading, parsing, chunking, or embedding fails.
    """

    pass


class QdrantConnectionError(AgenticRAGError):
    """Qdrant connection or communication errors.

    Raised when unable to connect to Qdrant or when communication fails.
    """

    pass


class CollectionNotFoundError(AgenticRAGError):
    """Collection does not exist.

    Raised when attempting to access a Qdrant collection that doesn't exist.
    """

    pass


class EmbeddingError(AgenticRAGError):
    """Errors during embedding generation.

    Raised when embedding model loading or vector generation fails.
    """

    pass


class SearchError(AgenticRAGError):
    """Errors during search operations.

    Raised when search query execution or result processing fails.
    """

    pass


class ProviderConfigurationError(AgenticRAGError):
    """Provider configuration is invalid or incomplete.

    Raised when LLM provider configuration is missing required fields
    or contains invalid values.
    """

    pass
