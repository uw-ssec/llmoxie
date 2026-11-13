# Monitoring and Alerting, PR 3: Ops Spend Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `llmaven ops spend-report`. It shows which key, user, model or
team drove LLM spend in a date range, flags rows against the window before it,
and is named in the `llm_spend` alert email through an `investigate` custom
property.

**Architecture:** A new package, `src/llmaven/ops/`, that imports nothing from
`llmaven.cli` or `llmaven.data`.

- `spend.py` holds pure functions and its own `/spend/logs` fetch loop.
- `__init__.py` holds `build_ops_app(get_credentials)`, which returns the Typer
  group.
- `cli.py` registers the group once and passes in a callback that returns
  `_get_litellm_credentials`.
- `monitoring.py` adds `custom_properties` to the actions of both `llm_spend`
  rules.

**Tech Stack:** Python 3.12, Typer and Rich, httpx (`MockTransport` in tests),
stdlib `zipfile`/`json`/`csv`, and Pulumi `pulumi-azure-native` 3.29.0.

**Spec:** `docs/superpowers/specs/2026-11-13-ops-spend-report-design.md`

## Global Constraints

- **Pixi only.** Run tests with `pixi run -e llmaven pytest <path> -q`. The gate
  is `pixi run -e llmaven verify`.
- **Before the first edit to each file**, run
  `pixi run -e llmaven okf search --for-path <file>`.
- **The `ops` package imports nothing from `llmaven.cli` or `llmaven.data`.**
  Credentials come from a callback passed in at registration.
- **`cli.py` changes only by registering the group and the credential hook.**
  `_extract_litellm_logs` is not refactored.
- **Data safety** (`bugs/cli-output-data-safety`):
  - No raw API keys in table, CSV or error output.
  - Prompt and response content is never read or printed.
  - With no alias, the key label is a short prefix of `api_key` as LiteLLM
    returns it.
- **Flags:**
  - `new`: spend in the report window and none in the baseline.
  - `spike`: `spend >= threshold * prior` and `prior > 0`.
  - Blank otherwise. Blank for every row when the baseline is empty.
- **Baseline window:** `[start - n_days, start - 1 day]`, with
  `n_days = (end - start).days + 1`.
- **Platform scope** (`decisions/platform-only-scope`, constraint):
  `tests/test_platform_scope.py::test_cli_exposes_only_platform_commands` pins
  the top-level commands. Add `"ops"` to that set. Change nothing else in that
  file.
- **Spec correction:** in `pulumi-azure-native`, `custom_properties` is a field
  of `monitor.ActionsArgs`, not of `ScheduledQueryRule`. It is set there and
  shows up as `rule.inputs["actions"]["customProperties"]`.
- **Commits:**
  - Conventional format with scope `cli` (Tasks 2–7, 9) or `infra` (Task 8).
  - Add an `Assisted-by: <harness>:<model>` trailer.
  - Never add `Signed-off-by:`.
- **No live infrastructure.** No deploy, `--preview` or destroy without explicit
  user approval.

## Review Focus

1. **Day-boundary double counting.** Each per-day request sends
   `end_date=day+1`, as the extract does. If LiteLLM treats that bound as
   inclusive, consecutive days overlap. `fetch_spend_records` keeps only the
   records whose `startTime` falls on the requested day. Test in Task 5.
2. **`startTime` formats.** A trailing `Z`, a `+00:00` or other offset, and a
   naive timestamp must all land on the right UTC day. A missing or unparsable
   value is dropped and never crashes. Test in Task 2.
3. **Missing or `None` spend.** A missing or `None` `spend` counts as `0.0` and
   never raises. Test in Task 2.
4. **Non-list response body.** This is an error naming the day; the report does
   not silently skip the day and under-report. The CLI exits 1 with `✗`, and the
   message never contains the key. Test in Task 5 (error) and Task 7 (exit
   code).
5. **Key leaks.** The full `api_key` value never appears in a label or CSV. An
   `api_key` that looks raw (`sk-` prefix) is labelled `(unhashed key)`, not by
   its prefix. Test in Tasks 2 and 6.

