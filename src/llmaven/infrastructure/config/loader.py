"""Configuration loader for LLMaven deployment.

This module handles loading and parsing llmaven-config.yaml files.
"""

from pathlib import Path
from typing import Any, Union

import yaml
from pydantic import ValidationError
from ruamel.yaml import YAML

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


def _coerce_yaml_value(value: Any) -> Any:
    """Coerce an update value into the type written back to YAML.

    The string ``"null"`` and ``None`` both map to a YAML ``null``. Booleans are
    written as native YAML booleans (``true``/``false``). Everything else is
    written as-is; ruamel.yaml adds quoting only when required.
    """
    if value is None or value == "null":
        return None
    return value


def update_config_fields(
    config_path: Union[str, Path], updates: dict[str, str]
) -> None:
    """Update specific fields in YAML config while preserving formatting.

    Uses a ruamel.yaml round-trip (load-modify-dump) so all comments, blank
    lines, key ordering, and inline annotations are preserved. Field paths are
    dotted and may be nested to any depth (e.g. ``azure.resource_group`` or
    ``a.b.c``). Only existing fields are updated; unknown paths raise an error
    rather than creating new keys, so user settings are never silently added to.

    Args:
        config_path: Path to llmaven-config.yaml file
        updates: Dictionary mapping dotted field paths to new values
                 (e.g., {'azure.resource_group': 'rg-name'})

    Raises:
        ConfigLoadError: If the file is missing, any field path does not exist,
            or file operations fail.

    Example:
        update_config_fields('/path/to/llmaven-config.yaml', {
            'azure.resource_group': 'rg-llmaven-westus',
            'project.pulumi_state_store': 'pulumistate'
        })
    """
    config_path = Path(config_path)
    if not config_path.exists():
        raise ConfigLoadError(f"Configuration file not found: {config_path}")

    yaml_rt = YAML()
    yaml_rt.preserve_quotes = True
    # Prevent ruamel from re-wrapping long scalars/comments onto new lines.
    yaml_rt.width = 4096
    # Render None as the explicit literal `null` (matching the template style)
    # instead of an empty scalar, so existing `null` lines round-trip unchanged.
    yaml_rt.representer.add_representer(
        type(None),
        lambda representer, _: representer.represent_scalar(
            "tag:yaml.org,2002:null", "null"
        ),
    )

    try:
        with open(config_path, "r") as f:
            data = yaml_rt.load(f)
    except Exception as e:
        raise ConfigLoadError(f"Failed to read configuration file {config_path}: {e}")

    if data is None:
        raise ConfigLoadError(
            f"Configuration file is empty: {config_path}\n"
            f"Cannot update fields in an empty configuration."
        )

    not_found = []
    for path, new_value in updates.items():
        keys = path.split(".")
        node = data
        # Walk to the parent mapping of the leaf key.
        for key in keys[:-1]:
            if not isinstance(node, dict) or key not in node:
                node = None
                break
            node = node[key]

        leaf = keys[-1]
        if not isinstance(node, dict) or leaf not in node:
            not_found.append(path)
            continue

        node[leaf] = _coerce_yaml_value(new_value)

    if not_found:
        raise ConfigLoadError(
            f"Configuration fields not found: {', '.join(sorted(not_found))}"
        )

    try:
        with open(config_path, "w") as f:
            yaml_rt.dump(data, f)
    except Exception as e:
        raise ConfigLoadError(f"Failed to write configuration file {config_path}: {e}")
