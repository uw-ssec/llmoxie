"""Tests for AgenticConfig settings.

This module tests the configuration management for the agentic RAG system,
including default values, environment variable loading, and validation.
"""

import os
import pytest
from pydantic import ValidationError

from llmaven.agentic.settings import AgenticConfig


class TestAgenticConfigDefaults:
    """Test default configuration values."""

    def test_default_qdrant_url(self):
        """Test default Qdrant URL."""
        config = AgenticConfig()
        assert config.qdrant_url == "http://localhost:6333"

    def test_default_qdrant_api_key(self):
        """Test default Qdrant API key is None."""
        config = AgenticConfig()
        assert config.qdrant_api_key is None

    def test_default_collection_name(self):
        """Test default collection name."""
        config = AgenticConfig()
        assert config.collection_name == "agentic-rag"

    def test_default_dense_model(self):
        """Test default dense embedding model."""
        config = AgenticConfig()
        assert config.dense_model == "sentence-transformers/all-MiniLM-L6-v2"

    def test_default_sparse_model(self):
        """Test default sparse embedding model."""
        config = AgenticConfig()
        assert config.sparse_model == "Qdrant/bm25"

    def test_default_colbert_model(self):
        """Test default ColBERT embedding model."""
        config = AgenticConfig()
        assert config.colbert_model == "colbert-ir/colbertv2.0"

    def test_default_llm_provider(self):
        """Test default LLM provider."""
        config = AgenticConfig()
        assert config.llm_provider == "openai"

    def test_default_llm_model(self):
        """Test default LLM model."""
        config = AgenticConfig()
        assert config.llm_model == "gpt-4o-mini"

    def test_default_huggingface_model(self):
        """Test default HuggingFace model is None."""
        config = AgenticConfig()
        assert config.huggingface_model is None

    def test_default_enable_rerank(self):
        """Test default rerank setting."""
        config = AgenticConfig()
        assert config.enable_rerank is True

    def test_default_prefetch_top_k(self):
        """Test default prefetch top-k value."""
        config = AgenticConfig()
        assert config.prefetch_top_k == 20

    def test_default_final_top_k(self):
        """Test default final top-k value."""
        config = AgenticConfig()
        assert config.final_top_k == 5


class TestAgenticConfigEnvironmentVariables:
    """Test environment variable loading."""

    def test_qdrant_url_from_env(self):
        """Test Qdrant URL loaded from environment variable."""
        os.environ["AGENTIC_QDRANT_URL"] = "http://custom:6333"
        try:
            config = AgenticConfig()
            assert config.qdrant_url == "http://custom:6333"
        finally:
            del os.environ["AGENTIC_QDRANT_URL"]

    def test_qdrant_api_key_from_env(self):
        """Test Qdrant API key loaded from environment variable."""
        os.environ["AGENTIC_QDRANT_API_KEY"] = "test-api-key-123"
        try:
            config = AgenticConfig()
            assert config.qdrant_api_key == "test-api-key-123"
        finally:
            del os.environ["AGENTIC_QDRANT_API_KEY"]

    def test_collection_name_from_env(self):
        """Test collection name loaded from environment variable."""
        os.environ["AGENTIC_COLLECTION_NAME"] = "test-collection"
        try:
            config = AgenticConfig()
            assert config.collection_name == "test-collection"
        finally:
            del os.environ["AGENTIC_COLLECTION_NAME"]

    def test_dense_model_from_env(self):
        """Test dense model loaded from environment variable."""
        os.environ["AGENTIC_DENSE_MODEL"] = "custom/dense-model"
        try:
            config = AgenticConfig()
            assert config.dense_model == "custom/dense-model"
        finally:
            del os.environ["AGENTIC_DENSE_MODEL"]

    def test_sparse_model_from_env(self):
        """Test sparse model loaded from environment variable."""
        os.environ["AGENTIC_SPARSE_MODEL"] = "custom/sparse-model"
        try:
            config = AgenticConfig()
            assert config.sparse_model == "custom/sparse-model"
        finally:
            del os.environ["AGENTIC_SPARSE_MODEL"]

    def test_colbert_model_from_env(self):
        """Test ColBERT model loaded from environment variable."""
        os.environ["AGENTIC_COLBERT_MODEL"] = "custom/colbert-model"
        try:
            config = AgenticConfig()
            assert config.colbert_model == "custom/colbert-model"
        finally:
            del os.environ["AGENTIC_COLBERT_MODEL"]

    def test_llm_provider_from_env(self):
        """Test LLM provider loaded from environment variable."""
        os.environ["AGENTIC_LLM_PROVIDER"] = "ollama"
        try:
            config = AgenticConfig()
            assert config.llm_provider == "ollama"
        finally:
            del os.environ["AGENTIC_LLM_PROVIDER"]

    def test_llm_model_from_env(self):
        """Test LLM model loaded from environment variable."""
        os.environ["AGENTIC_LLM_MODEL"] = "llama2"
        try:
            config = AgenticConfig()
            assert config.llm_model == "llama2"
        finally:
            del os.environ["AGENTIC_LLM_MODEL"]

    def test_huggingface_model_from_env(self):
        """Test HuggingFace model loaded from environment variable."""
        os.environ["AGENTIC_HUGGINGFACE_MODEL"] = "allenai/OLMo-2-1124-7B-Instruct"
        try:
            config = AgenticConfig()
            assert config.huggingface_model == "allenai/OLMo-2-1124-7B-Instruct"
        finally:
            del os.environ["AGENTIC_HUGGINGFACE_MODEL"]

    def test_enable_rerank_from_env(self):
        """Test enable_rerank loaded from environment variable."""
        os.environ["AGENTIC_ENABLE_RERANK"] = "false"
        try:
            config = AgenticConfig()
            assert config.enable_rerank is False
        finally:
            del os.environ["AGENTIC_ENABLE_RERANK"]

    def test_prefetch_top_k_from_env(self):
        """Test prefetch_top_k loaded from environment variable."""
        os.environ["AGENTIC_PREFETCH_TOP_K"] = "50"
        try:
            config = AgenticConfig()
            assert config.prefetch_top_k == 50
        finally:
            del os.environ["AGENTIC_PREFETCH_TOP_K"]

    def test_final_top_k_from_env(self):
        """Test final_top_k loaded from environment variable."""
        os.environ["AGENTIC_FINAL_TOP_K"] = "10"
        try:
            config = AgenticConfig()
            assert config.final_top_k == 10
        finally:
            del os.environ["AGENTIC_FINAL_TOP_K"]

    def test_case_insensitive_env_vars(self):
        """Test that environment variables are case-insensitive."""
        os.environ["agentic_qdrant_url"] = "http://lowercase:6333"
        try:
            config = AgenticConfig()
            assert config.qdrant_url == "http://lowercase:6333"
        finally:
            del os.environ["agentic_qdrant_url"]

    def test_ignores_unprefixed_env_vars(self):
        """Test that non-AGENTIC_ prefixed variables are ignored."""
        os.environ["QDRANT_URL"] = "http://should-be-ignored:6333"
        try:
            config = AgenticConfig()
            assert config.qdrant_url == "http://localhost:6333"  # Default value
        finally:
            del os.environ["QDRANT_URL"]


