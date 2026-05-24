"""Tests for LLM provider factory.

This module tests the provider factory and its ability to create
different LLM models based on configuration.
"""

from unittest.mock import patch, MagicMock

import pytest

from llmaven.agentic.providers.factory import (
    create_llm_model,
    _create_openai_model,
    _create_ollama_model,
    _create_litellm_model,
    _create_azure_model,
    _create_huggingface_model,
)
from llmaven.agentic.exceptions import ProviderConfigurationError


class TestProviderFactory:
    """Test suite for provider factory."""

    def test_create_openai_model(self):
        """Test creating OpenAI model."""
        with patch("llmaven.agentic.providers.factory.config") as mock_config:
            mock_config.llm_provider = "openai"
            mock_config.llm_model = "gpt-4o-mini"

            with patch(
                "llmaven.agentic.providers.factory._create_openai_model"
            ) as mock_create:
                mock_create.return_value = MagicMock()
                result = create_llm_model()
                mock_create.assert_called_once()
                assert result is not None

    def test_create_ollama_model(self):
        """Test creating Ollama model."""
        with patch("llmaven.agentic.providers.factory.config") as mock_config:
            mock_config.llm_provider = "ollama"
            mock_config.llm_model = "llama2"

            with patch(
                "llmaven.agentic.providers.factory._create_ollama_model"
            ) as mock_create:
                mock_create.return_value = MagicMock()
                result = create_llm_model()
                mock_create.assert_called_once()
                assert result is not None

    def test_create_litellm_model(self):
        """Test creating LiteLLM model."""
        with patch("llmaven.agentic.providers.factory.config") as mock_config:
            mock_config.llm_provider = "litellm"
            mock_config.llm_model = "gpt-4o-mini"
            mock_config.litellm_api_base = "http://localhost:4000"

            with patch(
                "llmaven.agentic.providers.factory._create_litellm_model"
            ) as mock_create:
                mock_create.return_value = MagicMock()
                result = create_llm_model()
                mock_create.assert_called_once()
                assert result is not None

    def test_create_azure_model(self):
        """Test creating Azure model."""
        with patch("llmaven.agentic.providers.factory.config") as mock_config:
            mock_config.llm_provider = "azure"
            mock_config.llm_model = "gpt-4o"
            mock_config.azure_endpoint = "https://myresource.openai.azure.com"
            mock_config.azure_api_key = "test-key"

            with patch(
                "llmaven.agentic.providers.factory._create_azure_model"
            ) as mock_create:
                mock_create.return_value = MagicMock()
                result = create_llm_model()
                mock_create.assert_called_once()
                assert result is not None

    def test_create_huggingface_model_not_implemented(self):
        """Test that HuggingFace provider raises NotImplementedError."""
        with patch("llmaven.agentic.providers.factory.config") as mock_config:
            mock_config.llm_provider = "huggingface"

            with pytest.raises(
                NotImplementedError, match="HuggingFace provider is not yet implemented"
            ):
                create_llm_model()

    def test_unsupported_provider(self):
        """Test that unsupported provider raises ProviderConfigurationError."""
        with patch("llmaven.agentic.providers.factory.config") as mock_config:
            mock_config.llm_provider = "invalid_provider"

            with pytest.raises(
                ProviderConfigurationError, match="Unsupported provider"
            ):
                create_llm_model()


class TestOpenAIProvider:
    """Test suite for OpenAI provider creation."""

    @patch("pydantic_ai.models.openai.OpenAIChatModel")
    @patch("pydantic_ai.providers.openai.OpenAIProvider")
    def test_create_openai_model_direct(self, mock_provider_class, mock_model_class):
        """Test creating OpenAI model directly."""
        from unittest.mock import ANY

        with patch("llmaven.agentic.providers.factory.config") as mock_config:
            mock_config.llm_model = "gpt-4o-mini"
            mock_provider_instance = MagicMock()
            mock_provider_class.return_value = mock_provider_instance
            mock_model_class.return_value = MagicMock()

            result = _create_openai_model()

            mock_provider_class.assert_called_once_with(http_client=ANY)
            mock_model_class.assert_called_once_with(
                "gpt-4o-mini", provider=mock_provider_instance
            )
            assert result is not None


