"""Document ingestion pipeline for Agentic RAG.

This module provides document loading, parsing, chunking, and embedding capabilities.
"""

__all__ = ["IngestionPipeline"]


def __getattr__(name: str):
    """Lazy import for ML-dependent IngestionPipeline."""
    if name == "IngestionPipeline":
        from llmaven.agentic.ingestion.pipeline import IngestionPipeline

        return IngestionPipeline
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
