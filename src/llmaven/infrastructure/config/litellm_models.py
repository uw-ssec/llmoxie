"""Consistency checks between LiteLLM's model_list and Foundry deployments."""

from pathlib import Path

import yaml

from .schema import LLMavenConfig


def resolve_litellm_config_file(config: LLMavenConfig, config_path: Path) -> Path:
    """Resolve litellm.config_file relative to the infra config file, like main.py."""
    path = Path(config.litellm.config_file)
    if not path.is_absolute():
        path = (Path(config_path).parent / path).resolve()
    return path


def missing_foundry_deployments(config: LLMavenConfig, config_path: Path) -> list[str]:
    """List problems where LiteLLM's model_list points at an undeployed Foundry model.

    Every ``azure/<deployment>`` model in the LiteLLM config must name one of
    ``foundry.deployments``. Returns an empty list when Foundry or LiteLLM is
    disabled.

    Args:
        config: LLMaven configuration
        config_path: Path of the infra YAML (litellm.config_file is relative to it)

    Returns:
        Human-readable error messages, one per problem
    """
    if not (config.foundry.enabled and config.litellm and config.litellm.enabled):
        return []

    litellm_path = resolve_litellm_config_file(config, config_path)
    try:
        litellm_config = yaml.safe_load(litellm_path.read_text())
    except (OSError, yaml.YAMLError) as e:
        return [f"Cannot read LiteLLM config {litellm_path}: {e}"]

    if litellm_config is None:  # Empty file
        litellm_config = {}
    if not isinstance(litellm_config, dict):
        return [
            f"{litellm_path}: top level must be a mapping, "
            f"got {type(litellm_config).__name__}"
        ]
    # A missing or null model_list is valid: models can live in LiteLLM's database.
    model_list = litellm_config.get("model_list")
    if model_list is None:
        model_list = []
    if not isinstance(model_list, list):
        return [
            f"{litellm_path}: model_list must be a list, "
            f"got {type(model_list).__name__}"
        ]

    deployed = {d.name for d in config.foundry.deployments}
    errors = []
    for index, entry in enumerate(model_list):
        where = f"{litellm_path}: model_list[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{where} must be a mapping, got {type(entry).__name__}")
            continue
        params = entry.get("litellm_params")
        if not isinstance(params, dict):
            errors.append(
                f"{where}.litellm_params must be a mapping, got {type(params).__name__}"
            )
            continue
        model = params.get("model")
        if not isinstance(model, str) or not model.startswith("azure/"):
            continue
        deployment = model.split("/", 1)[1]
        if deployment not in deployed:
            errors.append(
                f"LiteLLM model '{entry.get('model_name')}' uses {model}, but "
                f"foundry.deployments has no deployment named '{deployment}' "
                f"(deployed: {sorted(deployed)})"
            )
    return errors


def missing_spend_logger(config: LLMavenConfig, config_path: Path) -> list[str]:
    """Warnings when llm_spend is enabled but the LiteLLM config lacks the callback.

    The ``llm_spend`` alert reads the ``LLMOXIE_SPEND`` line written by the
    ``spend_logger`` callback, so without it the alert never sees any data.
    Returns an empty list unless ``llm_spend`` is enabled and LiteLLM is enabled.

    Args:
        config: LLMaven configuration
        config_path: Path of the infra YAML (litellm.config_file is relative to it)

    Returns:
        Human-readable warning messages, one per problem
    """
    if not (
        "llm_spend" in config.monitoring.alerts.enabled_alerts
        and config.litellm
        and config.litellm.enabled
    ):
        return []

    litellm_path = resolve_litellm_config_file(config, config_path)
    try:
        litellm_config = yaml.safe_load(litellm_path.read_text())
    except (OSError, yaml.YAMLError) as e:
        return [f"Cannot read LiteLLM config {litellm_path}: {e}"]

    if litellm_config is None:  # Empty file
        litellm_config = {}
    if not isinstance(litellm_config, dict):
        return [
            f"{litellm_path}: top level must be a mapping, "
            f"got {type(litellm_config).__name__}"
        ]

    settings = litellm_config.get("litellm_settings")
    callbacks = settings.get("callbacks") if isinstance(settings, dict) else None
    if callbacks is None:
        callbacks = []
    elif not isinstance(callbacks, list):
        callbacks = [callbacks]
    if not any(
        isinstance(entry, str) and entry.startswith("spend_logger.")
        for entry in callbacks
    ):
        return [
            f"{litellm_path}: litellm_settings.callbacks has no spend_logger "
            "entry; the llm_spend alert will see no data"
        ]
    return []


def missing_salt_key(config: LLMavenConfig, config_path: Path) -> list[str]:
    """Warn when LiteLLM stores models in its database without its own salt key.

    LiteLLM encrypts the credentials it stores with ``LITELLM_SALT_KEY`` and
    falls back to the master key when that is unset, so rotating the master key
    would leave stored credentials unreadable. Returns an empty list unless
    LiteLLM is enabled with ``general_settings.store_model_in_db: true`` and
    ``LITELLM_SALT_KEY`` is set neither in ``litellm.env_vars`` nor in
    ``litellm.key_vault_secret_refs``.

    Args:
        config: LLMaven configuration
        config_path: Path of the infra YAML (litellm.config_file is relative to it)

    Returns:
        Human-readable warning messages, one per problem
    """
    if not (config.litellm and config.litellm.enabled):
        return []
    if "LITELLM_SALT_KEY" in config.litellm.env_vars or (
        "LITELLM_SALT_KEY" in (config.litellm.key_vault_secret_refs or {})
    ):
        return []

    litellm_path = resolve_litellm_config_file(config, config_path)
    try:
        litellm_config = yaml.safe_load(litellm_path.read_text())
    except (OSError, yaml.YAMLError) as e:
        return [f"Cannot read LiteLLM config {litellm_path}: {e}"]

    settings = (
        litellm_config.get("general_settings")
        if isinstance(litellm_config, dict)
        else None
    )
    if not (isinstance(settings, dict) and settings.get("store_model_in_db") is True):
        return []
    return [
        f"{litellm_path} sets general_settings.store_model_in_db but LITELLM_SALT_KEY "
        "is not set, so LiteLLM encrypts stored credentials with the master key and "
        "rotating the master key makes them unreadable. Set LITELLM_SALT_KEY (a Key "
        "Vault secret ref in litellm.key_vault_secret_refs) to the current master "
        "key's value, deploy, and never change it"
    ]
