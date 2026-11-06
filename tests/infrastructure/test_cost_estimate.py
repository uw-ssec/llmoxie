"""Tests for estimate_monthly_cost(), focused on the Pulumi state store line.

Covers https://github.com/uw-ssec/llmaven/issues/84: the monthly estimate must
account for the Pulumi state store (a separate Azure Storage account used as the
deployment backend).
"""

from __future__ import annotations

import pytest

from llmaven.deployment.validate import (
    METRIC_ALERT_MONTHLY_COST,
    STATE_STORE_MAX_COST,
    STATE_STORE_MIN_COST,
    estimate_monthly_cost,
)
from llmaven.infrastructure.config.schema import (
    AlertsConfig,
    BackupJobConfig,
    DatabaseConfig,
    LiteLLMConfig,
    LLMavenAPIConfig,
    LLMavenConfig,
    MLflowConfig,
    MonitoringConfig,
)


def _minimal_config() -> LLMavenConfig:
    """A config with every optional/container service disabled.

    With container apps and monitoring off, the estimate is fully determined by
    the database tier, database storage, blob storage, and the state store —
    which makes the arithmetic exact and independent of unrelated defaults.
    """
    return LLMavenConfig(
        database=DatabaseConfig(sku_name="B_Standard_B1ms", storage_size_gb=32),
        mlflow=MLflowConfig(enabled=False),
        litellm=LiteLLMConfig(enabled=False),
        llmaven_api=LLMavenAPIConfig(enabled=False),
        monitoring=MonitoringConfig(),
        # backup_job.database is required; enabled defaults False so the
        # cross-field validation against database.databases is skipped.
        backup_job=BackupJobConfig(database="llmaven"),
    )


def test_state_store_constants_are_sane():
    assert STATE_STORE_MIN_COST > 0
    assert STATE_STORE_MAX_COST >= STATE_STORE_MIN_COST


def test_state_store_is_included_in_estimate():
    config = _minimal_config()

    min_cost, max_cost = estimate_monthly_cost(config)

    # Burstable DB (13/20) + storage 32 * 0.115 (min only) + blob (2/5)
    # + state store. Everything else is disabled.
    expected_without_state_store_min = 13.0 + (32 * 0.115) + 2.0
    expected_without_state_store_max = 20.0 + 5.0

    assert min_cost == pytest.approx(
        expected_without_state_store_min + STATE_STORE_MIN_COST
    )
    assert max_cost == pytest.approx(
        expected_without_state_store_max + STATE_STORE_MAX_COST
    )


def test_enabling_a_container_app_still_adds_its_cost():
    """Guard against regressions in the existing container-app math."""
    base_min, base_max = estimate_monthly_cost(_minimal_config())

    config = _minimal_config()
    config.mlflow = MLflowConfig(enabled=True, cpu=0.5)
    with_mlflow_min, with_mlflow_max = estimate_monthly_cost(config)

    # 0.5 vCPU * 15/30 per the existing rough rates.
    assert with_mlflow_min == pytest.approx(base_min + 0.5 * 15.0)
    assert with_mlflow_max == pytest.approx(base_max + 0.5 * 30.0)


def test_application_insights_flag_no_longer_costs_anything():
    base = _minimal_config()
    with pytest.warns(DeprecationWarning):
        flagged = _minimal_config().model_copy(
            update={"monitoring": MonitoringConfig(enable_application_insights=True)}
        )
    assert estimate_monthly_cost(flagged) == estimate_monthly_cost(base)


def test_alerts_add_their_rule_costs():
    cfg = _minimal_config()
    cfg.monitoring.alerts = AlertsConfig(
        email_receivers=["a@b.org"],
        enabled_alerts=["db_cpu", "db_storage", "cloud_budget"],
    )
    lo, hi = estimate_monthly_cost(cfg)
    base_lo, base_hi = estimate_monthly_cost(_minimal_config())
    assert lo - base_lo == pytest.approx(2 * METRIC_ALERT_MONTHLY_COST)
    assert hi - base_hi == pytest.approx(2 * METRIC_ALERT_MONTHLY_COST)