class TestOllamaProvider:
    """Test suite for Ollama provider creation."""

    @patch("pydantic_ai.models.openai.OpenAIChatModel")
    @patch("pydantic_ai.providers.ollama.OllamaProvider")
    @patch.dict("os.environ", {}, clear=True)
    def test_create_ollama_model_defaults(self, mock_provider_class, mock_model_class):
        """Test creating Ollama model with default settings."""
        with patch("llmaven.agentic.providers.factory.config") as mock_config:
            mock_config.llm_model = "llama2"
            mock_provider_instance = MagicMock()
            mock_provider_class.return_value = mock_provider_instance
            mock_model_class.return_value = MagicMock()

            result = _create_ollama_model()

            from unittest.mock import ANY

            mock_provider_class.assert_called_once_with(
                base_url="http://localhost:11434/v1",
                api_key="ollama",
                http_client=ANY,
            )
            mock_model_class.assert_called_once_with(
                "llama2",
                provider=mock_provider_instance,
            )
            assert result is not None

    @patch("pydantic_ai.models.openai.OpenAIChatModel")
    @patch("pydantic_ai.providers.ollama.OllamaProvider")
    @patch.dict(
        "os.environ",
        {"OLLAMA_BASE_URL": "http://custom:8080/v1", "OLLAMA_API_KEY": "custom-key"},
    )
    def test_create_ollama_model_custom_env(
        self, mock_provider_class, mock_model_class
    ):
        """Test creating Ollama model with custom environment variables."""
        with patch("llmaven.agentic.providers.factory.config") as mock_config:
            mock_config.llm_model = "llama2"
            mock_provider_instance = MagicMock()
            mock_provider_class.return_value = mock_provider_instance
            mock_model_class.return_value = MagicMock()

            result = _create_ollama_model()

            from unittest.mock import ANY

            mock_provider_class.assert_called_once_with(
                base_url="http://custom:8080/v1",
                api_key="custom-key",
                http_client=ANY,
            )
            mock_model_class.assert_called_once_with(
                "llama2",
                provider=mock_provider_instance,
            )
            assert result is not None


