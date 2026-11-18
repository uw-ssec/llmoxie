"""The console's Container Apps, the file share they use, and its jobs."""

import json
from types import SimpleNamespace

import pulumi
import pulumi_azure_native as azure_native
import pytest

from llmaven.infrastructure.config.schema import (
    LLMavenConfig,
    CONSOLE_BROKER_APP_SUFFIX,
    CONSOLE_DB,
    CONSOLE_WEB_APP_SUFFIX,
    console_job_name,
    console_vault_name,
    container_app_name,
)
from llmaven.infrastructure.resources import console
from llmaven.infrastructure.resources.console import (
    console_storage_account_name,
    create_console,
)
from llmaven.infrastructure.resources.console_secrets import create_console_secrets
from llmaven.infrastructure.resources.key_vault import create_key_vault

from .test_console_config import CONSOLE_HOST, _config
from .test_knowledge_hub_config import _hub_data
from .test_edge_app import _isolated_mocks
from .test_litellm_admin_host import ADMIN, KEYCLOAK_HOST
from .test_edge_config import LITELLM_HOST

PG_HOST = "psql.example.postgres.database.azure.com"
LITELLM_FQDN = "litellm.internal.test"
KC_FQDN = "keycloak.internal.test"
SHARED_IDENTITY = "shared-identity-id"
SENDER = "console@mail.example.org"
ACCOUNT_KEY = "storage-account-key"
TENANT = "11111111-1111-1111-1111-111111111111"
DEPLOYER = "22222222-2222-2222-2222-222222222222"
APP_TYPE = "azure-native:app:ContainerApp"
JOB_TYPE = "azure-native:app:Job"
ENV_STORAGE_TYPE = "azure-native:app:ManagedEnvironmentsStorage"
MASTER_KEY_SECRET = "litellm-master-key"
PG_ADMIN_SECRET = "console-db-admin-password"


class _Mocks(pulumi.runtime.Mocks):
    def __init__(self):
        self.resources: list[pulumi.runtime.MockResourceArgs] = []

    def new_resource(self, args):
        self.resources.append(args)
        outputs = dict(args.inputs)
        if args.typ == "random:index/randomPassword:RandomPassword":
            outputs["result"] = f"{args.name}-value"
        if args.typ == "azure-native:managedidentity:UserAssignedIdentity":
            outputs["principalId"] = f"{args.name}-principal"
        if args.typ == "azure-native:keyvault:Vault":
            name = args.inputs["vaultName"]
            outputs["name"] = name
            outputs["properties"] = {
                **args.inputs["properties"],
                "vaultUri": f"https://{name}.vault.azure.net/",
            }
        if args.typ == "azure-native:storage:StorageAccount":
            outputs["name"] = args.inputs["accountName"]
        if args.typ in (APP_TYPE, JOB_TYPE):
            # Outputs report identities as a map, unlike the list inputs take.
            identity = args.inputs["identity"]
            outputs["identity"] = {
                **identity,
                "userAssignedIdentities": {
                    i: {} for i in identity.get("userAssignedIdentities", [])
                },
            }
        if args.typ == APP_TYPE:
            configuration = dict(args.inputs.get("configuration", {}))
            configuration["ingress"] = {
                **configuration.get("ingress", {}),
                "fqdn": f"{args.inputs['containerAppName']}.internal.test",
            }
            outputs["configuration"] = configuration
        return f"{args.name}-id", outputs

    def call(self, args):
        if args.token == "azure-native:storage:listStorageAccountKeys":
            return {"keys": [{"keyName": "key1", "value": ACCOUNT_KEY}]}
        return {}


@pytest.fixture
def mocks():
    recorder = _Mocks()
    with _isolated_mocks(recorder):
        yield recorder


HUB_URL = "https://hub.internal.test"


