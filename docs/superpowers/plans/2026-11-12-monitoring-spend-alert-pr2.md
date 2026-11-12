# Monitoring and Alerting, PR 2: LLM Spend Alert Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `llm_spend` alert. A new LiteLLM callback prints one
`LLMOXIE_SPEND {json}` line per successful request. Log Analytics sums those
lines, and a ScheduledQueryRule fires when spend in a window passes a threshold.

**Architecture:** `resources/spend_logger.py` is a standard-library-only
`CustomLogger`. It ships to the gateway the same way `adl_logger.py` does: an
`extra_modules` entry mounted beside `config.yaml`. The schema gains
`LlmSpendAlert`, and `monitoring.py` gains an `_llm_spend` builder that makes
one rule per non-null threshold. Deploy and `validate` warn, without failing,
when `llm_spend` is enabled but the LiteLLM config does not list the callback.

**Tech Stack:** Python 3.12, Pydantic v2, Pulumi with `pulumi-azure-native`
3.29.0, LiteLLM v1.108.6 (`CustomLogger`), and Azure Monitor
ScheduledQueryRule (KQL on `ContainerAppConsoleLogs_CL`).

**Spec:** `docs/superpowers/specs/2026-11-05-monitoring-alerting-design.md`,
section 3 ("LLM spend alert"). PR 3 is not part of this plan. It covers
`ops spend-report` and the `investigate` property.

## Global Constraints

- **Pixi only.**
  - Run every command as `pixi run -e llmaven <task>`.
  - Run tests with `pixi run -e llmaven pytest <path> -q`.
  - The gate is `pixi run -e llmaven verify`.
- **`litellm` is not installed in the `llmaven` environment.**
  - Tests stub `litellm`, `litellm.integrations` and
    `litellm.integrations.custom_logger` in `sys.modules`.
  - They load `spend_logger.py` with `importlib.util.spec_from_file_location`.
  - Do not add `litellm` as a dependency.
- **The logger may import only the standard library and LiteLLM.** The gateway
  image has nothing else.
- **No prompt, response or raw key in the spend line**
  (`facts/request-log-sources-differ`). Only the fields in the spec's example
  line are allowed.
- **Spend lines are best effort.** Postgres `LiteLLM_SpendLogs` stays the
  source of truth. The logger must never raise into LiteLLM.
- **Rolling out the logger** (`architecture/litellm-config-and-logger-mounted-as-secrets`):
  - A changed mounted file reaches running containers only when a new revision
    rolls.
  - `REFRESH_TRIGGER` does this by default.
  - A pinned `litellm.refresh_trigger` must be bumped.
  - A set `revision_suffix` must change.
- **Keep deployed identifiers** (`decisions/rebrand-keeps-deployed-identifiers`).
  - New Pulumi logical names are `alert-llm-spend-hourly` and
    `alert-llm-spend-daily`.
  - Rename nothing that already exists.
- **Before the first edit to each file**, run
  `pixi run -e llmaven okf search --for-path <file>`. Edit `knowledge/` only
  through the `okf` CLI.
- **No live infrastructure** (no deploy, `--preview` or destroy) without
  explicit user approval. Task 8's manual check is opt-in.
- **Commits:**
  - Conventional format with scope `infra`.
  - Add an `Assisted-by: <harness>:<model>` trailer.
  - Never add `Signed-off-by:`.

## Review Focus

1. **Both thresholds null.** `LlmSpendAlert(max_usd_per_hour=None,
   max_usd_per_day=None)` must fail validation. It must not deploy a no-op
   alert. Test in Task 4.
2. **LiteLLM disabled.** With `llm_spend` enabled and `litellm.enabled=false`,
   no rule is created, a skip warning is logged, and the cost estimate adds
   nothing. Test in Tasks 5 and 6.
3. **Config without `spend_logger`.** Deploy and `validate` warn but do not
   fail. The repo's `docker/config.yaml` must not warn. Test in Task 6.
4. **Missing data in `standard_logging_object`.** A missing `metadata`, a
   `response_cost` of `None` or an absent `total_tokens` produces a line with
   `0`/`null` values and no exception. Test in Task 2.
