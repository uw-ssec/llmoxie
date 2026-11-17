# The console on the Azure stack: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the LLMoxie console (`services/console/`) with
`llmaven infra deploy`, behind an off-by-default `console` block, and split
LiteLLM into a gateway host and an admin host.

**Architecture:** New `resources/console*.py` modules add two user-assigned
identities, two access-policy Key Vaults (one per identity), a small storage
account with an Azure Files share, `console-web` and `console-broker` Container
Apps, and two Container Apps Jobs (`console-db`, `console-init`) that
`infra deploy` runs after `up`, like the realm job. `resources/console_mail.py`
adds Azure Communication Services Email. The console itself gains optional
knowledge, an ACS mail backend and an Azure database setup script. A new
`llmaven infra keycloak-users` command creates invitee accounts from a CSV.

**Tech Stack:** Python 3.12, Pulumi `pulumi-azure-native` 3.x, Pydantic v2,
Typer, pytest with Pulumi mocks; the console's FastAPI/psycopg code and its
Docker image; Traefik file-provider config; Keycloak realm JSON for
keycloak-config-cli.

**Spec:** `docs/superpowers/specs/2026-11-15-console-azure-design.md` (read it
first; this plan argues from it).

## Global Constraints

- Branch `console-azure`, worktree
  `/Users/landungs/Repos/Work/llmoxie-worktrees/console-azure`. Gate:
  `pixi run -e llmaven verify`.
- Before the first edit to any file:
  `pixi run -e llmaven okf search --for-path <file>`; a `governance: hold` hit
  means stop and ask.
- With `console.enabled: false` and no `litellm.admin_hostname`, the edge
  dynamic config, the realm document and the program's resources render
  byte-identically to `origin/console-react-ui`.
- No Azure role assignments anywhere (`azure_native.authorization.*` is never
  created). The deployer is Contributor.
- No new `azure_native.keyvault.AccessPolicy` resources. Console vaults set
  their policies inline on `Vault` creation.
- No secret value in Pulumi exports, logs, the terminal, or committed files.
  Generated values use `pulumi_random.RandomPassword` and are written only as
  Key Vault secrets.
- Container App and Job names ≤ 32 characters (`CONTAINER_APP_NAME_MAX`); Key
  Vault names ≤ 24.
- Images pinned `<name>:<tag>@sha256:<digest>` when the console is enabled
  (`_check_digest`).
- The console's local stack must keep working: `MAIL_BACKEND` defaults to
  `smtp`; knowledge stays on when `KNOWLEDGE_HUB_URL` is set;
  `db/console-db.sql` is not changed.
- Commits: conventional messages,
  `git -c user.email=17802172+lsetiawan@users.noreply.github.com commit`,
  trailer `Assisted-by: claude-code:<model>`, no `Co-Authored-By` (AI_POLICY).
- Never run `llmaven infra deploy` (including `--preview`) or `az` writes. Task
  15 is the owner's, step by step.

## Review Focus

1. **Gateway host path variants** (`/V1/chat/completions`,
   `/v1/chat/completions/`, `/v1/chat%2Fcompletions`, `/ui/`, `/key/list` with a
   bearer from an admin IP) must find no route on the gateway host. Test in
   Task 1.
2. **The database job runs on every deploy**: the second run must not re-apply
   the schema or fail on existing roles, and a changed role password must take.
   Test in Task 5.
3. **Mail before the domain is verified**: an invitation must fail with
   `{"error": "mail_failed"}` (HTTP 502), not a bare 500, and inviting again
   must work once mail does. Test in Task 4.
4. **CSV from a spreadsheet**: a UTF-8 BOM, `Email` capitalised, stray spaces,
   blank lines and duplicate addresses must give one account per distinct
   lower-cased address; a file without an `email` column must create nothing and
   say why. Test in Task 13.
5. **Broker start-up before the jobs finish**: on a first deploy the broker
   starts with no key file and no schema; it must stay up (healthz 200) and
   answer errors per request, not crash-loop. Test in Task 3.

---

### Task 1: LiteLLM gateway host and admin host

**Files:**

- Modify: `src/llmaven/infrastructure/config/schema.py` (`LiteLLMConfig`,
  `_validate_edge`)
- Modify: `src/llmaven/infrastructure/resources/traefik.py`
  (`build_edge_dynamic_config`)
- Modify: `src/llmaven/infrastructure/resources/keycloak.py:218,228` (litellm
  login app URLs)
- Modify: `src/llmaven/infrastructure/resources/keycloak_realm.py:206,213`
  (litellm redirect URIs)
- Modify: `src/llmaven/infrastructure/main.py:565-569,665` (`PROXY_BASE_URL`,
  exports)
- Modify: `src/llmaven/deployment/validate.py:656` (hostname list)
- Test: `tests/infrastructure/test_litellm_admin_host.py`

**Interfaces:**

- Produces: `LiteLLMConfig.admin_hostname: str | None` (validated by
  `_check_hostname`); property `LiteLLMConfig.ui_hostname -> str | None`
  returning `admin_hostname or hostname`. Every later use of "LiteLLM's admin/UI
  host" goes through `ui_hostname`.

- [ ] **Step 1: Write the failing tests** in `test_litellm_admin_host.py`,
      reusing `_config`, `_http`, `_winner` from `test_edge_login_routing.py`
      and `_data` from `test_edge_config.py`. Use `GATEWAY = LITELLM_HOST` and
      `ADMIN = "litellm-admin.example.org"` (listed in `edge.custom_domains`).

