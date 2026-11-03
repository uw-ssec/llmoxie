# LLMoxie Multi-Tenant Hub: Design Spec (Milestone 1)

Owner: Don. Status: draft for review. Drafted by Monica (AI research agent) from
the Buzz #llmoxie brainstorming thread (2026-11-02/03). Background research
notes (Addenda 1-7) live outside this repo, in the drafting agent's workspace.

Related: [#193](https://github.com/uw-ssec/llmoxie/issues/193) (production
readiness gaps). This spec is the platform direction several of its items point
toward; it doesn't close them on the current Container Apps deployment.

| #193 item                           | Where this spec addresses it                                              |
| ----------------------------------- | ------------------------------------------------------------------------- |
| 1. Access control on public surface | §3, §4: Keycloak OIDC on console routes; only `/v1/*` routed to LiteLLM   |
| 2. `LITELLM_SALT_KEY` (#200)        | §7, §8: tier-0 secret, set before first model, written by Pulumi stage B  |
| 3. Shared state (Redis)             | §3: Valkey in the chart                                                   |
| 7. Data governance                  | §5, §6: consent, pseudonymous IDs, retention and consent-filtered exports |
| 8. MLflow                           | §3: MLflow off the write path, optional analysis view                     |

## 1. Problem and goal

LLMoxie today is a single-tenant Azure deployment (Container Apps, Flexible
Server Postgres, ADLS, Key Vault), driven by Pulumi with an Azure-shaped config
schema. SSEC needs:

- **A long-running hub**: one SSEC-operated instance shared by several
  collaborating organizations at once, each isolated from the others.
- **Occasional offshoots**: time-boxed single-org deployments on whichever cloud
  is funding the engagement (Azure or AWS today), torn down after the traces are
  exported. An offshoot is the hub's install path with one org configured.
- **Traces as the research product**: complete logs of AI interactions,
  attributable per pseudonymous participant, consent-filtered, exportable per
  org, and durable beyond the compute.

**Milestone 1 goal:** the multi-tenant hub running on SSEC's Azure, deployed as
a Helm chart on Azure Kubernetes Service via Nebari, with orgs, roster,
onboarding, consent, per-org provider keys and the trace log. Portability is
designed in, but no second cloud is exercised in this milestone.

## 2. Decisions (with who decided)

| #   | Decision                                                                                                                                                               | Source                                  |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| D1  | Infra: Pulumi stage A (network, managed Postgres, bucket, secrets) → `nic deploy` → Pulumi stage B (workload identity, K8s Secret, values) → ArgoCD installs the chart | Don, thread                             |
| D2  | Chart lives in the llmoxie repo at `charts/llmoxie`, published to `oci://ghcr.io/uw-ssec/charts`, versioned with app images                                            | Don                                     |
| D3  | Tenancy roles: SSEC platform admin / org lead / participant (option c "mix")                                                                                           | Don                                     |
| D4  | Org leads sign in through an IdP we run: **Keycloak** (Nebari-shipped), with UW Entra brokered for SSEC staff                                                          | Don (a); Keycloak recommended by Monica |
| D5  | Participants are key-only; they never log in. Keys come from an SSEC-provided onboarding service                                                                       | Don                                     |
| D6  | Build our own org-lead admin UI; do not depend on LiteLLM Enterprise                                                                                                   | Don                                     |
| D7  | Roster/allowlist lives in Keycloak                                                                                                                                     | Don                                     |
| D8  | Consent captured in the onboarding flow (no consent, no key), with per-participant opt-out of research use                                                             | Don                                     |
| D9  | Trace system of record: append-only log in object storage, written by a LiteLLM callback; MLflow optional analysis view                                                | Don                                     |
| D10 | Proxy-level traces only; no client-side agent telemetry                                                                                                                | Don                                     |
| D11 | Each org brings its own provider keys (BYOK) and pays its provider directly                                                                                            | Don                                     |
| D12 | Milestone 1 = the hub on Azure                                                                                                                                         | Don                                     |

## 3. Architecture

```
            Participants (API key only)          Org leads / SSEC admins (browser)
                     │                                       │
                     ▼                                       ▼
   ┌──────────────── Envoy Gateway (Nebari) ─────────────────────────────┐
   │  /v1/*  → LiteLLM (key auth)      /admin, /onboard → LLMoxie Console │
   └─────────────────────────────────────────────────────────────────────┘
          │                                   │            │
          ▼                                   ▼            ▼
   LiteLLM proxy (OSS) ◄──── admin API ──── LLMoxie Console ──► Keycloak
     │   │   └─ trace callback ─► bucket          │  (admin API, service account)
     │   └─ Valkey (rate limits / cache)          │
     └─ Postgres (LiteLLM DB) ◄───────────────────┘ (console DB: consent, invites, audit)
   Provider APIs (each org's own credentials)
```

Components shipped in `charts/llmoxie`:

- **LiteLLM proxy** (official chart or our image), external Postgres and Valkey,
  `db.deployStandalone=false`, `redis.enabled=false`. No Bitnami.
- **LLMoxie Console** (new): one service providing the org-lead admin UI, the
  SSEC admin UI, and the participant onboarding pages. It's the only component
  holding the LiteLLM admin key and the Keycloak admin service account.
- **Trace writer**: a LiteLLM custom callback (in the LiteLLM image) that
  appends records to object storage. It replaces the ADLS-specific logger.
- **MLflow** (optional, `mlflow.enabled`): analysis view loaded from the trace
  log; not on the write path.
- **DB init Job**: creates the LiteLLM, console and (optional) MLflow databases.
- Backing services: managed Postgres + cloud bucket in hub/prod
  (`backing.mode: managed`); CNPG `Cluster` + SeaweedFS + Valkey for local/dev
  and small offshoots (`backing.mode: embedded`).

Nebari provides Keycloak, Envoy Gateway, cert-manager, ArgoCD and CNPG operator.
The chart includes a `NebariApp` for routing/TLS/OIDC on the console routes
only; `/v1/*` stays API-key-authenticated.

## 4. Tenancy model

| Concept     | Keycloak                                               | LiteLLM                                                        | Console DB                                      |
| ----------- | ------------------------------------------------------ | -------------------------------------------------------------- | ----------------------------------------------- |
| Org         | group `/orgs/<org>`                                    | one team `org-<org>`                                           | org row (status, budget, consent form versions) |
| Org lead    | user in `/orgs/<org>/leads` (password or brokered SSO) | none (acts via console)                                        | audit entries                                   |
| Participant | user in `/orgs/<org>/participants`, **no credentials** | key(s) with `user_id = <keycloak uuid>`, `team_id = org-<org>` | invite + consent records                        |
| SSEC admin  | group `/platform-admins` (brokered from UW Entra)      | none (acts via console)                                        | audit entries                                   |

**Authorization is enforced in the console.** Every console action resolves the
caller's org from their Keycloak token and rejects any target outside it.
LiteLLM and Keycloak are called with platform-level credentials, so the console
is the security boundary.

**Defense in depth:** where Nebari's Keycloak is ≥ 26.2, scope the console's
Keycloak service account using Fine-Grained Admin Permissions v2 group
permissions (`view-members`, `manage-members`, `manage-membership`) limited to
`/orgs/*` (it must not touch `/platform-admins` or realm settings). See §10 open
item O3.

**Role capabilities**

- **SSEC admin:** create, suspend or delete orgs; set the org's total budget
  ceiling and rate limits; appoint org leads; view all orgs; run cross-org
  reports.
- **Org lead (own org only):** manage the roster (add, CSV import, remove); send
  invites; revoke or reissue keys; split the org budget into per-participant
  budgets up to the ceiling; manage the org's provider credentials; manage
  consent form versions; view usage; export traces. Cannot raise the org
  ceiling.
- **Participant:** holds a key and calls `/v1/*`. No UI after onboarding.

## 5. Onboarding and consent flow

1. The org lead adds participants (email + optional display label) to the
   roster. The console creates Keycloak users without credentials in
   `/orgs/<org>/participants`.
2. The org lead sends invites. The console emails each participant a
   **single-use, expiring** link (signed token; stored hashed, with expiry
   configurable per org and 7 days by default).
3. The participant opens the link. The console verifies the token, that the user
   is still on the roster and that the org is active.
4. The console shows the org's current consent form, which has two parts:
   - **Workshop terms**: required. Declining ends the flow with no key.
   - **Research use**: optional checkbox.
5. The console records consent
   `{keycloak_uuid, form_version, accepted_at, research_use}` (append-only, in
   the console DB; latest record wins) and issues a LiteLLM key:
   `team_id = org-<org>`, `user_id = <uuid>`, with the per-participant budget,
   optional expiry (default: engagement end date) and the org's model allowlist.
6. The key is shown **once**, with a copy button and a short "how to configure
   your client" snippet. The link is then consumed. Reissuing requires a new
   invite from the org lead.

**Consent rules**

- `research_use` is evaluated **at export time**. Changing it affects future
  exports only; the spec and the consent form must both say that data already
  exported cannot be recalled (the org's IRB confirms wording).
- A new form version re-prompts participants only if it is marked as changing
  research terms. Re-prompting is through a fresh invite.
- Participants can withdraw research use by asking their org lead (M1). A
  self-service withdraw link is a later item.
- Opted-out traces are kept for operations (debugging, spend) under the org's
  retention rule (§6) and are never included in research exports.

## 6. Trace log

**Write path:** a LiteLLM success/failure callback serializes one record per
request and appends it to object storage through `fsspec`-style backends
(`s3://`, `gs://`, `az://`), buffered and flushed every N records or T seconds.
Logging must never fail a user request. On write failure, buffer to local disk
and retry, and expose a metric and alert.

**Layout:**
`<bucket>/traces/v1/org=<org>/date=<YYYY-MM-DD>/part-<ts>-<writer>.jsonl.gz`.
Parquet compaction is a later batch job.

**Record schema v1** (one JSON object per request):

| Field                                             | Notes                                                                          |
| ------------------------------------------------- | ------------------------------------------------------------------------------ |
| `schema_version`                                  | `1`                                                                            |
| `request_id`                                      | LiteLLM call id                                                                |
| `org`, `participant_id`                           | `participant_id` = Keycloak UUID, never email                                  |
| `key_alias`                                       | hashed key id, not the key                                                     |
| `session_id`                                      | from request metadata/header if client sends one, else null                    |
| `model_requested`, `model_resolved`, `provider`   |                                                                                |
| `started_at`, `ended_at`, `latency_ms`, `ttft_ms` |                                                                                |
| `request`                                         | full messages, tools and params (excluding credentials)                        |
| `response`                                        | full response, including tool calls; streamed responses are reassembled        |
| `usage`                                           | prompt, completion and total tokens; cost                                      |
| `status`, `error`                                 | provider errors are classified as `provider_auth`, `provider_quota` or `other` |

**Scope boundary (D10):** only what crosses the proxy. Tool calls and tool
results are captured because they're in the messages. Local agent behavior
(skills fired, files read, shell commands, accept/reject) is **out of scope**,
and exports must be documented as such.

**Export:** an org lead (or SSEC admin) picks a date range. The console produces
a filtered copy (dropping participants whose latest consent has
`research_use=false`) to an export prefix, or a signed download URL. Each export
writes a manifest: who exported, when, the filter, record counts and consent
snapshot hash. Exports are audit-logged.

**Retention:** per-org setting. The default keeps research-consented traces
until the org's agreement end date plus a configured period. Opted-out and
non-consented traces are deleted at engagement end. Implementation uses bucket
lifecycle rules where they're prefix-expressible, plus a console job for
consent-based deletion.

**Isolation:** per-org prefixes. Org leads never get bucket credentials; all
access goes through the console.

## 7. Per-org provider credentials (BYOK)

LiteLLM's team-scoped models (`/model/new` with `model_info.team_id`) need an
Enterprise license ([docs](https://docs.litellm.ai/docs/proxy/team_model_add)).
OSS approach:

- The org lead enters a provider credential and selects the models to enable.
  The console tests the credential with a minimal call before saving.
- The console registers deployments through LiteLLM's admin API under
  **org-prefixed names** (`<org>/<model>`) and sets the team's `models`
  allowlist to exactly that org's names.
- Credentials are stored by LiteLLM in its DB, encrypted with NaCl SecretBox
  under a key derived from `LITELLM_SALT_KEY`
  ([security FAQ](https://docs.litellm.ai/docs/proxy/security_encryption_faq)).
  **The salt key must be set before the first model is added and cannot be
  rotated in place.** It is a tier-0 secret, held in the cloud secret store and
  backed up separately from the DB.
- Rotation: the org lead enters a new credential; the console updates the
  deployment and re-tests.
- Failures: provider auth or quota errors are surfaced to the org lead in the
  console (per-org error rate panel and optional email), not just to
  participants.
- Participants see prefixed model names in M1 (`acme/gpt-4o`). Hiding the prefix
  is open item O2.

## 8. Deployment (Milestone 1, Azure hub)

1. **Pulumi stage A** (existing Azure code, refactored behind a provider-neutral
   interface): VNet and subnets, Flexible Server (private), storage account and
   container, Key Vault.
2. **`nic deploy`** (Azure Kubernetes Service) into the existing VNet.
3. **Pulumi stage B:** workload identity (federated credentials using the
   cluster OIDC issuer), K8s Secret with DB URIs, LiteLLM master and salt keys,
   and console signing key. Non-secret values are written to the GitOps repo at
   `values/llmoxie.yaml`.
4. **ArgoCD** `Application` in project `nebari-apps` (not `default`, which NIC
   makes deny-all), multi-source: chart from OCI plus `$values` ref.
5. Keycloak realm config (groups, console client, Entra broker) is managed as
   code (Pulumi Keycloak provider in stage B).

**Migration from the current Container Apps prod** is in scope as a plan, not a
cutover: M1 runs the hub side by side; existing users move when the hub passes
acceptance. Key and spend history migration is decided in that plan.

**Required image change:** the MLflow image adds `boto3` and
`google-cloud-storage`. The LiteLLM image gains the trace callback and its
storage dependencies.

## 9. Testing and acceptance

- **Cross-org denial suite (required, CI):** for every console endpoint, a lead
  of org A attempting to act on org B (roster, keys, budgets, credentials,
  exports, consent forms) is rejected. It also asserts the console never calls
  LiteLLM or Keycloak with an out-of-org target.
- **Key isolation:** an org A participant key cannot call an org B model name.
- **Consent:** declining workshop terms issues no key. `research_use=false`
  participants are absent from exports; toggling affects only later exports.
- **Trace completeness:** streaming and non-streaming calls, tool calls, and
  provider errors each produce exactly one record with required fields. A
  storage outage doesn't fail requests and the records arrive after recovery.
- **Chart CI:** kind smoke test with `backing.mode: embedded` (CNPG +
  SeaweedFS + Valkey). It onboards a participant, makes a call to a mock
  provider and asserts the trace object exists.
- **Acceptance (M1):** two real orgs on the Azure hub, each with a lead, roster
  and own provider key. A dry-run workshop of at least 10 participants ends with
  a consent-filtered export that the research side confirms is usable.

## 10. Open items

| #   | Item                                | Why it matters                                                                                                                                                                                                         |
| --- | ----------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| O1  | Get a LiteLLM Enterprise quote      | Two features (scoped org admin, team models) are being built around the paywall. A real number lets us confirm build vs buy                                                                                            |
| O2  | Hiding the `<org>/` model prefix    | Team `model_aliases` is documented as deprecated in favor of tag-based routing ([docs](https://docs.litellm.ai/docs/proxy/team_based_routing)). Spike both; fall back to visible prefixes                              |
| O3  | Nebari's Keycloak version ≥ 26.2?   | FGAP v2 group scoping is supported from 26.2 ([release notes](https://keycloak.org/docs/latest/release_notes), [blog](https://www.keycloak.org/2025/05/fgap-kc-26-2.html)). If older, the console is the only boundary |
| O4  | Email delivery for invites          | Needs an SMTP/ESP choice per deployment, and Keycloak's SMTP could be reused                                                                                                                                           |
| O5  | IRB/consent wording templates       | Owned by orgs; LLMoxie supplies the mechanism and the irrevocability statement                                                                                                                                         |
| O6  | Budget semantics with BYOK          | Orgs pay providers directly, so LiteLLM budgets act as guard rails only. Confirm whether SSEC needs any billing view                                                                                                   |
| O7  | Container Apps → hub migration plan | Separate document before cutover                                                                                                                                                                                       |

## 11. Out of scope (M1)

- AWS offshoot (designed for, not exercised). Planned for Milestone 2 on EKS via
  Nebari, with S3 and RDS.
- Client-side agent telemetry (D10).
- Per-org federated SSO for org leads (Keycloak brokering keeps it possible).
- Participant self-service (login, usage view, self-withdraw).
- Native serverless compute paths (ECS or Cloud Run).
- LiteLLM Enterprise features.

## 12. Suggested build order

1. **P0:** `charts/llmoxie` (LiteLLM, optional MLflow, DB init, embedded and
   managed backing, `existingSecret` contract), kind CI, plus the image fixes.
2. **P1:** trace callback, record schema v1, write path and storage-outage
   handling.
3. **P2:** console skeleton (Keycloak OIDC, org model, SSEC admin create-org),
   cross-org denial test harness.
4. **P3:** roster, invites, onboarding, consent, key issuance.
5. **P4:** BYOK credentials, model allowlists, provider-error surfacing.
6. **P5:** exports, retention jobs, audit log.
7. **P6:** Azure hub deploy (Pulumi A/B refactor, NIC, ArgoCD), then the two-org
   dry run.
