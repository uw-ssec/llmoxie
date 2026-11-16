---
type: Decision
title: "Monitoring alerts are email-only, opt-in per environment, and the budget is scoped to the resource group"
description: "Alerting uses one email action group, absolute thresholds listed in enabled_alerts, a resource-group-scoped budget with no tag filter, Maximum-per-podName for restarts, and an llm_spend alert that reads a LiteLLM stdout line."
tags: [azure, monitoring, alerts]
generated: { by: "github-copilot:claude-sonnet-5.5", at: "2026-11-13T00:06:15Z" }
status: stable
code_refs: [src/llmaven/infrastructure/resources/monitoring.py, src/llmaven/infrastructure/config/schema.py]
---

## Context

The monitoring-alerting work adds Azure Monitor alert rules, one action group and a consumption budget behind `monitoring.alerts`. Everything below is created only for alert names listed in `monitoring.alerts.enabled_alerts`; an empty list creates no `monitor:*` or `consumption:*` resources at all, which keeps existing stacks unchanged.

## Decision

- **Email-only, one action group.** `alerts-action-group` emails every address in `monitoring.alerts.email_receivers`, and every alert plus the budget points at it, so receivers live in exactly one place. Budget notifications pass `contact_groups` only; `contact_emails` is passed empty because the provider requires the argument, and listing the same addresses in both would send every budget mail twice.
- **Opt-in per environment.** `enabled_alerts` defaults to `[]` for dev and to all eight alerts for staging and prod.
- **Absolute thresholds, not baselines.** Azure dynamic thresholds were not used: the platform has no traffic history to learn from, and an operator reading the config should see the number that fires.
- **The budget is scoped to the resource group, with no tag filter.** Environments that share a resource group share one budget, because the default name `rg-{project}-{location}` carries no environment. A `BudgetFilterArgs` tag filter on `Environment` was considered and rejected: it under-counts untagged spend, so the budget would read lower than the real bill and silence the alert that matters. The README instead states the sharing plainly and recommends a distinct `azure.resource_group` per environment.
- **`replica_restarts` uses `Maximum` split per `podName`, not `Total`.** Azure `RestartCount` is the cumulative number of restarts of one replica since it was created. Summing it over a window latches as soon as any replica has ever restarted, and because the alert is stateful it would then never email again on a real crash loop. The threshold now means "one replica has restarted more than `max_count` times since it started".
- **Evaluation frequency is derived from the window:** `PT1M` for a 1-minute window, `PT1H` for windows of 360 minutes and above, `PT5M` otherwise. Azure restricts which frequencies pair with which window sizes.
- **The backup-failure `ScheduledQueryRule` sets `skip_query_validation=True`.** A fresh workspace has no `ContainerAppSystemLogs_CL` table, and Azure validates the KQL at create time, so the rule would fail to create on a new stack.
- **The backup-failure query counts failed executions, not terminated containers.** It fires on `DeadlineExceeded` or `BackoffLimitExceeded` for an execution with no `Completed` event. Every run logs `ContainerTerminated`, including successful ones (exit code 0), so that reason can't be used. Read-only checks on 2026-11-06 over 120 days of logs flagged 70 of 125 prod executions, all timeouts from before September 16, and none of the 90 dev or 123 ISS executions. Both reasons have now been seen on real runs: `DeadlineExceeded` in those historical timeouts, and `BackoffLimitExceeded` in a forced failure on 2026-11-06. One prod execution was started with `az containerapp job start ... --container-name backup --command /bin/false`, so the job template and schedule stayed unchanged. All retries exited 1, the system log recorded `BackoffLimitExceeded` ("Job has reached the specified backoff limit") with no `Completed` event, and the rule fired at Sev1 about 4 minutes later. The first evaluation after a rule is created isn't aligned to the hour, so later failures can still take up to about an hour to email. Don't pass `--args "-c" "..."` to `az containerapp job start`: the CLI parses `-c` as its own flag, so use a command that takes no arguments.
- **The backup rule evaluates hourly over a two-hour window.** Prod backup system logs took a median of 131 s to ingest, so the overlap covers records that arrive after an evaluation. The rule is stateful (`auto_mitigate`), so the overlap shouldn't send a second email.
- **`llm_spend` reads a stdout line, not Postgres.** The `spend_logger` LiteLLM callback prints one `LLMOXIE_SPEND {json}` line per successful request, best effort, never raising, and never writing prompts, responses or raw keys. Container Apps forwards it to `ContainerAppConsoleLogs_CL`, and the alert sums `spend` over the window. Querying the Postgres spend logs would have needed a database connection from Azure Monitor. The cost is that console lines can be dropped or delayed, so the alert can under-report; the Postgres spend logs stay the source of truth.
- **One `ScheduledQueryRule` per threshold.** `max_usd_per_hour` (default null) and `max_usd_per_day` (default 50) each create `alert-llm-spend-hourly` and `alert-llm-spend-daily`, evaluated hourly over a one-hour and a one-day window. Both null is rejected at config load because the alert could never fire. The summarize has no `by` clause, so an idle gateway yields one row with 0 and doesn't fire. The rule is skipped with a warning when LiteLLM is disabled.
- **A missing callback is a warning, not an error.** `missing_spend_logger` warns on deploy (`pulumi.log.warn`) and in `llmaven infra validate` when `llm_spend` is enabled and the LiteLLM config has no `spend_logger.` callback. It fails only under `--strict`, because an operator may be mid-rollout and the alert is still valid once the callback lands. The cost estimate adds one log-alert price per threshold.
- **`cloud_budget.notify_at_percent` is limited to five distinct values,** because Azure rejects more notifications than that.
- **`monitoring.enable_application_insights` is deprecated** and provisions nothing. Loading a config with it set raises `FutureWarning`, not `DeprecationWarning`, which Python hides outside `__main__` so operators would never see it.

## Rollout notes

- When alerts are first enabled on an existing stack, the preview also lists `ManagedEnvironment ~appLogsConfiguration`. The environment reads the workspace's `customer_id` and shared key, and those values are unknown while `daily_data_cap_gb` updates the workspace. The real `up` resolves them to the same values and leaves the environment unchanged. A later `--expect-no-changes` preview passes.
- The spend logger reaches running gateways only on a new revision. A pinned `litellm.refresh_trigger` must be bumped, or a set `litellm.revision_suffix` changed; otherwise the deploy timestamp already forces one.

## Follow-ups

- An ops spend-report command (PR 3 of the spec).
- Webhook receivers on the action group; only email is wired today.
- Application Insights via OpenTelemetry, if distributed tracing is ever needed.

**Sources:** docs/superpowers/specs/2026-11-05-monitoring-alerting-design.md; Microsoft Azure Monitor metric reference for Container Apps `RestartCount`; code review of branch monitoring-initial; forced backup failure and rollout on 2026-11-06 (uw-ssec/llmoxie#193 comment).

# Related Concepts
- [Production-readiness gaps are tracked in #193, and some settings do less than they suggest](../facts/production-readiness-gaps.md): Alerting closes the monitoring gaps this fact tracks and records how the alert config behaves
