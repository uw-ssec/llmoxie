# Monitoring Alerts (PR 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Operators get email alerts for gateway errors and latency, replica
restarts, Postgres storage and CPU, backup job failures, and monthly Azure cost,
all created by the existing Pulumi program from `llmaven-config.yaml`.

**Architecture:** A typed `monitoring.alerts` config block selects alerts per
environment through `enabled_alerts`. A new `resources/monitoring.py` exposes
`create_monitoring(...)`, which `main.py` calls once after every other resource.
It creates one email action group and one Azure resource per enabled alert, and
skips (with a warning) any alert whose target isn't deployed.

**Tech Stack:** Python 3, Pydantic v2, `pulumi-azure-native` 3.29.0 (`monitor`,
`consumption`, `operationalinsights`), pytest with `pulumi.runtime.Mocks`, Pixi.

**Spec:** `docs/superpowers/specs/2026-11-05-monitoring-alerting-design.md`
(sections 1, 2, and 4; sections 3 and 5's PR 2/3 are out of scope).

## Global Constraints

- Pixi only: run everything as `pixi run -e llmaven <cmd>`. No `pip`/`conda`.
- No new dependencies. `pulumi-azure-native` stays `>=3.29.0,<4`.
- Allowed alert names, exactly: `gateway_errors`, `gateway_latency`,
  `replica_restarts`, `db_storage`, `db_cpu`, `backup_job_failures`,
  `cloud_budget`. `llm_spend` is NOT added in this PR.
- Config names describe what is measured; Azure metric names appear only in
  `resources/monitoring.py`.
- Every threshold is absolute (count, ms, USD, or % of resource capacity).
- Schema defaults: `gateway_errors {max_5xx_count: 10, window_minutes: 15}`,
  `gateway_latency {max_avg_ms: 300000, window_minutes: 15}`,
  `replica_restarts {max_count: 3, window_minutes: 30}`,
  `db_storage {max_percent: 80}`,
  `db_cpu {max_percent: 85, window_minutes: 30}`, `backup_job_failures {}`,
  `cloud_budget {monthly_usd: 500, notify_at_percent: [80, 100]}`.
- Per-environment defaults: dev `enabled_alerts: []`; staging and prod all 7.
  `cloud_budget.monthly_usd`: dev 200, staging 300, prod 500.
- A config with no `alerts` block loads with `enabled_alerts: []` and creates no
  `monitor:*` or `consumption:*` resources.
- The action group's Pulumi resource name is `alerts-action-group`, with
  `use_common_alert_schema=True`.
- The budget sets `ignore_changes=["timePeriod"]`.
- Never run `llmaven infra deploy` (including `--preview`) or `infra destroy`
  without explicit human approval (AGENTS.md rule 8).
- Before the first edit to any file, run
  `pixi run -e llmaven okf search --for-path <file>` (AGENTS.md rule 6).
- Commits use conventional format with scope `infra` and an
  `Assisted-by: <harness>:<model>` trailer; never `Signed-off-by:`.

## Review Focus

1. **`window_minutes` outside Azure's allowed window sizes** (for example 10):
   metric alerts only accept 1, 5, 15, 30, 60, 360, 720, or 1440 minutes. Expect
   a config validation error naming the allowed values, not a failed deploy.
   Test in Task 2.
2. **Duplicate entries in `enabled_alerts`** (`[db_cpu, db_cpu]`): expect them
   deduplicated so Pulumi doesn't get two resources with the same name. Test in
   Task 2.
3. **Alerts listed while LiteLLM is disabled** (`litellm.enabled: false`):
   expect the gateway and restart alerts to be skipped with a warning, not a
   crash on a `None` app. Test in Task 4.
4. **`notify_at_percent` empty, or with values ≤ 0 or > 1000:** expect a
   validation error, because Azure rejects a budget with no notifications or
   with an out-of-range threshold. Test in Task 2.
5. **Malformed `email_receivers` entry** (`"ops"`): expect a validation error
   before deploy rather than an Azure 400. Test in Task 2.

---

### Task 1: Confirm the Azure facts the spec left open

No code. These are read-only lookups; they need no deploy. Record each answer in
a new "Verified facts" section at the end of this plan and commit it. If any
answer differs from the assumption below, stop and update the affected task
before implementing it.

**Files:**

- Modify: `docs/superpowers/plans/2026-11-05-monitoring-alerts-pr1.md` (append
  "Verified facts")

| #   | Question                                                               | Assumption used in Tasks 4–6                                                                                       | How to check                                                                                                                                                                                                                                         |
| --- | ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Container Apps metric names and the 5xx dimension                      | `Requests` with dimension `statusCodeCategory` = `5xx`; `ResponseTime` (ms); `RestartCount`                        | [Supported metrics for Microsoft.App/containerApps](https://learn.microsoft.com/en-us/azure/azure-monitor/reference/supported-metrics/microsoft-app-containerapps-metrics), or `az monitor metrics list-definitions --resource <dev litellm app id>` |
| 2   | How streamed responses count toward `ResponseTime`                     | Time until the stream ends                                                                                         | Same docs page; if unknown, note "unconfirmed" and keep the 300000 ms default                                                                                                                                                                        |
| 3   | Does `Microsoft.App/jobs` expose a failed-execution metric?            | No; use KQL on `ContainerAppSystemLogs_CL` filtered by `JobName_s` and a failure `Reason_s`                        | [Supported metrics for Microsoft.App/jobs](https://learn.microsoft.com/en-us/azure/azure-monitor/reference/supported-metrics/microsoft-app-jobs-metrics); for KQL, the failure `Reason_s` values in the dev workspace                                |
| 4   | Postgres Flexible Server metric names                                  | `storage_percent`, `cpu_percent`                                                                                   | [Supported metrics for Microsoft.DBforPostgreSQL/flexibleServers](https://learn.microsoft.com/en-us/azure/azure-monitor/reference/supported-metrics/microsoft-dbforpostgresql-flexibleservers-metrics)                                               |
| 5   | Is `consumption.Budget` supported on the deployment subscription type? | Yes                                                                                                                | Ask the human partner which offer the subscription is on (for example sponsorship or EA), then check [Budgets supported offers](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-acm-create-budgets)                   |
| 6   | Azure Monitor alert pricing                                            | Metric alert ~$0.10 per monitored time series per month; log alert evaluated hourly ~$0.50 per month; budgets free | [Azure Monitor pricing](https://azure.microsoft.com/en-us/pricing/details/monitor/)                                                                                                                                                                  |

- [ ] **Step 1:** Answer each row and append the results to this plan.
- [ ] **Step 2:** Commit:
      `docs(infra): record verified Azure facts for monitoring plan`.

---

### Task 2: Alert config schema, per-environment defaults, and deprecation

**Files:**

- Modify: `src/llmaven/infrastructure/config/schema.py` (`MonitoringConfig` and
  `LLMavenConfig.model_post_init`)
- Modify: `src/llmaven/infrastructure/config/defaults.py` (three
  `MonitoringConfig(...)` calls and the `monitoring:` block of the template)
- Test: `tests/infrastructure/test_monitoring_config.py` (new)

**Interfaces:**

- Produces, in `schema.py`:

  - `AlertName = Literal["gateway_errors", "gateway_latency", "replica_restarts", "db_storage", "db_cpu", "backup_job_failures", "cloud_budget"]`
  - `ALL_ALERTS: tuple[AlertName, ...]`, in the order above
  - `LOG_BASED_ALERTS: frozenset[AlertName] = frozenset({"backup_job_failures"})`
  - `ALLOWED_WINDOW_MINUTES = (1, 5, 15, 30, 60, 360, 720, 1440)`
  - Threshold models with the spec defaults:
    `GatewayErrorsAlert(max_5xx_count: int, window_minutes: int)`,
    `GatewayLatencyAlert(max_avg_ms: int, window_minutes: int)`,
    `ReplicaRestartsAlert(max_count: int, window_minutes: int)`,
    `DbStorageAlert(max_percent: int)`,
    `DbCpuAlert(max_percent: int, window_minutes: int)`,
    `BackupJobFailuresAlert()`,
    `CloudBudgetAlert(monthly_usd: float, notify_at_percent: list[int])`
  - `AlertsConfig` with `email_receivers: list[str] = []`,
    `enabled_alerts: list[AlertName] = []`, and one field per threshold model,
    named exactly like the alert
  - `MonitoringConfig.alerts: AlertsConfig = Field(default_factory=AlertsConfig)`
  - `MonitoringConfig.enable_application_insights` default changes to `False`

- [ ] **Step 1: Write the failing tests** in `test_monitoring_config.py`:

```python
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
```

The defaults for staging and prod enable alerts, so they also need a placeholder
receiver: use `email_receivers: ["ops@example.org"]` in both `defaults.py` and
the template, with a comment telling operators to replace it.

- [ ] **Step 2: Run the tests and confirm they fail**

Run:
`pixi run -e llmaven pytest tests/infrastructure/test_monitoring_config.py -v`
Expected: FAIL with `ImportError` on `AlertsConfig`.

- [ ] **Step 3: Implement the schema**

  - Validate `email_receivers` with a simple `^[^@\s]+@[^@\s]+\.[^@\s]+$` regex
    per entry. That avoids adding `email-validator` as a dependency.
  - Deduplicate `enabled_alerts` in a `field_validator`, keeping order.
  - Check that windows are in `ALLOWED_WINDOW_MINUTES`; the error message lists
    the values joined by `", "`.
  - `notify_at_percent`: `min_length=1`, each value in `1..1000`.
  - Emit the deprecation with `warnings.warn(..., DeprecationWarning)` in a
    `field_validator` on `enable_application_insights`, only when the value is
    `True`.
  - Add the log-analytics check to `LLMavenConfig.model_post_init` next to the
    existing Redis checks, raising `ValueError` that names
    `monitoring.enable_log_analytics`.

- [ ] **Step 4: Update `defaults.py`**

  - Set `enable_application_insights=False` in all three environments.
  - Pass `alerts=AlertsConfig(...)` per the Global Constraints.
  - In the template, drop the `enable_application_insights` line and render an
    `alerts:` block with `email_receivers`, `enabled_alerts` (one per line, or
    `[]`), and `cloud_budget.monthly_usd`. Leave every other threshold to the
    schema defaults, with a comment pointing to the spec.

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `pixi run -e llmaven pytest tests/infrastructure/ -v` Expected: the new
tests PASS and `test_schema_defaults.py` still passes. The cost estimate still
reads `enable_application_insights` until Task 6. Because that setting now
defaults to `False`, a cost test that relied on the old `True` default may
change; if one fails for that reason only, mark it
`xfail(reason="fixed in Task 6")` and remove the marker in Task 6.

- [ ] **Step 6: Commit:**
      `feat(infra): add monitoring.alerts config with per-environment defaults`.

---

### Task 3: Apply `daily_data_cap_gb` to the Log Analytics workspace

**Files:**

- Modify: `src/llmaven/infrastructure/resources/helpers.py`
  (`create_log_analytics_workspace`)
- Modify: `src/llmaven/infrastructure/main.py` (step 6 call)
- Test: `tests/infrastructure/test_monitoring_program.py` (new; harness plus the
  first tests)

**Interfaces:**

- Produces:
  `create_log_analytics_workspace(name, resource_group_name, location, retention_days=90, daily_quota_gb: float | None = None, tags=None) -> operationalinsights.Workspace`.
  When `daily_quota_gb` is not `None`, it passes
  `workspace_capping=WorkspaceCappingArgs(daily_quota_gb=...)`.
- Produces a test harness in `test_monitoring_program.py`:
  `_run(tmp_path, monkeypatch, config_overrides: dict) -> tuple[list[MockResourceArgs], dict[str, list[str]], list[str]]`.
  It returns the resources, the `ignoreChanges` recorded per resource name, and
  any `pulumi.log.warn` messages. Base it on `_run` in
  `tests/infrastructure/test_redis_program.py`:

  - Copy the `_Mocks` class and the stubbing of
    `helpers.create_container_app_with_key_vault_secrets`.
  - The stub must return
    `SimpleNamespace(id=pulumi.Output.from_input(f"{app_name}-id"), configuration=pulumi.Output.from_input(None))`,
    so later tasks can read `.id`.
  - Record `request.ignoreChanges` in the patched `RegisterResource`.
  - Capture warnings by monkeypatching `pulumi.log.warn`.
  - Include the autouse `_reset_pulumi_mocks` fixture.
  - Don't modify `test_redis_program.py`.

- [ ] **Step 1: Write the failing tests**

```python
def test_data_cap_is_applied_to_workspace(tmp_path, monkeypatch):
    resources, _, _ = _run(
        tmp_path, monkeypatch, {"monitoring": {"daily_data_cap_gb": 1.0}}
    )
    [ws] = _by_type(resources, "azure-native:operationalinsights:Workspace")
    assert ws.inputs["workspaceCapping"]["dailyQuotaGb"] == 1.0


def test_null_data_cap_leaves_capping_unset(tmp_path, monkeypatch):
    resources, _, _ = _run(
        tmp_path, monkeypatch, {"monitoring": {"daily_data_cap_gb": None}}
    )
    [ws] = _by_type(resources, "azure-native:operationalinsights:Workspace")
    assert "workspaceCapping" not in ws.inputs


def test_no_alerts_block_creates_no_monitoring_resources(tmp_path, monkeypatch):
    resources, _, _ = _run(tmp_path, monkeypatch, {})
    assert not [
        r
        for r in resources
        if r.typ.startswith(("azure-native:monitor:", "azure-native:consumption:"))
    ]
```

The harness base config enables Log Analytics:
`"monitoring": {"enable_log_analytics": True}`.

- [ ] **Step 2: Run them and confirm the data-cap test fails**

Run:
`pixi run -e llmaven pytest tests/infrastructure/test_monitoring_program.py -v`
Expected: `test_data_cap_is_applied_to_workspace` FAILS with
`KeyError: 'workspaceCapping'`.

- [ ] **Step 3: Implement it.** Add the parameter and pass
      `daily_quota_gb=config.monitoring.daily_data_cap_gb` from `main.py`.

- [ ] **Step 4: Run them and confirm they pass**

Run: `pixi run -e llmaven pytest tests/infrastructure/ -v` Expected: PASS.

- [ ] **Step 5: Commit:**
      `feat(infra): apply monitoring.daily_data_cap_gb to Log Analytics`.

---

### Task 4: Action group and metric alerts

**Files:**

- Create: `src/llmaven/infrastructure/resources/monitoring.py`
- Modify: `src/llmaven/infrastructure/resources/__init__.py` (export
  `create_monitoring`)
- Modify: `src/llmaven/infrastructure/main.py`:
  - Initialize `mlflow_app = litellm_app = backup_job = None` before step 8.
  - Assign the result of `create_backup_job(...)` to `backup_job`.
  - Call `create_monitoring(...)` just before "Export common outputs".
- Test: `tests/infrastructure/test_monitoring_program.py`

**Interfaces:**

- Consumes: `AlertsConfig`, the threshold models, and `ALL_ALERTS` from Task 2;
  the `_run` harness from Task 3.
- Produces:

```python
@dataclass
class MonitoringResources:
    action_group: azure_native.monitor.ActionGroup
    alerts: dict[str, pulumi.CustomResource]  # Pulumi resource name -> resource

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
) -> MonitoringResources | None  # None when enabled_alerts is empty
```

Pulumi resource names (tests assert these): `alerts-action-group`,
`alert-gateway-errors`, `alert-gateway-latency`,
`alert-replica-restarts-litellm`, `alert-replica-restarts-mlflow`,
`alert-db-storage`, `alert-db-cpu`; Task 5 adds `alert-backup-job-failures` and
`budget-monthly`.

Metric alert settings:

- **Shared:**
  - `location="global"`, `scopes=[target.id]`, `evaluation_frequency="PT5M"`.
  - `window_size=f"PT{window_minutes}M"` (or `PT1H`/`PT6H`/`PT12H`/`PT24H` for
    60 minutes and above).
  - `db_storage` uses a fixed `PT15M` window.
  - `auto_mitigate=True`;
    `actions=[MetricAlertActionArgs(action_group_id=action_group.id)]`.
  - Criteria are a single `MetricCriteriaArgs` in
    `MetricAlertSingleResourceMultipleMetricCriteriaArgs` with
    `criterion_type="StaticThresholdCriterion"` and `operator="GreaterThan"`.
- **Per alert** (metric, aggregation, severity):
  - `gateway_errors`: `Requests`, `Total`, dimension
    `statusCodeCategory Include ["5xx"]`, severity 1.
  - `gateway_latency`: `ResponseTime`, `Average`, severity 2.
  - `replica_restarts`: `RestartCount`, `Total`, severity 2.
  - `db_storage`: `storage_percent`, `Maximum`, severity 1.
  - `db_cpu`: `cpu_percent`, `Average`, severity 2.
  - These are the names from Task 1; use the verified names if they differ.
- **Action group:** `group_short_name` = `"llmoxie"` (12 characters max), one
  `EmailReceiverArgs(name=f"email-{i}", email_address=addr, use_common_alert_schema=True)`
  per receiver.

- [ ] **Step 1: Write the failing tests**

```python
ALL_ON = {
    "monitoring": {
        "enable_log_analytics": True,
        "alerts": {
            "email_receivers": ["ops@example.org", "dev@example.org"],
            "enabled_alerts": [
                "gateway_errors",
                "gateway_latency",
                "replica_restarts",
                "db_storage",
                "db_cpu",
            ],
        },
    }
}


def test_action_group_emails_everyone_with_common_schema(tmp_path, monkeypatch):
    resources, _, _ = _run(tmp_path, monkeypatch, ALL_ON)
    [ag] = _by_type(resources, "azure-native:monitor:ActionGroup")
    assert ag.name == "alerts-action-group"
    assert [r["emailAddress"] for r in ag.inputs["emailReceivers"]] == [
        "ops@example.org",
        "dev@example.org",
    ]
    assert all(r["useCommonAlertSchema"] for r in ag.inputs["emailReceivers"])


def test_metric_alerts_target_metric_and_threshold(tmp_path, monkeypatch):
    resources, _, _ = _run(tmp_path, monkeypatch, ALL_ON)
    alerts = {
        r.name: r.inputs
        for r in _by_type(resources, "azure-native:monitor:MetricAlert")
    }
    assert set(alerts) == {
        "alert-gateway-errors",
        "alert-gateway-latency",
        "alert-replica-restarts-litellm",
        "alert-replica-restarts-mlflow",
        "alert-db-storage",
        "alert-db-cpu",
    }
    crit = alerts["alert-gateway-errors"]["criteria"]["allOf"][0]
    assert (crit["metricName"], crit["threshold"], crit["timeAggregation"]) == (
        "Requests",
        10,
        "Total",
    )
    assert crit["dimensions"][0]["values"] == ["5xx"]
    assert alerts["alert-gateway-errors"]["windowSize"] == "PT15M"
    assert alerts["alert-gateway-errors"]["scopes"] == ["llmaven-dev-litellm-id"]
    assert alerts["alert-db-cpu"]["criteria"]["allOf"][0]["threshold"] == 85
    assert alerts["alert-db-storage"]["scopes"] == ["postgres-server-dev-id"]
    for a in alerts.values():
        assert a["actions"][0]["actionGroupId"] == "alerts-action-group-id"


def test_mlflow_disabled_skips_only_mlflow_restart_alert(tmp_path, monkeypatch):
    resources, _, warnings = _run(
        tmp_path, monkeypatch, {**ALL_ON, "mlflow": {"enabled": False}}
    )
    names = {r.name for r in _by_type(resources, "azure-native:monitor:MetricAlert")}
    assert "alert-replica-restarts-litellm" in names
    assert "alert-replica-restarts-mlflow" not in names
    assert any("mlflow" in w.lower() for w in warnings)


def test_litellm_disabled_skips_gateway_alerts_without_crashing(tmp_path, monkeypatch):
    resources, _, warnings = _run(
        tmp_path, monkeypatch, {**ALL_ON, "litellm": {"enabled": False}}
    )
    names = {r.name for r in _by_type(resources, "azure-native:monitor:MetricAlert")}
    assert (
        not {
            "alert-gateway-errors",
            "alert-gateway-latency",
            "alert-replica-restarts-litellm",
        }
        & names
    )
    assert {"alert-db-storage", "alert-db-cpu"} <= names
    assert any("litellm" in w.lower() for w in warnings)
```

The mock returns `f"{name}-id"` as each resource's ID. `postgres-server-dev` is
the Pulumi name in `resources/database.py`, and `llmaven-dev-litellm` is the
`app_name` the stubbed app helper records. MLflow is enabled by default in the
harness config, so `alert-replica-restarts-mlflow` exists in `ALL_ON`.

- [ ] **Step 2: Run them and confirm they fail**

Run:
`pixi run -e llmaven pytest tests/infrastructure/test_monitoring_program.py -v`
Expected: the new tests FAIL; there is no ActionGroup.

- [ ] **Step 3: Implement `monitoring.py` and wire it into `main.py`.** Use one
      small builder per alert. For each name in `enabled_alerts`:

  - Look up its target.
  - If the target is `None`, call
    `pulumi.log.warn(f"monitoring: {name} skipped, <target> is not deployed")`.
  - Otherwise create the resource.

- [ ] **Step 4: Run them and confirm they pass**

Run: `pixi run -e llmaven pytest tests/infrastructure/ -v` Expected: PASS,
including `test_redis_program.py`.

- [ ] **Step 5: Commit:**
      `feat(infra): add email action group and metric alerts`.

---

### Task 5: Backup-failure log alert and monthly cost budget

**Files:**

- Modify: `src/llmaven/infrastructure/resources/monitoring.py`
- Test: `tests/infrastructure/test_monitoring_program.py`

**Interfaces:**

- Consumes: `create_monitoring` and `MonitoringResources` from Task 4.
- Produces: resources `alert-backup-job-failures` (`monitor.ScheduledQueryRule`)
  and `budget-monthly` (`consumption.Budget`), added to
  `MonitoringResources.alerts`.

Log alert settings:

- `kind="LogAlert"`, `location=location`, `scopes=[log_analytics_workspace.id]`,
  `severity=1`.
- `evaluation_frequency="PT1H"`, `window_size="PT1H"`.
- One condition: the KQL from Task 1 row 3, filtered to
  `JobName_s == "<job_name>"`. Get the job name from the `job_name` output of
  the `backup_job` resource.
- `time_aggregation="Count"`, `operator="GreaterThan"`, `threshold=0`.
- `actions=ActionsArgs(action_groups=[action_group.id])`.

Budget settings:

- `scope=f"/subscriptions/{config.azure.subscription_id}/resourceGroups/{resource_group_name}"`.
- `budget_name=f"{project}-{environment}-monthly"`, `category="Cost"`,
  `time_grain="Monthly"`, `amount=monthly_usd`.
- `time_period=BudgetTimePeriodArgs(start_date=f"{today.year:04d}-{today.month:02d}-01T00:00:00Z")`,
  where `today = datetime.now(timezone.utc)`.
- `opts=ResourceOptions(ignore_changes=["timePeriod"])`.
- One notification per percent, keyed `f"actual_{p}"`:
  `NotificationArgs(enabled=True, operator="GreaterThan", threshold=p, threshold_type="Actual", contact_emails=email_receivers, contact_groups=[action_group.id])`.

- [ ] **Step 1: Write the failing tests** (import `ALL_ALERTS` from
      `llmaven.infrastructure.config.schema`)

```python
FULL = {
    "monitoring": {
        "enable_log_analytics": True,
        "alerts": {
            "email_receivers": ["ops@example.org"],
            "enabled_alerts": list(ALL_ALERTS),
            "cloud_budget": {"monthly_usd": 300, "notify_at_percent": [50, 100]},
        },
    },
    "backup_job": {"enabled": True},
}


def test_backup_failure_rule_targets_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("LLMAVEN_SECRETS_BACKUP_STORAGE_CONNECTION_STRING", "x")
    resources, _, _ = _run(tmp_path, monkeypatch, FULL)
    [rule] = _by_type(resources, "azure-native:monitor:ScheduledQueryRule")
    assert rule.name == "alert-backup-job-failures"
    assert rule.inputs["scopes"] == ["log-analytics-id"]
    assert rule.inputs["actions"]["actionGroups"] == ["alerts-action-group-id"]


def test_backup_disabled_skips_rule_with_warning(tmp_path, monkeypatch):
    cfg = {**FULL, "backup_job": {"enabled": False}}
    resources, _, warnings = _run(tmp_path, monkeypatch, cfg)
    assert not _by_type(resources, "azure-native:monitor:ScheduledQueryRule")
    assert any("backup_job_failures" in w for w in warnings)


def test_budget_notifies_action_group_and_ignores_time_period(tmp_path, monkeypatch):
    monkeypatch.setenv("LLMAVEN_SECRETS_BACKUP_STORAGE_CONNECTION_STRING", "x")
    resources, ignore, _ = _run(tmp_path, monkeypatch, FULL)
    [budget] = _by_type(resources, "azure-native:consumption:Budget")
    assert budget.inputs["amount"] == 300
    assert budget.inputs["timePeriod"]["startDate"].endswith("-01T00:00:00Z")
    notes = budget.inputs["notifications"]
    assert set(notes) == {"actual_50", "actual_100"}
    assert notes["actual_100"]["contactGroups"] == ["alerts-action-group-id"]
    assert "timePeriod" in ignore["budget-monthly"]
```

- [ ] **Step 2: Run them and confirm they fail**

Run:
`pixi run -e llmaven pytest tests/infrastructure/test_monitoring_program.py -v`
Expected: the three new tests FAIL.

- [ ] **Step 3: Implement both builders** in `monitoring.py`.

- [ ] **Step 4: Run them and confirm they pass**

Run: `pixi run -e llmaven pytest tests/infrastructure/ -v` Expected: PASS.

- [ ] **Step 5: Commit:**
      `feat(infra): alert on backup job failures and monthly Azure cost`.

---

### Task 6: Cost estimate

**Files:**

- Modify: `src/llmaven/deployment/validate.py` (`estimate_monthly_cost`, near
  the "# Monitoring costs" block)
- Modify: `tests/infrastructure/test_cost_estimate.py`
  - In `_minimal_config`, drop `enable_application_insights=False`; it's the
    default now.
  - Add tests.

**Interfaces:**

- Produces: `estimate_alerts_monthly_cost(config: LLMavenConfig) -> float` and
  module constants `METRIC_ALERT_MONTHLY_COST`, `LOG_ALERT_MONTHLY_COST`, set to
  the prices verified in Task 1, row 6.
  - Count one metric alert for each enabled `gateway_errors`, `gateway_latency`,
    `db_storage` and `db_cpu`.
  - Count `replica_restarts` once per enabled app (LiteLLM, MLflow).
  - Count `backup_job_failures` as one log alert, only when
    `backup_job.enabled`.
  - `cloud_budget` costs 0.
- `estimate_monthly_cost` no longer reads `enable_application_insights`; it adds
  `estimate_alerts_monthly_cost(config)` to both the minimum and the maximum.

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run them and confirm they fail.** Run
      `pixi run -e llmaven pytest tests/infrastructure/test_cost_estimate.py -v`.
      Expected: FAIL; App Insights still adds $5–20.
- [ ] **Step 3: Implement it.**
- [ ] **Step 4: Run them and confirm they pass.** Run the same command.
      Expected: PASS.
- [ ] **Step 5: Commit:**
      `feat(infra): estimate alert rule costs; drop App Insights from estimate`.

---

### Task 7: Docs, full verification, and the manual check handoff

**Files:**

- Modify: `README.md`, section "Azure Resources Created" (around line 248): add
  the action group, metric and log alert rules, and the budget, and say they're
  created only for alerts listed in `monitoring.alerts.enabled_alerts`. Add a
  short "Alerting" subsection under "Azure Infrastructure Deployment" that
  covers:

  - Each alert name and what it watches.
  - That thresholds are absolute.
  - That `enable_application_insights` is deprecated.
  - That the Azure budget doesn't cover non-Azure LLM spend until PR 2.

- [ ] **Step 1:** Write the docs.
- [ ] **Step 2:** Run `pixi run -e llmaven verify`. Expected: pytest and
      `okf-validate` pass. Pre-commit passes for every file this PR touches. If
      `docker/README.md` fails as it does on `main`, report it as pre-existing
      and don't reformat it.
- [ ] **Step 3:** Commit: `docs(infra): document monitoring alerts`.
- [ ] **Step 4: Stop for the human partner.** The agent does not deploy. Hand
      over the manual checks from spec section 4 and ask them to run and record
      them in the PR description:
  1. `llmaven infra deploy --preview` on dev, with alerts enabled in the dev
     config, shows only additions plus the in-place workspace update.
  2. After the deploy, `--expect-no-changes` comes back clean.
  3. Azure's "Test action group" email arrives.
  4. One real alert fires: restart LiteLLM, or temporarily lower a threshold.

---

## Verified facts

_(Filled in by Task 1.)_
