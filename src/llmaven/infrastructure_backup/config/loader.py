"""Configuration loading utilities for LLMaven backup infrastructure."""

from pathlib import Path

import yaml
from pydantic import ValidationError

from .schema import LLMavenBackupConfig


class BackupConfigLoadError(Exception):
    """Raised when backup configuration cannot be loaded or validated."""

    pass


def load_backup_config(config_path: Path) -> LLMavenBackupConfig:
    """Load and validate the backup configuration from a YAML file.

    Args:
        config_path: Path to the llmaven-backup-config.yaml file

    Returns:
        Validated LLMavenBackupConfig

    Raises:
        BackupConfigLoadError: If the file is missing, unreadable, or fails validation
    """
    if not config_path.exists():
        raise BackupConfigLoadError(
            f"Backup config file not found: {config_path}\n"
            "Run 'llmaven infra backup init' to create one."
        )

    try:
        raw = yaml.safe_load(config_path.read_text())
    except yaml.YAMLError as e:
        raise BackupConfigLoadError(f"Invalid YAML in {config_path}: {e}")

    if not isinstance(raw, dict):
        raise BackupConfigLoadError(
            f"Backup config file is empty or invalid: {config_path}"
        )

    try:
        return LLMavenBackupConfig(**raw)
    except ValidationError as e:
        raise BackupConfigLoadError(
            f"Backup configuration validation failed in {config_path}:\n{e}"
        )


def save_backup_config(config: LLMavenBackupConfig, output_path: Path) -> None:
    """Serialize backup configuration to a YAML file.

    Args:
        config: Validated LLMavenBackupConfig
        output_path: Destination file path
    """
    output_path.write_text(
        yaml.dump(config.model_dump(), default_flow_style=False, sort_keys=False)
    )


def update_backup_config_fields(config_path: Path, updates: dict) -> None:
    """Update specific fields in a backup config YAML file in-place.

    Uses dot-notation keys (e.g. "azure.resource_group").
    Preserves all other fields and structure.

    Args:
        config_path: Path to the backup config YAML file
        updates: Dict of dot-notation keys to new values
    """
    raw = yaml.safe_load(config_path.read_text()) or {}

    for key_path, value in updates.items():
        parts = key_path.split(".")
        node = raw
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    config_path.write_text(yaml.dump(raw, default_flow_style=False, sort_keys=False))
