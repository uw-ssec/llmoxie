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

| Command          | What it does                                                                               |
| ---------------- | ------------------------------------------------------------------------------------------ |
| `init`           | Writes a config with defaults (`-e dev\|staging\|prod`, `-o <path>`, `--no-interactive`)   |
| `validate`       | Checks the config (`--strict` fails on warnings, `--env-file` for secrets)                 |
| `deploy`         | Deploys (`--preview`, `--yes`, `--expect-no-changes`, `--env-file`)                        |
| `status`         | Shows the deployed stack's status                                                          |
| `refresh`        | Refreshes Pulumi state from Azure (`--yes`)                                                |
| `cancel`         | Cancels a stuck Pulumi update                                                              |
| `destroy`        | Tears down **all** resources (`--yes`)                                                     |
| `extract`        | Downloads LiteLLM spend logs to a zip (`--source`, `--out`)                                |
| `keycloak-users` | Creates Keycloak accounts for invitees from a CSV (`--csv`, `--out`, `--dry-run`, `--yes`) |

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
otherwise redirect UI logins there. `PROXY_BASE_URL` alone did not cover
LiteLLM's trailing-slash redirects (`/ui` to `/ui/`, `/sso/key/generate/`),
which Starlette builds from `Host`; on dev they sent the browser to
`http://<app>.internal…`, an Azure 404. The fork build pinned in
`docker/dockerfiles/litellm.dockerfile` includes uw-ssec/llmoxie-litellm#13,
which rewrites any redirect back to the request's own host to `PROXY_BASE_URL`,
so the edge needs that build or later.

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
  `mlflow-gate`, `litellm-gate`, `litellm`, `llmaven-cli` and `console`, the
  last even with the console off), and
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
`keycloak-admin-password`. **Don't delete it**, even though Keycloak's admin
console asks you to replace the "temporary admin user": the realm job signs in
as `admin` with that password on every deploy, so the next deploy would fail at
the realm import. For a personal admin, add a user in the `master` realm with
the `admin` realm role and keep `admin` for the job.

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

**One sign-in, SSO only.** With `litellm.login.enabled` the stack also sets
`AUTO_REDIRECT_UI_LOGIN_TO_SSO=true`, so LiteLLM's own login page goes straight
to Keycloak, which already has the gate's session, and adds
`general_settings.disable_password_login_when_sso_enabled: true` to the mounted
LiteLLM config (`apply_sso_only_login` in `resources/helpers.py`). The second
turns off LiteLLM's username/password form, which otherwise accepts the master
key as an admin password; LiteLLM shows an "Environment-credential login is
enabled" banner while that form is live. An operator's own value for either
wins. The master key still works on the API.

