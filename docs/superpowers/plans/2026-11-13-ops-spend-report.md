# Monitoring and Alerting, PR 3: Ops Spend Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `llmaven ops spend-report`. It shows which key, user, model or
team drove LLM spend in a date range, flags rows against the window before it,
and is named in the `llm_spend` alert payload through an `investigate` custom
property. Verified fact 4 says custom properties reach webhook, Logic App, Azure
Function and Automation runbook receivers only, so an operator who gets the
alert by email does not see the hint.

**Architecture:** A new package, `src/llmaven/ops/`, that imports nothing from
`llmaven.cli` or `llmaven.data`.

- `spend.py` holds pure functions and its own `/spend/logs/v2` fetch loop.
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
- **Spec correction:** custom properties do not reach email, SMS or push
  recipients, and do not show on the portal alert details page (verified fact
  4). Nothing in this plan may claim the alert email names the command. The
  property is still set, because it does reach webhook, Logic App, Azure
  Function and Automation runbook receivers.
- **Spec correction:** `/spend/logs` is deprecated and truncates at 10,000 rows
  (verified facts 3 and 6). Task 5 calls `/spend/logs/v2` and paginates.
- **Commits:**
  - Conventional format with scope `cli` (Tasks 2–7, 9) or `infra` (Task 8).
  - Add an `Assisted-by: <harness>:<model>` trailer.
  - Never add `Signed-off-by:`.
- **No live infrastructure.** No deploy, `--preview` or destroy without explicit
  user approval.

## Review Focus

1. **Day boundaries.** `/spend/logs/v2` compares `startTime` with `>=` against
   `start_date` and `<=` against `end_date`, and parses a bare `YYYY-MM-DD` as
   midnight UTC (verified fact 6). A per-day request must therefore widen the
   upper bound past midnight, or it returns only the records at exactly
   `00:00:00Z`. `fetch_spend_records` sends the next day's midnight —
   `end_date="<day + 1> 00:00:00"` — because `23:59:59` would lose anything
   stamped inside the final second of the day. Both bounds being inclusive means
   the request also picks up records at exactly the next day's midnight, so
   `fetch_spend_records` keeps only the records whose `startTime` falls on the
   requested day; those neighbours come back on that day's own request. Test in
   Task 5.
2. **`startTime` formats.** A trailing `Z`, a `+00:00` or other offset, and a
   naive timestamp must all land on the right UTC day. A missing or unparsable
   value is dropped and never crashes. Test in Task 2.
3. **Missing or `None` spend.** A missing or `None` `spend` counts as `0.0` and
   never raises. Test in Task 2.
4. **Unexpected response body.** A body that is not a mapping with a list `data`
   is an error naming the day; the report does not silently skip the day and
   under-report. The CLI exits 1 with `✗`, and the message never contains the
   key. Test in Task 5 (error) and Task 7 (exit code).
5. **Key leaks.** The full `api_key` value never appears in a label or CSV. An
   `api_key` that looks raw (`sk-` prefix) is labelled `(unhashed key)`, not by
   its prefix. Test in Tasks 2 and 6.

6. **Truncated pages.** `total` and `total_pages` from `/spend/logs/v2` stop
   counting at 10,000 records (verified fact 6), so they cannot drive the
   pagination loop. `fetch_spend_records` pages until a page comes back shorter
   than `page_size`. Test in Task 5.

Items 4 and 5 go beyond the spec, which says nothing about unexpected bodies or
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
| 6   | What does `/spend/logs/v2` require and return?                                         | Added after row 3 showed `/spend/logs` is deprecated           | `spend_management_endpoints.py` (`ui_view_spend_logs`) at the pinned image tag                       |

- [x] **Step 1: Answer each row** in `## Verified facts`. If an answer
      contradicts an assumption, stop and update the affected task first. Row 4
      is contradicted: custom properties never reach email, SMS or push
      recipients, so the Goal, Task 8 and the spec were rewritten to say "alert
      payload" and to name the receivers that do see it. Row 3 sent Task 5 to
      `/spend/logs/v2`, which row 6 then covers.
- [x] **Step 2: Commit.**
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

Team labels follow verified fact 1: `team_id` is a top-level column, and
`get_logging_payload` writes `""` when a request has no team. `group_label`
therefore treats `""` exactly like a missing value and falls back to
`metadata.user_api_key_team_alias`, then to `(no team)`.

- [ ] **Step 1: Write failing tests.**
  - `test_record_day_formats`: parametrized over `"2026-03-01T23:30:00Z"`,
    `"2026-03-01T23:30:00+00:00"`, `"2026-03-02T01:30:00+02:00"` and
    `"2026-03-01T23:30:00"`. Each gives `date(2026, 3, 1)`. `None`, `""` and
    `"garbage"` give `None`.
  - `test_group_label`: parametrized over every `--by` and every fallback (spec
    table plus the two key fallbacks). Covers `team_id: ""`, which must fall
    back rather than become an empty label. Asserts the full 64-char hash is not
    in the label.
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

