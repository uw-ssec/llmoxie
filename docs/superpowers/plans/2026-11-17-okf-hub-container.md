# okf-hub Container Branch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** A container-only copy of uw-ssec/okf-hub, on a long-lived branch, that
serves `/mcp`, `/v1/snapshot` and `/healthz` to Keycloak-token callers with its
state in Postgres and Azure Blob Storage, and publishes an image to
`ghcr.io/uw-ssec/okf-hub`.

**Architecture:** Keep every module that is plain logic (`oidc.ts`,
`bundles.ts`, `policy*.ts`, `guarded-call.ts`, `mcp-schema.ts`,
`tool-presentation.ts`, `rpc-summary.ts`, `serial.ts`, the Go/Wasm engine).
Replace the two Durable Objects with a Postgres head store and an in-process
engine host, R2 with an Azure Blob store, and the Worker entry and its OAuth
provider with a Node HTTP server whose only auth is `resolveCaller`. The hub
REST API stays as an in-process function the engine calls; it is never routed
from the network.

**Tech Stack:** Node 22, TypeScript, vitest, `pg`, `@azure/storage-blob`, the
MCP SDK already in `package.json`, Go 1.26 (engine build only), Docker, GitHub
Actions.

**Spec:** `docs/superpowers/specs/2026-11-17-okf-hub-container-design.md` in
uw-ssec/llmoxie (branch `docs/okf-hub-container-design`). Read its "okf-hub: the
container branch" section before starting.

**Where it runs:** the okf-hub checkout at `~/Repos/Work/okf-hub`, on a new
branch `container` from `main` (d3a6c99). `main` is never changed.

## Global Constraints

- Serve exactly `/mcp`, `/v1/snapshot`, `/healthz`; every other path is 404,
  including `/api/v1/...`.
- Required settings, refuse to start without them: `OIDC_ISSUER`,
  `OIDC_JWKS_URL`, `OIDC_AUDIENCE`, `OIDC_GRANTS`, `VAULT_MASTER_KEY_HEX` (64
  hex), `DATABASE_URL`, `AZURE_STORAGE_CONNECTION_STRING`. Optional:
  `OIDC_ACTOR_CLAIM` (default `okf_org`), `BLOB_CONTAINER` (default `okf-hub`),
  `PORT` (default `7878`).
- No `PUBLIC_URL`, `MCP_TOKEN`, `HUB_TOKEN`, `MCP_VAULT_ID`, `VAULT_KEY_HEX`,
  GitHub OAuth or KV.
- Blob keys keep the Worker's layout: `vaults/<id>/blobs/<sha256>` and
  `vaults/<id>/refs/<seq zero-padded to 12>-<commit>.json`.
- Commit rules carry over exactly: 400 `commit blob not uploaded` when the
  commit's blob is absent; 409 `{error: "head_mismatch", current_head}` on a
  stale expected head.
- One engine per process; every engine use goes through the existing
  `engineExclusive` queue.
- `/mcp` keeps the Worker's client-visible behavior: 406 without
  `Accept: application/json, text/event-stream`, the same tools, instructions,
  bundle rules and error texts.
- Image: non-root, read-only root filesystem works, `/healthz` healthcheck,
  `linux/amd64`, tag `ghcr.io/uw-ssec/okf-hub:container-<short sha>`.

## Review Focus

