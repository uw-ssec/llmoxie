"""Azure Managed Redis for multi-replica LiteLLM (#211)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import yaml
from pydantic import ValidationError

from llmaven.deployment.validate import (
    HOURS_PER_MONTH,
    PRIVATE_ENDPOINT_MAX_COST,
    PRIVATE_ENDPOINT_MIN_COST,
    REDIS_HOURLY_PRICE_PER_NODE,
    estimate_monthly_cost,
)
from llmaven.infrastructure.config.defaults import (
    generate_default_config,
    get_config_template_yaml,
)
from llmaven.infrastructure.config.schema import LLMavenConfig
from llmaven.infrastructure.resources import helpers
from llmaven.infrastructure.resources.redis import (
    REDIS_ROUTER_SETTINGS,
    apply_redis_router_settings,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
LITELLM_CONFIG = REPO_ROOT / "docker" / "config.yaml"


# --- Config schema: Redis is required when LiteLLM runs >1 replica ---------


def test_redis_defaults_on_for_multi_replica_litellm():
    config = LLMavenConfig.model_validate({"litellm": {"max_replicas": 3}})
    assert config.redis.enabled is True


def test_redis_defaults_off_for_single_replica_litellm():
    config = LLMavenConfig.model_validate({"litellm": {"max_replicas": 1}})
    assert config.redis.enabled is False


def test_single_replica_litellm_may_still_enable_redis():
    config = LLMavenConfig.model_validate(
        {"litellm": {"max_replicas": 1}, "redis": {"enabled": True}}
    )
    assert config.redis.enabled is True


def test_disabling_redis_with_multi_replica_litellm_is_an_error():
    with pytest.raises(ValidationError, match="litellm.max_replicas is 2"):
        LLMavenConfig.model_validate(
            {"litellm": {"max_replicas": 2}, "redis": {"enabled": False}}
        )


def test_disabled_litellm_does_not_require_redis():
    config = LLMavenConfig.model_validate(
        {"litellm": {"enabled": False, "max_replicas": 5}, "redis": {"enabled": False}}
    )
    assert config.redis.enabled is False


def test_oss_cluster_policy_is_rejected():
    # OSSCluster needs a cluster-aware client, which REDIS_HOST/PORT doesn't give.
    with pytest.raises(ValidationError, match="Clustering policy"):
        LLMavenConfig.model_validate({"redis": {"clustering_policy": "OSSCluster"}})


def test_redis_schema_defaults():
    config = LLMavenConfig()
    assert config.redis.sku_name == "Balanced_B0"
    assert config.redis.clustering_policy == "EnterpriseCluster"
    assert config.redis.high_availability is False
    assert config.networking.private_endpoints_subnet == "10.0.3.0/24"


@pytest.mark.parametrize("environment", ["dev", "staging", "prod"])
def test_generated_template_round_trips_redis(environment):
    data = yaml.safe_load(get_config_template_yaml(environment))
    config = LLMavenConfig.model_validate(data)
    expected = generate_default_config(environment)

    assert data["redis"]["enabled"] is True  # every default runs >1 replica
    assert config.redis == expected.redis
    assert config.networking.private_endpoints_subnet == "10.0.3.0/24"


# Deployed stacks (llmaven-deploy dev/prod/iss-workshop) use this layout and
# predate private_endpoints_subnet.
EXISTING_STACK_NETWORKING = {
    "vnet_address_space": "172.16.0.0/16",
    "container_apps_subnet": "172.16.0.0/23",
    "postgres_subnet": "172.16.2.0/24",
}


def test_omitted_private_endpoints_subnet_follows_existing_vnet():
    config = LLMavenConfig.model_validate({"networking": EXISTING_STACK_NETWORKING})
    assert config.redis.enabled is True
    assert config.networking.private_endpoints_subnet == "172.16.3.0/24"


def test_omitted_private_endpoints_subnet_skips_partial_block():
    config = LLMavenConfig.model_validate(
        {
            "networking": {
                "vnet_address_space": "10.1.0.0/16",
                "container_apps_subnet": "10.1.0.0/23",
                "postgres_subnet": "10.1.2.0/25",
            }
        }
    )
    assert config.networking.private_endpoints_subnet == "10.1.3.0/24"


def test_explicit_private_endpoints_subnet_is_kept():
    networking = {
        **EXISTING_STACK_NETWORKING,
        "private_endpoints_subnet": "172.16.9.0/24",
    }
    config = LLMavenConfig.model_validate({"networking": networking})
    assert config.networking.private_endpoints_subnet == "172.16.9.0/24"


@pytest.mark.parametrize(
    ("subnet", "message"),
    [("10.0.3.0/24", "outside"), ("172.16.1.0/24", "overlaps")],
)
def test_invalid_private_endpoints_subnet_is_rejected(subnet, message):
    networking = {**EXISTING_STACK_NETWORKING, "private_endpoints_subnet": subnet}
    with pytest.raises(ValidationError, match=message):
        LLMavenConfig.model_validate({"networking": networking})


def test_full_vnet_only_fails_when_redis_needs_the_subnet():
    networking = {
        "vnet_address_space": "10.2.0.0/22",
        "container_apps_subnet": "10.2.0.0/23",
        "postgres_subnet": "10.2.2.0/23",
    }
    single = LLMavenConfig.model_validate(
        {"networking": networking, "litellm": {"max_replicas": 1}}
    )
    assert single.redis.enabled is False
    assert single.networking.private_endpoints_subnet is None

    with pytest.raises(ValidationError, match="private endpoints subnet"):
        LLMavenConfig.model_validate({"networking": networking})


def test_only_prod_defaults_to_high_availability():
    assert generate_default_config("dev").redis.high_availability is False
    assert generate_default_config("staging").redis.high_availability is False
    assert generate_default_config("prod").redis.high_availability is True


@pytest.mark.parametrize(
    ("environment", "expected"), [("dev", False), ("staging", False), ("prod", True)]
)
def test_existing_config_without_redis_section_gets_environment_ha(
    environment, expected
):
    # Configs written before the redis section existed gain Redis on their next
    # deploy; a prod stack must get the same HA as a freshly generated prod one.
    config = LLMavenConfig.model_validate(
        {"project": {"environment": environment}, "litellm": {"max_replicas": 2}}
    )
    assert config.redis.enabled is True
    assert config.redis.high_availability is expected
    assert expected is generate_default_config(environment).redis.high_availability


def test_explicit_high_availability_overrides_environment():
    prod = LLMavenConfig.model_validate(
        {"project": {"environment": "prod"}, "redis": {"high_availability": False}}
    )
    dev = LLMavenConfig.model_validate(
        {"project": {"environment": "dev"}, "redis": {"high_availability": True}}
    )
    assert prod.redis.high_availability is False
    assert dev.redis.high_availability is True


# --- LiteLLM config injection ------------------------------------------------


def test_router_settings_are_added_to_repo_litellm_config():
    rendered = yaml.safe_load(apply_redis_router_settings(LITELLM_CONFIG.read_text()))
    original = yaml.safe_load(LITELLM_CONFIG.read_text())

    assert rendered["router_settings"] == REDIS_ROUTER_SETTINGS
    assert rendered["litellm_settings"]["force_redis_hash_tag_grouping"] is True
    # Everything else is untouched.
    for key in ("model_list", "general_settings"):
        assert rendered[key] == original[key]
    rendered["litellm_settings"].pop("force_redis_hash_tag_grouping")
    assert rendered["litellm_settings"] == original["litellm_settings"]


def test_existing_router_settings_are_kept_and_comments_preserved():
    text = (
        "# top comment\n"
        "router_settings:\n"
        "  routing_strategy: simple-shuffle  # keep me\n"
        "  redis_host: stale-host\n"
    )
    out = apply_redis_router_settings(text)
    data = yaml.safe_load(out)

    assert data["router_settings"]["routing_strategy"] == "simple-shuffle"
    assert data["router_settings"]["redis_host"] == "os.environ/REDIS_HOST"
    assert "# top comment" in out
    assert "# keep me" in out


def test_no_cluster_policy_skips_hash_tag_grouping():
    data = yaml.safe_load(
        apply_redis_router_settings("model_list: []\n", clustering_policy="NoCluster")
    )
    assert data["router_settings"] == REDIS_ROUTER_SETTINGS
    assert "litellm_settings" not in data


@pytest.mark.parametrize("text", ["- a\n- b\n", "router_settings: [1]\n"])
def test_malformed_litellm_config_is_rejected(text):
    with pytest.raises(ValueError, match="mapping"):
        apply_redis_router_settings(text)


def _mounted_litellm_config(redis_enabled: bool, **kwargs) -> str:
    with patch.object(
        helpers, "create_container_app_with_key_vault_secrets", return_value=Mock()
    ) as create_app:
        helpers.create_litellm_app(
            name="llmaven-dev-litellm",
            resource_group_name="rg",
            location="westus2",
            container_env_id="env-id",
            container_env_name="env",
            image="example.test/litellm:1",
            port=4000,
            cpu=1,
            memory="2Gi",
            min_replicas=1,
            max_replicas=2,
            env_vars={},
            key_vault=SimpleNamespace(properties=SimpleNamespace(vault_uri="kv")),
            key_vault_secret_refs={},
            config_file=str(LITELLM_CONFIG),
            redis_enabled=redis_enabled,
            **kwargs,
        )
    return create_app.call_args.kwargs["inline_secrets"]["config-yaml"]


def test_litellm_config_is_mounted_verbatim_without_redis():
    # Single-replica environments must not reference unset REDIS_* env vars,
    # and the mounted secret must not change (no new revision).
    assert _mounted_litellm_config(redis_enabled=False) == LITELLM_CONFIG.read_text()


def test_litellm_config_gets_redis_block_when_enabled():
    data = yaml.safe_load(_mounted_litellm_config(redis_enabled=True))
    assert data["router_settings"] == REDIS_ROUTER_SETTINGS
    assert data["litellm_settings"]["force_redis_hash_tag_grouping"] is True


def test_litellm_config_no_cluster_omits_hash_tag_grouping():
    data = yaml.safe_load(
        _mounted_litellm_config(redis_enabled=True, redis_clustering_policy="NoCluster")
    )
    assert data["router_settings"] == REDIS_ROUTER_SETTINGS
    assert "force_redis_hash_tag_grouping" not in data["litellm_settings"]


# --- Cost estimate -----------------------------------------------------------


def _cost(redis: dict) -> tuple[float, float]:
    return estimate_monthly_cost(
        LLMavenConfig.model_validate({"litellm": {"max_replicas": 1}, "redis": redis})
    )


def test_cost_estimate_includes_redis_node_and_private_endpoint():
    base_min, base_max = _cost({"enabled": False})
    with_min, with_max = _cost({"enabled": True})

    node = REDIS_HOURLY_PRICE_PER_NODE["Balanced_B0"] * HOURS_PER_MONTH
    assert with_min - base_min == pytest.approx(node + PRIVATE_ENDPOINT_MIN_COST)
    assert with_max - base_max == pytest.approx(node + PRIVATE_ENDPOINT_MAX_COST)


def test_cost_estimate_doubles_redis_for_high_availability():
    single_min, _ = _cost({"enabled": True})
    ha_min, _ = _cost({"enabled": True, "high_availability": True})

    node = REDIS_HOURLY_PRICE_PER_NODE["Balanced_B0"] * HOURS_PER_MONTH
    assert ha_min - single_min == pytest.approx(node)