```python
def test_unset_admin_hostname_renders_unchanged():  # snapshot vs. config without the field
    assert render_edge_dynamic_config(base, backends) == render_edge_dynamic_config(
        base_with_none, backends
    )


@pytest.mark.parametrize(
    "path", ["/v1/chat/completions", "/v1/models", "/health/liveliness"]
)
def test_gateway_serves_ai_and_health_paths(path):
    assert _winner(http, GATEWAY, path) in {"litellm-public", "litellm-health"}


@pytest.mark.parametrize(
    "path",
    [
        "/ui/",
        "/ui",
        "/key/list",
        "/sso/key/generate",
        "/oauth2/start",
        "/V1/chat/completions",
        "/v1/chat/completions/",
        "/v1/chat%2Fcompletions",
        "/",
    ],
)
@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer sk-x"}, {"Cookie": "_llm_auth=x"}]
)
def test_gateway_has_no_route_for_anything_else(path, headers):
    assert _winner(http, GATEWAY, path, **headers) is None


def test_admin_host_gets_the_login_routes():
    assert _winner(http, ADMIN, "/ui/") == "litellm-admin"
    assert _carries(http, "litellm-admin", "litellm-login")
    assert _winner(http, ADMIN, "/oauth2/callback") == "litellm-oauth2"


def test_admin_hostname_must_be_a_custom_domain(): ...  # ValueError mentions edge.custom_domains
def test_admin_hostname_must_differ_from_other_hosts(): ...  # litellm.hostname, mlflow, keycloak
def test_ui_hostname_falls_back_to_hostname(): ...
def test_realm_and_login_app_use_ui_hostname(): ...  # redirectUris and OAUTH2_PROXY_REDIRECT_URL/WHITELIST_DOMAINS
```

The cookie name comes from `LOGIN_COOKIE["litellm"]`; use it, not a literal.

- [ ] **Step 2: Run**
      `pixi run -e llmaven pytest tests/infrastructure/test_litellm_admin_host.py -q`.
      Expected: FAIL (`admin_hostname` unknown).

- [ ] **Step 3: Implement.** In `build_edge_dynamic_config`, when
      `litellm.admin_hostname` is set: health and public routers stay on
      `Host(litellm.hostname)`; `_add_litellm_login_routes` (or the
      IP-allowlisted `litellm-admin` catch-all when login is off) gets
      `Host(litellm.admin_hostname)`; no catch-all on the gateway host. Unset:
      unchanged code path. `_validate_edge`: `admin_hostname` in
      `edge.custom_domains`, differs from `litellm.hostname`, `mlflow.hostname`,
      `keycloak.hostname`. Replace `litellm.hostname`/`app_config.hostname` with
      `ui_hostname` at the five call sites in Files (the `mlflow` login app
      keeps `mlflow.hostname`; give `MLflowConfig` the same `ui_hostname`
      property returning `hostname` so `create_login_app` stays generic).
      `main.py`: `PROXY_BASE_URL` uses `ui_hostname`; export `litellm_admin_url`
      only when `admin_hostname` is set. `validate.py`: add
      `("litellm.admin_hostname", config.litellm.admin_hostname)` when set.

- [ ] **Step 4: Run** the new tests plus
      `tests/infrastructure/test_edge_*.py tests/infrastructure/test_keycloak_*.py tests/infrastructure/test_login_app.py`.
      Expected: PASS, no existing test changed.

- [ ] **Step 5: Commit**
      `feat(infra): split LiteLLM into a gateway host and an admin host`.

---

### Task 2: The `console` config block

**Files:**

- Modify: `src/llmaven/infrastructure/config/schema.py`
- Modify: `src/llmaven/infrastructure/resources/database.py:131`
  (`RETAINED_DATABASES`)
- Modify: `src/llmaven/deployment/validate.py` (`validate_config`: salt-key
  error; `check_required_providers(..., console_enabled: bool = False)` adds
  `"Microsoft.Communication"`)
- Test: `tests/infrastructure/test_console_config.py`; add
  `PINNED_CONSOLE_IMAGE = "ghcr.io/uw-ssec/llmoxie-console:dev@sha256:" + "c" * 64`
  to `tests/infrastructure/__init__.py`

**Interfaces:**

- Produces, in `schema.py`:
  - `CONSOLE_WEB_APP_SUFFIX = "con-web"`,
    `CONSOLE_BROKER_APP_SUFFIX = "con-broker"`, `CONSOLE_DB = "console_db"`.
  - `console_job_name(project_name: str, environment: str, kind: Literal["db", "init"]) -> str`
    returning `f"{project_name}-con{kind}-{environment}"`.
  - `console_vault_name(project_name: str, environment: str, which: Literal["web", "broker"]) -> str`
    returning `f"kv-{project_name}-{environment}-c{which[0]}"[:24]`.
  - `ConsoleAppSize(BaseModel)`: `cpu: float = 0.25 (ge 0.25)`,
    `memory: str = "0.5Gi"`, `min_replicas: int = 1 (ge 0)`,
    `max_replicas: int = 1 (ge 1)`.
  - `ConsoleMailConfig(BaseModel)`: `domain: str | None` (hostname-checked),
    `sender: str = "console"`, `display_name: str = "LLMoxie console"`,
    `domain_verified: bool = False`.
  - `ConsoleConfig(BaseModel)`: `enabled: bool = False`, `hostname: str | None`,
    `image: str = "ghcr.io/uw-ssec/llmoxie-console:latest"`,
    `admin_subjects: list[str] = []`, `invite_ttl_hours: int = 72 (ge 1)`,
    `mail: ConsoleMailConfig`, `web: ConsoleAppSize` (default `max_replicas=2`),
    `broker: ConsoleAppSize` (default `cpu=0.5, memory="1Gi"`),
    `revision_suffix: str | None`, `refresh_trigger: str | None`.
  - `LLMavenConfig.console: ConsoleConfig`; `_validate_console()` called from
    `model_post_init` after `_validate_keycloak()`.
