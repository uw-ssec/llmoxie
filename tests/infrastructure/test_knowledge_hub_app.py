"""The knowledge hub's URL and its Container App."""

import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pulumi

from llmaven.infrastructure.config.schema import (
    KNOWLEDGE_HUB_APP_SUFFIX,
    KNOWLEDGE_HUB_PORT,
    LLMavenConfig,
    container_app_name,
)
from llmaven.infrastructure.resources import container_apps, knowledge_hub
from llmaven.infrastructure.resources.knowledge_hub import (
    create_knowledge_hub_app,
    hub_url,
)

from .test_edge_app import _isolated_mocks
from .test_knowledge_hub_config import HUB_IMAGE, _hub_data

DOMAIN = "x.westus2.azurecontainerapps.io"
KEYCLOAK_INTERNAL = "keycloak.internal.test"
SECRET_NAMES = {
    "VAULT_MASTER_KEY_HEX": "okf-hub-master-key",
    "DATABASE_URL": "okf-hub-database-url",
    "AZURE_STORAGE_CONNECTION_STRING": "okf-hub-storage-connection",
}
GRANTS = (
    '[{"bundle":"orgs/oidc-{actor}","access":"write"},'
    '{"role":"knowledge-reader","bundle":"orgs/*","access":"read"}]'
)


def _env():
    return SimpleNamespace(
        id=pulumi.Output.from_input("env-id"),
        name=pulumi.Output.from_input("containerenv"),
        default_domain=pulumi.Output.from_input(DOMAIN),
    )


def _secrets():
    return SimpleNamespace(
        identity=SimpleNamespace(id=pulumi.Output.from_input("hub-identity-id")),
        vault=SimpleNamespace(
            properties=SimpleNamespace(
                vault_uri=pulumi.Output.from_input("https://kv-hub/")
            )
        ),
        secret_names=dict(SECRET_NAMES),
        resources=[],
    )


def test_hub_url_is_the_apps_internal_fqdn():
    captured = {}

    @pulumi.runtime.test
    def run():
        return hub_url(_env(), "llmaven", "dev").apply(
            lambda url: captured.update(url=url)
        )

    with _isolated_mocks():
        run()
    name = container_app_name("llmaven", "dev", KNOWLEDGE_HUB_APP_SUFFIX)
    assert name == "llmaven-dev-okf-hub-dev"
    assert captured["url"] == f"https://{name}.internal.{DOMAIN}"
    assert captured["url"] == (
        "https://llmaven-dev-okf-hub-dev.internal.x.westus2.azurecontainerapps.io"
    )


def _create_app():
    """Run the creator against a stubbed helper; return its kwargs, env resolved."""
    config = LLMavenConfig.model_validate(_hub_data())
    captured: dict = {"secrets": _secrets()}

    @pulumi.runtime.test
    def run():
        with patch.object(
            knowledge_hub, "create_container_app_with_key_vault_secrets"
        ) as create:
            create_knowledge_hub_app(
                config=config,
                resource_group_name="rg",
                location="westus2",
                container_env=_env(),
                secrets=captured["secrets"],
                keycloak_fqdn=pulumi.Output.from_input(KEYCLOAK_INTERNAL),
                tags={},
            )
        kwargs = captured["kwargs"] = create.call_args.kwargs
        return pulumi.Output.all(**kwargs["env_vars"]).apply(
            lambda env: captured.update(env=env)
        )

    with _isolated_mocks():
        run()
    captured["kwargs"]["_secrets"] = captured["secrets"]
    return config, captured["kwargs"], captured["env"]


def test_the_app_is_internal_on_port_7878_with_one_replica():
    config, kwargs, _ = _create_app()
    assert kwargs["app_name"] == f"llmaven-dev-{KNOWLEDGE_HUB_APP_SUFFIX}"
    assert kwargs["enable_ingress"] is True
    assert kwargs["ingress_external"] is False
    assert kwargs["container_port"] == KNOWLEDGE_HUB_PORT == 7878
    assert kwargs["health_probe_port"] == 7878
    assert kwargs["health_probe_path"] == "/healthz"
    assert kwargs["min_replicas"] == kwargs["max_replicas"] == 1
    assert kwargs["container_image"] == config.knowledge_hub.image == HUB_IMAGE
    assert kwargs["cpu"] == config.knowledge_hub.cpu
    assert kwargs["memory"] == config.knowledge_hub.memory
    assert kwargs["environment"] == "dev"


def test_the_app_runs_as_the_hub_identity_and_reads_its_vault():
    _, kwargs, _ = _create_app()
    secrets = kwargs["_secrets"]
    assert kwargs["managed_identity_id"] is secrets.identity.id
    assert kwargs["key_vault_uri"] is secrets.vault.properties.vault_uri
    assert kwargs["key_vault_secret_refs"] == SECRET_NAMES


def test_the_app_settings():
    _, _, env = _create_app()
    url = f"https://{container_app_name('llmaven', 'dev', 'okf-hub')}.internal.{DOMAIN}"
    assert env == {
        "OIDC_ISSUER": "https://auth.example.org/realms/llmoxie",
        "OIDC_JWKS_URL": (
            f"https://{KEYCLOAK_INTERNAL}/realms/llmoxie/protocol/openid-connect/certs"
        ),
        "OIDC_AUDIENCE": url,
        "OIDC_GRANTS": GRANTS,
        "BLOB_CONTAINER": "okf-hub",
        "PORT": "7878",
    }
    assert json.loads(env["OIDC_GRANTS"]) == [
        {"bundle": "orgs/oidc-{actor}", "access": "write"},
        {"role": "knowledge-reader", "bundle": "orgs/*", "access": "read"},
    ]


def test_the_secrets_are_only_the_three_vault_references():
    _, kwargs, env = _create_app()
    assert set(kwargs["key_vault_secret_refs"]) == {
        "VAULT_MASTER_KEY_HEX",
        "DATABASE_URL",
        "AZURE_STORAGE_CONNECTION_STRING",
    }
    assert not set(kwargs["key_vault_secret_refs"]) & set(env)
    assert not kwargs.get("inline_secrets")
    assert not kwargs.get("sidecars")


def test_the_probes_check_healthz_and_allow_two_minutes_to_start():
    """Container Apps ignores the image's HEALTHCHECK, so the app sets probes."""
    config = LLMavenConfig.model_validate(_hub_data())
    with (
        patch.object(
            container_apps.azure_native.app,
            "ContainerApp",
            return_value=SimpleNamespace(name="app", configuration=Mock()),
        ) as create_app,
        patch.object(container_apps.pulumi, "export"),
    ):
        create_knowledge_hub_app(
            config=config,
            resource_group_name="rg",
            location="westus2",
            container_env=SimpleNamespace(
                id="env-id", name="containerenv", default_domain=DOMAIN
            ),
            secrets=SimpleNamespace(
                identity=SimpleNamespace(id="hub-identity-id"),
                vault=SimpleNamespace(properties=SimpleNamespace(vault_uri=Mock())),
                secret_names=dict(SECRET_NAMES),
                resources=[],
            ),
            keycloak_fqdn=KEYCLOAK_INTERNAL,
            tags={},
        )
    probes = {
        p.type: p for p in create_app.call_args.kwargs["template"].containers[0].probes
    }
    assert set(probes) == {"Liveness", "Readiness", "Startup"}
    for probe in probes.values():
        assert probe.http_get.path == "/healthz"
        assert probe.http_get.port == 7878
    startup = probes["Startup"]
    budget = (startup.initial_delay_seconds or 0) + (
        startup.period_seconds * startup.failure_threshold
    )
    assert budget >= 120
