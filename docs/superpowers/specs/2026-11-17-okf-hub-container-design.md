# okf-hub as a container service on the Azure stack

Date: 2026-11-17. Status: draft for the owner's review.

## Intent

The console's knowledge features (each organization's shared OKF bundle, reached
as MCP tools through LiteLLM, and the leads' knowledge page) need a knowledge
hub. The hub the console targets is
[uw-ssec/okf-hub](https://github.com/uw-ssec/okf-hub), which today runs only as
a Cloudflare Worker. The owner wants **one deployment with everything in
Azure**: `llmaven infra deploy` brings up the hub like any other service, with
no second cloud account and no separate Cloudflare deploy to keep in step.

The console already speaks okf-hub's API (`/mcp?bundle=`, `/v1/snapshot`, the
`okf_org` claim, `orgs/oidc-{actor}` bundles, the `knowledge-reader` role). Its
full end-to-end suite passed against okf-hub under `wrangler dev` on 2026-11-17
(305 passed; PR #251), so the hub's behavior is the reference this work must
keep.

## Goals

- A container build of okf-hub that serves the same `/mcp`, `/v1/snapshot` and
  `/healthz` behavior as the Worker, for callers holding Keycloak access tokens,
  with its state in Azure Postgres and Azure Blob Storage.
- That image published from uw-ssec/okf-hub and run by the llmoxie Pulumi
  program as one more Container App, off by default behind a config block.
- The console's knowledge turned on by the same deploy: its `KEYCLOAK_*` and
  `KNOWLEDGE_*` settings, the Keycloak clients and role it relies on, and the
  gateway's `/mcp` route.
- Organizations that already exist when the hub turns on get knowledge too, even
  though their bundles start empty.
- The console's end-to-end suite passes against the container, locally, before
  anything reaches dev.

## Non-goals

- **The Cloudflare version stays as it is.** okf-hub's `main` keeps the Worker
  and its deployment. This work does not touch it.
- **No sign-in other than Keycloak.** The container drops the Worker's GitHub
  OAuth flow for personal MCP clients, its grants page, the static `MCP_TOKEN`
  and the single configured vault (`MCP_VAULT_ID`, `VAULT_KEY_HEX`).
- **No external device-sync API.** The hub REST API that local `okf hub sync`
  devices use (`/api/v1/vaults/...`, `HUB_TOKEN`) is not served. The engine
  still uses it in process (see Design, okf-hub).
- **No migration of existing data.** There is no Azure-hosted knowledge today;
  bundles start empty.
- Bundles shown outside the console, backups beyond what Postgres and Blob
  Storage already give, and a knowledge UI of the hub's own.

## Anti-goals

- A hub that can lose or silently drop a write. The Worker's compare-and-swap
  commit and "never point the head at a commit the hub does not hold" rules
  carry over exactly.
- A token from one organization reaching another organization's bundle, by any
  path (tool argument, `?bundle=`, snapshot).
- New Azure role assignments. The deployer is Contributor only
  (`facts/deployer-is-contributor-no-role-assignments`).

## Constraints

- **okf-hub is private today.** The owner will make the repository public when
  it is ready; its image on `ghcr.io` becomes public then. Container Apps here
  pull only public images (`registries=[]`, `container_apps.py`), so **the dev
  deploy waits until the image is public**. Everything before that is built and
  tested locally.
- Postgres in dev is VNet-only; the hub reaches it like the console does.
  Database URLs use `sslmode=verify-full` as the console's do.
- One identity and one access-policy Key Vault per container, policies set
  inline at creation (`decisions/console-on-azure`,
  `bugs/key-vault-access-policy-replace`).
- The console stays usable with knowledge off. A console that never had the hub
  behaves as today.

## Approaches

Where the hub runs:

| Approach                                                                | Trade-off                                                                                                             | Outcome                                             |
| ----------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------- |
| Pulumi deploys the Worker to Cloudflare (`pulumi-cloudflare`)           | Runs okf-hub exactly as built, but a second cloud account and API token in the deploy                                 | Rejected: the owner wants everything in Azure       |
| The Worker unchanged in a container under workerd, state on Azure Files | Literally "a container", but R2/KV exist only as local simulations there and SQLite on SMB risks locking; one replica | Rejected: untrusted for real data                   |
| A container-native hub                                                  | Fits the stack like every other service                                                                               | **Chosen**; specifically okf-hub, not okf-memory-rs |

How okf-hub carries the container version:

| Approach                                                                  | Trade-off                                                                                             | Outcome                 |
| ------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | ----------------------- |
| One codebase, two entry points behind interfaces                          | One copy of the logic, but a refactor of the Worker and every change checked on both                  | Not chosen              |
| **A container-only copy on a long-lived branch of okf-hub**               | Simple, the Worker on `main` is untouched; the two drift and fixes are carried across by hand         | **Chosen by the owner** |
| The Worker code on Node behind shims that fake Durable Objects, R2 and KV | Smallest change to okf-hub's files, but faking Durable Object guarantees is where data-loss bugs hide | Rejected                |

Where the code lives: in uw-ssec/okf-hub, which publishes an image that llmoxie
pins by digest (as it pins the LiteLLM fork). Copying the source into llmoxie's
`services/` was rejected because llmoxie is public and okf-hub is not (yet).

## Design

### okf-hub: the container branch

A branch of uw-ssec/okf-hub, named by the owner (`container` is the working
name), turns the Worker into a Node service. What changes:

- **Runtime.** A Node HTTP server (Node 22, matching the Worker's
  `nodejs_compat` code) serves `/mcp`, `/v1/snapshot` and `/healthz` and nothing
  else (404). The Worker's `index.ts`, `provider.ts`, `authorize.ts`,
  `grants.ts`, `github.ts`, `session.ts` and `pages.ts`, the
  `@cloudflare/workers-oauth-provider` dependency, the keep-warm alarms
  (`keep-warm.ts`) and `wrangler.jsonc` go.
- **Auth.** Every `/mcp` and `/v1/snapshot` request needs a bearer that
  `resolveCaller` (`oidc.ts`, unchanged) accepts; anything else is 401 with the
  same error shape the Worker's snapshot endpoint returns. The grants a token
  carries become the request's policy exactly as `provider.ts`'s
  `resolveExternalToken` builds it today. OIDC settings are required, not
  optional: the container refuses to start without `OIDC_ISSUER`,
  `OIDC_JWKS_URL`, `OIDC_AUDIENCE`, `OIDC_GRANTS` and `VAULT_MASTER_KEY_HEX`.
  There is no `PUBLIC_URL`; the audience is `OIDC_AUDIENCE` alone.
- **Head pointers** (`vault-head.ts`). A Postgres table per concept, not per
  vault: `vault_head (vault_id primary key, commit_id, updated_at)` and
  `vault_history (seq bigserial, vault_id, commit_id, previous_id, accepted_at)`.
  `commit(expected, next)` is one transaction that reads the head `FOR UPDATE`
  (or inserts the first row), compares, writes the head and appends the history
  row, returning the same `CommitResult`. This is the compare-and-swap guarantee
  the Durable Object gave by running one request at a time.
- **Blobs** (`hub.ts`). Azure Blob Storage, one container, with the same key
  layout (`vaults/<id>/blobs/<sha256>`, and the append-only
  `vaults/<id>/refs/<seq>-<commit>.json` mirror). Uploads keep the SHA-256 check
  before writing; existence checks keep their bounded concurrency.
- **The engine** (`vault-engine.ts`, `engine/runtime.ts`). The Go engine (Wasm,
  built from `engine/FORK_COMMIT` as today) runs in the Node process. It still
  stores everything through the hub API, called in process (`okfHubFetch` to
  `routeHub`): that internal API stays, backed by the two stores above, and is
  never reachable over the network. One engine per process, every call under the
  existing `serialQueue`; a call for a vault other than the loaded one reloads
  it, as the Worker does when an isolate switches vaults. The blob cache and the
  "head moved after a failed sync" reporting carry over.
- **Replicas: one.** The compare-and-swap keeps several replicas from corrupting
  a vault, but it is unverified whether okf's sync retries after a 409 or the
  engine reports "Not saved" to the caller (`vault-engine.ts`). With one
  replica, every call for a vault runs through one engine, as on the Worker.
  Raising the count needs that question answered first. (My call.)
- **MCP transport.** `/mcp` stays stateless, JSON responses, the same tools,
  instructions and bundle rules (`bundleCall`, `nameBundle`, `guardedCall`,
  `policy.ts` unchanged). The Worker builds its handler with `createMcpHandler`
  from the `agents` package; the container uses the MCP SDK's own Streamable
  HTTP transport or anything equivalent, as long as clients see the same
  behavior (including the 406 without
  `Accept: application/json, text/event-stream`).
- **Schema.** The container creates its two tables at startup if missing
  (idempotent). Its database role owns only its own database.
- **Configuration.** Environment variables: the five OIDC settings above,
  `OIDC_ACTOR_CLAIM` (default `okf_org`), `DATABASE_URL`,
  `AZURE_STORAGE_CONNECTION_STRING`, `BLOB_CONTAINER`, `PORT` (default 7878).
- **Image.** A multi-stage Dockerfile (Go stage builds the engine, Node stage
  runs), non-root, read-only root filesystem, `/healthz` healthcheck. A GitHub
  Actions workflow on the branch builds `linux/amd64` and pushes
  `ghcr.io/uw-ssec/okf-hub:<branch>-<sha>`.
- **Tests.** The Worker's unit tests that cover shared logic keep running. New
  tests cover the Postgres compare-and-swap (including two concurrent commits
  from one expected head: exactly one wins) and the blob store. The OIDC
  end-to-end script (`test/mcp-oidc.sh`) runs against the container under docker
  compose with Postgres and Azurite. Tests of removed features go.

### llmoxie: the Pulumi service

- **Config block** `knowledge_hub` in `llmaven-config`, off by default:
  `enabled`, `image` (pinned by digest), CPU and memory. Turning it on requires
  `console.enabled`. No hostname: the hub is internal only, since nothing in
  scope calls it from outside (no personal sign-in, no device sync). Its
  audience is fixed at the internal FQDN because the broker writes that audience
  into each organization's Keycloak client and MCP server URL when the
  organization is created; changing it later would break every existing
  organization. (My call.)
- **Data that outlives the block.** Every bundle's key derives from
  `VAULT_MASTER_KEY_HEX`, so losing it loses every bundle. It is not a
  `pulumi_random` value: the operator generates it once and keeps it in the
  deploy env file (sops-encrypted in llmaven-deploy, like the other deploy
  secrets), and Pulumi copies it into the hub's vault. It survives lost Pulumi
  state and turning the block off. The `okf_hub` database and the Blob container
  are kept when the block is turned off (`retain_on_delete`), as `console_db`
  is; turning it back on needs them imported, documented alongside the console's
  re-enable steps. (My call.)
- **Resources** (a new `resources/knowledge_hub.py`, following `console.py` and
  `console_secrets.py`):
  - its user-assigned identity and access-policy Key Vault holding
    `VAULT_MASTER_KEY_HEX` (from the deploy env, above), the database URL, and
    the Blob connection string;
  - a database `okf_hub` and a login role that owns it, created the way
    `console-db` creates the console's (a manual job run after `up`), with
    CONNECT revoked from `PUBLIC`;
  - a Blob container in the stack's storage account (or its own account if that
    is simpler under the no-role-assignment rule; builder's call);
  - the Container App: internal ingress only, port 7878, the image pinned by
    digest, settings from its vault. The audience is the hub's internal https
    FQDN, which is also the console's `KNOWLEDGE_HUB_URL`.
- **Realm** (`keycloak_realm.py`), when the hub is on:
  - realm role `knowledge-reader`;
  - client `console-provisioner`: service account with `manage-clients` of
    `realm-management`;
  - client `console-knowledge`: service account with `knowledge-reader`, the hub
    as audience, a hardcoded `okf_org` claim `console_reader`. The test that
    asserts these are absent becomes "absent unless the hub is on". Secrets come
    in as `$(env:...)` placeholders like the other clients and land in the
    broker's vault.
- **Console settings**, when the hub is on: the broker gets `KNOWLEDGE_HUB_URL`,
  `KEYCLOAK_ADMIN_URL`, `KEYCLOAK_TOKEN_URL`, the provisioner and knowledge
  client ids and secrets (internal Keycloak FQDN, as the console's other
  server-side Keycloak calls use). With the hub off, none are set and the
  console behaves as today.
- **Knowledge for existing organizations** (console code, `services/console/`,
  so a new console image is published and pinned). Today the broker sets up an
  organization's knowledge (its `okf-org-<short name>` Keycloak client, its
  LiteLLM MCP server, `org.mcp_server_id`, and its teams' access to that server)
  only when the organization is created with the hub on (`broker/app.py`). A new
  broker operation does the same setup for every active or suspended
  organization that has none (`mcp_server_id` null), idempotently: a Keycloak
  client or MCP server that a half-finished earlier run left behind is reused or
  replaced (`litellm.mcp_server_new` already replaces a server of the same
  name), and running it twice changes nothing. It gives each existing team of
  those organizations access to the server with `litellm.team_set_knowledge`, as
  team creation does through `team_new`. Suspended organizations get the client
  and server but their teams stay closed (`team_set_knowledge(team, None)`),
  exactly as suspension leaves them; resuming opens them through the existing
  path. Removed organizations are skipped. Each organization's setup is audited
  like the creation path's. `infra deploy` runs it after `console-init` when the
  hub is on, the same way it runs the console's other post-`up` jobs (a manual
  job invoking the broker operation, waited for, reported with ready-to-run `az`
  commands on failure). The bundles start empty: a new name is an empty vault
  until its first write.
