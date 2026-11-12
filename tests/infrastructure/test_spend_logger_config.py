"""Tests for missing_spend_logger: llm_spend needs the spend_logger callback."""

from __future__ import annotations

from pathlib import Path

import pytest

from llmaven.infrastructure.config.litellm_models import missing_spend_logger
from llmaven.infrastructure.config.schema import (
    AlertsConfig,
    LiteLLMConfig,
    LLMavenConfig,
    MonitoringConfig,
)

REPO_CONFIG = Path(__file__).resolve().parents[2] / "docker" / "config.yaml"


def _config(
    litellm_config: Path,
    enabled_alerts: list[str] | None = None,
    litellm_enabled: bool = True,
) -> LLMavenConfig:
    if enabled_alerts is None:
        enabled_alerts = ["llm_spend"]
    return LLMavenConfig(
        litellm=LiteLLMConfig(enabled=litellm_enabled, config_file=str(litellm_config)),
        monitoring=MonitoringConfig(
            alerts=AlertsConfig(
                email_receivers=["ops@llmoxie.test"], enabled_alerts=enabled_alerts
            )
        ),
    )


def _litellm_file(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(content)
    return path


def test_repo_config_registers_spend_logger(tmp_path):
    config = _config(REPO_CONFIG)
    assert missing_spend_logger(config, tmp_path / "llmaven-config.yaml") == []


def test_string_callbacks_without_spend_logger_is_reported(tmp_path):
    path = _litellm_file(
        tmp_path, "litellm_settings:\n  callbacks: adl_logger.proxy_handler_instance\n"
    )
    messages = missing_spend_logger(_config(path), tmp_path / "x.yaml")
    assert messages == [
        f"{path}: litellm_settings.callbacks has no spend_logger entry; "
        "the llm_spend alert will see no data"
    ]


def test_list_callbacks_with_spend_logger_is_clean(tmp_path):
    path = _litellm_file(
        tmp_path,
        "litellm_settings:\n  callbacks:\n"
        "    - adl_logger.proxy_handler_instance\n"
        "    - spend_logger.proxy_handler_instance\n",
    )
    assert missing_spend_logger(_config(path), tmp_path / "x.yaml") == []


def test_string_callbacks_with_spend_logger_is_clean(tmp_path):
    path = _litellm_file(
        tmp_path,
        "litellm_settings:\n  callbacks: spend_logger.proxy_handler_instance\n",
    )
    assert missing_spend_logger(_config(path), tmp_path / "x.yaml") == []


@pytest.mark.parametrize(
    "content", ["", "general_settings: {}\n", "litellm_settings:\n"]
)
def test_missing_litellm_settings_is_reported(tmp_path, content):
    path = _litellm_file(tmp_path, content)
    messages = missing_spend_logger(_config(path), tmp_path / "x.yaml")
    assert len(messages) == 1
    assert "has no spend_logger entry" in messages[0]


def test_not_checked_when_llm_spend_not_enabled(tmp_path):
    path = _litellm_file(tmp_path, "general_settings: {}\n")
    config = _config(path, enabled_alerts=["db_cpu"])
    assert missing_spend_logger(config, tmp_path / "x.yaml") == []


def test_not_checked_when_litellm_disabled(tmp_path):
    path = _litellm_file(tmp_path, "general_settings: {}\n")
    config = _config(path, litellm_enabled=False)
    assert missing_spend_logger(config, tmp_path / "x.yaml") == []


def test_unreadable_file_is_reported(tmp_path):
    path = tmp_path / "absent.yaml"
    messages = missing_spend_logger(_config(path), tmp_path / "x.yaml")
    assert len(messages) == 1
    assert "Cannot read LiteLLM config" in messages[0]


def test_non_mapping_top_level_is_reported(tmp_path):
    path = _litellm_file(tmp_path, "- spend_logger\n")
    messages = missing_spend_logger(_config(path), tmp_path / "x.yaml")
    assert len(messages) == 1
    assert "top level must be a mapping, got list" in messages[0]