class TestLiteLLMProvider:
    """Test suite for LiteLLM provider creation."""

    @patch("pydantic_ai.models.openai.OpenAIChatModel")
    @patch("pydantic_ai.providers.openai.OpenAIProvider")
    def test_create_litellm_model_success(self, mock_provider_class, mock_model_class):
        """Test creating LiteLLM model with valid configuration."""
        with patch("llmaven.agentic.providers.factory.config") as mock_config:
            mock_config.litellm_api_base = "http://localhost:4000"
            mock_config.litellm_api_key = "test-key"
            mock_config.litellm_model_prefix = "openai/"
            mock_config.llm_model = "gpt-4o-mini"
            mock_provider_instance = MagicMock()
            mock_provider_class.return_value = mock_provider_instance
            mock_model_class.return_value = MagicMock()

            result = _create_litellm_model()

            from unittest.mock import ANY

            mock_provider_class.assert_called_once_with(
                base_url="http://localhost:4000",
                api_key="test-key",
                http_client=ANY,
            )
            mock_model_class.assert_called_once_with(
                "openai/gpt-4o-mini",
                provider=mock_provider_instance,
            )
            assert result is not None

    @patch("pydantic_ai.models.openai.OpenAIChatModel")
    @patch("pydantic_ai.providers.openai.OpenAIProvider")
    def test_create_litellm_model_no_prefix(
        self, mock_provider_class, mock_model_class
    ):
        """Test creating LiteLLM model without model prefix."""
        with patch("llmaven.agentic.providers.factory.config") as mock_config:
            mock_config.litellm_api_base = "http://localhost:4000"
            mock_config.litellm_api_key = None
            mock_config.litellm_model_prefix = ""
            mock_config.llm_model = "gpt-4o-mini"
            mock_provider_instance = MagicMock()
            mock_provider_class.return_value = mock_provider_instance
            mock_model_class.return_value = MagicMock()

            result = _create_litellm_model()

            from unittest.mock import ANY

            mock_provider_class.assert_called_once_with(
                base_url="http://localhost:4000",
                api_key="dummy",
                http_client=ANY,
            )
            mock_model_class.assert_called_once_with(
                "gpt-4o-mini",
                provider=mock_provider_instance,
            )
            assert result is not None

    def test_create_litellm_model_missing_base_url(self):
        """Test that missing LiteLLM base URL raises error."""
        with patch("llmaven.agentic.providers.factory.config") as mock_config:
            mock_config.litellm_api_base = None

            with pytest.raises(
                ProviderConfigurationError,
                match="AGENTIC_LITELLM_API_BASE is required for LiteLLM provider",
            ):
                _create_litellm_model()

    @patch("httpx.AsyncClient")
    @patch("pydantic_ai.models.openai.OpenAIChatModel")
    @patch("pydantic_ai.providers.openai.OpenAIProvider")
    def test_create_litellm_model_with_tags(self, mock_provider_class, mock_model_class, mock_http_client_class):
        """Test that tags are sent via x-litellm-tags header."""
        with patch("llmaven.agentic.providers.factory.config") as mock_config:
            mock_config.litellm_api_base = "http://localhost:4000"
            mock_config.litellm_api_key = "test-key"
            mock_config.litellm_model_prefix = ""
            mock_config.llm_model = "gpt-4o-mini"
            mock_http_client_class.return_value = MagicMock()
            mock_provider_class.return_value = MagicMock()
            mock_model_class.return_value = MagicMock()

            _create_litellm_model(tags=["study-xyz", "rubin-lsst"])

            call_kwargs = mock_http_client_class.call_args[1]
            assert call_kwargs["headers"]["x-litellm-tags"] == "study-xyz,rubin-lsst"

    @patch("httpx.AsyncClient")
    @patch("pydantic_ai.models.openai.OpenAIChatModel")
    @patch("pydantic_ai.providers.openai.OpenAIProvider")
    def test_create_litellm_model_without_tags(self, mock_provider_class, mock_model_class, mock_http_client_class):
        """Test that no x-litellm-tags header is set when tags is None."""
        with patch("llmaven.agentic.providers.factory.config") as mock_config:
            mock_config.litellm_api_base = "http://localhost:4000"
            mock_config.litellm_api_key = "test-key"
            mock_config.litellm_model_prefix = ""
            mock_config.llm_model = "gpt-4o-mini"
            mock_http_client_class.return_value = MagicMock()
            mock_provider_class.return_value = MagicMock()
            mock_model_class.return_value = MagicMock()

            _create_litellm_model(tags=None)

            call_kwargs = mock_http_client_class.call_args[1]
            assert "x-litellm-tags" not in call_kwargs.get("headers", {})

