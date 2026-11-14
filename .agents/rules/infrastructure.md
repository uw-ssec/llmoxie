# Infrastructure (Pulumi on Azure)

**Load when:** working on `src/llmaven/infrastructure/`,
`src/llmaven/infrastructure_backup/` or `src/llmaven/deployment/`, or running
any `llmaven infra` / `llmaven backup-infra` command.

## Safety First

`deploy`, `destroy`, `refresh`, `cancel` and `backup-infra deploy` change real
Azure resources or Pulumi state. **Get explicit human approval before running
any of them**, including `deploy --preview`. `--preview` skips the Pulumi
update, but first `initialize_azure_infra()` (`deployment/deploy.py`) creates
the resource group and Pulumi state storage if the config doesn't name existing
ones. `deploy --expect-no-changes` refuses to run when those aren't set.

## Prerequisites

- Pulumi CLI: `pixi run -e llmaven install-pulumi`
- Azure CLI authenticated: `az login`
- A config file, `llmaven-config.yaml` by default. It is gitignored and holds
  secrets; never commit it. Real environment configs live in the private
  `uw-ssec/llmaven-deploy` repository.

## Commands

Run them as `pixi run -e llmaven llmaven infra <command>`. `--config/-c` selects
the config file.

| Command    | What it does                                                                             |
| ---------- | ---------------------------------------------------------------------------------------- |
| `init`     | Writes a config with defaults (`-e dev\|staging\|prod`, `-o <path>`, `--no-interactive`) |
| `validate` | Checks the config (`--strict` fails on warnings, `--env-file` for secrets)               |
| `deploy`   | Deploys (`--preview`, `--yes`, `--expect-no-changes`, `--env-file`)                      |
| `status`   | Shows the deployed stack's status                                                        |
| `refresh`  | Refreshes Pulumi state from Azure (`--yes`)                                              |
| `cancel`   | Cancels a stuck Pulumi update                                                            |
| `destroy`  | Tears down **all** resources (`--yes`)                                                   |
| `extract`  | Downloads LiteLLM spend logs to a zip (`--source`, `--out`)                              |

The separate backup stack has its own commands: `llmaven backup-infra deploy`
and `llmaven backup-infra output`.

## Key Files

| Path                                    | Purpose                                      |
| --------------------------------------- | -------------------------------------------- |
| `src/llmaven/infrastructure/main.py`    | Pulumi program for the main stack            |
| `src/llmaven/infrastructure/resources/` | Container apps, database, Key Vault, storage |
| `src/llmaven/infrastructure/config/`    | Config models loaded from the YAML           |
| `src/llmaven/infrastructure_backup/`    | Pulumi program for the backup stack          |
| `src/llmaven/deployment/`               | `init`, `validate`, `deploy` logic           |

## Deployed Resources

- Resource group, virtual network and subnets, private DNS zone
- Container Apps managed environment, with the LiteLLM and MLflow container apps
  and the scheduled backup job
- Azure Database for PostgreSQL flexible server and its databases
- Storage account and blob containers, with lifecycle management
- Key Vault for secrets, plus a user-assigned managed identity
- Log Analytics workspace
- Optional (`foundry.enabled`): Azure AI Foundry `AIServices` account and its
  model deployments (`resources/foundry.py`). Its network ACL allows only the
  Container Apps subnet through a `Microsoft.CognitiveServices` service
  endpoint, and the stack writes the `azure-api-*` Key Vault secrets.
- Azure Managed Redis for LiteLLM (when `redis.enabled`), behind a private
  endpoint in `private-endpoints-subnet` with a `privatelink.redis.azure.net`
  private DNS zone; public access is disabled