Items 4 and 5 go beyond the spec, which says nothing about non-list bodies or
raw keys. They are deliberate choices: fail loudly rather than under-report, and
never print a raw key prefix.

---

### Task 1: Verify external facts

**Files:**

- Modify: this plan (the `## Verified facts` table)

**Interfaces:** none.

| #   | Question                                                                               | Assumption used in Tasks 2–8                                   | How to check                                                                                         |
| --- | -------------------------------------------------------------------------------------- | -------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| 1   | Which spend-log fields hold the team?                                                  | `team_id` (top level), then `metadata.user_api_key_team_alias` | `LiteLLM_SpendLogs` in `litellm/proxy/schema.prisma` and `SpendLogsMetadata` at the pinned image tag |
| 2   | Is `api_key` in a spend-log record the hashed token?                                   | Yes (SHA-256 hex), never `sk-...`                              | `litellm/proxy/spend_tracking/spend_tracking_utils.py` (`get_logging_payload`)                       |
| 3   | Is `/spend/logs` `end_date` inclusive?                                                 | It may be. Task 5 filters by day either way                    | `litellm/proxy/spend_tracking/spend_management_endpoints.py` (`view_spend_logs`)                     |
| 4   | Does a log alert's `actions.customProperties` appear in the common-schema alert email? | Yes, under "Custom properties"                                 | Azure docs "Log search alert rule – custom properties"                                               |
| 5   | Is `custom_properties` on `monitor.ActionsArgs` in `pulumi-azure-native` 3.29.0?       | Yes (already confirmed in `_inputs.py` of the installed SDK)   | Already checked                                                                                      |

- [ ] **Step 1: Answer each row** in `## Verified facts`. If an answer
      contradicts an assumption, stop and update the affected task first.
- [ ] **Step 2: Commit.**
      `git commit -m "docs(cli): verify facts for the ops spend-report plan"`

---

### Task 2: Labels, days and aggregation

**Files:**

- Create: `src/llmaven/ops/__init__.py` (empty for now),
  `src/llmaven/ops/spend.py`
- Create: `tests/ops/__init__.py`, `tests/ops/test_spend.py`

**Interfaces:**

- Consumes: raw record dicts (`startTime`, `spend`, `model`, `user`, `api_key`,
  `team_id`, `metadata`).
- Produces:
  - `class GroupBy(str, Enum)`: `key`, `user`, `model`, `team`.
  - `def record_day(record: dict) -> date | None`: the UTC date of `startTime`.
  - `def group_label(record: dict, by: GroupBy) -> str`
  - `def aggregate(records: Iterable[dict], by: GroupBy, start: date, end: date) -> dict[str, float]`

`record_day` parses with `datetime.fromisoformat` after replacing a trailing `Z`
with `+00:00`. It treats a naive value as UTC, converts an aware value to UTC,
and returns `None` for a missing or bad value. Key fallback order:

1. `metadata.user_api_key_alias`
2. `(unhashed key)` if `api_key` starts with `sk-`
3. `key:<first 8 chars>` if `api_key` is set
4. `(no key)`

- [ ] **Step 1: Write failing tests.**
  - `test_record_day_formats`: parametrized over `"2026-03-01T23:30:00Z"`,
    `"2026-03-01T23:30:00+00:00"`, `"2026-03-02T01:30:00+02:00"` and
    `"2026-03-01T23:30:00"`. Each gives `date(2026, 3, 1)`. `None`, `""` and
    `"garbage"` give `None`.
  - `test_group_label`: parametrized over every `--by` and every fallback (spec
    table plus the two key fallbacks). Asserts the full 64-char hash is not in
    the label.
  - `test_aggregate_window_and_missing_spend`: records on `start - 1`, `start`,
    `end` and `end + 1`. Only the middle two count. `spend: None` and a missing
    `spend` add `0.0`. A record with no `startTime` is dropped.
