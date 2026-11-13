"""Standalone Traefik edge config and the backends' hostnames."""

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from pydantic import ValidationError as PydanticValidationError

from llmaven.deployment import validate as validate_mod
from llmaven.deployment.validate import ValidationError, validate_config
from llmaven.infrastructure.config.schema import LLMavenConfig

REPO_ROOT = Path(__file__).resolve().parents[2]

EXISTING_STACK = {
    "networking": {
        "vnet_address_space": "172.16.0.0/16",
        "container_apps_subnet": "172.16.0.0/23",
        "postgres_subnet": "172.16.2.0/24",
    },
}

TRUSTED = ["100.100.0.0/17"]
LITELLM_HOST = "ai.example.org"
MLFLOW_HOST = "mlflow.example.org"


def _domains(*names: str) -> list[dict]:
    return [{"name": n, "certificate_name": f"cert-{i}"} for i, n in enumerate(names)]


def _data(edge: dict | None = None, litellm: dict | None = None, mlflow=None) -> dict:
    return {
        **EXISTING_STACK,
        "edge": {
            "enabled": True,
            "custom_domains": _domains(LITELLM_HOST, MLFLOW_HOST),
            "trusted_proxy_ips": TRUSTED,
            **(edge or {}),
        },
        "litellm": {
            "cpu": 2,
            "memory": "4Gi",
            "hostname": LITELLM_HOST,
            **(litellm or {}),
        },
        "mlflow": {"hostname": MLFLOW_HOST, **(mlflow or {})},
    }


def _config(**kwargs) -> LLMavenConfig:
    return LLMavenConfig.model_validate(_data(**kwargs))


def test_edge_is_off_by_default():
    config = LLMavenConfig()
    assert config.edge.enabled is False
    assert config.litellm.hostname is None
    assert config.mlflow.hostname is None


def test_trusted_proxy_ips_are_required_when_the_edge_is_on():
    data = _data()
    del data["edge"]["trusted_proxy_ips"]
    with pytest.raises(ValueError, match=r"edge\.trusted_proxy_ips.*#229"):
        LLMavenConfig.model_validate(data)


def test_trusted_proxy_ips_error_names_the_ranges():
    data = _data(edge={"trusted_proxy_ips": None})
    with pytest.raises(ValueError) as error:
        LLMavenConfig.model_validate(data)
    message = str(error.value)
    assert "100.100.0.0/17" in message
    assert "100.100.192.0/19" in message


def test_empty_trusted_proxy_ips_are_rejected():
    with pytest.raises(ValueError, match=r"edge\.trusted_proxy_ips"):
        _config(edge={"trusted_proxy_ips": []})


def test_explicit_trusted_proxy_ips_are_kept():
    config = _config(edge={"trusted_proxy_ips": ["10.0.0.0/24", "100.100.0.0/17"]})
    assert config.edge.trusted_proxy_ips == ["10.0.0.0/24", "100.100.0.0/17"]


def test_edge_off_needs_no_trusted_proxy_ips():
    config = LLMavenConfig.model_validate({"edge": {"enabled": False}})
    assert config.edge.trusted_proxy_ips is None


def test_edge_needs_a_hostname_per_enabled_backend():
    data = _data()
    del data["litellm"]["hostname"]
    with pytest.raises(ValueError, match=r"litellm\.hostname"):
        LLMavenConfig.model_validate(data)

    data = _data()
    del data["mlflow"]["hostname"]
    with pytest.raises(ValueError, match=r"mlflow\.hostname"):
        LLMavenConfig.model_validate(data)

    data = _data(litellm={"enabled": False})
    del data["litellm"]["hostname"]
    LLMavenConfig.model_validate(data)


def test_edge_needs_an_enabled_backend():
    with pytest.raises(ValueError, match="at least one enabled backend"):
        _config(litellm={"enabled": False}, mlflow={"enabled": False})


def test_backend_hostname_must_be_an_edge_custom_domain():
    with pytest.raises(ValueError, match=r"edge\.custom_domains"):
        _config(edge={"custom_domains": _domains(MLFLOW_HOST)})


def test_backend_hostnames_must_differ():
    with pytest.raises(ValueError, match="must differ"):
        _config(mlflow={"hostname": LITELLM_HOST})


def test_edge_refuses_the_litellm_sidecar():
    with pytest.raises(ValueError) as exc:
        _config(litellm={"proxy": {"enabled": True}})
    assert "litellm.hostname" in str(exc.value)
    assert "litellm.admin_allowed_ips" in str(exc.value)


@pytest.mark.parametrize("app", ["litellm", "mlflow"])
def test_edge_refuses_custom_domains_on_backends(app):
    with pytest.raises(ValueError, match=r"edge\.custom_domains"):
        _config(**{app: {"custom_domains": _domains(LITELLM_HOST)}})


def test_edge_refuses_app_ip_rules_on_litellm():
    rule = {"name": "office", "ip_address_range": "203.0.113.0/24"}
    with pytest.raises(ValueError, match="ip_security_restrictions"):
        _config(litellm={"ip_security_restrictions": [rule]})


