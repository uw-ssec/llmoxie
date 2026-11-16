"""The console config block: validation, names, retained database, providers."""

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from pydantic import ValidationError as PydanticValidationError

from llmaven.deployment import validate as validate_mod
from llmaven.deployment.validate import ValidationError, validate_config
from llmaven.infrastructure.config.schema import (
    CONSOLE_DB,
    LLMavenConfig,
    console_job_name,
    console_vault_name,
    container_app_name,
    CONSOLE_BROKER_APP_SUFFIX,
    CONSOLE_WEB_APP_SUFFIX,
)
from llmaven.infrastructure.resources.database import RETAINED_DATABASES

from . import PINNED_CONSOLE_IMAGE
from .test_litellm_admin_host import ADMIN, KEYCLOAK_HOST
from .test_edge_config import _data, LITELLM_HOST, MLFLOW_HOST
from .test_edge_login_routing import KEYCLOAK_ADMIN
from . import PINNED_KEYCLOAK_IMAGE

CONSOLE_HOST = "console.example.org"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _console_data(**console) -> dict:
    data = _data(litellm={"admin_allowed_ips": ["203.0.113.0/24"]})
    data["edge"]["custom_domains"] += [
        {"name": KEYCLOAK_HOST, "certificate_name": "cert-kc"},
        {"name": ADMIN, "certificate_name": "cert-admin"},
        {"name": CONSOLE_HOST, "certificate_name": "cert-console"},
    ]
    data["keycloak"] = {
        "enabled": True,
        "image": PINNED_KEYCLOAK_IMAGE,
        "hostname": KEYCLOAK_HOST,
        "admin_allowed_ips": [KEYCLOAK_ADMIN],
    }
    data["litellm"]["login"] = {"enabled": True}
    data["litellm"]["admin_hostname"] = ADMIN
    data["console"] = {
        "enabled": True,
        "hostname": CONSOLE_HOST,
        "image": PINNED_CONSOLE_IMAGE,
        "admin_subjects": ["00000000-0000-0000-0000-000000000001"],
        "mail": {"domain": "mail.example.org"},
        **console,
    }
    return data


def _config(**console) -> LLMavenConfig:
    return LLMavenConfig.model_validate(_console_data(**console))


def test_console_off_by_default_and_renders_nothing():
    config = LLMavenConfig()
    assert config.console.enabled is False
    assert CONSOLE_DB not in config.database.databases


def test_valid_console_config_is_accepted():
    config = _config()
    assert config.console.web.max_replicas == 2
    assert config.console.broker.cpu == 0.5
    assert config.console.broker.memory == "1Gi"
    assert config.console.mail.sender == "console"


def _without_edge(d):
    d["edge"]["enabled"] = False


def _without_keycloak(d):
    d["keycloak"]["enabled"] = False
    d["litellm"]["login"] = {"enabled": False}


def _without_login(d):
    d["litellm"]["login"] = {"enabled": False}


def _without_admin_hostname(d):
    del d["litellm"]["admin_hostname"]


def _without_hostname(d):
    del d["console"]["hostname"]


def _without_admin_subjects(d):
    d["console"]["admin_subjects"] = []


def _without_mail_domain(d):
    d["console"]["mail"] = {}


@pytest.mark.parametrize(
    ("missing", "mutate", "field"),
    [
        ("edge", _without_edge, "edge.enabled"),
        ("keycloak", _without_keycloak, "keycloak.enabled"),
        ("litellm_login", _without_login, "litellm.login.enabled"),
        ("admin_hostname", _without_admin_hostname, "litellm.admin_hostname"),
        ("hostname", _without_hostname, "console.hostname"),
        ("admin_subjects", _without_admin_subjects, "console.admin_subjects"),
        ("mail_domain", _without_mail_domain, "console.mail.domain"),
    ],
)
def test_console_requires(missing, mutate, field):
    data = _console_data()
    mutate(data)
    with pytest.raises(ValueError, match=field.replace(".", r"\.")):
        LLMavenConfig.model_validate(data)


def test_console_needs_litellm_enabled():
    data = _console_data()
    data["litellm"]["enabled"] = False
    with pytest.raises(ValueError, match="litellm"):
        LLMavenConfig.model_validate(data)