- [ ] **Step 2: Run them and confirm they fail.**
      `pixi run -e llmaven pytest tests/ops/test_spend.py -q`
- [ ] **Step 3: Implement** `GroupBy`, `record_day`, `group_label` and
      `aggregate`.
- [ ] **Step 4: Run them and confirm they pass.**
- [ ] **Step 5: Commit.**
      `feat(cli): add spend grouping and aggregation for ops spend-report`

---

### Task 3: Baseline comparison

**Files:**

- Modify: `src/llmaven/ops/spend.py`
- Test: `tests/ops/test_spend.py`

**Interfaces:**

- Consumes: two `aggregate` results.
- Produces:
  - `@dataclass(frozen=True) class SpendRow`: `label: str`, `spend: float`,
    `prior: float | None`, `ratio: float | None`, `flag: str`.
  - `def baseline_window(start: date, end: date) -> tuple[date, date]`
  - `def compare(current: dict[str, float], baseline: dict[str, float] | None, threshold: float) -> list[SpendRow]`

`baseline=None` means there is no baseline data. Then `prior`, `ratio` and
`flag` are blank for every row. Otherwise `prior = baseline.get(label, 0.0)`,
and `ratio = spend / prior` only when `prior > 0`. Rows come only from
`current`. Sort by spend descending, then by label.

- [ ] **Step 1: Write failing tests.**
  - `test_baseline_window`: `(03-08, 03-14)` gives `(03-01, 03-07)`.
    `(03-08, 03-08)` gives `(03-07, 03-07)`.
  - `test_compare_flags`: one row each for `new`, `spike` (exactly at
    `threshold * prior`), below threshold (`""`), and a zero-spend label with no
    prior (`""`, not `new`). Also checks the sort order.
  - `test_compare_blank_baseline`: `baseline=None` gives `None`/`None`/`""` on
    every row.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and confirm they pass.**
- [ ] **Step 5: Commit.**
      `feat(cli): flag new and spiking spend against a baseline`

---

### Task 4: Extract reader

**Files:**

- Modify: `src/llmaven/ops/spend.py`
- Test: `tests/ops/test_spend.py`

**Interfaces:**

- Consumes: `llmaven infra extract` output. It writes zip entries or files named
  `litellm_spend_logs_<date>.jsonl`, one JSON record per line.
- Produces: `def iter_extract_records(path: Path) -> Iterator[dict]`

It accepts a `.zip` (every `*.jsonl` entry), a directory (every `*.jsonl` file,
sorted) or a single `.jsonl` file. It skips blank lines and lines that are not
dict objects. Any other kind of path raises `ValueError`.

- [ ] **Step 1: Write failing tests.** A `tmp_path` fixture writes two days of
      records. `test_iter_extract_records_zip`, `_directory` and `_single_file`
      each yield the same records. `test_iter_extract_records_skips_blank_lines`
      checks the blank-line case.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and confirm they pass.**
- [ ] **Step 5: Commit.** `feat(cli): read spend records from extract output`

---

### Task 5: LiteLLM fetch with retry

**Files:**

- Modify: `src/llmaven/ops/spend.py`
- Test: `tests/ops/test_spend.py`

**Interfaces:**

- Consumes: LiteLLM `GET {base_url}/spend/logs`.
- Produces:
  - `class SpendFetchError(Exception)`
  - `def fetch_spend_records(base_url: str, api_key: str, start: date, end: date, *, client: httpx.Client | None = None, sleep: Callable[[float], None] = time.sleep, attempts: int = 3) -> Iterator[dict]`

For each day from `start` to `end`:

- Send `params={"start_date": day, "end_date": day + 1, "summarize": "false"}`
  with the header `Authorization: Bearer <api_key>`.
- Retry transport errors and 5xx up to `attempts`, sleeping `2 ** attempt`
  seconds.
- Raise `SpendFetchError` on a 4xx, on exhausted retries, or on a non-list body.
  The message names the day and the status, never the key.
- Yield only the records where `record_day(record) == day`.

