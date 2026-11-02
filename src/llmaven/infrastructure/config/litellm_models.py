"""Consistency checks between LiteLLM's model_list and Foundry deployments."""

from pathlib import Path
from typing import List

import yaml

from .schema import LLMavenConfig


def resolve_litellm_config_file(config: LLMavenConfig, config_path: Path) -> Path:
    """Resolve litellm.config_file relative to the infra config file, like main.py."""
    path = Path(config.litellm.config_file)
    if not path.is_absolute():
        path = (Path(config_path).parent / path).resolve()
    return path


def missing_foundry_deployments(config: LLMavenConfig, config_path: Path) -> List[str]:
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
        litellm_config = yaml.safe_load(litellm_path.read_text()) or {}
    except (OSError, yaml.YAMLError) as e:
        return [f"Cannot read LiteLLM config {litellm_path}: {e}"]

    model_list = (
        litellm_config.get("model_list") if isinstance(litellm_config, dict) else None
    ) or []
    deployed = {d.name for d in config.foundry.deployments}
    errors = []
    for entry in model_list:
        params = (entry or {}).get("litellm_params") or {}
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
