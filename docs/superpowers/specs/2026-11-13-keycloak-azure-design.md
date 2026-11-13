# Keycloak on Azure, behind a standalone Traefik

**Date:** 2026-11-13 **Branch:** `keycloak-service` (from `console-react-ui`)
**Status:** design, awaiting approval

## Intent

Keycloak becomes llmoxie's real identity provider in deployed environments,
starting with the Azure stack that `llmaven infra deploy` builds. Two reasons,
both from the owner:

1. The console needs it. Its broker creates one Keycloak client per organization
   at runtime (as `console-provisioner`) so the knowledge hub can tell
   organizations apart, and connected services (JupyterHub and the like) sign
   users in through the same realm. Entra External ID, which the unmerged Azure
   console design (`upstream/docs/azure-console-design`,
   `docs/superpowers/specs/2026-11-06-azure-console-design.md`, decision 10 "No
   Keycloak") chose, does not offer that. **This design replaces that design's
   identity section;** its owner should be told.
2. Keycloak will later broker CILogon, so people can sign in with their
   institution. The console identifies people by Keycloak's issuer and `sub`,
   which stay stable when a CILogon login is linked to a Keycloak user, so
   nothing here may tie identity to local passwords outside Keycloak.

The first use is to put a Keycloak login in front of the two admin surfaces the
stack already has: people sign in through Keycloak instead of LiteLLM's own UI
login (whose password is the master key), and MLflow stops being reachable with
no login at all.

To do that once and in the shape the console will need, Traefik moves out of
LiteLLM's replica and becomes the stack's only public entry point, in front of
every service, as in the local prototype (`~/Agent-Workspace/litellm-keycloak`,
`traefik/dynamic.yml`).

## Two stages

The work ships in two stages on this branch, each rolled out on its own
(staging, then ISS, then prod) before the next starts:

- **Stage 1, standalone Traefik.** A Traefik Container App is the only app with
  public ingress. LiteLLM and MLflow move to internal-only ingress, and every
  custom domain moves to Traefik. Routing and access are what they are today; no
  Keycloak yet.
- **Stage 2, Keycloak and the logins.** A Keycloak Container App behind that
  Traefik, its realm applied by keycloak-config-cli from the config YAML, and
  Keycloak logins in front of MLflow and the LiteLLM UI, with LiteLLM's UI
  signing in through Keycloak on the uw-ssec fork.

## Goals

- One public entry point. Nothing in the stack is reachable from the internet
  except through Traefik, so no route can skip its rules.
- A Keycloak Container App with its own database, its secrets in Key Vault, and
  a stable public hostname (the token issuer).
- The realm (roles, clients, mappers, later identity providers) described in the
  llmoxie config YAML, so each environment's realm is kept and reviewed in
  `uw-ssec/llmaven-deploy`, and applied by
  [keycloak-config-cli](https://github.com/adorsys/keycloak-config-cli) on every
  deploy.
- MLflow reachable from outside only with a Keycloak login holding the role
  `mlflow-user`, or a Keycloak access token for a client holding it. LiteLLM
  keeps logging to MLflow.
- LiteLLM's UI and management routes reachable only with a Keycloak login
  holding `litellm-admin`, with LiteLLM's UI signing that person in through
  Keycloak (SSO) with no second prompt, on the
  [uw-ssec/llmoxie-litellm](https://github.com/uw-ssec/llmoxie-litellm) fork so
  SSO keeps working past five LiteLLM users. Scripts that carry a LiteLLM key
  from an allowlisted IP keep working as today.
- A `staging` stack to prove each stage before ISS and prod.

## Non-goals

- Deploying the console to Azure. That is the next branch; it adds the console's
  hostnames to Traefik and its clients (`console`, `console-provisioner`,
  `console-knowledge`) and audience mapper to the realm through the same config.
- CILogon. The design leaves room for it (see "Identity providers later") but
  does not configure it.
- Helm / Kubernetes, the local docker-compose stack, and the console's
  end-to-end suite.
- More than one Keycloak replica.
- MFA policy, self-registration and password-reset email.
- Extending the `pg_dump` backup job to several databases (#193).

## Anti-goals

- **A login that can be skipped.** A gate that a platform FQDN, a route alias, a
  double slash or a path prefix gets around is worse than none, because people
  will trust it.
- **Breaking request logging or the AI paths.** API-key traffic to LiteLLM's
  public inference paths must not see Keycloak at all, and LiteLLM must keep
  writing traces to MLflow.
- **Realm drift.** A realm whose real state lives only in the admin console,
  with no record in `llmaven-deploy`.
- **Clobbering runtime clients.** The deploy must never delete the
  per-organization clients the console creates.
- **Secrets in YAML.** Client secrets, the bootstrap admin password and cookie
  secrets never appear in the config file.

## Constraints (from project memory and the code)

- **One Key Vault access policy, one shared identity.** azure-native's
  `AccessPolicy` replaces rather than adds, so every app and job uses the shared
  user-assigned identity and its single policy
  (`knowledge/bugs/key-vault-access-policy-replace.md`). The new apps and the
  job use it too; don't add a second `AccessPolicy`. Apps must `depends_on` the
  policy (`knowledge/facts/fresh-stack-startup-requirements.md`).
- **The LiteLLM image is pinned by tag and digest, and upgrades are one-way**
  (`knowledge/decisions/litellm-image-digest-pin-and-one-way-upgrade.md`). The
  fork image is pinned the same way. The fork is upstream `v1.108.6`, which prod
  and ISS already run, so no Prisma migration is expected; confirm it.
- **Path rules are exact-path allowlists for LiteLLM.** Never add `PathPrefix`
  routes for LiteLLM's `/v1/` or `/health/`; it serves management routes under
  both (`knowledge/requirements/traefik-sidecar-allowlist-and-client-ip.md`).
  The same record explains why a front door used to be rejected: the platform
  FQDN reached the app directly. Internal-only ingress on every backend is what
  removes that objection here, so it is not optional.
- **Client-IP trust is unproven on Azure.** The rightmost `X-Forwarded-For`
  entry is trusted only from `trusted_proxy_ips`, and the two checks the README
  names (the Envoy peer is inside that range; no other workload can reach
  Traefik directly and forge the header) have never run live. They run on
  staging in stage 1, before ISS and prod.
- **Custom domains are declarative, and the first certificate is manual**
  (`knowledge/facts/custom-domains-declarative-certificate-manual.md`). A
  hostname not in `custom_domains` is removed on deploy, and a managed
  certificate is issued only after a manual `hostname add` / `hostname bind`.
- **Identifiers of deployed resources stay**
  (`rebrand-keeps-deployed-identifiers`): existing apps, databases and
  containers keep their names.
- **Never touch live infrastructure without approval.** Every deploy, including
  `--preview`, and creating the staging stack, are the owner's to run.

## Approaches

Decisions taken in conversation, with what was weighed:

**Scope.** (A) Keycloak and logins for MLflow and the LiteLLM UI, or (B)
Keycloak plus the console on Azure. **Chosen: A.** B roughly triples the work
and pulls the console's whole Azure design into this branch; A also secures two
surfaces right away.

**LiteLLM UI sign-in.** (A) Keycloak gate, then LiteLLM's own master-key login
as well; (B) gate plus LiteLLM SSO on stock LiteLLM, which refuses SSO once its
database holds more than five user rows
(`knowledge/decisions/stay-on-oss-litellm-gateway.md`), and the console will
create one per participant; (C) gate plus SSO on a fork without that cap.
**Chosen: C**, on `uw-ssec/llmoxie-litellm` (branch `sso-enabled`: upstream
v1.108.6 with the cap removed, built without the proprietary `enterprise/`
package). This takes on the fork maintenance that decision record advised
against, deliberately; the record gets updated.

**Realm configuration.** (A) a realm file imported at startup, which only
imports a realm that doesn't exist yet, so later changes are manual and
untracked; (B) keycloak-config-cli as a job on every deploy; (C) Pulumi's
Keycloak provider, which needs the admin API reachable from the deploying
machine during the deploy that creates Keycloak. **Chosen: B, with the realm
described in the llmoxie config YAML** so it is updated in `llmaven-deploy`.

**Where the path rules live.** (A) sidecars in each app (Traefik and
oauth2-proxy inside LiteLLM's and MLflow's replicas, another in Keycloak's), or
(B) one standalone Traefik in front of everything, with every backend on
internal ingress. **Chosen: B, now, in two stages.** With A the gates are built
per app and rebuilt when Traefik moves out, which the owner expects it will have
to for the console; B builds them once and matches the prototype. B costs a
migration of every custom domain to the Traefik app.

**Callers that carry a key, not a browser.**
`llmaven infra extract --source litellm` calls `/spend/logs` with the master
key, `--source mlflow` reads MLflow through its public URL, operators may mint
keys on `/key/*`, and llmoxie-analysis may read MLflow. **Chosen:** on LiteLLM's
host, a request that carries a bearer key from `admin_allowed_ips` goes to
LiteLLM without a Keycloak login (LiteLLM still checks the key, so that path
keeps today's protection); on MLflow's host, the login also accepts a Keycloak
access token, and `infra extract` gets one from a service-account client.
Rejected: breaking `extract`; an internal-only automation port (useless from an
operator's laptop).

**Backing up `keycloak_db`.** **Chosen:** the flexible server's built-in
point-in-time backups, which already cover every database on the server. The
`pg_dump` job (one database per job) is unchanged; dumping several databases
stays with #193. Known gap: built-in backups are deleted with the server.

## Stage 1: standalone Traefik

### 1.1 The Traefik app

`create_edge_app` in `resources/traefik.py`, generalized from today's sidecar
renderer (same image pin, same content-digest env var so a policy change rolls a
new revision, same dynamic config mounted as a secret volume):

- Its own Container App, `<stack>-traefik`, external ingress, the only one in
  the stack. All public hostnames are bound to it (`edge.custom_domains`). Its
  own platform FQDN answers 404 for everything except a health path.
- At least two replicas in prod (it is now in front of everything); rate limits
  stay per replica, as today.
- Routes are by host. Each backend gets a `hostname` in its own config section
  and Traefik sends that host to the backend's internal address
  (`https://<app>.internal.<environment default domain>`). Traefik does not pass
  the public `Host` through (`passHostHeader: false`). The environment's
  internal Envoy routes by `Host`, and the public hostnames are no longer bound
  to the backends.
- The client IP is the rightmost `X-Forwarded-For` entry (`depth: 1`), kept only
  from `trusted_proxy_ips`, exactly as the sidecar does today.

### 1.2 LiteLLM's host

The same rules as today's sidecar, now on the LiteLLM hostname: exact health
paths open and not rate limited, exact public inference paths open and rate
limited, everything else only from `admin_allowed_ips`, everything unknown 404.
The renderer and its tests carry over.

### 1.3 MLflow's host

Open, as MLflow's public ingress is today. (Stage 2 puts the login on it.) An
optional `admin_allowed_ips` for MLflow's host may be added if it falls out of
the shared renderer; it is not required.

### 1.4 Backends on internal ingress

LiteLLM and MLflow get `ingress_external=False`. Their platform FQDNs stop
answering from the internet, and their `custom_domains` must be empty (a
validation error otherwise; the hostnames now live on Traefik).

- The LiteLLM sidecar stays while `edge` is off, so prod and ISS configs keep
  deploying unchanged. `edge.enabled` with `litellm.proxy.enabled: true` is a
  validation error naming the new fields (`edge.*`, `litellm.hostname`,
  `litellm.admin_allowed_ips`, `litellm.public_paths`, `litellm.health_paths`).
  The sidecar and `litellm.proxy` are removed in a follow-up after every
  environment has moved.
- `litellm.ip_security_restrictions` applies to the whole app's ingress, which
  now only Traefik reaches, so it must be empty; per-host IP rules are Traefik's
  job. Validation error otherwise.
- The `mlflow-tracking-uri` secret is built from MLflow's ingress FQDN, which is
  the internal one once its ingress is internal, so it changes with no code
  change. Operators running `infra extract --source mlflow` set the public
  MLflow hostname in their env file.
- Monitoring alerts target the apps' own metrics, which still see every request;
  the builder checks that `monitoring.py` needs no change and adds Traefik's
  restarts to the replica-restart alert.

### 1.5 Config (stage 1)

```yaml
edge:
  enabled: true
  image: docker.io/library/traefik:v3.7.x@sha256:<digest>
  min_replicas: 2
  custom_domains: # every public hostname, bound to the Traefik app
    - { name: ai.example.org, certificate_name: ... }
    - { name: mlflow.example.org, certificate_name: ... }
  trusted_proxy_ips: null # defaults to the Container Apps subnet
  rate_limit_average: 50
  rate_limit_burst: 100
litellm:
  hostname: ai.example.org
  admin_allowed_ips: [203.0.113.0/24]
  public_paths: [...] # defaults as today
  health_paths: [...]
mlflow:
  hostname: mlflow.example.org
```

Validation: every backend `hostname` is in `edge.custom_domains` and appears
once; with `edge.enabled`, backends have no `custom_domains` and LiteLLM has no
`ip_security_restrictions`; without `edge.enabled` the stack deploys exactly as
it does today, so existing configs keep working until each environment is moved.

### 1.6 Stage 1 rollout

Per environment, starting with a new `staging` stack (new config in
`llmaven-deploy`, its own resource group and state; created by the owner):

1. Deploy with `edge.enabled: true`. On a stack with existing hostnames this is
   where they move: the deploy removes each hostname from its old app and lists
   it on Traefik. Then, per hostname, bind it to Traefik by hand
   (`az containerapp hostname add` / `bind`; the builder checks whether the
   existing managed certificate can be reused in the same environment or a new
   one must be issued). Each hostname is down from its removal until its bind.
   Plan the window; announce it on ISS and prod.
2. On staging, run the two client-IP checks: the Envoy peer is inside
   `trusted_proxy_ips`, and a workload in the environment cannot reach Traefik's
   port directly and forge an allowlisted `X-Forwarded-For`. Also check
   streaming responses through Traefik, and that LiteLLM's and MLflow's platform
   FQDNs no longer answer from outside.
3. Anyone still calling LiteLLM at its platform FQDN breaks at this step; find
   and move them before ISS and prod.

## Stage 2: Keycloak and the logins

### 2.1 Keycloak image

`docker/dockerfiles/keycloak.dockerfile`:
`FROM quay.io/keycloak/keycloak:<26.x>@sha256:<digest>` (the current 26.x
release when built, by tag and multi-arch digest), then
`kc.sh build --db=postgres --health-enabled=true --metrics-enabled=true`.
`.github/workflows/build-services.yml` builds and publishes it as
`ghcr.io/uw-ssec/llmoxie-keycloak`. `tests/test_platform_scope.py` pins compose
services and the CLI, not dockerfiles; check it stays green.

### 2.2 Keycloak app

`create_keycloak_app` in a new `resources/keycloak.py`, internal ingress:

- `start --optimized`, one replica (`min = max = 1`, `--cache=local`), never
  scaled to zero: every login and, later, the console verify tokens against it.
- `KC_DB_URL` for `keycloak_db` (below), user and password as Key Vault refs.
- `KC_HOSTNAME=https://<keycloak.hostname>` fixes the issuer;
  `KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true` lets services in the environment use
  the internal address; `KC_PROXY_HEADERS=xforwarded`; `KC_HTTP_ENABLED=true`.
- `KC_BOOTSTRAP_ADMIN_USERNAME`/`PASSWORD` from Key Vault. The bootstrap admin
  is in the `master` realm, used by keycloak-config-cli and for break-glass.
- Startup probe on the management port (9000, `/health/ready`) with a long
  budget (first boot creates the schema).

On Keycloak's host Traefik exposes `PathPrefix(/realms/)` and
`PathPrefix(/resources/)` to everyone (Keycloak's own guidance; these prefixes
hold only what Keycloak means to be public), `/admin/` only from
`keycloak.admin_allowed_ips` (empty blocks it for everyone), everything
else 404. Services in the environment (the config job, the logins' token
redemption, later the console broker) use the internal address.

### 2.3 Database and backup

`keycloak_db` is added to the databases on the existing flexible server when
`keycloak.enabled`, with the same admin credentials and connection-string secret
pattern as `litellm_db` and `mlflow_db` (a least-privilege role is the same open
gap those have, #193). It is backed up by the server's built-in point-in-time
backups; the builder confirms the configured retention and records it. The
`pg_dump` job is not changed.

### 2.4 Secrets

Generated by Pulumi (`pulumi_random.RandomPassword`), stored in Key Vault
through `SecretsManager`, never in YAML:

| Key Vault secret                         | Used by                                         |
| ---------------------------------------- | ----------------------------------------------- |
| `keycloak-admin-password`                | Keycloak (bootstrap admin), the config job      |
| connection string for `keycloak_db`      | Keycloak                                        |
| `keycloak-client-mlflow-gate`            | config job (sets it), MLflow's oauth2-proxy     |
| `keycloak-client-litellm-gate`           | config job, LiteLLM's oauth2-proxy              |
| `keycloak-client-litellm`                | config job, LiteLLM (`GENERIC_CLIENT_SECRET`)   |
| `keycloak-client-llmaven-cli`            | config job; operators copy it to their env file |
| `oauth2-proxy-cookie-mlflow`, `-litellm` | the two oauth2-proxy apps                       |

Secrets the operator supplies later (a CILogon client secret, for example) come
in through the existing `LLMAVEN_SECRETS_*` env-file mechanism and are named in
`keycloak.realm.secret_refs`.

### 2.5 Realm configuration

```yaml
keycloak:
  enabled: true
  image: ghcr.io/uw-ssec/llmoxie-keycloak:<tag>
  hostname: auth.example.org # the issuer; listed in edge.custom_domains
  admin_allowed_ips: [203.0.113.0/24] # who may open /admin/
  config_cli_image: docker.io/adorsys/keycloak-config-cli:<ver>@sha256:<digest>
  realm:
    name: llmoxie # permanent: it is part of the issuer
    display_name: LLMoxie
    secret_refs: {} # env var name -> Key Vault secret, for $(env:...) in overrides
    overrides: {} # a keycloak-config-cli realm fragment, merged last
mlflow:
  login: { enabled: true, role: mlflow-user }
litellm:
  login: { enabled: true, role: litellm-admin }
```

**Rendering.** The Pulumi program renders one keycloak-config-cli realm
document: the realm (name, display name, registration off, verified email
required, brute-force protection on), the realm roles the enabled logins name,
and these clients:

| Client         | Kind                                      | Redirect URI                             |
| -------------- | ----------------------------------------- | ---------------------------------------- |
| `mlflow-gate`  | confidential, standard flow, PKCE S256    | `https://<mlflow host>/oauth2/callback`  |
| `litellm-gate` | confidential, standard flow, PKCE S256    | `https://<litellm host>/oauth2/callback` |
| `litellm`      | confidential, standard flow (LiteLLM SSO) | `https://<litellm host>/sso/callback`    |
| `llmaven-cli`  | confidential, service account only        | none                                     |

Each login client gets a realm-roles mapper so the role is in its tokens.
`llmaven-cli`'s service account holds `mlflow-user`, and an audience mapper adds
`mlflow-gate` to its access tokens so MLflow's login accepts them. Client
secrets are keycloak-config-cli variables
(`$(env:KC_CLIENT_SECRET_MLFLOW_GATE)`) that reach the job as Key Vault refs, so
the rendered document holds none. `realm.overrides` is deep-merged last (named
lists such as clients, roles and identity providers merge by their key, not by
index), so an environment can add anything keycloak-config-cli supports without
a code change.

**Applying it.** A Container Apps Job, manual trigger, running
keycloak-config-cli against Keycloak's internal address as the bootstrap admin,
the rendered document mounted as a secret volume (as LiteLLM's config is,
`knowledge/architecture/litellm-config-and-logger-mounted-as-secrets.md`):

- `IMPORT_VARSUBSTITUTION_ENABLED=true` for the secrets.
- `IMPORT_MANAGED_CLIENT=no-delete`, and the same for roles, identity providers
  and the other managed kinds: anything in Keycloak but not in the document,
  such as the console's per-organization clients, is left alone. Removing a
  client is a documented manual step.
- `IMPORT_REMOTESTATE_ENABLED=true`.

`llmaven infra deploy`, after a successful `pulumi up` that includes Keycloak,
starts one execution of the job and waits for it, failing the deploy if it fails
(the realm then stays as it was, and re-running deploy retries). A change to the
document or the job image changes a content digest in the job template, so
`pulumi up` shows it. `--preview` does not run it.

### 2.6 The logins (oauth2-proxy)

Two oauth2-proxy Container Apps (image pinned by digest), internal ingress, one
per protected host, as in the prototype: `<stack>-mlflow-auth` and
`<stack>-litellm-auth`. Each runs `keycloak-oidc` with its client, PKCE S256,
the allowed role, secure cookies scoped to its host, its cookie secret from Key
Vault, explicit endpoints (browser-facing authorization URL on the public
hostname; token and JWKS on Keycloak's internal address), and answers Traefik's
`ForwardAuth` (`--reverse-proxy`, `--upstream=static://202`). Traefik routes
`/oauth2/*` on each host to that host's oauth2-proxy.

**MLflow's host:** every route passes `ForwardAuth`. A browser without a session
is sent to Keycloak; a session without `mlflow-user` is refused. oauth2-proxy
also accepts a bearer access token issued by the realm with audience
`mlflow-gate` and the role (`--skip-jwt-bearer-tokens`), which is how
`infra extract` and other automation get in. The builder confirms the role check
applies to bearer tokens too, not only to sessions.

**LiteLLM's host:** public inference and health paths stay as stage 1 left them,
with no login. Every other route needs, in behavior:

- a browser request with no `Authorization` header: a Keycloak session with
  `litellm-admin`, from any IP;
- a request with a valid session: passes from any IP (LiteLLM's UI calls its API
  with a bearer key and the session cookie);
- a request carrying a bearer key and no session: passes to LiteLLM only from
  `admin_allowed_ips` (LiteLLM then checks the key), and is refused elsewhere.

How Traefik and oauth2-proxy express that (separate routers on the presence of
`Authorization`, oauth2-proxy's `trusted_ips`, two `ForwardAuth` endpoints) is
the builder's choice; the tests below pin the behavior, including that LiteLLM's
own master-key login form is never reachable without a Keycloak session.

### 2.7 LiteLLM on the fork, with SSO

**Image.** `docker/dockerfiles/litellm.dockerfile` changes its base from
`ghcr.io/berriai/litellm:v1.108.6@sha256:…` to
`ghcr.io/uw-ssec/llmoxie-litellm-fork:v1.108.6@sha256:<digest>`. It keeps the
logging packages it adds but **not** its `litellm==1.108.6` re-pin from PyPI,
which would put upstream's package back over the fork's and bring the five-user
cap back; the fork image already carries MLflow support. A test fails if the
re-pin returns, and the image build checks that the installed `litellm` lacks
the cap (`_raise_if_sso_exceeds_free_user_limit`). Whether the `ensurepip` step
(`knowledge/facts/litellm-image-install-quirks.md`) is still needed on the
fork's base is checked, not assumed.

Before that, the fork's "Publish image" workflow must have pushed the tag (so
far it has only run on PRs since the `-fork` rename), and the digest is checked
like any LiteLLM pin: same upstream version, Prisma migrations unchanged from
upstream v1.108.6, and both architectures if the fork publishes both (it builds
amd64 only today; the decision record says so if that stays).

**SSO.** LiteLLM gets `PROXY_BASE_URL` (its public hostname),
`GENERIC_CLIENT_ID=litellm`, `GENERIC_CLIENT_SECRET` (Key Vault), the
authorization endpoint on the public hostname and the token and userinfo
endpoints on Keycloak's internal address, `GENERIC_SCOPE=openid email profile`,
and the id, email and display-name attributes. Everyone reaching `/sso/*`
already holds `litellm-admin`, so LiteLLM should make them proxy admins by
mapping the role to the claim v1.108.6 reads for a role
(`GENERIC_USER_ROLE_ATTRIBUTE` or equivalent), falling back to `PROXY_ADMIN_ID`
for one named admin if it has none.

### 2.8 `llmaven infra extract`

`--source litellm` is unchanged (master key, from an allowlisted IP).
`--source mlflow` gets a Keycloak access token with the client-credentials grant
for `llmaven-cli` (token URL and secret from new `LLMAVEN_SECRETS_KEYCLOAK_*`
env-file entries, documented) and passes it to MLflow as
`MLFLOW_TRACKING_TOKEN`, against MLflow's public hostname. Without those entries
it behaves as today, so it still works against stacks where MLflow has no login.

### 2.9 Stage 2 validation

- `keycloak.hostname` is in `edge.custom_domains`.
- Any `login.enabled` requires `keycloak.enabled` and `edge.enabled`.
- `realm.name` must not change for an existing stack (it is in the issuer); warn
  when it differs from the deployed output.
- Images named by digest.
- `realm.overrides` must not redefine the clients the stack renders.

### 2.10 Stage 2 rollout

Per environment, staging first, with a recent `pg_dump` of `litellm_db`:

1. Publish the fork image; pin its digest; release.
2. Deploy with `keycloak.enabled: true`, logins off, and Keycloak's hostname
   added to `edge.custom_domains` (bind its certificate by hand, as in stage 1).
   Check the issuer at
   `https://<host>/realms/<name>/.well-known/openid-configuration`.
3. Create the first admins in the realm (admin console from an allowlisted IP)
   and grant `mlflow-user` and `litellm-admin`. Copy the `llmaven-cli` secret
   into operators' env files.
4. Turn on `mlflow.login` and `litellm.login`. Deploy. Run the checks below.

## Verification

- Unit tests (`tests/infrastructure/`):
  - stage 1: the edge renderer per host (no prefix route on LiteLLM, unknown
    paths 404, XFF from trusted peers only), backends get internal ingress,
    hostname and migration validation (`litellm.proxy` refused with a pointer),
    the tracking URI is internal, and a config without `edge` renders exactly
    today's templates;
  - stage 2: schema defaults and validation; realm rendering (clients, roles,
    mappers, variables, overrides merging by key, no secret values in the
    document); Keycloak's host rules (`/admin/` allowlisted); the job's digest
    changes with the document; the LiteLLM Dockerfile has no `litellm==` re-pin.
- Locally, before any deploy: Traefik with the rendered config against stand-in
  backends for the LiteLLM-host behaviors in 2.6; Keycloak (the built image)
  plus keycloak-config-cli applying a rendered document, a second run changing
  nothing and leaving an extra client in place.
- On staging (owner-approved deploys), stage 1: the client-IP checks, streaming,
  platform FQDNs closed, existing API keys and the admin allowlist behave as
  before, LiteLLM traces still reach MLflow. Stage 2: MLflow sends a browser to
  Keycloak and refuses a user without `mlflow-user`;
  `infra extract --source mlflow` works with a token; LiteLLM's public paths
  answer with an API key and no cookie; `/ui/` sends a browser to Keycloak,
  refuses a user without `litellm-admin`, and signs an admin into the UI with no
  second prompt; a bearer key on a management route works from an allowlisted IP
  and not from elsewhere; LiteLLM's login form is unreachable without a session;
  Keycloak's `/admin/` is refused from a non-allowlisted IP.
- `pixi run -e llmaven verify`.

## Records to update

- `knowledge/decisions/stay-on-oss-litellm-gateway.md`: SSO runs on the uw-ssec
  fork.
- `knowledge/decisions/litellm-image-digest-pin-and-one-way-upgrade.md`: the
  pinned image is the fork's.
- `knowledge/requirements/traefik-sidecar-allowlist-and-client-ip.md`: the
  sidecar is replaced by a standalone Traefik with internal-only backends, and
  the staging results.
- New decision: Keycloak is the identity provider, realm in the config YAML
  applied by keycloak-config-cli, `keycloak_db` on point-in-time backups, and
  why (replaces the Entra plan).
- `.agents/rules/infrastructure.md`: the edge, Keycloak, the logins, the
  rollouts.

## Identity providers later

CILogon is added per environment as an `identityProviders` entry (OIDC) in
`realm.overrides`, its client secret named in `realm.secret_refs`. People who
signed in locally can link their CILogon login to their Keycloak user, so their
`sub`, and their console identity, does not change. Whether CILogon's email
counts as verified, and whether local passwords are then turned off, are
decisions for that change.

## Left to the builder

- Exact versions and digests: Traefik, Keycloak 26.x, keycloak-config-cli to
  match it, oauth2-proxy.
- Whether azure-native 3.29 covers internal ingress addressing, Container Apps
  Jobs with secret volumes, and moving a hostname with its managed certificate
  between apps in one environment as assumed; if not, say so before working
  around it.
- The Traefik/oauth2-proxy mechanics for the LiteLLM-host behaviors in 2.6.
- How LiteLLM v1.108.6 maps an SSO claim to a proxy role.
- Resource sizes (Keycloak from 1 CPU / 2 Gi; Traefik and oauth2-proxy small).
- How `infra deploy` runs and waits for the job (azure-native has no "run job"
  call; `az containerapp job start` plus polling, with the configured
  subscription per `knowledge/bugs/azure-subscription-and-expired-login.md`).
- Whether stage 1 and stage 2 go to `main` as one PR or two (two is the natural
  cut, matching the rollouts).