- **Turning the hub off again** is not a clean revert, and this work does not
  build one: organizations keep MCP servers pointing at a hub that is gone, and
  team pages keep listing the knowledge tools. The re-enable and turn-off limits
  are documented with the console's in `.agents/rules/infrastructure.md`. (My
  call.)
- **Gateway `/mcp`.** The LiteLLM gateway host's allowed paths gain `/mcp` (and
  whatever subpaths LiteLLM's MCP gateway needs; builder confirms), so people's
  MCP clients reach their organization's tools with their LiteLLM key.
- **Network.** LiteLLM (which calls the hub for every MCP tool call) and the
  broker reach the hub on its internal FQDN. The hub reaches Keycloak's JWKS on
  the internal Keycloak FQDN, but the token's issuer is the public one, so
  `OIDC_ISSUER` is the public issuer and `OIDC_JWKS_URL` the internal URL.

### Done

1. okf-hub's container branch: unit tests and `test/mcp-oidc.sh` pass against
   the container with Postgres and Azurite.
2. The console's end-to-end suite passes against the container image (305
   passed, as against `wrangler dev`). It runs in the owner's local
   docker-compose stack (`~/Agent-Workspace/litellm-keycloak`) through a compose
   override that swaps in the image, as on 2026-11-17, with the owner's go-ahead
   each time. okf-hub's own compose setup (item 1) is what anyone else can
   rerun. (My call.)
