# Console React Front End Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** `console-web` keeps its server duties and its pages become a React
application built from shadcn/ui components and styled to the SSEC design
system.

**Architecture:** FastAPI gains a JSON API under `/web-api/` whose responses are
built field by field from the broker's replies. A Vite + React application in
`services/console/frontend/` builds to static files that FastAPI serves for
every page URL. Sign-in, the callback, sign-out and invitation acceptance stay
plain browser navigations.

**Tech Stack:** Python 3.12, FastAPI, psycopg, httpx (existing); Vite, React 19,
TypeScript, React Router 7, Tailwind 4, shadcn/ui, Vitest, Testing Library
(new).

**Spec:** `docs/superpowers/specs/2026-11-12-console-react-frontend-design.md`.
Read it before any task.

## Global Constraints

- All paths below are relative to `services/console/` unless they start with
  `docs/`, `knowledge/` or `~`.
- Content security policy, exactly:
  `default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self' <identity provider origin>`.
  Never add `'unsafe-inline'`, `'unsafe-eval'` or another origin. If a component
  needs one, use a different component.
- Cookies, the `Origin` check, token refresh, the policy check before every
  broker call, `/healthz` and `/api/v1/*` do not change.
- A response under `/web-api/` carries only the fields named in Task 1. Never
  `participant_id`, never `team_orgs`, never `mcp_server_id`, never raw Markdown.
- An API key lives in React state only. Never `localStorage`, `sessionStorage`,
  router history state, or the session row.
- No request to any other origin: fonts and all assets are bundled.
- Buttons have corner radius 0. Teal, green, pink and spirit-gold are never text
  on white.
- Error shape for every `/web-api/` failure:
  `{"error": {"status": <int>, "message": "<text>"}}`.