5. **Leaks.** No prompt, response, `messages` or raw `api_key` text may appear
   in the line, even when present in `kwargs`. Test in Task 2.

---

### Task 1: Verify external facts

**Files:**

- Modify: this plan (the `## Verified facts` table)

**Interfaces:** none.

| #   | Question | Assumption used in Tasks 2–6 | How to check |
| --- | -------- | ---------------------------- | ------------ |
| 1   | Does `litellm_settings.callbacks` accept a YAML list of `module.instance` entries in v1.108.6? | Yes: `[adl_logger.proxy_handler_instance, spend_logger.proxy_handler_instance]` | LiteLLM proxy docs ("Custom Callbacks"); `litellm/proxy/proxy_server.py` at tag `v1.108.6` (search `callbacks`) |
| 2   | Which `StandardLoggingPayload` keys hold the fields? | `id`, `model`, `response_cost`, `total_tokens`; `metadata.user_api_key_alias`, `metadata.user_api_key_hash`, `metadata.user_api_key_user_id`, `metadata.user_api_key_team_alias` | `litellm/types/utils.py` (`StandardLoggingPayload`, `StandardLoggingMetadata`) at `v1.108.6` |
| 3   | Is `user_api_key_hash` the hashed token, never the raw key? | Yes, it is the SHA-256 token as stored in `LiteLLM_VerificationToken` | Same file and `litellm/proxy/litellm_pre_call_utils.py` |
| 4   | Do Container Apps console logs land in `ContainerAppConsoleLogs_CL` with `ContainerAppName_s` and `Log_s`, and does stdout from a callback land there? | Yes (classic `_CL` schema, as already used by `BACKUP_FAILURE_QUERY`) | Azure docs "Monitor logs in Azure Container Apps with Log Analytics" |
| 5   | Does a ScheduledQueryRule condition accept `time_aggregation="Total"` with `metric_measure_column="spend"`? | Yes | `azure-native` `monitor.ConditionArgs` docs; Azure "Log search alert rule" REST reference |
| 6   | Is `window_size="P1D"` valid with `evaluation_frequency="PT1H"`? | Yes (max window 2 days; frequency ≤ window) | Azure docs "Create a log search alert", window and frequency limits |
| 7   | What does a log search rule cost per month at PT1H? | `LOG_ALERT_MONTHLY_COST = 0.50` is still close enough | Azure Monitor pricing page, "Log search alerts" |
| 8   | Does a callback's `print(..., flush=True)` reach container stdout under LiteLLM's proxy server (uvicorn/gunicorn workers)? | Yes | LiteLLM source for stdout redirection; the Task 8 manual check confirms it |

- [ ] **Step 1: Answer each row.** Fill in the `## Verified facts` table at the
      end of this plan. If an answer contradicts an assumption, stop and update
      the affected task before continuing. Row 2 key names feed Task 2; rows 5
      and 6 feed Task 5; row 7 feeds Task 6.
- [ ] **Step 2: Commit.**

```bash
git add docs/superpowers/plans/2026-11-12-monitoring-spend-alert-pr2.md
git commit -m "docs(infra): verify facts for the llm_spend alert plan"
```

---

### Task 2: `SpendLogger` callback

**Files:**

- Create: `src/llmaven/infrastructure/resources/spend_logger.py`
- Create: `tests/infrastructure/test_spend_logger.py`

**Interfaces:**

- `SPEND_LINE_PREFIX = "LLMOXIE_SPEND "` (14 characters; the KQL uses
  `substring(Log_s, 14)`).
- `def spend_record(payload: dict[str, Any]) -> dict[str, Any]`: pure, builds
  the record.
- `class SpendLogger(CustomLogger)` with
  `async def async_log_success_event(self, kwargs, response_obj, start_time, end_time) -> None`.
- `proxy_handler_instance = SpendLogger()`.

- [ ] **Step 1: Write the failing tests.**