class TestAgenticConfigValidation:
    """Test configuration validation."""

    def test_valid_config(self):
        """Test that valid configuration is accepted."""
        config = AgenticConfig(
            qdrant_url="http://test:6333",
            collection_name="test-collection",
            prefetch_top_k=30,
            final_top_k=10,
        )
        assert config.qdrant_url == "http://test:6333"
        assert config.collection_name == "test-collection"
        assert config.prefetch_top_k == 30
        assert config.final_top_k == 10

    def test_prefetch_top_k_must_be_positive(self):
        """Test that prefetch_top_k must be positive."""
        with pytest.raises(ValidationError):
            AgenticConfig(prefetch_top_k=-1)

    def test_final_top_k_must_be_positive(self):
        """Test that final_top_k must be positive."""
        with pytest.raises(ValidationError):
            AgenticConfig(final_top_k=0)

    def test_boolean_enable_rerank(self):
        """Test that enable_rerank accepts boolean values."""
        config_false = AgenticConfig(enable_rerank=False)
        config_true = AgenticConfig(enable_rerank=True)
        assert config_false.enable_rerank is False
        assert config_true.enable_rerank is True

    def test_string_types(self):
        """Test that string fields accept string values."""
        config = AgenticConfig(
            qdrant_url="http://test:6333",
            collection_name="test",
            dense_model="test/model",
            sparse_model="test/sparse",
            colbert_model="test/colbert",
            llm_provider="huggingface",
            llm_model="test-model",
        )
        assert isinstance(config.qdrant_url, str)
        assert isinstance(config.collection_name, str)
        assert isinstance(config.dense_model, str)
        assert isinstance(config.sparse_model, str)
        assert isinstance(config.colbert_model, str)
        assert isinstance(config.llm_provider, str)
        assert isinstance(config.llm_model, str)


class TestAgenticConfigGlobalInstance:
    """Test the global configuration instance."""

    def test_global_config_exists(self):
        """Test that global config instance exists."""
        from llmaven.agentic.settings import config

        assert isinstance(config, AgenticConfig)

    def test_global_config_has_defaults(self):
        """Test that global config has default values."""
        from llmaven.agentic.settings import config

        assert config.qdrant_url == "http://localhost:6333"
        assert config.collection_name == "agentic-rag"

    def test_global_config_importable(self):
        """Test that global config can be imported from package."""
        from llmaven.agentic import config

        assert isinstance(config, AgenticConfig)


class TestAgenticConfigEdgeCases:
    """Test edge cases and special scenarios."""

    def test_empty_string_values(self):
        """Test that empty strings are accepted (though not recommended)."""
        config = AgenticConfig(
            qdrant_url="",
            collection_name="",
        )
        assert config.qdrant_url == ""
        assert config.collection_name == ""

    def test_none_api_key(self):
        """Test that None API key is valid."""
        config = AgenticConfig(qdrant_api_key=None)
        assert config.qdrant_api_key is None

    def test_none_huggingface_model(self):
        """Test that None HuggingFace model is valid."""
        config = AgenticConfig(huggingface_model=None)
        assert config.huggingface_model is None

    def test_all_providers(self):
        """Test all supported LLM providers."""
        providers = ["openai", "ollama", "huggingface"]
        for provider in providers:
            config = AgenticConfig(llm_provider=provider)
            assert config.llm_provider == provider

    def test_large_top_k_values(self):
        """Test that large top-k values are accepted."""
        config = AgenticConfig(
            prefetch_top_k=1000,
            final_top_k=100,
        )
        assert config.prefetch_top_k == 1000
        assert config.final_top_k == 100