def _create(mocks, hub_url=None, **console_overrides):
    if hub_url:
        data = _hub_data()
        data["console"].update(console_overrides)
        config = LLMavenConfig.model_validate(data)
    else:
        config = _config(**console_overrides)
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
        secrets = create_console_secrets(
            config=config,
            resource_group_name=rg,
            location="westus2",
            tenant_id=TENANT,
            deployer_object_id=DEPLOYER,
            main_vault=main_vault,
            postgres_host=pulumi.Output.from_input(PG_HOST),
            admin_password=pulumi.Output.secret("server-admin-password"),
            mail_connection_string=pulumi.Output.secret("endpoint=acs"),
        )
        out["apps"] = create_console(
            config=config,
            resource_group_name=rg,
            location="westus2",
            container_env=SimpleNamespace(
                id=pulumi.Output.from_input("env-id"),
                name=pulumi.Output.from_input("containerenv"),
            ),
            main_vault=main_vault,
            shared_identity_id=SHARED_IDENTITY,
            secrets=secrets,
            sender_address=SENDER,
            litellm_fqdn=pulumi.Output.from_input(LITELLM_FQDN),
            keycloak_fqdn=pulumi.Output.from_input(KC_FQDN),
            postgres_host=pulumi.Output.from_input(PG_HOST),
            tags={"env": "test"},
            knowledge_hub_url=hub_url,
        )

    run()
    return config, mocks.resources


def _names(config):
    return config.project.name, config.project.environment


def _of_type(resources, typ):
    return [r for r in resources if r.typ == typ]


def _app(resources, config, suffix):
    name = container_app_name(*_names(config), suffix)
    return next(
        r for r in _of_type(resources, APP_TYPE) if r.inputs["containerAppName"] == name
    )


def _job(resources, config, kind):
    name = console_job_name(*_names(config), kind)
    return next(r for r in _of_type(resources, JOB_TYPE) if r.inputs["jobName"] == name)


def _container(resource):
    containers = resource.inputs["template"]["containers"]
    assert len(containers) == 1
    return containers[0]


def _env(resource):
    return {e["name"]: e["value"] for e in _container(resource)["env"] if "value" in e}


def _refs(resource):
    return {
        e["name"]: e["secretRef"]
        for e in _container(resource)["env"]
        if "secretRef" in e
    }


def _secrets(resource):
    return {s["name"]: s for s in resource.inputs["configuration"]["secrets"]}


def _identity_id(resources, label):
    identity = next(
        r
        for r in resources
        if r.typ == "azure-native:managedidentity:UserAssignedIdentity"
        and r.name.endswith(f"-console-{label}")
    )
    return f"{identity.name}-id"


def _vault_uri(config, which):
    return f"https://{console_vault_name(*_names(config), which)}.vault.azure.net"


def _main_vault_uri(resources):
    main = next(r for r in resources if r.name.startswith("key-vault-"))
    return f"https://{main.inputs['vaultName']}.vault.azure.net"


def _user_identities(resource):
    identities = resource.inputs["identity"]["userAssignedIdentities"]
    return list(identities)


# --- names -------------------------------------------------------------------


def test_names_match_the_schema_helpers(mocks):
    config, resources = _create(mocks)
    assert _app(resources, config, CONSOLE_WEB_APP_SUFFIX)
    assert _app(resources, config, CONSOLE_BROKER_APP_SUFFIX)
    assert _job(resources, config, "db")
    assert _job(resources, config, "init")
    assert len(_of_type(resources, APP_TYPE)) == 2
    assert len(_of_type(resources, JOB_TYPE)) == 2


def test_storage_account_name_for_dev_fits_and_is_deterministic():
    name = console_storage_account_name("llmaven-dev", "dev", "westus2")
    assert name == "llmavendevdevwestcon"
    assert len(name) == 20
    assert name == console_storage_account_name("llmaven-dev", "dev", "westus2")


@pytest.mark.parametrize(
    ("project", "environment"),
    [("a" * 20, "dev"), ("bad_name", "dev")],
)
def test_storage_account_name_rejects_what_azure_would(project, environment):
    with pytest.raises(ValueError, match="3-24 lowercase letters and digits"):
        console_storage_account_name(project, environment, "westus2")


