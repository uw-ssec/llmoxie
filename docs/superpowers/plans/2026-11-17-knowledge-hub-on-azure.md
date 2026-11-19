# Knowledge Hub on the Azure Stack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** An off-by-default `knowledge_hub` block that makes
`llmaven infra deploy` run okf-hub's container on Azure Container Apps and turn
on the console's knowledge, including for organizations that already exist.

**Architecture:** A new `resources/knowledge_hub.py` creates the hub's identity,
vault, secrets, Blob container and internal Container App, following
`console.py` and `console_secrets.py`. The realm gains the `knowledge-reader`
role and the `console-provisioner` and `console-knowledge` clients; the broker
gains its `KEYCLOAK_*`/`KNOWLEDGE_*` settings; the edge's gateway host gains
`/mcp`. A new console job backfills knowledge for organizations made while the
hub was off.

**Tech Stack:** Python 3.12, Pulumi (`pulumi-azure-native`), pydantic, pytest;
the console's FastAPI broker; Keycloak realm import.

**Spec:** `docs/superpowers/specs/2026-11-17-okf-hub-container-design.md`
(section "llmoxie: the Pulumi service").

**Depends on:** the okf-hub container image
(`docs/superpowers/plans/2026-11-17-okf-hub-container.md`) only for Task B9.
Tasks B1 to B8 build and test without it.

## Global Constraints

- `knowledge_hub.enabled` defaults to `false`; with it off, every rendered
  resource, realm document and app setting is exactly what it is today.
- It requires `console.enabled` and `keycloak.enabled`; its `image` must be
  digest-pinned (`_check_digest`) when enabled.
- Hub URL = the hub Container App's internal https FQDN, computed as
  `https://<container_app_name(project, environment, "okf-hub")>.internal.<environment default domain>`.
  It is the hub's `OIDC_AUDIENCE`, the console's `KNOWLEDGE_HUB_URL`, and the
  audience in `console-knowledge` and every `okf-org-*` client. It never changes
  for a stack.
- Hub settings: `OIDC_ISSUER=https://<keycloak.hostname>/realms/<realm>` (public
  issuer),
  `OIDC_JWKS_URL=https://<keycloak internal FQDN>/realms/<realm>/protocol/openid-connect/certs`,
  `OIDC_GRANTS=[{"bundle":"orgs/oidc-{actor}","access":"write"},{"role":"knowledge-reader","bundle":"orgs/*","access":"read"}]`,
  `BLOB_CONTAINER=okf-hub`, `PORT=7878`; secrets `VAULT_MASTER_KEY_HEX`,
  `DATABASE_URL`, `AZURE_STORAGE_CONNECTION_STRING` from the hub's own vault.
- `VAULT_MASTER_KEY_HEX` comes from the deploy env as
  `LLMAVEN_SECRETS_OKF_HUB_MASTER_KEY` (64 hex). Pulumi never generates it.
- The `okf_hub` database and the `okf-hub` Blob container use
  `retain_on_delete=True`.
- One replica (`min_replicas = max_replicas = 1`), internal ingress only, port
  7878, health path `/healthz`.
- No Azure role assignments anywhere; vault access policies inline at creation.
- Database URLs end `?sslmode=verify-full&sslrootcert=system`.

## Review Focus

- **Hub on, console off (or Keycloak off):** config validation must refuse it
  with a message naming the missing block. Test in B1.
- **Master key missing or malformed in the env file:** `infra validate` and the
  deploy must stop before `up`, naming `LLMAVEN_SECRETS_OKF_HUB_MASTER_KEY`,
  rather than deploying a hub that cannot start. Test in B3.
- **A half-finished backfill** (it created an org's Keycloak client, then
  LiteLLM failed): the next run must finish that org and not fail on the
  leftover client. Test in B7.
- **A removed organization** in the backfill: skipped, no client, no server.
  Test in B7.
- **Turning the hub off after it was on:** the realm, broker settings and
  gateway paths go back to today's, while the database and Blob container stay.
  Test in B4.

---

### Task B1: The `knowledge_hub` config block

**Files:**

- Modify: `src/llmaven/infrastructure/config/schema.py`
- Test: `tests/infrastructure/test_knowledge_hub_config.py`

**Interfaces:**

