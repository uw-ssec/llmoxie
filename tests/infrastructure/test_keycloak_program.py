"""Run the whole Pulumi program under mocks to check the Keycloak wiring."""

from __future__ import annotations

import ast

import pytest

from llmaven.infrastructure import resources
from llmaven.infrastructure.config.schema import (
    KEYCLOAK_APP_SUFFIX,
    LITELLM_LOGIN_APP_SUFFIX,
    MLFLOW_LOGIN_APP_SUFFIX,
    container_app_name,
    realm_job_name,
)
from llmaven.infrastructure.resources import SecretsManager
from llmaven.infrastructure.resources import keycloak as keycloak_module
from llmaven.infrastructure.resources.secrets_manager import KEYCLOAK_SECRET_NAMES

from . import PINNED_KEYCLOAK_IMAGE
from .test_edge_program import EDGE, _run, _with_edge

KEYCLOAK_HOST = "auth.example.org"
ISSUER = f"https://{KEYCLOAK_HOST}/realms/llmoxie"
OIDC = "protocol/openid-connect"
KEYCLOAK_APP = f"llmaven-dev-{KEYCLOAK_APP_SUFFIX}"
KEYCLOAK_APP_NAME = container_app_name("llmaven", "dev", KEYCLOAK_APP_SUFFIX)
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
    config["keycloak"] = {
        "enabled": True,
        "image": PINNED_KEYCLOAK_IMAGE,
        "hostname": KEYCLOAK_HOST,
    }
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


def _forbid(monkeypatch):
    """Make every Keycloak entry point raise: stage 1 must never reach them."""

    def boom(*args, **kwargs):
        raise AssertionError("Keycloak code ran with keycloak.enabled false")

    for name in ("create_keycloak_app", "create_realm_job"):
        monkeypatch.setattr(resources, name, boom)
    monkeypatch.setattr(keycloak_module, "create_login_app", boom)
    monkeypatch.setattr(SecretsManager, "create_keycloak_secrets", boom)


def test_keycloak_off_is_stage_1(tmp_path_factory):
    runs = []
    for config in ({}, {"keycloak": {"enabled": False}}):
        with pytest.MonkeyPatch.context() as monkeypatch:
            _forbid(monkeypatch)
            edge_calls: dict = {}
            real = resources.create_edge_app

            def spy(*args, _real=real, **kwargs):
                edge_calls.update(kwargs)
                return _real(*args, **kwargs)

            monkeypatch.setattr(resources, "create_edge_app", spy)
            run = _run(
                tmp_path_factory.mktemp("off"), monkeypatch, **config, **_with_edge()
            )
            runs.append((run, edge_calls))
    (implicit, implicit_edge), (explicit, explicit_edge) = runs
    for run, edge in runs:
        assert set(run[2]) == {
            "llmaven-dev-litellm",
            "llmaven-dev-mlflow",
            "llmaven-dev-traefik",
        }
        assert not [k for k in run[1] if "keycloak" in k or "realm" in k]
        assert not [
            k
            for k in run[2]["llmaven-dev-litellm"]["env_vars"]
            if k.startswith("GENERIC_")
        ]
        assert set(edge["backends"]) == {"litellm", "mlflow"}

    def full(run):
        return sorted(
            (r.typ, r.name, repr(sorted(r.inputs.items(), key=str))) for r in run[0]
        )

    assert full(implicit) == full(explicit)
    assert implicit[1].keys() == explicit[1].keys()


def test_keycloak_resources_exist(keycloak_run):
    created, exports, apps, calls = keycloak_run
    expected = {
        container_app_name("llmaven", "dev", suffix)
        for suffix in (
            KEYCLOAK_APP_SUFFIX,
            MLFLOW_LOGIN_APP_SUFFIX,
            LITELLM_LOGIN_APP_SUFFIX,
        )
    }
    assert expected <= {
        container_app_name("llmaven", "dev", a.removeprefix("llmaven-dev-"))
        for a in apps
    }
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
    for key in (
        "client_mlflow_gate",
        "client_llmaven_cli",
        "client_litellm_gate",
        "client_litellm",
    ):
        secret = KEYCLOAK_SECRET_NAMES[key]
        assert f"kv-secret-{secret}-dev" in names, secret


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
    assert env["GENERIC_ROLE_MAPPINGS_GROUP_CLAIM"] == "realm_access.roles"
    # LiteLLM parses this with ast.literal_eval, so it is a Python dict literal.
    assert ast.literal_eval(env["GENERIC_ROLE_MAPPINGS_ROLES"]) == {
        "proxy_admin": ["litellm-admin"]
    }
    assert "GENERIC_USER_ROLE_ATTRIBUTE" not in env
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


def test_operator_client_secret_value_wins(tmp_path, monkeypatch):
    _, _, apps = _run(
        tmp_path,
        monkeypatch,
        **_keycloak(env_vars={"GENERIC_CLIENT_SECRET": "plain"}),
    )
    kwargs = apps["llmaven-dev-litellm"]
    assert kwargs["env_vars"]["GENERIC_CLIENT_SECRET"] == "plain"
    assert "GENERIC_CLIENT_SECRET" not in kwargs["key_vault_secret_refs"]


def test_operator_client_secret_ref_wins(tmp_path, monkeypatch):
    _, _, apps = _run(
        tmp_path,
        monkeypatch,
        **_keycloak(key_vault_secret_refs={"GENERIC_CLIENT_SECRET": "my-secret"}),
    )
    kwargs = apps["llmaven-dev-litellm"]
    assert kwargs["key_vault_secret_refs"]["GENERIC_CLIENT_SECRET"] == "my-secret"
    assert "GENERIC_CLIENT_SECRET" not in kwargs["env_vars"]
