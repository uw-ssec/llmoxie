"""Run the whole Pulumi program under mocks to check the knowledge hub wiring."""

from __future__ import annotations

import pulumi
import pulumi_azure_native as azure_native
import pytest

from llmaven.infrastructure import resources
from llmaven.infrastructure.config.schema import (
    KNOWLEDGE_HUB_APP_SUFFIX,
    KNOWLEDGE_HUB_DB,
    KNOWLEDGE_HUB_MASTER_KEY_ENV,
    CONSOLE_BROKER_APP_SUFFIX,
    console_job_name,
    container_app_name,
    knowledge_hub_storage_account_name,
    realm_job_name,
)
from llmaven.infrastructure.resources import console as console_module
from llmaven.infrastructure.resources import knowledge_hub

from .test_console_program import _console
from .test_edge_program import _run
from .test_keycloak_program import KEYCLOAK_INTERNAL
from .test_knowledge_hub_config import HUB_IMAGE

HUB = f"llmaven-dev-{KNOWLEDGE_HUB_APP_SUFFIX}"
BROKER = f"llmaven-dev-{CONSOLE_BROKER_APP_SUFFIX}"
HUB_URL = (
    f"https://{container_app_name('llmaven', 'dev', KNOWLEDGE_HUB_APP_SUFFIX)}"
    ".internal.env.test"
)
KEY = "ab" * 32
DB_JOB = console_job_name("llmaven", "dev", "db")
KNOW_JOB = console_job_name("llmaven", "dev", "know")
REALM_JOB = realm_job_name("llmaven", "dev")
MAIN_PASSWORD_SECRET = "kv-secret-okf-hub-main-okf-hub-db-password-dev"
HUB_CREATORS = (
    "create_knowledge_hub_secrets",
    "create_knowledge_hub_storage_account",
    "create_knowledge_hub_storage_secret",
    "create_knowledge_hub_storage",
    "create_knowledge_hub_app",
)


def _hub_config(enabled: bool = True) -> dict:
    config = _console()
    config["knowledge_hub"] = {"enabled": enabled, "image": HUB_IMAGE}
    return config


def _spied_run(tmp_path, monkeypatch, config: dict):
    """(resources, exports, apps, calls, opts): opts are each spied resource's options."""
    calls: dict = {}
    opts: dict = {}

    real_realm = resources.create_realm_job

    def realm_spy(*args, **kwargs):
        calls["create_realm_job"] = kwargs
        url = kwargs.get("knowledge_hub_url")
        if url is not None:
            pulumi.Output.from_input(url).apply(
                lambda u: calls.__setitem__("realm_hub_url", u)
            )
        return real_realm(*args, **kwargs)

    monkeypatch.setattr(resources, "create_realm_job", realm_spy)

    real_console = console_module.create_console

    def console_spy(*args, **kwargs):
        calls["create_console"] = kwargs
        result = calls["create_console.result"] = real_console(*args, **kwargs)
        return result

    monkeypatch.setattr(console_module, "create_console", console_spy)

    for name in HUB_CREATORS:
        real = getattr(knowledge_hub, name)

        def wrapper(*args, _real=real, _name=name, **kwargs):
            calls[_name] = kwargs
            result = calls[f"{_name}.result"] = _real(*args, **kwargs)
            return result

        monkeypatch.setattr(knowledge_hub, name, wrapper)

    # Job env values may be Outputs; keep each one's resolved value by the
    # identity of its EnvironmentVarArgs.
    env_values = calls["env_values"] = {}
    real_env = azure_native.app.EnvironmentVarArgs

    def env_spy(*args, **kwargs):
        env = real_env(*args, **kwargs)
        if kwargs.get("value") is not None:
            pulumi.Output.from_input(kwargs["value"]).apply(
                lambda v, _key=id(env): env_values.__setitem__(_key, v)
            )
        return env

    monkeypatch.setattr(azure_native.app, "EnvironmentVarArgs", env_spy)

    for module, cls in (
        (azure_native.dbforpostgresql, "Database"),
        (azure_native.storage, "BlobContainer"),
        (azure_native.storage, "StorageAccount"),
    ):
        real_cls = getattr(module, cls)

        def spy(resource_name, *args, _real=real_cls, **kwargs):
            opts[resource_name] = kwargs.get("opts")
            return _real(resource_name, *args, **kwargs)

        monkeypatch.setattr(module, cls, spy)

    run = _run(tmp_path, monkeypatch, **config)
    return (*run, calls, opts)


