"""Provider factory for dynamic LLM model creation.

This module provides a factory function that creates the appropriate LLM model
based on the configured provider (OpenAI, Ollama, LiteLLM, Azure, HuggingFace).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic_ai.models.openai import OpenAIChatModel

from llmaven.agentic.exceptions import ProviderConfigurationError
from llmaven.agentic.settings import config


def create_llm_model(
    provider: str | None = None,
    model: str | None = None,
) -> OpenAIChatModel:
    """Create an LLM model based on the configured provider.

    Args:
        provider: Optional provider override. Defaults to ``config.llm_provider``.
        model: Optional model override. Defaults to ``config.llm_model``.

    Returns:
        OpenAIChatModel: The configured LLM model instance.

    Raises:
        ProviderConfigurationError: If the provider is unsupported or configuration is invalid.
    """
    resolved_provider = (provider or config.llm_provider).lower()
    resolved_model = model or config.llm_model

    if resolved_provider == "openai":
        return _create_openai_model(resolved_model)
    elif resolved_provider == "ollama":
        return _create_ollama_model(resolved_model)
    elif resolved_provider == "litellm":
        return _create_litellm_model(resolved_model)
    elif resolved_provider == "azure":
        return _create_azure_model(resolved_model)
    elif resolved_provider == "huggingface":
        return _create_huggingface_model()
    else:
        raise ProviderConfigurationError(f"Unsupported provider: {resolved_provider}")


def _create_openai_model(model: str) -> OpenAIChatModel:
    """Create OpenAI model using default provider.

    Returns:
        OpenAIChatModel: OpenAI model instance.
    """
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider
    import httpx

    # Create HTTP client with timeout configuration
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(300.0, connect=10.0),  # 5 min total, 10 sec connect
    )

    provider = OpenAIProvider(http_client=http_client)
    return OpenAIChatModel(model, provider=provider)


def _create_ollama_model(model: str) -> OpenAIChatModel:
    """Create Ollama model using OpenAI-compatible endpoint.

    Ollama provides an OpenAI-compatible API at /v1 endpoint.

    Returns:
        OpenAIChatModel: Ollama model configured with OpenAI compatibility.
    """
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.ollama import OllamaProvider
    import httpx

    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    api_key = os.getenv("OLLAMA_API_KEY", "ollama")  # Ollama doesn't require a real key

    # Create HTTP client with timeout configuration
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(300.0, connect=10.0),  # 5 min total, 10 sec connect
    )

    provider = OllamaProvider(
        base_url=base_url, api_key=api_key, http_client=http_client
    )
    return OpenAIChatModel(model, provider=provider)


def _create_litellm_model(model: str) -> OpenAIChatModel:
    """Create LiteLLM model for unified provider access.

    LiteLLM provides a unified interface to 100+ LLM providers through
    either a proxy server or direct SDK usage.

    Returns:
        OpenAIChatModel: LiteLLM model instance.

    Raises:
        ProviderConfigurationError: If required LiteLLM configuration is missing.
    """
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    if not config.litellm_api_base:
        raise ProviderConfigurationError(
            "AGENTIC_LITELLM_API_BASE is required for LiteLLM provider. "
            "Set it to your LiteLLM proxy URL (e.g., http://localhost:4000) "
            "or the provider's API endpoint."
        )

    # Construct model name with prefix if specified
    model_name = f"{config.litellm_model_prefix}{model}"

    # Create HTTP client with timeout configuration
    import httpx

    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(300.0, connect=10.0),  # 5 min total, 10 sec connect
    )

    provider = OpenAIProvider(
        base_url=config.litellm_api_base,
        api_key=config.litellm_api_key or "dummy",  # Some proxies don't require keys
        http_client=http_client,
    )

    return OpenAIChatModel(model_name, provider=provider)


def _create_azure_model(model: str) -> OpenAIChatModel:
    """Create Azure AI Foundry model.

    Azure OpenAI Service provides OpenAI models through Azure's infrastructure
    with additional enterprise features and compliance.

    Returns:
        OpenAIChatModel: Azure OpenAI model instance.

    Raises:
        ProviderConfigurationError: If required Azure configuration is missing.
    """
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider
    import httpx

    if not config.azure_endpoint:
        raise ProviderConfigurationError(
            "AGENTIC_AZURE_ENDPOINT is required for Azure provider. "
            "Example: https://myresource.openai.azure.com"
        )
    if not config.azure_api_key:
        raise ProviderConfigurationError(
            "AGENTIC_AZURE_API_KEY is required for Azure provider. "
            "Provide your Azure OpenAI API key."
        )

    # Use deployment name if specified, otherwise use model name
    deployment = config.azure_deployment_name or model

    # Construct Azure OpenAI base URL
    # Azure uses: https://{resource}.openai.azure.com/openai/deployments/{deployment}/
    base_url = f"{config.azure_endpoint.rstrip('/')}/openai/deployments/{deployment}"

    # Create HTTP client with Azure-specific configuration
    # Azure uses api-version in query params and api-key in headers
    http_client = httpx.AsyncClient(
        params={"api-version": config.azure_api_version},
        headers={"api-key": config.azure_api_key},
    )

    provider = OpenAIProvider(
        base_url=base_url,
        api_key=config.azure_api_key,
        http_client=http_client,
    )
    return OpenAIChatModel(deployment, provider=provider)


def _create_huggingface_model():
    """Create HuggingFace model adapter.

    This is a placeholder for future HuggingFace integration.
    It would wrap the existing LanguageModel class as an adapter.

    Raises:
        NotImplementedError: HuggingFace provider is not yet implemented.
    """
    raise NotImplementedError(
        "HuggingFace provider is not yet implemented. "
        "Consider using OpenAI, Ollama, LiteLLM, or Azure providers instead."
    )
