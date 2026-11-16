"""The console's confidential client in the Keycloak realm."""

import json
from pathlib import Path

import pytest

from llmaven.infrastructure.resources.keycloak import _job_secret_refs
from llmaven.infrastructure.resources.keycloak_realm import (
    CLIENT_SECRET_ENV,
    build_realm_document,
    render_realm_document,
)
from llmaven.infrastructure.resources.secrets_manager import KEYCLOAK_SECRET_NAMES

from .test_console_config import CONSOLE_HOST, _config
from .test_litellm_admin_host import _config as _base_config

FIXTURES = Path(__file__).parent / "fixtures"


def _clients(config) -> dict:
    return {c["clientId"]: c for c in build_realm_document(config).get("clients", [])}


def test_console_client_present_when_enabled():
    client = _clients(_config())["console"]
    assert client["redirectUris"] == [f"https://{CONSOLE_HOST}/auth/callback"]
    assert client["publicClient"] is False
    assert client["standardFlowEnabled"] is True
    assert client["serviceAccountsEnabled"] is False
    assert client["attributes"]["pkce.code.challenge.method"] == "S256"
    assert (
        client["attributes"]["post.logout.redirect.uris"] == f"https://{CONSOLE_HOST}/*"
    )
    assert client["secret"] == "$(env:KC_CLIENT_SECRET_CONSOLE)"


def test_console_client_audience_mapper():
    mappers = {m["name"]: m for m in _clients(_config())["console"]["protocolMappers"]}
    assert mappers["console-broker-audience"] == {
        "name": "console-broker-audience",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-audience-mapper",
        "config": {
            "included.custom.audience": "console-broker",
            "access.token.claim": "true",
            "id.token.claim": "false",
        },
    }


def test_console_client_absent_when_disabled():
    assert "console" not in _clients(_base_config())


def test_no_other_console_clients():
    ids = set(_clients(_config()))
    assert "console-provisioner" not in ids
    assert "console-knowledge" not in ids


def test_secret_env_and_vault_name():
    assert CLIENT_SECRET_ENV["console"] == "KC_CLIENT_SECRET_CONSOLE"
    assert KEYCLOAK_SECRET_NAMES["client_console"] == "console-oidc-client-secret"


def test_job_secret_refs_include_console_when_enabled():
    refs = _job_secret_refs(_config())
    assert refs["KC_CLIENT_SECRET_CONSOLE"] == "console-oidc-client-secret"


@pytest.mark.parametrize("name,admin", [("logins_on", None), ("admin_host", "set")])
def test_unchanged_when_console_off(name, admin):
    """Goldens rendered from the code before the console client existed
    (commit 576f4dd, via test_litellm_admin_host._config)."""
    config = _base_config(admin=None) if admin is None else _base_config()
    assert (
        render_realm_document(config) == (FIXTURES / f"realm_{name}.json").read_text()
    )
    golden_refs = json.loads((FIXTURES / f"realm_{name}_secret_refs.json").read_text())
    assert _job_secret_refs(config) == golden_refs
