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


def update_config_fields(
    config_path: Union[str, Path], updates: dict[str, str]
) -> None:
    """Update specific fields in YAML config while preserving formatting.

    This function updates only the specified fields while preserving all comments,
    blank lines, and formatting in the YAML file.

    Args:
        config_path: Path to llmaven-config.yaml file
        updates: Dictionary mapping field paths to new values
                 (e.g., {'azure.resource_group': 'rg-name'})

    Raises:
        ConfigLoadError: If file operations fail

    Example:
        update_config_fields('/path/to/llmaven-config.yaml', {
            'azure.resource_group': 'rg-llmaven-westus',
            'project.pulumi_state_store': 'pulumistate'
        })
    """
    import re

    config_path = Path(config_path)
    if not config_path.exists():
        raise ConfigLoadError(f"Configuration file not found: {config_path}")

    try:
        with open(config_path, "r") as f:
            content = f.read()
    except Exception as e:
        raise ConfigLoadError(f"Failed to read configuration file {config_path}: {e}")

    lines = content.split("\n")
    result_lines = []
    applied_updates = set()
    current_section = None

    for line in lines:
        section_match = re.match(r"^([a-z_]+):\s*(?:#.*)?$", line)
        if section_match:
            current_section = section_match.group(1)
            result_lines.append(line)
            continue

        field_match = (
            re.match(r"^(\s+)([a-z_]+):\s*(.*)$", line) if current_section else None
        )
        if field_match:
            indent, field_name, rest = field_match.groups()
            full_path = f"{current_section}.{field_name}"

            if full_path in updates:
                new_value = updates[full_path]
                applied_updates.add(full_path)
                comment = (
                    comment_match.group(1)
                    if (comment_match := re.search(r"(\s+#.*)$", rest))
                    else ""
                )

                formatted_value = (
                    "null"
                    if new_value in [None, "null"]
                    else str(new_value).lower()
                    if isinstance(new_value, bool)
                    else f'"{new_value}"'
                    if isinstance(new_value, str)
                    and (" " in new_value or ":" in new_value)
                    else str(new_value)
                )
                result_lines.append(f"{indent}{field_name}: {formatted_value}{comment}")
                continue

        result_lines.append(line)

    unapplied_updates = set(updates.keys()) - applied_updates
    if unapplied_updates:
        raise ConfigLoadError(
            f"Configuration fields not found: {', '.join(sorted(unapplied_updates))}"
        )

    try:
        with open(config_path, "w") as f:
            f.write("\n".join(result_lines))
    except Exception as e:
        raise ConfigLoadError(f"Failed to write configuration file {config_path}: {e}")