- Produces in `schema.py`: `KNOWLEDGE_HUB_APP_SUFFIX = "okf-hub"`,
  `KNOWLEDGE_HUB_DB = "okf_hub"`, `KNOWLEDGE_HUB_PORT = 7878`,
  `KNOWLEDGE_HUB_MASTER_KEY_ENV = "LLMAVEN_SECRETS_OKF_HUB_MASTER_KEY"`,
  `knowledge_hub_vault_name(project_name: str, environment: str) -> str`
  (`f"kv-{project_name}-{environment}-kh"[:24]`),
  `class KnowledgeHubConfig(BaseModel)` with `enabled: bool = False`,
  `image: str = "ghcr.io/uw-ssec/okf-hub:latest"`, `cpu: float = 0.5`,
  `memory: str = "1Gi"`; `LLMavenConfig.knowledge_hub: KnowledgeHubConfig`;
  `console_job_name`'s `kind` widened to `Literal["db", "init", "know"]`;
  `STACK_CLIENT_IDS` gains `"console-provisioner"` and `"console-knowledge"`.

- [ ] **Step 1: Write the failing tests:**
  - `the hub is off by default`:
    `LLMavenConfig(...minimal...).knowledge_hub.enabled is False`.
  - `on without the console is refused`:
    `knowledge_hub.enabled=True, console.enabled=False` raises `ValidationError`
    mentioning `console.enabled`; same for `keycloak.enabled`.
  - `on with a moving tag is refused`: message mentions `knowledge_hub.image`
    and `sha256`.
  - `the vault name fits`:
    `len(knowledge_hub_vault_name("llmaven", "staging")) <= 24` and it starts
    `kv-llmaven-staging-`.
  - `the job name fits`:
    `len(console_job_name("llmaven", "staging", "know")) <= CONTAINER_APP_NAME_MAX`.
- [ ] **Step 2:**
      `pixi run -e llmaven pytest tests/infrastructure/test_knowledge_hub_config.py -q`.
      Expected: FAIL.
- [ ] **Step 3:** Implement; the cross-block check is a
      `model_validator(mode="after")` on `LLMavenConfig` beside the console's.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(infra): add the knowledge_hub config block`.

### Task B2: Realm additions

**Files:**

- Modify: `src/llmaven/infrastructure/resources/keycloak_realm.py`,
  `src/llmaven/infrastructure/resources/keycloak.py` (`_job_secret_refs`, realm
  job env)
- Test: `tests/infrastructure/test_knowledge_hub_realm.py`; update
  `tests/infrastructure/test_console_realm.py` where it asserts these are absent

**Interfaces:**

- Produces:
  `CLIENT_SECRET_ENV["console-provisioner"] = "KC_CLIENT_SECRET_CONSOLE_PROVISIONER"`,
  `CLIENT_SECRET_ENV["console-knowledge"] = "KC_CLIENT_SECRET_CONSOLE_KNOWLEDGE"`,
  `KNOWLEDGE_HUB_URL_ENV = "KC_KNOWLEDGE_HUB_URL"` (the realm job's plain env
  var holding the hub URL), and `KNOWLEDGE_READER_ROLE = "knowledge-reader"`,
  `KNOWLEDGE_READER_ORG = "console_reader"`.
- Consumes (B3): the main-vault secret names for the two client secrets
  (`ConsoleSecrets.provisioner_secret_name`, `knowledge_secret_name`). B2's
  tests stub them; B3 creates them.

With `knowledge_hub.enabled`, `build_realm_document` adds, matching the
definitions the console suite passed against:

- realm role `knowledge-reader`;
- client `console-provisioner`: confidential, service account only (no standard
  flow, no direct grants), secret `_secret("console-provisioner")`; user
  `service-account-console-provisioner` with
  `clientRoles: {"realm-management": ["manage-clients"]}`;
- client `console-knowledge`: same shape, secret `_secret("console-knowledge")`,
  mappers `knowledge-hub-audience` (`oidc-audience-mapper`,
  `included.custom.audience` = `$(env:KC_KNOWLEDGE_HUB_URL)`) and `organization`
  (`oidc-hardcoded-claim-mapper`, `claim.name` `okf_org`, `claim.value`
  `console_reader`, access token only); user `service-account-console-knowledge`
  with `realmRoles: ["knowledge-reader"]`.

