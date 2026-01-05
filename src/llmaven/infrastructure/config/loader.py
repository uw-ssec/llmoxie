"""Configuration loader for LLMaven deployment.

This module handles loading and parsing llmaven-config.yaml files.
"""

from pathlib import Path
from typing import Union

import yaml
from pydantic import ValidationError

from .schema import LLMavenConfig


class ConfigLoadError(Exception):
    """Exception raised when configuration loading fails."""

    pass


def load_config(config_path: Union[str, Path]) -> LLMavenConfig:
    """Load and validate configuration from YAML file.

    Args:
        config_path: Path to llmaven-config.yaml file

    Returns:
        Validated LLMavenConfig object

    Raises:
        ConfigLoadError: If file doesn't exist, is invalid YAML, or fails validation
    """
    config_path = Path(config_path)

    # Check if file exists
    if not config_path.exists():
        raise ConfigLoadError(
            f"Configuration file not found: {config_path}\n"
            f"Run 'llmaven init' to generate a default configuration."
        )

    # Read YAML file
    try:
        with open(config_path, "r") as f:
            config_dict = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigLoadError(f"Invalid YAML syntax in {config_path}: {e}")
    except Exception as e:
        raise ConfigLoadError(f"Failed to read configuration file {config_path}: {e}")

    # Validate with Pydantic
    try:
        config = LLMavenConfig(**config_dict)
    except ValidationError as e:
        error_messages = []
        for error in e.errors():
            field = " -> ".join(str(loc) for loc in error["loc"])
            message = error["msg"]
            error_messages.append(f"  {field}: {message}")

        raise ConfigLoadError(
            "Configuration validation failed:\n" + "\n".join(error_messages)
        )

    return config


def load_config_dict(config_path: Union[str, Path]) -> dict:
    """Load configuration as dictionary without validation.

    Args:
        config_path: Path to llmaven-config.yaml file

    Returns:
        Configuration dictionary

    Raises:
        ConfigLoadError: If file doesn't exist or is invalid YAML
    """
    config_path = Path(config_path)

    if not config_path.exists():
        raise ConfigLoadError(f"Configuration file not found: {config_path}")

    try:
        with open(config_path, "r") as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigLoadError(f"Invalid YAML syntax in {config_path}: {e}")
    except Exception as e:
        raise ConfigLoadError(f"Failed to read configuration file {config_path}: {e}")


def save_config(config: LLMavenConfig, output_path: Union[str, Path]) -> None:
    """Save configuration to YAML file.

    Args:
        config: LLMavenConfig object to save
        output_path: Path where to save the configuration

    Raises:
        ConfigLoadError: If file cannot be written
    """
    output_path = Path(output_path)

    try:
        # Convert Pydantic model to dict, excluding None values
        config_dict = config.model_dump(exclude_none=True, mode="python")

        # Write to YAML file
        with open(output_path, "w") as f:
            yaml.dump(
                config_dict,
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
                width=88,
            )
    except Exception as e:
        raise ConfigLoadError(f"Failed to write configuration to {output_path}: {e}")
