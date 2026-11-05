"""Tests for the monitoring.alerts configuration schema and defaults."""

import pytest
import yaml
from pydantic import ValidationError

from llmaven.infrastructure.config.defaults import (
    generate_default_config,
    get_config_template_yaml,
)
from llmaven.infrastructure.config.schema import (
    ALL_ALERTS,
    AlertsConfig,
    CloudBudgetAlert,
    GatewayErrorsAlert,
    LLMavenConfig,
    MonitoringConfig,
)


def test_no_alerts_block_means_alerting_off():
    assert LLMavenConfig().monitoring.alerts.enabled_alerts == []


def test_unknown_alert_name_rejected():
    with pytest.raises(ValidationError):
        AlertsConfig(enabled_alerts=["gateway_errorz"], email_receivers=["a@b.org"])


def test_enabled_alerts_require_email_receivers():
    with pytest.raises(ValidationError, match="email_receivers"):
        AlertsConfig(enabled_alerts=["db_cpu"])


def test_empty_alerts_need_no_receivers():
    assert AlertsConfig().email_receivers == []


def test_duplicate_alert_names_are_deduplicated():
    cfg = AlertsConfig(enabled_alerts=["db_cpu", "db_cpu"], email_receivers=["a@b.org"])
    assert cfg.enabled_alerts == ["db_cpu"]


def test_malformed_email_rejected():
    with pytest.raises(ValidationError):
        AlertsConfig(enabled_alerts=["db_cpu"], email_receivers=["ops"])


@pytest.mark.parametrize("minutes", [0, 10, 45, 2000])
def test_window_minutes_must_be_an_azure_window(minutes):
    with pytest.raises(ValidationError, match="1, 5, 15, 30, 60, 360, 720, 1440"):
        GatewayErrorsAlert(window_minutes=minutes)


@pytest.mark.parametrize("percents", [[], [0], [1001]])
def test_budget_notify_at_percent_bounds(percents):
    with pytest.raises(ValidationError):
        CloudBudgetAlert(notify_at_percent=percents)


def test_log_alert_needs_log_analytics():
    # model_post_init raises ValueError directly (ValidationError is a subclass).
    with pytest.raises(ValueError, match="enable_log_analytics"):
        LLMavenConfig(
            monitoring={
                "enable_log_analytics": False,
                "alerts": {
                    "enabled_alerts": ["backup_job_failures"],
                    "email_receivers": ["a@b.org"],
                },
            }
        )


def test_application_insights_true_warns_but_loads():
    with pytest.warns(DeprecationWarning, match="enable_application_insights"):
        cfg = MonitoringConfig(enable_application_insights=True)
    assert cfg.enable_application_insights is True


def test_schema_threshold_defaults():
    a = AlertsConfig()
    assert (a.gateway_errors.max_5xx_count, a.gateway_errors.window_minutes) == (10, 15)
    assert (a.gateway_latency.max_avg_ms, a.gateway_latency.window_minutes) == (
        300000,
        15,
    )
    assert (a.replica_restarts.max_count, a.replica_restarts.window_minutes) == (3, 30)
    assert a.db_storage.max_percent == 80
    assert (a.db_cpu.max_percent, a.db_cpu.window_minutes) == (85, 30)
    assert (a.cloud_budget.monthly_usd, a.cloud_budget.notify_at_percent) == (
        500,
        [80, 100],
    )


@pytest.mark.parametrize(
    "env,alerts,budget",
    [
        ("dev", [], 200),
        ("staging", list(ALL_ALERTS), 300),
        ("prod", list(ALL_ALERTS), 500),
    ],
)
def test_environment_defaults_round_trip_through_template(env, alerts, budget):
    for cfg in (
        generate_default_config(env),
        LLMavenConfig(**yaml.safe_load(get_config_template_yaml(env))),
    ):
        assert cfg.monitoring.alerts.enabled_alerts == alerts
        assert cfg.monitoring.alerts.cloud_budget.monthly_usd == budget
        assert cfg.monitoring.enable_application_insights is False
