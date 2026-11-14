"""The Keycloak realm document rendered from config."""

import json
import re

import pytest

from llmaven.infrastructure.config.schema import LLMavenConfig
from llmaven.infrastructure.resources.keycloak_realm import (
    CLIENT_SECRET_ENV,
    build_realm_document,
    merge_overrides,
    render_realm_document,
)

LITELLM_HOST = "ai.example.org"
MLFLOW_HOST = "mlflow.example.org"
AUTH_HOST = "auth.example.org"


def _config(mlflow_login=True, litellm_login=True, overrides=None) -> LLMavenConfig:
    domains = [
        {"name": n, "certificate_name": f"cert-{i}"}
        for i, n in enumerate((LITELLM_HOST, MLFLOW_HOST, AUTH_HOST))
    ]
    return LLMavenConfig.model_validate(
        {
            "networking": {
                "vnet_address_space": "172.16.0.0/16",
                "container_apps_subnet": "172.16.0.0/23",
                "postgres_subnet": "172.16.2.0/24",
            },
            "edge": {
                "enabled": True,
                "custom_domains": domains,
                "trusted_proxy_ips": ["100.100.0.0/17"],
            },
            "litellm": {
                "cpu": 2,
                "memory": "4Gi",
                "hostname": LITELLM_HOST,
                "login": {"enabled": litellm_login},
            },
            "mlflow": {
                "hostname": MLFLOW_HOST,
                "login": {"enabled": mlflow_login},
            },
            "keycloak": {
                "enabled": True,
                "hostname": AUTH_HOST,
                "realm": {"overrides": overrides or {}},
            },
        }
    )


def _client(doc: dict, client_id: str) -> dict:
    return next(c for c in doc["clients"] if c["clientId"] == client_id)


def test_client_secret_env_names():
    assert CLIENT_SECRET_ENV == {
        "mlflow-gate": "KC_CLIENT_SECRET_MLFLOW_GATE",
        "litellm-gate": "KC_CLIENT_SECRET_LITELLM_GATE",
        "litellm": "KC_CLIENT_SECRET_LITELLM",
        "llmaven-cli": "KC_CLIENT_SECRET_LLMAVEN_CLI",
    }


def test_realm_basics():
    doc = build_realm_document(_config())
    assert doc["realm"] == "llmoxie"
    assert doc["enabled"] is True
    assert doc["displayName"] == "LLMoxie"
    assert doc["registrationAllowed"] is False
    assert doc["verifyEmail"] is True
    assert doc["bruteForceProtected"] is True


def test_roles_follow_enabled_logins():
    both = build_realm_document(_config())
    assert {r["name"] for r in both["roles"]["realm"]} == {
        "mlflow-user",
        "litellm-admin",
    }
    only_mlflow = build_realm_document(_config(litellm_login=False))
    assert {r["name"] for r in only_mlflow["roles"]["realm"]} == {"mlflow-user"}
    ids = {c["clientId"] for c in only_mlflow["clients"]}
    assert ids == {"mlflow-gate", "llmaven-cli"}


def test_no_login_renders_realm_basics_only():
    doc = build_realm_document(_config(mlflow_login=False, litellm_login=False))
    assert doc["realm"] == "llmoxie"
    assert doc.get("clients", []) == []
    assert doc.get("roles", {}).get("realm", []) == []


def test_gate_clients():
    doc = build_realm_document(_config())
    for client_id, host, env in (
        ("mlflow-gate", MLFLOW_HOST, "KC_CLIENT_SECRET_MLFLOW_GATE"),
        ("litellm-gate", LITELLM_HOST, "KC_CLIENT_SECRET_LITELLM_GATE"),
    ):
        client = _client(doc, client_id)
        assert client["publicClient"] is False
        assert client["standardFlowEnabled"] is True
        assert client["attributes"]["pkce.code.challenge.method"] == "S256"
        assert client["redirectUris"] == [f"https://{host}/oauth2/callback"]
        assert client["secret"] == f"$(env:{env})"


def test_litellm_sso_client():
    client = _client(build_realm_document(_config()), "litellm")
    assert "pkce.code.challenge.method" not in client["attributes"]
    assert client["redirectUris"] == [f"https://{LITELLM_HOST}/sso/callback"]
    assert client["publicClient"] is False
    assert client["standardFlowEnabled"] is True
    assert client["secret"] == "$(env:KC_CLIENT_SECRET_LITELLM)"


