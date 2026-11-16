"""Keycloak and the MLflow / LiteLLM logins: config and validation."""

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from llmaven.deployment import validate as validate_mod
from llmaven.deployment.validate import validate_config
from llmaven.infrastructure.config.schema import (
    CONTAINER_APP_NAME_MAX,
    LLMavenConfig,
    is_reserved_realm_env,
    container_app_name,
    edge_app_name,
    realm_job_name,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

EXISTING_STACK = {
    "networking": {
        "vnet_address_space": "172.16.0.0/16",
        "container_apps_subnet": "172.16.0.0/23",
        "postgres_subnet": "172.16.2.0/24",
    },
}
PINNED_KEYCLOAK = "ghcr.io/uw-ssec/llmoxie-keycloak:26.5.5@sha256:" + "b" * 64
LITELLM_HOST = "ai.example.org"
MLFLOW_HOST = "mlflow.example.org"
AUTH_HOST = "auth.example.org"


def _domains(*names: str) -> list[dict]:
    return [{"name": n, "certificate_name": f"cert-{i}"} for i, n in enumerate(names)]


def _data(keycloak=None, litellm=None, mlflow=None, project=None) -> dict:
    data = {
        **EXISTING_STACK,
        "edge": {
            "enabled": True,
            "custom_domains": _domains(LITELLM_HOST, MLFLOW_HOST, AUTH_HOST),
            "trusted_proxy_ips": ["100.100.0.0/17"],
        },
        "litellm": {
            "cpu": 2,
            "memory": "4Gi",
            "hostname": LITELLM_HOST,
            **(litellm or {}),
        },
        "mlflow": {"hostname": MLFLOW_HOST, **(mlflow or {})},
        "keycloak": {
            "enabled": True,
            "image": PINNED_KEYCLOAK,
            "hostname": AUTH_HOST,
            **(keycloak or {}),
        },
    }
    if project:
        data["project"] = project
    return data


def _config(**kwargs) -> LLMavenConfig:
    return LLMavenConfig.model_validate(_data(**kwargs))


def test_keycloak_is_off_by_default():
    config = LLMavenConfig()
    assert config.keycloak.enabled is False
    assert config.mlflow.login.enabled is False
    assert config.litellm.login.enabled is False
    assert config.mlflow.login.role == "mlflow-user"
    assert config.litellm.login.role == "litellm-admin"


def test_valid_keycloak_config_passes():
    config = _config()
    assert config.keycloak.realm.name == "llmoxie"
    assert "@sha256:" in config.keycloak.config_cli_image
    assert "@sha256:" in config.keycloak.oauth2_proxy_image


def test_keycloak_needs_the_edge():
    data = _data()
    data["edge"] = {"enabled": False}
    with pytest.raises(ValueError, match=r"edge\.enabled"):
        LLMavenConfig.model_validate(data)


def test_keycloak_hostname_must_be_an_edge_domain_and_distinct():
    with pytest.raises(ValueError, match=r"keycloak\.hostname"):
        _config(keycloak={"hostname": None})
    with pytest.raises(ValueError, match=r"edge\.custom_domains"):
        _config(keycloak={"hostname": "other.example.org"})
    with pytest.raises(ValueError, match=r"keycloak\.hostname"):
        _config(keycloak={"hostname": LITELLM_HOST})
    with pytest.raises(ValueError, match=r"keycloak\.hostname"):
        _config(keycloak={"hostname": MLFLOW_HOST})


def test_login_needs_keycloak():
    for app in ("mlflow", "litellm"):
        data = _data(**{app: {"login": {"enabled": True}}})
        data["keycloak"]["enabled"] = False
        with pytest.raises(ValueError, match=rf"{app}\.login\.enabled"):
            LLMavenConfig.model_validate(data)


def test_keycloak_db_is_added_to_databases():
    config = _config()
    assert config.database.databases.count("keycloak_db") == 1
    data = _data()
    data["database"] = {"databases": ["llmaven", "keycloak_db"]}
    again = LLMavenConfig.model_validate(data)
    assert again.database.databases.count("keycloak_db") == 1


def test_databases_are_untouched_with_keycloak_off():
    data = _data()
    data["keycloak"]["enabled"] = False
    config = LLMavenConfig.model_validate(data)
    assert config.database.databases == ["llmaven", "mlflow_db", "litellm_db"]


@pytest.mark.parametrize("field", ["config_cli_image", "oauth2_proxy_image"])
def test_third_party_images_need_a_digest(field):
    with pytest.raises(ValueError, match="@sha256:"):
        _config(keycloak={field: "quay.io/example/image:v1"})


def test_overrides_cannot_redefine_stack_clients():
    with pytest.raises(ValueError, match="litellm"):
        _config(
            keycloak={"realm": {"overrides": {"clients": [{"clientId": "litellm"}]}}}
        )
    config = _config(
        keycloak={"realm": {"overrides": {"clients": [{"clientId": "jupyterhub"}]}}}
    )
    assert config.keycloak.enabled


@pytest.mark.parametrize("name", ["LLMoxie", "a"])
def test_bad_realm_names_are_rejected(name):
    with pytest.raises(ValueError):
        _config(keycloak={"realm": {"name": name}})


def test_realm_name_pattern_accepts_llmoxie():
    assert _config(keycloak={"realm": {"name": "llmoxie"}}).keycloak.realm.name == (
        "llmoxie"
    )


def test_long_project_name_is_rejected_per_resource():
    # 16 characters: the edge is exactly 32, the LiteLLM login app is 33.
    project = {"name": "a" * 16, "environment": "dev"}
    data = _data(litellm={"login": {"enabled": True}}, project=project)
    assert len(edge_app_name("a" * 16, "dev")) == CONTAINER_APP_NAME_MAX
    with pytest.raises(ValueError) as error:
        LLMavenConfig.model_validate(data)
    message = str(error.value)
    assert container_app_name("a" * 16, "dev", "llm-auth") in message
    assert "33" in message and "32" in message


def test_long_project_name_is_rejected_for_the_realm_job():
    name = "a" * 23
    assert len(realm_job_name(name, "dev")) == 33
    with pytest.raises(ValueError) as error:
        _config(project={"name": name, "environment": "dev"})
    message = str(error.value)
    assert realm_job_name(name, "dev") in message
    assert "32" in message


def test_keycloak_app_name_is_checked():
    # The edge fits (32) and the job fits; "<p>-dev-keycloak-dev" is 33.
    name = "a" * 16
    with pytest.raises(ValueError) as error:
        _config(project={"name": name, "environment": "dev"})
    message = str(error.value)
    assert container_app_name(name, "dev", "keycloak") in message
    assert realm_job_name(name, "dev") not in message


def test_logins_off_do_not_check_their_names():
    # The edge is exactly 32 characters, so only Keycloak's names would be over.
    data = _data(project={"name": "a" * 16, "environment": "dev"})
    data["keycloak"]["enabled"] = False
    LLMavenConfig.model_validate(data)


@pytest.mark.parametrize("project, env", [("llmaven-iss", "prod"), ("llmaven", "dev")])
def test_container_app_name_matches_edge_helper(project, env):
    assert container_app_name(project, env, "traefik") == edge_app_name(project, env)


def test_empty_keycloak_admin_ips_warns(tmp_path, capsys):
    data = _data()
    data["azure"] = {
        "subscription_id": "00000000-0000-0000-0000-000000000000",
        "tenant_id": "00000000-0000-0000-0000-000000000000",
        "resource_group": "rg-test",
    }
    data["litellm"]["config_file"] = str(REPO_ROOT / "docker" / "config.yaml")
    data["monitoring"] = {"alerts": {"email_receivers": ["ops@llmoxie.test"]}}
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
    assert "keycloak.admin_allowed_ips" in capsys.readouterr().out


def test_unpinned_images_are_ignored_with_keycloak_off():
    data = _data(keycloak={"config_cli_image": "x:latest"})
    data["keycloak"]["enabled"] = False
    LLMavenConfig.model_validate(data)


@pytest.mark.parametrize(
    "image",
    [
        "x@sha256:",
        "x:1@sha256:" + "X" * 64,
        "x:1@sha256:" + "a" * 63,
        "x@sha256:" + "a" * 64,
        "x:1@sha256:" + "a" * 64 + " ",
    ],
)
def test_images_need_a_full_pinned_reference(image):
    with pytest.raises(ValueError, match="sha256"):
        _config(keycloak={"oauth2_proxy_image": image})


def test_default_images_and_registry_ports_are_accepted():
    _config()
    _config(keycloak={"config_cli_image": "reg:5000/x:1@sha256:" + "a" * 64})


@pytest.mark.parametrize("client_id", ["$(env:CLIENT_ID)", "a-$(x)"])
def test_override_client_ids_cannot_use_substitution(client_id):
    with pytest.raises(ValueError, match=r"\$\("):
        _config(
            keycloak={"realm": {"overrides": {"clients": [{"clientId": client_id}]}}}
        )


def test_override_client_ids_are_compared_case_insensitively():
    with pytest.raises(ValueError, match="LiteLLM"):
        _config(
            keycloak={"realm": {"overrides": {"clients": [{"clientId": "LiteLLM"}]}}}
        )


def test_keycloak_image_needs_a_digest_when_enabled():
    # Keycloak's database migrations are one-way, so a moving tag is refused.
    for image in (
        "ghcr.io/uw-ssec/llmoxie-keycloak:latest",
        "ghcr.io/uw-ssec/llmoxie-keycloak@sha256:" + "a" * 64,
    ):
        with pytest.raises(ValueError, match=r"@sha256:"):
            _config(keycloak={"image": image})
    _config(keycloak={"image": PINNED_KEYCLOAK})


def test_unpinned_keycloak_image_is_ignored_with_keycloak_off():
    # The default stays :latest because Keycloak is off by default.
    config = LLMavenConfig()
    assert config.keycloak.image.endswith(":latest")


@pytest.mark.parametrize("key", ["realm", "id"])
def test_overrides_cannot_rename_the_realm(key):
    with pytest.raises(ValueError, match=r"keycloak\.realm\.name"):
        _config(keycloak={"realm": {"overrides": {key: "other"}}})


@pytest.mark.parametrize(
    "name",
    [
        "KEYCLOAK_PASSWORD",
        "KEYCLOAK_URL",
        "keycloak_user",
        "KEYCLOAK_AVAILABILITYCHECK_TIMEOUT",
        "KC_CLIENT_SECRET_LITELLM",
        "IMPORT_MANAGED_CLIENT",
        "REALM_DOCUMENT_SHA256",
    ],
)
def test_realm_secret_refs_cannot_use_reserved_names(name):
    with pytest.raises(ValueError, match="reserved"):
        _config(keycloak={"realm": {"secret_refs": {name: "some-secret"}}})


def test_realm_secret_refs_accept_other_names():
    config = _config(keycloak={"realm": {"secret_refs": {"SMTP_PASSWORD": "smtp"}}})
    assert config.keycloak.realm.secret_refs == {"SMTP_PASSWORD": "smtp"}
    assert not is_reserved_realm_env("SMTP_PASSWORD")


@pytest.mark.parametrize("app", ["mlflow", "litellm"])
def test_login_needs_its_app_enabled(app):
    data = _data(**{app: {"enabled": False, "login": {"enabled": True}}})
    with pytest.raises(ValueError, match=rf"{app}\.login\.enabled.*{app}\.enabled"):
        LLMavenConfig.model_validate(data)


def test_master_realm_is_rejected():
    with pytest.raises(ValueError, match="master"):
        _config(keycloak={"realm": {"name": "master"}})
