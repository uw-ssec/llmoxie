"""The knowledge hub's secrets, vault, Blob container and master-key check."""

import os
from pathlib import Path
from unittest.mock import patch

import click
import pulumi
import pytest
import yaml
from typer.testing import CliRunner

from llmaven.cli import app
from llmaven.deployment import validate as validate_mod
from llmaven.infrastructure.config.schema import (
    KNOWLEDGE_HUB_MASTER_KEY_ENV,
    LLMavenConfig,
    knowledge_hub_vault_name,
)
from llmaven.infrastructure.resources.console import (
    console_storage_account_name,
    create_console,
)
from llmaven.infrastructure.resources.console_secrets import (
    KNOWLEDGE_SECRET,
    PROVISIONER_SECRET,
    create_console_secrets,
)
from llmaven.infrastructure.resources.key_vault import create_key_vault
from llmaven.infrastructure.resources import knowledge_hub
from llmaven.infrastructure.resources.knowledge_hub import (
    create_knowledge_hub_secrets,
    create_knowledge_hub_storage,
    master_key_from_env,
)

from . import PINNED_KEYCLOAK_IMAGE  # noqa: F401
from .test_console_apps import _Mocks as _AppMocks
from .test_console_apps import _job, _refs
from .test_edge_app import _isolated_mocks
from .test_knowledge_hub_config import HUB_IMAGE, _hub_data

HOST = "psql.example.postgres.database.azure.com"
TENANT = "11111111-1111-1111-1111-111111111111"
DEPLOYER = "22222222-2222-2222-2222-222222222222"
SECRET_TYPE = "azure-native:keyvault:Secret"
KEY = "ab" * 32
ACCOUNT_KEY = "storage-account-key"


# --- master_key_from_env ---------------------------------------------------


def test_a_valid_master_key_is_returned():
    assert master_key_from_env({KNOWLEDGE_HUB_MASTER_KEY_ENV: KEY}) == KEY


@pytest.mark.parametrize(
    "value", [None, "", KEY[:-1], KEY + "a", "AB" * 32, "zz" * 32], ids=str
)
def test_a_missing_or_malformed_master_key_names_the_variable(value):
    env = {} if value is None else {KNOWLEDGE_HUB_MASTER_KEY_ENV: value}
    with pytest.raises(ValueError, match=KNOWLEDGE_HUB_MASTER_KEY_ENV):
        master_key_from_env(env)


# --- infra validate --------------------------------------------------------


def _write_config(tmp_path: Path, hub: bool) -> Path:
    stored = tmp_path / "litellm.yaml"
    stored.write_text("general_settings:\n  store_model_in_db: true\n")
    data = _hub_data()
    data["azure"] = {
        "subscription_id": "00000000-0000-0000-0000-000000000000",
        "tenant_id": "00000000-0000-0000-0000-000000000000",
        "resource_group": "rg-test",
    }
    data["monitoring"] = {"alerts": {"email_receivers": ["ops@llmoxie.test"]}}
    data["litellm"]["config_file"] = str(stored)
    data["litellm"]["key_vault_secret_refs"] = {
        "LITELLM_SALT_KEY": "litellm-salt-key"
    }
    data["knowledge_hub"]["enabled"] = hub
    path = tmp_path / "llmaven-config.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


# The only secret the config below asks for besides the hub's key.
BASELINE = ["LLMAVEN_SECRETS_LITELLM_SALT_KEY=fake-salt"]


def _validate(tmp_path, monkeypatch, hub, env_lines):
    env_lines = [*BASELINE, *env_lines]
    for name in list(os.environ):
        if name.startswith("LLMAVEN_SECRETS_"):
            monkeypatch.delenv(name)
    config = _write_config(tmp_path, hub)
    env_file = tmp_path / ".env.secrets"
    env_file.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    with (
        patch.object(validate_mod, "check_azure_cli", return_value=(True, "ok")),
        patch.object(
            validate_mod, "check_subscription_access", return_value=(True, "ok")
        ),
        patch.object(
            validate_mod, "check_required_providers", return_value=(True, "ok")
        ),
        patch.object(
            validate_mod,
            "check_config_for_hardcoded_secrets",
            return_value=(True, []),
        ),
    ):
        result = CliRunner().invoke(
            app,
            ["infra", "validate", "--config", str(config), "--env-file", str(env_file)],
        )
    return result, click.unstyle(result.output)


def test_validate_names_a_missing_master_key_when_the_hub_is_on(tmp_path, monkeypatch):
    result, output = _validate(tmp_path, monkeypatch, True, ["LLMAVEN_SECRETS_FOO=bar"])
    assert result.exit_code != 0
    assert KNOWLEDGE_HUB_MASTER_KEY_ENV in output


def test_validate_names_a_malformed_master_key_when_the_hub_is_on(
    tmp_path, monkeypatch
):
    line = f"{KNOWLEDGE_HUB_MASTER_KEY_ENV}={KEY.upper()}"
    result, output = _validate(tmp_path, monkeypatch, True, [line])
    assert result.exit_code != 0
    assert KNOWLEDGE_HUB_MASTER_KEY_ENV in output