- `RETAINED_DATABASES = frozenset({"keycloak_db", "console_db"})`.

- [ ] **Step 1: Write the failing tests.** Each invalid case asserts
      `ValueError` whose message names the field to fix:

```python
def test_console_off_by_default_and_renders_nothing():
    assert LLMavenConfig().console.enabled is False


@pytest.mark.parametrize(
    "missing",
    [
        "edge",
        "keycloak",
        "litellm_login",
        "admin_hostname",
        "hostname",
        "admin_subjects",
        "mail_domain",
    ],
)
def test_console_requires(missing): ...
def test_console_image_must_be_pinned(): ...  # ":latest" refused, message cites console.image
def test_console_hostname_must_be_unique_custom_domain(): ...
def test_console_requires_salt_key_and_db_models(
    tmp_path,
): ...  # validate_config raises ValidationError, not a warning
def test_console_requires_communication_provider(
    monkeypatch,
): ...  # check_required_providers(console_enabled=True) lists Microsoft.Communication
def test_console_adds_console_db():
    assert "console_db" in cfg.database.databases


def test_console_names_fit(): ...  # project "llmaven-dev", env "dev": all four names <= 32; vaults <= 24
def test_console_names_too_long_are_refused(): ...  # project "a-very-long-project-name"
def test_console_db_is_retained():
    assert "console_db" in RETAINED_DATABASES
```

- [ ] **Step 2: Run**
      `pixi run -e llmaven pytest tests/infrastructure/test_console_config.py -q`.
      Expected: FAIL.

- [ ] **Step 3: Implement** the models and `_validate_console()`. Requirements
      when enabled: `edge.enabled`, `keycloak.enabled`, `litellm.enabled`,
      `litellm.login.enabled`, `litellm.admin_hostname`; `hostname` set, in
      `edge.custom_domains`, unequal to every other hostname;
      `_check_digest(console.image, "console.image")`; `admin_subjects`
      non-empty; `mail.domain` set. The salt-key and `store_model_in_db` check
      needs LiteLLM's config file, so it lives in `validate_config` (which
      `infra deploy` also runs): where it calls `missing_salt_key` today, raise
      `ValidationError` instead of warning when `console.enabled`, and also
      require `store_model_in_db: true` then. Pass
      `console_enabled=config.console.enabled` to `check_required_providers`.
      Append `CONSOLE_DB` to `database.databases`. Extend `_validate_app_names`
      with both apps, both jobs, and a vault-name length check.

- [ ] **Step 4: Run** the new tests and
      `tests/infrastructure/test_salt_key_warning.py tests/infrastructure/test_keycloak_db_retention.py`.
      Expected: PASS.

- [ ] **Step 5: Commit** `feat(infra): add the console config block`.

---

### Task 3: Console: knowledge optional, and a broker that starts before its jobs

**Files:**

- Modify: `services/console/console_app/broker/keycloak.py`, `knowledge.py`,
  `app.py` (org create/suspend/remove, team create, team view,
  `/orgs/{id}/knowledge`)
- Modify: `services/console/console_app/broker/litellm.py` (`_KEY_FILE` read
  lazily)
- Modify: `services/console/frontend/src/…` (the org knowledge page and team MCP
  block; find with `grep -rn knowledge frontend/src`)
- Test: `services/console/tests/test_knowledge_off.py`, front-end test beside
  the knowledge page's existing test

**Interfaces:**

- Produces: `keycloak.ENABLED: bool` (true iff `KNOWLEDGE_HUB_URL` is set and
  non-empty); when false, every `KEYCLOAK_*` and `KNOWLEDGE_*` variable is
  optional and module import succeeds. Broker `GET /orgs/{org_id}/knowledge`
  answers
  `404 {"error": "knowledge_off", "message": "Knowledge isn't set up on this console."}`;
  the team view's `knowledge_tools` is `null` when the org has no
  `mcp_server_id`.
- `litellm.admin_key() -> str` reads `LITELLM_ADMIN_KEY_FILE` on each call
  (raise `LiteLLMError("admin_key", 503)` if missing), instead of at import.

- [ ] **Step 1: Write the failing tests.** These need no stack: set env in a
      fixture before importing `console_app.broker.app`, and stub `db`,
      `litellm` and `keycloak` calls with `monkeypatch`.

```python
def test_broker_imports_without_hub_or_keycloak_settings(broker_env_without_hub):
    import console_app.broker.app


def test_org_create_skips_knowledge(app_client, calls):
    assert "org_client_create" not in calls and "mcp_server_new" not in calls


def test_team_create_gets_no_mcp_server(app_client, calls):
    assert calls["team_new"].mcp_server_id is None


def test_knowledge_route_says_off(app_client):
    r = ...
    assert r.status_code == 404 and r.json()["error"] == "knowledge_off"


def test_org_remove_skips_client_delete(app_client, calls):
    assert "org_client_delete" not in calls


def test_healthz_without_key_file_or_schema(broker_env_without_hub):
    assert client.get("/healthz").status_code == 200
```

