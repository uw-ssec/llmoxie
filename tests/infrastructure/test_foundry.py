"""Tests for the optional Azure AI Foundry account and model deployments (#196)."""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pulumi
import pytest
from pydantic import ValidationError

from llmaven.deployment import validate as validate_mod
from llmaven.infrastructure.config.defaults import get_config_template_yaml
from llmaven.infrastructure.config.litellm_models import missing_foundry_deployments
from llmaven.infrastructure.config.loader import load_config
from llmaven.infrastructure.config.schema import (
    FoundryConfig,
    FoundryDeploymentConfig,
    LLMavenConfig,
    foundry_secret_collisions,
)

DEPLOYMENT = {
    "name": "gpt-5-mini",
    "model_name": "gpt-5-mini",
    "model_version": "2025-08-07",
}


def _write_configs(
    tmp_path: Path,
    foundry_enabled: bool,
    model_list_yaml: str = "  - model_name: gpt-5-mini\n    litellm_params:\n      model: azure/gpt-5-mini\n",
    deployments_yaml: str = (
        "    - name: gpt-5-mini\n"
        "      model_name: gpt-5-mini\n"
        "      model_version: '2025-08-07'\n"
    ),
) -> Path:
    """Write an infra YAML and a LiteLLM config next to it; return the infra path."""
    litellm_dir = tmp_path / "litellm"
    litellm_dir.mkdir()
    (litellm_dir / "config.yaml").write_text("model_list:\n" + model_list_yaml)
    config_path = tmp_path / "infra" / "llmaven-config.yaml"
    config_path.parent.mkdir()
    config_path.write_text(
        textwrap.dedent(
            f"""\
            project:
              name: llmaven
              environment: dev
              location: eastus
            azure:
              subscription_id: "00000000-0000-0000-0000-000000000000"
              tenant_id: "11111111-1111-1111-1111-111111111111"
              resource_group: rg-test
            litellm:
              config_file: ../litellm/config.yaml
            foundry:
              enabled: {str(foundry_enabled).lower()}
              deployments:
            """
        )
        + (deployments_yaml if foundry_enabled else "    []\n")
    )
    return config_path


# --- schema -----------------------------------------------------------------


def test_foundry_defaults_disabled_bring_your_own_endpoint():
    config = LLMavenConfig()
    assert config.foundry.enabled is False
    assert config.foundry.deployments == []


def test_deployment_defaults_pin_versions():
    d = FoundryDeploymentConfig(**DEPLOYMENT)
    assert d.version_upgrade_option == "NoAutoUpgrade"
    assert d.sku == "GlobalStandard"
    assert d.model_format == "OpenAI"


@pytest.mark.parametrize(
    "field,value",
    [
        ("sku", "Cheapest"),
        ("version_upgrade_option", "Whenever"),
        ("capacity", 0),
        ("name", "bad name"),
        ("model_name", ""),
        ("model_name", "   "),
        ("model_format", ""),
        ("model_format", " \t"),
        ("model_version", ""),
        ("model_version", "  "),
    ],
)
def test_deployment_rejects_bad_fields(field, value):
    with pytest.raises(ValidationError):
        FoundryDeploymentConfig(**{**DEPLOYMENT, field: value})


def test_duplicate_deployment_names_rejected():
    with pytest.raises(ValidationError, match="Duplicate"):
        FoundryConfig(enabled=True, deployments=[DEPLOYMENT, DEPLOYMENT])


def test_account_name_must_be_valid_subdomain():
    with pytest.raises(ValidationError):
        FoundryConfig(account_name="-bad-")


def test_init_template_loads_with_foundry_disabled(tmp_path):
    path = tmp_path / "llmaven-config.yaml"
    path.write_text(get_config_template_yaml("dev"))
    config = load_config(path)
    assert config.foundry.enabled is False


# --- secret collisions -----------------------------------------------------


def test_collisions_only_when_enabled():
    names = ["azure-api-base", "azure-api-key", "litellm-master-key"]
    assert foundry_secret_collisions(False, names) == []
    assert foundry_secret_collisions(True, names) == ["azure-api-base", "azure-api-key"]