The realm job's env gets `KC_KNOWLEDGE_HUB_URL` (plain value, the hub URL) and
secret refs for both client secrets when the hub is on.

- [ ] **Step 1: Write the failing tests:**
  - `hub off: the realm is unchanged`: the rendered document equals today's for
    a console-on config (snapshot or explicit `clientId` list).
  - `hub on: role, clients and service accounts`: the role exists; both clients
    exist with `serviceAccountsEnabled: True`, `standardFlowEnabled: False`; the
    provisioner's user has `manage-clients` of `realm-management`; the knowledge
    user has realm role `knowledge-reader`; the audience mapper's value is
    `$(env:KC_KNOWLEDGE_HUB_URL)`; the claim mapper sets `okf_org` =
    `console_reader`.
  - `hub on: the realm job gets both secrets and the hub URL`:
    `_job_secret_refs(config)` has both `KC_CLIENT_SECRET_CONSOLE_*` keys.
  - `realm.overrides cannot redefine them`: an override with
    `clientId: console-knowledge` is refused, as for the other stack clients.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run, plus `tests/infrastructure/test_keycloak_realm.py` and
      `test_console_realm.py`. Expected: PASS.
- [ ] **Step 5:** Commit:
      `feat(infra): add the knowledge clients and role to the realm`.

### Task B3: Hub secrets, database and Blob container

**Files:**

- Create: `src/llmaven/infrastructure/resources/knowledge_hub.py`
- Modify: `src/llmaven/infrastructure/resources/console_secrets.py` (the two
  client secrets), `services/console/db_setup.py` (the `okf_hub` role),
  `src/llmaven/infrastructure/resources/console.py` (db job env),
  `src/llmaven/cli.py` (`infra validate`)
- Test: `tests/infrastructure/test_knowledge_hub_secrets.py`,
  `services/console/tests/test_db_setup.py` (extend)

**Interfaces:**

- Produces in `knowledge_hub.py`:
  `master_key_from_env(env: Mapping[str, str]) -> str` (raises `ValueError`
  naming `LLMAVEN_SECRETS_OKF_HUB_MASTER_KEY` when missing or not 64 lowercase
  hex); `@dataclass class KnowledgeHubSecrets` with `identity`, `vault`,
  `secret_names: dict[str, str]` (env var → secret name in the hub vault:
  `VAULT_MASTER_KEY_HEX`, `DATABASE_URL`, `AZURE_STORAGE_CONNECTION_STRING`),
  `db_password: pulumi.Output[str]`, `resources: list[pulumi.Resource]`;
  `create_knowledge_hub_secrets(config, resource_group_name, location, tenant_id, deployer_object_id, postgres_host, storage_account_name, master_key) -> KnowledgeHubSecrets`;
  `create_knowledge_hub_storage(config, resource_group_name, storage_account_name, tags) -> azure_native.storage.BlobContainer`
  (`okf-hub`, `retain_on_delete=True`).
- `ConsoleSecrets` gains `provisioner_secret_name` and `knowledge_secret_name`
  (main and broker vault copies, random via `_password`), present only when the
  hub is on.
- `db_setup.py`: with `OKF_HUB_DB_PASSWORD` set, create login role `okf_hub` (or
  reset its password), make it owner of database `okf_hub`, revoke CONNECT on
  `okf_hub` from PUBLIC. `okf_hub` is left out of `CONSOLE_OTHER_DATABASES`.

The database itself is added to the ARM-created list in `main.py` (B4) with
`retain_on_delete=True`. The storage connection string comes from
`azure_native.storage.list_storage_account_keys_output` on the console's storage
account (`console_storage_account_name(...)`), as a secret Output.

