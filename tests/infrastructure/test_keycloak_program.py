"""Run the whole Pulumi program under mocks to check the Keycloak wiring."""

from __future__ import annotations

import pytest

from llmaven.infrastructure import resources
from llmaven.infrastructure.config.schema import (
    KEYCLOAK_APP_SUFFIX,
    LITELLM_LOGIN_APP_SUFFIX,
    MLFLOW_LOGIN_APP_SUFFIX,
    realm_job_name,
)

from .test_edge_program import EDGE, LITELLM_HOST, MLFLOW_HOST, _run, _with_edge

KEYCLOAK_HOST = "auth.example.org"
ISSUER = f"https://{KEYCLOAK_HOST}/realms/llmoxie"
OIDC = "protocol/openid-connect"
KEYCLOAK_APP = f"llmaven-dev-{KEYCLOAK_APP_SUFFIX}"
KEYCLOAK_INTERNAL = f"{KEYCLOAK_APP}.internal.env.test"
ML_AUTH = f"llmaven-dev-{MLFLOW_LOGIN_APP_SUFFIX}"
LLM_AUTH = f"llmaven-dev-{LITELLM_LOGIN_APP_SUFFIX}"

KEYCLOAK_EDGE = {
    **EDGE,
    "custom_domains": [
        *EDGE["custom_domains"],
        {"name": KEYCLOAK_HOST, "certificate_name": "cert-2"},
    ],
}


def _keycloak(mlflow_login=True, litellm_login=True, **litellm):
    config = _with_edge(**litellm)
    config["edge"] = KEYCLOAK_EDGE
    config["keycloak"] = {"enabled": True, "hostname": KEYCLOAK_HOST}
    config["mlflow"]["login"] = {"enabled": mlflow_login}
    config["litellm"]["login"] = {"enabled": litellm_login}
    return config