def test_validate_accepts_a_good_master_key(tmp_path, monkeypatch):
    line = f"{KNOWLEDGE_HUB_MASTER_KEY_ENV}={KEY}"
    result, output = _validate(tmp_path, monkeypatch, True, [line])
    assert result.exit_code == 0, output


def test_validate_does_not_ask_for_the_key_when_the_hub_is_off(tmp_path, monkeypatch):
    result, output = _validate(tmp_path, monkeypatch, False, ["LLMAVEN_SECRETS_FOO=bar"])
    assert KNOWLEDGE_HUB_MASTER_KEY_ENV not in output
    assert result.exit_code == 0, output


# --- Pulumi resources ------------------------------------------------------


class _Recorder(_AppMocks):
    def new_resource(self, args):
        id_, outputs = super().new_resource(args)
        if args.typ == "azure-native:storage:BlobContainer":
            outputs["name"] = args.inputs["containerName"]
        return id_, outputs


@pytest.fixture
def mocks():
    recorder = _Recorder()
    with _isolated_mocks(recorder):
        yield recorder


def _create(mocks, hub=True):
    data = _hub_data()
    data["knowledge_hub"]["enabled"] = hub
    config = LLMavenConfig.model_validate(data)
    project, env = config.project.name, config.project.environment
    out = {}

    @pulumi.runtime.test
    def run():
        rg = pulumi.Output.from_input("rg")
        main_vault = create_key_vault(
            resource_group_name=rg,
            location="westus2",
            tenant_id=TENANT,
            config=config,
            tags={},
            deployer_object_id=DEPLOYER,
        )
        out["console"] = create_console_secrets(
            config=config,
            resource_group_name=rg,
            location="westus2",
            tenant_id=TENANT,
            deployer_object_id=DEPLOYER,
            main_vault=main_vault,
            postgres_host=pulumi.Output.from_input(HOST),
            admin_password=pulumi.Output.secret("server-admin-password"),
            mail_connection_string=pulumi.Output.secret("endpoint=acs"),
        )
        if hub:
            out["hub"] = create_knowledge_hub_secrets(
                config=config,
                resource_group_name=rg,
                location="westus2",
                tenant_id=TENANT,
                deployer_object_id=DEPLOYER,
                main_vault=main_vault,
                postgres_host=pulumi.Output.from_input(HOST),
                storage_account_name=console_storage_account_name(
                    project, env, "westus2"
                ),
                master_key=KEY,
            )
            out["container"] = create_knowledge_hub_storage(
                config=config,
                resource_group_name=rg,
                storage_account_name=console_storage_account_name(
                    project, env, "westus2"
                ),
                tags={},
            )

    run()
    return out, config, mocks.resources


def _plain(value):
    return value.get("value") if isinstance(value, dict) else value


def _main_secrets(resources):
    return {
        r.inputs["secretName"]: r
        for r in resources
        if r.typ == SECRET_TYPE
        and r.name.startswith(("kv-secret-console-main-", "kv-secret-okf-hub-main-"))
    }


def _secrets_in(resources, vault_name):
    return {
        r.inputs["secretName"]: r
        for r in resources
        if r.typ == SECRET_TYPE and r.inputs["vaultName"] == vault_name
    }


def _value(secret):
    return _plain(secret.inputs["properties"]["value"])


def test_the_hub_vault_has_exactly_the_hub_identity_and_the_deployer(mocks):
    out, config, resources = _create(mocks)
    name = knowledge_hub_vault_name(config.project.name, config.project.environment)
    (vault,) = [
        r
        for r in resources
        if r.typ == "azure-native:keyvault:Vault" and r.inputs["vaultName"] == name
    ]
    policies = vault.inputs["properties"]["accessPolicies"]
    assert len(policies) == 2
    identity = out["hub"].identity
    by_object = {p["objectId"]: p for p in policies}
    assert by_object[f"{identity._name}-principal"]["permissions"] == {
        "secrets": ["get", "list"]
    }
    assert "set" in by_object[DEPLOYER]["permissions"]["secrets"]
    assert vault.inputs["properties"]["enableRbacAuthorization"] is False


def test_the_hub_vault_holds_its_three_secrets(mocks):
    out, config, resources = _create(mocks)
    name = knowledge_hub_vault_name(config.project.name, config.project.environment)
    held = _secrets_in(resources, name)
    assert out["hub"].secret_names == {
        "VAULT_MASTER_KEY_HEX": "okf-hub-master-key",
        "DATABASE_URL": "okf-hub-database-url",
        "AZURE_STORAGE_CONNECTION_STRING": "okf-hub-storage-connection",
    }
    assert set(held) == set(out["hub"].secret_names.values())
    assert _value(held["okf-hub-master-key"]) == KEY


def test_the_database_url_names_the_role_and_database(mocks):
    out, config, resources = _create(mocks)
    name = knowledge_hub_vault_name(config.project.name, config.project.environment)
    url = _value(_secrets_in(resources, name)["okf-hub-database-url"])
    assert url.startswith("postgresql://okf_hub:")
    assert url.endswith(f"@{HOST}:5432/okf_hub?sslmode=verify-full&sslrootcert=system")