- [ ] **Step 1: Write the failing tests:**
  - `master_key_from_env`: valid 64 hex returns it; missing, 63 chars, and
    uppercase/non-hex each raise with the variable's name.
  - `infra validate names a missing master key`: with the hub on and the
    variable absent from the env file, `llmaven infra validate` exits non-zero
    and prints `LLMAVEN_SECRETS_OKF_HUB_MASTER_KEY` (follow the existing
    validate tests' CliRunner pattern).
  - Pulumi mocks (the pattern in `test_console_secrets.py`): the hub vault is
    named `knowledge_hub_vault_name(...)`, has exactly the hub identity and the
    deployer in its policies, and holds the three secrets; the database URL
    names role `okf_hub`, database `okf_hub` and ends
    `?sslmode=verify-full&sslrootcert=system`; the Blob container is `okf-hub`
    with `retain_on_delete`.
  - `db_setup` (extend its Docker-backed tests): with `OKF_HUB_DB_PASSWORD`,
    role `okf_hub` can connect to `okf_hub` and create a table; a role other
    than `okf_hub` cannot connect; running twice is harmless.
- [ ] **Step 2:** Run both test files. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit:
      `feat(infra): create the knowledge hub's secrets, database role and Blob container`.

### Task B4: The hub Container App and the program wiring

**Files:**

- Modify: `src/llmaven/infrastructure/resources/knowledge_hub.py`,
  `src/llmaven/infrastructure/main.py`
- Test: `tests/infrastructure/test_knowledge_hub_app.py`,
  `tests/infrastructure/test_knowledge_hub_program.py`

**Interfaces:**

- Consumes: B1 names, B3 secrets and storage.
- Produces:
  `hub_url(container_env: azure_native.app.ManagedEnvironment, project: str, environment: str) -> pulumi.Output[str]`;
  `create_knowledge_hub_app(config, resource_group_name, location, container_env, secrets: KnowledgeHubSecrets, keycloak_fqdn, tags, opts) -> azure_native.app.ContainerApp`;
  stack exports `knowledge_hub_url`.

`main.py`, with `knowledge_hub.enabled`: read the master key with
`master_key_from_env(os.environ)` before creating anything; add
`KNOWLEDGE_HUB_DB` to the databases created (retained); compute `hub_url` right
after the Container Apps environment so the realm job (B2) and the broker (B5)
can use it; create the hub's secrets, Blob container and app after the console
(it needs the console's storage account).

- [ ] **Step 1: Write the failing tests:**
  - `hub_url`: for a mocked environment with default domain
    `x.westus2.azurecontainerapps.io`, project `llmaven`, environment `dev` →
    `https://llmaven-dev-okf-hub-dev.internal.x.westus2.azurecontainerapps.io`
    (use `container_app_name` to build the name, so the test pins the suffix
    rule).
  - App (mocks): internal ingress, target port 7878, health path `/healthz`,
    `min_replicas == max_replicas == 1`, image is `config.knowledge_hub.image`,
    runs as the hub identity, plain env `OIDC_ISSUER`, `OIDC_JWKS_URL`,
    `OIDC_AUDIENCE` (= `hub_url`), `OIDC_GRANTS` (exact JSON from Global
    Constraints), `BLOB_CONTAINER=okf-hub`, `PORT=7878`, and secret refs for the
    three secrets only.
  - Program (the pattern in `test_console_program.py`): hub off → no hub
    resources, `knowledge_hub_url` not exported, database list unchanged; hub on
    → all of them, and `okf_hub` is in the databases with `retain_on_delete`.
  - `turning the hub off keeps its data`: the database and Blob container
    resources carry `retain_on_delete=True` (assert on the resource options the
    mocks record).
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run, plus
      `pixi run -e llmaven pytest tests/infrastructure -q`. Expected: PASS.
- [ ] **Step 5:** Commit:
      `feat(infra): run the knowledge hub as an internal Container App`.

### Task B5: The console's knowledge settings

**Files:**

- Modify: `src/llmaven/infrastructure/resources/console.py`,
  `src/llmaven/infrastructure/main.py`
- Test: `tests/infrastructure/test_console_apps.py` (extend)

**Interfaces:**

- Consumes: `hub_url` (B4), the client secret names (B3).
- `create_console` gains `knowledge_hub_url: pulumi.Input[str] | None = None`.

With a hub URL, the broker's env adds `KNOWLEDGE_HUB_URL` (the hub URL),
`KEYCLOAK_ADMIN_URL` (`https://<keycloak internal FQDN>/admin/realms/<realm>`),
`KEYCLOAK_TOKEN_URL`
(`https://<keycloak internal FQDN>/realms/<realm>/protocol/openid-connect/token`),
`KEYCLOAK_PROVISIONER_CLIENT_ID=console-provisioner`,
`KNOWLEDGE_READER_CLIENT_ID=console-knowledge`, and secret refs
`KEYCLOAK_PROVISIONER_CLIENT_SECRET` and `KNOWLEDGE_READER_CLIENT_SECRET` from
the broker vault. `console-web` is unchanged.

- [ ] **Step 1: Write the failing tests:** broker env without a hub URL has no
      `KEYCLOAK_*` or `KNOWLEDGE_*` names (today's behavior); with one, it has
      exactly the seven above with those values, and the two secrets come from
      the broker vault, never the web vault.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit:
      `feat(infra): give the console broker its knowledge settings`.

### Task B6: `/mcp` on the gateway host

**Files:**

- Modify: `src/llmaven/infrastructure/resources/traefik.py`
  (`build_edge_dynamic_config`)
- Test: `tests/infrastructure/test_edge_routing.py` (extend)

**Interfaces:**

- Produces: `gateway_public_paths(config: LLMavenConfig) -> list[str]` in
  `traefik.py`: the configured public paths, plus `"/mcp"` and `"/mcp/"` when
  `knowledge_hub.enabled`.

- [ ] **Step 1: Write the failing tests:** hub off → the gateway router's rule
      has no `/mcp`; hub on → it matches `Path(`/mcp`)` and `Path(`/mcp/`)` and
      still nothing under `/mcp/` beyond that (the exact-path rule; the
      console's `tests/test_gateway.py` list of refused paths is the reference).
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit:
      `feat(infra): route /mcp on the gateway when the knowledge hub is on`.

### Task B7: Backfill knowledge for existing organizations

**Files:**

- Create: `services/console/console_app/broker/knowledge_backfill.py`,
  `services/console/knowledge_backfill.py`,
  `services/console/tests/test_knowledge_backfill.py`
- Modify: `src/llmaven/infrastructure/resources/console.py` (the `know` job),
  `src/llmaven/infrastructure/main.py` (export `console_knowledge_job`),
  `src/llmaven/deployment/deploy.py` (`CONSOLE_JOBS`),
  `src/llmaven/infrastructure/resources/console_secrets.py` (main-vault copy of
  the broker DB URL)
- Test: `tests/infrastructure/test_console_jobs_run.py` (extend),
  `tests/infrastructure/test_console_apps.py` (extend)

**Interfaces:**

- Produces in `knowledge_backfill.py` (broker package):
  `backfill() -> list[str]`, returning the slugs it set up. It uses the broker's
  own modules (`db`, `keycloak`, `litellm`, `audit` from `app.py` with
  `s=None`), so it needs the broker's settings.
- `services/console/knowledge_backfill.py`: the job's script; prints one line
  per slug and `backfilled N organizations`; exits non-zero on any failure,
  after finishing the organizations it can.
- Job `know` (`console_job_name(..., "know")`): the console image,
  `python knowledge_backfill.py`, the read-only share (`RO_STORAGE`) for the
  LiteLLM admin key, the broker's knowledge env from B5, and secret refs from
  the main vault for `CONSOLE_BROKER_DATABASE_URL` and the two client secrets.
- `deploy.py`: when `knowledge_hub.enabled`, `CONSOLE_JOBS` runs
  `console_knowledge_job` third, purpose
  `Setting up knowledge for existing organizations`, container `console-know`.

Per organization with `status <> 'removed' AND mcp_server_id IS NULL`:
`keycloak.org_client_create(slug)` (it already replaces a leftover client),
`litellm.mcp_server_new(slug, f"{keycloak.HUB_URL}/mcp?bundle={keycloak.bundle(slug)}", keycloak.TOKEN_URL, keycloak.client_id(slug), secret)`
(it already replaces a server of the same name), `UPDATE org SET mcp_server_id`,
then for each active team
`litellm.team_set_knowledge(team_id, None if org status is 'suspended' else server_id)`,
then
`audit(None, "org.knowledge", "ok", org_id=..., target=slug, backfill=True)`.
One organization's failure is audited `"error"` and does not stop the others.

- [ ] **Step 1: Write the failing tests** in
      `services/console/tests/test_knowledge_backfill.py` (end-to-end against
      the local stack like the rest of the suite). To make an org "made without
      knowledge", create it through the API, then delete its MCP server and
      Keycloak client and set `mcp_server_id` to NULL as the superuser. Run the
      backfill as the job does:
      `subprocess.run([sys.executable, "knowledge_backfill.py"], env=...)` from
      the console directory, with the broker's settings built from the suite's
      own (`LITELLM_URL`, `CONSOLE_BROKER_DATABASE_URL` = `BROKER_DATABASE_URL`,
      `KNOWLEDGE_HUB_URL`, the stack's Keycloak admin and token URLs and
      provisioner credentials, and `LITELLM_ADMIN_KEY_FILE` pointing at a temp
      file holding `LITELLM_MASTER_KEY`). The broker modules read their settings
      at import, so a subprocess keeps them out of the test process.
  - `an org made without knowledge gets it`: after `backfill()`, `mcp_server_id`
    is set, Keycloak has `okf-org-<slug>`, LiteLLM lists its server, and a
    member key of its team can call `<tools>-okf_search`.
  - `a suspended org gets the server but its teams stay closed`: the member key
    lists no knowledge tools; after resume, it does.
  - `a removed org is skipped`: no client, no server, not in the returned slugs.
  - `a second run changes nothing`: returns `[]`; server ids unchanged.
  - `a half-finished run is finished`: leave only the Keycloak client behind (no
    server, `mcp_server_id` NULL); `backfill()` sets the org up and returns its
    slug.
  - In `tests/infrastructure`: the `know` job exists only with the hub on,
    mounts the read-only share, runs `knowledge_backfill.py`, and takes its
    secrets from the main vault; `deploy` runs it after `console-init` and
    reports
    `Infrastructure deployed, but setting up knowledge for existing organizations did not finish: ...`
    on failure.
- [ ] **Step 2:** Run (console suite against the owner's stack, with the owner's
      go-ahead; `pixi run -e llmaven pytest tests/infrastructure -q` for the
      rest). Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit:
      `feat(console): set up knowledge for organizations made before the hub`.

### Task B8: Operator docs and project memory

**Files:**

- Modify: `.agents/rules/infrastructure.md` (new section "The knowledge hub"),
  `services/console/README.md` ("Without the hub" and the requirements table),
  `llmaven-config*.example` files if the console block is shown there
- Knowledge: `knowledge/decisions/` through the `okf-memory` skill

- [ ] **Step 1:** In `infrastructure.md`: turning it on (generate the key once
      with `openssl rand -hex 32` into `LLMAVEN_SECRETS_OKF_HUB_MASTER_KEY` in
      the sops env file; it can never change while bundles exist; pin the image
      digest), what the deploy runs (`console-know` after `console-init`),
      turning it off (orgs keep MCP servers pointing at the missing hub; the
      database and Blob container stay and must be imported to turn it back on),
      and "Unverified until dev" items (the internal FQDN as audience, the hub
      reaching Keycloak's JWKS internally, the Blob connection string from
      listKeys).
- [ ] **Step 2:** Record the decision with `pixi run -e llmaven okf create` (the
      `okf-memory` skill): `decisions/knowledge-hub-on-azure`, linking
      `decisions/console-on-azure`, with the owner's choices from the spec's
      "Decided by the owner".
- [ ] **Step 3:** `pixi run -e llmaven verify`. Expected: pass, including
      `okf validate`.
- [ ] **Step 4:** Commit: `docs(infra): document the knowledge hub`.

### Task B9: Acceptance (owner-gated)

Not code. Each step needs the owner's go-ahead.

- [ ] **Step 1 (local):** With the okf-hub image from the container plan's Task
      7, swap it into the owner's stack (`~/Agent-Workspace/litellm-keycloak`)
      with a compose override, and run the console suite including
      `test_knowledge_backfill.py`. Expected: everything passes (305+ passed).
- [ ] **Step 2 (after okf-hub and its image are public):** In llmaven-deploy's
      dev config, set `knowledge_hub.enabled: true` and the digest-pinned image;
      add `LLMAVEN_SECRETS_OKF_HUB_MASTER_KEY` to the sops env file. Run
      `llmaven infra deploy ... --preview`, summarize creates/updates for the
      owner, and deploy only on their explicit go-ahead.
- [ ] **Step 3 (dev):** The existing `uw-ssec` organization has `mcp_server_id`
      set (backfilled); a member writes a concept through
      `https://dev.llm.uwssec.org/mcp`; its lead sees it on the knowledge page.