```python
"""Tests for the LiteLLM spend logger callback (loaded without LiteLLM)."""

import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

LOGGER_PATH = (
    Path(__file__).parents[2]
    / "src/llmaven/infrastructure/resources/spend_logger.py"
)


@pytest.fixture
def spend_logger(monkeypatch):
    custom_logger = types.ModuleType("litellm.integrations.custom_logger")
    custom_logger.CustomLogger = type("CustomLogger", (), {})
    monkeypatch.setitem(sys.modules, "litellm", types.ModuleType("litellm"))
    monkeypatch.setitem(
        sys.modules, "litellm.integrations", types.ModuleType("litellm.integrations")
    )
    monkeypatch.setitem(
        sys.modules, "litellm.integrations.custom_logger", custom_logger
    )
    spec = importlib.util.spec_from_file_location("spend_logger", LOGGER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _payload(**overrides):
    payload = {
        "id": "req-1",
        "model": "gpt-4o",
        "response_cost": 0.0123,
        "total_tokens": 4567,
        "messages": [{"role": "user", "content": "SECRET PROMPT"}],
        "response": {"choices": [{"message": {"content": "SECRET RESPONSE"}}]},
        "metadata": {
            "user_api_key_alias": "alice-key",
            "user_api_key_hash": "abc123hash",
            "user_api_key_user_id": "alice",
            "user_api_key_team_alias": "team-a",
        },
    }
    payload.update(overrides)
    return payload


def _emit(module, kwargs):
    asyncio.run(
        module.proxy_handler_instance.async_log_success_event(kwargs, None, None, None)
    )


def _only_line(out: str) -> dict:
    [line] = out.splitlines()
    assert line.startswith("LLMOXIE_SPEND ")
    return json.loads(line[len("LLMOXIE_SPEND "):])


def test_prefix_is_fourteen_characters(spend_logger):
    assert len(spend_logger.SPEND_LINE_PREFIX) == 14


def test_success_prints_one_spend_line(spend_logger, capsys):
    _emit(spend_logger, {"standard_logging_object": _payload(), "api_key": "sk-raw"})
    record = _only_line(capsys.readouterr().out)
    assert set(record) == {
        "ts", "request_id", "key_alias", "key_hash", "user_id",
        "team_alias", "model", "spend", "total_tokens",
    }
    assert record["request_id"] == "req-1"
    assert record["key_hash"] == "abc123hash"
    assert record["spend"] == pytest.approx(0.0123)
    assert record["total_tokens"] == 4567


def test_line_never_carries_prompt_response_or_raw_key(spend_logger, capsys):
    _emit(spend_logger, {"standard_logging_object": _payload(), "api_key": "sk-raw"})
    out = capsys.readouterr().out
    for secret in ("SECRET PROMPT", "SECRET RESPONSE", "sk-raw", "messages"):
        assert secret not in out


def test_missing_metadata_and_cost_do_not_raise(spend_logger, capsys):
    payload = _payload(response_cost=None, metadata=None)
    del payload["total_tokens"]
    _emit(spend_logger, {"standard_logging_object": payload})
    record = _only_line(capsys.readouterr().out)
    assert record["spend"] == 0.0
    assert record["total_tokens"] == 0
    assert record["key_alias"] is None


def test_no_standard_logging_object_prints_nothing(spend_logger, capsys):
    _emit(spend_logger, {})
    assert capsys.readouterr().out == ""


def test_exception_is_logged_not_raised(spend_logger, capsys, monkeypatch):
    def boom(_payload):
        raise RuntimeError("boom")

    monkeypatch.setattr(spend_logger, "spend_record", boom)
    _emit(spend_logger, {"standard_logging_object": _payload()})
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "boom" in captured.err
```

- [ ] **Step 2: Run them and watch them fail.**
      `pixi run -e llmaven pytest tests/infrastructure/test_spend_logger.py -q`
      fails because the file does not exist.