@pytest.fixture(scope="module")
def hub_on(tmp_path_factory):
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv(KNOWLEDGE_HUB_MASTER_KEY_ENV, KEY)
        return _spied_run(tmp_path_factory.mktemp("hub-on"), monkeypatch, _hub_config())


@pytest.fixture(scope="module")
def hub_off(tmp_path_factory):
    with pytest.MonkeyPatch.context() as monkeypatch:
        # The key is not needed, or read, with the hub off.
        monkeypatch.delenv(KNOWLEDGE_HUB_MASTER_KEY_ENV, raising=False)
        return _spied_run(
            tmp_path_factory.mktemp("hub-off"), monkeypatch, _hub_config(False)
        )


def _databases(created) -> set[str]:
    return {
        r.inputs.get("databaseName")
        for r in created
        if r.typ == "azure-native:dbforpostgresql:Database"
    }


def _env_names(job) -> set[str]:
    return {e.name for e in job["template"].containers[0].env}


def _env_value(job, name):
    [value] = [e.value for e in job["template"].containers[0].env if e.name == name]
    return value


def _refs(job) -> dict[str, str]:
    return {
        e.name: e.secret_ref for e in job["template"].containers[0].env if e.secret_ref
    }


def _resolved_env(job, name, calls):
    [env] = [e for e in job["template"].containers[0].env if e.name == name]
    return calls["env_values"][id(env)]


def _depends_on(opts) -> list[str]:
    return [d._name for d in opts.depends_on]


# --- the hub off: nothing changes ------------------------------------------


def test_hub_off_creates_nothing_of_the_hub(hub_off):
    created, exports, apps, calls, _ = hub_off
    assert "knowledge_hub_url" not in exports
    assert "console_knowledge_job" not in exports
    assert HUB not in apps
    assert not [r.name for r in created if "okf-hub" in r.name]
    for name in HUB_CREATORS:
        assert name not in calls, name


def test_hub_off_database_list_is_unchanged(hub_off):
    created = hub_off[0]
    assert KNOWLEDGE_HUB_DB not in _databases(created)
    assert _databases(created) == {
        "llmaven",
        "mlflow_db",
        "litellm_db",
        "keycloak_db",
        "console_db",
    }


def test_hub_off_realm_job_and_console_are_unchanged(hub_off):
    _, _, apps, calls, _ = hub_off
    assert calls["create_realm_job"].get("knowledge_hub_url") is None
    assert "KC_KNOWLEDGE_HUB_URL" not in _env_names(apps.jobs[REALM_JOB])
    console = calls["create_console"]
    assert console.get("knowledge_hub_job_secret_names") is None
    assert "OKF_HUB_DB_PASSWORD" not in _refs(apps.jobs[DB_JOB])
    assert not [n for n in _depends_on(console["opts"]) if "okf-hub" in n]


# --- the hub on -------------------------------------------------------------


def test_hub_on_creates_the_app_and_exports_its_url(hub_on):
    created, exports, apps, calls, _ = hub_on
    assert HUB in apps
    assert exports["knowledge_hub_url"] == HUB_URL
    assert exports["console_knowledge_job"] == console_job_name(
        "llmaven", "dev", "know"
    )
    for name in HUB_CREATORS:
        assert name in calls, name
    vaults = {r.name for r in created if r.typ == "azure-native:keyvault:Vault"}
    assert "okf-hub-vault-dev" in vaults


def test_one_hub_url_for_the_realm_job_the_app_and_the_export(hub_on):
    _, exports, apps, calls, _ = hub_on
    assert calls["realm_hub_url"] == HUB_URL
    assert "KC_KNOWLEDGE_HUB_URL" in _env_names(apps.jobs[REALM_JOB])
    assert apps[HUB]["resolved_env"]["OIDC_AUDIENCE"] == HUB_URL
    assert exports["knowledge_hub_url"] == HUB_URL


def test_every_hub_url_setting_is_the_same_value(hub_on):
    """The broker, the know job, the hub's audience and the realm job agree."""
    _, exports, apps, calls, _ = hub_on
    audience = apps[HUB]["resolved_env"]["OIDC_AUDIENCE"]
    assert audience == HUB_URL
    assert apps[BROKER]["resolved_env"]["KNOWLEDGE_HUB_URL"] == audience
    assert _resolved_env(apps.jobs[KNOW_JOB], "KNOWLEDGE_HUB_URL", calls) == audience
    assert (
        _resolved_env(apps.jobs[REALM_JOB], "KC_KNOWLEDGE_HUB_URL", calls) == audience
    )
    assert exports["knowledge_hub_url"] == audience


