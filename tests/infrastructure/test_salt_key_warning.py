"""Tests for missing_salt_key: stored credentials must not depend on the master key."""

from __future__ import annotations

from pathlib import Path

import pytest

from llmaven.infrastructure.config.litellm_models import missing_salt_key
from llmaven.infrastructure.config.schema import LiteLLMConfig, LLMavenConfig

REPO_CONFIG = Path(__file__).resolve().parents[2] / "docker" / "config.yaml"


def _config(litellm_config: Path, **litellm) -> LLMavenConfig:
    return LLMavenConfig(
        litellm=LiteLLMConfig(config_file=str(litellm_config), **litellm)
    )


def _litellm_file(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(content)
    return path


def test_repo_config_without_salt_key_is_reported(tmp_path):
    # docker/config.yaml stores models in the database, so a stack that
    # deploys it without a salt key ties stored credentials to the master key.
    messages = missing_salt_key(_config(REPO_CONFIG), tmp_path / "x.yaml")
    assert len(messages) == 1
    assert "LITELLM_SALT_KEY" in messages[0]
    assert str(REPO_CONFIG) in messages[0]


@pytest.mark.parametrize(
    "litellm",
    [
        {"key_vault_secret_refs": {"LITELLM_SALT_KEY": "litellm-salt-key"}},
        {"env_vars": {"LITELLM_SALT_KEY": "plain"}},
        {"enabled": False},
    ],
    ids=["secret-ref", "env-var", "litellm-disabled"],
)
def test_salt_key_set_or_litellm_off_is_clean(tmp_path, litellm):
    assert missing_salt_key(_config(REPO_CONFIG, **litellm), tmp_path / "x.yaml") == []


@pytest.mark.parametrize(
    "content",
    [
        "general_settings:\n  store_model_in_db: false\n",
        "general_settings:\n  master_key: os.environ/LITELLM_MASTER_KEY\n",
        "model_list: []\n",
        "",
    ],
    ids=["store-false", "store-unset", "no-general-settings", "empty-file"],
)
def test_models_not_stored_in_db_is_clean(tmp_path, content):
    path = _litellm_file(tmp_path, content)
    assert missing_salt_key(_config(path), tmp_path / "x.yaml") == []


def test_unreadable_litellm_config_is_reported(tmp_path):
    path = tmp_path / "missing.yaml"
    messages = missing_salt_key(_config(path), tmp_path / "x.yaml")
    assert len(messages) == 1
    assert messages[0].startswith(f"Cannot read LiteLLM config {path}")
