"""The oauth2-proxy login apps in front of MLflow and the LiteLLM UI."""

from types import SimpleNamespace
from unittest.mock import patch

import pulumi
import pytest

from llmaven.infrastructure.config.schema import (
    LITELLM_LOGIN_APP_SUFFIX,
    MLFLOW_LOGIN_APP_SUFFIX,
    LLMavenConfig,
    container_app_name,
)
from llmaven.infrastructure.resources import container_apps, keycloak
from llmaven.infrastructure.resources.secrets_manager import KEYCLOAK_SECRET_NAMES
from llmaven.infrastructure.resources.traefik import LOGIN_COOKIE

from .test_edge_app import _isolated_mocks
from .test_keycloak_app import AUTH_HOST, IDENTITY, KC_FQDN, KEY_VAULT, _config

REALM_URL = f"https://{AUTH_HOST}/realms/llmoxie"
OIDC = "protocol/openid-connect"
SKIP_AUTH_ENV = (
    "OAUTH2_PROXY_SKIP_AUTH_ROUTES",
    "OAUTH2_PROXY_SKIP_AUTH_PREFLIGHT",
    "OAUTH2_PROXY_SKIP_AUTH_REGEX",
    "OAUTH2_PROXY_TRUSTED_IPS",
)


@pytest.fixture(autouse=True)
def _mocks():
    with _isolated_mocks():
        yield


def _create_login(kind: str, config: LLMavenConfig) -> dict:
    captured: dict = {}

    @pulumi.runtime.test
    def run():
        with (
            patch.object(
                container_apps.azure_native.app,
                "ContainerApp",
                return_value=SimpleNamespace(
                    name="app", configuration=pulumi.Output.from_input(None)
                ),
            ) as create_app,
            patch.object(container_apps.pulumi, "export"),
            patch.object(keycloak.azure_native.keyvault, "AccessPolicy") as policy,
        ):
            keycloak.create_login_app(
                kind,
                resource_group_name="rg",
                location="westus2",
                container_env_id="env-id",
                key_vault=KEY_VAULT,
                config=config,
                keycloak_fqdn=pulumi.Output.from_input(KC_FQDN),
                managed_identity_id=IDENTITY,
            )
        kwargs = create_app.call_args.kwargs
        container = kwargs["template"].containers[0]
        return pulumi.Output.all(
            env={e.name: e.value for e in container.env if e.value is not None},
            refs={e.name: e.secret_ref for e in container.env if e.secret_ref},
        ).apply(
            lambda r: captured.update(r, kwargs=kwargs, container=container, ap=policy)
        )

    run()
    return captured


def _common_env(kind: str, client: str, role: str, host: str) -> dict:
    return {
        "OAUTH2_PROXY_PROVIDER": "keycloak-oidc",
        "OAUTH2_PROXY_CLIENT_ID": client,
        "OAUTH2_PROXY_ALLOWED_ROLES": role,
        "OAUTH2_PROXY_OIDC_ISSUER_URL": REALM_URL,
        "OAUTH2_PROXY_SKIP_OIDC_DISCOVERY": "true",
        "OAUTH2_PROXY_LOGIN_URL": f"{REALM_URL}/{OIDC}/auth",
        "OAUTH2_PROXY_REDEEM_URL": f"https://{KC_FQDN}/realms/llmoxie/{OIDC}/token",
        "OAUTH2_PROXY_OIDC_JWKS_URL": f"https://{KC_FQDN}/realms/llmoxie/{OIDC}/certs",
        "OAUTH2_PROXY_REDIRECT_URL": f"https://{host}/oauth2/callback",
        "OAUTH2_PROXY_CODE_CHALLENGE_METHOD": "S256",
        "OAUTH2_PROXY_REVERSE_PROXY": "true",
        "OAUTH2_PROXY_UPSTREAMS": "static://202",
        "OAUTH2_PROXY_COOKIE_SECURE": "true",
        "OAUTH2_PROXY_COOKIE_NAME": LOGIN_COOKIE[kind],
        "OAUTH2_PROXY_EMAIL_DOMAINS": "*",
        "OAUTH2_PROXY_SKIP_PROVIDER_BUTTON": "true",
        "OAUTH2_PROXY_WHITELIST_DOMAINS": host,
        "OAUTH2_PROXY_HTTP_ADDRESS": "0.0.0.0:4180",
    }


def _check_shape(result: dict, suffix: str) -> None:
    kwargs = result["kwargs"]
    config = _config()
    assert kwargs["container_app_name"] == container_app_name("llmaven", "dev", suffix)
    ingress = kwargs["configuration"].ingress
    assert ingress.external is False
    assert ingress.target_port == 4180
    container = result["container"]
    assert container.image == config.keycloak.oauth2_proxy_image
    assert container.probes
    for probe in container.probes:
        assert probe.http_get.path == "/ping"
        assert probe.http_get.port == 4180


def test_login_app_shape_mlflow():
    result = _create_login("mlflow", _config())
    _check_shape(result, MLFLOW_LOGIN_APP_SUFFIX)
    expected = _common_env("mlflow", "mlflow-gate", "mlflow-user", "mlflow.example.org")
    expected["OAUTH2_PROXY_SKIP_JWT_BEARER_TOKENS"] = "true"
    assert result["env"].items() >= expected.items()
    assert result["refs"] == {
        "OAUTH2_PROXY_CLIENT_SECRET": KEYCLOAK_SECRET_NAMES["client_mlflow_gate"],
        "OAUTH2_PROXY_COOKIE_SECRET": KEYCLOAK_SECRET_NAMES["cookie_mlflow"],
    }
    assert KEYCLOAK_SECRET_NAMES["client_mlflow_gate"] == "keycloak-client-mlflow-gate"
    assert KEYCLOAK_SECRET_NAMES["cookie_mlflow"] == "oauth2-proxy-cookie-mlflow"


def test_login_app_shape_litellm():
    result = _create_login("litellm", _config())
    _check_shape(result, LITELLM_LOGIN_APP_SUFFIX)
    expected = _common_env("litellm", "litellm-gate", "litellm-admin", "ai.example.org")
    assert result["env"].items() >= expected.items()
    # LiteLLM's bearer keys are not Keycloak tokens, so they are never verified here.
    assert "OAUTH2_PROXY_SKIP_JWT_BEARER_TOKENS" not in result["env"]
    assert result["refs"] == {
        "OAUTH2_PROXY_CLIENT_SECRET": KEYCLOAK_SECRET_NAMES["client_litellm_gate"],
        "OAUTH2_PROXY_COOKIE_SECRET": KEYCLOAK_SECRET_NAMES["cookie_litellm"],
    }


@pytest.mark.parametrize("kind", ["mlflow", "litellm"])
def test_login_apps_never_skip_auth(kind):
    # Traefik forwards with trustForwardHeader, so a client's X-Forwarded-* can
    # reach oauth2-proxy; none of its skip-auth switches may ever be on.
    result = _create_login(kind, _config())
    for name in SKIP_AUTH_ENV:
        assert name not in result["env"]
        assert name not in result["refs"]