def test_edge_needs_health_paths():
    with pytest.raises(ValueError, match="health_paths"):
        _config(litellm={"health_paths": []})


@pytest.mark.parametrize(
    "hostname",
    [
        "https://ai.example.org",
        "ai.example.org:443",
        "ai.example.org/v1",
        "a`b.example.org",
        "AI.example.org",
        "ai.example.org\n",
    ],
)
def test_invalid_hostname_is_rejected(hostname):
    with pytest.raises(PydanticValidationError):
        LLMavenConfig.model_validate({"litellm": {"hostname": hostname}})
    with pytest.raises(PydanticValidationError):
        LLMavenConfig.model_validate({"mlflow": {"hostname": hostname}})


def test_duplicate_edge_custom_domains_are_rejected():
    with pytest.raises(ValueError, match=LITELLM_HOST):
        _config(
            edge={"custom_domains": _domains(LITELLM_HOST, MLFLOW_HOST, LITELLM_HOST)}
        )


def test_existing_sidecar_config_still_validates():
    config = LLMavenConfig.model_validate({"litellm": {"proxy": {"enabled": True}}})
    assert config.edge.enabled is False
    assert config.litellm.proxy.enabled is True


def test_new_litellm_fields_reuse_the_proxy_validation():
    with pytest.raises(PydanticValidationError):
        LLMavenConfig.model_validate({"litellm": {"admin_allowed_ips": ["nope"]}})
    with pytest.raises(PydanticValidationError):
        LLMavenConfig.model_validate({"litellm": {"public_paths": ["v1/x"]}})


def _run_validate(tmp_path: Path, min_replicas: int, strict: bool) -> None:
    data = _data(edge={"min_replicas": min_replicas})
    data["project"] = {"name": "llmaven", "environment": "prod", "location": "eastus"}
    data["azure"] = {
        "subscription_id": "00000000-0000-0000-0000-000000000000",
        "tenant_id": "00000000-0000-0000-0000-000000000000",
        "resource_group": "rg-test",
    }
    data["monitoring"] = {"alerts": {"email_receivers": ["ops@llmoxie.test"]}}
    data["litellm"]["config_file"] = str(REPO_ROOT / "docker" / "config.yaml")
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
        validate_config(path, strict=strict)


def test_prod_edge_with_one_replica_warns(tmp_path, capsys):
    _run_validate(tmp_path, min_replicas=1, strict=False)
    assert "edge.min_replicas" in capsys.readouterr().out

    with pytest.raises(ValidationError):
        _run_validate(tmp_path, min_replicas=1, strict=True)


def test_prod_edge_with_two_replicas_does_not_warn(tmp_path, capsys):
    _run_validate(tmp_path, min_replicas=2, strict=False)
    assert "edge.min_replicas" not in capsys.readouterr().out


def _validate_data(tmp_path: Path, data: dict, strict: bool = False) -> None:
    data["azure"] = {
        "subscription_id": "00000000-0000-0000-0000-000000000000",
        "tenant_id": "00000000-0000-0000-0000-000000000000",
        "resource_group": "rg-test",
    }
    data["litellm"] = {
        **data.get("litellm", {}),
        "config_file": str(REPO_ROOT / "docker" / "config.yaml"),
    }
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
        validate_config(path, strict=strict)


@pytest.mark.parametrize(
    "litellm, mlflow, field",
    [
        ({"hostname": LITELLM_HOST}, {}, "litellm.hostname"),
        ({"admin_allowed_ips": ["203.0.113.0/24"]}, {}, "litellm.admin_allowed_ips"),
        ({}, {"hostname": MLFLOW_HOST}, "mlflow.hostname"),
    ],
)
def test_edge_only_settings_without_the_edge_warn(
    tmp_path, capsys, litellm, mlflow, field
):
    data = {**EXISTING_STACK, "litellm": litellm, "mlflow": mlflow}
    _validate_data(tmp_path, data)
    assert f"{field} is set but edge.enabled is false" in capsys.readouterr().out

    with pytest.raises(ValidationError):
        _validate_data(tmp_path, {**data}, strict=True)


def test_edge_only_settings_with_the_edge_do_not_warn(tmp_path, capsys):
    _validate_data(tmp_path, _data())
    assert "edge.enabled is false" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "edge",
    [
        {"env_vars": {"A": "b"}},
        {"key_vault_secret_refs": {"A": "b"}},
        {"min_replicas": 0},
        {"revision_suffix": "x" * 55},
    ],
)
def test_edge_rejects_settings_it_ignores_or_cannot_honour(edge):
    with pytest.raises(PydanticValidationError):
        _config(edge=edge)


def test_edge_accepts_a_suffix_at_the_limit_and_one_replica():
    config = _config(edge={"revision_suffix": "x" * 54, "min_replicas": 1})
    assert config.edge.min_replicas == 1


def test_disabled_edge_ignores_those_checks():
    config = LLMavenConfig.model_validate(
        {"edge": {"enabled": False, "env_vars": {"A": "b"}, "min_replicas": 0}}
    )
    assert config.edge.enabled is False
