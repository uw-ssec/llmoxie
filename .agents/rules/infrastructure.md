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