- Consumes: LiteLLM `GET {base_url}/spend/logs/v2`.
- Produces:
  - `class SpendFetchError(Exception)`
  - `PAGE_SIZE = 1000`
  - `def fetch_spend_records(base_url: str, api_key: str, start: date, end: date, *, client: httpx.Client | None = None, sleep: Callable[[float], None] = time.sleep, attempts: int = 3) -> Iterator[dict]`

`/spend/logs` is deprecated and silently truncates at 10,000 rows (verified
facts 3 and 6), so this uses `/spend/logs/v2`.

For each day from `start` to `end`, page from `page = 1`:

- Send
  `params={"start_date": f"{day} 00:00:00", "end_date": f"{day + timedelta(days=1)} 00:00:00", "page": page, "page_size": PAGE_SIZE}`
  with the header `Authorization: Bearer <api_key>`. Both date bounds are
  inclusive and a bare `YYYY-MM-DD` parses as midnight UTC, so the explicit
  next-midnight upper bound is what makes the day whole (verified fact 6);
  `23:59:59` would drop anything stamped inside the final second.
- Read the page from `body["data"]`. Stop the day when `len(data) < PAGE_SIZE`,
  otherwise increment `page`. Do **not** use `total` or `total_pages`: both are
  capped at 10,000 records and under-report a busy day (Review Focus 6).
- Retry transport errors and 5xx up to `attempts`, sleeping `2 ** attempt`
  seconds. A retry re-sends the same page.
- Raise `SpendFetchError` on a 4xx, on exhausted retries, or on a body that is
  not a mapping with a list under `data`. The message names the day and the
  page, never the key.
- Yield only the records where `record_day(record) == day`.

`PAGE_SIZE` is 1000 because that is the server's `le` bound on `page_size`
(verified fact 6); a larger value is a 422.

When `client` is `None`, create `httpx.Client(timeout=30.0)` and close it
afterwards.

- [x] **Step 1: Write failing tests** using
      `httpx.Client(transport=httpx.MockTransport(handler))` and
      `sleep=lambda s: None`.
  - `test_fetch_one_request_per_day`: a 3-day range whose days each fit in one
    page makes 3 requests, each with `page=1`, `page_size=1000`,
    `start_date="<day> 00:00:00"`, `end_date="<day + 1> 00:00:00"` and a bearer
    header.
  - `test_fetch_pages_until_short_page`: a day whose first page returns
    `PAGE_SIZE` records and whose second returns fewer makes two requests for
    that day and yields both pages. Use a small monkeypatched `PAGE_SIZE` so the
    fixture stays readable.
  - `test_fetch_ignores_capped_totals`: the handler reports `total: 10000` and
    `total_pages: 10` while returning a short first page; exactly one request is
    made for that day (Review Focus 6).
  - `test_fetch_drops_records_from_next_day`: the handler returns a record for
    `day` and one for `day + 1`, and only the first is yielded (Review Focus 1).
  - `test_fetch_retries_5xx_then_succeeds`: the first response is 503, the
    second is 200.
  - `test_fetch_bad_body_raises`: a `{"detail": ...}` body, and a body whose
    `data` is not a list, each raise `SpendFetchError`, and `api_key` is not in
    `str(exc)`.
  - `test_fetch_4xx_raises_without_retry`: a 401 makes exactly one request.
- [x] **Step 2: Run them and confirm they fail.**
- [x] **Step 3: Implement.**
- [x] **Step 4: Run them and confirm they pass.**
- [x] **Step 5: Commit.** `feat(cli): fetch spend logs per day with retry`

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

Verified fact 4: custom properties are carried only in webhook, Logic App, Azure
Function and Automation runbook payloads. They are absent from email, SMS and
push notifications, and from the portal alert details page. Setting the property
is still worth it, because it makes the hint available to any such receiver
added to the action group later, but the docstring and the commit must not
promise it in the email. Leave a comment on the constant saying so.

- [ ] **Step 1: Write a failing test.** Extend
      `test_llm_spend_hourly_and_daily_rules` so that, for both rules,
      `rule.inputs["actions"]["customProperties"] == {"investigate": LLM_SPEND_INVESTIGATE}`.
- [ ] **Step 2: Run it and confirm it fails.**
      `pixi run -e llmaven pytest tests/infrastructure/test_monitoring_program.py -q`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run it and confirm it passes.**
- [ ] **Step 5: Commit.**
      `feat(infra): attach ops spend-report hint to llm_spend alert payloads`

---

### Task 9: Gate

**Files:** none.

- [ ] **Step 1:** Run `pixi run -e llmaven verify` and read the output. Fix
      failures in the task that owns the code.
- [ ] **Step 2 (opt-in, needs user approval):** against a deployed stack, run
      `llmaven ops spend-report --start <d> --end <d> -e <env>`. Check that the
      team label is filled in, which confirms Task 1 row 1.

## Verified facts

