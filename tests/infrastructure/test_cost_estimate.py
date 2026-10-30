"""Tests for estimate_monthly_cost(), focused on the Pulumi state store line.

Covers https://github.com/uw-ssec/llmaven/issues/84: the monthly estimate must
account for the Pulumi state store (a separate Azure Storage account used as the
deployment backend).
"""

from __future__ import annotations

import pytest

from llmaven.deployment.validate import (
    STATE_STORE_MAX_COST,
    STATE_STORE_MIN_COST,
    estimate_monthly_cost,
)
from llmaven.infrastructure.config.schema import (
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
        monitoring=MonitoringConfig(enable_application_insights=False),
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