def test_the_connection_string_uses_the_console_storage_account(mocks):
    out, config, resources = _create(mocks)
    name = knowledge_hub_vault_name(config.project.name, config.project.environment)
    account = console_storage_account_name(
        config.project.name, config.project.environment, "westus2"
    )
    conn = _value(_secrets_in(resources, name)["okf-hub-storage-connection"])
    assert conn == (
        "DefaultEndpointsProtocol=https;"
        f"AccountName={account};AccountKey={ACCOUNT_KEY};"
        "EndpointSuffix=core.windows.net"
    )


def test_the_db_password_is_in_the_main_vault_too(mocks):
    out, config, resources = _create(mocks)
    main = _main_secrets(resources)
    assert out["hub"].job_secret_names == {"OKF_HUB_DB_PASSWORD": "okf-hub-db-password"}
    assert "okf-hub-db-password" in main
    url = _value(
        _secrets_in(
            resources,
            knowledge_hub_vault_name(config.project.name, config.project.environment),
        )["okf-hub-database-url"]
    )
    password = _value(main["okf-hub-db-password"])
    assert f"okf_hub:{password}@" in url


def test_the_blob_container_is_private_and_retained():
    config = LLMavenConfig.model_validate(_hub_data())
    with patch.object(knowledge_hub.azure_native.storage, "BlobContainer") as blob:
        create_knowledge_hub_storage(config, "rg", "acct", {})
    kwargs = blob.call_args.kwargs
    assert kwargs["container_name"] == "okf-hub"
    assert kwargs["account_name"] == "acct"
    assert kwargs["public_access"] == "None"
    assert kwargs["opts"].retain_on_delete is True


def test_the_client_secrets_go_to_the_main_and_broker_vaults(mocks):
    out, config, resources = _create(mocks)
    cs = out["console"]
    assert cs.provisioner_secret_name == PROVISIONER_SECRET
    assert cs.knowledge_secret_name == KNOWLEDGE_SECRET
    project, env = config.project.name, config.project.environment
    from llmaven.infrastructure.config.schema import console_vault_name

    main = _main_secrets(resources)
    broker = _secrets_in(resources, console_vault_name(project, env, "broker"))
    web = _secrets_in(resources, console_vault_name(project, env, "web"))
    for name in (PROVISIONER_SECRET, KNOWLEDGE_SECRET):
        assert _value(main[name]) == _value(broker[name])
        assert name not in web
    assert _value(main[PROVISIONER_SECRET]) != _value(main[KNOWLEDGE_SECRET])


def test_the_client_secrets_are_absent_with_the_hub_off(mocks):
    out, config, resources = _create(mocks, hub=False)
    cs = out["console"]
    assert cs.provisioner_secret_name is None and cs.knowledge_secret_name is None
    names = {r.inputs["secretName"] for r in resources if r.typ == SECRET_TYPE}
    assert PROVISIONER_SECRET not in names and KNOWLEDGE_SECRET not in names


def test_the_db_job_reads_the_extra_main_vault_secrets(mocks):
    from types import SimpleNamespace

    data = _hub_data()
    config = LLMavenConfig.model_validate(data)
    extra = {"OKF_HUB_DB_PASSWORD": "okf-hub-db-password"}

    @pulumi.runtime.test
    def run():
        rg = pulumi.Output.from_input("rg")
        main_vault = create_key_vault(
            resource_group_name=rg,
            location="westus2",
            tenant_id=TENANT,
            config=config,
            tags={},
            deployer_object_id=DEPLOYER,
        )
        cs = create_console_secrets(
            config=config,
            resource_group_name=rg,
            location="westus2",
            tenant_id=TENANT,
            deployer_object_id=DEPLOYER,
            main_vault=main_vault,
            postgres_host=pulumi.Output.from_input(HOST),
            admin_password=pulumi.Output.secret("server-admin-password"),
            mail_connection_string=pulumi.Output.secret("endpoint=acs"),
        )
        create_console(
            config=config,
            resource_group_name=rg,
            location="westus2",
            container_env=SimpleNamespace(
                id=pulumi.Output.from_input("env-id"),
                name=pulumi.Output.from_input("containerenv"),
            ),
            main_vault=main_vault,
            shared_identity_id="shared-identity-id",
            secrets=cs,
            sender_address="console@mail.example.org",
            litellm_fqdn=pulumi.Output.from_input("litellm.internal.test"),
            keycloak_fqdn=pulumi.Output.from_input("keycloak.internal.test"),
            postgres_host=pulumi.Output.from_input(HOST),
            tags={},
            knowledge_hub_job_secret_names=extra,
        )

    run()
    job = _job(mocks.resources, config, "db")
    assert _refs(job)["OKF_HUB_DB_PASSWORD"] == "okf-hub-db-password"
    assert "okf-hub-db-password" in {
        s["name"] for s in job.inputs["configuration"]["secrets"]
    }
    assert "PGPASSWORD" in _refs(job)