3. llmoxie: `pixi run -e llmaven verify` passes, with tests for the new block,
   the realm additions and the console settings, on and off. The console suite
   gains tests for the backfill: an organization (with teams) created while
   knowledge is off gets its client, MCP server and team access when the
   operation runs; a second run changes nothing; a removed organization is
   skipped.
4. After okf-hub and its image are public: a dev deploy, previewed and approved
   step by step by the owner. On dev, the existing `uw-ssec` organization has
   knowledge after the deploy (backfilled, empty), a member writes a concept
   through `/mcp`, and its lead sees it on the knowledge page.

## Decided by the owner

- Everything in Azure, one deploy (2026-11-17).
- uw-ssec/okf-hub, made container-native; not okf-memory-rs.
- Keycloak tokens only.
- The code lives in uw-ssec/okf-hub, which publishes an image; the owner makes
  the repository public when ready.
- The Cloudflare version stays on `main`; the container version is a copy on a
  branch.
- Organizations that already exist get knowledge when the hub turns on, even if
  their bundles are empty.

## Left to the builder

- The branch name, the Node HTTP framework, and the Postgres and Blob client
  libraries.
- Whether the Blob container shares the stack's storage account.
- Table and index details beyond the compare-and-swap rule.
- How the `okf_hub` database and role are created, as long as it follows the
  console's `console-db` pattern and the no-role-assignment rule.
- Resource sizes for dev.