- CSRF token travels in the `X-CSRF-Token` header on every `/web-api/` post.
- Toolchain from Pixi (`nodejs` in the console's `pixi.toml`); JavaScript
  packages from npm with a committed `package-lock.json`. Never `pip`, `conda`
  or `venv` directly.
- The local stack at `~/Agent-Workspace/litellm-keycloak` is used through a
  compose override kept outside both repositories. Never edit or commit in that
  repository. Ask the owner before recreating a volume, creating a database
  there, or editing its files.
- Commits: `git -c user.email="$(git config --global user.email)" commit`, a
  Conventional Commits subject, and the trailer
  `Assisted-by: claude-code:claude-fable-5-2`. Never `--no-verify`. Run
  `pixi run -e llmaven verify` from the repository root before each commit. Push
  only when the owner asks.

## Review Focus

1. **The session ends while the application is open.** An action answers 401.
   Expected: the browser goes to `/?next=<current path>`, not a broken screen.
   Pinned in Task 6.
2. **Reload or Back after a key was shown.** Expected: the key is gone and
   cannot be recovered. Pinned in Task 10.
3. **The broker is down, or `console-web` answers with something that is not
   JSON.** Expected: an error screen with the message and a way back, never a
   blank page. Pinned in Task 6.
4. **A crafted `next` value** such as `//evil.example` or `https:evil`.
   Expected: sign-in lands on `/`. Pinned in Task 5.
5. **A double click on a slow action** (create key, send invitations).
   Expected: one request; the button is disabled while it runs. Pinned in
   Task 6.

---

## File Structure

```
services/console/
  console_app/web/
    app.py          app, middleware, native routes, /api/v1, shell (shrinks)
    visit.py        Visit, ApiError, error handlers (moved out of app.py)
    shapes.py       pure functions: broker reply -> browser response
    api.py          APIRouter(prefix="/web-api"): session, page data, actions
    dist/           built front end (gitignored)
    templates/      deleted in Task 5
    static/         deleted in Task 5
  frontend/
    package.json, package-lock.json, vite.config.ts, tsconfig*.json,
    components.json, eslint.config.js, index.html
    src/main.tsx, src/router.tsx
    src/styles/ssec-tokens.css   vendored, pinned
    src/styles/app.css           Tailwind entry, theme mapping, fonts
    src/lib/api.ts               fetch client, ApiError, session store
    src/lib/types.ts             response types (mirror of shapes.py)
    src/lib/format.ts            money, dates
    src/lib/use-action.ts        post + toast + reload + goto
    src/components/ui/           shadcn components
    src/components/              app-shell, page-header, code-block,
                                 status-badge, confirm-dialog,
                                 type-to-confirm-dialog, form-field
    src/pages/                   one file per screen
  tests/
    test_shapes.py   new, pure, no stack needed
    test_web_api.py  new, shell + headers + API plumbing
    helpers.py, test_console.py, test_knowledge.py, test_dlp.py,
    test_integration.py, test_operator.py   ported to JSON
```

---

### Task 0: Branch, stack and baseline

**Files:**

- Create (outside both repos): `<scratchpad>/stack/override.yml`
- Create (gitignored): `tests/.env`

- [ ] **Step 1:** Create branch `console-react-ui` from `llmoxie-console`.
      Commit the spec and this plan (`docs(console): ...`).
- [ ] **Step 2:** Start the stack: in `~/Agent-Workspace/litellm-keycloak`, run
      its documented `docker-compose up -d --wait`. Confirm every service is
      healthy.
- [ ] **Step 3:** Compare the live `console_db` with `db/console-db.sql`
      (`\dt` and `\d <table>` through the stack's Postgres container). Expected:
      the same tables plus `agent`. Anything else: stop and ask the owner.
- [ ] **Step 4:** Write `override.yml` so `console-init`, `console-broker` and
      `console-web` build from this repository
      (`build.context: <abs path>/services/console`, `target: app`) under a
      distinct image name `llmoxie-console:dev`. Recreate those three services
      with both compose files.
- [ ] **Step 5:** Fill `tests/.env` from `tests/env.example`, using the values
      in the stack's `console-tests` service. Run
      `pixi run test <stack network>`.
- [ ] **Step 6:** Record which tests pass and fail in the task notes. This is
      the baseline; a test that fails here is not this plan's regression. If
      the suite cannot run at all, stop and report.

---

### Task 1: Response shapes

**Files:**

- Create: `console_app/web/shapes.py`
- Test: `tests/test_shapes.py`

**Interfaces:**

- Produces (all pure, no imports from `app.py`, `sessions` or `oidc`):

```python
def session(me: dict, csrf: str, gateway_url: str, litellm_admin_url: str) -> dict
def admin_orgs(orgs: list[dict]) -> dict
def audit(events: list[dict]) -> dict
def dlp(view: dict, actions: dict[str, str]) -> dict
def org(view: dict, *, is_lead: bool, is_admin: bool) -> dict
def knowledge(view: dict, *, concept: dict | None, body_html: str,
              links_out: list[dict], links_in: list[dict],
              graph: dict, log_html: str) -> dict
def team_manage(view: dict, usage: list[dict], *, is_lead: bool) -> dict
def my_team(view: dict) -> dict
def invite(info: dict) -> dict
def key(created: dict) -> dict
```

Fields each returns, and nothing else:

| Function      | Fields                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `session`     | `signed_in: true`, `csrf`, `me: {email, is_admin, lead_orgs: [{id, name, status}], teams: [{id, name, org_name, status}]}`, `config: {gateway_url, litellm_admin_url}`                                                                                                                                                                                                                                                                  |
| `admin_orgs`  | `orgs: [{id, name, slug, budget_ceiling, leads, teams, status}]`                                                                                                                                                                                                                                                                                                                                                                        |
| `audit`       | `events: [{at, actor_email, actor_role, action, result, org_name, team_name}]`                                                                                                                                                                                                                                                                                                                                                          |
| `dlp`         | `enabled`, `read`, `shown`, `actions`, `totals: [{kind, action, count}]`, `events: [{at, kinds, blocked, action, source, mode, count, email, user_id, request}]` where `request` is the first 8 characters of `request_id`. When `enabled` is false, only `enabled`.                                                                                                                                                                     |
| `org`         | `org: {id, name, slug, status, budget_ceiling}`, `is_lead`, `is_admin`, `leads: [{email}]` plus `id` only when `is_admin`, `lead_invites: [{id, email, status, signin_email}]` (empty list unless `is_admin`), `models: [{id, public_name, provider}]`, `providers`, `teams: [{id, name, members, team_budget, status}]`                                                                                                                |
| `knowledge`   | `org: {id, name}`, `tools`, `edge_count`, `concepts: [{id, title, type, description, tags, links, written_at}]`, `concept: null \| {id, title, type, status, written_at, tags, description, html, links_out: [{id, title, note}], links_in: [{id, title, note}]}`, `graph` (as `graph.picture` returns it), `log_html` (empty string when there is no log)                                                                              |
| `team_manage` | `team: {id, name, status, org_id, org_name, org_status, org_budget_ceiling, team_budget, key_limit, key_budget, key_expiry_days}`, `is_lead`, `models: [{id, public_name, allowed}]`, `members: [{id, email, terms_accepted, keys}]`, `invites: [{id, email, status, signin_email}]`, `keys: [{id, email, name, waiting, hint, created_at, expires, last_used, spend}]`, `usage: [{email, requests, failed, tokens, spend}]`, `integrations: [{id, name, client_id, can_enroll}]` |
| `my_team`     | `team: {id, name, status, org_name, org_status, consent_text, key_limit, key_budget, key_expiry_days}`, `consent: null \| {terms_accepted, research_use}`, `keys: [{id, name, waiting, created_at}]`, `models: [str]`, `knowledge_tools`, `usage: {requests, tokens, spend}`                                                                                                                                                              |
| `invite`      | `valid`, and when valid `kind`, `org_name`, `team_name`                                                                                                                                                                                                                                                                                                                                                                                 |
| `key`         | `name`, `key`                                                                                                                                                                                                                                                                                                                                                                                                                           |

- [ ] **Step 1: Write the failing tests** in `tests/test_shapes.py`. Feed each
      function a broker-style reply that holds extra fields, and assert the exact
      key set at every level. Required cases:

```python
def test_session_drops_identifiers():
    out = shapes.session(ME, "tok", "http://g", "")
    assert set(out["me"]) == {"email", "is_admin", "lead_orgs", "teams"}
    assert "participant_id" not in json.dumps(out) and "team_orgs" not in json.dumps(out)

def test_team_manage_never_carries_participant_id():
    out = shapes.team_manage(TEAM_VIEW, USAGE, is_lead=True)
    assert "participant_id" not in json.dumps(out)
    assert set(out["members"][0]) == {"id", "email", "terms_accepted", "keys"}
    assert set(out["usage"][0]) == {"email", "requests", "failed", "tokens", "spend"}

def test_org_hides_lead_ids_and_invites_from_a_lead():
    out = shapes.org(ORG_VIEW, is_lead=True, is_admin=False)
    assert set(out["leads"][0]) == {"email"} and out["lead_invites"] == []
    assert "mcp_server_id" not in json.dumps(out)

def test_org_gives_an_admin_what_the_remove_buttons_need():
    out = shapes.org(ORG_VIEW, is_lead=False, is_admin=True)
    assert set(out["leads"][0]) == {"id", "email"} and out["lead_invites"]

def test_knowledge_carries_no_raw_markdown():
    out = shapes.knowledge(KNOWLEDGE_VIEW, concept=None, body_html="", links_out=[],
                           links_in=[], graph=GRAPH, log_html="")
    assert out["concept"] is None and "body" not in json.dumps(out) and "log" not in out

def test_dlp_shortens_the_request_id():
    assert shapes.dlp(DLP_VIEW, {})["events"][0]["request"] == DLP_VIEW["events"][0]["request_id"][:8]
```

      Add one exact-key-set test for each remaining function.

- [ ] **Step 2:** Run `pixi run -e llmaven pytest services/console/tests/test_shapes.py -q`
      from the repository root. Expected: import error, `shapes` missing.
- [ ] **Step 3:** Implement `shapes.py`. One private helper
      `_pick(row: dict, *fields: str) -> dict`; every function builds its result
      from `_pick` calls, so a new broker field never leaks by default. Values
      keep the broker's types (UUIDs and datetimes are already JSON strings).
- [ ] **Step 4:** Run the same command. Expected: all pass.
- [ ] **Step 5:** Commit: `feat(console): add browser response shapes`.

---

### Task 2: Browser API plumbing, session and page data

**Files:**

- Create: `console_app/web/visit.py`, `console_app/web/api.py`
- Modify: `console_app/web/app.py` (import `Visit` from `visit.py`, include the
  router; the HTML routes stay for now)
- Test: `tests/test_web_api.py`, `tests/helpers.py`

**Interfaces:**

- Consumes: `shapes.*` from Task 1.
- Produces:

```python
# visit.py
class ApiError(Exception):
    def __init__(self, status: int, message: str): ...
class Visit:  # same constructor and methods as today
    def __init__(self, request: Request, *, api: bool = False)
```

With `api=True`: no session raises `ApiError(401, "You are signed out.")`; the
broker's 401, 403, 404 and 502 raise `ApiError` with today's wording; a 409 or
422 raises `ApiError(status, detail)` whether or not `back` is given.
`check_csrf(token)` raises `ApiError(403, "This form has expired. Go back,
reload the page and try again.")`. With `api=False` behaviour is exactly today's.
`app.py` registers a handler that turns `ApiError` into the global error shape
with `Cache-Control: no-store`.

```python
# helpers.py additions
Browser.api_get(path: str) -> httpx.Response        # GET CONSOLE + "/web-api" + path
Browser.api_post(path: str, json: dict | None = None, *, files=None, data=None,
                 csrf: str | None = ...) -> httpx.Response   # sends X-CSRF-Token
sign_in(...)  # unchanged walk; afterwards sets browser.csrf from /web-api/session
```

Routes added in `api.py` (each: `Visit(request, api=True)`, `visit.require(...)`
with the same action name as today's HTML route, broker call, shape):

| Route                                       | Policy action   | Shape                |
| ------------------------------------------- | --------------- | -------------------- |
| `GET /web-api/session`                      | none            | `{"signed_in": false}` or `shapes.session` |
| `GET /web-api/admin/orgs`                   | `org.list`      | `shapes.admin_orgs`  |
| `GET /web-api/admin/audit`                  | `audit.read`    | `shapes.audit`       |
| `GET /web-api/admin/dlp`                    | `dlp.read`      | `shapes.dlp`         |
| `GET /web-api/orgs/{org_id}`                | `org.view`      | `shapes.org`         |
| `GET /web-api/orgs/{org_id}/knowledge`      | `org.knowledge` | `shapes.knowledge`; query `concept` |
| `GET /web-api/teams/{team_id}/manage`       | `team.view`     | `shapes.team_manage` (calls broker `/manage` and `/usage`) |
| `GET /web-api/teams/{team_id}`              | `my.team`       | `shapes.my_team`     |
| `GET /web-api/invites/{token}`              | none, no session | `shapes.invite`; token length rule as today (20 to 200) |

`GET /web-api/session` never raises: no session, or a session that cannot be
refreshed, answers `{"signed_in": false}`.

- [ ] **Step 1: Write the failing tests** in `tests/test_web_api.py`:

```python
def test_session_reports_signed_out_without_a_cookie():
    r = Browser().api_get("/session")
    assert r.status_code == 200 and r.json() == {"signed_in": False}
    assert r.headers["cache-control"] == "no-store"

def test_page_data_needs_a_session_and_says_so_as_json():
    r = Browser().api_get("/admin/orgs")
    assert r.status_code == 401 and r.json() == {"error": {"status": 401, "message": "You are signed out."}}

def test_admin_session_carries_no_identifiers():
    alice = sign_in("alice", "alice123")
    body = alice.api_get("/session").json()
    assert body["signed_in"] and body["me"]["is_admin"] and len(body["csrf"]) >= 24
    assert "participant_id" not in json.dumps(body) and "team_orgs" not in json.dumps(body)

def test_unknown_org_is_a_json_404():
    alice = sign_in("alice", "alice123")
    r = alice.api_get(f"/orgs/{uuid.uuid4()}")
    assert r.status_code == 404 and r.json()["error"]["status"] == 404

def test_invitation_lookup_needs_no_session():
    r = Browser().api_get("/invites/" + "x" * 30)
    assert r.status_code == 200 and r.json() == {"valid": False}
```

- [ ] **Step 2:** Rebuild and restart `console-web` and `console-broker` with the
      override, run `pixi run test <network> -- tests/test_web_api.py` (pass the
      file the way the task accepts extra pytest arguments; if it does not,
      run the test image's `pytest` by hand). Expected: 404s, tests fail.
- [ ] **Step 3:** Move `Stop`, `Visit` and the error helpers into `visit.py`
      with the `api` flag. Write `api.py` with the routes above. The knowledge
      route reuses the link and graph logic now in `org_knowledge`; move that
      logic into `api.py` and have the old HTML route call it.
- [ ] **Step 4:** Rebuild, restart, run `tests/test_web_api.py`. Expected: pass.
      Run the whole suite. Expected: the Task 0 baseline, unchanged.
- [ ] **Step 5:** Commit: `feat(console): add the browser API for page data`.

---

### Task 3: Browser API actions

**Files:**

- Modify: `console_app/web/api.py`
- Test: `tests/test_web_api.py`

**Interfaces:**

- Produces: every action below, as `POST` under `/web-api`, each doing
  `visit.check_csrf(request.headers.get("x-csrf-token", ""))`, the same
  `visit.require(...)` as today's form route, the same broker call, and
  returning `{"message": <today's flash text>}` plus the extras shown. Bodies
  are JSON with today's field names and the same trimming.

| Route                                                        | Body                                                        | Extras                              |
| ------------------------------------------------------------ | ----------------------------------------------------------- | ----------------------------------- |
| `/admin/orgs`                                                | `name, slug, budget_ceiling`                                | `goto: /orgs/{id}`                  |
| `/admin/orgs/{org_id}/suspend`, `/resume`                    | none                                                        |                                     |
| `/admin/orgs/{org_id}/ceiling`                               | `budget_ceiling`                                            |                                     |
| `/admin/orgs/{org_id}/remove`                                | `confirm_slug`                                              | `goto: /admin`                      |
| `/admin/orgs/{org_id}/leads`                                 | `email`                                                     |                                     |
| `/admin/orgs/{org_id}/lead-requests/{invite_id}`             | `approve: bool`                                             |                                     |
| `/admin/orgs/{org_id}/leads/{person_id}/remove`              | none                                                        |                                     |
| `/admin/orgs/{org_id}/lead-invites/{invite_id}/revoke`       | none                                                        |                                     |
| `/admin/teams/{team_id}/remove`                              | `confirm_name`                                              | `goto: /orgs/{org_id}`              |
| `/admin/teams/{team_id}/integrations`                        | `client_id, name, can_enroll: bool`                         |                                     |
| `/admin/integrations/{integration_id}/remove`                | none                                                        | `goto: /teams/{team_id}/manage`     |
| `/orgs/{org_id}/models`                                      | `provider, model, api_key, api_base, api_version`           |                                     |
| `/orgs/{org_id}/models/{model_id}/remove`                    | none                                                        |                                     |
| `/orgs/{org_id}/teams`                                       | `name, key_limit, key_budget, key_expiry_days, team_budget, consent_text` | `goto: /teams/{id}/manage` |
| `/teams/{team_id}/invites`                                   | **multipart**: `emails`, `csv_file`                         |                                     |
| `/teams/{team_id}/budget`                                    | `team_budget`                                               |                                     |
| `/teams/{team_id}/models`                                    | `model_ids: [str]`                                          |                                     |
| `/teams/{team_id}/archive`                                   | none                                                        |                                     |
| `/teams/{team_id}/invites/{invite_id}/revoke`                | none                                                        |                                     |
| `/teams/{team_id}/requests/{invite_id}`                      | `approve: bool`                                             |                                     |
| `/teams/{team_id}/keys/{key_id}/revoke`, `/rotate`           | none                                                        |                                     |
| `/teams/{team_id}/members/{person_id}/remove`                | none                                                        |                                     |
| `/teams/{team_id}/my/consent`                                | `terms_accepted: bool, research_use: bool`                  |                                     |
| `/teams/{team_id}/my/keys`                                   | `name`                                                      | `key: shapes.key(...)`, `rotated: false`, no `message` |
| `/teams/{team_id}/my/keys/{key_id}/rotate`                   | none                                                        | `key: shapes.key(...)`, `rotated: true`, no `message`  |
| `/teams/{team_id}/my/keys/{key_id}/delete`                   | none                                                        |                                     |

Declare `/teams/{team_id}/invites` before any broader team route. The invite
route keeps today's two refusals as `ApiError(422, ...)`: "That file is too
large (200 KB at most)." and "No email addresses found.". Request bodies that
fail validation answer 422 with message "Some of those values are not valid.".

- [ ] **Step 1: Write the failing tests** (append to `tests/test_web_api.py`):

```python
def test_posts_without_the_csrf_header_are_refused():
    alice = sign_in("alice", "alice123")
    r = alice.api_post("/admin/orgs", {"name": "N", "slug": "n-x", "budget_ceiling": 1}, csrf=None)
    assert r.status_code == 403 and "expired" in r.json()["error"]["message"]

def test_cross_site_posts_are_refused_before_anything_else():
    alice = sign_in("alice", "alice123")
    r = alice.request("POST", CONSOLE + "/web-api/admin/orgs", headers={"Origin": "http://evil.example"})
    assert r.status_code == 403

def test_a_bad_value_comes_back_as_a_message_not_a_stack_trace():
    alice = sign_in("alice", "alice123")
    r = alice.api_post("/admin/orgs", {"name": "N", "slug": "Not A Slug", "budget_ceiling": 1})
    assert r.status_code == 422 and isinstance(r.json()["error"]["message"], str)

def test_creating_an_org_answers_with_a_message_and_where_to_go():
    alice = sign_in("alice", "alice123")
    r = alice.api_post("/admin/orgs", {"name": f"Web API {RUN}", "slug": f"wa-{RUN}", "budget_ceiling": 5})
    body = r.json()
    assert r.status_code == 200 and body["message"] == f"Created Web API {RUN}."
    assert body["goto"].startswith("/orgs/") and set(body) == {"message", "goto"}
```

- [ ] **Step 2:** Rebuild, restart, run. Expected: 404 or 405, tests fail.
- [ ] **Step 3:** Implement the routes with Pydantic request models.
- [ ] **Step 4:** Rebuild, restart, run `tests/test_web_api.py`. Expected: pass.
      Whole suite: baseline unchanged.
- [ ] **Step 5:** Commit: `feat(console): add the browser API actions`.

---

### Task 4: Port the end-to-end suite to the browser API

**Files:**

- Modify: `tests/helpers.py`, `tests/test_console.py`, `tests/test_knowledge.py`,
  `tests/test_dlp.py`, `tests/test_integration.py`, `tests/test_operator.py`

**Interfaces:**

- Consumes: `Browser.api_get`, `Browser.api_post` (Task 2), all routes (Tasks 2
  and 3).
- Produces: a suite that never reads console HTML, except the "Signed in" page
  inside `sign_in` and the checks Task 5 adds.

Rules for the port:

- Each test keeps its name and what it proves.
- `browser.page(path)` + text assertion becomes `api_get` + field assertion.
- `browser.post(path, form)` becomes `api_post(path, json)`. A redirect target
  assertion becomes an assertion on `goto`. A flash assertion becomes an
  assertion on `message` or `error.message`.
- "This button is not on the page" becomes: the flag that hides it is false
  (`is_lead`, `is_admin`, status), **and** the post is refused with 403.
- `test_lead_sees_who_holds_which_keys_but_never_a_key` asserts the key string,
  with and without its `sk-` prefix, is absent from the full JSON text of the
  manage response.
- `test_participant_registers_consents_and_gets_a_key_shown_once` asserts the
  key is in the create response and in no later `GET /web-api/teams/{id}`.
- `test_forms_refuse_cross_site_and_tokenless_posts` targets `/web-api/` posts
  and `POST /logout`.
- `test_console_web_enforces_the_same_rules` targets `/web-api/` routes.
- Knowledge: add an assertion that with no `concept` query the response holds
  no concept text, and that with one it holds that concept's HTML only. The
  untrusted-Markdown test asserts on `concept.html`.

- [ ] **Step 1:** Port `helpers.py` and `test_console.py`. Rebuild is not
      needed; run the suite. Expected: `test_console.py` at the baseline.
- [ ] **Step 2:** Port the other four files. Run the whole suite. Expected:
      the baseline, with no test reading console HTML
      (`grep -n "\.text" tests/test_*.py` shows only Keycloak, Mailpit and
      gateway responses).
- [ ] **Step 3:** Commit: `test(console): drive the suite through the browser API`.

---

### Task 5: Front-end scaffold, packaging and the switch to the shell

After this task the Jinja pages are gone and the console serves a placeholder
application. The suite stays green because it no longer reads pages.

**Files:**

- Create: `frontend/` scaffold (see File Structure), `frontend/src/styles/ssec-tokens.css`,
  `frontend/src/styles/app.css`
- Modify: `console_app/web/app.py`, `Dockerfile`, `pixi.toml`, `pixi.lock`,
  `.gitignore`, `.dockerignore`, `requirements.txt`
- Delete: `console_app/web/templates/`, `console_app/web/static/`
- Test: `tests/test_web_api.py`, `frontend/src/App.test.tsx`

**Interfaces:**

- Produces:
  - `npm run build` in `frontend/` writes to `../console_app/web/dist`
    (`index.html` with `<div id="root">`, hashed files under `assets/`).
  - `npm run check` runs ESLint, `tsc --noEmit` and `vitest run`.
  - Pixi tasks in the console manifest, all with `cwd = "frontend"`:
    `ui-install` (`npm ci`), `ui-build`, `ui-check`, `ui-watch`
    (`npm run build -- --watch`).
  - `app.py`: `/assets` served from `dist/assets`; any other `GET` not under
    `web-api/`, `api/` or `assets/` returns `dist/index.html`; those three
    prefixes answer 404 for unknown paths (JSON error shape under `web-api/`).
    If `dist/index.html` is missing, 503 with plain text
    "The console's front end has not been built.".
  - `GET /auth/callback` success: the "Signed in" page, built in Python with
    `html.escape`, still carrying
    `<meta http-equiv="refresh" content="0; url=<target>">` and a "Continue"
    link. Failure: `303` to `/?signin=failed`.
  - `POST /logout` and `POST /invite/{token}` errors: plain-text responses with
    today's status codes.
  - CSP header: the exact string in Global Constraints.
  - Theme: Tailwind `@theme` in `app.css` maps shadcn variables to the vendored
    tokens: `--primary: purple-700`, hover `purple-900`, `--destructive: #c62828`,
    `--border: #d5d8de`, `--ring: #6b4fa6`, `--radius: 8px`, with the button
    component overridden to radius 0, uppercase, `--font-compressed`, focus ring
    `0 0 0 0.2rem rgba(75, 46, 131, 0.5)`. Fonts imported from self-hosted
    packages: Encode Sans, Encode Sans Compressed, Open Sans, JetBrains Mono.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_web_api.py`):

```python
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
       "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self' ")

@pytest.mark.parametrize("path", ["/", "/admin", "/orgs/abc", "/teams/abc/manage", "/invite/" + "x" * 30, "/nope"])
def test_every_page_url_serves_the_shell(path):
    r = Browser().get(path)
    assert r.status_code == 200 and '<div id="root">' in r.text
    assert r.headers["content-security-policy"].startswith(CSP)
    assert "unsafe" not in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"

def test_the_shell_loads_only_its_own_files():
    html = Browser().get("/").text
    urls = re.findall(r'(?:src|href)="([^"]+)"', html)
    assert urls and all(u.startswith("/assets/") for u in urls)
    assert "<script>" not in html and "style=" not in html

def test_unknown_api_paths_are_not_the_shell():
    assert Browser().api_get("/nope").status_code == 404
    assert Browser().get("/api/v1/nope").status_code in (404, 405)

@pytest.mark.parametrize("next_value", ["//evil.example", "https:evil.example", "/\\evil", "/" + "a" * 300])
def test_a_crafted_next_lands_on_home(next_value):
    b = sign_in("alice", "alice123", start=("/login", {"next": next_value}))
    assert b.landed_path == "/"

def test_a_failed_sign_in_returns_to_the_sign_in_screen():
    r = Browser().get("/auth/callback?code=x&state=y", follow=False)
    assert r.status_code == 303 and r.headers["location"] == "/?signin=failed"
```

      And `frontend/src/App.test.tsx`: the placeholder app renders the text
      "LLMoxie console".

- [ ] **Step 2:** Run the Python tests. Expected: fail (pages are still Jinja).
- [ ] **Step 3:** Vendor the tokens: fetch
      `design-system/01-tokens.css` from `uw-ssec/uw-ssec.github.io` at commit
      `d3f017b` into `frontend/src/styles/ssec-tokens.css`, with a header comment
      giving the repository, path, commit and date (2026-09-11).
- [ ] **Step 4:** Scaffold the front end. Follow the current shadcn "Vite"
      installation guide (read it; the CLI changes between releases). Add
      `nodejs` (current active LTS) to the console `pixi.toml` and regenerate
      its lock with `pixi lock`. Confirm each font package exists on npm before
      adding it; if one does not, commit the font files (they are OFL-licensed)
      under `frontend/src/fonts/`.
- [ ] **Step 5:** Add the Node build stage to the `Dockerfile` (same Node major
      as Pixi, pinned by digest), copy `dist` into the `app` stage. Update
      `.gitignore` and `.dockerignore` (`frontend/node_modules`,
      `console_app/web/dist`).
- [ ] **Step 6:** Switch `app.py`: remove every HTML page route and form route,
      the Jinja setup and the flash helpers; add the shell, the new CSP and the
      callback changes. Delete `templates/` and `static/`. Remove `Jinja2` from
      `requirements.txt` only if `markupsafe` is still installed or
      `markdown.py` is changed to return `str`.
- [ ] **Step 7:** `pixi run ui-check` and `pixi run ui-build` pass. Add a bind
      mount of `console_app/web/dist` to `console-web` in the override so
      `pixi run ui-watch` refreshes the running console. Rebuild, restart, run
      the whole suite. Expected: baseline plus the new tests passing.
- [ ] **Step 8:** Open `http://console.localhost:8000` in a browser. Expected:
      the placeholder renders in Encode Sans on a white page, and the browser
      console shows no content-security-policy violation.
- [ ] **Step 9:** Commit: `feat(console)!: serve a React shell in place of the Jinja pages`.

---

### Task 6: API client, application shell and the simple screens

**Files:**

- Create: `frontend/src/lib/api.ts`, `lib/types.ts`, `lib/format.ts`,
  `lib/use-action.ts`, `src/router.tsx`, `components/app-shell.tsx`,
  `components/page-header.tsx`, `components/code-block.tsx`,
  `components/status-badge.tsx`, `components/confirm-dialog.tsx`,
  `components/type-to-confirm-dialog.tsx`, `components/form-field.tsx`,
  `pages/sign-in.tsx`, `pages/home.tsx`, `pages/not-invited.tsx`,
  `pages/invitation.tsx`, `pages/invitation-result.tsx`, `pages/error.tsx`
- Test: `lib/api.test.ts`, `lib/use-action.test.tsx`, `router.test.tsx`,
  `components/type-to-confirm-dialog.test.tsx`

**Interfaces:**

- Consumes: `/web-api/session`, `/web-api/invites/{token}`.
- Produces:

```ts
// lib/api.ts
export class ApiError extends Error { status: number }
export function get<T>(path: string): Promise<T>            // GET /web-api + path
export function post<T = ActionResult>(path: string, body?: unknown): Promise<T>
export function postForm<T = ActionResult>(path: string, form: FormData): Promise<T>
export function loadSession(): Promise<Session>             // caches; sets the CSRF token
export function currentSession(): SignedIn                  // throws if signed out
// lib/types.ts: one exported type per shape in Task 1, plus
export type ActionResult = { message?: string; goto?: string; key?: { name: string; key: string }; rotated?: boolean }
// lib/use-action.ts
export function useAction(): { run: (call: () => Promise<ActionResult>) => Promise<ActionResult | undefined>; pending: boolean }
// lib/format.ts
export function usd(value: number | string, digits?: 2 | 4): string   // "$12.00", "$0.0031"
export function day(iso: string | null): string                      // "2026-11-12"
export function minute(iso: string): string                          // "2026-11-12 08:15:02"
// components
<CodeBlock value: string copy?: boolean />
<TypeToConfirmDialog title expected: string confirmLabel onConfirm: (typed: string) => Promise<void> />
<ConfirmDialog title description confirmLabel destructive? onConfirm />
```

Behaviour:

- `get`/`post` send `credentials: "same-origin"`; `post` adds `X-CSRF-Token`.
  A non-2xx answer with the error shape throws `ApiError(status, message)`. A
  reply that is not JSON throws
  `ApiError(502, "The console could not complete that. Nothing was changed.")`.
- A 401 from any call other than `loadSession` sets
  `window.location.href = "/?next=" + encodeURIComponent(location.pathname)`.
- `useAction.run`: sets `pending`, ignores a second call while pending, on
  success shows `message` as a toast, then navigates to `goto` or reloads the
  current route's data; on `ApiError` 409/422 returns the error to the caller
  for inline display and otherwise shows it as a toast. Whether the toast is
  shadcn's sonner or an inline alert is decided here by testing it under the
  real CSP in the browser.
- Router: root loader calls `loadSession`. Signed out: the sign-in screen
  (`<form method="post" action="/login">` with a hidden `next` taken from the
  `next` query), plus the notice "That sign-in could not be completed. Please
  start again." when `?signin=failed`. Signed in with no roles: Not invited.
  A participant with exactly one team and no other role: redirect to
  `/teams/{id}`. Otherwise Home. `/invite/:token` and
  `/invite-result/:outcome` render without a session.
- Shell: navigation bar per the design system (purple-900, gold-200 links, 2px
  teal underline on the active link). Admin links: Organizations, Audit log,
  Data protection, and "LiteLLM UI" (external, `rel="noopener"`) when
  `config.litellm_admin_url` is set. The email, and Sign out as
  `<form method="post" action="/logout">` with a hidden `csrf` field.
- Route error boundary: shows `ApiError.message` (403 "You do not have access
  to that.", 404 "That does not exist.", others as given) and "Back to the
  console".
- Copy for every screen is today's template text, word for word.

- [ ] **Step 1: Write the failing tests:**

```ts
// api.test.ts
it("throws ApiError with the server's message", ...)            // 409 {"error":{"status":409,"message":"Taken."}}
it("treats a non-JSON reply as a 502", ...)                     // body "<html>bad gateway"
it("sends the CSRF token on posts and not on gets", ...)
it("goes to sign-in with next when an action answers 401", ...) // location.href === "/?next=%2Fteams%2Fabc"
// use-action.test.tsx
it("sends one request when run twice before the first settles", ...)
it("navigates to goto, else reloads", ...)
// router.test.tsx
it("shows sign-in when signed out and keeps next in the form", ...)
it("sends a lone participant straight to their team", ...)
it("shows the error screen with a way back when the page loader fails", ...)
// type-to-confirm-dialog.test.tsx
it("keeps the confirm button disabled until the text matches exactly", ...)
```

- [ ] **Step 2:** `pixi run ui-check`. Expected: fail.
- [ ] **Step 3:** Add the shadcn components needed so far (button, card, input,
      label, table, badge, dialog, alert, and the toast choice). Implement the
      files above.
- [ ] **Step 4:** `pixi run ui-check`. Expected: pass. In the browser against
      the stack: sign in as alice, see Home, sign out; open an invitation link
      from Mailpit signed out.
- [ ] **Step 5:** Commit: `feat(console): add the application shell and sign-in screens`.

---

### Task 7: Admin screens

**Files:**

- Create: `pages/admin-orgs.tsx`, `pages/audit.tsx`, `pages/dlp.tsx`
- Test: `pages/admin-orgs.test.tsx`, `pages/dlp.test.tsx`

**Interfaces:**

- Consumes: `get`, `post`, `useAction`, shell components (Task 6);
  `GET /web-api/admin/orgs|audit|dlp`, `POST /web-api/admin/orgs`.

Port `admin.html`, `audit.html` and `dlp.html` field for field. The new
organization form keeps the template's constraints (`name` 2 to 80 characters,
`slug` matching `[a-z0-9][a-z0-9-]{1,30}`, ceiling a number at least 0, step
0.01). The data protection screen keeps its three states: not connected, no
events, events.

- [ ] **Step 1: Write the failing tests:**

```ts
it("posts the new organization and follows goto", ...)
it("shows the server's message beside the form on a 422", ...)
it("labels a blocked event 'request refused' and maps other actions through the server's labels", ...)
it("says the console is not connected when enabled is false", ...)
```

- [ ] **Step 2:** `pixi run ui-check`. Expected: fail.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `pixi run ui-check` passes. Browser: create an organization as
      alice; open Audit log and Data protection.
- [ ] **Step 5:** Commit: `feat(console): add the admin screens`.

---

### Task 8: Organization screen

**Files:**

- Create: `pages/org.tsx`
- Test: `pages/org.test.tsx`

**Interfaces:**

- Consumes: `GET /web-api/orgs/{id}` and the organization, lead, model and team
  actions from Task 3.

Port `org.html`. Visibility rules, from the template:

- Admin section (ceiling, suspend or resume, remove): `is_admin`.
- Remove organization: `TypeToConfirmDialog` with `expected = org.slug`; the
  typed text is sent as `confirm_slug`.
- Knowledge link: `is_lead`.
- Lead remove buttons, pending lead invitations and "Invite a lead": `is_admin`.
- Model remove buttons: `is_lead`. "Add a model" and "New team":
  `is_lead && org.status === "active"`.
- The provider API key field is `type="password"`, `autocomplete="off"`, and is
  cleared after a successful post.

- [ ] **Step 1: Write the failing tests:**

```ts
it("shows a lead no admin controls and no lead invitations", ...)
it("shows an admin who is not a lead no add-model or new-team form", ...)
it("hides add-model and new-team when the organization is suspended", ...)
it("sends the typed short name when removing and follows goto to /admin", ...)
it("clears the provider key field after adding a model", ...)
```

- [ ] **Step 2:** `pixi run ui-check`. Expected: fail.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `pixi run ui-check` passes. Browser: as alice invite a lead;
      as the lead add a `mock` model and create a team.
- [ ] **Step 5:** Commit: `feat(console): add the organization screen`.

---

### Task 9: Team screen for leads and admins

**Files:**

- Create: `pages/team-manage.tsx`, and `pages/team-manage/` section components
  if the file passes about 300 lines
- Test: `pages/team-manage.test.tsx`

**Interfaces:**

- Consumes: `GET /web-api/teams/{id}/manage` and the team actions from Task 3;
  `postForm` for invitations.

Port `team_manage.html`. `live = is_lead && team.status === "active" &&
team.org_status === "active"`. Rules from the template:

- Not a lead: the note "You are viewing this team as an SSEC admin. You can
  remove people from it; everything else here is for the organization's lead."
- Budget and model inputs are disabled unless `live`; their save buttons show
  only when `live`.
- Member remove: `live || (is_admin && team.status === "active")`.
- Approve and Reject on a `needs_approval` invitation: always shown. Cancel
  invitation: `live`.
- Invite people (textarea and CSV file, sent with `postForm`): `live`.
- Key Rotate: `live && !key.waiting`. Key Revoke: `live`.
- Archive section: `live`, behind a `ConfirmDialog`.
- Connected services section: shown when there are integrations or `is_admin`.
  Disconnect and "Connect a service": `is_admin` (the form also needs
  `team.status === "active"`).
- Remove team: `is_admin`, `TypeToConfirmDialog` with `expected = team.name`.

- [ ] **Step 1: Write the failing tests:**

```ts
it("gives an admin who is not the lead only the remove-member and remove-team controls", ...)
it("freezes every control on an archived team", ...)
it("sends typed addresses and a CSV file as multipart", ...)
it("offers Approve and Reject for a request that needs approval", ...)
it("never renders a key value, only its hint", ...)
```

- [ ] **Step 2:** `pixi run ui-check`. Expected: fail.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `pixi run ui-check` passes. Browser: as the lead set the
      budget, tick a model, invite two people (one typed, one by CSV).
- [ ] **Step 5:** Commit: `feat(console): add the team screen for leads`.

---

### Task 10: Team screen for participants

**Files:**

- Create: `pages/my-team.tsx`
- Test: `pages/my-team.test.tsx`

**Interfaces:**

- Consumes: `GET /web-api/teams/{id}`, the three `my/keys` actions and
  `my/consent`; `CodeBlock`; `currentSession().config.gateway_url`.

Port `my_team.html`. `live = team.status === "active" && team.org_status ===
"active"`; `agreed = consent?.terms_accepted`. Keys, "How to connect" and usage
show only when `agreed`. "Create key" shows when `live` and the key count is
under `team.key_limit`. A created or rotated key is kept in component state and
shown at the top in a `CodeBlock` with a copy button and the text "Copy it now.
It will not be shown again." (plus "The key it replaces no longer works." after
a rotation). The create and rotate calls use `post` directly, not a router
action, so the key never enters router or history state.

- [ ] **Step 1: Write the failing tests:**

```ts
it("shows the new key once, in a code block, with the copy-now warning", ...)
it("loses the key when the screen is left and opened again", ...)
it("writes the key to no storage", ...)   // localStorage, sessionStorage and history.state stay free of the key string
it("shows no keys section until the terms are accepted", ...)
it("offers 'Get replacement key' for a key a lead rotated", ...)
it("hides Create key at the key limit and on a closed team", ...)
```

- [ ] **Step 2:** `pixi run ui-check`. Expected: fail.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `pixi run ui-check` passes. Browser: as an invited participant
      accept the terms, create a key, copy it, reload and see it gone, then call
      the gateway with it.
- [ ] **Step 5:** Commit: `feat(console): add the team screen for participants`.

---

### Task 11: Knowledge screen

**Files:**

- Create: `pages/knowledge.tsx`, `components/knowledge-graph.tsx`
- Test: `pages/knowledge.test.tsx`

**Interfaces:**

- Consumes: `GET /web-api/orgs/{id}/knowledge?concept=<id>`.

Port `knowledge.html`. The selected concept is the `concept` query parameter,
so links and reloads keep working. `concept.html` and `log_html` are inserted
with `dangerouslySetInnerHTML` inside a container styled for prose; they are
already sanitized by `web/markdown.py`. Clicks on links inside that container
whose `href` starts with `?concept=` are intercepted and handled by the router,
so they do not reload the page. `KnowledgeGraph` draws the SVG from
`graph.nodes`, `graph.lines` and `graph.legend` exactly as the template did
(viewBox from `graph.width` and `graph.height`, radius 8, label 22 below,
arrow marker, `selected` and `faded` states); the six type colours `t0` to `t5`
come from the token palette, in a stylesheet, not inline styles. Each node is a
router link to `?concept=<id>`.

- [ ] **Step 1: Write the failing tests:**

```ts
it("renders the selected concept's HTML and no other concept's text", ...)
it("shows member-written markup as text", ...)   // html "&lt;script&gt;alert(1)&lt;/script&gt;" renders the literal characters, no script element
it("handles a ?concept= link in the text without leaving the page", ...)
it("draws one node per graph node and marks the selected one", ...)
it("explains how to add knowledge when there are no concepts", ...)
```

- [ ] **Step 2:** `pixi run ui-check`. Expected: fail.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `pixi run ui-check` passes. Browser: after
      `tests/test_knowledge.py` has run against the stack, open that
      organization's knowledge as its lead; select a node; follow a link in the
      text.
- [ ] **Step 5:** Commit: `feat(console): add the knowledge screen`.

---

### Task 12: Browser pass, documentation and project memory

**Files:**

- Modify: `README.md`, `tests/env.example` if anything changed
- Modify through `okf` only: root `knowledge/`

- [ ] **Step 1:** Rebuild the image from scratch with the override (no bind
      mount of `dist`), so what is tested is what the `Dockerfile` builds.
- [ ] **Step 2:** In a browser against the stack, with the developer console
      open, walk each role's main flow from the stack README's "Trying the
      console" (admin, lead, participant), plus: an admin viewing a team they
      do not lead, removing a team and an organization, a mismatched-email
      invitation, and sign-out. Record any content-security-policy violation or
      failed request. Fix what is found, each fix with a test.
- [ ] **Step 3:** Check against `DESIGN.md`: button corners, the three font
      families actually loaded from `/assets/`, no teal text on white, focus
      rings visible with the keyboard, headings in order.
- [ ] **Step 4:** Run the whole end-to-end suite and `pixi run ui-check`.
      Expected: the Task 0 baseline plus every test this plan added.
- [ ] **Step 5:** Update `README.md`: the service table ("Public pages" now a
      React application served by `console-web`), the design point about
      scripts (now: only the console's own script runs, under the policy in
      this plan; a key is held in memory only), Getting started (the `ui-*`
      tasks), and the Tests section (front-end tests; the suite drives
      `/web-api/`).
- [ ] **Step 6:** Record in project memory with the `okf-memory` skill: the
      console's pages are a React application; the content security policy and
      why nothing may be added to it; `/web-api/` responses are built field by
      field and why `participant_id` stays on the server; the key is held in
      memory only. Relate it to `decisions/platform-only-scope`.
- [ ] **Step 7:** `pixi run -e llmaven verify` from the repository root. Commit:
      `docs(console): describe the React front end`.
- [ ] **Step 8:** Report to the owner: what passed, what the baseline was, any
      test that still fails and why, and that nothing was changed in the local
      stack beyond test data. Stop the stack only if the owner asks.
