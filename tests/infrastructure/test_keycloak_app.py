"""The Keycloak Container App and its realm-import Container Apps Job."""

import hashlib
from types import SimpleNamespace
from unittest.mock import patch

import pulumi
import pytest

from llmaven.infrastructure.config.schema import (
    KEYCLOAK_APP_SUFFIX,
    LLMavenConfig,
    container_app_name,
    is_reserved_realm_env,
    realm_job_name,
)
from llmaven.infrastructure.resources import container_apps, keycloak
from llmaven.infrastructure.resources.keycloak_realm import (
    CLIENT_SECRET_ENV,
    render_realm_document,
)
from llmaven.infrastructure.resources.secrets_manager import KEYCLOAK_SECRET_NAMES

from .test_edge_app import _isolated_mocks

AUTH_HOST = "auth.example.org"
KC_FQDN = "keycloak.internal.test"
IDENTITY = "identity-id"
KEYCLOAK_IMAGE = "ghcr.io/uw-ssec/llmoxie-keycloak:26.5.5@sha256:" + "b" * 64


@pytest.fixture(autouse=True)
def _mocks():
    with _isolated_mocks():
        yield


def _config(mlflow_login=True, litellm_login=True, **realm) -> LLMavenConfig:
    domains = [
        {"name": n, "certificate_name": f"cert-{i}"}
        for i, n in enumerate(("ai.example.org", "mlflow.example.org", AUTH_HOST))
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
                "hostname": "ai.example.org",
                "login": {"enabled": litellm_login},
            },
            "mlflow": {
                "hostname": "mlflow.example.org",
                "login": {"enabled": mlflow_login},
            },
            "keycloak": {
                "enabled": True,
                "image": KEYCLOAK_IMAGE,
                "hostname": AUTH_HOST,
                "realm": realm,
            },
        }
    )


KEY_VAULT = SimpleNamespace(
    properties=SimpleNamespace(vault_uri=pulumi.Output.from_input("https://kv/"))
)


def _create_app(config: LLMavenConfig) -> dict:
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
            keycloak.create_keycloak_app(
                resource_group_name="rg",
                location="westus2",
                container_env_id="env-id",
                key_vault=KEY_VAULT,
                config=config,
                managed_identity_id=IDENTITY,
            )
        kwargs = create_app.call_args.kwargs
        container = kwargs["template"].containers[0]
        return pulumi.Output.all(
            env={e.name: e.value for e in container.env},
            refs={e.name: e.secret_ref for e in container.env if e.secret_ref},
        ).apply(
            lambda r: captured.update(r, kwargs=kwargs, container=container, ap=policy)
        )

    run()
    return captured


def _create_job(config: LLMavenConfig) -> dict:
    captured: dict = {}

    @pulumi.runtime.test
    def run():
        with (
            patch.object(
                keycloak.azure_native.app,
                "Job",
                return_value=SimpleNamespace(name="job"),
            ) as create_job,
            patch.object(keycloak.pulumi, "export"),
            patch.object(keycloak.azure_native.keyvault, "AccessPolicy") as policy,
        ):
            keycloak.create_realm_job(
                resource_group_name="rg",
                location="westus2",
                container_env_id="env-id",
                key_vault=KEY_VAULT,
                config=config,
                keycloak_fqdn=pulumi.Output.from_input(KC_FQDN),
                managed_identity_id=IDENTITY,
            )
        kwargs = create_job.call_args.kwargs
        container = kwargs["template"].containers[0]
        secrets = kwargs["configuration"].secrets
        return pulumi.Output.all(
            env={e.name: e.value for e in container.env if e.value is not None},
            refs={e.name: e.secret_ref for e in container.env if e.secret_ref},
            secrets={s.name: s.value for s in secrets if s.value is not None},
        ).apply(
            lambda r: captured.update(r, kwargs=kwargs, container=container, ap=policy)
        )

    run()
    return captured


def test_keycloak_app_shape():
    result = _create_app(_config())
    kwargs = result["kwargs"]
    assert kwargs["container_app_name"] == container_app_name(
        "llmaven", "dev", KEYCLOAK_APP_SUFFIX
    )
    ingress = kwargs["configuration"].ingress
    assert ingress.external is False
    assert ingress.target_port == 8080
    scale = kwargs["template"].scale
    assert scale.min_replicas == scale.max_replicas == 1

    container = result["container"]
    assert container.args == ["start", "--optimized", "--cache=local"]
    assert container.image == KEYCLOAK_IMAGE
    assert (
        result["env"].items()
        >= {
            "KC_HOSTNAME": f"https://{AUTH_HOST}",
            "KC_HOSTNAME_BACKCHANNEL_DYNAMIC": "true",
            "KC_PROXY_HEADERS": "xforwarded",
            "KC_HTTP_ENABLED": "true",
            "KC_HEALTH_ENABLED": "true",
            "KC_BOOTSTRAP_ADMIN_USERNAME": "admin",
        }.items()
    )
    names = KEYCLOAK_SECRET_NAMES
    assert result["refs"] == {
        "KC_DB_URL": names["db_url"],
        "KC_DB_USERNAME": names["db_username"],
        "KC_DB_PASSWORD": names["db_password"],
        "KC_BOOTSTRAP_ADMIN_PASSWORD": names["admin_password"],
    }
    for probe in container.probes:
        assert probe.http_get.path == "/health/ready"
        assert probe.http_get.port == 9000
    startup = next(p for p in container.probes if p.type == "Startup")
    assert startup.failure_threshold >= 30


