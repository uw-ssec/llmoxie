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
  everything except the health path.
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

**Client IP and trust.** Traefik keeps `X-Forwarded-For` only from peers in
`edge.trusted_proxy_ips` (default: `networking.container_apps_subnet`). The
admin allowlist and rate limiter read the rightmost entry of the header as
received (`depth: 1`). That is safe only because every legitimate peer is the
Container Apps Envoy, which appends the real client IP. Any other workload that
can reach Traefik's port directly from inside the trusted range can forge an
allowlisted IP. This was observed with the real binary: a forged
`X-Forwarded-For: 203.0.113.7` from a trusted peer reached the backend (200),
while the same header from an untrusted peer got 403. Don't widen
`trusted_proxy_ips`.

**Validation errors** (all raised when the config loads):

- `edge.enabled and litellm.proxy.enabled are both true`: set
  `litellm.proxy.enabled: false` and move its policy to `litellm.hostname` and
  `litellm.admin_allowed_ips`. Public and health paths move to
  `litellm.public_paths` and `litellm.health_paths`, and `trusted_proxy_ips`,
  `rate_limit_average` and `rate_limit_burst` move to `edge.*`.
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

**Rollout.** Per environment, staging first:

1. Deploy with `edge.enabled: true`. On a stack with existing hostnames, the
   deploy removes each hostname from its old app and lists it on Traefik. Then,
   per hostname, bind it to Traefik by hand with `az containerapp hostname add`
   and `az containerapp hostname bind`. Check whether the existing managed
   certificate can be reused in the same environment or a new one must be
   issued. Each hostname is down from its removal until its bind, so plan the
   window and announce it on ISS and prod.
2. On staging, run both client-IP checks. The Envoy peer must be inside
   `trusted_proxy_ips`, and no other workload in the environment may be able to
   reach Traefik's port directly and forge an allowlisted `X-Forwarded-For`.
   Also check streaming responses through Traefik, and that LiteLLM's and
   MLflow's platform FQDNs no longer answer from outside.
3. Anyone still calling LiteLLM or MLflow at a platform FQDN breaks at this
   step. Find those callers and move them before ISS and prod.

Without `edge.enabled` the stack deploys exactly as before. Design:
`docs/superpowers/specs/2026-11-13-keycloak-azure-design.md`.