When `client` is `None`, create `httpx.Client(timeout=30.0)` and close it
afterwards.

- [ ] **Step 1: Write failing tests** using
      `httpx.Client(transport=httpx.MockTransport(handler))` and
      `sleep=lambda s: None`.
  - `test_fetch_one_request_per_day`: a 3-day range makes 3 requests, each with
    `summarize=false`, the right dates and a bearer header.
  - `test_fetch_drops_records_from_next_day`: the handler returns a record for
    `day` and one for `day + 1`, and only the first is yielded (Review Focus 1).
  - `test_fetch_retries_5xx_then_succeeds`: the first response is 503, the
    second is 200.
  - `test_fetch_non_list_body_raises`: a `{"detail": ...}` body raises
    `SpendFetchError`, and `api_key` is not in `str(exc)`.
  - `test_fetch_4xx_raises_without_retry`: a 401 makes exactly one request.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and confirm they pass.**
- [ ] **Step 5: Commit.** `feat(cli): fetch spend logs per day with retry`

---

### Task 6: Table and CSV output

**Files:**

- Modify: `src/llmaven/ops/spend.py`
- Test: `tests/ops/test_spend.py`

**Interfaces:**

- Consumes: `list[SpendRow]`.
- Produces:

  - `CSV_COLUMNS = ("label", "spend_usd", "prior_usd", "ratio", "flag")`
  - `def write_csv(rows: list[SpendRow], path: Path) -> None`. `None` is written
    as an empty cell. Writes every row.
  - `def render_table(rows: list[SpendRow], *, title: str, top: int | None) -> rich.table.Table`.
    The title states the source, window, baseline and grouping. Shows the first
    `top` rows plus a total row, and the total covers all rows.

- [ ] **Step 1: Write failing tests.**
  - `test_write_csv_columns_and_blanks`: the header equals `CSV_COLUMNS`, and a
    blank-baseline row has empty `prior_usd`/`ratio`/`flag`.
  - `test_csv_has_no_raw_key`: builds rows through `group_label` from records
    with a 64-char `api_key` and no alias, and checks the key is not in the file
    text.
  - `test_render_table_top_and_total`: three rows with `top=1` give 1 data row
    plus a total equal to the sum of all three. Render with
    `Console(record=True)`.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and confirm they pass.**
- [ ] **Step 5: Commit.** `feat(cli): render spend report table and CSV`

---

### Task 7: `ops spend-report` command and registration

**Files:**

- Modify: `src/llmaven/ops/__init__.py`, `src/llmaven/cli.py`,
  `tests/test_platform_scope.py`, `README.md` (CLI Reference block)
- Create: `tests/ops/test_cli.py`

**Interfaces:**

- Consumes: everything in `spend.py`, plus
  `_get_litellm_credentials(env_file) -> (base_url, master_key)` from `cli.py`.
- Produces:
  - `def build_ops_app(get_credentials: Callable[[Path | None], tuple[str, str]]) -> typer.Typer`.
    It returns a group named `ops` with one command, `spend-report`.
  - In `cli.py`, next to the other `add_typer` calls:
    `app.add_typer(build_ops_app(lambda env_file: _get_litellm_credentials(env_file)), name="ops")`.
    The lambda defers the lookup, because `_get_litellm_credentials` is defined
    later in the module.

Options follow the spec table:

- `--start` and `--end` use `formats=["%Y-%m-%d"]`.
- `--by` is `GroupBy`, default `key`.
- `--threshold` defaults to `2.0`.
- `--top` is `int | None`.
- `--from-zip` uses `exists=True`.
- `--csv` is a path.
- `-e/--env-file` is redefined locally with the same settings as
  `ENV_FILE_OPTION`.

Command flow:

1. `start > end` raises `typer.BadParameter` (exit 2).
2. Compute `bstart, bend = baseline_window(...)`.
3. Get records over `[bstart, end]`, from `iter_extract_records` or from
   `fetch_spend_records(*get_credentials(env_file), bstart, end)`, and build a
   list once.