def test_check_secrets_flags_collision_and_skips_managed(monkeypatch, tmp_path):
    config = load_config(_write_configs(tmp_path, foundry_enabled=True))
    monkeypatch.setattr(
        validate_mod,
        "get_llmaven_secrets",
        lambda _p=None: {
            "litellm-master-key": "x" * 32,
            "anthropic-api-key": "y" * 32,
            "mlflow-experiment-name": "exp",
            "azure-api-key": "z" * 32,
        },
    )
    ok, messages = validate_mod.check_secrets(config)
    assert ok is False
    text = "\n".join(messages)
    assert "azure-api-key is managed by the stack" in text
    # The other managed secrets are not reported as missing.
    assert "Missing: azure-api-base" not in text
    assert "Missing: azure-api-version" not in text


def test_check_secrets_byo_path_still_requires_azure_secrets(monkeypatch, tmp_path):
    config = load_config(_write_configs(tmp_path, foundry_enabled=False))
    monkeypatch.setattr(
        validate_mod,
        "get_llmaven_secrets",
        lambda _p=None: {"litellm-master-key": "x" * 32},
    )
    ok, messages = validate_mod.check_secrets(config)
    assert ok is False
    assert any("Missing: azure-api-base" in m for m in messages)


# --- model_list consistency ------------------------------------------------


def test_model_list_matches_deployments(tmp_path):
    path = _write_configs(tmp_path, foundry_enabled=True)
    assert missing_foundry_deployments(load_config(path), path) == []


def test_model_alias_must_match_deployment_name_not_model_name(tmp_path):
    path = _write_configs(
        tmp_path,
        foundry_enabled=True,
        model_list_yaml=(
            "  - model_name: fast\n    litellm_params:\n      model: azure/fast-chat\n"
            "  - model_name: claude\n    litellm_params:\n      model: anthropic/claude\n"
        ),
        deployments_yaml=(
            "    - name: fast-chat\n"
            "      model_name: gpt-5-mini\n"
            "      model_version: '2025-08-07'\n"
        ),
    )
    assert missing_foundry_deployments(load_config(path), path) == []


def test_model_list_entry_without_deployment_is_reported(tmp_path):
    path = _write_configs(
        tmp_path,
        foundry_enabled=True,
        model_list_yaml="  - model_name: big\n    litellm_params:\n      model: azure/gpt-5\n",
    )
    errors = missing_foundry_deployments(load_config(path), path)
    assert len(errors) == 1 and "'gpt-5'" in errors[0]


def test_missing_litellm_config_is_reported(tmp_path):
    path = _write_configs(tmp_path, foundry_enabled=True)
    (tmp_path / "litellm" / "config.yaml").unlink()
    errors = missing_foundry_deployments(load_config(path), path)
    assert len(errors) == 1 and "Cannot read LiteLLM config" in errors[0]


@pytest.mark.parametrize(
    "content,expected",
    [
        ("- azure/fast\n", "top level must be a mapping, got list"),
        ("model_list: azure/fast\n", "model_list must be a list, got str"),
        ("model_list:\n  - azure/fast\n", "model_list[0] must be a mapping, got str"),
        (
            "model_list:\n  - model_name: fast\n    litellm_params:\n"
            "      - azure/fast\n",
            "model_list[0].litellm_params must be a mapping, got list",
        ),
        (
            "model_list:\n  - model_name: fast\n",
            "model_list[0].litellm_params must be a mapping, got NoneType",
        ),
    ],
)
def test_malformed_litellm_config_is_reported(tmp_path, content, expected):
    path = _write_configs(tmp_path, foundry_enabled=True)
    litellm_config = tmp_path / "litellm" / "config.yaml"
    litellm_config.write_text(content)
    errors = missing_foundry_deployments(load_config(path), path)
    assert len(errors) == 1
    assert expected in errors[0]
    assert str(litellm_config) in errors[0]


@pytest.mark.parametrize("content", ["", "general_settings: {}\n", "model_list:\n"])
def test_litellm_config_without_model_list_is_consistent(tmp_path, content):
    path = _write_configs(tmp_path, foundry_enabled=True)
    (tmp_path / "litellm" / "config.yaml").write_text(content)
    assert missing_foundry_deployments(load_config(path), path) == []


def test_model_list_not_checked_when_disabled(tmp_path):
    path = _write_configs(
        tmp_path,
        foundry_enabled=False,
        model_list_yaml="  - model_name: big\n    litellm_params:\n      model: azure/gpt-5\n",
    )
    assert missing_foundry_deployments(load_config(path), path) == []


