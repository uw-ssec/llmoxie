"""LiteLLM split into a gateway host (AI paths and health) and an admin host."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from llmaven.infrastructure.config.schema import LLMavenConfig
from llmaven.infrastructure.resources.keycloak_realm import build_realm_document
from llmaven.infrastructure.resources.traefik import (
    LOGIN_COOKIE,
    render_edge_dynamic_config,
)

from . import PINNED_KEYCLOAK_IMAGE
from .test_edge_config import LITELLM_HOST, MLFLOW_HOST, _data
from .test_edge_login_routing import (
    BACKENDS,
    KEYCLOAK_ADMIN,
    KEYCLOAK_HOST,
    _carries,
    _config as _base_config,
    _http,
    _winner,
)
from .test_edge_app import _isolated_mocks
from .test_login_app import _create_login

GATEWAY = LITELLM_HOST
ADMIN = "litellm-admin.example.org"
FIXTURES = Path(__file__).parent / "fixtures"


def _config(
    admin=ADMIN, *, keycloak=True, mlflow_login=True, litellm_login=True, **litellm
) -> LLMavenConfig:
    data = _data(litellm={"admin_allowed_ips": ["203.0.113.0/24"], **litellm})
    data["edge"]["custom_domains"] += [
        {"name": KEYCLOAK_HOST, "certificate_name": "cert-kc"},
        {"name": ADMIN, "certificate_name": "cert-admin"},
    ]
    if keycloak:
        data["keycloak"] = {
            "enabled": True,
            "image": PINNED_KEYCLOAK_IMAGE,
            "hostname": KEYCLOAK_HOST,
            "admin_allowed_ips": [KEYCLOAK_ADMIN],
        }
    data["mlflow"]["login"] = {"enabled": mlflow_login}
    data["litellm"]["login"] = {"enabled": litellm_login}
    if admin is not None:
        data["litellm"]["admin_hostname"] = admin
    return LLMavenConfig.model_validate(data)


# Golden renders captured from the code before admin_hostname existed (commit
# b0d1709), so "unset renders unchanged" compares against the old behaviour.
GOLDENS = {
    "keycloak_logins_on": (_base_config(), BACKENDS),
    "litellm_login_off": (_base_config(litellm_login=False), BACKENDS),
    "no_keycloak": (
        _base_config(keycloak=False, mlflow_login=False, litellm_login=False),
        {k: v for k, v in BACKENDS.items() if k in ("litellm", "mlflow")},
    ),
}


@pytest.mark.parametrize("name", GOLDENS)
def test_unset_admin_hostname_renders_unchanged(name):
    config, backends = GOLDENS[name]
    assert config.litellm.admin_hostname is None
    expected = (FIXTURES / f"edge_dynamic_{name}.yaml").read_text()
    assert render_edge_dynamic_config(config, backends) == expected


@pytest.mark.parametrize(
    "path", ["/v1/chat/completions", "/v1/models", "/health/liveliness"]
)
def test_gateway_serves_ai_and_health_paths(path):
    http = _http(_config(), BACKENDS)
    assert _winner(http, GATEWAY, path) in {"litellm-public", "litellm-health"}


@pytest.mark.parametrize("login", [True, False])
@pytest.mark.parametrize(
    "path",
    [
        "/ui/",
        "/ui",
        "/key/list",
        "/sso/key/generate",
        "/oauth2/start",
        "/V1/chat/completions",
        "/v1/chat/completions/",
        "/v1/chat%2Fcompletions",
        "/",
    ],
)
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer sk-x"},
        {"Cookie": f"{LOGIN_COOKIE['litellm']}=x"},
    ],
)
def test_gateway_has_no_route_for_anything_else(path, headers, login):
    http = _http(_config(litellm_login=login), BACKENDS)
    assert _winner(http, GATEWAY, path, **headers) is None


def test_admin_host_gets_the_login_routes():
    http = _http(_config(), BACKENDS)
    assert _winner(http, ADMIN, "/ui/") == "litellm-admin"
    assert _carries(http, "litellm-admin", "litellm-login")
    assert _winner(http, ADMIN, "/oauth2/callback") == "litellm-oauth2"
    # the AI paths are not served on the admin host through the public routers
    assert _winner(http, ADMIN, "/v1/chat/completions") == "litellm-admin"


def test_admin_host_without_login_is_the_ip_allowlisted_catch_all():
    http = _http(_config(litellm_login=False), BACKENDS)
    router = http["routers"]["litellm-admin"]
    assert router["rule"] == f"Host(`{ADMIN}`)"
    assert "litellm-admin-ip-allowlist" in router["middlewares"]


def test_admin_hostname_must_be_a_custom_domain():
    data = _data(litellm={"admin_hostname": "elsewhere.example.org"})
    with pytest.raises(ValidationError, match="edge.custom_domains"):
        LLMavenConfig.model_validate(data)


@pytest.mark.parametrize("other", ["litellm", "mlflow", "keycloak"])
def test_admin_hostname_must_differ_from_other_hosts(other):
    hosts = {"litellm": LITELLM_HOST, "mlflow": MLFLOW_HOST, "keycloak": KEYCLOAK_HOST}
    with pytest.raises(ValidationError, match="must differ"):
        _config(admin=hosts[other])


def test_ui_hostname_falls_back_to_hostname():
    assert _config(admin=None).litellm.ui_hostname == LITELLM_HOST
    assert _config().litellm.ui_hostname == ADMIN
    assert _config(admin=None).mlflow.ui_hostname == MLFLOW_HOST


def test_realm_uses_ui_hostname():
    doc = build_realm_document(_config())
    uris = {c["clientId"]: c.get("redirectUris") for c in doc["clients"]}
    assert uris["litellm-gate"] == [f"https://{ADMIN}/oauth2/callback"]
    assert uris["litellm"] == [f"https://{ADMIN}/sso/callback"]


def test_login_app_uses_ui_hostname():
    with _isolated_mocks():
        env = _create_login("litellm", _config())["env"]
    assert env["OAUTH2_PROXY_REDIRECT_URL"] == f"https://{ADMIN}/oauth2/callback"
    assert env["OAUTH2_PROXY_WHITELIST_DOMAINS"] == ADMIN