4. Aggregate both windows. An empty baseline becomes `None`, and a note goes to
   `Console(stderr=True)`.
5. `compare`.
6. Print the table to stdout. Write the CSV if asked and note its path on
   stderr.
7. A `SpendFetchError` prints `✗ <message>` to stderr and exits 1.

- [ ] **Step 1: Write failing tests.**
  - `test_spend_report_from_zip_writes_csv`: a zip fixture with baseline and
    report days, run through `CliRunner` with `app` from `llmaven.cli` and
    `["ops", "spend-report", ..., "--from-zip", z, "--csv", c]`. Expects exit 0,
    a `spike` row in the CSV, and the label in stdout.
  - `test_spend_report_from_zip_without_baseline_notes_it`: no baseline records
    gives exit 0, an empty `flag` column and a note on stderr.
  - `test_spend_report_start_after_end_fails`: a non-zero exit, with no fetch or
    credential call.
  - `test_spend_report_fetch_error_exits_1`: uses `build_ops_app` with a stub
    credential callback, and monkeypatches `fetch_spend_records` to raise
    `SpendFetchError`. Expects exit 1 and `✗` in the output.
  - In `tests/test_platform_scope.py`, add `"ops"` to the expected set.
- [ ] **Step 2: Run them and confirm they fail.**
      `pixi run -e llmaven pytest tests/ops tests/test_platform_scope.py -q`
- [ ] **Step 3: Implement** `build_ops_app` and the registration. Add one line
      under the infra commands in the README CLI Reference block:
      `llmaven ops spend-report --start 2026-01-01 --end 2026-01-07  # Spend by key/user/model/team vs prior window`.
- [ ] **Step 4: Run them and confirm they pass.** Also run
      `pixi run -e llmaven python -c "import llmaven.ops, sys; assert 'llmaven.cli' not in sys.modules and 'llmaven.data' not in sys.modules"`.
- [ ] **Step 5: Commit.** `feat(cli): add llmaven ops spend-report command`

---

### Task 8: `investigate` hint on `llm_spend` alerts

**Files:**

- Modify: `src/llmaven/infrastructure/resources/monitoring.py` (`_llm_spend`)
- Test: `tests/infrastructure/test_monitoring_program.py`

**Interfaces:**

- Produces: a module constant
  `LLM_SPEND_INVESTIGATE = "llmaven ops spend-report --start <date> --end <date> -e <env file>"`
  and
  `actions=ActionsArgs(action_groups=[...], custom_properties={"investigate": LLM_SPEND_INVESTIGATE})`.

- [ ] **Step 1: Write a failing test.** Extend
      `test_llm_spend_hourly_and_daily_rules` so that, for both rules,
      `rule.inputs["actions"]["customProperties"] == {"investigate": LLM_SPEND_INVESTIGATE}`.
- [ ] **Step 2: Run it and confirm it fails.**
      `pixi run -e llmaven pytest tests/infrastructure/test_monitoring_program.py -q`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run it and confirm it passes.**
- [ ] **Step 5: Commit.**
      `feat(infra): name ops spend-report in llm_spend alerts`

---

### Task 9: Gate

**Files:** none.

- [ ] **Step 1:** Run `pixi run -e llmaven verify` and read the output. Fix
      failures in the task that owns the code.
- [ ] **Step 2 (opt-in, needs user approval):** against a deployed stack, run
      `llmaven ops spend-report --start <d> --end <d> -e <env>`. Check that the
      team label is filled in, which confirms Task 1 row 1.

## Verified facts

| #   | Answer                                                  | Source                                             |
| --- | ------------------------------------------------------- | -------------------------------------------------- |
| 1   |                                                         |                                                    |
| 2   |                                                         |                                                    |
| 3   |                                                         |                                                    |
| 4   |                                                         |                                                    |
| 5   | Yes: `ActionsArgs.custom_properties: Mapping[str, str]` | installed `pulumi_azure_native/monitor/_inputs.py` |