class TestAzureProvider:
    """Test suite for Azure provider creation."""

    @patch("pydantic_ai.models.openai.OpenAIChatModel")
    @patch("pydantic_ai.providers.openai.OpenAIProvider")
    @patch("httpx.AsyncClient")
    def test_create_azure_model_success(
        self, mock_http_client_class, mock_provider_class, mock_model_class
    ):
        """Test creating Azure model with valid configuration."""
        with patch("llmaven.agentic.providers.factory.config") as mock_config:
            mock_config.azure_endpoint = "https://myresource.openai.azure.com"
            mock_config.azure_api_key = "test-key"
            mock_config.azure_deployment_name = "gpt-4o-deployment"
            mock_config.llm_model = "gpt-4o"
            mock_config.azure_api_version = "2024-10-21"
            mock_http_client_instance = MagicMock()
            mock_http_client_class.return_value = mock_http_client_instance
            mock_provider_instance = MagicMock()
            mock_provider_class.return_value = mock_provider_instance
            mock_model_class.return_value = MagicMock()

            result = _create_azure_model()

            mock_http_client_class.assert_called_once()
            http_call_kwargs = mock_http_client_class.call_args[1]
            assert http_call_kwargs["params"]["api-version"] == "2024-10-21"
            assert http_call_kwargs["headers"]["api-key"] == "test-key"

            mock_provider_class.assert_called_once()
            provider_call_kwargs = mock_provider_class.call_args[1]
            assert (
                provider_call_kwargs["base_url"]
                == "https://myresource.openai.azure.com/openai/deployments/gpt-4o-deployment"
            )
            assert provider_call_kwargs["api_key"] == "test-key"
            assert provider_call_kwargs["http_client"] == mock_http_client_instance

            mock_model_class.assert_called_once_with(
                "gpt-4o-deployment",
                provider=mock_provider_instance,
            )
            assert result is not None

    @patch("pydantic_ai.models.openai.OpenAIChatModel")
    @patch("pydantic_ai.providers.openai.OpenAIProvider")
    @patch("httpx.AsyncClient")
    def test_create_azure_model_no_deployment_name(
        self, mock_http_client_class, mock_provider_class, mock_model_class
    ):
        """Test creating Azure model without deployment name (uses model name)."""
        with patch("llmaven.agentic.providers.factory.config") as mock_config:
            mock_config.azure_endpoint = "https://myresource.openai.azure.com"
            mock_config.azure_api_key = "test-key"
            mock_config.azure_deployment_name = None
            mock_config.llm_model = "gpt-4o"
            mock_config.azure_api_version = "2024-10-21"
            mock_http_client_instance = MagicMock()
            mock_http_client_class.return_value = mock_http_client_instance
            mock_provider_instance = MagicMock()
            mock_provider_class.return_value = mock_provider_instance
            mock_model_class.return_value = MagicMock()

            result = _create_azure_model()

            mock_provider_class.assert_called_once()
            provider_call_kwargs = mock_provider_class.call_args[1]
            assert (
                provider_call_kwargs["base_url"]
                == "https://myresource.openai.azure.com/openai/deployments/gpt-4o"
            )

            mock_model_class.assert_called_once_with(
                "gpt-4o",
                provider=mock_provider_instance,
            )
            assert result is not None

    def test_create_azure_model_missing_endpoint(self):
        """Test that missing Azure endpoint raises error."""
        with patch("llmaven.agentic.providers.factory.config") as mock_config:
            mock_config.azure_endpoint = None
            mock_config.azure_api_key = "test-key"

            with pytest.raises(
                ProviderConfigurationError,
                match="AGENTIC_AZURE_ENDPOINT is required for Azure provider",
            ):
                _create_azure_model()

    def test_create_azure_model_missing_api_key(self):
        """Test that missing Azure API key raises error."""
        with patch("llmaven.agentic.providers.factory.config") as mock_config:
            mock_config.azure_endpoint = "https://myresource.openai.azure.com"
            mock_config.azure_api_key = None

            with pytest.raises(
                ProviderConfigurationError,
                match="AGENTIC_AZURE_API_KEY is required for Azure provider",
            ):
                _create_azure_model()


class TestHuggingFaceProvider:
    """Test suite for HuggingFace provider creation."""

    def test_create_huggingface_model_not_implemented(self):
        """Test that HuggingFace provider is not implemented."""
        with pytest.raises(
            NotImplementedError, match="HuggingFace provider is not yet implemented"
        ):
            _create_huggingface_model()
