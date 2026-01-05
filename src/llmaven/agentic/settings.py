"""Configuration for Agentic RAG components.

This module provides configuration management for the agentic RAG system
using Pydantic Settings, following the pattern from llmaven.config.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgenticConfig(BaseSettings):
    """Configuration for the agentic RAG system.

    Attributes:
        qdrant_url: Qdrant server URL (default: http://localhost:6333)
        qdrant_api_key: Optional API key for Qdrant authentication
        collection_name: Default collection name for agentic RAG (default: agentic-rag)
        dense_model: Dense embedding model (default: sentence-transformers/all-MiniLM-L6-v2)
        sparse_model: Sparse embedding model (default: Qdrant/bm25)
        colbert_model: ColBERT embedding model (default: colbert-ir/colbertv2.0)
        llm_provider: LLM provider to use (openai, ollama, litellm, azure, huggingface)
        llm_model: LLM model identifier
        litellm_api_base: Base URL for LiteLLM proxy server
        litellm_api_key: API key for LiteLLM authentication
        litellm_model_prefix: Model prefix for LiteLLM (e.g., "openai/", "anthropic/")
        azure_endpoint: Azure OpenAI endpoint URL
        azure_api_key: Azure API key for authentication
        azure_api_version: Azure API version (default: 2024-10-21)
        azure_deployment_name: Azure deployment name for the model
        huggingface_model: Optional HuggingFace model for local inference
        enable_rerank: Whether to enable ColBERT reranking (default: True)
        prefetch_top_k: Number of candidates from each prefetch method (default: 20)
        final_top_k: Final number of results to return (default: 5)
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Ignore unexpected environment variables
        env_prefix="AGENTIC_",  # Consistent with API_ prefix pattern
    )

    # Qdrant configuration
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None

    # Collection configuration
    collection_name: str = "agentic-rag"

    # Embedding model configuration
    dense_model: str = (
        "sentence-transformers/all-MiniLM-L6-v2"  # 384-dim (fastembed supported)
    )
    sparse_model: str = "Qdrant/bm25"
    colbert_model: str = "colbert-ir/colbertv2.0"

    # LLM provider configuration
    llm_provider: Literal["openai", "ollama", "litellm", "azure", "huggingface"] = (
        "openai"
    )
    llm_model: str = "gpt-4o-mini"

    # LiteLLM-specific configuration
    litellm_api_base: str | None = None  # e.g., "http://localhost:4000" for proxy
    litellm_api_key: str | None = None
    litellm_model_prefix: str = ""  # e.g., "openai/" or "anthropic/" or "custom/"

    # Azure AI Foundry configuration
    azure_endpoint: str | None = None  # e.g., "https://<resource>.openai.azure.com"
    azure_api_key: str | None = None
    azure_api_version: str = "2024-10-21"  # Default to stable API version
    azure_deployment_name: str | None = None  # Azure deployment name

    # HuggingFace configuration
    huggingface_model: str | None = None  # For local HuggingFace models

    # Search configuration
    enable_rerank: bool = True
    prefetch_top_k: int = Field(
        default=20, gt=0, description="Number of candidates from each prefetch method"
    )
    final_top_k: int = Field(
        default=5, gt=0, description="Final number of results to return"
    )


# Global configuration instance
config = AgenticConfig()