# --- apps --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("suffix", "port", "module"),
    [
        (CONSOLE_WEB_APP_SUFFIX, 8200, "web"),
        (CONSOLE_BROKER_APP_SUFFIX, 8100, "broker"),
    ],
)
def test_apps_are_internal_and_probe_healthz(mocks, suffix, port, module):
    config, resources = _create(mocks)
    app = _app(resources, config, suffix)
    ingress = app.inputs["configuration"]["ingress"]
    assert ingress["external"] is False
    assert ingress["targetPort"] == port
    container = _container(app)
    assert container["image"] == config.console.image
    assert container["args"] == [
        "uvicorn",
        f"console_app.{module}.app:app",
        "--host",
        "0.0.0.0",
        "--port",
        str(port),
    ]
    probes = container["probes"]
    assert {p["type"] for p in probes} == {"Liveness", "Readiness", "Startup"}
    for probe in probes:
        assert probe["httpGet"] == {"path": "/healthz", "port": port}


def test_app_sizes_come_from_config(mocks):
    config, resources = _create(
        mocks,
        web={"cpu": 0.5, "memory": "1Gi", "min_replicas": 2, "max_replicas": 3},
    )
    web = _app(resources, config, CONSOLE_WEB_APP_SUFFIX)
    assert _container(web)["resources"] == {"cpu": 0.5, "memory": "1Gi"}
    assert web.inputs["template"]["scale"]["minReplicas"] == 2
    assert web.inputs["template"]["scale"]["maxReplicas"] == 3
    broker = _app(resources, config, CONSOLE_BROKER_APP_SUFFIX)
    assert _container(broker)["resources"] == {"cpu": 0.5, "memory": "1Gi"}
    assert broker.inputs["template"]["scale"]["maxReplicas"] == 1


def test_apps_pin_revision_suffix_and_refresh_trigger(mocks):
    config, resources = _create(mocks, revision_suffix="r7", refresh_trigger="t7")
    for suffix in (CONSOLE_WEB_APP_SUFFIX, CONSOLE_BROKER_APP_SUFFIX):
        app = _app(resources, config, suffix)
        assert app.inputs["template"]["revisionSuffix"] == "r7"
        assert _env(app)["REFRESH_TRIGGER"] == "t7"


def test_web_env(mocks):
    config, resources = _create(mocks)
    web = _app(resources, config, CONSOLE_WEB_APP_SUFFIX)
    realm = config.keycloak.realm.name
    issuer = f"https://{KEYCLOAK_HOST}/realms/{realm}"
    internal = f"https://{KC_FQDN}/realms/{realm}/protocol/openid-connect"
    broker = container_app_name(*_names(config), CONSOLE_BROKER_APP_SUFFIX)
    env = _env(web)
    del env["REFRESH_TRIGGER"]
    assert env == {
        "OIDC_ISSUER": issuer,
        "OIDC_CLIENT_ID": "console",
        "OIDC_AUTH_URL": f"{issuer}/protocol/openid-connect/auth",
        "OIDC_LOGOUT_URL": f"{issuer}/protocol/openid-connect/logout",
        "OIDC_TOKEN_URL": f"{internal}/token",
        "OIDC_JWKS_URL": f"{internal}/certs",
        "CONSOLE_PUBLIC_URL": f"https://{CONSOLE_HOST}",
        "GATEWAY_PUBLIC_URL": f"https://{LITELLM_HOST}",
        "LITELLM_ADMIN_URL": f"https://{ADMIN}",
        "CONSOLE_BROKER_URL": f"https://{broker}.internal.test",
    }
    assert _refs(web) == {
        "CONSOLE_WEB_DATABASE_URL": "console-web-db-url",
        "CONSOLE_BROKER_CALLER_SECRET": "console-broker-caller-secret",
        "OIDC_CLIENT_SECRET": "console-oidc-client-secret",
    }


def test_web_is_isolated(mocks):
    config, resources = _create(mocks)
    web = _app(resources, config, CONSOLE_WEB_APP_SUFFIX)
    names = set(_env(web)) | set(_refs(web))
    for forbidden in (
        "LITELLM_MASTER_KEY",
        "LITELLM_ADMIN_KEY_FILE",
        "ACS_CONNECTION_STRING",
        "LITELLM_URL",
    ):
        assert forbidden not in names
    assert "volumes" not in web.inputs["template"]
    assert "volumeMounts" not in _container(web)

    web_identity = _identity_id(resources, "web")
    assert _user_identities(web) == [web_identity]
    own = _vault_uri(config, "web")
    for secret in _secrets(web).values():
        assert secret["keyVaultUrl"].startswith(f"{own}/secrets/")
        assert secret["identity"] == web_identity
    text = json.dumps(web.inputs)
    assert _vault_uri(config, "broker") not in text
    assert _main_vault_uri(resources) not in text
    assert SHARED_IDENTITY not in text
    assert _identity_id(resources, "broker") not in text