- [ ] **Step 3: Write the logger.** Follow `adl_logger.py` for the logger
      setup (stderr handler, prefix `[SpendLogger]`, `propagate=False`). Write
      the line with `print(SPEND_LINE_PREFIX + json.dumps(record,
      separators=(",", ":")), flush=True)`. Build `ts` with
      `datetime.now(timezone.utc).isoformat()`. Coerce values as
      `float(payload.get("response_cost") or 0)` and
      `int(payload.get("total_tokens") or 0)`; use
      `payload.get("metadata") or {}`. Return early, without printing, when
      `standard_logging_object` is missing or empty. Wrap the whole body in
      `try/except Exception` and log with `logger.exception`. Use the key names
      confirmed in Task 1, row 2.
- [ ] **Step 4: Run the tests until they pass.**
- [ ] **Step 5: Commit.**
      `feat(infra): add a LiteLLM callback that logs per-request spend`

---

### Task 3: Ship the logger to the gateway

**Files:**

- Modify: `src/llmaven/infrastructure/main.py` (section 8.2, near
  `adl_logger_path`)
- Modify: `docker/config.yaml` (line 20, `callbacks`)
- Modify: `docker/docker-compose.yml` (LiteLLM volumes)
- Modify: `docker/README.md` (the `callbacks` example and the "Request Logging
  to Azure Blob Storage" section)

**Interfaces:** none new. `helpers.create_litellm_app` already mounts every
`extra_modules` file as a secret named from the file name
(`spend_logger.py` → `spend-logger-py`) at `/app/config/spend_logger.py`.

- [ ] **Step 1: Wire `main.py`.** Add
      `spend_logger_path = Path(__file__).parent / Path("resources/spend_logger.py")`
      next to `adl_logger_path`. Pass
      `extra_modules=[adl_logger_path, spend_logger_path]`.
- [ ] **Step 2: Update `docker/config.yaml`.** Change the line to
      `callbacks: [adl_logger.proxy_handler_instance, spend_logger.proxy_handler_instance]`.
      Extend the comment above it with one line naming the spend logger.
- [ ] **Step 3: Mount it locally.** In `docker/docker-compose.yml`, add
      `- ../src/llmaven/infrastructure/resources/spend_logger.py:/app/spend_logger.py`
      after the `adl_logger.py` mount.
- [ ] **Step 4: Update `docker/README.md`.** Update both `callbacks` examples
      to the list form. Add a short "Spend lines" note covering:
      - the line format;
      - that it feeds the `llm_spend` alert;
      - that Postgres stays the source of truth.
- [ ] **Step 5: Run the infrastructure tests.**
      `pixi run -e llmaven pytest tests/infrastructure -q`
      No existing test asserts the mounted-secret list (checked when writing
      this plan), so nothing should change. The secret name
      `spend-logger-py` is derived from the file name by `helpers.py`.
- [ ] **Step 6: Commit.**
      `feat(infra): mount the spend logger beside the LiteLLM config`

---

### Task 4: Schema and defaults

**Files:**

- Modify: `src/llmaven/infrastructure/config/schema.py` (`AlertName`,
  `LOG_BASED_ALERTS`, new `LlmSpendAlert`, `AlertsConfig`)
- Modify: `src/llmaven/infrastructure/config/defaults.py` (template comment,
  lines 333–334)
- Modify: `tests/infrastructure/test_monitoring_config.py`

**Interfaces:**

```python
class LlmSpendAlert(BaseModel):
    max_usd_per_hour: float | None = Field(default=None, gt=0)
    max_usd_per_day: float | None = Field(default=50, gt=0)

    @model_validator(mode="after")
    def _at_least_one_threshold(self) -> "LlmSpendAlert": ...

    def thresholds(self) -> dict[str, float]:
        """Non-null thresholds keyed by window: {"hourly": x, "daily": y}."""
```

`AlertsConfig.llm_spend: LlmSpendAlert = Field(default_factory=LlmSpendAlert)`.
`"llm_spend"` goes last in `AlertName` and is added to `LOG_BASED_ALERTS`.

- [ ] **Step 1: Write the failing tests** in `test_monitoring_config.py`:
      - `LlmSpendAlert()` gives `(None, 50)` and `thresholds() == {"daily": 50}`.
      - Both thresholds set gives both keys.
      - Both `None` raises `ValidationError` mentioning `max_usd_per`.
      - `0` and `-1` are rejected for each field.
      - `enabled_alerts=["llm_spend"]` with `enable_log_analytics=False` raises
        the existing "enable_log_analytics" error.
      - `"llm_spend" in ALL_ALERTS`.
- [ ] **Step 2: Run them and watch them fail.**
- [ ] **Step 3: Implement.** Follow `CloudBudgetAlert` for style.
- [ ] **Step 4: Update the template comment** in `defaults.py` to list
      `llm_spend`. Do not add an `llm_spend:` block to the template; the
      schema defaults apply, as with the other thresholds. Staging and prod
      pick the alert up through `list(ALL_ALERTS)`.
- [ ] **Step 5: Run the config and defaults tests.**
      `pixi run -e llmaven pytest tests/infrastructure -q -k "config or defaults"`
      If a test compares the full alert list or a rendered template, update
      only that expectation.
- [ ] **Step 6: Commit.** `feat(infra): add the llm_spend alert config`

---

### Task 5: The `_llm_spend` builder

**Files:**

- Modify: `src/llmaven/infrastructure/resources/monitoring.py`
- Modify: `tests/infrastructure/test_monitoring_program.py`

**Interfaces:**

```python
LLM_SPEND_FREQUENCY = "PT1H"
LLM_SPEND_WINDOWS = {"hourly": "PT1H", "daily": "P1D"}
LLM_SPEND_QUERY = (
    'ContainerAppConsoleLogs_CL | where ContainerAppName_s == "{app}" '
    'and Log_s startswith "LLMOXIE_SPEND " '
    "| extend r = parse_json(substring(Log_s, 14)) "
    "| summarize spend = sum(todouble(r.spend))"
)

def _llm_spend(ctx: _Context) -> dict[str, pulumi.CustomResource]: ...
```

Register `"llm_spend": _llm_spend` in `_BUILDERS`. Each threshold makes a
`ScheduledQueryRule` named `alert-llm-spend-{window}` with:

- `kind="LogAlert"`, `severity=2`, `scopes=[ws.id]`;
- `evaluation_frequency=LLM_SPEND_FREQUENCY` and
  `window_size=LLM_SPEND_WINDOWS[window]`;
- `auto_mitigate=True`, `skip_query_validation=True`;
- one condition: `query`, `time_aggregation="Total"`,
  `metric_measure_column="spend"`, `operator="GreaterThan"`,
  `threshold=<usd>`;
- `ctx.action_group.id` and `ctx.tags`.

Build the query with `ctx.litellm_app.name.apply(...)`. When
`ctx.litellm_app` is `None`, call `_warn_skipped("llm_spend", "litellm app")`.
When the workspace is `None`, call
`_warn_skipped("llm_spend", "log analytics workspace")`. Add a comment that the
window overlap at PT1H/P1D is expected (a daily breach re-fires hourly until
auto-mitigated), and that the lines are best effort.

- [ ] **Step 1: Update the test stub.** In `fake_create_app`, add
      `name=pulumi.Output.from_input(kwargs["app_name"])`.
- [ ] **Step 2: Fix the three backup tests.** The tests at lines 350, 359
      and 394 assume a single ScheduledQueryRule. Filter them by name
      `alert-backup-job-failures` instead. Run the file; it should still pass.
- [ ] **Step 3: Write the failing tests:**
      - `FULL` config: one `alert-llm-spend-daily` rule with:
        - `windowSize == "P1D"` and `evaluationFrequency == "PT1H"`;
        - `timeAggregation == "Total"` and `metricMeasureColumn == "spend"`;
        - `threshold == 50`;
        - a query containing `llmaven-dev-litellm` and `substring(Log_s, 14)`.
        No hourly rule.
      - Both thresholds set: both rules exist; the hourly rule has `PT1H`/`PT1H`.
      - LiteLLM disabled: no `alert-llm-spend-*` rules, and the warnings include
        `"monitoring: llm_spend skipped, litellm app is not deployed"`.
      - The query's prefix literal equals `spend_logger.SPEND_LINE_PREFIX`.
        Compare against the file text, so no stubbing is needed.
- [ ] **Step 4: Run them and watch them fail.**
- [ ] **Step 5: Implement**, following `_backup_job_failures`.
- [ ] **Step 6: Run** `pixi run -e llmaven pytest tests/infrastructure/test_monitoring_program.py -q`.
- [ ] **Step 7: Commit.** `feat(infra): alert when LLM spend passes a threshold`

---

### Task 6: Missing-callback warning and cost estimate

**Files:**

- Modify: `src/llmaven/infrastructure/config/litellm_models.py`
- Modify: `src/llmaven/infrastructure/main.py` (after the `foundry_enabled`
  block, around line 127)
- Modify: `src/llmaven/deployment/validate.py` (imports, "# 4.2. Alert
  recipients", `estimate_alerts_monthly_cost`)
- Modify: `tests/infrastructure/test_foundry.py` (or a new
  `tests/infrastructure/test_spend_logger_config.py` if that file is
  foundry-only)
- Modify: `tests/infrastructure/test_validate_alert_receivers.py`
- Modify: `tests/infrastructure/test_cost_estimate.py`

**Interfaces:**

```python
def missing_spend_logger(config: LLMavenConfig, config_path: Path) -> list[str]:
    """Warnings when llm_spend is enabled but the LiteLLM config lacks the callback."""
```

- It returns `[]` unless `"llm_spend"` is in
  `config.monitoring.alerts.enabled_alerts` and `config.litellm.enabled`.
- It reads the file the same way `missing_foundry_deployments` does, reusing
  its unreadable-file and non-mapping messages.
- It normalises `litellm_settings.callbacks` (str, list or missing) to a list.
  If no entry starts with `"spend_logger."`, it returns one message:
  `f"{path}: litellm_settings.callbacks has no spend_logger entry; the llm_spend alert will see no data"`.

In `estimate_alerts_monthly_cost`, add `len(config.monitoring.alerts.llm_spend.thresholds())`
to `log_count` when `llm_spend` is enabled and LiteLLM is enabled.

- [ ] **Step 1: Write the failing tests.**
      - `missing_spend_logger`:
        - the repo `docker/config.yaml` → `[]`;
        - a string `callbacks` with only `adl_logger` → one message;
        - no `litellm_settings` → one message;
        - `llm_spend` not enabled → `[]`;
        - LiteLLM disabled → `[]`;
        - an unreadable file → the read-error message.
      - Validate (`_write_config` gains `litellm_config: Path | None = None`):
        - a config without `spend_logger` plus `["llm_spend"]` → the warning
          is in `warnings`, and `errors` is unchanged;
        - the repo config → no spend warning.
      - Cost:
        - `llm_spend` with `LiteLLMConfig(enabled=True)` and the default
          thresholds adds `LOG_ALERT_MONTHLY_COST` once;
        - both thresholds add it twice;
        - LiteLLM disabled adds nothing.
- [ ] **Step 2: Run them and watch them fail.**
- [ ] **Step 3: Implement `missing_spend_logger`.** Factor out a small
      `_load_litellm_yaml` helper only if it removes real duplication with
      `missing_foundry_deployments`. Otherwise copy the six lines.
- [ ] **Step 4: Warn on deploy.** In `main.py`, after the foundry block, add
      a lazy import, then
      `for message in missing_spend_logger(config, config_path): pulumi.log.warn(message)`.
- [ ] **Step 5: Warn in validate.** In `validate.py`, append each message to
      `warnings` and print `⚠️` after the alert-recipients if/else, before
      `print()`.
- [ ] **Step 6: Update the cost estimate.**
- [ ] **Step 7: Run** `pixi run -e llmaven pytest tests/infrastructure -q`.
- [ ] **Step 8: Commit.**
      `feat(infra): warn when llm_spend has no spend logger and price its rules`

---

### Task 7: Docs and project memory

**Files:**

- Modify: `README.md` (the "Alerting" section)
- Modify (via `okf` only): `knowledge/decisions/monitoring-alerts-config.md`

- [ ] **Step 1: Update `README.md`.**
  - Add an `llm_spend` row to the alert table, with:
    - the default `max_usd_per_day: 50` and `max_usd_per_hour: null`;
    - Log Analytics as the source.
  - Change "all seven" to "all eight".
  - In the data-cap paragraph, name `llm_spend` alongside
    `backup_job_failures`. If the daily cap is reached, both alerts go blind.
  - Rewrite the spend paragraph:
    - the Azure budget covers Azure charges;
    - `llm_spend` covers model-provider spend recorded by LiteLLM;
    - both are best effort, and Postgres spend logs are the source of truth.
  - Add the roll-out note: a pinned `litellm.refresh_trigger` must be bumped,
    or a set `revision_suffix` changed, for the new logger to reach running
    gateways.
- [ ] **Step 2: Update project memory.** Record the `llm_spend` design in
      `decisions/monitoring-alerts-config` through the `okf` CLI (see the
      `okf-memory` skill):
      - the stdout line rather than Postgres;
      - one rule per threshold;
      - a warning, not an error, for a missing callback.
      Then run `pixi run -e llmaven okf validate`.
- [ ] **Step 3: Commit.** `docs(infra): document the llm_spend alert`

---

### Task 8: Verify and hand off

**Files:** none new.

- [ ] **Step 1: Run the gate.** Run `pixi run -e llmaven verify` and read the
      output. Fix any failures in the files this plan touched.
- [ ] **Step 2: Review the diff.** Run `git diff main...HEAD` and check it
      against the Review Focus items. Remove anything that does not trace to
      this plan.
- [ ] **Step 3: Manual dev check.** This step is opt-in and needs explicit
      user approval before any deploy.
  1. Locally, run `pixi run -e llmaven up`, send one chat request, and
     confirm that `docker compose logs litellm` shows one `LLMOXIE_SPEND`
     line with no prompt text.
  2. In dev, with approval, enable `llm_spend` with
     `max_usd_per_hour: 0.01`.
  3. Run `llmaven infra deploy --preview`. Confirm that the plan shows two
     `alert-llm-spend-*` rules and a new LiteLLM revision.
  4. Deploy. Send a few requests.
  5. Within about 10 minutes, the KQL from the spec returns a non-zero `spend`
     in Log Analytics.
  6. Within about 1 hour, the hourly alert email arrives.
  7. Restore the thresholds and redeploy.
- [ ] **Step 4: Hand off.** Report the verify result and the manual-check
      status. Note any Task 1 answers that changed an assumption. Do not open
      a PR; that follows `contribution-discipline.md`.

---

## Verified facts

| #   | Answer | Matches assumption | Source |
| --- | ------ | ------------------ | ------ |
| 1   | Yes. `initialize_callbacks_on_proxy` iterates a list value; each entry that is not a built-in name or a `CustomLogger` goes through `get_instance_fn`, which splits on the last dot, loads `<config dir>/<module>.py` if present (else `importlib.import_module`), and takes the attribute; results are appended to `litellm.callbacks`. `docker/config.yaml:20` currently uses a single string, so it must become a YAML list, and the new module must be mounted next to `adl_logger` via `extra_modules`. | Yes | LiteLLM v1.108.6 `litellm/proxy/common_utils/callback_utils.py` (`initialize_callbacks_on_proxy`), `litellm/proxy/types_utils/utils.py` (`get_instance_fn`); repo `docker/config.yaml:20`, `helpers.py:341` |
| 2   | Top level: `id`, `model`, `response_cost`, `total_tokens`. `metadata` (`StandardLoggingMetadata`, extends `StandardLoggingUserAPIKeyMetadata`): `user_api_key_alias`, `user_api_key_hash`, `user_api_key_user_id`, `user_api_key_team_alias` (also `user_api_key_team_id`, `user_api_key_end_user_id`). `StandardLoggingMetadata` has separate `team_alias`/`team_id` fields, which are not the key's team. | Yes | LiteLLM v1.108.6 `litellm/types/utils.py` (`StandardLoggingPayload`, `StandardLoggingMetadata`, `StandardLoggingUserAPIKeyMetadata`) |
| 3   | Yes, with caveats. For `sk-` keys the auth path replaces the key with `hash_token` (`sha256(token).hexdigest()`), and `user_api_key_hash` is set from `get_logged_api_key`. The raw `sk-` key is not logged on the normal path. Caveats: (a) master-key requests log the alias `litellm_proxy_master_key`, not a hash; (b) UI session tokens with a `key_alias` log the alias; (c) non-`sk-` bearer tokens may pass through unhashed on other paths. Treat the field as an opaque identifier. | Yes (with caveats) | LiteLLM v1.108.6 `litellm_pre_call_utils.py` (`get_logged_api_key`, `user_api_key_hash=`), `user_api_key_auth.py` (`hash_token` for `sk-`), `proxy/utils.py` (`hash_token`), `constants.py:1752` (`LITELLM_PROXY_MASTER_KEY_ALIAS`) |
| 4   | Yes. Container `stdout`/`stderr` land in `ContainerAppConsoleLogs_CL`, with columns `ContainerAppName_s`, `ContainerGroupName_g`, `ContainerId_s`, `ContainerImage_s`, `EnvironmentName_s`, `Log_s`, `RevisionName_s`. A callback's stdout is console output, so it lands there. | Yes | Microsoft Learn, Azure Container Apps "Log monitoring" (https://learn.microsoft.com/azure/container-apps/log-monitoring); repo `BACKUP_FAILURE_QUERY` |
| 5   | Yes. `timeAggregation` accepts Count, Average, Minimum, Maximum, Total, and is required for LogAlert rules; `metricMeasureColumn` names the numeric column to aggregate. `azure-native` `monitor.ScheduledQueryRule` (v3.30.0, API 2026-03-01) exposes both. | Yes | Azure REST "Scheduled Query Rules - Create Or Update" (https://learn.microsoft.com/rest/api/monitor/scheduled-query-rules/create-or-update); Pulumi registry `azure-native.monitor.ScheduledQueryRule`; Learn "Create or edit a log search alert rule" |
| 6   | Yes. Evaluation frequency may be 1 minute to 1 day, and the alert time range is limited to a maximum of 2 days, so `P1D` and `PT1H` are both valid. Both are ISO 8601 durations, required for LogAlert. The docs do not state "frequency <= window" explicitly; it holds here anyway (`PT1H` < `P1D`). | Yes | Microsoft Learn, "Create or edit a log search alert rule" (https://learn.microsoft.com/azure/azure-monitor/alerts/alerts-create-log-alert-rule); REST create-or-update page above |
| 7   | About $0.50/month. Retail list price, eastus, USD per rule: log alert at 1 min $3.00, 5 min $1.50, 10 min $1.00, 15 min $0.50. No tier exists for frequencies longer than 15 min, so `PT1H` is inferred to bill at the lowest (15 min) tier. `LOG_ALERT_MONTHLY_COST = 0.50` (`validate.py:376`) stays correct. Caveats: list price for eastus only, not an invoice; the pricing page was not fetchable, so the figures come from the Retail Prices API. | Yes (inferred for PT1H) | Azure Retail Prices API: `https://prices.azure.com/api/retail/prices?$filter=serviceName eq 'Azure Monitor' and armRegionName eq 'eastus'` (meters "Alerts System Log Monitored at N Minute Frequency"); Learn "Azure Monitor alert types" (billed by evaluation interval) |
| 8   | Yes by code reading; not confirmed at runtime. LiteLLM v1.108.6 does not redirect or capture `sys.stdout` in `proxy_server.py`, `litellm_logging.py` or `callback_utils.py`; `proxy_cli.py` runs uvicorn or gunicorn, neither of which captures `print`. The image sets no `PYTHONUNBUFFERED`, so `flush=True` is needed. The Task 8 manual check does the runtime confirmation. | Yes (runtime pending Task 8) | LiteLLM v1.108.6 `proxy/proxy_server.py`, `proxy/proxy_cli.py`, `litellm_core_utils/litellm_logging.py`; repo `docker/dockerfiles/litellm.dockerfile` |