@pytest.mark.parametrize(
    "image",
    [
        "ghcr.io/uw-ssec/llmoxie-console:latest",
        "ghcr.io/uw-ssec/llmoxie-console:dev",
    ],
)
def test_console_image_must_be_pinned(image):
    with pytest.raises(ValueError, match=r"console\.image"):
        _config(image=image)


def test_unpinned_image_is_fine_while_console_is_off():
    data = _console_data(image="x:latest")
    data["console"]["enabled"] = False
    LLMavenConfig.model_validate(data)


def test_console_hostname_must_be_a_custom_domain():
    with pytest.raises(ValueError, match=r"console\.hostname.*edge\.custom_domains"):
        _config(hostname="elsewhere.example.org")


@pytest.mark.parametrize(
    "other",
    [LITELLM_HOST, MLFLOW_HOST, KEYCLOAK_HOST, ADMIN],
    ids=["litellm", "mlflow", "keycloak", "litellm-admin"],
)
def test_console_hostname_must_be_unique(other):
    with pytest.raises(ValueError, match="must differ"):
        _config(hostname=other)


def _validate(tmp_path, litellm_file, litellm_extra=None):
    data = _console_data()
    data["azure"] = {
        "subscription_id": "00000000-0000-0000-0000-000000000000",
        "tenant_id": "00000000-0000-0000-0000-000000000000",
        "resource_group": "rg-test",
    }
    data["monitoring"] = {"alerts": {"email_receivers": ["ops@llmoxie.test"]}}
    data["litellm"]["config_file"] = str(litellm_file)
    data["litellm"].update(litellm_extra or {})
    path = tmp_path / "llmaven-config.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
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
        validate_config(path, strict=False)


def test_console_requires_salt_key_and_db_models(tmp_path):
    stored = tmp_path / "stored.yaml"
    stored.write_text("general_settings:\n  store_model_in_db: true\n")
    unstored = tmp_path / "unstored.yaml"
    unstored.write_text("general_settings:\n  store_model_in_db: false\n")
    salt = {"key_vault_secret_refs": {"LITELLM_SALT_KEY": "litellm-salt-key"}}

    with pytest.raises(ValidationError):
        _validate(tmp_path, stored)  # no salt key
    with pytest.raises(ValidationError):
        _validate(tmp_path, unstored, salt)  # models not in the database
    _validate(tmp_path, stored, salt)


def test_console_requires_communication_provider(monkeypatch):
    seen = []

    class Result:
        returncode = 0
        stdout = "Registered\n"
        stderr = ""

    def fake_run(cmd, **_kwargs):
        seen.append(cmd[cmd.index("--namespace") + 1])
        return Result()

    monkeypatch.setattr(validate_mod.subprocess, "run", fake_run)
    validate_mod.check_required_providers("sub")
    assert "Microsoft.Communication" not in seen
    seen.clear()
    validate_mod.check_required_providers("sub", console_enabled=True)
    assert "Microsoft.Communication" in seen


def test_console_adds_console_db():
    assert "console_db" in _config().database.databases


def test_console_names_fit():
    data = _console_data()
    data["project"] = {"name": "llmaven-dev", "environment": "dev"}
    LLMavenConfig.model_validate(data)
    project, env = "llmaven-dev", "dev"
    names = [
        container_app_name(project, env, CONSOLE_WEB_APP_SUFFIX),
        container_app_name(project, env, CONSOLE_BROKER_APP_SUFFIX),
        console_job_name(project, env, "db"),
        console_job_name(project, env, "init"),
    ]
    assert all(len(n) <= 32 for n in names), names
    vaults = {console_vault_name(project, env, w) for w in ("web", "broker")}
    assert len(vaults) == 2
    assert all(len(v) <= 24 for v in vaults)


def test_console_names_too_long_are_refused():
    data = _console_data()
    data["project"] = {"name": "a-very-long-project-name", "environment": "dev"}
    with pytest.raises(ValueError, match="Shorten project.name"):
        LLMavenConfig.model_validate(data)


def test_console_vault_name_too_long_is_refused_not_truncated():
    # kv-<p>-dev-cw is 10 + len(p) chars, over 24 from 15 characters up.
    data = _console_data()
    data["project"] = {"name": "p" * 15, "environment": "dev"}
    with pytest.raises(ValueError, match="Key Vault"):
        LLMavenConfig.model_validate(data)


def test_console_db_is_retained():
    assert "console_db" in RETAINED_DATABASES
    assert "keycloak_db" in RETAINED_DATABASES