- **The Go engine exits** (a fatal error `recover()` can't catch): the process
  must exit non-zero so Container Apps restarts it, instead of every later call
  hanging. Test in Task 5.
- **Postgres is down or restarts:** `/healthz` must fail while the database is
  unreachable and recover by itself after. Test in Task 6.
- **Calls for two vaults at once:** a call for vault B arriving while vault A's
  call runs must wait, then reload B; it must never run against A's loaded
  files. Test in Task 5.
- **A token for an organization whose Keycloak client was deleted:** still valid
  until expiry, as on the Worker; nothing to build, but the e2e in Task 7 must
  show a token with the wrong audience or issuer gets 401.
- **Two writers racing on one vault** (two replicas, or a retried request):
  exactly one commit wins. Test in Task 2.

---

### Task 1: Branch, Node tooling and configuration

**Files:**

- Create: `src/config.ts`, `test/config.test.ts`, `tsconfig.json` (replace),
  `vitest.config.ts` if needed
- Modify: `package.json`

**Interfaces:**

- Produces:
  `type HubConfig = { oidc: OidcConfig; masterKeyHex: string; databaseUrl: string; blobConnectionString: string; blobContainer: string; port: number }`
  and `loadConfig(env: Record<string, string | undefined>): HubConfig` in
  `src/config.ts`. `OidcConfig` is `oidc.ts`'s; build it with the existing
  `oidcConfig(env)` and throw if it returns null.

- [ ] **Step 1:** `git switch -c container main` in `~/Repos/Work/okf-hub`.
- [ ] **Step 2: Write the failing tests** in `test/config.test.ts`:
  - `loads a complete environment`: all required vars set → `port === 7878`,
    `blobContainer === "okf-hub"`, `oidc.actorClaim === "okf_org"`.
  - `names each missing setting`: for each of the seven required vars, deleting
    it makes `loadConfig` throw an error whose message contains that var's name.
  - `rejects a master key that is not 64 hex`: `"abc"` and 64 non-hex chars both
    throw, message contains `VAULT_MASTER_KEY_HEX`.
- [ ] **Step 3:** Run `npx vitest run test/config.test.ts`. Expected: FAIL
      (module not found).
- [ ] **Step 4:** Implement `loadConfig`. In `package.json`, add `pg`,
      `@azure/storage-blob` (and `@types/pg`), add scripts `build` (`tsc -p .`
      to `dist/`), `start` (`node dist/main.js`), keep `test`. Make
      `tsconfig.json` target Node (`"module": "nodenext"`, `"types": ["node"]`,
      `outDir: "dist"`, `noEmit` off). Leave the Worker files in place for now;
      they leave the build in Task 6.
- [ ] **Step 5:** Run `npx vitest run test/config.test.ts`. Expected: PASS.
- [ ] **Step 6:** Commit:
      `feat(container): load the hub's settings from the environment`.

### Task 2: Postgres head store

**Files:**

- Create: `src/stores.ts`, `src/pg-heads.ts`, `test/pg-heads.test.ts`,
  `compose.test.yml`

**Interfaces:**

- Consumes: `HeadState`, `CommitResult` (move these two types from
  `src/vault-head.ts` into `src/stores.ts`).
- Produces in `src/stores.ts`:
  `interface HeadStore { getHead(vaultId: string): Promise<HeadState>; commit(vaultId: string, expected: string, next: string): Promise<CommitResult> }`
  and
  `interface BlobStore { has(key: string): Promise<boolean>; get(key: string): Promise<Uint8Array | null>; put(key: string, data: Uint8Array, contentType: string): Promise<void> }`
  and `type Stores = { heads: HeadStore; blobs: BlobStore }`.
- Produces in `src/pg-heads.ts`: `class PgHeadStore implements HeadStore` with
  `constructor(pool: pg.Pool)`, `migrate(): Promise<void>` (idempotent),
  `history(vaultId: string, limit?: number)`, `ping(): Promise<void>`.

- [ ] **Step 1:** `compose.test.yml` with `postgres:17` (port 55432, password
      `test`) and `mcr.microsoft.com/azure-storage/azurite` (blob port 10000).
      Tests read `TEST_DATABASE_URL` and `TEST_BLOB_CONNECTION_STRING`; a
      `test:integration` script sets both for the compose services. Integration
      test files fail loudly (not skip) when the variable is missing.
- [ ] **Step 2: Write the failing tests** in `test/pg-heads.test.ts` (fresh
      schema per test run, random vault ids `v_<32 hex>`):
  - `an unknown vault has an empty head`: `getHead` →
    `{ head_commit: "", updated_at: "" }`.
  - `the first commit from "" is accepted`: `commit(v, "", A)` →
    `ok: true, head: A, previous: "", seq: 1`; `getHead(v).head_commit === A`;
    `updated_at` matches `/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/`.
  - `a stale expected head is refused`: after A, `commit(v, "", B)` →
    `{ ok: false, current_head: A }`, head still A.
  - `exactly one of two racing commits wins`:
    `Promise.all([commit(v, A, B), commit(v, A, C)])` → one `ok: true`, one
    `{ ok: false }` whose `current_head` is the winner; history has 2 rows.
  - `vaults are independent`: commits on two vaults each get `seq` counting only
    their own history.
  - `migrate twice is harmless`.
- [ ] **Step 3:** `docker compose -f compose.test.yml up -d` then
      `npm run test:integration -- test/pg-heads.test.ts`. Expected: FAIL.
- [ ] **Step 4:** Implement. Tables per the spec:
      `vault_head (vault_id text primary key, commit_id text not null, updated_at text not null)`,
      `vault_history (seq bigserial, vault_id text not null, commit_id text not null, previous_id text not null, accepted_at text not null)`
      with an index on `(vault_id, seq)`. `seq` returned to callers is the
      per-vault count (`SELECT count(*)` inside the transaction, or a per-vault
      counter column), not the global bigserial. `commit` is one transaction:
      `SELECT ... FOR UPDATE` on the head row; for a missing row, insert with
      `ON CONFLICT DO NOTHING` and re-check, so two first commits cannot both
      win. Timestamps second-precision RFC 3339 as `vault-head.ts` makes them.
- [ ] **Step 5:** Run the tests. Expected: PASS.
- [ ] **Step 6:** Commit:
      `feat(container): keep vault heads in Postgres with compare-and-swap`.

### Task 3: Azure Blob store

**Files:**

- Create: `src/azure-blobs.ts`, `test/azure-blobs.test.ts`

**Interfaces:**

- Produces: `class AzureBlobStore implements BlobStore` with
  `constructor(connectionString: string, container: string)`,
  `ensureContainer(): Promise<void>`, `ping(): Promise<void>`.

- [ ] **Step 1: Write the failing tests** (against Azurite):
  - `put then get returns the same bytes`; `has` true after put.
  - `a missing key`: `get` → `null`, `has` → `false`.
  - `ensureContainer twice is harmless`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement with `@azure/storage-blob`
      (`BlockBlobClient.uploadData` with `blobHTTPHeaders.blobContentType`,
      `exists`, `downloadToBuffer`; map 404 to `null`).
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(container): store blobs in Azure Blob Storage`.

### Task 4: The in-process hub API on the stores

**Files:**

- Modify: `src/hub.ts`
- Create: `test/hub.test.ts`

**Interfaces:**

- Consumes: `Stores` (Task 2).
- Produces: `routeHub(request: Request, stores: Stores): Promise<Response>` —
  same routes, bodies, status codes and validation as today, minus the bearer
  check (it is never reachable from the network). `R2_CONCURRENCY` becomes the
  blob-check concurrency.

- [ ] **Step 1: Write the failing tests** with in-memory fakes of
      `HeadStore`/`BlobStore` (a `Map`, and a head store with the same
      compare-and-swap semantics):
  - `PUT a blob whose hash does not match` → 400 `blob hash mismatch`, nothing
    stored.
  - `commit before the commit blob is uploaded` → 400
    `commit blob not uploaded`, head unchanged.
  - `an accepted commit writes its ref`: after uploading blob `H` and committing
    `"" → H`, the blob store holds `vaults/<v>/refs/000000000001-<H>.json` whose
    JSON has `seq: 1, commit: H, previous: ""`.
  - `a stale commit` → 409 `{ error: "head_mismatch", current_head }`.
  - `check-missing lists only absent hashes`.
  - `an invalid vault id` → 400.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Change `routeHub` to take `stores` and use `stores.heads` /
      `stores.blobs` in place of `env.VAULT_HEAD` / `env.BLOBS`. Drop the
      `bearerMatches` check and `src/auth.ts` if nothing else imports it.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit:
      `refactor(container): serve the hub API from pluggable stores`.

### Task 5: Engine host

**Files:**

- Create: `src/engine-host.ts`, `test/engine-host.test.ts`
- Modify: `src/engine/runtime.ts` (load the Wasm with
  `WebAssembly.compile(await readFile(<path next to the built module>))` instead
  of the `.wasm` import), `src/mcp.ts` (take the host instead of `env`)

**Interfaces:**

- Consumes: `routeHub(request, stores)` (Task 4), `vaultKeyFor` (`bundles.ts`),
  `engineExclusive`, `startEngine`, `resetVolume`, `loadedVaultId`,
  `setLoadedVault`, `readBundleFiles`, `engineExited` (`engine/runtime.ts`).
- Produces: `class EngineHost` with
  `constructor(stores: Stores, masterKeyHex: string, onEngineExit: () => void = () => process.exit(1))`,
  `callTool(name: string, args: Record<string, unknown>, actor: string, vaultId: string): Promise<ToolResult>`,
  `snapshot(vaultId: string): Promise<Snapshot>`. `ToolResult` and `Snapshot`
  move from `vault-engine.ts` to `src/engine-host.ts`.
  `bundleCall(host: EngineHost, tool, args, policy, requestBundle)` replaces its
  `env` parameter.

`EngineHost` is `VaultEngine` without the Durable Object: same
`ensureInitialized`, blob cache, `MUTATING` set and "head moved after a failed
sync" reporting, with `okfHubFetch` calling
`routeHub(new Request("https://hub.internal" + path, ...), stores)`. No
keep-warm, no `TEST_FAULTS`, no `MCP_VAULT_ID`/`VAULT_KEY_HEX`: the key is
always `vaultKeyFor(masterKeyHex, vaultId)`. Where `VaultEngine` called
`ctx.abort`, call `onEngineExit()` and return an error result.

- [ ] **Step 1: Write the failing tests** (the real engine needs the built Wasm;
      build it once with `npm run build:engine`, which needs Go, or in the
      Docker stage of Task 7; the tests use in-memory fake stores):
  - `create then show`: `callTool("okf_create", {...}, "okf-org-acme", vaultA)`
    succeeds; `okf_show` of that concept returns its body.
  - `vaults never see each other`: create in vault A, then `okf_search` in vault
    B finds nothing, then A still finds it.
  - `calls for two vaults run one at a time`: start a call on A and a call on B
    without awaiting; each result is from its own vault (assert on content), and
    the fake head store records no interleaved commits.
  - `snapshot returns the bundle's files`: after a create,
    `snapshot(vaultA).files` has the concept's path with its content and a
    16-hex `version`.
  - `the engine exiting calls onEngineExit`: stub `engineExited` to return true
    (export a test seam from `engine/runtime.ts`), call `callTool`; the injected
    `onEngineExit` was called once and the result `isError` is true.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement `EngineHost`; update `bundleCall` and its test
      (`test/bundle-call.test.ts`: the fake becomes a fake host).
- [ ] **Step 4:** Run `npx vitest run`. Expected: PASS (unit and these tests).
- [ ] **Step 5:** Commit: `feat(container): run the okf engine in process`.

### Task 6: HTTP server, and the Worker removed

**Files:**

- Create: `src/app.ts`, `src/main.ts`, `test/app.test.ts`
- Modify: `src/mcp.ts`, `src/snapshot.ts`, `README.md`
- Delete: `src/index.ts`, `src/provider.ts`, `src/authorize.ts`,
  `src/grants.ts`, `src/github.ts`, `src/session.ts`, `src/pages.ts`,
  `src/keep-warm.ts`, `src/vault-head.ts`, `src/vault-engine.ts`,
  `src/env.d.ts`, `wrangler.jsonc`, `worker-configuration.d.ts`, their tests
  (`github`, `pages`, `session`, `keep-warm`), and the Worker-only e2e scripts
  (`e2e.sh`, `mcp-e2e.sh`, `mcp-oauth.sh`, `mcp-concurrency.sh`,
  `mcp-failure.sh`, `mcp-env.sh`, `fake-github.mjs`, `oauth-client.mjs`); drop
  `wrangler`, `agents` and `@cloudflare/workers-oauth-provider` from
  `package.json`.

**Interfaces:**

- Consumes: `loadConfig`, `PgHeadStore`, `AzureBlobStore`, `EngineHost`,
  `resolveCaller`, `bundleCall`.
- Produces:
  `createHandler(deps: { config: HubConfig; host: EngineHost; health: () => Promise<void> }): (request: Request) => Promise<Response>`
  in `src/app.ts`; `src/main.ts` loads config, migrates, ensures the container,
  and serves the handler on `PORT` (any Node adapter for fetch-style handlers;
  builder's choice).

Routing: `/healthz` → `health()` then 200 `ok`, or 503 if it throws.
`/v1/snapshot` → today's `handleSnapshot`, with `env` replaced by the config and
host. `/mcp` → bearer → `resolveCaller` → 401 (the snapshot endpoint's JSON
error shape) when null, else policy
`{ clientName, access: "full", exclude: [], bundles: grants }` (what
`provider.ts` built) → today's `handleMcp` logic, built on the MCP SDK's own
Streamable HTTP server transport in stateless JSON mode instead of
`createMcpHandler`. Everything else → 404.

- [ ] **Step 1: Write the failing tests** (`test/app.test.ts`, fake host, a
      `JwksCache` with an in-test RS256 key as `test/oidc.test.ts` does):
  - `healthz is ok while the stores answer`, and
    `healthz is 503 while health() throws`.
  - `mcp without a bearer is 401`;
    `mcp with a token for another audience is 401`.
  - `the hub API is not reachable`: `GET /api/v1/vaults/v_<32 hex>/head` → 404.
  - `an unknown path is 404`.
  - `mcp without the event-stream Accept header is 406`.
  - `an org token lists every okf tool and calls its own bundle`: `tools/list`
    has the six tools; `tools/call okf_search` reaches the fake host with that
    org's vault id.
  - `an org naming another org's bundle gets Access denied`:
    `?bundle=orgs/oidc-other` → 403; tool argument `bundle` → result text starts
    `Access denied`.
  - `snapshot needs read access`: reader token → 200; another org's token → 403.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement, delete the Worker files, rewrite the README's
      "Using it" section for the container (settings table from Global
      Constraints; "the Cloudflare version lives on `main`").
- [ ] **Step 4:** Run `npx tsc -p . && npx vitest run`. Expected: build clean,
      all unit tests PASS.
- [ ] **Step 5:** Commit:
      `feat(container): serve /mcp and /v1/snapshot from Node with Keycloak tokens only`.

### Task 7: Image and end-to-end

**Files:**

- Create: `Dockerfile`, `.dockerignore` (update), `compose.yml`,
  `test/container-oidc.sh`

**Interfaces:**

- Consumes: `npm run build`, `npm start`, `scripts/build-engine.sh`'s steps,
  `test/fake-oidc.mjs`, `test/mcp-call.mjs`.

- [ ] **Step 1:** `Dockerfile`: a `golang:1.26` stage that clones
      uw-ssec/okf-agent-memory at `engine/FORK_COMMIT` and builds
      `okf-engine.wasm`, `wasm_exec.js` and `okf-tools.json` exactly as
      `scripts/build-engine.sh` does; a Node 22 build stage (`npm ci`,
      `npm run build`); a slim Node 22 runtime stage with production deps and
      `dist/`, user `10001`, `EXPOSE 7878`, `HEALTHCHECK` on `/healthz`.
- [ ] **Step 2:** `compose.yml`: the hub image, `postgres:17`, Azurite, and
      `test/fake-oidc.mjs` as the issuer, wired with the Global Constraints
      settings (`OIDC_GRANTS`
      `[{"bundle":"orgs/oidc-{actor}","access":"write"},{"role":"knowledge-reader","bundle":"orgs/*","access":"read"}]`).
- [ ] **Step 3:** `test/container-oidc.sh`: `test/mcp-oidc.sh`'s checks minus
      every `MCP_TOKEN` and "configured vault" line, against the compose stack,
      plus `the container restarts clean`: `docker compose restart hub`, then
      acme's concept is still there.
- [ ] **Step 4:** Run
      `docker compose up -d --build && bash test/container-oidc.sh`. Expected:
      `failed: 0`.
- [ ] **Step 5:** Run the image read-only:
      `docker run --read-only --tmpfs /tmp ...` reaches healthy. Expected:
      healthy.
- [ ] **Step 6:** Commit:
      `feat(container): build the image and test it end to end`.

### Task 8: Publish the image

**Files:**

- Create: `.github/workflows/container-image.yml`

- [ ] **Step 1:** Workflow on push to `container` and `workflow_dispatch`: run
      `npm ci`, `npx tsc -p .`, `npx vitest run`, `docker compose up` +
      `test/container-oidc.sh`, then build and push
      `ghcr.io/uw-ssec/okf-hub:container-<short sha>` (`linux/amd64`) with
      `GITHUB_TOKEN` (`packages: write`). Actions pinned by commit SHA.
- [ ] **Step 2:** Push the branch (owner's go-ahead) and confirm the workflow
      run is green and the tag exists:
      `gh api /orgs/uw-ssec/packages/container/okf-hub/versions --jq '.[0].metadata.container.tags'`.
      Expected: contains `container-<sha>`.
- [ ] **Step 3:** Record the digest
      (`docker buildx imagetools inspect ghcr.io/uw-ssec/okf-hub:container-<sha>`)
      for llmoxie's plan, Task B9.
- [ ] **Step 4:** Commit: `ci(container): publish the hub image`.