def test_broker_env(mocks):
    config, resources = _create(mocks, invite_ttl_hours=48)
    broker = _app(resources, config, CONSOLE_BROKER_APP_SUFFIX)
    realm = config.keycloak.realm.name
    env = _env(broker)
    del env["REFRESH_TRIGGER"]
    assert env == {
        "LITELLM_URL": f"https://{LITELLM_FQDN}",
        "LITELLM_ADMIN_KEY_FILE": "/run/console/admin-key",
        "MAIL_BACKEND": "acs",
        "MAIL_FROM": SENDER,
        "CONSOLE_ADMIN_SUBJECTS": ",".join(config.console.admin_subjects),
        "CONSOLE_INVITE_TTL_HOURS": "48",
        "OIDC_ISSUER": f"https://{KEYCLOAK_HOST}/realms/{realm}",
        "OIDC_CLIENT_ID": "console",
        "OIDC_JWKS_URL": (
            f"https://{KC_FQDN}/realms/{realm}/protocol/openid-connect/certs"
        ),
        "CONSOLE_PUBLIC_URL": f"https://{CONSOLE_HOST}",
    }
    assert _refs(broker) == {
        "CONSOLE_BROKER_DATABASE_URL": "console-broker-db-url",
        "CONSOLE_BROKER_CALLER_SECRET": "console-broker-caller-secret",
        "ACS_CONNECTION_STRING": "console-mail-connection",
    }
    assert "LITELLM_MASTER_KEY" not in _refs(broker)


KNOWLEDGE_ENV = {
    "KNOWLEDGE_HUB_URL",
    "KEYCLOAK_ADMIN_URL",
    "KEYCLOAK_TOKEN_URL",
    "KEYCLOAK_PROVISIONER_CLIENT_ID",
    "KNOWLEDGE_READER_CLIENT_ID",
}
KNOWLEDGE_REFS = {"KEYCLOAK_PROVISIONER_CLIENT_SECRET", "KNOWLEDGE_READER_CLIENT_SECRET"}


def test_without_a_hub_the_apps_have_no_knowledge_settings(mocks):
    config, resources = _create(mocks)
    for suffix in (CONSOLE_BROKER_APP_SUFFIX, CONSOLE_WEB_APP_SUFFIX):
        app = _app(resources, config, suffix)
        assert not KNOWLEDGE_ENV & set(_env(app))
        assert not KNOWLEDGE_REFS & set(_refs(app))


def test_with_a_hub_the_broker_gets_its_knowledge_settings(mocks):
    config, resources = _create(mocks, hub_url=HUB_URL)
    realm = config.keycloak.realm.name
    broker = _app(resources, config, CONSOLE_BROKER_APP_SUFFIX)
    env = _env(broker)
    assert {k: env[k] for k in KNOWLEDGE_ENV} == {
        "KNOWLEDGE_HUB_URL": HUB_URL,
        "KEYCLOAK_ADMIN_URL": f"https://{KC_FQDN}/admin/realms/{realm}",
        "KEYCLOAK_TOKEN_URL": (
            f"https://{KC_FQDN}/realms/{realm}/protocol/openid-connect/token"
        ),
        "KEYCLOAK_PROVISIONER_CLIENT_ID": "console-provisioner",
        "KNOWLEDGE_READER_CLIENT_ID": "console-knowledge",
    }
    refs = _refs(broker)
    assert {k: refs[k] for k in KNOWLEDGE_REFS} == {
        "KEYCLOAK_PROVISIONER_CLIENT_SECRET": "console-provisioner-secret",
        "KNOWLEDGE_READER_CLIENT_SECRET": "console-knowledge-secret",
    }
    own = _vault_uri(config, "broker")
    for name in ("console-provisioner-secret", "console-knowledge-secret"):
        assert _secrets(broker)[name]["keyVaultUrl"].startswith(f"{own}/secrets/")
    assert _vault_uri(config, "web") not in json.dumps(broker.inputs)


