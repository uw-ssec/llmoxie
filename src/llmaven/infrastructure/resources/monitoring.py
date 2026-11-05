"""Azure Monitor alerting: an email action group and metric alerts.

Each alert named in ``monitoring.alerts.enabled_alerts`` is built by a small
function that looks up its target resource. When the target is not deployed
the alert is skipped with a warning rather than failing the whole deployment.
"""

from dataclasses import dataclass
from typing import Callable

import pulumi
import pulumi_azure_native as azure_native

from ..config.schema import AlertsConfig, LLMavenConfig

# Azure metric names and dimensions. Verified against Microsoft docs, except
# the literal "5xx" dimension value, which is undocumented: confirm in dev.
CONTAINER_APP_REQUESTS_METRIC = "Requests"
CONTAINER_APP_STATUS_DIMENSION = "statusCodeCategory"
CONTAINER_APP_STATUS_5XX = "5xx"
CONTAINER_APP_RESPONSE_TIME_METRIC = "ResponseTime"
CONTAINER_APP_RESTART_METRIC = "RestartCount"
POSTGRES_STORAGE_METRIC = "storage_percent"
POSTGRES_CPU_METRIC = "cpu_percent"

ACTION_GROUP_SHORT_NAME = "llmoxie"  # Azure allows at most 12 characters.
EVALUATION_FREQUENCY = "PT5M"
# Azure rejects a window shorter than the evaluation frequency.
ONE_MINUTE = "PT1M"
DB_STORAGE_WINDOW = "PT15M"

# Window sizes of 60 minutes and above use hour notation in ISO 8601.
_HOUR_WINDOWS = {60: "PT1H", 360: "PT6H", 720: "PT12H", 1440: "PT24H"}


def _window_size(minutes: int) -> str:
    """Convert a window in minutes to the ISO 8601 form Azure Monitor accepts."""
    return _HOUR_WINDOWS.get(minutes, f"PT{minutes}M")


@dataclass
class MonitoringResources:
    """Resources created by :func:`create_monitoring`."""

    action_group: azure_native.monitor.ActionGroup
    alerts: dict[str, pulumi.CustomResource]  # Pulumi resource name -> resource


@dataclass
class _Context:
    """Everything an alert builder needs."""

    alerts_config: AlertsConfig
    resource_group_name: str
    action_group: azure_native.monitor.ActionGroup
    litellm_app: azure_native.app.ContainerApp | None
    mlflow_app: azure_native.app.ContainerApp | None
    postgres_server: azure_native.dbforpostgresql.Server | None
    tags: dict[str, str]


def _metric_alert(
    ctx: _Context,
    *,
    resource_name: str,
    alert_name: str,
    target_id: pulumi.Input[str],
    metric_name: str,
    aggregation: str,
    threshold: float,
    window_size: str,
    severity: int,
    dimensions: list[azure_native.monitor.MetricDimensionArgs] | None = None,
) -> azure_native.monitor.MetricAlert:
    """Create one static-threshold metric alert wired to the action group."""
    return azure_native.monitor.MetricAlert(
        resource_name,
        resource_group_name=ctx.resource_group_name,
        location="global",
        scopes=[target_id],
        severity=severity,
        enabled=True,
        evaluation_frequency=(
            ONE_MINUTE if window_size == ONE_MINUTE else EVALUATION_FREQUENCY
        ),
        window_size=window_size,
        auto_mitigate=True,
        criteria=azure_native.monitor.MetricAlertSingleResourceMultipleMetricCriteriaArgs(
            odata_type="Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria",
            all_of=[
                azure_native.monitor.MetricCriteriaArgs(
                    criterion_type="StaticThresholdCriterion",
                    name=alert_name,
                    metric_name=metric_name,
                    operator="GreaterThan",
                    threshold=threshold,
                    time_aggregation=aggregation,
                    dimensions=dimensions,
                )
            ],
        ),
        actions=[
            azure_native.monitor.MetricAlertActionArgs(
                action_group_id=ctx.action_group.id
            )
        ],
        tags=ctx.tags,
    )


def _warn_skipped(name: str, target: str) -> None:
    pulumi.log.warn(f"monitoring: {name} skipped, {target} is not deployed")


def _gateway_errors(ctx: _Context) -> dict[str, pulumi.CustomResource]:
    if ctx.litellm_app is None:
        _warn_skipped("gateway_errors", "litellm app")
        return {}
    cfg = ctx.alerts_config.gateway_errors
    return {
        "alert-gateway-errors": _metric_alert(
            ctx,
            resource_name="alert-gateway-errors",
            alert_name="gateway_errors",
            target_id=ctx.litellm_app.id,
            metric_name=CONTAINER_APP_REQUESTS_METRIC,
            aggregation="Total",
            threshold=cfg.max_5xx_count,
            window_size=_window_size(cfg.window_minutes),
            severity=1,
            dimensions=[
                azure_native.monitor.MetricDimensionArgs(
                    name=CONTAINER_APP_STATUS_DIMENSION,
                    operator="Include",
                    values=[CONTAINER_APP_STATUS_5XX],
                )
            ],
        )
    }