Front end: the knowledge page renders "Knowledge isn't set up on this console."
for `knowledge_off`, and the team page hides the MCP block when
`knowledge_tools` is null.

- [ ] **Step 2: Run**
      `cd services/console && pixi run test-image && docker run --rm llmoxie-console-tests:dev pytest -q tests/test_knowledge_off.py`
      (with the colima workaround from project memory if the build can't pull).
      Expected: FAIL at import (`KeyError: 'KEYCLOAK_ADMIN_URL'`).

- [ ] **Step 3: Implement.** Read optional settings with `os.environ.get`; guard
      each knowledge call site in `app.py` (lines ~322–328, 381–383, 589, 882)
      with `keycloak.ENABLED`. Front end per Interfaces.

- [ ] **Step 4: Run** the new tests, `pixi run ui-check`, and
      `pytest -q tests/test_shapes.py`. Then the full end-to-end suite against
      the local stack with the hub on (project memory
      `console-local-test-stack`: an override compose file pointing the console
      services' `build.context` here; ask the owner before starting that stack).
      Expected: all PASS.

- [ ] **Step 5: Commit** `feat(console): run without the knowledge hub`.

---

### Task 4: Console: ACS mail backend

**Files:**

- Create: `services/console/console_app/broker/mail.py`
- Modify: `services/console/console_app/broker/app.py:14,32-34,122-142` (use
  `mail`), exception handler
- Modify: `services/console/requirements.txt` (add `azure-communication-email`,
  pinned with hashes the way the file already pins)
- Test: `services/console/tests/test_mail.py`

**Interfaces:**

- Produces in `mail.py`: `class MailError(Exception)` (message never includes
  the address or body); `send(to: str, subject: str, body: str) -> None`.
  Backend from `MAIL_BACKEND` (`smtp` default, `acs`); `smtp` uses `SMTP_HOST`,
  `SMTP_PORT`, `MAIL_FROM` as today; `acs` uses
  `EmailClient.from_connection_string(ACS_CONNECTION_STRING)`, sender
  `MAIL_FROM`, `begin_send(...).result()` with a 30 s timeout. Any backend
  failure raises `MailError`.
- `app.py`: `send_invite` and `send_notice` call `mail.send`;
  `@app.exception_handler(mail.MailError)` returns
  `502 {"error": "mail_failed", "message": "The email could not be sent. Try again later."}`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_smtp_is_the_default(monkeypatch, fake_smtp):
    mail.send("a@x.org", "s", "b")
    assert fake_smtp.sent[0]["To"] == "a@x.org"


def test_acs_sends_with_connection_string(
    monkeypatch, fake_email_client
): ...  # sender == MAIL_FROM, recipients [{"address": "a@x.org"}]
def test_acs_failure_raises_mail_error_without_address(
    monkeypatch,
): ...  # "a@x.org" not in str(err)
def test_invite_mail_failure_is_502_mail_failed(app_client): ...
def test_reinvite_after_mail_failure_works(
    app_client,
): ...  # second invite revokes the first, sends once
```

- [ ] **Step 2: Run** in the test image as in Task 3. Expected: FAIL
      (`No module named console_app.broker.mail`).
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Run** the new tests and the end-to-end suite (Mailpit path).
      Expected: PASS.
- [ ] **Step 5: Commit**
      `feat(console): send mail through Azure Communication Services`.

---

### Task 5: Console: database setup for Azure

**Files:**

- Create: `services/console/db_setup.py` (next to `init_admin_key.py`)
- Modify: `services/console/Dockerfile` (copy `db_setup.py` and
  `db/console-db.sql` into `/app`)
- Test: `services/console/tests/test_db_setup.py`

**Interfaces:**

- Produces: `python db_setup.py`, reading `PGHOST`, `PGUSER` (admin login),
  `PGPASSWORD`, `CONSOLE_WEB_DB_PASSWORD`, `CONSOLE_BROKER_DB_PASSWORD`,
  `CONSOLE_OTHER_DATABASES` (comma-separated), `CONSOLE_SCHEMA_FILE` (default
  `db/console-db.sql`). Functions: `schema_statements(sql: str) -> str`
  returning the text after the `\c console_db` line; `main() -> int`.
- Behaviour, as the admin login, `sslmode=require`:
  1. On `postgres`: create `console_web` and `console_broker` LOGIN if missing;
     `ALTER ROLE … PASSWORD` both every run (passwords as parameters via
     `psycopg.sql`, never interpolated or printed).
  2. `REVOKE ALL ON DATABASE console_db FROM PUBLIC`;
     `GRANT CONNECT … TO console_web, console_broker`.
  3. For each name in `CONSOLE_OTHER_DATABASES`:
     `GRANT CONNECT … TO <admin login>` then `REVOKE CONNECT … FROM PUBLIC`.
  4. On `console_db`: if `to_regclass('public.person')` is null, run
     `schema_statements(...)` in one transaction; else print "schema already in
     place".

- [ ] **Step 1: Write the failing tests.**
      `test_schema_statements_drop_psql_meta_commands` runs without a database.
      The rest use a throwaway `postgres:16` container (fixture skips if Docker
      is unavailable) where an `azadmin` role (LOGIN CREATEROLE CREATEDB,
      **not** superuser) owns `console_db`, `litellm_db` and `mlflow_db`,
      mimicking Azure:

```python
def test_runs_twice_without_error(pg):
    assert main() == 0 and main() == 0


def test_second_run_does_not_reapply_schema(
    pg,
): ...  # a row inserted between runs survives
def test_changed_password_takes(pg): ...  # connect as console_web with the new password
def test_console_roles_cannot_connect_elsewhere(
    pg,
): ...  # console_web -> litellm_db raises InsufficientPrivilege
def test_admin_keeps_connect_on_other_databases(pg): ...
def test_broker_sees_rls(
    pg,
): ...  # console_broker without org setting sees 0 rows of person
```

- [ ] **Step 2: Run** `pytest -q services/console/tests/test_db_setup.py` inside
      the test image with `--network` to the container (or the host's
      `pixi run -e llmaven pytest` if psycopg is present there). Expected: FAIL.
- [ ] **Step 3: Implement.** If the schema text fails under a non-superuser (an
      `ALTER … OWNER` or extension), adapt only `db_setup.py` around it and
      record what and why in the module docstring; `console-db.sql` stays
      unchanged.
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit**
      `feat(console): set up the console database on a server without a superuser`.

---

### Task 6: Publish the console image from CI

**Files:**

- Modify: `.github/workflows/build-services.yml` (matrix entry)
- Test: `tests/infrastructure/test_console_image.py`

**Interfaces:** Produces image `ghcr.io/uw-ssec/llmoxie-console` with the
workflow's existing tag scheme.

- [ ] **Step 1: Write the failing test:** load the workflow YAML and assert a
      matrix entry with `name: console`, `context: ./services/console`,
      `file: ./services/console/Dockerfile`, `target: app`,
      `platforms: linux/amd64`; the build step's `file:` reads
      `matrix.service.file`, and its `target:` reads `matrix.service.target`.
      The other four entries gain
      `file: ./docker/dockerfiles/<their dockerfile>` and build exactly as
      before (assert their resolved file paths are unchanged).
- [ ] **Step 2: Run** it. Expected: FAIL.
- [ ] **Step 3: Implement** (matrix `file` and `target` keys; existing entries
      keep their behaviour). Run `zizmor` via pre-commit.
- [ ] **Step 4: Run** the test and
      `pixi run -e llmaven pre-commit run --files .github/workflows/build-services.yml`.
      Expected: PASS.
- [ ] **Step 5: Commit** `ci: build and publish the console image`.

---

### Task 7: The console's Keycloak client

**Files:**

- Modify: `src/llmaven/infrastructure/resources/keycloak_realm.py` (client),
  `src/llmaven/infrastructure/resources/keycloak.py` (`_job_secret_refs`,
  `CLIENT_SECRET_ENV`, `_CLIENT_SECRET_KEY`)
- Modify: `src/llmaven/infrastructure/resources/secrets_manager.py`
  (`KEYCLOAK_SECRET_NAMES["client_console"] = "console-oidc-client-secret"`)
- Test: `tests/infrastructure/test_console_realm.py`

**Interfaces:**

- Produces: realm client `console` when `config.console.enabled`:
  `_web_client("console", f"https://{console.hostname}/auth/callback", "LLMoxie console")`
  plus
  `attributes["post.logout.redirect.uris"] = f"https://{console.hostname}/*"`
  and a mapper
  `{"name": "console-broker-audience", "protocolMapper": "oidc-audience-mapper", "config": {"included.custom.audience": "console-broker", "access.token.claim": "true", "id.token.claim": "false"}}`
  (custom audience, as the proof of concept: `included.client.audience` would
  need a `console-broker` client). Secret placeholder
  `$(env:KC_CLIENT_SECRET_CONSOLE)`; the realm job maps it to Key Vault secret
  `console-oidc-client-secret` in the **main** vault.

- [ ] **Step 1: Write the failing tests:** client present only when enabled;
      exact redirect URI, PKCE S256, audience mapper config; `_job_secret_refs`
      has `KC_CLIENT_SECRET_CONSOLE`; realm document unchanged when the console
      is off (compare with a config lacking the block); no `console-provisioner`
      or `console-knowledge` client.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** with
      `tests/infrastructure/test_keycloak_realm.py tests/infrastructure/test_keycloak_secrets.py`.
      Expected: PASS.
- [ ] **Step 5: Commit** `feat(infra): add the console's client to the realm`.

---

### Task 8: Console identities, vaults and secrets

**Files:**

- Create: `src/llmaven/infrastructure/resources/console_secrets.py`
- Test: `tests/infrastructure/test_console_secrets.py`

**Interfaces:**

- Produces:

```python
@dataclass
class ConsoleSecrets:
    web_identity: azure_native.managedidentity.UserAssignedIdentity
    broker_identity: azure_native.managedidentity.UserAssignedIdentity
    web_vault: azure_native.keyvault.Vault
    broker_vault: azure_native.keyvault.Vault
    web_secret_names: dict[str, str]  # env var -> secret name in web_vault
    broker_secret_names: dict[str, str]  # env var -> secret name in broker_vault
    job_secret_names: dict[
        str, str
    ]  # env var -> secret name in the main vault (console-db job)
    resources: list[pulumi.Resource]  # for depends_on


def create_console_secrets(
    config: LLMavenConfig,
    resource_group_name: pulumi.Input[str],
    location: str,
    tenant_id: str,
    deployer_object_id: str | None,
    main_vault: azure_native.keyvault.Vault,
    postgres_host: pulumi.Input[str],
    mail_connection_string: pulumi.Input[str],
) -> ConsoleSecrets: ...
```

- Secrets and vaults exactly as the spec's table in §6. Env var names: web
  `CONSOLE_WEB_DATABASE_URL`, `CONSOLE_BROKER_CALLER_SECRET`,
  `OIDC_CLIENT_SECRET`; broker `CONSOLE_BROKER_DATABASE_URL`,
  `CONSOLE_BROKER_CALLER_SECRET`, `ACS_CONNECTION_STRING`; job
  `CONSOLE_WEB_DB_PASSWORD`, `CONSOLE_BROKER_DB_PASSWORD`. Database URLs:
  `postgresql://<role>:<password>@<host>:5432/console_db?sslmode=require`. The
  client secret goes to the main vault as `console-oidc-client-secret` (Task 7's
  name) and to the web vault.
- Each console vault: `enable_rbac_authorization=False`, the main vault's
  soft-delete and purge settings (`config.security.key_vault`),
  `access_policies` = [its identity: secrets `get`, `list`] + [deployer: the
  main vault's deployer policy, when `deployer_object_id`].

- [ ] **Step 1: Write the failing tests** (Pulumi mocks, as
      `test_keycloak_secrets.py` does):

```python
def test_each_vault_has_exactly_its_identity_and_the_deployer(): ...
def test_web_vault_holds_only_web_secrets():
    assert names(web) == {
        "console-oidc-client-secret",
        "console-broker-caller-secret",
        "console-web-db-url",
    }


def test_broker_vault_holds_only_broker_secrets(): ...
def test_no_role_assignments_or_access_policy_resources():
    assert not any(
        t.startswith("azure-native:authorization")
        or t == "azure-native:keyvault:AccessPolicy"
        for t in types
    )


def test_no_secret_value_is_exported(): ...
def test_vault_names_match_console_vault_name(): ...
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** Reuse `create_user_assigned_managed_identity`
      (helpers.py) and the deployer-policy construction from `create_key_vault`
      (extract a helper
      `deployer_access_policy(tenant_id, object_id) -> AccessPolicyEntryArgs` in
      `key_vault.py` and use it in both places; the main vault's rendered args
      must not change, which `test_recovery_resource_updates.py`/existing tests
      catch).
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit**
      `feat(infra): give each console app its own identity and vault`.

---

### Task 9: Console mail resources

**Files:**

- Create: `src/llmaven/infrastructure/resources/console_mail.py`
- Test: `tests/infrastructure/test_console_mail.py`

**Interfaces:**

```python
@dataclass
class ConsoleMail:
    communication_service: azure_native.communication.CommunicationService
    domain: azure_native.communication.Domain
    sender_address: str  # f"{mail.sender}@{mail.domain}"
    connection_string: pulumi.Output[str]  # secret output


def create_console_mail(
    config: LLMavenConfig, resource_group_name: pulumi.Input[str], tags: dict[str, str]
) -> ConsoleMail: ...
```

- `EmailService` (location `global`, `data_location="United States"`); `Domain`
  named `mail.domain`, `domain_management=CUSTOMER_MANAGED`,
  `user_engagement_tracking=DISABLED`; `SenderUsername` `mail.sender` with
  `display_name`; `CommunicationService` (location `global`, same data location)
  with `linked_domains=[domain.id]` **only** when `mail.domain_verified`.
  `connection_string` from
  `list_communication_service_keys_output(...).primary_connection_string`,
  wrapped with `pulumi.Output.secret`.
- Exports `console_mail_verification_records` (the domain's
  `verification_records`: names, types and values of the DNS records, which are
  not secret).

- [ ] **Step 1: Write the failing tests:** domain unlinked when
      `domain_verified` is false and linked when true; tracking disabled; sender
      address; connection string is a secret output; the verification-records
      export exists.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit**
      `feat(infra): send console mail through Azure Communication Services`.

---

### Task 10: Console apps, file share and jobs

**Files:**

- Create: `src/llmaven/infrastructure/resources/console.py`
- Test: `tests/infrastructure/test_console_apps.py`

**Interfaces:**

- Consumes: `ConsoleSecrets` (Task 8), `ConsoleMail.sender_address` (Task 9),
  names from Task 2, `create_container_app_with_key_vault_secrets`
  (container_apps.py:119).
- Produces:

```python
@dataclass
class ConsoleApps:
    web: azure_native.app.ContainerApp
    broker: azure_native.app.ContainerApp
    db_job: azure_native.app.Job
    init_job: azure_native.app.Job


def create_console(
    config: LLMavenConfig,
    resource_group_name: pulumi.Input[str],
    location: str,
    container_env: azure_native.app.ManagedEnvironment,
    main_vault: azure_native.keyvault.Vault,
    shared_identity_id: pulumi.Input[str],
    secrets: ConsoleSecrets,
    sender_address: str,
    litellm_fqdn: pulumi.Input[str],
    keycloak_fqdn: pulumi.Input[str],
    postgres_host: pulumi.Input[str],
    tags: dict[str, str],
    opts: pulumi.ResourceOptions | None = None,
) -> ConsoleApps: ...
```

- Storage: a StorageV2 `Standard_LRS` account (no HNS,
  `allow_blob_public_access=False`, `minimum_tls_version=TLS1_2`), a file share
  `console-run` (quota 1 GiB), and two `ManagedEnvironmentsStorage` entries over
  that share: `console-run-rw` (`access_mode` ReadWrite, mounted only by
  `console-init`) and `console-run-ro` (`access_mode` ReadOnly, mounted only by
  the broker). Container Apps sets read-only per environment storage, not per
  mount.
- `console-web`: port 8200, command
  `uvicorn console_app.web.app:app --host 0.0.0.0 --port 8200`, internal
  ingress, health `/healthz`, identity `secrets.web_identity`, vault
  `secrets.web_vault`, env per spec §4
  (`OIDC_ISSUER=https://<kc host>/realms/<realm>`, `OIDC_CLIENT_ID=console`,
  `OIDC_AUTH_URL`/`OIDC_LOGOUT_URL` public, `OIDC_TOKEN_URL`/`OIDC_JWKS_URL` on
  `https://<keycloak_fqdn>/realms/<realm>/protocol/openid-connect/{token,certs}`,
  `CONSOLE_PUBLIC_URL`, `GATEWAY_PUBLIC_URL=https://<litellm.hostname>`,
  `LITELLM_ADMIN_URL=https://<litellm.ui_hostname>`,
  `CONSOLE_BROKER_URL=https://<broker fqdn>`).
- `console-broker`: port 8100, internal ingress, health `/healthz`, identity and
  vault the broker's, `LITELLM_URL=https://<litellm_fqdn>`,
  `LITELLM_ADMIN_KEY_FILE=/run/console/admin-key`, `MAIL_BACKEND=acs`,
  `MAIL_FROM=<sender_address>`, `CONSOLE_ADMIN_SUBJECTS` joined by commas,
  `CONSOLE_INVITE_TTL_HOURS`, `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_JWKS_URL`,
  `CONSOLE_PUBLIC_URL`; share mounted read-only at `/run/console`.
- `console-db` job (manual trigger, shared identity, main vault):
  `python db_setup.py`, `PGHOST`, `PGUSER=config.database.admin_login`,
  `PGPASSWORD` from the main vault's Postgres admin password secret, the two
  role passwords from `secrets.job_secret_names`, `CONSOLE_OTHER_DATABASES` =
  every other name in `database.databases`.
- `console-init` job (manual, shared identity, main vault):
  `python init_admin_key.py`, `LITELLM_URL`, `LITELLM_MASTER_KEY` from
  `litellm-master-key`, `LITELLM_ADMIN_KEY_FILE=/run/console/admin-key`, share
  mounted read-write.
- Both apps use `config.console.revision_suffix`/`refresh_trigger` like
  Keycloak.

- [ ] **Step 1: Write the failing tests** (mocks): `console-web` has no
      `LITELLM_MASTER_KEY`, `LITELLM_ADMIN_KEY_FILE`, `ACS_CONNECTION_STRING`,
      volume, or reference to the broker's vault or the main vault, and uses
      only `web_identity`; the broker mounts `console-run-ro` and `console-init`
      mounts `console-run-rw`; both apps internal; job commands and env names as
      above; no master key anywhere except `console-init`; names equal Task 2's
      helpers.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** If `create_container_app_with_key_vault_secrets`
      assumes one vault/identity per call, pass the console vault's URI and
      identity; don't widen its signature beyond what the two apps need.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit**
      `feat(infra): run console-web, console-broker and their jobs`.

---

### Task 11: Wire the console into the program and the edge

**Files:**

- Modify: `src/llmaven/infrastructure/main.py` (after Keycloak 8.4 and LiteLLM
  8.2, before the edge 8.3), exports
- Modify: `src/llmaven/infrastructure/resources/traefik.py` (`console` router
  and service)
- Test: `tests/infrastructure/test_console_program.py`; extend
  `tests/infrastructure/test_litellm_admin_host.py` with the console host

**Interfaces:**

- Consumes: Tasks 7–10.
- Produces: backends key `"console"` → web app FQDN; router `console`:
  `Host(console.hostname)`, middlewares `["client-rate-limit"]`, service
  `console`. Exports `console_url`, `console_db_job`, `console_init_job`,
  `console_mail_verification_records`.

- [ ] **Step 1: Write the failing tests** (whole program under mocks, as
      `test_keycloak_program.py`): with the console off, the resource list, edge
      config and realm equal the same run on the `_keycloak()` config without
      the block (byte-identical edge YAML); with it on, the four apps/jobs
      exist, the edge routes the console host only to `console`, with no
      ForwardAuth, and every console path on the gateway host still has no
      route; exports present.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** Pass `mail.connection_string` into
      `create_console_secrets`; `depends_on` the secrets' resources for the apps
      and jobs.
- [ ] **Step 4: Run** the new tests and the whole `tests/infrastructure/`.
      Expected: PASS.
- [ ] **Step 5: Commit** `feat(infra): deploy the console behind the edge`.

---

### Task 12: Run the console jobs after `up`

**Files:**

- Modify: `src/llmaven/deployment/deploy.py:426-512,711-724`
- Test: `tests/infrastructure/test_console_jobs_run.py` (mirror
  `test_realm_job_run.py`)

**Interfaces:**

- Produces:
  `run_job(config, job_name: str, purpose: str, timeout_s: int = 600, poll_s: int = 10) -> None`
  (the current body of `run_realm_job`, with `purpose` in every message, e.g.
  "Applying the Keycloak realm", "Setting up the console database", "Creating
  the broker's LiteLLM key"); `run_realm_job` becomes a thin wrapper so its
  tests keep passing. After the realm job, when `config.console.enabled`:
  `run_job` for `console_db_job`, then `console_init_job`, each failure raising
  `DeploymentError("Infrastructure deployed, but <purpose> did not finish: …")`
  with the ready-to-run `az` hints.

- [ ] **Step 1: Write the failing tests:** order realm → db → init; a db failure
      stops before init and names the console database; a missing export is an
      error; console off runs only the realm job.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** with `tests/infrastructure/test_realm_job_run.py`.
      Expected: PASS.
- [ ] **Step 5: Commit**
      `feat(deploy): set up the console database and broker key after deploying`.

---

### Task 13: `llmaven infra keycloak-users`

**Files:**

- Create: `src/llmaven/deployment/keycloak_users.py`
- Modify: `src/llmaven/cli.py` (command)
- Test: `tests/infrastructure/test_keycloak_users.py`

**Interfaces:**

```python
def read_emails(
    csv_path: Path,
) -> list[
    str
]: ...  # utf-8-sig, case-insensitive "email" header, strip, lower, dedupe in order; ValueError if no column


@dataclass
class UserPlan:
    create: list[str]
    existing: list[str]


def plan_users(
    client: httpx.Client, realm: str, emails: list[str]
) -> UserPlan: ...  # GET /admin/realms/{realm}/users?email=<e>&exact=true
def create_users(
    client: httpx.Client, realm: str, emails: list[str], out: Path
) -> int: ...
```

- `create_users` writes `out` with
  `os.open(..., O_CREAT | O_EXCL | O_WRONLY, 0o600)` (refuse to overwrite),
  header `email,temporary_password`, and POSTs each user
  `{"username": e, "email": e, "emailVerified": True, "enabled": True, "requiredActions": ["UPDATE_PASSWORD"], "credentials": [{"type": "password", "value": <secrets.token_urlsafe(18)>, "temporary": True}]}`;
  a 409 counts as existing.
- CLI:
  `llmaven infra keycloak-users -c <config> --csv <file> --out <file> [--dry-run] [--yes]`.
  Base URL `https://<keycloak.hostname>`; admin token from
  `/realms/master/protocol/openid-connect/token` (`client_id=admin-cli`, user
  `admin`, password from
  `az keyvault secret show --vault-name <key_vault_name stack output> --name keycloak-admin-password`
  through `_run_az_command`). Prints counts and the `--out` path, never a
  password; asks to confirm unless `--yes`.

- [ ] **Step 1: Write the failing tests** with `httpx.MockTransport`:

```python
def test_bom_mixed_case_spaces_blank_and_duplicates(tmp_path):
    assert read_emails(f) == ["alice@x.org", "bob@x.org"]


def test_missing_email_column_is_refused(tmp_path): ...
def test_existing_users_are_skipped(): ...
def test_created_user_payload(): ...  # emailVerified, UPDATE_PASSWORD, temporary
def test_out_file_is_0600_and_not_overwritten(tmp_path): ...
def test_cli_never_prints_a_password(tmp_path, capsys): ...
def test_dry_run_creates_nothing(): ...
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit**
      `feat(cli): create invitee Keycloak accounts from a CSV`.

---

### Task 14: Docs and project memory

**Files:**

- Modify: `.agents/rules/infrastructure.md` (a "The console" section: config,
  the two LiteLLM hosts, vaults without role assignments, mail domain
  verification and `domain_verified`, provider registration, `keycloak-users`,
  rollout, rollback incl. Key Vault soft-delete on re-enable, what's unverified)
- Modify: `services/console/README.md` (optional hub; `MAIL_BACKEND`,
  `ACS_CONNECTION_STRING`; `db_setup.py`)
- Modify: `README.md` if it lists stack hosts
- Project memory via `okf` only: create `decisions/console-on-azure` (the five
  choices of the spec's Approaches, plus invitee accounts by CSV); create
  `facts/deployer-is-contributor-no-role-assignments`; update
  `decisions/keycloak-identity-provider` (console client) and
  `bugs/key-vault-access-policy-replace` (inline policies on separate vaults);
  `okf relate` them; `code_refs` to the new modules.

- [ ] **Step 1:** Write the docs.
- [ ] **Step 2: Run** `pixi run -e llmaven okf validate --strict --drift` and
      `pixi run -e llmaven verify`. Expected: clean, all tests pass.
- [ ] **Step 3: Commit** `docs: record how the console runs on Azure`.

---

### Task 15: Dev rollout (owner-approved, not for subagents)

Every live step waits for the owner's explicit go-ahead; the agent runs only
previews and read-only checks unless told otherwise.

- [ ] Owner: `az provider register --namespace Microsoft.Communication`.
- [ ] Push the branch; run `build-services` for `console`; pin `console.image`
      by tag and digest.
- [ ] Owner: Cloudflare CNAME + `asuid` TXT for `dev.litellm.uwssec.org` and
      `dev.console.uwssec.org`; hostname add/bind on the Traefik app; add both
      to `edge.custom_domains` in `llmaven-deploy/azure/dev/llmaven-config.yaml`
      on a new llmaven-deploy branch.
- [ ] Config: `litellm.admin_hostname`, the `console` block (`admin_subjects`:
      the owner's `llmoxie` user id), `domain_verified: false`.
      `infra validate`.
- [ ] Preview; summarise creates/updates/deletes; owner approves; deploy in the
      background.
- [ ] Owner: the mail domain's records (from
      `console_mail_verification_records`) in Cloudflare;
      `az communication email domain initiate-verification`; once verified,
      `domain_verified: true`, preview, approve, deploy.
- [ ] `llmaven infra keycloak-users` for a test lead and participant (owner runs
      it or approves it).
- [ ] The spec's "Done on dev" list, items 1–7, with evidence for each.
- [ ] Update `LITELLM_BASE_URL` in dev's env file to the admin host (for
      `infra extract`), re-encrypt per project memory, commit to the
      llmaven-deploy branch, open its PR when asked.