The container images come from GHCR. See
[repository-map.md](repository-map.md#deployment) for how they're built.

## Redis for LiteLLM

LiteLLM keeps rate limits, budgets and router state per replica unless the
replicas share a Redis. The program therefore requires Redis whenever
`litellm.max_replicas > 1`: `redis.enabled` defaults to true then, and setting
it to false is a config error. With one replica Redis is off by default.

- The resource is Azure Managed Redis (`azure_native.redisenterprise`), not
  Azure Cache for Redis, which Microsoft is retiring.
- `redis.clustering_policy` defaults to `EnterpriseCluster`, so LiteLLM sees one
  endpoint on port 10000 (TLS). It can't be changed without recreating the
  database, which drops its data. `OSSCluster` is rejected because it needs a
  cluster-aware client.
- `docker/config.yaml` stays Redis-free. At deploy time, when Redis is enabled,
  the program adds `router_settings.redis_*` and
  `litellm_settings.force_redis_hash_tag_grouping: true` to the mounted copy.
  The flag keeps LiteLLM's rate-limit Lua scripts within one hash slot; without
  it they fail with CROSSSLOT and LiteLLM falls back to per-replica counters.
- `redis-host`, `redis-port` and `redis-password` live in Key Vault and reach
  LiteLLM as secret refs; `REDIS_SSL=true` is a plain env var.
- `redis.high_availability`, when omitted, is true in prod and false elsewhere,
  so an existing prod config without a `redis` section gets two nodes.
- LiteLLM depends on the private DNS zone group, so a new revision doesn't start
  before the Redis host name resolves privately in the VNet.
- Turning on Redis for an existing stack is additive, but it changes the LiteLLM
  revision, so `deploy --expect-no-changes` will report changes once.

**Rotating the Redis key:** regenerate the primary key
(`az redisenterprise database regenerate-key --cluster-name <cluster> --resource-group <rg> --key-type Primary`),
then run `llmaven infra deploy`. The deploy reads the new key and updates the
`redis-password` secret. LiteLLM picks it up in its next revision: deploys
create one by default, but if `litellm.refresh_trigger` is pinned, restart the
active revision (`az containerapp revision restart`). Until then LiteLLM can't
reach Redis, so rotate in a quiet window.

## Traefik proxy for LiteLLM

The edge (next section) replaces this sidecar. It stays for stacks that have not
moved to the edge and will be removed in a follow-up once every stack has.

`litellm.proxy.enabled` (off by default) adds a Traefik sidecar, built in
`resources/traefik.py`. Ingress `targetPort` moves to the proxy port, and
LiteLLM is started with `--host 127.0.0.1`. LiteLLM reads `--host` or `HOST`;
the `LITELLM_HOST` env var has no effect.

- Routing is an allowlist of exact paths. Never add `PathPrefix` routes for
  `/v1/` or `/health/`: LiteLLM 1.106.6 serves management routes under both.
- The client IP comes from `ipStrategy.depth: 1`, the rightmost
  `X-Forwarded-For` entry, which Envoy appends. Both the allowlist and the rate
  limiter use it. Traefik deletes X-Forwarded-* from peers outside
  `forwardedHeaders.trustedIPs` (default: the Container Apps subnet).
- Platform probes can't reach a localhost-only LiteLLM, so with the proxy on,
  LiteLLM's probes are HTTP GETs of the first `health_paths` entry on the proxy
  port. With the proxy off the probes are unchanged.
- The sidecar mounts only the Traefik config secret. The template's total CPU
  and memory must be a valid Consumption pair, and the schema checks this.
- The dynamic config is an app-level secret, and Container Apps does not restart
  revisions when secrets change. The SHA-256 of that config plus the sidecar's
  static settings (args, image, cpu, memory) is set as `TRAEFIK_POLICY_SHA256`
  on the sidecar, and a pinned `revision_suffix` gets `-p<digest[:8]>`. Any
  proxy change, such as revoking an admin IP, toggling `log_forwarded_for` or
  narrowing `trusted_proxy_ips`, therefore rolls a new revision under a new
  name.
- `ip_security_restrictions` must be IPv4 and use a single action, because
  Container Apps rejects mixed Allow/Deny lists.
- Before prod, pass the README staging gates. Step 3 confirms the Envoy peer is
  inside `trusted_proxy_ips`, using `log_forwarded_for`. Step 4 confirms that
  another workload calling the replica's proxy port with a forged allowlisted
  XFF is refused.
- With the proxy disabled the template is unchanged, so
  `deploy --expect-no-changes` still passes.

## Traefik edge in front of the stack

`edge.enabled` (off by default) adds a standalone Traefik Container App,
`<stack>-traefik`, built by `create_edge_app` in `resources/helpers.py` from the
renderer in `resources/traefik.py`. With it on:

- Traefik is the only app with external ingress. All public hostnames
  (`edge.custom_domains`) are bound to it. Its own platform FQDN answers 404 for
  everything. Health is on the separate ping port (`edge.ping_port`), which the
  platform probes use.
- LiteLLM and MLflow move to internal ingress, so their platform FQDNs stop
  answering from the internet. This removes the platform-FQDN bypass the sidecar
  could not close.
- Routing is by host. Each backend has a `hostname`, and Traefik sends that host
  to the backend's internal FQDN. It passes the internal FQDN as `Host`
  (`passHostHeader: false`), because the environment's internal Envoy routes by
  `Host`. A request with no `Host` gets 400 (HTTP/1.1) or 404 (HTTP/1.0), and an
  unknown host gets 404, so nothing reaches a backend without a configured host.
- LiteLLM's host keeps the sidecar's policy: exact health paths open, exact
  public paths open and rate limited, everything else only from
  `litellm.admin_allowed_ips`. MLflow's host is open.
- `mlflow-tracking-uri` becomes MLflow's internal address automatically. If you
  run `llmaven infra extract --source mlflow`, set the public MLflow hostname in
  your env file, plus `LLMAVEN_SECRETS_KEYCLOAK_TOKEN_URL` and
  `LLMAVEN_SECRETS_KEYCLOAK_CLI_CLIENT_SECRET` (both or neither) to pass the
  login.

```yaml
edge:
  enabled: true
  image: docker.io/library/traefik:v3.7.x@sha256:<digest>
  min_replicas: 2
  custom_domains: # every public hostname, bound to the Traefik app
    - { name: ai.example.org, certificate_name: ... }
    - { name: mlflow.example.org, certificate_name: ... }
  trusted_proxy_ips: [100.100.0.0/17] # required, no default; see below
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

**Client IP and trust.** Traefik keeps `X-Forwarded-For` only from peers in
`edge.trusted_proxy_ips`, which is required when the edge is on and has no
default (a missing or empty value is a config error, issue #229). The admin
allowlist and rate limiter read the rightmost entry of the header as received
(`depth: 1`). That is safe only because every legitimate peer is the Container
Apps Envoy, which appends the real client IP. Any other workload that can reach
Traefik's port directly from inside the trusted range can forge an allowlisted
IP. This was observed with the real binary: a forged
`X-Forwarded-For: 203.0.113.7` from a trusted peer reached the backend (200),
while the same header from an untrusted peer got 403. Don't widen
`trusted_proxy_ips`.

**What to set.** The Envoy peer range is not `networking.container_apps_subnet`.
In the workload-profile environment on ISS (#229), Traefik's access log showed
Envoy connecting from `100.100.0.0/17` (`ClientAddr` `100.100.0.86` and
`100.100.0.246`), while replicas sat in `100.100.192.0/19`. With
`trusted_proxy_ips: [100.100.0.0/17]` admin paths returned 200 from allowlisted
IPs, and a forged allowlisted `X-Forwarded-For` sent from one replica straight
to another was refused (403). Microsoft reserves `100.100.0.0/17`,
`100.100.128.0/19`, `100.100.160.0/19` and `100.100.192.0/19` there, but doesn't
say which block Envoy uses, so the split is observed, not guaranteed. Never
include the replica range. Consumption-only environments are untested and may
differ. Confirm the peer range on staging with `edge.log_forwarded_for: true`.
The sidecar (`litellm.proxy`) still defaults to the subnet, tracked in #229.

**Validation errors** (all raised when the config loads):

- `edge.enabled and litellm.proxy.enabled are both true`: set
  `litellm.proxy.enabled: false` and move its policy to `litellm.hostname` and
  `litellm.admin_allowed_ips`. Public and health paths move to
  `litellm.public_paths` and `litellm.health_paths`, and `trusted_proxy_ips`,
  `rate_limit_average` and `rate_limit_burst` move to `edge.*`.
- `edge.trusted_proxy_ips is required when the edge is on`: set it to the Envoy
  peer range (see "What to set" above), never the replica range.
- `edge.revision_suffix ... is too long`: shorten it to the stated maximum.
- `<app>.hostname is not set`, or
  `<app>.hostname ... is not listed in edge.custom_domains`: every enabled
  backend needs a hostname that is also in `edge.custom_domains`.
- `edge.custom_domains lists [...] more than once`, and
  `litellm.hostname and mlflow.hostname are both ...`: each hostname appears
  once and the two backends differ.
- `<app>.custom_domains must be empty when the edge is on`: move those hostnames
  to `edge.custom_domains`.
- `litellm.ip_security_restrictions must be empty when the edge is on`: use
  `litellm.admin_allowed_ips`.
- `litellm.health_paths must not be empty when the edge is on`, and
  `edge.port and edge.ping_port must differ`.
- `edge.enabled needs at least one enabled backend`.

`llmaven infra validate` warns when a prod config has `edge.min_replicas`
below 2. Rate limits stay per replica.

`llmaven infra validate` also warns when `litellm.hostname`,
`litellm.admin_allowed_ips` or `mlflow.hostname` is set while `edge.enabled` is
false. They have no effect then, so turning the edge off (or never turning it
on) leaves the admin surface unrestricted unless the sidecar or
`litellm.ip_security_restrictions` does it. With the edge on, `edge.env_vars`
and `edge.key_vault_secret_refs` must be empty (the edge ignores them),
`edge.min_replicas` must be at least 1, `edge.trusted_proxy_ips` must be set,
and a pinned `edge.revision_suffix` must fit the whole revision name,
`<app>--<suffix>-p<8 hex>` (at most 54 characters). `<app>` is
`<project.name>-<project.environment>-traefik-<env>`, and the error states the
maximum suffix length (#228). With the edge on, LiteLLM gets
`PROXY_BASE_URL=https://<litellm.hostname>` unless `litellm.env_vars` sets it,
because Traefik sends LiteLLM its internal FQDN as `Host` and LiteLLM would
otherwise redirect UI logins there.

**Trust boundary.** Traefik's allowlist and rate limits apply only to traffic
that passes through Traefik. With the edge on, LiteLLM and MLflow are reachable
from any workload in the Container Apps environment (and the VNet) at their
internal addresses without passing either. LiteLLM still requires its key and
MLflow has no login. The sidecar guarded in-environment callers too; the edge
does not. Whether to add in-replica protection is an open owner decision.

**Pin `edge.refresh_trigger`.** Unpinned, it defaults to the deploy timestamp
and rolls a new Traefik revision on every deploy. That fails
`--expect-no-changes` and can cut long streams on the single entry point. A
pinned `litellm.revision_suffix` must change in the same deploy that removes the
sidecar, because the template changes.

**Rollout.** Deploys and hostname binds change live infrastructure and are the
owner's to run; nothing here is run by an agent. Per environment, staging first:

0. Before the first deploy, find everyone calling LiteLLM or MLflow at a
   platform FQDN and move them to the public hostnames. They break at the deploy
   in step 2, which flips both apps to internal ingress.
1. Staging must rehearse what ISS and prod do. First deploy staging in the prod
   shape: edge off, sidecar on, hostnames and certificates bound on the
   backends. Then turn the edge on. Behind the edge MLflow receives its internal
   FQDN as `Host`, and MLflow 3.5 and later answers 403 for a `Host` outside
   `MLFLOW_SERVER_ALLOWED_HOSTS` (or `--allowed-hosts`). This repo sets neither:
   `docker/dockerfiles/mlflow.dockerfile` is `mlflow server` on
   `ghcr.io/mlflow/mlflow:v3.6.0`, and `MLflowConfig.env_vars` defaults to
   `MLFLOW_HOST=0.0.0.0` only (compose passes `--allowed-hosts "*"`, the
   deployed app does not). So MLflow uses its default host policy, and whether
   that accepts `<app>.internal.<domain>` is unverified; MLflow 3.10's default
   (localhost and private IPs) would not. That `Host` only exists once the edge
   is on, so the staging flip is the test: open the MLflow hostname through the
   edge and send one LiteLLM request (step 4). If MLflow answers 403, set
   `MLFLOW_SERVER_ALLOWED_HOSTS` in `mlflow.env_vars` on staging, and on ISS and
   prod before their flip. Setting `mlflow.env_vars` replaces the default
   mapping, so keep `MLFLOW_HOST: "0.0.0.0"` in it (without it MLflow listens on
   localhost only and is unreachable). While the edge is off, the list must also
   cover the hosts MLflow answers to today (its platform FQDN and public
   hostname), or setting it early breaks current callers.
2. Deploy with `edge.enabled: true`. The deploy moves each hostname from its old
   app to Traefik and binds it (SNI) to the existing managed certificate named
   in `edge.custom_domains`, so that certificate must already exist in the
   environment. Do the manual `az containerapp hostname add` and
   `az containerapp hostname bind` (see
   `knowledge/facts/custom-domains-declarative-certificate-manual.md`) only for
   a hostname whose managed certificate doesn't exist yet. Whether Azure accepts
   a hostname on Traefik in the same deploy that removes it from the old app is
   unverified and is checked on staging first. If it refuses, re-running the
   deploy is the expected fix, but that is also unverified. Each hostname is
   down from its removal until it is bound, so plan the window and announce it
   on ISS and prod.
3. DNS. Each hostname's CNAME points at the old app's platform FQDN. Repoint it
   to the Traefik app's FQDN (`edge_url`), or confirm on staging that Azure
   accepts the bind and later renews the managed certificate with the old
   target. Both are unverified; check on staging.
4. After the deploy, confirm LiteLLM's revision picked up the internal tracking
   URI. If `litellm.refresh_trigger` is pinned and no new revision rolled,
   restart the active revision. Then send a request and confirm its trace
   arrives in MLflow.
5. On staging, run both client-IP checks. The Envoy peer must be inside
   `trusted_proxy_ips`, and no other workload in the environment may be able to
   reach Traefik's port directly and forge an allowlisted `X-Forwarded-For`.
   Also check streaming responses through Traefik, and that LiteLLM's and
   MLflow's platform FQDNs no longer answer from outside. Also check that the
   LiteLLM UI login lands on the public host, and that Traefik's TLS to
   `https://<app>.internal.<domain>` is trusted with the real certificate (the
   offline tests used plain-HTTP stubs).
6. Repeat for ISS and prod once staging passes.

**Rollback takes two deploys.** Pulumi creates and updates before it deletes, so
a single deploy cannot give the backends hostnames Traefik still holds.

1. Deploy with `edge.enabled: false`, the backends' `custom_domains` still
   empty, and `litellm.proxy.enabled: true` if the sidecar was on before. This
   removes Traefik (and its hostname bindings) and returns the backends to
   external ingress. Restore the sidecar in this deploy, not the next: without
   it LiteLLM's admin surface is open on its platform FQDN until deploy 2.
2. Deploy again with the backends' `custom_domains` restored.

Rehearse both on staging before the first prod enable. Expect the hostnames to
be down between the two deploys.

Without `edge.enabled` the stack deploys exactly as before. Design:
`docs/superpowers/specs/2026-11-13-keycloak-azure-design.md`.

## Keycloak and the logins

`keycloak.enabled` (off by default, and it needs `edge.enabled`) adds Keycloak
behind the edge, a Container Apps Job that applies the realm from the YAML, and
an oauth2-proxy login app in front of each of the MLflow and LiteLLM UIs that
turns its login on. Design:
`docs/superpowers/specs/2026-11-13-keycloak-azure-design.md`, stage 2. Source:
`resources/keycloak.py` (apps and job), `resources/keycloak_realm.py` (realm
document), `resources/traefik.py` (login routes).

- **Keycloak** is a Container App with internal ingress, on its own public
  hostname (`keycloak.hostname`, which must be in `edge.custom_domains`). It
  runs Keycloak 26.5.5 from `docker/dockerfiles/keycloak.dockerfile`: optimized
  (`start --optimized`), `--cache=local`, one replica. With the local cache
  there is no clustering, and the real-container run showed no JGroups lines.
  Its database is `keycloak_db` on the stack's Postgres server.
- **Edge routes on the Keycloak host**: `/realms/` and `/resources/` are open
  (rate limited). `/admin/` is allowed only from `keycloak.admin_allowed_ips`
  (empty closes it to everyone; `llmaven infra validate` warns). Everything else
  there is 404.
- **Login apps** (`mlflow.login`, `litellm.login`, each `enabled` and `role`):
  oauth2-proxy v7.15.6 apps behind the edge. MLflow's default role is
  `mlflow-user`, LiteLLM's is `litellm-admin`. A request with the login cookie
  is sent through ForwardAuth from any IP. On MLflow's host a bearer token from
  `llmaven-cli` also passes oauth2-proxy's check. On LiteLLM's host a bearer key
  with no session passes only from `litellm.admin_allowed_ips`, as before. The
  `/oauth2/` routes on both hosts are rate limited like the other public routes.
  LiteLLM's exact public inference and health paths are routed before any login
  check, so a key in any header still works there. On every other path a request
  needs a Keycloak session unless it carries `Authorization: Bearer` from an
  allowlisted IP. Requests whose path contains `%`, a backslash, a NUL or `;`,
  and anything under the LiteLLM UI and login paths (`LITELLM_UI_PATHS` in
  `resources/traefik.py`), always need a session, from any IP. So admin scripts
  that use encoded paths (for example `/v1/models/openai%2Fgpt-4o`, or Bedrock
  ARNs with `%3A`) or other key headers (`x-litellm-api-key`, `api-key`,
  `x-api-key`, a lowercase `bearer`) on a non-public path now get sent to the
  login. Change them to a plain path and `Authorization: Bearer`, or run them
  from a session.
- **Trust boundary.** Keycloak and the two login apps, like LiteLLM and MLflow,
  are internal-ingress apps. Any workload in the Container Apps environment can
  reach them without passing Traefik. This is the same open decision as in
  "Traefik edge in front of the stack".

```yaml
keycloak:
  enabled: true
  hostname: auth.example.org # in edge.custom_domains; differs from the apps'
  admin_allowed_ips: [203.0.113.0/24]
  realm:
    name: llmoxie # permanent, see below
    secret_refs: {} # env var name -> Key Vault secret name
    overrides: {} # realm JSON merged over the stack's realm
  image: ghcr.io/uw-ssec/llmoxie-keycloak:<tag>@sha256:<digest> # required, below
  # config_cli_image, oauth2_proxy_image, cpu (1.0), memory (2Gi),
  # revision_suffix and refresh_trigger are optional
mlflow:
  login: { enabled: true } # role defaults to mlflow-user
litellm:
  login: { enabled: true } # role defaults to litellm-admin
```

`config_cli_image` (keycloak-config-cli 6.5.1-26.5.5) and `oauth2_proxy_image`
(v7.15.6) are pinned by digest, and the schema refuses an image that isn't
`<name>:<tag>@sha256:<64 hex>`. `keycloak.image` is held to the same rule once
`keycloak.enabled` is true, because Keycloak's database migrations are one-way.
Its default is the moving `:latest` tag, which is fine while Keycloak is off, so
enabling Keycloak means setting `keycloak.image` to a built tag and its digest.

**Validation errors** (raised when the config loads):

- `<app>.login.enabled is true but keycloak.enabled is false`.
- `keycloak.enabled needs edge.enabled`.
- `keycloak.enabled is true but keycloak.hostname is not set`, and
  `keycloak.hostname ... is not listed in edge.custom_domains`.
- `keycloak.hostname and <app>.hostname are both ...`: the hostnames must
  differ.
- `realm.overrides.clients redefines the stack's client ...` (the stack owns
  `mlflow-gate`, `litellm-gate`, `litellm` and `llmaven-cli`), and
  `... has clientId ... with a $( substitution`.
- `Azure caps these names at 32 characters: ... Shorten project.name.` for the
  Keycloak app, the realm job and the login apps.
- `Image ... must be pinned as <name>:<tag>@sha256:<64 hex digits>` (named
  `keycloak.image`, `keycloak.config_cli_image` or
  `keycloak.oauth2_proxy_image`).
- `<app>.login.enabled is true but <app>.enabled is false`.
- `realm.name cannot be 'master'`.
- `realm.overrides sets 'realm'` (or `'id'`): that would rename the imported
  realm; set `keycloak.realm.name` instead.
- `realm.secret_refs uses reserved env var names`: names starting with
  `KEYCLOAK_`, `IMPORT_` or `KC_CLIENT_SECRET_`, and `REALM_DOCUMENT_SHA256`,
  are set by the realm job itself.

`keycloak_db` is added to `database.databases` automatically. That also creates
an unused `postgres://` connection-string secret for it; it is harmless. The
database resource is retained on delete (only that one): turning
`keycloak.enabled` off leaves `keycloak_db`, with its users, credentials and
grants, on the server.

**Secrets** (Key Vault; the stack generates all of them):
`keycloak-admin-password`, `keycloak-db-url`, `keycloak-db-username`,
`keycloak-db-password`, `keycloak-client-mlflow-gate`,
`keycloak-client-litellm-gate`, `keycloak-client-litellm`,
`keycloak-client-llmaven-cli`, `oauth2-proxy-cookie-mlflow` and
`oauth2-proxy-cookie-litellm`. The client and cookie secrets exist only for the
logins that are on. The bootstrap admin user is `admin`; its password is in
`keycloak-admin-password`.

**Realm management.** The realm is a document rendered from the config
(`keycloak_realm.py`) and applied by keycloak-config-cli in a Container Apps Job
(`<project.name>-realm-<env>`), not at Keycloak startup.

- It runs with `IMPORT_MANAGED_*=no-delete`: clients, roles, identity providers,
  groups and client scopes that aren't in the document are left alone. The
  console's per-organization clients, created at runtime, survive every import.
  Because nothing is deleted, removing a client from the document does not
  remove it from Keycloak. Delete it by hand in the admin console.
- It merges client attributes. Removing an attribute from the document does not
  clear it in an already-imported realm; set it to `""` explicitly instead.
- `realm.overrides` is merged over the stack's realm, lists by key, and cannot
  redefine the four stack clients. Add other clients under a new `clientId`.
- `realm.secret_refs` maps an env var name to a Key Vault secret name, for
  operator secrets the document references as `$(env:NAME)`, such as a CILogon
  client secret.
- CILogon comes later, per environment, as an `identityProviders` entry in
  `realm.overrides`, brokered through Keycloak (spec "Identity providers
  later"). Nothing in the stack depends on it.
- **The realm name is permanent.** It is part of the token issuer
  `https://<keycloak.hostname>/realms/<name>`, so renaming it breaks every
  client. `llmaven infra deploy` refuses a changed name with
  `keycloak.realm.name is '<new>' but the stack deployed realm '<old>'`; set it
  back.
- The `llmaven-cli` service account holds `mlflow-user`. It has a placeholder
  verified email, `llmaven-cli@service.invalid`, because oauth2-proxy refuses a
  token without a verified email (the first real-container run proved this).

**The realm job during `deploy`.** After a successful `up`,
`llmaven infra deploy` starts the realm job and waits for it (up to 600 s). It
does this also after an `up` with no changes, and never on `--preview`. If the
job fails or doesn't finish, the deploy raises
`Infrastructure deployed, but the Keycloak realm was not applied: ...`. If the
job ends Failed, Stopped or Degraded, the message carries Azure's reason and
message and the command
`az containerapp job logs show ... --container realm-import` (it needs the
`containerapp` CLI extension). If it outlasts the 600 s, the message carries
that logs command and also `az containerapp job execution show` for the status.
Fix the cause and run `deploy` again; the import is repeatable.

**Backups.** `keycloak_db` is on the Postgres server's point-in-time backups.
The retention is `database.backup_retention_days` (7 to 35), which defaults to 7
for dev, 14 for staging and 35 for prod in `config/defaults.py`; check the
deployed config for the real value. A restore brings back the whole server's
state at that time, including the realm's users and sessions.

**LiteLLM SSO.** With `litellm.login.enabled`, LiteLLM's Admin UI signs in
through the `litellm` client. LiteLLM must be the uw-ssec fork build (see
`docker/dockerfiles/litellm.dockerfile`): it is published for amd64 only, so
Apple Silicon hosts need emulation. The Dockerfile imports `mlflow` and
`litellm.proxy.proxy_server` together at build time (under `timeout 600`), so an
image that can't import them fails in CI; that import has not been run locally.
The stack sets `GENERIC_ROLE_MAPPINGS_GROUP_CLAIM=realm_access.roles` and
`GENERIC_ROLE_MAPPINGS_ROLES` mapping `proxy_admin` to `litellm.login.role`.
LiteLLM updates the role on every login. **Revocation.** Each login app
refreshes its session with Keycloak every minute
(`OAUTH2_PROXY_COOKIE_REFRESH=1m`, below Keycloak's 5-minute access-token
lifespan) and caps the cookie at 10 hours (`OAUTH2_PROXY_COOKIE_EXPIRE=10h`,
Keycloak's default SSO session max). On a refresh, oauth2-proxy's
`keycloak-oidc` provider re-reads the roles from the new tokens, and a user who
was disabled or whose Keycloak session ended is signed out. So removing
`mlflow-user` or `litellm-admin`, or disabling a user, ends their gate access
within about a minute (read in oauth2-proxy v7.15.6; not yet run against
staging, see "Staging checks"). It does not demote `proxy_admin` in LiteLLM's
database, and API keys they minted earlier keep the role LiteLLM gave them.
Revoke those keys too.

**`llmaven infra extract`.** To pass the MLflow login, put both of these in the
env file, next to the public MLflow hostname:
`LLMAVEN_SECRETS_KEYCLOAK_TOKEN_URL` (the realm's token endpoint) and
`LLMAVEN_SECRETS_KEYCLOAK_CLI_CLIENT_SECRET` (copy it from Key Vault secret
`keycloak-client-llmaven-cli`). Set both or neither. The extract refreshes the
token before it expires. The CLI no longer prints local variables in error
tracebacks (`pretty_exceptions_show_locals` is off), so secrets from env files
can't appear there.

**Rollout** (spec 2.10; changes live infrastructure, so it is the owner's to
run, and nothing here is run by an agent). Stage 1 (the edge) must be live on
the environment first. Staging first, then ISS and prod:

0. Take a recent `pg_dump` of `litellm_db`. LiteLLM's Prisma migrations are
   one-way (see "stay on the OSS LiteLLM gateway" in project memory), so a
   rollback of the image means restoring that dump.
1. Release with the fork LiteLLM image (the one in
   `docker/dockerfiles/litellm.dockerfile`) and deploy it, before turning
   `litellm.login` on. Set `keycloak.image` to a built tag and its digest.
2. Deploy with `keycloak.enabled: true` and both `login.enabled: false`.
   Keycloak and the realm job come up; nothing is gated yet. Bind the Keycloak
   hostname and its certificate the same way as the edge's hostnames (not yet
   exercised for Keycloak). Check that the issuer
   `https://<keycloak.hostname>/realms/<name>/.well-known/openid-configuration`
   answers. With the logins off the realm has no `mlflow-user` or
   `litellm-admin` role and no `llmaven-cli` client yet, and no client secrets
   exist, so those cannot be done here. From an IP in
   `keycloak.admin_allowed_ips`, sign in to the admin console as `admin` and
   create the administrators' users **in the `<keycloak.realm.name>` realm, not
   `master`**. Give each an email with "Email verified" on and set a password:
   the realm requires a verified email and no SMTP is configured, and
   oauth2-proxy also refuses an unverified email.
3. Turn `mlflow.login.enabled` and `litellm.login.enabled` on and deploy. Move
   admin scripts off encoded paths and non-`Authorization` key headers first
   (see "Login apps" above). This deploy creates the roles, the clients and
   their secrets, and turns the logins on. **From this deploy until step 4, the
   MLflow and LiteLLM UIs refuse everyone**, because no user holds the role yet.
   API keys on LiteLLM's public paths keep working.
4. Immediately grant `mlflow-user` and `litellm-admin` to the administrators in
   the admin console, and copy the `llmaven-cli` secret from Key Vault
   (`keycloak-client-llmaven-cli`) into the operators' env files (above).
5. Run the "Staging checks" below.

**Rollback.** Turn the logins off first and keep `keycloak.enabled: true`:
deploy with both `login.enabled: false`. That removes the login apps and their
routes, and the UIs go back to stage 1's behavior. It also deletes each login's
Key Vault secrets (its client and cookie secrets); whether Key Vault's
soft-delete blocks creating a secret of the same name again when the login is
turned back on is unverified, so check on staging before relying on it. Turning
`keycloak.enabled` off after that removes the Keycloak app, the realm job and
the Keycloak secrets, but not `keycloak_db`: the database is retained on the
server, with its users, credentials and grants. The retained database is no
longer in Pulumi state, so turning Keycloak on again would try to create it
again and fail until it is imported into the stack (`pulumi import`); that path
is unverified. Don't turn Keycloak off while a login is on (the config is
refused). Rolling LiteLLM back from the fork image is a separate step and needs
the `pg_dump` from step 0.

**Staging checks** (what the local run could not show; see also "What was
tested"):

- A real LiteLLM Admin UI SSO login on the fork build. It exercises LiteLLM's
  call to Keycloak's userinfo on the internal address with a token whose issuer
  is the public one.
- The realm job on a fresh stack finishes within its 300 s availability wait
  (`KEYCLOAK_AVAILABILITYCHECK_TIMEOUT`), when Keycloak is still on its first
  boot and migrating its database.
- The first realm import with the administrators created as in step 2, then a
  sign-in with each.
- Role removal: remove `mlflow-user` (or `litellm-admin`) from a signed-in user;
  their next request after the one-minute refresh gets 403.

**What was tested** (a local run with the real Keycloak, keycloak-config-cli,
oauth2-proxy and Traefik images at the config's pinned versions, and `whoami`
stubs for LiteLLM and MLflow; 10/10 re-run cases as expected after two fixes).
Proven: the issuer is the public URL, and oauth2-proxy redeems codes against
Keycloak's internal address (never through the edge) while accepting tokens with
the public issuer; a browser login works for a user with the role on both hosts
and is refused for one without `litellm-admin` on LiteLLM (a browser session
without `mlflow-user` on MLflow was not tested); an `llmaven-cli` bearer passes
MLflow, and a bearer token for a user without `mlflow-user` gets 403; garbage
bearers go to the login; on LiteLLM, a bearer key passes only from the
allowlisted IP, and the UI and login paths, including `//ui/`, `/%75i/`,
`/ui%2F` and `;` forms, always go to the login; large sessions split into two
cookies and still match the route; the Keycloak admin console is closed to other
IPs, including through `..`, `%2e%2e` and `;` path tricks; and a second realm
job run keeps client `org-demo`, created by hand, and changes nothing but the
order of built-in client scope lists in a Keycloak export. It used these dev
overrides: plain HTTP everywhere (insecure cookies, `http://` redirect URIs
patched in by hand), and an `X-Forwarded-For` header on each request to stand in
for Envoy. Still unverified and needing staging: TLS on the internal FQDNs,
Envoy as the real peer (with `KC_PROXY_HEADERS=xforwarded` and an `https`
forwarded protocol), the hostname move, what real LiteLLM and MLflow do with
forwarded requests, and a login against the real LiteLLM fork build.
