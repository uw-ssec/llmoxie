"""Azure Monitor alerting: an email action group, metric and log alerts, a budget.

Each alert named in ``monitoring.alerts.enabled_alerts`` is built by a small
function that looks up its target resource. When the target is not deployed
the alert is skipped with a warning rather than failing the whole deployment.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
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
# RestartCount is cumulative per replica, so the restart alert splits by pod.
CONTAINER_APP_POD_DIMENSION = "podName"
POSTGRES_STORAGE_METRIC = "storage_percent"
POSTGRES_CPU_METRIC = "cpu_percent"

ACTION_GROUP_SHORT_NAME = "llmoxie"  # Azure allows at most 12 characters.
EVALUATION_FREQUENCY = "PT5M"
# Azure rejects a window shorter than the evaluation frequency.
ONE_MINUTE = "PT1M"
# Azure pairs frequency with window size; PT1H is the safe pairing for the
# long windows (6 hours and above).
HOURLY_FREQUENCY = "PT1H"
LONG_WINDOW_MINUTES = 360
DB_STORAGE_WINDOW = "PT15M"
BACKUP_FAILURE_FREQUENCY = "PT1H"
# Twice the frequency, so a record ingested after one evaluation is still in the
# next one's window. The rule is stateful, so the overlap doesn't email twice.
BACKUP_FAILURE_WINDOW = "PT2H"

# Container Apps system logs, classic ``log_analytics_configuration`` schema
# (``_CL`` table, ``_s`` columns). The rule fires when this query returns any
# row, one per failed execution.
#
# ContainerTerminated can't be used: every run logs it, including successful
# ones and attempts recovered by a retry. DeadlineExceeded is confirmed from 70
# timed-out production runs. BackoffLimitExceeded (retries exhausted) has not
# been observed live, so confirm it by forcing a failure.
BACKUP_FAILURE_QUERY = """\
ContainerAppSystemLogs_CL
| where JobName_s == "{job_name}"
| summarize
    Failed = countif(Reason_s in ("BackoffLimitExceeded", "DeadlineExceeded")),
    Completed = countif(Reason_s == "Completed")
    by ExecutionName_s
