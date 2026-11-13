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


def test_trusted_proxy_ips_default_to_container_apps_subnet():
    assert _config().edge.trusted_proxy_ips == ["172.16.0.0/23"]


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
    ],
)
def test_invalid_hostname_is_rejected(hostname):
    with pytest.raises(PydanticValidationError):
        LLMavenConfig.model_validate({"litellm": {"hostname": hostname}})
    with pytest.raises(PydanticValidationError):
        LLMavenConfig.model_validate({"mlflow": {"hostname": hostname}})


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