def test_required_providers_include_cognitive_services_only_when_enabled(
    monkeypatch,
):
    seen = []

    class Result:
        returncode = 0
        stdout = "Registered\n"
        stderr = ""

    def fake_run(cmd, **_kwargs):
        seen.append(cmd[cmd.index("--namespace") + 1])
        return Result()

    monkeypatch.setattr(validate_mod.subprocess, "run", fake_run)
    validate_mod.check_required_providers("sub")
    assert "Microsoft.CognitiveServices" not in seen
    seen.clear()
    validate_mod.check_required_providers("sub", foundry_enabled=True)
    assert "Microsoft.CognitiveServices" in seen


# --- Pulumi program under mocks --------------------------------------------


class _Mocks(pulumi.runtime.Mocks):
    def __init__(self):
        self.resources = []

    def new_resource(self, args: pulumi.runtime.MockResourceArgs):
        self.resources.append(args)
        outputs = dict(args.inputs)
        outputs.setdefault("name", args.name)
        # Provider-computed outputs the program reads.
        if args.typ.endswith("storage:StorageAccount"):
            outputs["primaryEndpoints"] = {"blob": "https://sa.blob.core.windows.net/"}
        if args.typ.endswith("keyvault:Vault"):
            outputs["properties"] = {
                **outputs.get("properties", {}),
                "vaultUri": "https://kv.vault.azure.net/",
            }
        if args.typ.endswith("postgresql:Server"):
            outputs["fullyQualifiedDomainName"] = "pg.postgres.database.azure.com"
        if args.typ.endswith("managedidentity:UserAssignedIdentity"):
            outputs["principalId"] = "principal"
        identity = outputs.get("identity")
        if isinstance(identity, dict) and isinstance(
            identity.get("userAssignedIdentities"), list
        ):
            outputs["identity"] = {
                **identity,
                "userAssignedIdentities": {
                    i: {} for i in identity["userAssignedIdentities"]
                },
            }
        return f"{args.name}_id", outputs

    def call(self, args: pulumi.runtime.MockCallArgs):
        if args.token.endswith("getClientConfig"):
            return {"objectId": "obj", "tenantId": "tenant", "clientId": "client"}
        if args.token.endswith("listAccountKeys"):
            return {"key1": "foundry-key-1", "key2": "foundry-key-2"}
        if args.token.endswith("listStorageAccountKeys"):
            return {"keys": [{"value": "storage-key"}]}
        if args.token.endswith("getSharedKeys"):
            return {"primarySharedKey": "shared"}
        return {}