def test_realm_job_shape():
    config = _config(secret_refs={"EXTRA_SECRET": "extra-kv-secret"})
    result = _create_job(config)
    kwargs = result["kwargs"]
    assert kwargs["job_name"] == realm_job_name("llmaven", "dev")
    job_config = kwargs["configuration"]
    assert job_config.trigger_type == "Manual"
    assert job_config.replica_retry_limit == 0
    assert job_config.manual_trigger_config.parallelism == 1
    container = result["container"]
    assert container.image == config.keycloak.config_cli_image
    assert (
        result["env"].items()
        >= {
            "KEYCLOAK_URL": f"https://{KC_FQDN}",
            "KEYCLOAK_USER": "admin",
            "KEYCLOAK_AVAILABILITYCHECK_ENABLED": "true",
            # A fresh stack's first Keycloak boot (database migrations) can
            # take minutes; the config-cli default is 120s.
            "KEYCLOAK_AVAILABILITYCHECK_TIMEOUT": "300s",
            "IMPORT_FILES_LOCATIONS": "/config/realm.json",
            "IMPORT_VARSUBSTITUTION_ENABLED": "true",
            "IMPORT_REMOTESTATE_ENABLED": "true",
            "IMPORT_MANAGED_CLIENT": "no-delete",
            "IMPORT_MANAGED_ROLE": "no-delete",
            "IMPORT_MANAGED_IDENTITYPROVIDER": "no-delete",
            "IMPORT_MANAGED_GROUP": "no-delete",
            "IMPORT_MANAGED_CLIENTSCOPE": "no-delete",
        }.items()
    )

    names = KEYCLOAK_SECRET_NAMES
    expected = {
        "KEYCLOAK_PASSWORD": names["admin_password"],
        "KC_CLIENT_SECRET_MLFLOW_GATE": names["client_mlflow_gate"],
        "KC_CLIENT_SECRET_LLMAVEN_CLI": names["client_llmaven_cli"],
        "KC_CLIENT_SECRET_LITELLM_GATE": names["client_litellm_gate"],
        "KC_CLIENT_SECRET_LITELLM": names["client_litellm"],
        "EXTRA_SECRET": "extra-kv-secret",
    }
    assert result["refs"] == expected
    assert set(CLIENT_SECRET_ENV.values()) <= set(expected)
    kv = [s for s in job_config.secrets if s.key_vault_url is not None]
    assert {s.name for s in kv} == set(expected.values())
    assert all(s.identity == IDENTITY for s in kv)

    document = render_realm_document(config)
    assert result["secrets"] == {keycloak.REALM_SECRET: document}
    (volume,) = kwargs["template"].volumes
    assert volume.storage_type == "Secret"
    assert volume.secrets[0].secret_ref == keycloak.REALM_SECRET
    assert volume.secrets[0].path == "realm.json"
    (mount,) = container.volume_mounts
    assert mount.volume_name == volume.name
    assert mount.mount_path == "/config"
    assert (
        result["env"][keycloak.REALM_DIGEST_ENV]
        == hashlib.sha256(document.encode()).hexdigest()
    )


def test_realm_job_references_only_enabled_clients():
    result = _create_job(_config(litellm_login=False))
    assert set(result["refs"]) == {
        "KEYCLOAK_PASSWORD",
        "KC_CLIENT_SECRET_MLFLOW_GATE",
        "KC_CLIENT_SECRET_LLMAVEN_CLI",
    }


def test_realm_digest_changes_with_config():
    before = _create_job(_config())["env"][keycloak.REALM_DIGEST_ENV]
    after = _create_job(_config(display_name="Another"))["env"][
        keycloak.REALM_DIGEST_ENV
    ]
    assert before != after


def test_keycloak_uses_shared_identity_and_no_access_policy():
    app = _create_app(_config())
    job = _create_job(_config())
    assert app["kwargs"]["identity"].user_assigned_identities == [IDENTITY]
    assert job["kwargs"]["identity"].user_assigned_identities == [IDENTITY]
    assert all(
        s.identity == IDENTITY
        for s in app["kwargs"]["configuration"].secrets
        if s.key_vault_url is not None
    )
    app["ap"].assert_not_called()
    job["ap"].assert_not_called()


def test_every_env_the_realm_job_sets_is_reserved():
    # realm.secret_refs must not be able to override any of these.
    result = _create_job(_config())
    names = set(result["env"]) | set(result["refs"])
    assert names
    for name in names:
        assert is_reserved_realm_env(name), name