| where Failed > 0 and Completed == 0
"""

# The spend logger prints one ``LLMOXIE_SPEND {json}`` line per request to the
# LiteLLM console. The query sums ``spend`` over the rule's window. Without a
# ``by`` clause ``summarize`` always returns one row, with 0 on empty input, so
# an idle gateway doesn't fire a threshold above 0. 14 is the length of the
# ``LLMOXIE_SPEND `` prefix; tests check it against ``spend_logger``.
LLM_SPEND_FREQUENCY = "PT1H"
LLM_SPEND_WINDOWS = {"hourly": "PT1H", "daily": "P1D"}
LLM_SPEND_QUERY = (
    'ContainerAppConsoleLogs_CL | where ContainerAppName_s == "{app}" '
    'and Log_s startswith "LLMOXIE_SPEND " '
    "| extend r = parse_json(substring(Log_s, 14)) "
    "| summarize spend = sum(todouble(r.spend))"
)

# Window sizes of 60 minutes and above use hour notation in ISO 8601.
_HOUR_WINDOWS = {60: "PT1H", 360: "PT6H", 720: "PT12H", 1440: "PT24H"}
# Windows of LONG_WINDOW_MINUTES and above, in the ISO 8601 form Azure uses.
_LONG_WINDOWS = frozenset(
    size for minutes, size in _HOUR_WINDOWS.items() if minutes >= LONG_WINDOW_MINUTES
)


def _window_size(minutes: int) -> str:
    """Convert a window in minutes to the ISO 8601 form Azure Monitor accepts."""
    return _HOUR_WINDOWS.get(minutes, f"PT{minutes}M")


def _evaluation_frequency(window_size: str) -> str:
    """Pick the evaluation frequency Azure accepts alongside ``window_size``."""
    if window_size == ONE_MINUTE:
        return ONE_MINUTE
    if window_size in _LONG_WINDOWS:
        return HOURLY_FREQUENCY
    return EVALUATION_FREQUENCY


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
    location: str
    log_analytics_workspace: azure_native.operationalinsights.Workspace | None
    backup_job: azure_native.app.Job | None
    subscription_id: str
    project_name: str
    environment: str


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
        evaluation_frequency=_evaluation_frequency(window_size),
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
    """Alert when a single replica has restarted more than ``max_count`` times.

    ``RestartCount`` is the cumulative number of restarts of a replica since it
    was created, so summing it over a window latches as soon as any replica has
    ever restarted. Taking the Maximum, split per ``podName``, keeps the
    threshold meaning "one replica restarted this many times since it started".
    """
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
            aggregation="Maximum",
            threshold=cfg.max_count,
            window_size=_window_size(cfg.window_minutes),
            severity=2,
            dimensions=[
                azure_native.monitor.MetricDimensionArgs(
                    name=CONTAINER_APP_POD_DIMENSION,
                    operator="Include",
                    values=["*"],
                )
            ],
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


def _backup_job_failures(ctx: _Context) -> dict[str, pulumi.CustomResource]:
    if ctx.backup_job is None:
        _warn_skipped("backup_job_failures", "backup job")
        return {}
    if ctx.log_analytics_workspace is None:
        _warn_skipped("backup_job_failures", "log analytics workspace")
        return {}
    query = ctx.backup_job.name.apply(
        lambda job_name: BACKUP_FAILURE_QUERY.format(job_name=job_name)
    )
    return {
        "alert-backup-job-failures": azure_native.monitor.ScheduledQueryRule(
            "alert-backup-job-failures",
            resource_group_name=ctx.resource_group_name,
            location=ctx.location,
            kind="LogAlert",
            enabled=True,
            scopes=[ctx.log_analytics_workspace.id],
            severity=1,
            evaluation_frequency=BACKUP_FAILURE_FREQUENCY,
            window_size=BACKUP_FAILURE_WINDOW,
            auto_mitigate=True,
            # A fresh workspace has no ContainerAppSystemLogs_CL table until
            # the first backup run, and Azure validates the query at create
            # time. Without this the rule fails to create on a new stack.
            skip_query_validation=True,
            criteria=azure_native.monitor.ScheduledQueryRuleCriteriaArgs(
                all_of=[
                    azure_native.monitor.ConditionArgs(
                        query=query,
                        time_aggregation="Count",
                        operator="GreaterThan",
                        threshold=0,
                    )
                ]
            ),
            actions=azure_native.monitor.ActionsArgs(
                action_groups=[ctx.action_group.id]
            ),
            tags=ctx.tags,
        )
    }


def _llm_spend(ctx: _Context) -> dict[str, pulumi.CustomResource]:
    if ctx.litellm_app is None:
        _warn_skipped("llm_spend", "litellm app")
        return {}
    if ctx.log_analytics_workspace is None:
        _warn_skipped("llm_spend", "log analytics workspace")
        return {}
    litellm_app = ctx.litellm_app
    query = litellm_app.name.apply(
        lambda app_name: LLM_SPEND_QUERY.format(app=app_name)
    )
    alerts: dict[str, pulumi.CustomResource] = {}
    # The windows overlap the hourly frequency on purpose: a daily breach
    # re-evaluates every hour and stays fired until it auto-mitigates. The
    # spend lines are best effort (console logs can be dropped or delayed), so
    # this alert can under-report.
    for window, usd in ctx.alerts_config.llm_spend.thresholds().items():
        name = f"alert-llm-spend-{window}"
        alerts[name] = azure_native.monitor.ScheduledQueryRule(
            name,
            resource_group_name=ctx.resource_group_name,
            location=ctx.location,
            kind="LogAlert",
            enabled=True,
            scopes=[ctx.log_analytics_workspace.id],
            severity=2,
            evaluation_frequency=LLM_SPEND_FREQUENCY,
            window_size=LLM_SPEND_WINDOWS[window],
            auto_mitigate=True,
            # The console log table may not exist on a fresh workspace, and
            # Azure validates the query at create time.
            skip_query_validation=True,
            criteria=azure_native.monitor.ScheduledQueryRuleCriteriaArgs(
                all_of=[
                    azure_native.monitor.ConditionArgs(
                        query=query,
                        time_aggregation="Total",
                        metric_measure_column="spend",
                        operator="GreaterThan",
                        threshold=usd,
                    )
                ]
            ),
            actions=azure_native.monitor.ActionsArgs(
                action_groups=[ctx.action_group.id]
            ),
            tags=ctx.tags,
        )
    return alerts


def _cloud_budget(ctx: _Context) -> dict[str, pulumi.CustomResource]:
    """Create the monthly budget. Its scope is the whole resource group.

    Environments that share a resource group therefore share one budget; see
    the README "Alerting" section.
    """
    if not ctx.subscription_id:
        raise ValueError(
            "cloud_budget needs a subscription to scope the budget to; set "
            "azure.subscription_id in your config"
        )
    if not ctx.resource_group_name:
        raise ValueError(
            "cloud_budget needs a resource group to scope the budget to; set "
            "azure.resource_group in your config"
        )
    cfg = ctx.alerts_config.cloud_budget
    today = datetime.now(timezone.utc)
    return {
        "budget-monthly": azure_native.consumption.Budget(
            "budget-monthly",
            opts=pulumi.ResourceOptions(ignore_changes=["timePeriod"]),
            scope=(
                f"/subscriptions/{ctx.subscription_id}"
                f"/resourceGroups/{ctx.resource_group_name}"
            ),
            budget_name=f"{ctx.project_name}-{ctx.environment}-monthly",
            category="Cost",
            time_grain="Monthly",
            amount=cfg.monthly_usd,
            # The start date is the first of the current month at creation;
            # ignore_changes keeps later runs from rewriting it.
            time_period=azure_native.consumption.BudgetTimePeriodArgs(
                start_date=f"{today.year:04d}-{today.month:02d}-01T00:00:00Z"
            ),
            notifications={
                # The action group is the single place receivers live, so a
                # webhook added there also reaches budget notifications. Listing
                # the same addresses in contact_emails would double every mail,
                # but the provider's NotificationArgs requires the argument, so
                # it is passed empty rather than omitted.
                f"actual_{percent}": azure_native.consumption.NotificationArgs(
                    enabled=True,
                    operator="GreaterThan",
                    threshold=percent,
                    threshold_type="Actual",
                    contact_emails=[],
                    contact_groups=[ctx.action_group.id],
                )
                for percent in cfg.notify_at_percent
            },
        )
    }


# Alert name -> builder. Enabled alerts with no builder here are skipped.
_BUILDERS: dict[str, Callable[[_Context], dict[str, pulumi.CustomResource]]] = {
    "gateway_errors": _gateway_errors,
    "gateway_latency": _gateway_latency,
    "replica_restarts": _replica_restarts,
    "db_storage": _db_storage,
    "db_cpu": _db_cpu,
    "backup_job_failures": _backup_job_failures,
    "llm_spend": _llm_spend,
    "cloud_budget": _cloud_budget,
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
    ``log_analytics_workspace`` and ``backup_job`` feed the backup-failure log
    alert; the budget needs only the resource group and the project settings.
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
        location=location,
        log_analytics_workspace=log_analytics_workspace,
        backup_job=backup_job,
        subscription_id=config.azure.subscription_id,
        project_name=config.project.name,
        environment=config.project.environment,
    )
    alerts: dict[str, pulumi.CustomResource] = {}
    for name in alerts_config.enabled_alerts:
        builder = _BUILDERS.get(name)
        if builder is not None:
            alerts.update(builder(ctx))

    return MonitoringResources(action_group=action_group, alerts=alerts)
