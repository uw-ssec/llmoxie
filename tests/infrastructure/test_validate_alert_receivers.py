"""`validate` warns when alerts would go to a placeholder address.

The generated staging/prod configs ship `ops@example.org`. Deploying with it
left in place "succeeds" while nobody ever receives an alert.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from llmaven.deployment import validate as validate_mod
from llmaven.deployment.validate import ValidationError, validate_config

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_config(
    tmp_path: Path,
    receivers: list[str],
    enabled: list[str],
    litellm_config: Path | None = None,
) -> Path:
    config = {
        "project": {"name": "llmaven", "environment": "dev", "location": "eastus"},
        "azure": {
            "subscription_id": "00000000-0000-0000-0000-000000000000",
            "tenant_id": "00000000-0000-0000-0000-000000000000",
            "resource_group": "rg-test",
        },
        "monitoring": {
            "enable_log_analytics": True,
            "alerts": {"email_receivers": receivers, "enabled_alerts": enabled},
        },
        "litellm": {
            "config_file": str(litellm_config or REPO_ROOT / "docker" / "config.yaml")
        },
    }
    path = tmp_path / "llmaven-config.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path


def _run(config_path: Path, strict: bool = False) -> None:
    """Run validate_config with every Azure/secret probe stubbed out."""
    with (
        patch.object(validate_mod, "check_azure_cli", return_value=(True, "ok")),
        patch.object(
            validate_mod, "check_subscription_access", return_value=(True, "ok")
        ),
        patch.object(
            validate_mod, "check_required_providers", return_value=(True, "ok")
        ),
        patch.object(validate_mod, "check_secrets", return_value=(True, [])),
        patch.object(
            validate_mod,
            "check_config_for_hardcoded_secrets",
            return_value=(True, []),
        ),
    ):
        validate_config(config_path, strict=strict)


@pytest.mark.parametrize("domain", ["example.org", "example.com", "example.net"])
def test_placeholder_receiver_warns(tmp_path, capsys, domain):
    path = _write_config(tmp_path, [f"ops@{domain}"], ["db_cpu"])

    _run(path)

    out = capsys.readouterr().out
    assert "Validation Passed with Warnings" in out
    assert f"ops@{domain}" in out


def test_placeholder_receiver_fails_in_strict_mode(tmp_path, capsys):
    path = _write_config(tmp_path, ["ops@example.org"], ["db_cpu"])

    with pytest.raises(ValidationError):
        _run(path, strict=True)

    assert "ops@example.org" in capsys.readouterr().out


def test_real_receiver_does_not_warn(tmp_path, capsys):
    path = _write_config(tmp_path, ["ops@llmoxie.test"], ["db_cpu"])

    _run(path)

    assert "Validation Passed with Warnings" not in capsys.readouterr().out


def test_llm_spend_without_spend_logger_warns(tmp_path, capsys):
    litellm_config = tmp_path / "litellm.yaml"
    litellm_config.write_text(
        "litellm_settings:\n  callbacks: adl_logger.proxy_handler_instance\n"
    )
    path = _write_config(
        tmp_path, ["ops@llmoxie.test"], ["llm_spend"], litellm_config=litellm_config
    )

    _run(path)

    out = capsys.readouterr().out
    assert "Validation Passed with Warnings" in out
    assert "has no spend_logger entry" in out


def test_llm_spend_without_spend_logger_fails_in_strict_mode(tmp_path, capsys):
    litellm_config = tmp_path / "litellm.yaml"
    litellm_config.write_text("general_settings: {}\n")
    path = _write_config(
        tmp_path, ["ops@llmoxie.test"], ["llm_spend"], litellm_config=litellm_config
    )

    with pytest.raises(ValidationError):
        _run(path, strict=True)


def test_llm_spend_with_repo_config_does_not_warn(tmp_path, capsys):
    path = _write_config(tmp_path, ["ops@llmoxie.test"], ["llm_spend"])

    _run(path)

    out = capsys.readouterr().out
    assert "spend_logger" not in out
    assert "Validation Passed with Warnings" not in out


def test_placeholder_receiver_ignored_when_no_alerts_enabled(tmp_path, capsys):
    path = _write_config(tmp_path, ["ops@example.org"], [])

    _run(path)

    out = capsys.readouterr().out
    assert "Validation Passed with Warnings" not in out
    assert "ops@example.org" not in out
