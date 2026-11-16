"""Tests for apply_sso_only_login: no LiteLLM password login behind the Keycloak login."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import yaml

from llmaven.infrastructure.resources import helpers
from llmaven.infrastructure.resources.helpers import (
    SSO_ONLY_LOGIN_SETTING,
    apply_sso_only_login,
)

LITELLM_CONFIG = Path(__file__).resolve().parents[2] / "docker" / "config.yaml"


def test_setting_is_added_to_repo_litellm_config():
    rendered = yaml.safe_load(apply_sso_only_login(LITELLM_CONFIG.read_text()))
    original = yaml.safe_load(LITELLM_CONFIG.read_text())
    assert rendered["general_settings"][SSO_ONLY_LOGIN_SETTING] is True
    # Nothing else in general_settings changes.
    del rendered["general_settings"][SSO_ONLY_LOGIN_SETTING]
    assert rendered == original


def test_operator_value_is_kept_and_comments_preserved():
    text = (
        "# keep me\n"
        "general_settings:\n"
        "  master_key: os.environ/LITELLM_MASTER_KEY  # inline\n"
        f"  {SSO_ONLY_LOGIN_SETTING}: false\n"
    )
    out = apply_sso_only_login(text)
    assert "# keep me" in out and "# inline" in out
    assert yaml.safe_load(out)["general_settings"][SSO_ONLY_LOGIN_SETTING] is False


@pytest.mark.parametrize("text", ["", "model_list: []\n"])
def test_general_settings_is_created_when_missing(text):
    data = yaml.safe_load(apply_sso_only_login(text))
    assert data["general_settings"] == {SSO_ONLY_LOGIN_SETTING: True}


@pytest.mark.parametrize("text", ["- a\n- b\n", "general_settings: [1]\n"])
def test_malformed_litellm_config_is_rejected(text):
    with pytest.raises(ValueError, match="mapping"):
        apply_sso_only_login(text)


def _mounted_litellm_config(sso_only_login: bool) -> str:
    with patch.object(
        helpers, "create_container_app_with_key_vault_secrets", return_value=Mock()
    ) as create_app:
        helpers.create_litellm_app(
            name="llmaven-dev-litellm",
            resource_group_name="rg",
            location="westus2",
            container_env_id="env-id",
            container_env_name="env",
            image="example.test/litellm:1",
            port=4000,
            cpu=1,
            memory="2Gi",
            min_replicas=1,
            max_replicas=2,
            env_vars={},
            key_vault=SimpleNamespace(properties=SimpleNamespace(vault_uri="kv")),
            key_vault_secret_refs={},
            config_file=str(LITELLM_CONFIG),
            sso_only_login=sso_only_login,
        )
    return create_app.call_args.kwargs["inline_secrets"]["config-yaml"]


def test_mounted_config_is_verbatim_without_the_login():
    # Stacks without the Keycloak login keep the same secret, so no new revision.
    assert _mounted_litellm_config(sso_only_login=False) == LITELLM_CONFIG.read_text()


def test_mounted_config_turns_off_password_login_with_the_login():
    data = yaml.safe_load(_mounted_litellm_config(sso_only_login=True))
    assert data["general_settings"][SSO_ONLY_LOGIN_SETTING] is True
