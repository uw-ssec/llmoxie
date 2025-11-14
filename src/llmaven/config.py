"""Configuration for LLMaven Web Service.

This module provides API-specific configuration using Pydantic Settings.
"""

from __future__ import annotations

from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class WebServiceConfig(BaseSettings):
    """Configuration for the web service.

    Attributes:
        api_title: Title for the API
        api_description: Description for the API
        api_version: Version of the API
        cors_origins: List of allowed CORS origins
        cors_allow_credentials: Whether to allow credentials in CORS
        cors_allow_methods: Allowed HTTP methods for CORS
        cors_allow_headers: Allowed headers for CORS
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_prefix="API_",
    )

    api_title: str = "LLMaven API"
    api_description: str = "REST API for LLMaven Documents Engine"
    api_version: str = "0.1.0"

    # CORS configuration
    cors_origins: List[str] = [
        "*" # Allow everything
    ]
    cors_allow_credentials: bool = True
    cors_allow_methods: List[str] = ["*"]
    cors_allow_headers: List[str] = ["*"]


# Global configuration instance
config = WebServiceConfig()
