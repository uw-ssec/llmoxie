# Ops Spend Report Design

- **Date:** 2026-11-13
- **Parent spec:**
  [2026-11-05-monitoring-alerting-design.md](2026-11-05-monitoring-alerting-design.md),
  PR 3
- **Status:** Draft, awaiting review

## Goal

When an `llm_spend` alert fires, the operator runs one command to see which key,
user, model, or team drove the spend, and whether that is unusual compared with
the window before it. The alert email names that command.

## Scope

- A new `llmaven ops spend-report` command.
- An `investigate` custom property on both `llm_spend` alert rules.

Out of scope: any change to `llmaven infra extract`, to `llmaven.data`, or to
alert thresholds.

## Deviations from the parent spec

- **No PNG output.** Only a Rich table and an optional CSV are produced. A chart
  adds a plotting dependency for little gain over a sorted table.
- **No reuse of `llmaven.data` or the extract client.** The `ops` package is
  written as if it will move out of this repository (as `llmaven.data` is moving
  to uw-ssec/llmoxie-analysis, see okf
  `data-pipeline-moves-to-llmoxie-analysis`). It has its own `/spend/logs` fetch
  loop and a stdlib reader for extract output. It imports nothing from
  `llmaven.cli` or `llmaven.data`.

## Command

```
llmaven ops spend-report --start YYYY-MM-DD --end YYYY-MM-DD
    [--by key|user|model|team] [--threshold 2.0] [--top N]
    [--from-zip PATH] [--csv PATH] [-e ENV_FILE]
```

| Flag          | Default  | Meaning                                                                                  |
| ------------- | -------- | ---------------------------------------------------------------------------------------- |
| `--start`     | required | First day of the report window (inclusive, UTC).                                         |
| `--end`       | required | Last day of the report window (inclusive, UTC).                                          |
| `--by`        | `key`    | Grouping dimension.                                                                      |
| `--threshold` | `2.0`    | A row is flagged `spike` when its spend is at least this multiple of its baseline spend. |
| `--top`       | all      | Show only the N highest-spend rows in the table (CSV always has every row).              |
| `--from-zip`  | none     | Read records from an `llmaven infra extract` output instead of calling LiteLLM.          |
| `--csv`       | none     | Also write the rows to this CSV file.                                                    |
| `-e`          | none     | Env file for LiteLLM credentials (the existing `ENV_FILE_OPTION`).                       |

`--start` after `--end` is a usage error.

## Module layout

- `src/llmaven/ops/__init__.py`: defines `ops_app` (a Typer group) and the
  `spend-report` command. It takes `base_url` and `api_key` from a credential
  callback passed in at registration, so the package has no import from
  `llmaven.cli`.
- `src/llmaven/ops/spend.py`: pure functions plus the HTTP loop.
  - `fetch_spend_records(base_url, api_key, start, end)` yields raw records, one
    `GET /spend/logs?start_date=..&end_date=..&summarize=false` per day, with
    its own small retry on transport errors and 5xx (httpx only).
  - `iter_extract_records(path)` yields raw records from a `.zip` of extract
    output, a directory of `*.jsonl` files, or a single `.jsonl` file, using
    `zipfile` and `json`.
  - `group_label(record, by)` returns the label for one record.
  - `aggregate(records, by, start, end)` returns `{label: spend_usd}` for
    records whose `startTime` falls in `[start, end]`.
  - `compare(current, baseline, threshold)` returns `SpendRow` items (`label`,
    `spend`, `prior`, `ratio`, `flag`), sorted by spend descending.
  - `render_table(rows, ...)` and `write_csv(rows, path)`.
- `src/llmaven/cli.py`: one `app.add_typer(ops_app, name="ops")` registration
  and a credential hook that calls `_get_litellm_credentials`. No other change.
  `_extract_litellm_logs` is not refactored.

## Data flow

1. Compute the baseline window: the same length immediately before `--start`,
   i.e. `[start - n_days, start - 1 day]`.
2. Load records for both windows:
   - Live: fetch the baseline window and the report window from `/spend/logs`.
   - `--from-zip`: read all records once and split them by `startTime`. If no
     record falls in the baseline window, print a note and leave the baseline
     columns blank (no flags).
3. Aggregate each window by `--by`.
4. Compare and flag:
   - `new`: spend in the report window, none in the baseline.
   - `spike`: `spend >= threshold * prior` and `prior > 0`.
   - empty otherwise.
5. Render a Rich table to stdout with a total row; write a CSV if asked. Notes
   and progress go to stderr (`console_err` pattern).

## Grouping labels

| `--by` | Source field                                                  | Fallback     |
| ------ | ------------------------------------------------------------- | ------------ |
| key    | `metadata.user_api_key_alias`                                 | hashed key   |
| user   | `user`                                                        | `(no user)`  |
| model  | `model`                                                       | `(no model)` |
| team   | `team_id`, then `metadata.user_api_key_team_alias` if present | `(no team)`  |

The team field names are an assumption from the LiteLLM spend log schema; the
existing reader does not use them. The implementation confirms them against a
real `/spend/logs` record before relying on them.

## Data safety

Per okf `cli-output-data-safety`, raw API keys never appear in table or CSV
output. When a key has no alias, the label is the `api_key` value as LiteLLM
returns it (already a hash in spend logs), truncated to a short prefix. Prompt
and response content is never read or printed.

## Alert email hint

`_llm_spend` in `src/llmaven/infrastructure/resources/monitoring.py` sets on
both the hourly and daily `ScheduledQueryRule`:

```python
custom_properties = {
    "investigate": "llmaven ops spend-report --start <date> --end <date> -e <env file>"
}
```

The value is static. Azure log alert custom properties are not templated by fire
time, so the operator fills in the dates from the alert email.

## Tests

- `tests/ops/test_spend.py`:
  - `fetch_spend_records` against a mocked httpx transport: one request per day
    with `summarize=false`, retry on a 5xx then success.
  - `iter_extract_records` for a zip fixture, a directory, and a single file.
  - `group_label` for each `--by`, including every fallback.
  - `aggregate` drops records outside the window.
  - `compare` flags `new`, `spike`, and leaves below-threshold rows unflagged;
    blank baseline gives no flags.
  - `write_csv` columns and order; no raw key in output.
- `tests/ops/test_cli.py`: `CliRunner` run with `--from-zip` and `--csv`;
  `--start` after `--end` exits non-zero.
- `tests/infrastructure/test_monitoring_program.py`: both `llm_spend` rules
  carry the `investigate` custom property. The email itself is not checked in
  tests.

## Risks

- `/spend/logs` with `summarize=false` can be large for busy days; one request
  per day bounds it, and the baseline doubles the request count.
- Spend in LiteLLM logs and in the console-log alert can differ (okf
  `request-log-sources-differ`); the report states its source in the header.