def _run_program(config_path: Path, monkeypatch) -> list:
    from llmaven.infrastructure.main import create_pulumi_program

    for key in list(os.environ):
        if key.startswith("LLMAVEN_SECRETS_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("LLMAVEN_SECRETS_LITELLM_MASTER_KEY", "master")
    mocks = _Mocks()
    pulumi.runtime.set_mocks(mocks, preview=False)
    program = create_pulumi_program(config_path)

    @pulumi.runtime.test
    def run():
        program()
        return pulumi.Output.from_input(True)

    run()
    return mocks.resources


def _by_type(resources, type_suffix):
    return [r for r in resources if r.typ.endswith(type_suffix)]


def test_program_with_foundry_creates_locked_down_account(tmp_path, monkeypatch):
    resources = _run_program(_write_configs(tmp_path, True), monkeypatch)

    [account] = _by_type(resources, "cognitiveservices:Account")
    assert account.inputs["kind"] == "AIServices"
    assert account.inputs["accountName"] == "llmaven-foundry-dev"
    props = account.inputs["properties"]
    assert props["customSubDomainName"] == "llmaven-foundry-dev"
    assert props["publicNetworkAccess"] == "Enabled"
    acls = props["networkAcls"]
    assert acls["defaultAction"] == "Deny"
    assert acls["bypass"] == "None"
    assert acls.get("ipRules", []) == []
    [vnet_rule] = acls["virtualNetworkRules"]
    assert vnet_rule["id"] == "container-apps-subnet_id"
    assert vnet_rule["ignoreMissingVnetServiceEndpoint"] is False

    [deployment] = _by_type(resources, "cognitiveservices:Deployment")
    assert deployment.inputs["deploymentName"] == "gpt-5-mini"
    assert deployment.inputs["sku"] == {"name": "GlobalStandard", "capacity": 10}
    assert deployment.inputs["properties"]["versionUpgradeOption"] == "NoAutoUpgrade"
    assert deployment.inputs["properties"]["model"]["version"] == "2025-08-07"

    [subnet] = [r for r in resources if r.name == "container-apps-subnet"]
    assert subnet.inputs["serviceEndpoints"] == [
        {"service": "Microsoft.CognitiveServices"}
    ]

    secret_props = {
        r.inputs["secretName"]: r.inputs["properties"]
        for r in _by_type(resources, "keyvault:Secret")
    }
    assert (
        secret_props["azure-api-base"]["value"]
        == "https://llmaven-foundry-dev.openai.azure.com/"
    )
    assert secret_props["azure-api-version"]["value"] == "2025-04-01-preview"
    # The key reaches the engine wrapped as a Pulumi secret.
    key_props = secret_props["azure-api-key"]
    assert key_props.get(pulumi.runtime.rpc._special_sig_key) == (
        pulumi.runtime.rpc._special_secret_sig
    )
    assert key_props["value"]["value"] == "foundry-key-1"


def test_program_chains_deployments_and_litellm_waits_for_them(tmp_path, monkeypatch):
    path = _write_configs(
        tmp_path,
        True,
        model_list_yaml="  - model_name: a\n    litellm_params:\n      model: azure/a\n",
        deployments_yaml=(
            "    - name: a\n      model_name: gpt-5-mini\n      model_version: '1'\n"
            "    - name: b\n      model_name: gpt-5\n      model_version: '1'\n"
        ),
    )
    import pulumi_azure_native as azure_native

    import llmaven.infrastructure.resources as resources_mod

    captured = []
    real_create_litellm_app = resources_mod.create_litellm_app

    def spy_litellm(*args, **kwargs):
        captured.append(kwargs["opts"])
        return real_create_litellm_app(*args, **kwargs)

    deployment_opts = []
    real_deployment = azure_native.cognitiveservices.Deployment

    def spy_deployment(*args, **kwargs):
        deployment_opts.append(kwargs.get("opts"))
        return real_deployment(*args, **kwargs)

    monkeypatch.setattr(resources_mod, "create_litellm_app", spy_litellm)
    monkeypatch.setattr(azure_native.cognitiveservices, "Deployment", spy_deployment)

    resources = _run_program(path, monkeypatch)
    deployments = _by_type(resources, "cognitiveservices:Deployment")
    assert [d.inputs["deploymentName"] for d in deployments] == ["a", "b"]

    [litellm_opts] = captured
    deps = {r._name for r in litellm_opts.depends_on}
    assert {
        "foundry-deployment-a-dev",
        "foundry-deployment-b-dev",
        "kv-secret-azure-api-base-dev",
        "kv-secret-azure-api-key-dev",
        "kv-secret-azure-api-version-dev",
    } <= deps
    # The second deployment waits for the first (Azure rejects concurrent ones).
    [first, second] = deployment_opts
    assert first is None or not first.depends_on
    assert [r._name for r in second.depends_on] == ["foundry-deployment-a-dev"]


def test_program_without_foundry_adds_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("LLMAVEN_SECRETS_AZURE_API_BASE", "https://byo/")
    resources = _run_program(_write_configs(tmp_path, False), monkeypatch)
    assert _by_type(resources, "cognitiveservices:Account") == []
    assert _by_type(resources, "cognitiveservices:Deployment") == []
    [subnet] = [r for r in resources if r.name == "container-apps-subnet"]
    assert not subnet.inputs.get("serviceEndpoints")


def test_program_rejects_user_secret_that_foundry_manages(tmp_path, monkeypatch):
    path = _write_configs(tmp_path, True)
    monkeypatch.setenv("LLMAVEN_SECRETS_AZURE_API_KEY", "user-key")
    from llmaven.infrastructure.main import create_pulumi_program

    pulumi.runtime.set_mocks(_Mocks(), preview=False)
    with pytest.raises(ValueError, match="azure-api-key"):
        create_pulumi_program(path)()


def test_program_rejects_model_without_deployment(tmp_path, monkeypatch):
    path = _write_configs(
        tmp_path,
        True,
        model_list_yaml="  - model_name: big\n    litellm_params:\n      model: azure/gpt-5\n",
    )
    for key in list(os.environ):
        if key.startswith("LLMAVEN_SECRETS_"):
            monkeypatch.delenv(key)
    from llmaven.infrastructure.main import create_pulumi_program

    pulumi.runtime.set_mocks(_Mocks(), preview=False)
    with pytest.raises(ValueError, match="gpt-5"):
        create_pulumi_program(path)()
