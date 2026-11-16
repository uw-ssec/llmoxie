"""The console's identities, per-app vaults and secrets."""

import pulumi
import pulumi_azure_native as azure_native
import pytest

from llmaven.infrastructure.config.schema import console_vault_name
from llmaven.infrastructure.resources.console_secrets import create_console_secrets
from llmaven.infrastructure.resources.key_vault import create_key_vault
from llmaven.infrastructure.resources.secrets_manager import KEYCLOAK_SECRET_NAMES

from .test_console_config import _config
from .test_edge_app import _isolated_mocks

HOST = "psql.example.postgres.database.azure.com"
TENANT = "11111111-1111-1111-1111-111111111111"
DEPLOYER = "22222222-2222-2222-2222-222222222222"
SECRET_TYPE = "azure-native:keyvault:Secret"
RANDOM_TYPE = "random:index/randomPassword:RandomPassword"


class _Mocks(pulumi.runtime.Mocks):
    def __init__(self):
        self.resources: list[pulumi.runtime.MockResourceArgs] = []

    def new_resource(self, args):
        self.resources.append(args)
        outputs = dict(args.inputs)
        if args.typ == RANDOM_TYPE:
            outputs["result"] = f"{args.name}-value"
        if args.typ == "azure-native:managedidentity:UserAssignedIdentity":
            outputs["principalId"] = f"{args.name}-principal"
        if args.typ == "azure-native:keyvault:Vault":
            outputs["name"] = args.inputs.get("vaultName", args.name)
        return f"{args.name}-id", outputs

    def call(self, args):
        return {}


@pytest.fixture
def mocks():
    recorder = _Mocks()
    with _isolated_mocks(recorder):
        yield recorder


def _create(mocks, deployer=DEPLOYER):
    config = _config()
    out = {}

    @pulumi.runtime.test
    def run():
        main_vault = create_key_vault(
            resource_group_name=pulumi.Output.from_input("rg"),
            location="westus2",
            tenant_id=TENANT,
            config=config,
            tags={},
            deployer_object_id=deployer,
        )
        out["secrets"] = create_console_secrets(
            config=config,
            resource_group_name=pulumi.Output.from_input("rg"),
            location="westus2",
            tenant_id=TENANT,
            deployer_object_id=deployer,
            main_vault=main_vault,
            postgres_host=pulumi.Output.from_input(HOST),
            mail_connection_string=pulumi.Output.secret("endpoint=acs"),
        )

    run()
    return out["secrets"], config, mocks.resources


def _vaults(resources):
    return {
        r.inputs["vaultName"]: r for r in resources if r.typ.endswith(":keyvault:Vault")
    }


def _secrets_in(resources, vault_name):
    return {
        r.inputs["secretName"]: r
        for r in resources
        if r.typ == SECRET_TYPE and r.inputs["vaultName"] == vault_name
    }


def _plain(value):
    return value.get("value") if isinstance(value, dict) else value


def _policies(vault):
    return vault.inputs["properties"]["accessPolicies"]


def test_vault_names_match_console_vault_name(mocks):
    _, config, resources = _create(mocks)
    project, env = config.project.name, config.project.environment
    names = set(_vaults(resources))
    assert console_vault_name(project, env, "web") in names
    assert console_vault_name(project, env, "broker") in names


def test_each_vault_has_exactly_its_identity_and_the_deployer(mocks):
    cs, config, resources = _create(mocks)
    project, env = config.project.name, config.project.environment
    for which, identity in (("web", cs.web_identity), ("broker", cs.broker_identity)):
        vault = _vaults(resources)[console_vault_name(project, env, which)]
        props = vault.inputs["properties"]
        assert props["enableRbacAuthorization"] is False
        policies = _policies(vault)
        assert len(policies) == 2
        by_object = {p["objectId"]: p for p in policies}
        own = by_object[f"managed-identity-{project}-{env}-console-{which}-principal"]
        assert own["permissions"] == {"secrets": ["get", "list"]}
        assert own["tenantId"] == TENANT
        deployer = by_object[DEPLOYER]
        assert "set" in deployer["permissions"]["secrets"]
        kv = config.security.key_vault
        assert props["enableSoftDelete"] == kv.enable_soft_delete
        assert props["softDeleteRetentionInDays"] == kv.soft_delete_retention_days
        assert props.get("enablePurgeProtection") == kv.enable_purge_protection


def test_no_deployer_policy_without_object_id(mocks):
    _, config, resources = _create(mocks, deployer=None)
    web = _vaults(resources)[
        console_vault_name(config.project.name, config.project.environment, "web")
    ]
    assert len(_policies(web)) == 1


def test_web_vault_holds_only_web_secrets(mocks):
    _, config, resources = _create(mocks)
    web = console_vault_name(config.project.name, config.project.environment, "web")
    assert set(_secrets_in(resources, web)) == {
        "console-oidc-client-secret",
        "console-broker-caller-secret",
        "console-web-db-url",
    }


def test_broker_vault_holds_only_broker_secrets(mocks):
    _, config, resources = _create(mocks)
    broker = console_vault_name(
        config.project.name, config.project.environment, "broker"
    )
    assert set(_secrets_in(resources, broker)) == {
        "console-broker-caller-secret",
        "console-broker-db-url",
        "console-mail-connection",
    }


