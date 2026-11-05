"""The backup job's storage credential must reach it through Key Vault (#219)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pulumi
import pytest
import yaml
from google.protobuf import json_format
from pulumi.runtime.rpc import _special_secret_sig, _special_sig_key

from llmaven.infrastructure.main import create_pulumi_program
from llmaven.infrastructure.resources import helpers

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV = "LLMAVEN_SECRETS_BACKUP_STORAGE_CONNECTION_STRING"
CUSTOM_ENV = "BACKUP_STORAGE_CONNECTION_STRING"
KV_NAME = "backup-storage-connection-string"
KV_URN_NAME = f"kv-secret-{KV_NAME}-dev"
CREDENTIAL = "synthetic-backup-credential"


class _Mocks(pulumi.runtime.Mocks):
    def new_resource(self, args: pulumi.runtime.MockResourceArgs):
        outputs = {
            k: v for k, v in args.inputs.items() if isinstance(v, (str, int, bool))
        }
        if args.typ == "azure-native:storage:StorageAccount":
            outputs["primaryEndpoints"] = {"blob": "https://sa.blob.core.windows.net/"}
        if args.typ == "azure-native:keyvault:Vault":
            outputs["properties"] = {"vaultUri": "https://kv.vault.azure.net/"}
        if args.typ == "azure-native:app:Job":
            # The identity input is a list but its output type is a mapping.
            outputs["identity"] = {"type": "UserAssigned"}
        return f"{args.name}-id", outputs

    def call(self, args: pulumi.runtime.MockCallArgs):
        if args.token == "azure-native:storage:listStorageAccountKeys":
            return {"keys": [{"keyName": "key1", "value": "storage-key"}]}
        if args.token == "azure-native:authorization:getClientConfig":
            return {
                "clientId": "c",
                "objectId": "00000000-0000-0000-0000-000000000000",
                "subscriptionId": "s",
                "tenantId": "00000000-0000-0000-0000-000000000000",
            }
        return {}


def _run(tmp_path, monkeypatch, backup_job: dict) -> SimpleNamespace:
    """Run the whole program under mocks, recording what each resource was sent."""
    config = {
        "project": {"name": "llmaven", "environment": "dev", "location": "eastus"},
        "azure": {
            "subscription_id": "00000000-0000-0000-0000-000000000000",
            "tenant_id": "00000000-0000-0000-0000-000000000000",
            "resource_group": "rg-test",
        },
        "monitoring": {"enable_log_analytics": False},
        "litellm": {"config_file": str(REPO_ROOT / "docker" / "config.yaml")},
        "backup_job": backup_job,
    }
    config_path = tmp_path / "llmaven-config.yaml"
    config_path.write_text(yaml.safe_dump(config))
    monkeypatch.delenv("PULUMI_CONFIG_PASSPHRASE", raising=False)
    monkeypatch.setattr(
        helpers,
        "create_container_app_with_key_vault_secrets",
        lambda **_: SimpleNamespace(configuration=pulumi.Output.from_input(None)),
    )

    registered: dict[str, dict] = {}
    names: list[str] = []
    register = pulumi.runtime.mocks.MockMonitor.RegisterResource

    def recording_register(monitor, request):
        urns = set(request.dependencies)
        for deps in request.propertyDependencies.values():
            urns.update(deps.urns)
        names.append(request.name)
        registered[request.name] = {
            "wire": json.dumps(json_format.MessageToDict(request.object)),
            "dependencies": {urn.rsplit("::", 1)[-1] for urn in urns},
        }
        return register(monitor, request)

    monkeypatch.setattr(
        pulumi.runtime.mocks.MockMonitor, "RegisterResource", recording_register
    )
    pulumi.runtime.set_mocks(_Mocks(), project="llmaven", stack="dev", preview=False)
    program = create_pulumi_program(config_path)

    @pulumi.runtime.test
    def run():
        program()

    run()
    # The mock monitor accepts duplicate URNs; the Pulumi engine rejects them.
    assert names.count(KV_URN_NAME) <= 1
    return SimpleNamespace(
        job=registered.get("backup-job-dev"),
        kv_secret=registered.get(KV_URN_NAME),
    )


def _assert_job_reads_credential_from_key_vault(result) -> None:
    job = json.loads(result.job["wire"])
    secrets = {s["name"]: s for s in job["configuration"]["secrets"]}
    assert set(secrets) == {KV_NAME, "db-connection-string-llmaven"}
    storage = secrets[KV_NAME]
    assert storage["keyVaultUrl"] == f"https://kv.vault.azure.net/secrets/{KV_NAME}"
    assert storage["identity"] == "managed-identity-llmaven-dev-apps-identity-id"
    assert "value" not in storage

    [container] = job["template"]["containers"]
    env = {e["name"]: e for e in container["env"]}
    assert env["AZURE_STORAGE_CONNECTION_STRING"] == {
        "name": "AZURE_STORAGE_CONNECTION_STRING",
        "secretRef": KV_NAME,
    }
    assert CREDENTIAL not in result.job["wire"]

    assert {
        KV_URN_NAME,
        "kv-secret-db-connection-string-llmaven-dev",
        "kv-access-policy-apps-identity-read",
    } <= result.job["dependencies"]


def _assert_key_vault_value_is_secret(result) -> None:
    value = json.loads(result.kv_secret["wire"])["properties"]["value"]
    assert value[_special_sig_key] == _special_secret_sig
    assert value["value"] == CREDENTIAL


def test_default_env_var_reuses_the_user_provided_key_vault_secret(
    tmp_path, monkeypatch
):
    monkeypatch.setenv(DEFAULT_ENV, CREDENTIAL)
    monkeypatch.delenv(CUSTOM_ENV, raising=False)

    result = _run(tmp_path, monkeypatch, {"enabled": True})

    _assert_key_vault_value_is_secret(result)
    _assert_job_reads_credential_from_key_vault(result)


def test_custom_env_var_creates_a_secret_wrapped_key_vault_secret(
    tmp_path, monkeypatch
):
    monkeypatch.delenv(DEFAULT_ENV, raising=False)
    monkeypatch.setenv(CUSTOM_ENV, CREDENTIAL)

    result = _run(
        tmp_path,
        monkeypatch,
        {"enabled": True, "connection_string_env": CUSTOM_ENV},
    )

    _assert_key_vault_value_is_secret(result)
    _assert_job_reads_credential_from_key_vault(result)


def test_both_env_vars_with_the_same_value_share_one_key_vault_secret(
    tmp_path, monkeypatch
):
    monkeypatch.setenv(DEFAULT_ENV, CREDENTIAL)
    monkeypatch.setenv(CUSTOM_ENV, CREDENTIAL)

    result = _run(
        tmp_path,
        monkeypatch,
        {"enabled": True, "connection_string_env": CUSTOM_ENV},
    )

    _assert_key_vault_value_is_secret(result)
    _assert_job_reads_credential_from_key_vault(result)


def test_both_env_vars_with_different_values_fail_without_printing_either(
    tmp_path, monkeypatch
):
    monkeypatch.setenv(DEFAULT_ENV, "synthetic-prefixed-value")
    monkeypatch.setenv(CUSTOM_ENV, "synthetic-custom-value")

    with pytest.raises(Exception, match=f"{DEFAULT_ENV}.*{CUSTOM_ENV}") as error:
        _run(
            tmp_path,
            monkeypatch,
            {"enabled": True, "connection_string_env": CUSTOM_ENV},
        )

    assert "synthetic-prefixed-value" not in str(error.value)
    assert "synthetic-custom-value" not in str(error.value)


def test_missing_connection_string_fails(tmp_path, monkeypatch):
    monkeypatch.delenv(DEFAULT_ENV, raising=False)

    with pytest.raises(Exception, match=f"{DEFAULT_ENV} must be set"):
        _run(tmp_path, monkeypatch, {"enabled": True})


def test_disabled_job_creates_neither_job_nor_key_vault_secret(tmp_path, monkeypatch):
    monkeypatch.delenv(DEFAULT_ENV, raising=False)
    monkeypatch.setenv(CUSTOM_ENV, CREDENTIAL)

    result = _run(
        tmp_path,
        monkeypatch,
        {"enabled": False, "connection_string_env": CUSTOM_ENV},
    )

    assert result.job is None
    assert result.kv_secret is None


@pytest.fixture(autouse=True)
def _reset_pulumi_mocks():
    yield
    pulumi.runtime.settings.configure(pulumi.runtime.Settings(project="", stack=""))