def test_hub_on_makes_no_role_assignment(hub_on):
    created = hub_on[0]
    assert not [r.name for r in created if "RoleAssignment" in r.typ]


def test_the_master_key_is_only_in_the_hub_vault(hub_on):
    """The key is in the deploy env, but the generic upload leaves it out."""
    created = hub_on[0]
    held = [
        r.name
        for r in created
        if r.typ == "azure-native:keyvault:Secret"
        and r.inputs["secretName"] == "okf-hub-master-key"
    ]
    # "hub" is the label create_knowledge_hub_secrets gives the hub vault's secrets.
    assert held == ["kv-secret-okf-hub-hub-okf-hub-master-key-dev"]


def test_the_hub_checks_tokens_against_keycloak(hub_on):
    env = hub_on[2][HUB]["resolved_env"]
    assert env["OIDC_ISSUER"] == "https://auth.example.org/realms/llmoxie"
    assert env["OIDC_JWKS_URL"] == (
        f"https://{KEYCLOAK_INTERNAL}/realms/llmoxie/protocol/openid-connect/certs"
    )


def test_hub_on_the_database_is_created_and_retained(hub_on):
    created, _, _, _, opts = hub_on
    assert KNOWLEDGE_HUB_DB in _databases(created)
    assert opts[f"postgres-db-{KNOWLEDGE_HUB_DB}-dev"].retain_on_delete is True


def test_turning_the_hub_off_keeps_its_data(hub_on):
    """The database, the storage account and the Blob container outlive the block."""
    opts = hub_on[4]
    assert opts[f"postgres-db-{KNOWLEDGE_HUB_DB}-dev"].retain_on_delete is True
    assert opts["okf-hub-storage-dev"].retain_on_delete is True
    assert opts["okf-hub-blob-dev"].retain_on_delete is True


def test_the_blob_container_is_in_the_hubs_own_account(hub_on):
    """Not the console's: turning the console off cannot delete the bundles."""
    created, _, _, calls, _ = hub_on
    name = knowledge_hub_storage_account_name("llmaven", "dev", "eastus")
    [account] = [
        r
        for r in created
        if r.typ == "azure-native:storage:StorageAccount"
        and r.name == "okf-hub-storage-dev"
    ]
    assert account.inputs["accountName"] == name
    assert name != console_module.console_storage_account_name(
        "llmaven", "dev", "eastus"
    )
    # The mocks echo no account name, so check the Output handed over.
    hub_account = calls["create_knowledge_hub_storage_account.result"]
    assert calls["create_knowledge_hub_storage"]["storage_account_name"] is (
        hub_account.name
    )
    assert calls["create_knowledge_hub_storage_secret"]["storage_account_name"] is (
        hub_account.name
    )
    # The account is waited for through its name, not through a console job.
    assert calls["create_knowledge_hub_storage"].get("opts") is None
    assert "storage_depends_on" not in calls["create_knowledge_hub_storage_secret"]


def test_the_console_db_job_creates_the_hub_role(hub_on):
    _, _, apps, calls, _ = hub_on
    db_job = apps.jobs[DB_JOB]
    assert _refs(db_job)["OKF_HUB_DB_PASSWORD"] == "okf-hub-db-password"
    assert calls["create_console"]["knowledge_hub_job_secret_names"] == {
        "OKF_HUB_DB_PASSWORD": "okf-hub-db-password"
    }
    # The job reads the password from the main vault, so it waits for it.
    assert MAIN_PASSWORD_SECRET in _depends_on(db_job["opts"])


def test_the_console_does_not_close_the_hub_database_itself(hub_on):
    """db_setup closes okf_hub after giving it to the okf_hub role."""
    others = _env_value(hub_on[2].jobs[DB_JOB], "CONSOLE_OTHER_DATABASES").split(",")
    assert KNOWLEDGE_HUB_DB not in others


def test_the_app_waits_for_its_secrets_and_its_container(hub_on):
    _, _, apps, calls, _ = hub_on
    waits = _depends_on(apps[HUB]["opts"])
    secrets = calls["create_knowledge_hub_secrets.result"]
    for resource in secrets.resources:
        assert resource._name in waits, resource._name
    assert calls["create_knowledge_hub_storage_secret.result"]._name in waits
    assert "okf-hub-blob-dev" in waits


def test_hub_on_without_the_master_key_fails(tmp_path, monkeypatch):
    monkeypatch.delenv(KNOWLEDGE_HUB_MASTER_KEY_ENV, raising=False)
    with pytest.raises(Exception, match=KNOWLEDGE_HUB_MASTER_KEY_ENV):
        _run(tmp_path, monkeypatch, **_hub_config())