def _gateway_latency(ctx: _Context) -> dict[str, pulumi.CustomResource]:
    if ctx.litellm_app is None:
        _warn_skipped("gateway_latency", "litellm app")
        return {}
    cfg = ctx.alerts_config.gateway_latency
    return {
        "alert-gateway-latency": _metric_alert(
            ctx,
            resource_name="alert-gateway-latency",
            alert_name="gateway_latency",
            target_id=ctx.litellm_app.id,
            metric_name=CONTAINER_APP_RESPONSE_TIME_METRIC,
            aggregation="Average",
            threshold=cfg.max_avg_ms,
            window_size=_window_size(cfg.window_minutes),
            severity=2,
        )
    }


def _replica_restarts(ctx: _Context) -> dict[str, pulumi.CustomResource]:
    cfg = ctx.alerts_config.replica_restarts
    created: dict[str, pulumi.CustomResource] = {}
    for label, app in (("litellm", ctx.litellm_app), ("mlflow", ctx.mlflow_app)):
        if app is None:
            _warn_skipped("replica_restarts", f"{label} app")
            continue
        resource_name = f"alert-replica-restarts-{label}"
        created[resource_name] = _metric_alert(
            ctx,
            resource_name=resource_name,
            alert_name="replica_restarts",
            target_id=app.id,
            metric_name=CONTAINER_APP_RESTART_METRIC,
            aggregation="Total",
            threshold=cfg.max_count,
            window_size=_window_size(cfg.window_minutes),
            severity=2,
        )
    return created


def _db_storage(ctx: _Context) -> dict[str, pulumi.CustomResource]:
    if ctx.postgres_server is None:
        _warn_skipped("db_storage", "postgres server")
        return {}
    return {
        "alert-db-storage": _metric_alert(
            ctx,
            resource_name="alert-db-storage",
            alert_name="db_storage",
            target_id=ctx.postgres_server.id,
            metric_name=POSTGRES_STORAGE_METRIC,
            aggregation="Maximum",
            threshold=ctx.alerts_config.db_storage.max_percent,
            window_size=DB_STORAGE_WINDOW,
            severity=1,
        )
    }


def _db_cpu(ctx: _Context) -> dict[str, pulumi.CustomResource]:
    if ctx.postgres_server is None:
        _warn_skipped("db_cpu", "postgres server")
        return {}
    cfg = ctx.alerts_config.db_cpu
    return {
        "alert-db-cpu": _metric_alert(
            ctx,
            resource_name="alert-db-cpu",
            alert_name="db_cpu",
            target_id=ctx.postgres_server.id,
            metric_name=POSTGRES_CPU_METRIC,
            aggregation="Average",
            threshold=cfg.max_percent,
            window_size=_window_size(cfg.window_minutes),
            severity=2,
        )
    }


# Alert name -> builder. Enabled alerts with no builder here are skipped.
_BUILDERS: dict[str, Callable[[_Context], dict[str, pulumi.CustomResource]]] = {
    "gateway_errors": _gateway_errors,
    "gateway_latency": _gateway_latency,
    "replica_restarts": _replica_restarts,
    "db_storage": _db_storage,
    "db_cpu": _db_cpu,
}


def create_monitoring(
    *,
    config: LLMavenConfig,
    resource_group_name: str,
    location: str,
    log_analytics_workspace: azure_native.operationalinsights.Workspace | None,
    litellm_app: azure_native.app.ContainerApp | None,
    mlflow_app: azure_native.app.ContainerApp | None,
    postgres_server: azure_native.dbforpostgresql.Server | None,
    backup_job: azure_native.app.Job | None,
    tags: dict[str, str],
) -> MonitoringResources | None:
    """Create the email action group and the enabled alerts.

    Returns ``None`` when no alerts are enabled. ``location``,
    ``log_analytics_workspace`` and ``backup_job`` are not used by the metric
    alerts; they are accepted for the log-based alert and budget builders.
    """
    alerts_config = config.monitoring.alerts
    if not alerts_config.enabled_alerts:
        return None

    action_group = azure_native.monitor.ActionGroup(
        "alerts-action-group",
        resource_group_name=resource_group_name,
        location="global",
        group_short_name=ACTION_GROUP_SHORT_NAME,
        enabled=True,
        email_receivers=[
            azure_native.monitor.MicrosoftCommonEmailReceiverArgs(
                name=f"email-{i}",
                email_address=address,
                use_common_alert_schema=True,
            )
            for i, address in enumerate(alerts_config.email_receivers)
        ],
        tags=tags,
    )

    ctx = _Context(
        alerts_config=alerts_config,
        resource_group_name=resource_group_name,
        action_group=action_group,
        litellm_app=litellm_app,
        mlflow_app=mlflow_app,
        postgres_server=postgres_server,
        tags=tags,
    )
    alerts: dict[str, pulumi.CustomResource] = {}
    for name in alerts_config.enabled_alerts:
        builder = _BUILDERS.get(name)
        if builder is not None:
            alerts.update(builder(ctx))

    return MonitoringResources(action_group=action_group, alerts=alerts)
