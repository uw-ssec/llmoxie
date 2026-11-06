# Monitoring and Alerting Design

- **Date:** 2026-11-05
- **Issue:** [#193](https://github.com/uw-ssec/llmoxie/issues/193), section 4
  ("Monitoring and alerting")
- **Status:** Draft, awaiting review

## Goal

Operators of an LLMoxie deployment get an email when the gateway, its database,
its backups, or its cloud bill need attention. Every monitor is defined as code
in the existing Pulumi program and configured from `llmaven-config.yaml`.

## Context

- The Pulumi program (`src/llmaven/infrastructure/main.py`) already creates a
  Log Analytics workspace when `monitoring.enable_log_analytics` is true and
  wires it into the Container Apps environment. Container logs land there today;
  nothing queries them.
- `monitoring.enable_application_insights` and `monitoring.daily_data_cap_gb`
  are parsed but create nothing. Their only consumer is the cost estimate
  (`src/llmaven/deployment/validate.py`).
- No action groups, alert rules, or budgets exist.
- Traffic is low and bursty (a research user base, not a steady consumer web
  service). Percentage-of-traffic thresholds would be noisy, so every threshold
  in this design is absolute.
- The pinned `pulumi-azure-native` (3.29.0) provides `monitor.ActionGroup`,
  `monitor.MetricAlert`, `monitor.ScheduledQueryRule`, and `consumption.Budget`.
  No dependency change is needed.

## Decisions

| Topic                         | Decision                                                                                                                                            |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Notification channel          | Email only. One action group, designed so webhook receivers can be added later without touching alert rules.                                        |
| Spend monitoring              | Azure Consumption Budget on the resource group now. An alert on total LiteLLM spend follows in PR 2.                                                |
| Thresholds                    | Fixed values from config. No anomaly detection.                                                                                                     |
| `daily_data_cap_gb`           | Implemented on the Log Analytics workspace.                                                                                                         |
| `enable_application_insights` | Deprecated. Still accepted; logs a warning; creates nothing.                                                                                        |
| Code structure                | One new module, `resources/monitoring.py`, with typed config (approach 1 of 3 considered).                                                          |
| Per-environment selection     | An explicit `enabled_alerts` list per config file.                                                                                                  |
| Portability                   | Config names describe what is measured, not Azure metric names. All Azure-specific code stays in `monitoring.py`. No multi-cloud abstraction layer. |

## Section 1: Configuration

### Schema

```yaml
monitoring:
  retention_days: 90
  enable_log_analytics: true
  daily_data_cap_gb: 1.0 # applied to the workspace; null = no cap
  enable_application_insights: false # deprecated, no effect
  alerts:
    email_receivers: [ops@example.org]
    enabled_alerts:
      - gateway_errors
      - gateway_latency
      - replica_restarts
      - db_storage
      - db_cpu
      - backup_job_failures
      - cloud_budget
    gateway_errors: { max_5xx_count: 10, window_minutes: 15 }
    gateway_latency: { max_avg_ms: 300000, window_minutes: 15 }
    replica_restarts: { max_count: 3, window_minutes: 30 }
    db_storage: { max_percent: 80 }
    db_cpu: { max_percent: 85, window_minutes: 30 }
    backup_job_failures: {}
    cloud_budget: { monthly_usd: 500, notify_at_percent: [80, 100] }
```

### Rules

- `enabled_alerts` is the only switch. Each entry must be one of the allowed
  alert names (a `Literal` type), so a typo fails validation. An empty list
  turns alerting off.
- Threshold blocks are optional. Omitted blocks use the schema defaults shown
  above.
- `email_receivers` is required when `enabled_alerts` is not empty.
- If `enable_log_analytics` is false, listing a log-based alert
  (`backup_job_failures`) fails validation.
- Configs written before this change, with no `alerts` block, load with
  `enabled_alerts: []`, so deploys of existing stacks show no new resources.
- Recipient emails go in `llmaven-config.yaml`, which is gitignored. They are
  not secrets.
- `gateway_latency` defaults to a 5-minute average because LLM calls, especially
  streamed ones, are long. The alert mainly catches hung requests.

### Per-environment defaults

`defaults.py` and the `infra init` template set these per environment. Dollar
amounts are placeholders; operators set real values in their own config.

| Setting                    | dev             | staging         | prod            |
| -------------------------- | --------------- | --------------- | --------------- |
| `enabled_alerts`           | `[]`            | all 7           | all 7           |
| `cloud_budget.monthly_usd` | 200             | 300             | 500             |
| Other thresholds           | schema defaults | schema defaults | schema defaults |

## Section 2: Pulumi resources

`main.py` calls `create_monitoring(...)` once, after every other resource. It
passes in the workspace, the LiteLLM app, the MLflow app, the Postgres server,
and the backup job. Any of these can be `None`.

### Action group

One `monitor.ActionGroup` with the Pulumi resource name `alerts-action-group`.
It has `use_common_alert_schema=True` and one email receiver per configured
address. Every alert below references its ID, so adding a webhook receiver later
changes only this resource.

### Alerts

| Alert name            | Azure resource     | Target                                  | Condition                                                                                                                                                                                                        |
| --------------------- | ------------------ | --------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `gateway_errors`      | MetricAlert        | LiteLLM app                             | `Requests` filtered to 5xx status codes, total > `max_5xx_count` over `window_minutes`                                                                                                                           |
| `gateway_latency`     | MetricAlert        | LiteLLM app                             | `ResponseTime` average > `max_avg_ms` over `window_minutes`                                                                                                                                                      |
| `replica_restarts`    | MetricAlert        | LiteLLM app, plus MLflow app if enabled | `RestartCount` maximum > `max_count`, split per `podName`, over `window_minutes`; `RestartCount` is cumulative per replica, so this means "a replica has restarted more than `max_count` times since it started" |
| `db_storage`          | MetricAlert        | Postgres server                         | `storage_percent` maximum > `max_percent`                                                                                                                                                                        |
| `db_cpu`              | MetricAlert        | Postgres server                         | `cpu_percent` average > `max_percent` over `window_minutes`                                                                                                                                                      |
| `backup_job_failures` | ScheduledQueryRule | Workspace                               | KQL over `ContainerAppSystemLogs_CL` finds a failed execution of the backup job                                                                                                                                  |
| `cloud_budget`        | consumption.Budget | Resource group                          | Actual monthly cost crosses each `notify_at_percent` of `monthly_usd`; notifies the action group                                                                                                                 |

### Behavior

- **Missing targets:** if an alert is listed but its target is not deployed, the
  program logs a warning and skips it. For example, `backup_job_failures` is
  skipped when the backup job is disabled. `replica_restarts` skips only the
  MLflow part when MLflow is disabled.
- **Data cap:** `daily_data_cap_gb` sets `workspace_capping.daily_quota_gb` on
  the existing workspace (an in-place update). `null` leaves it unset.
- **Budget start date:** Azure requires a start date on the first of a month.
  The program computes it once and sets `ignore_changes=["time_period"]` so
  `deploy --expect-no-changes` stays clean month to month.
- **Cost estimate:** `validate.py` stops counting Application Insights and adds
  the alert rules (roughly $0.10–3 per rule per month depending on type and
  frequency; confirm against current Azure Monitor pricing when implementing).

### Known limitations

- When the dev workspace reaches its daily data cap, log-based alerts see no
  data until the cap resets.
- Log Analytics ingestion takes a few minutes, so log-based alerts are near-real
  time, not instant.
- Until PR 2 lands, the Azure budget is the only spend guard. It covers Azure
  costs (including Azure OpenAI) but not other providers such as Anthropic.

### To verify during implementation

If any answer differs from the assumption, update the plan instead of
improvising.

1. The exact metric and dimension names for Container Apps (`Requests` with a
   status-code dimension, `ResponseTime`, `RestartCount`), and how streamed
   responses count toward `ResponseTime`.
2. Whether Container Apps Jobs expose a failed-execution metric. If they do,
   `backup_job_failures` becomes a cheaper MetricAlert instead of KQL.
3. Whether `consumption.Budget` is supported on the deployment's subscription
   type.

## Section 3: Spend log line and `llm_spend` alert (PR 2)

This is a follow-up, not part of PR 1.

- A new `SpendLogger` LiteLLM callback in `resources/spend_logger.py`, shipped
  through `extra_modules` like `adl_logger.py`. It is separate from `AdlLogger`
  so it does not depend on storage and never reads prompt content.
- On each successful request it prints one line to stdout, built from
  `standard_logging_object`:

  ```text
  LLMOXIE_SPEND {"ts":"...","request_id":"...","key_alias":"...","key_hash":"...","user_id":"...","team_alias":"...","model":"...","spend":0.0123,"total_tokens":4567}
  ```

  The line has no prompt, no response, and no raw key. Exceptions are caught and
  logged; a request never fails because of this callback.

- `docker/config.yaml` lists the new callback next to `adl_logger`. A deploy
  warns if `llm_spend` is enabled and the LiteLLM config file does not reference
  `spend_logger`.
- `llm_spend` becomes an allowed alert name, with
  `{max_usd_per_hour: null, max_usd_per_day: 50}`. Each non-null threshold
  creates one ScheduledQueryRule:

  ```kusto
  ContainerAppConsoleLogs_CL
  | where ContainerAppName_s == "<litellm app>" and Log_s startswith "LLMOXIE_SPEND "
  | extend r = parse_json(substring(Log_s, 14))
  | summarize spend = sum(todouble(r.spend))
  ```

- These log lines are best effort. LiteLLM's Postgres spend logs stay the source
  of truth.

## Section 4: Testing and verification

### Schema unit tests

- `enabled_alerts` rejects unknown names.
- An empty list needs no receivers; a non-empty list without receivers fails.
- A log-based alert with `enable_log_analytics: false` fails.
- `enable_application_insights: true` loads and logs a deprecation warning.
- A config with no `alerts` block loads with no alerts enabled.
- Per-environment defaults round-trip through `defaults.py` and the `infra init`
  template.

### Program tests

`tests/infrastructure/test_monitoring_program.py` runs the whole program under
`pulumi.runtime.Mocks`, following `test_redis_program.py`.

- **Alerting off:** no `monitor:*` or `consumption:*` resources are created.
- **All alerts on:** one ActionGroup with the configured emails and the common
  schema. Each MetricAlert targets the right resource, metric, and threshold.
  The ScheduledQueryRule targets the workspace. The Budget sets
  `ignore_changes=["time_period"]`. Every alert references the action group ID.
- **Missing targets:** with the backup job disabled, `backup_job_failures` is
  skipped with a warning and no crash. Same for MLflow and `replica_restarts`.
- **Data cap:** `daily_data_cap_gb` reaches `workspace_capping.daily_quota_gb`;
  `null` leaves it unset.
- **Cost estimate:** no longer counts Application Insights; includes the alert
  rules.

### Manual checks on a dev deployment

Record the results in the PR description.

1. `llmaven infra deploy --preview` shows only additions plus the in-place
   workspace update. After the deploy, `--expect-no-changes` is clean.
2. Azure's "Test action group" sends an email that arrives.
3. A real alert fires: restart LiteLLM (scale to 0 and back) or temporarily
   lower a threshold, and confirm the email.
4. Resolve the three "to verify" items from section 2.

Gate: `pixi run -e llmaven verify`.

## Section 5: Delivery

| PR  | Contents                                                                                                                                                                                                                                                                                                                                                          | Depends on                                                 |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| 1   | Sections 1, 2, and 4: schema, defaults, data cap, Application Insights deprecation, `monitoring.py`, tests, docs, cost estimate                                                                                                                                                                                                                                   | —                                                          |
| 2   | Section 3: `SpendLogger`, config wiring, `llm_spend` alert                                                                                                                                                                                                                                                                                                        | PR 1                                                       |
| 3   | `llmaven ops spend-report`: spend by key or user over a date range, read from LiteLLM `/spend/logs` (existing extract client) or an existing extract zip. Rich table, optional CSV or PNG, rows flagged against a trailing baseline. Adds an `investigate` custom property with this command to the `llm_spend` rules and confirms it appears in the alert email. | PR 2 for the email hint; the command alone needs only PR 1 |

### Follow-up issues (out of scope)

1. Webhook receivers (Teams, Slack, or PagerDuty) on the action group. The URL
   comes from an env var; Slack needs a payload translator.
2. LiteLLM native alerting (`ms_teams` or Slack) for per-key budgets, LLM
   exceptions, and spend reports. Pairs with item 1.
3. Per-key and per-user spend-spike detection with anomaly detection, once there
   are weeks of spend-line data.
4. Application Insights through the Container Apps OpenTelemetry agent. See
   [App Insights overview](https://learn.microsoft.com/en-us/azure/azure-monitor/app/app-insights-overview)
   and
   [Container Apps OpenTelemetry agents](https://learn.microsoft.com/en-us/azure/container-apps/opentelemetry-agents).
