"""Keycloak's database and client secrets in Key Vault."""

import pulumi
import pytest

from llmaven.infrastructure.config.schema import LLMavenConfig
from llmaven.infrastructure.resources.secrets_manager import (
    KEYCLOAK_SECRET_NAMES,
    SecretsManager,
)

from . import PINNED_KEYCLOAK_IMAGE
from .test_edge_app import _isolated_mocks

HOST = "psql.example.postgres.database.azure.com"


class _Mocks(pulumi.runtime.Mocks):
    def __init__(self):
        self.resources: list[pulumi.runtime.MockResourceArgs] = []

    def new_resource(self, args):
        self.resources.append(args)
        outputs = dict(args.inputs)
        if args.typ == "random:index/randomPassword:RandomPassword":
            outputs["result"] = "p" * int(args.inputs["length"])
        return f"{args.name}-id", outputs

    def call(self, args):
        return {}


@pytest.fixture
def mocks():
    recorder = _Mocks()
    with _isolated_mocks(recorder):
        yield recorder


def _config(mlflow_login: bool, litellm_login: bool) -> LLMavenConfig:
    return LLMavenConfig.model_validate(
        {
            "networking": {
                "vnet_address_space": "172.16.0.0/16",
                "container_apps_subnet": "172.16.0.0/23",
                "postgres_subnet": "172.16.2.0/24",
            },
            "edge": {
                "enabled": True,
                "trusted_proxy_ips": ["100.100.0.0/17"],
                "custom_domains": [
                    {"name": "ai.example.org", "certificate_name": "cert-0"},
                    {"name": "mlflow.example.org", "certificate_name": "cert-1"},
                    {"name": "auth.example.org", "certificate_name": "cert-2"},
                ],
            },
            "keycloak": {
                "enabled": True,
                "image": PINNED_KEYCLOAK_IMAGE,
                "hostname": "auth.example.org",
            },
            "litellm": {
                "hostname": "ai.example.org",
                "login": {"enabled": litellm_login},
            },
            "mlflow": {
                "hostname": "mlflow.example.org",
                "login": {"enabled": mlflow_login},
            },
        }
    )


def _create(mocks, mlflow_login=True, litellm_login=True):
    manager = SecretsManager(
        resource_group_name=pulumi.Output.from_input("rg"),
        vault_name=pulumi.Output.from_input("kv"),
        config=_config(mlflow_login, litellm_login),
        environment="dev",
    )

    created = {}

    @pulumi.runtime.test
    def run():
        created.update(
            manager.create_keycloak_secrets(
                postgres_host=pulumi.Output.from_input(HOST),
                admin_login="llmaven_admin",
                admin_password=pulumi.Output.secret("admin-pw"),
                config=manager.config,
            )
        )

    run()
    return created, mocks.resources


def _secret_values(resources) -> dict[str, object]:
    return {
        r.inputs["secretName"]: r.inputs["properties"]["value"]
        for r in resources
        if r.typ == "azure-native:keyvault:Secret"
    }


def _plain(value):
    # A Pulumi secret input is wrapped with its signature key.
    if isinstance(value, dict):
        return value.get("value")
    return value


def test_keycloak_db_url_is_jdbc(mocks):
    _, resources = _create(mocks)
    values = _secret_values(resources)
    assert _plain(values["keycloak-db-url"]) == (
        f"jdbc:postgresql://{HOST}:5432/keycloak_db?sslmode=require"
    )
    assert _plain(values["keycloak-db-username"]) == "llmaven_admin"
    assert _plain(values["keycloak-db-password"]) == "admin-pw"


def test_generated_secrets_have_no_special_characters(mocks):
    _, resources = _create(mocks)
    passwords = [
        r for r in resources if r.typ == "random:index/randomPassword:RandomPassword"
    ]
    assert passwords
    for r in passwords:
        assert r.inputs["special"] is False
        assert r.inputs["length"] >= 32
    cookies = [r for r in passwords if "cookie" in r.name]
    assert len(cookies) == 2
    assert all(r.inputs["length"] == 32 for r in cookies)


def test_only_enabled_logins_get_secrets(mocks):
    result, resources = _create(mocks, mlflow_login=True, litellm_login=False)
    names = set(_secret_values(resources))
    assert not {n for n in names if n.startswith("keycloak-client-litellm")}
    assert "oauth2-proxy-cookie-litellm" not in names
    assert {
        "keycloak-admin-password",
        "keycloak-db-url",
        "keycloak-db-username",
        "keycloak-db-password",
        "keycloak-client-mlflow-gate",
        "keycloak-client-llmaven-cli",
        "oauth2-proxy-cookie-mlflow",
    } == names
    assert set(result) == names


def test_secret_names_do_not_collide_with_extract_entries(mocks):
    _, resources = _create(mocks)
    names = set(_secret_values(resources))
    assert not names & {"keycloak-token-url", "keycloak-cli-client-secret"}
    assert not set(KEYCLOAK_SECRET_NAMES.values()) & {
        "keycloak-token-url",
        "keycloak-cli-client-secret",
    }