def test_cli_client_is_service_account_only():
    doc = build_realm_document(_config())
    client = _client(doc, "llmaven-cli")
    assert client["serviceAccountsEnabled"] is True
    assert client["standardFlowEnabled"] is False
    assert client["directAccessGrantsEnabled"] is False
    assert client["secret"] == "$(env:KC_CLIENT_SECRET_LLMAVEN_CLI)"
    audience = next(
        m
        for m in client["protocolMappers"]
        if m["protocolMapper"] == "oidc-audience-mapper"
    )
    assert audience["config"]["included.client.audience"] == "mlflow-gate"
    user = next(
        u for u in doc["users"] if u["username"] == "service-account-llmaven-cli"
    )
    assert user["serviceAccountClientId"] == "llmaven-cli"
    assert "mlflow-user" in user["realmRoles"]
    # oauth2-proxy rejects a bearer token without a verified email; .invalid
    # is reserved (RFC 2606) so the address can never receive mail.
    assert user["email"] == "llmaven-cli@service.invalid"
    assert user["emailVerified"] is True
    # No explicit scope list: the realm's default `email` scope applies.
    assert "defaultClientScopes" not in client


def test_roles_reach_access_tokens():
    doc = build_realm_document(_config())
    for client in doc["clients"]:
        mappers = [
            m
            for m in client["protocolMappers"]
            if m["protocolMapper"] == "oidc-usermodel-realm-role-mapper"
        ]
        assert len(mappers) == 1, client["clientId"]
        assert mappers[0]["protocol"] == "openid-connect"
        assert mappers[0]["config"]["claim.name"] == "realm_access.roles"
        assert mappers[0]["config"]["access.token.claim"] == "true"


def test_no_secret_values_in_document():
    config = _config()
    doc = build_realm_document(config)
    for client in doc["clients"]:
        assert client["secret"] == f"$(env:{CLIENT_SECRET_ENV[client['clientId']]})"
    text = render_realm_document(config)
    stripped = re.sub(r"\$\(env:[A-Z0-9_]+\)", "", text)
    allowed = {
        "oidc-usermodel-realm-role-mapper",
        "oidc-audience-mapper",
        f"https://{MLFLOW_HOST}/oauth2/callback",
        f"https://{LITELLM_HOST}/oauth2/callback",
        f"https://{LITELLM_HOST}/sso/callback",
    }
    long = [
        s
        for s in re.findall(r'"([^"]*)"', stripped)
        if len(s) >= 32 and s not in allowed
    ]
    assert long == []


@pytest.mark.parametrize(
    "overrides, path",
    [
        ({"clients": None}, "clients"),
        ({"clients": {}}, "clients"),
        ({"roles": []}, "roles"),
        ({"roles": {"realm": None}}, "roles.realm"),
    ],
)
def test_type_changing_overrides_are_rejected(overrides, path):
    with pytest.raises(ValueError, match=f"realm.overrides.{path} must be"):
        build_realm_document(_config(overrides=overrides))


def test_same_role_on_both_logins_is_one_role():
    config = _config()
    config.mlflow.login.role = "admin"
    config.litellm.login.role = "admin"
    names = [r["name"] for r in build_realm_document(config)["roles"]["realm"]]
    assert names == ["admin"]


def test_overrides_merge_lists_by_key():
    overrides = {
        "identityProviders": [{"alias": "cilogon", "providerId": "oidc"}],
        "clients": [{"clientId": "jupyterhub"}],
        "displayName": "X",
        "roles": {"realm": [{"name": "mlflow-user", "description": "Edited"}]},
    }
    doc = build_realm_document(_config(overrides=overrides))
    assert {c["clientId"] for c in doc["clients"]} == {
        "mlflow-gate",
        "litellm-gate",
        "litellm",
        "llmaven-cli",
        "jupyterhub",
    }
    assert [p["alias"] for p in doc["identityProviders"]] == ["cilogon"]
    assert doc["displayName"] == "X"
    roles = [r for r in doc["roles"]["realm"] if r["name"] == "mlflow-user"]
    assert len(roles) == 1
    assert roles[0]["description"] == "Edited"


def test_merge_overrides_replaces_other_lists_and_merges_client_roles():
    base = {"redirects": ["a"], "roles": {"client": {"c": [{"name": "r", "x": 1}]}}}
    out = merge_overrides(
        base, {"redirects": ["b"], "roles": {"client": {"c": [{"name": "r", "y": 2}]}}}
    )
    assert out["redirects"] == ["b"]
    assert out["roles"]["client"]["c"] == [{"name": "r", "x": 1, "y": 2}]
    assert base["redirects"] == ["a"]


def test_render_is_deterministic():
    config = _config()
    first = render_realm_document(config)
    assert first == render_realm_document(config)
    assert first == json.dumps(json.loads(first), sort_keys=True, indent=2)
