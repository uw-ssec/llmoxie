"""ceil-dlp guardrail wiring for LiteLLM (litellm.dlp)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pulumi
import pytest
import yaml
from pydantic import ValidationError

from llmaven.infrastructure.config.schema import LLMavenConfig
from llmaven.infrastructure.main import create_pulumi_program
from llmaven.infrastructure.resources import helpers
from llmaven.infrastructure.resources.dlp import (
    DLP_GUARDRAIL_MODULE,
    apply_dlp_guardrail,
    validate_dlp_policy,
)
from .test_redis_program import _Mocks

REPO_ROOT = Path(__file__).resolve().parents[2]
LITELLM_CONFIG = REPO_ROOT / "docker" / "config.yaml"
POLICY = "mode: enforce\nner_strength: 1\npolicies:\n  email: {action: mask}\n"


# --- Config schema ----------------------------------------------------------


def test_dlp_is_off_by_default():
    config = LLMavenConfig.model_validate({})
    assert config.litellm.dlp.enabled is False


def test_enabling_dlp_requires_a_policy_file():
    with pytest.raises(ValidationError, match="policy_file"):
        LLMavenConfig.model_validate({"litellm": {"dlp": {"enabled": True}}})


# --- Policy validation -------------------------------------------------------


def test_policy_with_ner_strength_1_is_accepted():
    validate_dlp_policy(POLICY, "p.yaml")


@pytest.mark.parametrize(
    "text", ["mode: enforce\n", "ner_strength: 3\n", "ner_strength: 2\n"]
)
def test_policy_must_set_ner_strength_1(text):
    # ceil-dlp defaults to 3, which downloads models the image doesn't carry.
    with pytest.raises(ValueError, match="ner_strength: 1"):
        validate_dlp_policy(text, "p.yaml")


def test_policy_must_be_a_mapping():
    with pytest.raises(ValueError, match="mapping"):
        validate_dlp_policy("- a\n- b\n", "p.yaml")


# --- Guardrail registration in the LiteLLM config ----------------------------


def test_guardrail_is_added_and_the_rest_of_the_config_kept():
    original = LITELLM_CONFIG.read_text()
    out = apply_dlp_guardrail(original, default_on=False)
    data = yaml.safe_load(out)
    [entry] = data["guardrails"]
    assert entry == {
        "guardrail_name": "ceil-dlp",
        "litellm_params": {
            "guardrail": "ceil_dlp_guardrail.CeilDLPGuardrail",
            "mode": ["pre_call", "post_call"],
            "default_on": False,
        },
    }
    before = yaml.safe_load(original)
    assert {k: v for k, v in data.items() if k != "guardrails"} == before


def test_existing_guardrails_are_kept():
    text = "guardrails:\n  - guardrail_name: other\n    litellm_params: {}\n"
    data = yaml.safe_load(apply_dlp_guardrail(text))
    assert [g["guardrail_name"] for g in data["guardrails"]] == ["other", "ceil-dlp"]


def test_a_hand_written_ceil_dlp_entry_is_an_error():
    text = "guardrails:\n  - guardrail_name: ceil-dlp\n    litellm_params: {}\n"
    with pytest.raises(ValueError, match="already registers"):
        apply_dlp_guardrail(text)


def test_guardrail_module_name_matches_the_registered_path():
    # LiteLLM imports "<module>.CeilDLPGuardrail" from a file of that name in
    # the config directory.
    assert DLP_GUARDRAIL_MODULE.name == "ceil_dlp_guardrail.py"
    assert "CeilDLPGuardrail" in DLP_GUARDRAIL_MODULE.read_text()


# --- Whole program under Pulumi mocks ----------------------------------------


def _run(tmp_path: Path, monkeypatch, dlp: dict | None) -> dict:
    litellm = {"max_replicas": 1, "config_file": str(LITELLM_CONFIG)}
    if dlp is not None:
        litellm["dlp"] = dlp
    config = {
        "project": {"name": "llmaven", "environment": "dev", "location": "eastus"},
        "azure": {
            "subscription_id": "00000000-0000-0000-0000-000000000000",
            "tenant_id": "00000000-0000-0000-0000-000000000000",
            "resource_group": "rg-test",
        },
        "monitoring": {"enable_log_analytics": False},
        "litellm": litellm,
    }
    config_path = tmp_path / "llmaven-config.yaml"
    config_path.write_text(yaml.safe_dump(config))
    monkeypatch.delenv("PULUMI_CONFIG_PASSPHRASE", raising=False)

    apps = {}

    def fake_create_app(**kwargs):
        apps[kwargs["app_name"]] = kwargs
        return SimpleNamespace(configuration=pulumi.Output.from_input(None))

    monkeypatch.setattr(
        helpers, "create_container_app_with_key_vault_secrets", fake_create_app
    )
    pulumi.runtime.set_mocks(_Mocks(), project="llmaven", stack="dev", preview=False)
    program = create_pulumi_program(config_path)

    @pulumi.runtime.test
    def run():
        program()

    run()
    return apps["llmaven-dev-litellm"]


def test_program_without_dlp_mounts_nothing_extra(tmp_path, monkeypatch):
    app = _run(tmp_path, monkeypatch, dlp=None)

    assert set(app["inline_secrets"]) == {"adl-logger-py", "config-yaml"}
    assert app["inline_secrets"]["config-yaml"] == LITELLM_CONFIG.read_text()
    assert not {"CEIL_DLP_CONFIG_PATH", "HF_HUB_OFFLINE"} & set(app["env_vars"])


def test_program_with_dlp_mounts_guardrail_and_policy(tmp_path, monkeypatch):
    (tmp_path / "ceil-dlp.yaml").write_text(POLICY)
    app = _run(
        tmp_path,
        monkeypatch,
        dlp={"enabled": True, "policy_file": "ceil-dlp.yaml", "default_on": True},
    )

    secrets = app["inline_secrets"]
    assert secrets["ceil-dlp-yaml"] == POLICY
    assert "CeilDLPGuardrail" in secrets["ceil-dlp-guardrail-py"]
    mounted = yaml.safe_load(secrets["config-yaml"])
    assert mounted["guardrails"][0]["litellm_params"]["default_on"] is True

    assert app["env_vars"]["CEIL_DLP_CONFIG_PATH"] == "/app/config/ceil-dlp.yaml"
    assert app["env_vars"]["HF_HUB_OFFLINE"] == "1"
    assert app["env_vars"]["TRANSFORMERS_OFFLINE"] == "1"

    [volume] = [v for v in app["volumes"] if v.name == "litellm-config-volume"]
    assert {item.path for item in volume.secrets} == {
        "adl_logger.py",
        "ceil_dlp_guardrail.py",
        "ceil-dlp.yaml",
        "config.yaml",
    }


def test_program_rejects_a_policy_without_ner_strength_1(tmp_path, monkeypatch):
    (tmp_path / "ceil-dlp.yaml").write_text("mode: enforce\n")
    with pytest.raises(Exception, match="ner_strength: 1"):
        _run(
            tmp_path,
            monkeypatch,
            dlp={"enabled": True, "policy_file": "ceil-dlp.yaml"},
        )


def test_program_rejects_a_policy_named_like_the_litellm_config(tmp_path, monkeypatch):
    sub = tmp_path / "dlp"
    sub.mkdir()
    (sub / "config.yaml").write_text(POLICY)
    with pytest.raises(Exception, match="clashes"):
        _run(
            tmp_path,
            monkeypatch,
            dlp={"enabled": True, "policy_file": "dlp/config.yaml"},
        )


@pytest.fixture(autouse=True)
def _reset_pulumi_mocks():
    yield
    pulumi.runtime.settings.configure(pulumi.runtime.Settings(project="", stack=""))