def test_main_vault_gets_the_client_secret_and_db_passwords(mocks):
    cs, _, resources = _create(mocks)
    main = [
        r
        for r in resources
        if r.typ == SECRET_TYPE and r.name.startswith("kv-secret-console-main-")
    ]
    names = {r.inputs["secretName"] for r in main}
    assert names == {
        KEYCLOAK_SECRET_NAMES["client_console"],
        "console-web-db-password",
        "console-broker-db-password",
    }
    assert cs.job_secret_names == {
        "CONSOLE_WEB_DB_PASSWORD": "console-web-db-password",
        "CONSOLE_BROKER_DB_PASSWORD": "console-broker-db-password",
    }


def test_env_var_maps(mocks):
    cs, _, _ = _create(mocks)
    assert cs.web_secret_names == {
        "CONSOLE_WEB_DATABASE_URL": "console-web-db-url",
        "CONSOLE_BROKER_CALLER_SECRET": "console-broker-caller-secret",
        "OIDC_CLIENT_SECRET": "console-oidc-client-secret",
    }
    assert cs.broker_secret_names == {
        "CONSOLE_BROKER_DATABASE_URL": "console-broker-db-url",
        "CONSOLE_BROKER_CALLER_SECRET": "console-broker-caller-secret",
        "ACS_CONNECTION_STRING": "console-mail-connection",
    }


def test_shared_secrets_have_one_value_in_both_places(mocks):
    _, config, resources = _create(mocks)
    project, env = config.project.name, config.project.environment
    web = _secrets_in(resources, console_vault_name(project, env, "web"))
    broker = _secrets_in(resources, console_vault_name(project, env, "broker"))
    main = {
        r.inputs["secretName"]: r
        for r in resources
        if r.typ == SECRET_TYPE and r.name.startswith("kv-secret-console-main-")
    }

    def value(r):
        return _plain(r.inputs["properties"]["value"])

    assert value(web["console-broker-caller-secret"]) == value(
        broker["console-broker-caller-secret"]
    )
    assert value(web["console-oidc-client-secret"]) == value(
        main["console-oidc-client-secret"]
    )


def test_database_urls_use_role_password_and_host(mocks):
    _, config, resources = _create(mocks)
    project, env = config.project.name, config.project.environment
    web = _secrets_in(resources, console_vault_name(project, env, "web"))
    broker = _secrets_in(resources, console_vault_name(project, env, "broker"))
    web_url = _plain(web["console-web-db-url"].inputs["properties"]["value"])
    broker_url = _plain(broker["console-broker-db-url"].inputs["properties"]["value"])
    assert web_url.startswith("postgresql://console_web:")
    assert web_url.endswith(f"@{HOST}:5432/console_db?sslmode=require")
    assert broker_url.startswith("postgresql://console_broker:")
    assert broker_url.endswith(f"@{HOST}:5432/console_db?sslmode=require")
    assert (
        _plain(broker["console-mail-connection"].inputs["properties"]["value"])
        == "endpoint=acs"
    )


def test_generated_values_are_url_safe_and_long(mocks):
    _, _, resources = _create(mocks)
    passwords = [r for r in resources if r.typ == RANDOM_TYPE and "console" in r.name]
    assert len(passwords) == 4
    for r in passwords:
        assert r.inputs["special"] is False
        assert r.inputs["length"] >= 32


def test_secret_resource_names_are_unique(mocks):
    _, _, resources = _create(mocks)
    names = [r.name for r in resources]
    assert len(names) == len(set(names))


def test_no_role_assignments_or_access_policy_resources(mocks):
    _, _, resources = _create(mocks)
    types = [r.typ for r in resources]
    assert not any(
        t.startswith("azure-native:authorization")
        or t == "azure-native:keyvault:AccessPolicy"
        for t in types
    )


def test_no_secret_value_is_exported(mocks, monkeypatch):
    exported = []
    monkeypatch.setattr(pulumi, "export", lambda name, value: exported.append(name))
    _create(mocks)
    # Only the main vault's own name and URI are exported, never a console value.
    assert [n for n in exported if not n.startswith("key_vault_")] == []


def test_every_console_secret_value_is_a_pulumi_secret(mocks, monkeypatch):
    # The mock monitor strips secret markers from resource inputs, so look at the
    # value where the writer hands it to the Secret's properties.
    values = []
    real = azure_native.keyvault.SecretPropertiesArgs

    def record(**kwargs):
        values.append(kwargs["value"])
        return real(**kwargs)

    monkeypatch.setattr(azure_native.keyvault, "SecretPropertiesArgs", record)
    _create(mocks)
    assert len(values) == 9
    flags = []

    @pulumi.runtime.test
    def check():
        async def gather():
            flags.extend([await v.is_secret() for v in values])

        return gather()

    check()
    assert flags == [True] * 9


def test_main_vault_access_policy_is_unchanged(mocks):
    """Characterisation of the main vault's policy, from before the helper."""
    _, config, resources = _create(mocks)
    main = [
        r
        for r in resources
        if r.typ.endswith(":keyvault:Vault") and r.name.startswith("key-vault-")
    ][0]
    assert _policies(main) == [
        {
            "tenantId": TENANT,
            "objectId": DEPLOYER,
            "permissions": {
                "secrets": [
                    "get",
                    "list",
                    "set",
                    "delete",
                    "recover",
                    "backup",
                    "restore",
                ],
                "keys": [
                    "get",
                    "list",
                    "create",
                    "delete",
                    "recover",
                    "wrapKey",
                    "unwrapKey",
                    "sign",
                    "verify",
                    "backup",
                    "restore",
                ],
            },
        }
    ]