def test_with_a_hub_console_web_is_unchanged(mocks):
    config, resources = _create(mocks)
    before = _app(resources, config, CONSOLE_WEB_APP_SUFFIX)
    env, refs = dict(_env(before)), dict(_refs(before))
    env.pop("REFRESH_TRIGGER")  # a timestamp, different on every run
    seen = len(mocks.resources)
    hub_config, hub_resources = _create(mocks, hub_url=HUB_URL)
    after = _app(hub_resources[seen:], hub_config, CONSOLE_WEB_APP_SUFFIX)
    after_env = dict(_env(after))
    after_env.pop("REFRESH_TRIGGER")
    assert after_env == env
    assert _refs(after) == refs


def test_admin_subjects_are_joined_with_commas(mocks):
    config, resources = _create(mocks, admin_subjects=["a", "b"])
    broker = _app(resources, config, CONSOLE_BROKER_APP_SUFFIX)
    assert _env(broker)["CONSOLE_ADMIN_SUBJECTS"] == "a,b"


def test_broker_uses_its_own_vault_and_identity(mocks):
    config, resources = _create(mocks)
    broker = _app(resources, config, CONSOLE_BROKER_APP_SUFFIX)
    broker_identity = _identity_id(resources, "broker")
    assert _user_identities(broker) == [broker_identity]
    own = _vault_uri(config, "broker")
    for secret in _secrets(broker).values():
        assert secret["keyVaultUrl"].startswith(f"{own}/secrets/")
        assert secret["identity"] == broker_identity
    text = json.dumps(broker.inputs)
    assert _vault_uri(config, "web") not in text
    assert _main_vault_uri(resources) not in text


def _mount(resource):
    volumes = resource.inputs["template"]["volumes"]
    mounts = _container(resource)["volumeMounts"]
    assert len(volumes) == len(mounts) == 1
    assert mounts[0]["volumeName"] == volumes[0]["name"]
    return volumes[0], mounts[0]


def test_broker_mounts_the_read_only_storage(mocks):
    config, resources = _create(mocks)
    volume, mount = _mount(_app(resources, config, CONSOLE_BROKER_APP_SUFFIX))
    assert volume["storageType"] == "AzureFile"
    assert volume["storageName"] == "console-run-ro"
    assert mount["mountPath"] == "/run/console"


def test_init_job_mounts_the_read_write_storage(mocks):
    config, resources = _create(mocks)
    volume, mount = _mount(_job(resources, config, "init"))
    assert volume["storageType"] == "AzureFile"
    assert volume["storageName"] == "console-run-rw"
    assert mount["mountPath"] == "/run/console"


def test_the_share_is_owned_by_the_image_user(mocks):
    config, resources = _create(mocks)
    for resource in (
        _app(resources, config, CONSOLE_BROKER_APP_SUFFIX),
        _job(resources, config, "init"),
    ):
        volume, _ = _mount(resource)
        options = volume["mountOptions"].split(",")
        assert {"uid=10001", "gid=10001", "file_mode=0600"} <= set(options)


# --- storage -----------------------------------------------------------------


def test_storage_account_and_share(mocks):
    config, resources = _create(mocks)
    (account,) = _of_type(resources, "azure-native:storage:StorageAccount")
    assert account.inputs["accountName"] == console_storage_account_name(
        *_names(config), "westus2"
    )
    assert account.inputs["kind"] == "StorageV2"
    assert account.inputs["sku"] == {"name": "Standard_LRS"}
    assert account.inputs["isHnsEnabled"] is False
    assert account.inputs["allowBlobPublicAccess"] is False
    assert account.inputs["minimumTlsVersion"] == "TLS1_2"
    (share,) = _of_type(resources, "azure-native:storage:FileShare")
    assert share.inputs["shareName"] == "console-run"
    assert share.inputs["shareQuota"] == 1
    assert share.inputs["accountName"] == account.inputs["accountName"]


