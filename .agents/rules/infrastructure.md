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
  your env file.

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
allowlist and rate limiter read the rightmost entry of the header as
received (`depth: 1`). That is safe only because every legitimate peer is the
Container Apps Envoy, which appends the real client IP. Any other workload that
can reach Traefik's port directly from inside the trusted range can forge an
allowlisted IP. This was observed with the real binary: a forged
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
- `edge.trusted_proxy_ips is required when the edge is on`: set it to the
  Envoy peer range (see "What to set" above), never the replica range.
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
