"""The knowledge hub's role and clients in the Keycloak realm, and the realm job."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pulumi
import pytest
from pydantic import ValidationError

from llmaven.infrastructure.config.schema import LLMavenConfig
from llmaven.infrastructure.resources import keycloak
from llmaven.infrastructure.resources.console_secrets import (
    KNOWLEDGE_SECRET,
    PROVISIONER_SECRET,
)
from llmaven.infrastructure.resources.keycloak import _job_secret_refs
from llmaven.infrastructure.resources.keycloak_realm import (
    CLIENT_SECRET_ENV,
    KNOWLEDGE_HUB_URL_ENV,
    KNOWLEDGE_READER_ORG,
    KNOWLEDGE_READER_ROLE,
    build_realm_document,
    render_realm_document,
)

from . import PINNED_KEYCLOAK_IMAGE  # noqa: F401
from .test_console_config import _config as _console_config
from .test_edge_app import _isolated_mocks
from .test_knowledge_hub_config import _hub_data

FIXTURES = Path(__file__).parent / "fixtures"
HUB_URL = "https://llmaven-dev-okf-hub.internal.example.azurecontainerapps.io"


def _hub_config() -> LLMavenConfig:
    return LLMavenConfig.model_validate(_hub_data())


def _clients(config) -> dict:
    return {c["clientId"]: c for c in build_realm_document(config).get("clients", [])}


def _users(config) -> dict:
    return {u["username"]: u for u in build_realm_document(config).get("users", [])}


def test_hub_off_the_realm_is_unchanged():
    """The golden is the console-on realm rendered at ca3332e, before the hub."""
    config = _console_config()
    assert (
        render_realm_document(config)
        == (FIXTURES / "realm_console_on.json").read_text()
    )
    doc = build_realm_document(config)
    assert {c["clientId"] for c in doc["clients"]} == {
        "litellm-gate",
        "litellm",
        "console",
    }
    assert KNOWLEDGE_READER_ROLE not in {r["name"] for r in doc["roles"]["realm"]}


def test_hub_on_role_clients_and_service_accounts():
    config = _hub_config()
    doc = build_realm_document(config)
    assert KNOWLEDGE_READER_ROLE in {r["name"] for r in doc["roles"]["realm"]}
    clients = _clients(config)
    for client_id in ("console-provisioner", "console-knowledge"):
        client = clients[client_id]
        assert client["serviceAccountsEnabled"] is True
        assert client["standardFlowEnabled"] is False
        assert client["directAccessGrantsEnabled"] is False
        assert client["publicClient"] is False
        assert client["secret"] == f"$(env:{CLIENT_SECRET_ENV[client_id]})"

    users = _users(config)
    provisioner = users["service-account-console-provisioner"]
    assert provisioner["serviceAccountClientId"] == "console-provisioner"
    assert provisioner["clientRoles"] == {"realm-management": ["manage-clients"]}
    knowledge = users["service-account-console-knowledge"]
    assert knowledge["serviceAccountClientId"] == "console-knowledge"
    assert knowledge["realmRoles"] == [KNOWLEDGE_READER_ROLE]

    mappers = {m["name"]: m for m in clients["console-knowledge"]["protocolMappers"]}
    audience = mappers["knowledge-hub-audience"]
    assert audience["protocolMapper"] == "oidc-audience-mapper"
    assert (
        audience["config"]["included.custom.audience"] == "$(env:KC_KNOWLEDGE_HUB_URL)"
    )
    org = mappers["organization"]
    assert org["protocolMapper"] == "oidc-hardcoded-claim-mapper"
    assert org["config"]["claim.name"] == "okf_org"
    assert org["config"]["claim.value"] == KNOWLEDGE_READER_ORG == "console_reader"
    assert org["config"]["access.token.claim"] == "true"
    assert org["config"]["id.token.claim"] == "false"
    assert org["config"]["userinfo.token.claim"] == "false"


def test_names_of_the_interface():
    assert CLIENT_SECRET_ENV["console-provisioner"] == (
        "KC_CLIENT_SECRET_CONSOLE_PROVISIONER"
    )
    assert CLIENT_SECRET_ENV["console-knowledge"] == (
        "KC_CLIENT_SECRET_CONSOLE_KNOWLEDGE"
    )
    assert KNOWLEDGE_HUB_URL_ENV == "KC_KNOWLEDGE_HUB_URL"
    assert KNOWLEDGE_READER_ROLE == "knowledge-reader"


def test_hub_on_the_job_gets_both_secrets():
    refs = _job_secret_refs(_hub_config())
    assert refs["KC_CLIENT_SECRET_CONSOLE_PROVISIONER"] == PROVISIONER_SECRET
    assert refs["KC_CLIENT_SECRET_CONSOLE_KNOWLEDGE"] == KNOWLEDGE_SECRET


def test_hub_off_the_job_has_neither_secret():
    refs = _job_secret_refs(_console_config())
    assert not [k for k in refs if k.startswith("KC_CLIENT_SECRET_CONSOLE_")]


@pytest.mark.parametrize("client_id", ["console-provisioner", "console-knowledge"])
def test_overrides_cannot_redefine_the_knowledge_clients(client_id):
    data = _hub_data()
    data["keycloak"]["realm"] = {"overrides": {"clients": [{"clientId": client_id}]}}
    with pytest.raises(ValidationError, match="redefines the stack's client"):
        LLMavenConfig.model_validate(data)


def _job_env(config: LLMavenConfig, **kwargs) -> dict:
    captured: dict = {}

    @pulumi.runtime.test
    def run():
        with (
            _isolated_mocks(),
            patch.object(
                keycloak.azure_native.app,
                "Job",
                return_value=SimpleNamespace(name="job"),
            ) as create_job,
            patch.object(keycloak.pulumi, "export"),
            patch.object(keycloak.azure_native.keyvault, "AccessPolicy"),
        ):
            keycloak.create_realm_job(
                resource_group_name="rg",
                location="westus2",
                container_env_id="env-id",
                key_vault=SimpleNamespace(
                    properties=SimpleNamespace(
                        vault_uri=pulumi.Output.from_input("https://kv/")
                    )
                ),
                config=config,
                keycloak_fqdn=pulumi.Output.from_input("keycloak.internal.test"),
                managed_identity_id="identity-id",
                **kwargs,
            )
        container = create_job.call_args.kwargs["template"].containers[0]
        return pulumi.Output.all(
            env={e.name: e.value for e in container.env if e.value is not None},
            refs={e.name: e.secret_ref for e in container.env if e.secret_ref},
        ).apply(captured.update)

    run()
    return captured


def test_hub_on_the_job_env_has_the_hub_url_and_secret_refs():
    result = _job_env(_hub_config(), knowledge_hub_url=HUB_URL)
    assert result["env"]["KC_KNOWLEDGE_HUB_URL"] == HUB_URL
    assert result["refs"]["KC_CLIENT_SECRET_CONSOLE_PROVISIONER"] == PROVISIONER_SECRET
    assert result["refs"]["KC_CLIENT_SECRET_CONSOLE_KNOWLEDGE"] == KNOWLEDGE_SECRET


def test_hub_off_the_job_env_has_no_hub_url():
    result = _job_env(_console_config(), knowledge_hub_url=HUB_URL)
    assert "KC_KNOWLEDGE_HUB_URL" not in result["env"]