def test_environment_storages_over_the_share(mocks):
    config, resources = _create(mocks)
    storages = {
        r.inputs["storageName"]: r for r in _of_type(resources, ENV_STORAGE_TYPE)
    }
    assert set(storages) == {"console-run-rw", "console-run-ro"}
    account = console_storage_account_name(*_names(config), "westus2")
    for name, mode in (
        ("console-run-rw", "ReadWrite"),
        ("console-run-ro", "ReadOnly"),
    ):
        storage = storages[name]
        assert storage.inputs["environmentName"] == "containerenv"
        # The account key makes the whole properties value a secret.
        properties = storage.inputs["properties"]
        azure_file = properties.get("value", properties)["azureFile"]
        assert azure_file["accessMode"] == mode
        assert azure_file["shareName"] == "console-run"
        assert azure_file["accountName"] == account
        assert azure_file["accountKey"] == ACCOUNT_KEY


def test_account_key_is_a_pulumi_secret(mocks, monkeypatch):
    keys = []
    real = azure_native.app.AzureFilePropertiesArgs

    def record(**kwargs):
        keys.append(kwargs["account_key"])
        return real(**kwargs)

    monkeypatch.setattr(console.azure_native.app, "AzureFilePropertiesArgs", record)
    _create(mocks)
    assert len(keys) == 2
    flags = []

    @pulumi.runtime.test
    def check():
        async def gather():
            flags.extend([await k.is_secret() for k in keys])

        return gather()

    check()
    assert flags == [True, True]


# --- jobs --------------------------------------------------------------------


def _assert_manual_job_on_main_vault(job, resources):
    configuration = job.inputs["configuration"]
    assert configuration["triggerType"] == "Manual"
    assert configuration["manualTriggerConfig"] == {
        "parallelism": 1,
        "replicaCompletionCount": 1,
    }
    assert configuration["replicaTimeout"] > 0
    assert _user_identities(job) == [SHARED_IDENTITY]
    main = _main_vault_uri(resources)
    for secret in _secrets(job).values():
        assert secret["keyVaultUrl"].startswith(f"{main}/secrets/")
        assert secret["identity"] == SHARED_IDENTITY


def test_db_job(mocks):
    config, resources = _create(mocks)
    job = _job(resources, config, "db")
    _assert_manual_job_on_main_vault(job, resources)
    container = _container(job)
    assert container["image"] == config.console.image
    assert container["args"] == ["python", "db_setup.py"]
    others = [d for d in config.database.databases if d != CONSOLE_DB]
    assert others  # the stack's own databases
    assert _env(job) == {
        "PGHOST": PG_HOST,
        "PGUSER": config.database.admin_login,
        "CONSOLE_OTHER_DATABASES": ",".join(others),
    }
    assert _refs(job) == {
        "PGPASSWORD": PG_ADMIN_SECRET,
        "CONSOLE_WEB_DB_PASSWORD": "console-web-db-password",
        "CONSOLE_BROKER_DB_PASSWORD": "console-broker-db-password",
    }
    assert set(_secrets(job)) == set(_refs(job).values())
    assert "volumes" not in job.inputs["template"]


def test_init_job(mocks):
    config, resources = _create(mocks)
    job = _job(resources, config, "init")
    _assert_manual_job_on_main_vault(job, resources)
    container = _container(job)
    assert container["image"] == config.console.image
    assert container["args"] == ["python", "init_admin_key.py"]
    assert _env(job) == {
        "LITELLM_URL": f"https://{LITELLM_FQDN}",
        "LITELLM_ADMIN_KEY_FILE": "/run/console/admin-key",
    }
    assert _refs(job) == {"LITELLM_MASTER_KEY": MASTER_KEY_SECRET}
    assert set(_secrets(job)) == {MASTER_KEY_SECRET}


def test_master_key_is_only_in_the_init_job(mocks):
    config, resources = _create(mocks)
    init = _job(resources, config, "init")
    holders = [
        r.name
        for r in resources
        if MASTER_KEY_SECRET in json.dumps(r.inputs)
        or "LITELLM_MASTER_KEY" in json.dumps(r.inputs)
    ]
    assert holders == [init.name]


def test_no_role_assignments_or_access_policies(mocks):
    _, resources = _create(mocks)
    assert not any(
        r.typ.startswith("azure-native:authorization")
        or r.typ == "azure-native:keyvault:AccessPolicy"
        for r in resources
    )