**Master key and salt key.** LiteLLM refuses to start without a master key, so
it can't be turned off; the most you can do is make it a break-glass secret that
only Key Vault holds, with admins using their own virtual keys. LiteLLM also
encrypts what it stores in its database (models, credentials) with
`LITELLM_SALT_KEY`, falling back to the master key when that is unset (fork
`get_salt_key()` in `litellm/proxy/common_utils/encrypt_decrypt_utils.py`). A
salt key added to a database with stored values must equal the master key's
current value; a fresh one makes every stored value unreadable (#200, and "never
add a fresh salt key" in project memory). Once set it never changes.
`llmaven infra validate` warns when the LiteLLM config has
`store_model_in_db: true` and `LITELLM_SALT_KEY` is in neither
`litellm.env_vars` nor `litellm.key_vault_secret_refs`. Dev has the salt key as
Key Vault secret `litellm-salt-key` since 2026-11-15.

After the salt key is set, rotate the master key **only by changing its value**
(the `litellm-master-key` secret, then a deploy). The fork's startup migration
sees the salt key and leaves stored values alone (`master_key_migration.py`).
Don't use `/key/regenerate` with `new_master_key`: in the fork it re-encrypts
stored models, `environment_variables` and MCP server credentials with the new
master key while decryption keeps reading the salt key (only guardrail params
check for it), which would corrupt them. That is read in the fork's
`key_management_endpoints.py`, not tested. The rotation itself, and moving
`infra extract` off the master key, are still to do on dev.

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
   Keycloak and the realm job come up; nothing is gated yet. The Keycloak
   hostname must be bound before this deploy, because the config has to list it
   in `edge.custom_domains` with an existing certificate. On dev (2026-11-15):
   add a DNS-only CNAME to the Traefik app's FQDN and the `asuid.<host>` TXT
   record (the environment's `customDomainVerificationId`), run
   `az containerapp hostname add` on the Traefik app, then
   `az containerapp hostname bind --validation-method CNAME`. The first bind
   failed with `CertificateProvisioningError` while the managed certificate was
   Pending; a few minutes later it was Succeeded and a second bind worked. Put
   the certificate's name in `edge.custom_domains`, then deploy. Check that the
   issuer
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
tested"). Dev ran the LiteLLM half on 2026-11-15, with MLflow off:

- A real LiteLLM Admin UI SSO login on the fork build. It exercises LiteLLM's
  call to Keycloak's userinfo on the internal address with a token whose issuer
  is the public one. **Shown on dev**: one Keycloak sign-in lands in the Admin
  UI as `proxy_admin`, once the fork build had the redirect fix (#13).
- The realm job on a fresh stack finishes within its 300 s availability wait
  (`KEYCLOAK_AVAILABILITYCHECK_TIMEOUT`), when Keycloak is still on its first
  boot and migrating its database. **Shown on dev**: the first run finished in
  under 70 s.
- The first realm import with the administrators created as in step 2, then a
  sign-in with each. **Shown on dev** for one administrator on LiteLLM.
- Role removal: remove `mlflow-user` (or `litellm-admin`) from a signed-in user;
  their next request after the one-minute refresh gets 403. Not yet run.
- The MLflow login, including the `llmaven-cli` bearer. Not run on dev, where
  MLflow is off.

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
forwarded requests, and a login against the real LiteLLM fork build (since shown
on dev for LiteLLM; see "Staging checks").

## The console

`console.enabled` (off by default) runs the LLMoxie console on the stack: the
web app, the broker, their database and roles, their Keycloak client and their
mail. Design: `docs/superpowers/specs/2026-11-15-console-azure-design.md`. The
service itself is described in `services/console/README.md`. Source:
`resources/console.py` (apps, file share, jobs), `resources/console_secrets.py`
(identities and vaults), `resources/console_mail.py` (Azure Communication
Services), `resources/keycloak_realm.py` (the client), `resources/traefik.py`
(routes), `deployment/keycloak_users.py` (accounts).

It needs `edge.enabled`, `keycloak.enabled`, `litellm.enabled`,
`litellm.login.enabled` and `litellm.admin_hostname`.

```yaml
litellm:
  hostname: dev.llm.example.org # gateway
  admin_hostname: dev.litellm.example.org # UI and management API
console:
  enabled: true
  hostname: dev.console.example.org # in edge.custom_domains
  image: ghcr.io/uw-ssec/llmoxie-console:<tag>@sha256:<digest>
  admin_subjects: ["<Keycloak user id>"] # CONSOLE_ADMIN_SUBJECTS
  invite_ttl_hours: 72
  mail:
    domain: mail.example.org
    sender: console # console@mail.example.org
    display_name: LLMoxie console
    domain_verified: false # true once the DNS records verify
  web: { min_replicas: 1, max_replicas: 2, cpu: 0.25, memory: 0.5Gi }
  broker: { min_replicas: 1, max_replicas: 1, cpu: 0.5, memory: 1Gi }
  # revision_suffix and refresh_trigger are optional
```

**Validation errors** (raised when the config loads):

- `console.enabled needs <flag>` for `edge.enabled`, `keycloak.enabled`,
  `litellm.enabled` and `litellm.login.enabled`, and
  `console.enabled needs litellm.admin_hostname`.
- `console.hostname` unset or not in `edge.custom_domains`, and
  `console.hostname and <app>.hostname are both ...`.
- `Image ... must be pinned as <name>:<tag>@sha256:<64 hex digits>` for
  `console.image`; the default `:latest` is fine only while the console is off.
- `console.admin_subjects` empty, and `console.mail.domain` unset.
- LiteLLM's config without `store_model_in_db: true`, or `LITELLM_SALT_KEY` in
  neither `litellm.env_vars` nor `litellm.key_vault_secret_refs`. Elsewhere
  these are warnings; here they are errors, because the console stores provider
  keys.
- An app, job or console vault name over its limit (32 characters for Container
  Apps and jobs, 24 for vaults).

`console_db` is added to `database.databases` automatically and, like
`keycloak_db`, is retained on delete.

**Two LiteLLM hosts.** `litellm.admin_hostname` splits LiteLLM in two. Unset,
LiteLLM renders as before.

- `litellm.hostname` is the **gateway**. The edge routes only
  `litellm.public_paths` (rate limited) and `litellm.health_paths` there. There
  is no catch-all, so every other path (`/ui`, `/key/*`, `/sso/*`, `/oauth2/*`,
  and every encoding or case variant) gets Traefik's 404 from any IP, with or
  without a key.
- `litellm.admin_hostname` is the **admin host**. It gets the rules the single
  host had: a Keycloak session with `litellm.login.role`, or a bearer key from
  `litellm.admin_allowed_ips`, never on the UI paths.
- `PROXY_BASE_URL`, the realm's `litellm` and `litellm-gate` redirect URIs and
  the `llm-auth` oauth2-proxy's redirect URL, cookie domain and whitelist domain
  move to the admin host.
- Exports: `litellm_url` stays the gateway; `litellm_admin_url` is the admin
  host.
- **Operator effect.** Anything that used a bearer key against the one host now
  needs the admin host. That includes `llmaven infra extract --source litellm`:
  set `LITELLM_BASE_URL` in its env file to `https://<litellm.admin_hostname>`.
  API clients on the gateway host keep working.

**Secrets and vaults, with no role assignments.** The people who run
`infra deploy` are Contributor, which can't make Azure role assignments, and the
program creates none (`azure_native.authorization.*` never appears). Isolation
comes from separate vaults instead.

- Two user-assigned identities, `console-web` and `console-broker`, and two
  access-policy vaults, `kv-<project>-<env>-cw` and `kv-<project>-<env>-cb`
  (`enable_rbac_authorization: false`, the main vault's soft-delete and purge
  settings). Each vault's policies are set **inline when the vault is created**
  and are exactly two: its identity (`get`, `list`) and the deployer. There are
  no `AccessPolicy` resources, so the replace behavior in
  `bugs/key-vault-access-policy-replace` can't happen. The main vault is
  unchanged.
- Unlike the main vault, the console vaults don't ignore changes to their
  policies, so every deploy rewrites the list. The deployer entry comes from
  whoever runs `infra deploy` (`get_client_config()`), so another operator's
  deploy swaps the previous operator's entry for their own. Adding
  `ignore_changes` would also freeze the identity entries, so it isn't set.
- The web vault holds `console-oidc-client-secret`,
  `console-broker-caller-secret` and `console-web-db-url`. The broker vault
  holds `console-broker-caller-secret`, `console-broker-db-url` and
  `console-mail-connection` (the Communication Service's primary connection
  string). `console-web` can read neither the main vault nor the broker's.
- The main vault also holds what the shared identity's jobs need:
  `console-web-db-password`, `console-broker-db-password`,
  `console-oidc-client-secret` (for the realm job) and
  `console-db-admin-password` (a copy of the Postgres admin password, the same
  precedent as Keycloak).
- Generated values are `pulumi_random.RandomPassword` and live in Pulumi state
  as secrets. None appears in an export or the env file.
- The broker's own LiteLLM key never passes through Pulumi or Key Vault.
  `console-init` writes it to an Azure Files share, `console-run`, mounted at
  `/run/console` (uid and gid 10001, directory mode 0700, file mode 0600). The
  share is on a small storage account of its own (StorageV2, Standard_LRS, no
  hierarchical namespace), because the main account is ADLS Gen2 and Azure Files
  isn't offered there. It is registered twice as environment storage:
  `console-run-rw` for the init job, `console-run-ro` for the broker.
- The console storage account allows public network access (it is key
  protected), and the console vaults set no network ACLs. With
  `security.enable_private_endpoints` on, they stay public, unlike the main
  vault.

**Apps and jobs.** `console-web` (port 8200) and `console-broker` (port 8100)
have internal ingress and `/healthz` probes. The edge adds a `console` router on
`Host(console.hostname)`, rate limited, with no ForwardAuth, because the console
signs people in itself. `console-db` (`python db_setup.py`) and `console-init`
(`python init_admin_key.py`) are manual jobs that run as the shared identity.
`db_setup.py` connects as the server's admin login, creates the roles
`console_web` and `console_broker` and sets their passwords on every run (so a
rotated secret takes), applies the schema only if `console_db` has none, and
revokes `CONNECT` on the other databases from `PUBLIC` after granting it to the
admin login. Both apps start and answer `/healthz` before the database job has
made their roles, and the broker also before the key file and the schema exist,
so on a first deploy they answer errors per request for about a minute rather
than crash-looping.

**Mail.** Pulumi creates an Email Communication Service, a customer-managed
domain (`console.mail.domain`), a sender username and a Communication Service
(`<project>-<env>-acs`).

- The subscription needs the `Microsoft.Communication` resource provider
  registered once: `az provider register --namespace Microsoft.Communication`.
  `llmaven infra validate` lists it among the required providers when the
  console is on.
- The domain's DNS records (domain TXT, SPF, DKIM, DKIM2) are exported as
  `console_mail_verification_records`. Add them at the DNS host, then start
  verification:
  `az communication email domain initiate-verification --domain-name <domain> --email-service-name <service> --resource-group <rg> --verification-type Domain`
  (and again for `SPF`, `DKIM` and `DKIM2`).
- Azure links a domain to the Communication Service only once it is verified. So
  `console.mail.domain_verified` defaults to `false`, and the service is created
  without the domain. Set it to `true` after verification and deploy again to
  link it. Until then an invitation fails with `mail_failed` (HTTP 502) and
  inviting again works once mail does.

**Accounts for invitees.** The realm has sign-up off and no mail, and an
invitation matches only a verified email, so an operator creates each lead's and
participant's Keycloak account first:

```sh
pixi run -e llmaven llmaven infra keycloak-users -c llmaven-config.yaml \
  --csv people.csv --out passwords.csv --dry-run
pixi run -e llmaven llmaven infra keycloak-users -c llmaven-config.yaml \
  --csv people.csv --out passwords.csv
```

- `people.csv` has an `email` column, the file a lead uploads to invite a team.
  A BOM, a capitalised header, stray spaces, blank lines and duplicates are
  handled: one account per distinct lower-cased address. A file with no `email`
  column creates nothing and says why.
- It needs a client IP in `keycloak.admin_allowed_ips`, and signs in as the
  bootstrap `admin` with `keycloak-admin-password` from the main vault.
- Each new account has the email as username, `emailVerified: true`, a random
  temporary password and the required action `UPDATE_PASSWORD`. Existing
  accounts are left alone and listed.
- The passwords go only to `--out` (mode 0600; the command refuses an existing
  file and removes it if nothing was created), never to the terminal. Send each
  person theirs another way, then delete the file.
- It changes the live realm, so it asks to confirm unless `--yes`. `--dry-run`
  creates nothing.

**Rollout** (changes live infrastructure; the owner runs it, nothing here is run
by an agent). Dev first:

0. `az provider register --namespace Microsoft.Communication`.
1. CI publishes `ghcr.io/uw-ssec/llmoxie-console`. Pin `console.image` by tag
   and digest.
2. DNS, in Cloudflare: a CNAME and an `asuid` TXT record for the admin and
   console hostnames. Add and bind each hostname on the Traefik app
   (`az containerapp hostname add`, then `bind`), and list the certificates in
   `edge.custom_domains`, as for Keycloak above.
3. Note your Keycloak user id (`<realm>` realm) for `console.admin_subjects`.
4. `llmaven infra deploy --preview`, then `deploy`, each with approval. After
   `up` the deploy runs the realm job, then `console-db`, then `console-init`,
   each waited for. A failure raises
   `Infrastructure deployed, but <purpose> did not finish` with the `az`
   commands to read the logs; fix the cause and deploy again, since all three
   are repeatable. `console_url`, `console_db_job` and `console_init_job` are
   exported. The first console deploy may fail and need a re-run while the two
   new identities' inline vault policies propagate (#171, as in
   `bugs/key-vault-access-policy-replace`).
5. Add the mail domain's records, start verification, set
   `console.mail.domain_verified: true` and deploy again (preview first, and
   check it is an in-place update, not a new connection string).
6. Create the test accounts with `keycloak-users`.
7. Run the end-to-end check in the design spec's "Done on dev".

**Rollback.** Turn `console.enabled` off and deploy. The apps, jobs, share,
identities, vaults and mail resources are removed; `console_db` is kept. LiteLLM
keeps the `console-broker` user (`proxy_admin`) and its keys; revoke them there.
`init_admin_key.py` mints a new key whenever the key file is missing or holds a
key that doesn't work, and never revokes the old ones, so each re-enable (a new,
empty share) adds another key. Unsetting `litellm.admin_hostname` (after the
console is off) returns LiteLLM to one host; move scripts back to the gateway
host first.

Turning the console **back on** after that needs a step first. Key Vault
soft-delete keeps the deleted console vaults' names reserved, so the create
fails until you recover or purge them:

```sh
az keyvault recover --name kv-<project>-<env>-cw
az keyvault recover --name kv-<project>-<env>-cb
```

(or `az keyvault purge` for each, which works only if purge protection is off).
Whether the program then adopts a recovered vault cleanly is unverified. The
same applies, also unverified, to the console secrets deleted from the main
vault: `console-oidc-client-secret`, `console-web-db-password`,
`console-broker-db-password` and `console-db-admin-password`. Soft-delete keeps
their names reserved, so recover or purge each before re-enabling
(`az keyvault secret recover --vault-name <main vault> --name <secret>`, or
`az keyvault secret purge` with the same arguments). The retained `console_db`
is no longer in Pulumi state, so re-enabling would try to create it again and
fail until it is imported (`pulumi import`), as for `keycloak_db`; that path is
unverified.

**Unverified until dev** (what the offline tests and local runs could not show):

- Who owns a database ARM creates (`azure_pg_admin` or the admin login), and
  that `GRANT CONNECT` then `REVOKE CONNECT FROM PUBLIC` works on Azure.
- The Azure Files mount with those uid, gid and mode options: that
  `console-init` can write `/run/console/admin-key` and the broker can read it.
- The broker and console-web answering `/healthz` 200 in a real container before
  the jobs run, and their connection pools reconnecting once the database roles
  and schema exist.
- A real Azure Communication Services send, the error before the domain is
  linked, and that flipping `domain_verified` is an in-place update with no
  connection-string rotation.
- That the console's access token carries `email`, `email_verified` and the
  `console-broker` audience (the email scope comes from the realm's default
  client scopes).
- That Contributor can create all of it: identities, vaults with inline
  policies, the Communication resources, the storage account and environment
  storage.
- Re-enabling after a disable, as above.

## The knowledge hub

`knowledge_hub.enabled` (off by default) runs
[okf-hub](https://github.com/uw-ssec/okf-hub), the organizations' shared
knowledge store, as an internal-only Container App beside the console. Design:
`docs/superpowers/specs/2026-11-17-okf-hub-container-design.md`. Source:
`resources/knowledge_hub.py` (identity, vault, secrets, storage account, Blob
container, app), `resources/keycloak_realm.py` (the role and clients),
`resources/traefik.py` (the `/mcp` route), `resources/console.py` (the broker's
settings).

It needs `console.enabled` and `keycloak.enabled`; `image` must be pinned as
`<name>:<tag>@sha256:<digest>` (the default `:latest` is fine only while the hub
is off).

```yaml
knowledge_hub:
  enabled: true
  image: ghcr.io/uw-ssec/okf-hub:container-8e3081d@sha256:90d230fb85f9ce685fcf39edf9f5e04481a8acfbe7b6f4379103f173b9ecf067
  cpu: 0.5
  memory: 1Gi
```

**Turning it on.**

- Generate the master key once, into the sops env file:
  `LLMAVEN_SECRETS_OKF_HUB_MASTER_KEY=$(openssl rand -hex 32)` (64 lowercase hex
  characters). It encrypts the hub's vault, so it **can never change while any
  bundle exists**; losing it makes the stored data unreadable. Pulumi never
  generates it. `infra validate` and `infra deploy` stop before `up` when it is
  missing or malformed. It is kept out of the main vault: only the hub's own
  vault holds it.
- The image is built from the `container` branch of `uw-ssec/okf-hub`. It is
  private until the owner makes that repository public, and Container Apps here
  pull only public images, so the dev deploy waits for that.
- Pin `console.image` (by digest) to a console build made from a commit that
  includes the knowledge hub work: `console-know` runs `knowledge_backfill.py`
  from that image, and an older console image lacks it, so the first hub-on
  deploy would finish `up` and then fail at `console-know`.
- The first hub-on deploy may fail and need a re-run while the hub's new
  identity's inline vault policy propagates (#171, as in
  `bugs/key-vault-access-policy-replace`), as for the console.
- The hub is `<project>-<env>-okf-hub-<env>`: one replica
  (`min_replicas = max_replicas = 1`), internal ingress, port 7878, probes on
  `/healthz`. Its URL is
  `https://<app name>.internal.<environment default domain>`. That one value is
  the hub's `OIDC_AUDIENCE`, the console's `KNOWLEDGE_HUB_URL` and the audience
  of `console-knowledge` and every `okf-org-*` client, so it must never change
  for a stack. It changes if the Container Apps environment is replaced (a new
  environment has a new default domain), which breaks every one of those
  clients' audiences and the hub's own.
- `REFRESH_TRIGGER` is fixed (`knowledge_hub.refresh_trigger`, else a constant),
  so a deploy rolls a new hub revision only when something else in the app
  changes.
- The hub has its own storage account, `okf-hub-storage-<env>`, named
  `<project><env><region>okf` (hyphens dropped, region cut to 4 letters, e.g.
  `llmavendevdevwestokf`): StorageV2, LRS, https only, TLS 1.2, no public blob
  access, shared keys on (the hub reads it through a connection string). The
  account, its Blob container `okf-hub` and the database `okf_hub` (owned by the
  role `okf_hub`, created by the `console-db` job) are all retained on delete.
- The hub starts serving before its database role exists (`/healthz` 200
  "starting", `/mcp` 503) and is ready once `console-db` has run, so the first
  hub-on deploy does not deadlock.
- The realm gains the role `knowledge-reader` and the clients
  `console-provisioner` and `console-knowledge`. The broker gets
  `KNOWLEDGE_HUB_URL`, `KEYCLOAK_ADMIN_URL`, `KEYCLOAK_TOKEN_URL` and the
  provisioner and knowledge client ids and secrets.
- The gateway host routes `/mcp` and `/mcp/` (exact paths) to LiteLLM when the
  hub is on; nothing else changes there.

**What the deploy runs.** After `up`: the realm job, then `console-db`,
`console-init` and `console-know`, each waited for. `console-know` sets up
knowledge (Keycloak client and MCP server) for organizations that existed before
the hub; it is idempotent, and suspended organizations' teams stay closed.

**Turning it off.** Set `knowledge_hub.enabled: false` and deploy. The app,
identity and vault are removed. Organizations keep their MCP servers in LiteLLM,
now pointing at the missing hub, and team pages keep listing the tools. The
`okf_hub` database, the hub's storage account and its `okf-hub` Blob container
are retained, so they stay (even if the console is turned off later) but leave
Pulumi state. Keycloak keeps the clients `console-provisioner` (which may manage
clients in the realm), `console-knowledge` and every `okf-org-*`, and the role
`knowledge-reader`: the realm import never deletes
(`IMPORT_MANAGED_*=no-delete`) and nothing removes the broker's `okf-org-*`
clients. Disable the clients in the Keycloak admin console.

Turning the hub **back on** needs steps first (the same master key, too):

- Key Vault soft-delete keeps the deleted names reserved. Recover the hub vault
  (`kv-<project>-<env>-kh`, cut to 24 characters) with
  `az keyvault recover --name <vault>`, or `az keyvault purge` (which works only
  if purge protection is off). Six secrets in two other vaults were deleted too,
  and each needs
  `az keyvault secret recover --vault-name <vault> --name <secret>` (or
  `az keyvault secret purge` with the same arguments):
  - in the main vault: `okf-hub-db-password`, `console-provisioner-secret`,
    `console-knowledge-secret` and `console-broker-db-url`;
  - in the console broker vault (`kv-<project>-<env>-cb`, cut to 24 characters):
    `console-provisioner-secret` and `console-knowledge-secret`.
- The retained database, storage account and Blob container are no longer in
  Pulumi state, so the create fails until each is imported (`pulumi import`), as
  for `console_db`: the database as `postgres-db-okf_hub-<env>`, type
  `azure-native:dbforpostgresql:Database`, ID
  `/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.DBforPostgreSQL/flexibleServers/<server>/databases/okf_hub`;
  the storage account as `okf-hub-storage-<env>`, type
  `azure-native:storage:StorageAccount`, ID
  `/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/<hub storage account>`;
  the container as `okf-hub-blob-<env>`, type
  `azure-native:storage:BlobContainer`, ID
  `/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/<hub storage account>/blobServices/default/containers/okf-hub`.
  Import the account before the container. These paths are unverified.

**Unverified until dev:**

- The internal FQDN as the token audience, end to end.
- The hub reaching Keycloak's JWKS at the internal FQDN while the tokens' issuer
  is the public hostname.
- The Blob connection string taken from `listKeys`.
- Whether a key-bearing MCP client needs LiteLLM routes beyond `/mcp`.
- How Container Apps treats the hub's first revision while it answers
  "starting".
- The brief two-replica overlap while a revision rolls over: Postgres
  compare-and-swap protects the data, but what okf does on a 409 is unverified.
- Re-enabling after a disable, as above.
- LiteLLM registering an organization's MCP server against a hub that still
  answers "starting".
- A `curl` from the hub's container to Keycloak's internal JWKS endpoint: that
  Node's CA store trusts the environment's certificate.
- Whether dev's LiteLLM fork supports MCP `oauth2_flow: client_credentials`, as
  the local fork does.