| #   | Answer                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | Source                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Confirmed: `LiteLLM_SpendLogs.team_id String?` is a top-level column; the display name is `metadata.user_api_key_team_alias`. `get_logging_payload` sets `team_id=metadata.get("user_api_key_team_id", "") or ""`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | litellm `v1.108.6`: `schema.prisma` (`model LiteLLM_SpendLogs`), `litellm/proxy/_types.py` (`class SpendLogsMetadata`), `litellm/proxy/spend_tracking/spend_tracking_utils.py` (`get_logging_payload` L542, `team_id=` L847)                                                                                                                                                                                                                                                                                    |
| 2   | Confirmed: SHA-256 hex, never `sk-...`. Schema comment: `// Hashed API Token. Not the actual Virtual Key.` `_redact_logged_api_key` strips `bearer ` and returns `hash_token(...)`, which is `hashlib.sha256(token.encode()).hexdigest()`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | litellm `v1.108.6`: `schema.prisma` (`api_key` column), `litellm/proxy/spend_tracking/spend_tracking_utils.py` (`_redact_logged_api_key` L139), `litellm/proxy/utils.py` (`hash_token` L8026)                                                                                                                                                                                                                                                                                                                   |
| 3   | Effectively no. The filter is `startTime: {gte: start, lte: end}`, but `end_date` is parsed as `strptime(end, "%Y-%m-%d").replace(tzinfo=utc)` — midnight — so only records at exactly `00:00:00Z` on the end day match. The route is `[DEPRECATED]` in favour of `/spend/logs/v2` and takes at most `SPEND_LOGS_PAGINATION_COUNT_CAP` (10,000) rows, logging `"/spend/logs result truncated to the %s most recent rows"`. **Consequence:** Task 5 moved to `/spend/logs/v2` (row 6)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | litellm `v1.108.6`: `litellm/proxy/spend_tracking/spend_management_endpoints.py` (`view_spend_logs`, L3511; `take=SPEND_LOGS_PAGINATION_COUNT_CAP` L3642 and L3695; truncation warning L385)                                                                                                                                                                                                                                                                                                                    |
| 4   | **Contradicted.** Custom properties are added only to webhook / Logic Apps / Azure Functions / Automation runbook payloads. Verbatim: "They aren't included in email, SMS, or push notifications, and they don't appear in the alert details page in the Azure portal." The common schema does define a top-level `customProperties` object, but only for webhook notifications                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | [Create Azure Monitor log search alert rules](https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/alerts-create-log-alert-rule) (Custom properties note); [Common alert schema](https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/alerts-common-schema) (Custom properties fields)                                                                                                                                                                                                          |
| 5   | Yes: `ActionsArgs.custom_properties: Mapping[str, str]`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | installed `pulumi_azure_native/monitor/_inputs.py`                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| 6   | `/spend/logs/v2` and `/spend/logs/ui` both route to `ui_view_spend_logs`. `start_date` and `end_date` are required (a missing one is a 400 `"Start date and end date are required"`). v2 accepts `"%Y-%m-%d %H:%M:%S"` or `"%Y-%m-%d"`; both are parsed with `strptime(...).replace(tzinfo=timezone.utc)`, so a bare date is midnight UTC. The SQL filter is `"startTime" >= $p` **and** `"startTime" <= $p`, inclusive at both ends — a whole day needs `end_date="<day> 23:59:59"`. Paging is `page` (`ge=1`, default 1) and `page_size` (`ge=1, le=1000`, default 50), applied as `LIMIT page_size OFFSET (page-1)*page_size`. The body is `{"data": [...], "total", "page", "page_size", "total_pages", "total_is_capped"}`. `total` is counted with `LIMIT CAP + 1` and clamped to `SPEND_LOGS_PAGINATION_COUNT_CAP = 10000`, and `total_pages` is derived from it — **so neither may drive a pagination loop**; page until a short page. The selected columns include `api_key`, `"user"`, `model`, `team_id`, `spend`, `"startTime"` and `metadata`, and exclude `messages`, `response` and `proxy_server_request`. A JSONB `metadata` returned as a string is `json.loads`-ed back to a dict with its keys untouched, so `user_api_key_alias` survives | litellm `v1.108.6`: `litellm/proxy/spend_tracking/spend_management_endpoints.py` — route decorators L2513/L2521 and handler `ui_view_spend_logs` L2529; `is_v2` L2660; `page`/`page_size` L2568–L2569; required dates L2714–L2722; accepted formats L2723; inclusive bounds L2867/L2870; `_SPEND_LOG_LIST_COLUMNS` L111–L123; `_hydrate_spend_log_metadata` L3311; `SPEND_LOGS_PAGINATION_COUNT_CAP` L87, count cap L3041 and `total_pages` L3084; response dict in `_build_ui_spend_logs_response` L4837–L4844 |

Residual uncertainty on row 6: `user_api_key_team_alias` does not appear
anywhere in `spend_management_endpoints.py`. Row 1 is the evidence that LiteLLM
writes it into `metadata`, and row 6 only shows that `/spend/logs/v2` returns
`metadata` unmodified. Task 9 Step 2 is still the check that the team label
fills in against a real deployment.