@pytest.fixture(scope="module")
def keycloak_run(tmp_path_factory):
    """(resources, exports, apps, calls) with Keycloak and both logins on."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        calls: dict[str, dict] = {}
        for name in ("create_realm_job", "create_edge_app"):
            real = getattr(resources, name)

            def wrapper(*args, _real=real, _name=name, **kwargs):
                calls[_name] = kwargs
                return _real(*args, **kwargs)

            monkeypatch.setattr(resources, name, wrapper)
        run = _run(tmp_path_factory.mktemp("keycloak"), monkeypatch, **_keycloak())
        return (*run, calls)


def _depends_on(kwargs) -> list[str]:
    return [d._name for d in kwargs["opts"].depends_on]


POLICY = "apps-identity"


def test_keycloak_off_is_stage_1(tmp_path_factory):
    with pytest.MonkeyPatch.context() as monkeypatch:
        implicit = _run(tmp_path_factory.mktemp("a"), monkeypatch, **_with_edge())
    with pytest.MonkeyPatch.context() as monkeypatch:
        explicit = _run(
            tmp_path_factory.mktemp("b"),
            monkeypatch,
            keycloak={"enabled": False},
            **_with_edge(),
        )
    for run in (implicit, explicit):
        assert not [r for r in run[0] if "keycloak" in r.name or "realm" in r.name]
        assert not [k for k in run[1] if "keycloak" in k or "realm" in k]
        assert set(run[2]) == {
            "llmaven-dev-litellm",
            "llmaven-dev-mlflow",
            "llmaven-dev-traefik",
        }

    def shape(run):
        return sorted((r.typ, r.name, sorted(r.inputs)) for r in run[0])

    assert shape(implicit) == shape(explicit)
    assert implicit[1] == explicit[1]
    assert not any(
        k.startswith("GENERIC_") for k in implicit[2]["llmaven-dev-litellm"]["env_vars"]
    )


def test_keycloak_resources_exist(keycloak_run):
    created, exports, apps, calls = keycloak_run
    assert {KEYCLOAK_APP, ML_AUTH, LLM_AUTH} <= set(apps)
    assert calls["create_realm_job"]["keycloak_fqdn"] is not None
    assert [e for e in exports if e.startswith("realm_job_name_")] == [
        "realm_job_name_dev"
    ]
    databases = [r for r in created if r.typ == "azure-native:dbforpostgresql:Database"]
    assert "keycloak_db" in {r.inputs.get("databaseName") for r in databases}
    for name in (KEYCLOAK_APP, ML_AUTH, LLM_AUTH):
        assert any(POLICY in n for n in _depends_on(apps[name])), name
    assert any(POLICY in n for n in _depends_on(calls["create_realm_job"]))


def test_realm_job_waits_for_keycloak_and_client_secrets(keycloak_run):
    names = _depends_on(keycloak_run[3]["create_realm_job"])
    assert KEYCLOAK_APP in names
    for secret in ("keycloak-client-litellm", "keycloak-client-mlflow-gate"):
        assert any(secret in n for n in names), secret


def test_login_apps_use_keycloaks_internal_fqdn(keycloak_run):
    redeem = keycloak_run[2][ML_AUTH]["resolved_env"]["OAUTH2_PROXY_REDEEM_URL"]
    assert redeem == f"https://{KEYCLOAK_INTERNAL}/realms/llmoxie/{OIDC}/token"


def test_edge_gets_all_backends(keycloak_run):
    calls = keycloak_run[3]
    assert set(calls["create_edge_app"]["backends"]) == {
        "litellm",
        "mlflow",
        "keycloak",
        "mlflow-auth",
        "litellm-auth",
    }
    waits = _depends_on(calls["create_edge_app"])
    assert {KEYCLOAK_APP, ML_AUTH, LLM_AUTH} <= set(waits)


def test_litellm_sso_env(keycloak_run):
    kwargs = keycloak_run[2]["llmaven-dev-litellm"]
    env = kwargs["env_vars"]
    assert env["GENERIC_CLIENT_ID"] == "litellm"
    assert env["GENERIC_AUTHORIZATION_ENDPOINT"] == f"{ISSUER}/{OIDC}/auth"
    resolved = kwargs["resolved_env"]
    internal = f"https://{KEYCLOAK_INTERNAL}/realms/llmoxie/{OIDC}"
    assert resolved["GENERIC_TOKEN_ENDPOINT"] == f"{internal}/token"
    assert resolved["GENERIC_USERINFO_ENDPOINT"] == f"{internal}/userinfo"
    assert env["GENERIC_SCOPE"] == "openid email profile"
    assert env["GENERIC_USER_ID_ATTRIBUTE"] == "preferred_username"
    assert env["GENERIC_USER_EMAIL_ATTRIBUTE"] == "email"
    assert env["GENERIC_USER_DISPLAY_NAME_ATTRIBUTE"] == "name"
    assert env["GENERIC_USER_ROLE_ATTRIBUTE"] == "role"
    assert kwargs["key_vault_secret_refs"]["GENERIC_CLIENT_SECRET"] == (
        "keycloak-client-litellm"
    )
    assert "GENERIC_CLIENT_SECRET" not in env


def test_litellm_sso_env_operator_wins(tmp_path, monkeypatch):
    (
        _,
        _,
        apps,
    ) = _run(
        tmp_path,
        monkeypatch,
        **_keycloak(env_vars={"GENERIC_SCOPE": "openid", "GENERIC_CLIENT_ID": "x"}),
    )
    env = apps["llmaven-dev-litellm"]["env_vars"]
    assert env["GENERIC_SCOPE"] == "openid"
    assert env["GENERIC_CLIENT_ID"] == "x"


def test_litellm_sso_env_absent_without_login(tmp_path, monkeypatch):
    _, _, apps = _run(tmp_path, monkeypatch, **_keycloak(litellm_login=False))
    kwargs = apps["llmaven-dev-litellm"]
    assert not [k for k in kwargs["env_vars"] if k.startswith("GENERIC_")]
    assert "GENERIC_CLIENT_SECRET" not in kwargs["key_vault_secret_refs"]
    assert LLM_AUTH not in apps and ML_AUTH in apps


def test_exports(keycloak_run):
    exports = keycloak_run[1]
    assert exports["keycloak_url"] == f"https://{KEYCLOAK_HOST}"
    assert exports["keycloak_issuer"] == ISSUER
    assert exports["keycloak_realm"] == "llmoxie"
    assert exports["keycloak_realm_job"] == realm_job_name("llmaven", "dev")
