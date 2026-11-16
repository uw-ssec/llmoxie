# The console on the Azure stack

**Date:** 2026-11-15 **Branch:** `console-azure` (from `console-react-ui`, PR
#240) **Status:** design, awaiting approval

## Intent

The LLMoxie console (`services/console/`, PR #240) runs today only in the local
proof of concept (`~/Agent-Workspace/litellm-keycloak`). This branch makes it
part of the Azure stack that `llmaven infra deploy` builds, the way it will run
for real, and brings it up on dev first. The owner chose Pulumi over a
hand-deployed try-out: whatever runs on dev is what staging and production will
run.

Keycloak is already on dev (#246, llmaven-deploy #58), so the console signs in
against the `llmoxie` realm at `dev.auth.uwssec.org`. The console's original
Azure design (`upstream/docs/azure-console-design`,
`docs/superpowers/specs/2026-11-06-azure-console-design.md`) still sets the
security goals; its Entra External ID sign-in was replaced by Keycloak
(`decisions/keycloak-identity-provider`).

## Goals

1. An off-by-default `console` config block that deploys `console-web`,
   `console-broker`, the one-shot `console-init`, the console's database and
   roles, its Keycloak clients and its mail, behind the existing Traefik edge.
2. LiteLLM split across two hostnames, as in the proof of concept: a **gateway**
   host that answers only the AI paths and health, and an **admin** host with
   the UI and management API behind the Keycloak login.
3. The console's secrets kept apart: `console-web` can read nothing that would
   let it act as the broker or as LiteLLM's admin.
4. Real mail: invitations and key-rotation notices sent through Azure
   Communication Services from `mail.uwssec.org`.
5. CI builds and publishes `ghcr.io/uw-ssec/llmoxie-console`.
6. Keycloak accounts for invitees, created from a CSV of emails by a script, so
   nobody has to click through Keycloak's admin console per person.
7. Everything deployable with the **Contributor** role: no Azure role
   assignments, because the people who run `infra deploy` don't have the right
   to make them.
8. Dev runs it, and the end-to-end check under [Done on dev](#done-on-dev)
   passes.

## Non-goals

- **The knowledge hub.** okf-hub is not deployed. The console runs without it
  (see [Console code changes](#9-console-code-changes)); the hub, the
  `console-knowledge` and `console-provisioner` clients and the gateway's `/mcp`
  route come in a later step. The broker uses `console-provisioner` only to
  create and delete each organization's knowledge client, so it would be an
  unused realm-wide right until then.
- **Self-service sign-up and identity providers.** The realm keeps
  `registrationAllowed: false` and gets no SMTP. "Sign in with GitHub" (Keycloak
  brokering GitHub and trusting its verified email) and self sign-up with
  Keycloak's own verification mail are later options.
- The data protection page (ceil-dlp). `CONSOLE_DLP_AUDIT_FILE` stays unset.
- Console alerts in `resources/monitoring.py`, the threat model, the pen test
  and the ASVS review from the original design. They stay on its build order.
- Schema migrations. The database job applies the schema once; a way to change
  it later is its own piece of work.
- Moving existing LiteLLM keys and users into the console (original design O11).
- The local docker-compose stack and Helm.

## Anti-goals

This fails even if it works when:

- `console-web`'s identity can read the LiteLLM master key, the broker's admin
  key or the provisioner secret.
- The gateway host serves any LiteLLM path beyond the AI paths and health, from
  any IP, with any key.
- A stack without `console.enabled` and without `litellm.admin_hostname` renders
  differently from today (`--expect-no-changes` must pass on it).
- A secret value appears in Pulumi output, a log, or a committed file.

## Constraints (from project memory and the code)

- **One shared identity, one AccessPolicy** on the existing vault
  (`bugs/key-vault-access-policy-replace`). The console must not add access
  policies to that vault.
- **Contributor only.** `infra deploy` runs under the operator's `az login`,
  which is Contributor on the subscription (checked 2026-11-15). That can create
  vaults and set their access policies, but not Azure role assignments.
- **Invitations need a verified email.** The broker matches an invitation only
  when the token's `email_verified` is true (`console_app/broker/auth.py`), and
  the realm has sign-up off and no mail.
- **Images pinned by tag and digest** when enabled, as for Keycloak; CI images
  are built in `build-services.yml`.
- **Container App and job names fit 32 characters**; the schema already checks
  this for every app.
- **The realm job runs with `no-delete`**, so per-organization clients the
  broker creates survive every deploy; the console's static clients are added to
  the rendered realm like the existing ones.
- **The Keycloak bootstrap `admin` stays**
  (`facts/keycloak-bootstrap-admin-is-the-realm-jobs-login`).
- **LiteLLM's salt key** must be set before any provider key is stored
  (`requirements/litellm-master-and-salt-key`). Dev has it.
- **`store_model_in_db: true`** in LiteLLM's config. Dev has it.
- **Live changes need explicit approval** for each preview and deploy.

## Approaches

Decided in conversation on 2026-11-15:

| Question           | Options considered                                                                    | Chosen and why                                                                                                                                      |
| ------------------ | ------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| How it is deployed | Hand-deployed try-out; a separate Pulumi stack; a `console` block in this program     | **The `console` block.** It's how it will run for real; a separate stack would still need this program's edge and realm                             |
| Knowledge hub      | Deploy okf-hub too; make knowledge optional in the console                            | **Optional.** Orgs, teams and keys work sooner; the hub adds on later without rework                                                                |
| Mail               | Azure Communication Services; an existing SSEC/UW provider; Mailpit in dev            | **Azure Communication Services**, sender domain `mail.uwssec.org`                                                                                   |
| Secret isolation   | The shared identity and vault; a console vault with one identity per container        | **One identity per container, each reading only its own secrets**, because the main vault grants all or nothing                                     |
| How it's isolated  | An RBAC vault with per-secret role assignments; one access-policy vault per container | **A vault per container, with access policies set when the vault is made.** Role assignments need rights the deployer lacks                         |
| LiteLLM hostnames  | One host split by path; a gateway host and an admin host                              | **Two hosts**, as in the proof of concept: `dev.llm` stays the gateway (API clients keep working), `dev.litellm` is admin                           |
| Invitee accounts   | Made by hand; self sign-up with Keycloak mail; sign in with GitHub                    | **Made by an operator, scripted from a CSV.** Self sign-up needs Keycloak SMTP, which on ACS needs an Entra app and a role assignment; GitHub later |

## Design

### 1. LiteLLM: gateway host and admin host

New optional `litellm.admin_hostname`. Unset, LiteLLM's routes render exactly as
today. Set:

- **`litellm.hostname` is the gateway.** The edge routes only
  `litellm.public_paths` (rate-limited) and `litellm.health_paths` on it. There
  is no catch-all router, so every other path, including `/ui`, `/key/*`,
  `/sso/*` and `/oauth2/*`, gets Traefik's 404 from any IP, with or without a
  key.
- **`litellm.admin_hostname` gets today's admin rules**
  (`_add_litellm_login_routes` with this host, or the IP-allowlisted catch-all
  when the login is off): a Keycloak session with `litellm.login.role`, or a
  bearer key from `admin_allowed_ips` and never on the UI paths.
- `PROXY_BASE_URL`, the realm's `litellm` and `litellm-gate` redirect URIs, and
  the `llm-auth` oauth2-proxy's redirect URL, cookie and whitelist domains move
  to the admin host.
- Validation: `admin_hostname` needs the edge, differs from every other
  hostname, and is listed in `edge.custom_domains` like the others.
- `pulumi.export("litellm_url", ...)` stays the gateway; a new
  `litellm_admin_url` export carries the admin host.
- Operator effect: management scripts using a bearer key, including
  `infra extract --source litellm` (its `LITELLM_BASE_URL` in the env file),
  must point at the admin host. The infrastructure rule says so.

### 2. The console image and CI

- `build-services.yml` gets a `console` matrix entry: context
  `services/console`, its `Dockerfile` (target `app`), `linux/amd64`, published
  as `ghcr.io/uw-ssec/llmoxie-console` with the same tag scheme.
- The stack pins `console.image` by tag and digest; `:latest` is refused when
  the console is enabled, as for Keycloak.

### 3. Config

```yaml
litellm:
  hostname: dev.llm.uwssec.org # gateway
  admin_hostname: dev.litellm.uwssec.org # new; UI and management API

console:
  enabled: true
  hostname: dev.console.uwssec.org
  image: ghcr.io/uw-ssec/llmoxie-console:<tag>@sha256:<digest>
  admin_subjects: ["<Keycloak user id>"] # CONSOLE_ADMIN_SUBJECTS
  invite_ttl_hours: 72
  mail:
    domain: mail.uwssec.org
    sender: console # console@mail.uwssec.org
    display_name: LLMoxie console
    domain_verified: false # set true once Cloudflare records verify
  web: { min_replicas: 1, max_replicas: 2, cpu: 0.25, memory: 0.5Gi }
  broker: { min_replicas: 1, max_replicas: 1, cpu: 0.5, memory: 1Gi }
```

Validation when `console.enabled`:

- needs `edge.enabled`, `keycloak.enabled`, `litellm.enabled`,
  `litellm.login.enabled` (the admin host must not be open) and
  `litellm.admin_hostname`;
- `console.hostname` differs from every other hostname;
- the image is pinned by tag and digest;
- LiteLLM's config has `store_model_in_db: true` and `LITELLM_SALT_KEY` is set
  in `env_vars` or `key_vault_secret_refs`. This is an error here, not the
  existing warning, because the console stores provider keys;
- `admin_subjects` is non-empty;
- every new app and job name fits 32 characters.

`console_db` is added to `database.databases` automatically and kept on delete,
as `keycloak_db` is (`RETAINED_DATABASES`).

### 4. Container Apps

All on internal ingress in the existing environment, health at `GET /healthz`.

| App / job        | Command                                 | Port | Identity                  | Reached by                      |
| ---------------- | --------------------------------------- | ---- | ------------------------- | ------------------------------- |
| `console-web`    | `uvicorn console_app.web.app:app …`     | 8200 | `console-web` identity    | the edge, at `console.hostname` |
| `console-broker` | `uvicorn console_app.broker.app:app …`  | 8100 | `console-broker` identity | `console-web`, internally       |
| `console-init`   | `python init_admin_key.py` (manual job) | –    | shared identity           | run by `infra deploy`           |
| `console-db`     | the database job ([§5](#5-database))    | –    | shared identity           | run by `infra deploy`           |

- The edge gets a `console` router: `Host(console.hostname)`, rate-limited, no
  ForwardAuth (the console signs people in itself), service `console-web`.
- `console-web`'s settings: `CONSOLE_BROKER_URL` is the broker's internal https
  FQDN; `OIDC_AUTH_URL` and `OIDC_LOGOUT_URL` use Keycloak's public hostname;
  `OIDC_TOKEN_URL` and `OIDC_JWKS_URL` use Keycloak's internal FQDN, as the
  oauth2-proxy logins do; `OIDC_ISSUER` is the public issuer;
  `GATEWAY_PUBLIC_URL` is `https://<litellm.hostname>`; `LITELLM_ADMIN_URL` is
  `https://<litellm.admin_hostname>`.
- The broker's settings: `LITELLM_URL` is LiteLLM's internal FQDN;
  `MAIL_BACKEND=acs` with the Communication Service's connection string;
  `KEYCLOAK_*` and `KNOWLEDGE_*` stay unset until the hub;
  `CONSOLE_ENABLE_MOCK_PROVIDER` stays unset.
- The broker is reachable by every app in the environment, as LiteLLM is. It
  authenticates every call itself (caller secret plus the user's token), which
  the README already relies on.
- After a successful `up`, `infra deploy` runs, in order: the realm job (as
  today), `console-db`, then `console-init`, each waited for, with the same
  "deployed, but … was not applied" report and ready-to-run `az` commands on
  failure. On a first deploy the console answers errors for the minute before
  the jobs finish; the builder checks the broker starts without the key file and
  the schema, and reads them when needed.

### 5. Database

- `console_db` on the existing Flexible Server (via `database.databases`).
- The `console-db` job connects as the server's admin login and applies an Azure
  version of `services/console/db/console-db.sql`, kept next to it:
  - roles `console_web` and `console_broker` are created if missing, and their
    passwords set from Key Vault on every run (so a rotated secret takes);
  - the schema is applied only when `console_db` has no tables yet;
  - tables are owned by the admin login, so row-level security applies to the
    broker;
  - `REVOKE CONNECT … FROM PUBLIC` covers every other database in
    `database.databases`, after granting `CONNECT` to the admin login, so
    LiteLLM, MLflow, Keycloak and the backup job keep working.
- It runs from the console image (Python and psycopg are already there), with a
  small script added to the image; the builder may use the backup image's `psql`
  instead if that's simpler.
- Point-in-time backups cover it as part of the server. The nightly `pg_dump`
  job keeps backing up only its configured database.

### 6. Secrets and identities

No Azure role assignments anywhere: the deployer is Contributor (see
Constraints). Isolation comes from separate vaults instead.

- **Two new user-assigned identities**, `console-web` and `console-broker`.
- **Two new Key Vaults**, one per identity, using access policies
  (`enable_rbac_authorization: false`, like the main vault) with the main
  vault's soft-delete and purge-protection settings. Each vault's access
  policies are set inline when the vault is created, and there are two: its
  identity may `get` and `list` secrets, and the deployer gets the same policy
  it has on the main vault (`create_key_vault`'s `deployer_object_id`). No
  separate `AccessPolicy` resources, so `bugs/key-vault-access-policy-replace`
  can't happen.
- The main vault and its one AccessPolicy are unchanged. Secrets the jobs need
  are written there too, since the jobs run as the shared identity.

| Secret                         | Generated by       | Vault(s)                        | Read by                  |
| ------------------------------ | ------------------ | ------------------------------- | ------------------------ |
| `console-oidc-client-secret`   | Pulumi random      | `console-web`; main (realm job) | `console-web`; realm job |
| `console-broker-caller-secret` | Pulumi random      | `console-web`; `console-broker` | both apps                |
| `console-web-db-url`           | from its password  | `console-web`                   | `console-web`            |
| `console-broker-db-url`        | from its password  | `console-broker`                | `console-broker`         |
| `console-mail-connection`      | the ACS access key | `console-broker`                | `console-broker`         |
| `console-web-db-password`      | Pulumi random      | main                            | `console-db` job         |
| `console-broker-db-password`   | Pulumi random      | main                            | `console-db` job         |

- The shared identity (LiteLLM, MLflow, the jobs) can read the console's
  database passwords and client secret in the main vault. It can already read
  the master key, so that adds little; what matters is that `console-web` can
  read neither the main vault nor the broker's.
- Generated values live in Pulumi state as secrets, as the Keycloak client
  secrets already do. Nothing new goes in the env file.
- **The broker's LiteLLM key** never passes through Pulumi or Key Vault:
  `console-init` makes it and writes it to an **Azure Files share** mounted at
  `/run/console` (read-write for the job, read-only for the broker), which is
  what the image already expects. The share is on a small storage account of its
  own (StorageV2, Standard_LRS, no hierarchical namespace): dev's main account
  is ADLS Gen2 (`enable_hierarchical_namespace: true`), where Azure Files isn't
  offered.

### 7. Realm

When `console.enabled`, `build_realm_document` adds:

- **`console`**: confidential, standard flow only, PKCE `S256`, redirect URI
  `https://<console.hostname>/auth/callback`, post-logout redirect to the
  console, an audience mapper adding `console-broker`, and the email scope. Its
  secret comes in as an `$(env:…)` placeholder like the existing clients.
  `console-provisioner` and `console-knowledge` wait for the hub. A test asserts
  the realm renders unchanged with the console off.

### 8. Mail

- Pulumi creates an **Email Communication Service** with a **customer-managed
  domain** `mail.uwssec.org`, a sender username `console`, and a **Communication
  Service** linked to that domain, all in the stack's resource group (data
  location: United States).
- The domain's verification records (domain TXT, SPF, DKIM, DKIM2) are exported.
  The owner adds them in Cloudflare, then verification is started
  (`az communication email domain initiate-verification`), as for the
  certificates. Linking the domain to the Communication Service needs it
  verified, so `console.mail.domain_verified` (default `false`) decides whether
  the deploy links it: the first deploy creates the domain, the owner verifies
  it and sets the flag, and the next deploy links it. Until then invitations
  fail with a clear mail error.
- The subscription must have the `Microsoft.Communication` resource provider
  registered (it wasn't on 2026-11-15); the rollout registers it once.
- The broker sends through the **Azure Communication Email SDK with the
  Communication Service's connection string**. Pulumi reads the service's
  primary connection string (`listCommunicationServiceKeys`) into the
  `console-mail-connection` secret in the broker's vault. That's a mail secret,
  but it needs no role assignment and no Entra app, which sending with a managed
  identity (a role on the service) and ACS's SMTP login (an Entra app) both
  would. Rotating it means regenerating the key and deploying.

### 9. Console code changes

On this branch, in `services/console/`:

- **Knowledge is optional.** With `KNOWLEDGE_HUB_URL` unset, the broker starts
  without any `KEYCLOAK_*` or `KNOWLEDGE_*` setting; creating an organization
  skips its Keycloak `okf-org-*` client and its MCP server; teams get no MCP
  server; the knowledge page and the team page's MCP details say knowledge isn't
  set up. Suspending and removing an organization skip the knowledge steps it
  never had. The existing suite still passes with the hub configured.
- **Mail backends.** `MAIL_BACKEND=smtp` (the default; Mailpit and the local
  stack keep working unchanged) or `acs`, which sends through the Azure
  Communication Email SDK with `ACS_CONNECTION_STRING`. The new dependency is
  locked in `requirements.txt`.
- **Database job script**, as in [§5](#5-database).
- Tests for each: unit tests that need no stack, plus the end-to-end suite
  against the local stack, both with the hub and without it.

### 10. Invitee accounts from a CSV

The realm has no sign-up and no mail, and an invitation needs a verified email,
so an operator creates each lead's and participant's Keycloak account before
inviting them. A new command does it in bulk:

```sh
llmaven infra keycloak-users -c llmaven-config.yaml --csv people.csv --out passwords.csv
```

- `people.csv` has an `email` column, the same file a lead uploads to invite
  participants to a team, so one list serves both steps.
- For each email without an account in `keycloak.realm.name`, it creates a user
  with that email as username and email, `emailVerified: true`, a random
  temporary password, and the required action `UPDATE_PASSWORD`. Existing
  accounts are left alone and reported.
- It calls Keycloak's admin API at `https://<keycloak.hostname>/admin/`, which
  the edge allows only from `keycloak.admin_allowed_ips`, signing in as the
  bootstrap `admin` with `keycloak-admin-password` read from the stack's main
  vault (the deployer has a policy there).
- The temporary passwords go only to `--out`, created with mode `0600`, never to
  the terminal. The operator sends each person theirs out of band and deletes
  the file.
- It changes the live realm, so it asks for confirmation unless `--yes`, and
  `--dry-run` lists what it would create.

## Rollout on dev

0. Register the `Microsoft.Communication` resource provider on the subscription
   (`az provider register --namespace Microsoft.Communication`).
1. CI publishes `llmoxie-console` from this branch; pin it by tag and digest.
2. DNS, by the owner in Cloudflare: CNAME and `asuid` TXT for
   `dev.litellm.uwssec.org` and `dev.console.uwssec.org`; hostname add and bind
   on the Traefik app; certificates listed in `edge.custom_domains`.
3. Note your Keycloak user id (`llmoxie` realm) for `console.admin_subjects`.
4. Preview, then deploy, with approval: LiteLLM split, console apps, vault,
   identities, jobs, mail resources.
5. Add the mail domain's records in Cloudflare, start verification, and deploy
   again once it's verified, to link the domain.
6. Create the test lead's and participant's accounts with
   `infra keycloak-users`.
7. The Done-on-dev check below.

Rollback: turn `console.enabled` off and deploy. The console vault, identities,
apps and mail resources are removed; `console_db` is kept. Unsetting
`litellm.admin_hostname` returns LiteLLM to one host.

## Done on dev

1. Signed in at `https://dev.console.uwssec.org` as the SSEC admin, create an
   organization and invite a lead.
2. The lead gets a real email from `console@mail.uwssec.org`, signs in with the
   account the script made (setting a new password), accepts, adds a model with
   a provider key, makes a team and invites a participant by CSV.
3. The participant accepts, creates a key and calls
   `https://dev.llm.uwssec.org/v1/chat/completions` with it.
4. The same key gets 404 on `dev.llm.uwssec.org/key/list` and `/ui`; anonymous
   requests to those paths get 404 too.
5. The lead archives the team; the key stops working.
6. The LiteLLM UI still works at `https://dev.litellm.uwssec.org/ui` with one
   Keycloak sign-in.
7. Read-only checks: each console vault's access policies are exactly its
   identity and the deployer, and neither console identity appears in the main
   vault's policies (`az keyvault show`); the console's `/healthz` is reachable
   publicly only through the edge's console route.

## Verification in the repo

- `pixi run -e llmaven verify` passes; the console's own tests pass
  (`pixi run ui-check`, `tests/test_shapes.py`, the end-to-end suite against the
  local stack).
- Render tests: with the console off and no `admin_hostname`, the edge config,
  realm document and program render byte-identically to `console-react-ui`.
- Edge rule tests (with the existing router evaluator): on the gateway host,
  every non-AI path, encoding variant and `;`/`%`/backslash probe has no route;
  on the admin host, the existing login tests hold.
- Secret scoping tests: each console vault has exactly two inline access
  policies (its identity and the deployer), each app references only its own
  vault, and the program creates no role assignments.
- The account script: unit tests against a stand-in admin API (creates, skips
  existing, never prints a password, `--out` is `0600`).

## Risks to verify on dev

- Whether databases created through ARM grant `CONNECT` to the admin login after
  `REVOKE … FROM PUBLIC`. The job grants it first, but this is untested on
  Azure.
- Re-enabling the console after turning it off: Key Vault soft-delete keeps the
  old vault names reserved, so a re-enable needs `az keyvault recover` or
  `purge` first; the rollback section of the rule says so.
- That Contributor can create everything here: identities, vaults with inline
  policies, ACS resources, the file share and environment storage.

## Records to update

- `.agents/rules/infrastructure.md`: a console section (config, rollout, the two
  LiteLLM hosts, mail domain verification, rollback).
- Project memory: a decision record for the console on Azure (the five choices
  above), and updates to `decisions/keycloak-identity-provider` (the console's
  client) and `bugs/key-vault-access-policy-replace` (inline policies on
  separate vaults as the way around it), and a fact that the deployer is
  Contributor and can't make role assignments.
- `services/console/README.md`: the optional hub and the mail backends.

## Left to the builder

Module layout under `resources/`, resource and secret names within the 32-char
limits, how the jobs are waited for, whether the database job reuses the backup
image, the exact Container App sizes, the router priorities on the gateway host,
and the shape of the console's knowledge-off messages.
