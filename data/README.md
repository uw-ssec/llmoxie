# data

Utilities for working with raw LiteLLM request/response data, from either export
path described in the
[data pipeline epic](https://github.com/uw-ssec/llmoxie/issues/153):

- **ADLS** (preferred — never truncates message content): one `.json` file per
  request, written by `AdlLogger`
  (`src/llmaven/infrastructure/resources/adl_logger.py`) to
  `logs/<yyyy>/<mm>/<dd>/<request_id>.json` in the `litellm-logs` container.
- **LiteLLM PostgreSQL spend logs** (fallback, may truncate long messages):
  exported via

  ```sh
  pixi shell -e llmaven
  llmaven infra extract --from 2026-01-01 --to 2026-03-31 --out jan-feb-march-2026.zip -e .env
  ```

- **`reader.py`** — flattens raw request/response records (either format) into a
  tidy per-content-block DataFrame, plus helpers for deduplicating resent
  history and picking the longest request per session. See the docstring on each
  function for details.
- **`group_sessions.py`** — groups raw requests into full per-session
  conversations (addresses [#46](https://github.com/uw-ssec/llmoxie/issues/46)).
  See the docstring on each function for details.

## Grouping requests into sessions

```sh
pixi run -e llmaven python data/group_sessions.py path/to/jan-feb-march-2026.zip -o sessions.jsonl
pixi run -e llmaven python data/group_sessions.py path/to/adls/logs/ --format parquet
```

The input path accepts:

- a single `.jsonl` file (the `litellm_spend_logs_*.jsonl` format from
  `llmaven infra extract`)
- a single `.json` file (one request per file, the ADLS format)
- a directory containing either, searched recursively (so the ADLS
  `<yyyy>/<mm>/<dd>/` layout works)
- a `.zip` of any of the above (read directly from the archive, nothing is
  extracted to disk)

Output defaults to JSONL, one JSON object per line, one line per session:

```json
{
  "session_id": "...",
  "device_id": "...",
  "account_uuid": "...",
  "user_api_key_alias": "carlos-api",
  "models": ["claude-sonnet-4-5-20250929"],
  "n_requests": 205,
  "total_spend": 17.07,
  "total_tokens": 19794027,
  "start_time": "2026-03-19T18:23:02.530000Z",
  "end_time": "2026-03-19T22:38:38.010000Z",
  "messages": [
    {"role": "user", "content": [{"type": "text", "text": "..."}]},
    {"role": "assistant", "content": [{"type": "tool_use", "name": "...", "id": "...", "input": {...}}]}
  ]
}
```

Pass `--format parquet` for a flat table instead, one row per message block,
with session-level fields (spend, tokens, time span, ...) repeated onto every
row. Useful for tools that work better with a flat table than nested JSON.
There's no analysis notebook in this repo yet (worth adding as a follow-up), but
if you have one, try it against both formats and see which is easier to work
with.

Notes:

- Each request re-sends the _entire_ conversation so far, so a session's
  messages are reconstructed from its single longest/most-recent request rather
  than merged across requests.
- `total_spend`/`total_tokens` are summed across every request in the session,
  so they reflect total resources consumed (including the resent-history
  overhead), not the length of the final conversation.
- Requests with no `session_id` (in `end_user` for the spend-log format, or
  `standard_logging_object.end_user` for ADLS) can't be grouped and are skipped
  — the script logs how many.
- ADLS records from non-chat-completions API calls (e.g. GitHub Copilot traffic
  through OpenAI's Responses API) have their reply under `response.output`
  rather than `response.choices`, which isn't parsed yet — reader.py logs a
  warning and that request's final reply is simply missing from the session.
  Follow-up work if that traffic needs to be included.

On the Jan–Mar 2026 dump: 11,992 requests → 279 sessions in ~10s.
