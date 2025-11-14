"""Configuration for LLMaven Frontend (Streamlit UI).

This module provides frontend-specific configuration using Pydantic Settings.
"""

from __future__ import annotations

import textwrap

from pydantic_settings import BaseSettings, SettingsConfigDict


class FrontendConfig(BaseSettings):
    """Configuration for the Streamlit frontend.

    Attributes:
        api_base_url: Base URL for the LLMaven API
        embedding_model: Model used for embeddings/retrieval
        generation_model: Model used for text generation
        existing_collection: Name of existing Qdrant collection
        existing_qdrant_path: Path to existing Qdrant vector store
        retrieval_k: Number of relevant documents to retrieve
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_prefix="FRONTEND_",
    )

    api_base_url: str = "http://localhost:8000/api"
    embedding_model: str = "sentence-transformers/all-MiniLM-L12-v2"
    generation_model: str = "allenai/OLMo-2-1124-7B-Instruct"
    existing_collection: str = "rubin_telescope"
    existing_qdrant_path: str = "data/vector_stores/rubin_qdrant"
    retrieval_k: int = 2


# Global configuration instance
config = FrontendConfig()


# Helper functions
def expand_query(query: str) -> str:
    """Modify query for better retrieval.

    Args:
        query: The user's search query

    Returns:
        Expanded query with additional keywords
    """
    if "Rubin" in query:
        query += " LSST Large Synoptic Survey Telescope"
    return query


def format_prompt(context: str, question: str) -> str:
    """Format the retrieval context into the final prompt.

    Args:
        context: Retrieved document context
        question: User's question

    Returns:
        Formatted prompt for the generation model
    """
    return textwrap.dedent(f"""
    You are an astrophysics expert with a focus on the Rubin telescope project
    (formerly known as Large Synoptic Survey Telescope - LSST). Please answer the
    question on astrophysics based on the following context:

    {context}

    Question: {question}
    """)
