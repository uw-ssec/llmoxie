# Standalone Traefik Edge (Stage 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** An optional `edge` Traefik Container App that becomes the stack's only
public entry point, with LiteLLM and MLflow moved to internal-only ingress and
every public hostname bound to Traefik, routing and access unchanged from today.

**Architecture:** A new `EdgeConfig` section plus per-backend `hostname` fields
in the config schema. A host-aware renderer in `resources/traefik.py` produces
Traefik's file-provider config, and a new `create_edge_app` deploys Traefik
through the existing `create_container_app_with_key_vault_secrets`. With
`edge.enabled`, `main.py` creates LiteLLM and MLflow with
`ingress_external=False`, then the edge app pointed at their internal FQDNs.
With `edge` off, every template is byte-for-byte what it is today, including the
LiteLLM Traefik sidecar, which stays until every environment has moved.

**Tech Stack:** Python 3.12, Pydantic v2, Pulumi (azure-native 3.29), Traefik
v3.7 (file provider), pytest.

**Spec:** `docs/superpowers/specs/2026-11-13-keycloak-azure-design.md` (Stage 1
sections and Constraints). Stage 2 (Keycloak and the logins) gets its own plan
after Stage 1 is rolled out.

## Global Constraints

- Run everything through Pixi: `pixi run -e llmaven pytest ...`,
  `pixi run -e llmaven verify`. Never `pip`, `conda` or `venv`.
- Never run `llmaven infra deploy` (including `--preview`), `destroy`, `refresh`
  or `cancel`. Deploys are the owner's.
- Before the first edit to any file, run
  `pixi run -e llmaven okf search --for-path <file>`; stop on
  `governance: hold`, keep any `constraint`.
- LiteLLM routing is an exact-path allowlist: never a `PathPrefix` route for
  LiteLLM's `/v1/` or `/health/`
  (`knowledge/requirements/traefik-sidecar-allowlist-and-client-ip.md`).
- Client IP is the rightmost `X-Forwarded-For` entry (`ipStrategy.depth: 1`),
  trusted only from `trusted_proxy_ips`, which defaults to
  `networking.container_apps_subnet`.
- Traefik image pinned by digest; reuse `LiteLLMProxyConfig`'s default image
  string (`traefik:v3.7.17@sha256:3211…151`).
- Don't add a Key Vault `AccessPolicy`; the edge app needs no Key Vault secrets
  (`knowledge/bugs/key-vault-access-policy-replace.md`).
- A config without an `edge` section (or with `edge.enabled: false`) produces
  exactly today's resources. Existing tests must pass unchanged.
- Existing resource names don't change (`rebrand-keeps-deployed-identifiers`).
- Commit messages: conventional, scopes from
  `.agents/rules/pre-commit-and-quality.md` (`infra`, `docs`, `knowledge`),
  ending with `Assisted-by: claude-code:<model id>`; no `Co-Authored-By`, no
  `Signed-off-by`.

## Review Focus

- **Unknown hosts, including Traefik's own platform FQDN and the backends' old
  public hostnames:** answered by Traefik with 404, never forwarded to a
  backend. Test in Task 3 (`test_only_configured_hosts_are_routed`).
- **A client-supplied `X-Forwarded-For` naming an allowlisted IP:** ignored; the
  admin catch-all still refuses. Static args trust only `trusted_proxy_ips`, and
  every `ipStrategy` is depth 1. Tests in Task 3, and observed with the real
  binary in Task 6.
- **Host header in another case or with a port (`AI.Example.ORG:443`):** routed
  like the configured host. This is Traefik's matcher behavior, so it isn't
  unit-testable; checked with the real binary in Task 6.
- **An existing prod/ISS config (sidecar on, custom domains on the apps, no
  `edge`):** unchanged templates. Test in Task 5
  (`test_without_edge_apps_keep_public_ingress_and_sidecar`); every test in
  `test_litellm_proxy.py` and `test_custom_domains.py` still passes.
- **Streaming completions through two proxies (Traefik, then the backend's
  internal Envoy):** flushed, not buffered. Test in Task 3 (`flushInterval`),
  and observed in Task 6.

---

### Task 1: Amend the spec where it contradicts itself

**Files:**

- Modify: `docs/superpowers/specs/2026-11-13-keycloak-azure-design.md` (sections
  1.1, 1.4, 1.5)

- [ ] **Step 1: In 1.4, replace the first bullet** ("The LiteLLM sidecar goes
      away …") with: the sidecar stays while `edge` is off, so prod and ISS
      configs keep deploying unchanged. `edge.enabled` with
      `litellm.proxy.enabled: true` is a validation error naming the new fields
      (`edge.*`, `litellm.hostname`, `litellm.admin_allowed_ips`,
      `litellm.public_paths`, `litellm.health_paths`). The sidecar and
      `litellm.proxy` are removed in a follow-up after every environment has
      moved.
- [ ] **Step 2: In 1.4, replace the tracking-URI bullet** with: the
      `mlflow-tracking-uri` secret is built from MLflow's ingress FQDN, which is
      the internal one once its ingress is internal, so it changes with no code
      change. Operators running `infra extract --source mlflow` set the public
      MLflow hostname in their env file.
- [ ] **Step 3: In 1.1, replace the Host-header sentence** with: Traefik does
      not pass the public `Host` through (`passHostHeader: false`). The
      environment's internal Envoy routes by `Host`, and the public hostnames
      are no longer bound to the backends.
- [ ] **Step 4: Run**
      `pixi run -e llmaven pre-commit --files docs/superpowers/specs/2026-11-13-keycloak-azure-design.md`.
      Expected: all hooks pass.
- [ ] **Step 5: Commit**
      `docs(infra): keep the LiteLLM sidecar until every stack has moved to the edge`

### Task 2: Config schema for the edge and the backends' hostnames

**Files:**

- Modify: `src/llmaven/infrastructure/config/schema.py` (new `EdgeConfig`;
  fields on `LiteLLMConfig`, `MLflowConfig`; `LLMavenConfig.edge`; checks in
  `LLMavenConfig.model_post_init`)
- Modify: `src/llmaven/deployment/validate.py` (section 6, production checks)
- Test: `tests/infrastructure/test_edge_config.py` (new)

**Interfaces:**

- Produces:
  - `class EdgeConfig(ContainerAppConfig)` with defaults:
    `enabled: bool = False`, `image` = `LiteLLMProxyConfig`'s default image,
    `port: int = 8080`, `ping_port: int = 8082`, `cpu: float = 0.5`,
    `memory: str = "1Gi"`, `min_replicas: int = 1`, `max_replicas: int = 3`,
    `trusted_proxy_ips: list[str] | None = None`,
    `rate_limit_average: int = 50`, `rate_limit_burst: int = 100`,
    `log_forwarded_for: bool = False`. `custom_domains` is inherited.
  - `LiteLLMConfig.hostname: str | None = None`,
    `LiteLLMConfig.admin_allowed_ips: list[str] = []`,
    `LiteLLMConfig.public_paths` (default `DEFAULT_PUBLIC_PATHS`),
    `LiteLLMConfig.health_paths` (default `DEFAULT_HEALTH_PATHS`), each with the
    same validators as on `LiteLLMProxyConfig`.
  - `MLflowConfig.hostname: str | None = None`.
  - `LLMavenConfig.edge: EdgeConfig`.
  - Hostname validator (shared): lower-case DNS name, no scheme, port, path or
    backtick.

- [ ] **Step 1: Write the failing tests** in
      `tests/infrastructure/test_edge_config.py`. Build configs with
      `LLMavenConfig.model_validate`, using the `EXISTING_STACK` networking from
      `test_litellm_proxy.py`:
  - `test_edge_is_off_by_default`: `LLMavenConfig().edge.enabled is False`, and
    `.hostname is None` on both apps.
  - `test_trusted_proxy_ips_default_to_container_apps_subnet`: with the edge on,
    `edge.trusted_proxy_ips == ["172.16.0.0/23"]`.
  - `test_edge_needs_a_hostname_per_enabled_backend`: edge on with
    `litellm.hostname` unset raises `ValueError` mentioning `litellm.hostname`.
    Same for `mlflow`. With `litellm.enabled: false`, no LiteLLM hostname is
    needed.
  - `test_backend_hostname_must_be_an_edge_custom_domain`:
    `litellm.hostname: ai.example.org` with no matching
    `edge.custom_domains[].name` raises, mentioning `edge.custom_domains`.
  - `test_backend_hostnames_must_differ`: the same name for both raises.
  - `test_edge_refuses_the_litellm_sidecar`: edge on plus
    `litellm.proxy.enabled: true` raises, and the message names
    `litellm.hostname` and `litellm.admin_allowed_ips`.
  - `test_edge_refuses_custom_domains_on_backends`: edge on plus
    `litellm.custom_domains` (and separately `mlflow.custom_domains`) raises,
    mentioning `edge.custom_domains`.
  - `test_edge_refuses_app_ip_rules_on_litellm`: edge on plus
    `litellm.ip_security_restrictions` raises.
  - `test_edge_needs_health_paths`: edge on with `litellm.health_paths: []`
    raises.
  - `@pytest.mark.parametrize` `test_invalid_hostname_is_rejected` over
    `["https://ai.example.org", "ai.example.org:443", "ai.example.org/v1", "a`b.example.org",
    "AI.example.org"]`.
  - `test_existing_sidecar_config_still_validates`:
    `{"litellm": {"proxy": {"enabled": True}}}` with no `edge` validates.
  - `test_prod_edge_with_one_replica_warns`, following
    `test_validate_alert_receivers.py`: a prod config with the edge on and
    `min_replicas: 1` gives a `validate_config` warning containing
    `edge.min_replicas`, and `strict=True` raises `ValidationError`.
- [ ] **Step 2: Run**
      `pixi run -e llmaven pytest tests/infrastructure/test_edge_config.py -q`.
      Expected: FAIL (`edge` is not an attribute; the fields don't exist).
- [ ] **Step 3: Implement the schema.** Add the fields and `EdgeConfig` above.
      Add the edge checks to `model_post_init` after the existing `proxy` block,
      raising `ValueError` with the messages the tests expect; set
      `edge.trusted_proxy_ips` from the subnet there, as the proxy block does.
      Add the prod warning to `validate.py`'s section 6 with the existing
      `warnings.append` / `print` pattern.
- [ ] **Step 4: Run** `pixi run -e llmaven pytest tests/infrastructure -q`.
      Expected: PASS, including the unchanged `test_litellm_proxy.py`,
      `test_schema_defaults.py` and `test_custom_domains.py`.
- [ ] **Step 5: Commit**
      `feat(infra): add the edge config and backend hostnames`

### Task 3: Host-aware Traefik config renderer

**Files:**

- Modify: `src/llmaven/infrastructure/resources/traefik.py` (new functions; the
  sidecar's `build_dynamic_config`, `build_static_args`, `policy_digest` stay as
  they are)
- Test: `tests/infrastructure/test_edge_routing.py` (new)

**Interfaces:**

- Consumes: `LLMavenConfig` with `edge`,
  `litellm.hostname/admin_allowed_ips/public_paths/health_paths`,
  `mlflow.hostname` (Task 2).
- Produces:
  - `build_edge_dynamic_config(config: LLMavenConfig, backends: dict[str, str]) -> dict`.
    `backends` maps `"litellm"` / `"mlflow"` to a backend base URL
    (`https://<internal fqdn>`), with a key only for enabled backends.
  - `render_edge_dynamic_config(config: LLMavenConfig, backends: dict[str, str]) -> str`:
    YAML, as `render_dynamic_config` does.
  - `build_edge_static_args(edge: EdgeConfig) -> list[str]`.
  - `edge_policy_digest(edge: EdgeConfig, dynamic_config: str) -> str`: like
    `policy_digest`, over the static args, image, cpu and memory plus the
    rendered config.
  - Constants: `EDGE_PING_PATH = "/ping"`, `EDGE_PING_ENTRYPOINT = "ping"`.

- [ ] **Step 1: Write the failing tests** in
      `tests/infrastructure/test_edge_routing.py`. Use a config with the edge
      on, `litellm.hostname=ai.example.org`,
      `mlflow.hostname=mlflow.example.org` and
      `admin_allowed_ips=["203.0.113.0/24"]`, and backends
      `{"litellm": "https://litellm.internal.env.test", "mlflow": "https://mlflow.internal.env.test"}`:
  - `test_litellm_routes_are_exact_paths_on_its_host`: health and public
    routers' rules are ``Host(`ai.example.org`) && (Path(`…`) || …)`` listing
    exactly the configured paths. No rule anywhere contains
    `PathPrefix(`/v1`or`PathPrefix(`/health`.
  - `test_litellm_catch_all_is_admin_only`: the lowest-priority LiteLLM router's
    rule is ``Host(`ai.example.org`)`` with middlewares
    `["litellm-admin-ip-allowlist", "client-rate-limit"]`. With empty
    `admin_allowed_ips`, its `sourceRange == ["127.0.0.1/32"]`.
  - `test_public_routes_are_rate_limited_and_health_is_not`.
  - `test_mlflow_host_is_open`: one router, ``Host(`mlflow.example.org`)``, no
    middlewares (as public as MLflow's ingress today).
  - `test_only_configured_hosts_are_routed`: every router rule starts with
    `Host(` naming one of the two hostnames. No router matches without a host,
    so Traefik's own FQDN and anything else gets 404.
  - `test_backends_are_internal_and_do_not_pass_host`: each service has one
    server, the URL from `backends`, with `passHostHeader is False` and
    `responseForwarding.flushInterval == "100ms"`.
  - `test_disabled_backend_has_no_routes`: with `litellm.enabled: false` and no
    `"litellm"` key, no router or service mentions LiteLLM.
  - `test_client_ip_comes_from_rightmost_forwarded_entry`: every `ipStrategy` is
    `{"depth": 1}`.
  - `test_static_args_trust_only_configured_peers_and_ping_is_separate`: args
    contain `--entryPoints.web.address=:8080`,
    `--entryPoints.web.forwardedHeaders.trustedIPs=172.16.0.0/23`,
    `--entryPoints.ping.address=:8082`, `--ping.entryPoint=ping`. No `--api`
    flag. The file provider has `watch=false`.
  - `test_edge_digest_changes_with_policy`: revoking `admin_allowed_ips` changes
    `edge_policy_digest`.
- [ ] **Step 2: Run**
      `pixi run -e llmaven pytest tests/infrastructure/test_edge_routing.py -q`.
      Expected: FAIL (`build_edge_dynamic_config` undefined).
- [ ] **Step 3: Implement the four functions** in `traefik.py`, reusing
      `_path_rule`, `_CLIENT_IP_STRATEGY`, `_NO_ADMIN_IPS` and the sidecar's
      rate-limit and responding-timeout settings. Router names are prefixed per
      backend (`litellm-health`, `litellm-public`, `litellm-admin`, `mlflow`),
      and so are middlewares where they are backend-specific. Update the module
      docstring to describe both uses.
- [ ] **Step 4: Run** `pixi run -e llmaven pytest tests/infrastructure -q`.
      Expected: PASS.
- [ ] **Step 5: Commit**
      `feat(infra): render host-based Traefik routes for the edge`

### Task 4: The edge Container App

**Files:**

- Modify: `src/llmaven/infrastructure/resources/helpers.py` (new
  `create_edge_app`), `src/llmaven/infrastructure/resources/__init__.py` (export
  it)
- Test: `tests/infrastructure/test_edge_app.py` (new)

**Interfaces:**

- Consumes: Task 3's renderer, digest, static args and constants;
  `create_container_app_with_key_vault_secrets`; `build_traefik_volume`,
  `TRAEFIK_DYNAMIC_SECRET`, `TRAEFIK_VOLUME_NAME`, `TRAEFIK_CONFIG_DIR`,
  `POLICY_DIGEST_ENV`, `policy_revision_suffix`.
- Produces:
  `create_edge_app(name: str, resource_group_name, location: str, container_env_id, config: LLMavenConfig, backends: dict[str, pulumi.Input[str]], tags: dict[str, str] | None = None, opts: pulumi.ResourceOptions | None = None) -> azure_native.app.ContainerApp`.
  `backends` holds FQDNs (`Output[str]`) that it turns into `https://` URLs.

- [ ] **Step 1: Write the failing tests** in
      `tests/infrastructure/test_edge_app.py`. Patch
      `azure_native.app.ContainerApp` and `pulumi.export` as
      `test_litellm_proxy._create` does, and resolve Outputs with
      `pulumi.runtime.set_mocks` / `@pulumi.runtime.test` as
      `test_redis_program.py` does:
  - `test_edge_ingress_is_external_with_all_public_hostnames`:
    `ingress.external is True`, `target_port == 8080`, and custom domain names
    equal `edge.custom_domains` names.
  - `test_edge_probes_use_ping`: every probe is an HTTP GET of `/ping` on 8082.
  - `test_edge_mounts_rendered_config`: the `traefik-dynamic-yaml` secret parses
    to `build_edge_dynamic_config(config, {"litellm": "https://<fqdn>", ...})`,
    mounted through `build_traefik_volume()` at `TRAEFIK_CONFIG_DIR`.
  - `test_edge_template_carries_policy_digest`: the `TRAEFIK_POLICY_SHA256` env
    value equals `edge_policy_digest` of the mounted config. A pinned
    `edge.revision_suffix` gets the `-p<8 hex>` suffix.
  - `test_edge_has_no_key_vault_secrets_or_identity`: every secret is inline. No
    `AccessPolicy` resource is created.
- [ ] **Step 2: Run**
      `pixi run -e llmaven pytest tests/infrastructure/test_edge_app.py -q`.
      Expected: FAIL (`create_edge_app` undefined).
- [ ] **Step 3: Implement `create_edge_app`.** Build the URLs with
      `pulumi.Output.all(**backends).apply(...)`, render the config and digest
      inside that `apply`, and pass
      `inline_secrets={TRAEFIK_DYNAMIC_SECRET: rendered}`,
      `env_vars={POLICY_DIGEST_ENV: digest}`,
      `command_args=build_edge_static_args(edge)`,
      `health_probe_port=edge.ping_port`, `health_probe_path=EDGE_PING_PATH`,
      `ingress_external=True` and `custom_domains=edge.custom_domains` to
      `create_container_app_with_key_vault_secrets`. If its `str` type hints
      refuse an `Output`, widen them to `pulumi.Input[str]` and change nothing
      else.
- [ ] **Step 4: Run** `pixi run -e llmaven pytest tests/infrastructure -q`.
      Expected: PASS.
- [ ] **Step 5: Commit** `feat(infra): deploy Traefik as the stack's edge app`

### Task 5: Wire the edge into the program; backends go internal

**Files:**

- Modify: `src/llmaven/infrastructure/resources/helpers.py` (`create_mlflow_app`
  and `create_litellm_app` take `ingress_external: bool = True`)
- Modify: `src/llmaven/infrastructure/main.py` (sections 8.1, 8.2, a new 8.3 for
  the edge, the URL exports, and the `create_monitoring` call)
- Modify: `src/llmaven/infrastructure/resources/monitoring.py`
  (`_Context.edge_app`, `create_monitoring(..., edge_app=None)`, replica-restart
  alert)
- Test: `tests/infrastructure/test_edge_program.py` (new),
  `tests/infrastructure/test_monitoring_program.py` (one new test)

**Interfaces:**

- Consumes: Task 4's `create_edge_app`; Task 2's config.
- Produces: Pulumi exports `edge_url` (Traefik's platform URL); `litellm_url` /
  `mlflow_url` become `https://<hostname>` when the edge is on.

- [ ] **Step 1: Write the failing tests.** In
      `tests/infrastructure/test_edge_program.py`, run the whole program under
      mocks as `test_redis_program.py` does. Extend the mock so
      `azure-native:app:ContainerApp` outputs `configuration.ingress.fqdn`:
      `<containerAppName>.internal.env.test` when `ingress.external` is false,
      `<containerAppName>.env.test` otherwise.
  - `test_with_edge_backends_are_internal`: the LiteLLM and MLflow
    `ContainerApp` inputs have `ingress.external == False`, and neither has
    custom domains.
  - `test_with_edge_traefik_is_the_only_public_app`: exactly one `ContainerApp`
    has `external == True`, and it carries `edge.custom_domains`.
  - `test_with_edge_tracking_uri_is_internal`: the `mlflow-tracking-uri` Key
    Vault secret's value contains `.internal.env.test`.
  - `test_with_edge_urls_are_public_hostnames`: the `litellm_url` and
    `mlflow_url` exports are `https://ai.example.org` and
    `https://mlflow.example.org`.
  - `test_without_edge_apps_keep_public_ingress_and_sidecar`: run with an
    ISS-like config (`litellm.proxy.enabled: true`, `litellm.custom_domains`
    set, no `edge`). Both apps have `external == True`, LiteLLM has two
    containers, there's no `traefik` app, and the exports are the platform
    FQDNs.

  In `test_monitoring_program.py`, add `test_replica_restart_alert_covers_edge`:
  with the edge on and `replica_restarts` enabled, an
  `alert-replica-restarts-edge` resource targets the edge app. With the edge
  off, no such resource exists and no skip warning is logged for it.

- [ ] **Step 2: Run**
      `pixi run -e llmaven pytest tests/infrastructure/test_edge_program.py tests/infrastructure/test_monitoring_program.py -q`.
      Expected: FAIL.
- [ ] **Step 3: Implement.** Add the `ingress_external` parameter to both
      helpers. In `main.py`, pass `ingress_external=not config.edge.enabled`.
      After 8.2, when `config.edge.enabled`, call
      `create_edge_app(name=f"{stack_name}-traefik", ...)` with each enabled
      backend's `configuration.apply(lambda c: c.ingress.fqdn)` and `depends_on`
      both apps. Then export `edge_url` and switch `litellm_url` / `mlflow_url`.
      In `monitoring.py`, add `("edge", ctx.edge_app)` to the restart loop only
      when `edge_app` is not `None`.
- [ ] **Step 4: Run** `pixi run -e llmaven pytest tests -q`. Expected: PASS,
      with every pre-existing test unchanged.
- [ ] **Step 5: Commit**
      `feat(infra): put LiteLLM and MLflow behind the edge on internal ingress`

### Task 6: Check the rendered config with the real Traefik binary

No committed code; this produces evidence for the PR description and the
knowledge record. Work in the session scratchpad.

**Files:**

- Create (scratchpad only): `edge-smoke/render.py`,
  `edge-smoke/docker-compose.yml`

- [ ] **Step 1: Render a config.** `render.py` calls
      `render_edge_dynamic_config` for a config with hostnames `ai.example.org`
      / `mlflow.example.org`, `admin_allowed_ips: ["203.0.113.7/32"]` and
      `trusted_proxy_ips: ["172.30.0.0/16"]`. The backends are
      `http://litellm-stub:80` and `http://mlflow-stub:80`. Write the YAML and
      `build_edge_static_args` to the scratch folder. Run it with
      `pixi run -e llmaven python -I <scratchpad>/edge-smoke/render.py`.
- [ ] **Step 2: Start the stack.** Traefik at the pinned image with those args
      and the file mounted, plus two `traefik/whoami` stubs pinned by digest, on
      a compose network `172.30.0.0/16`. Read
      [[docker-colima-credential-helper]] in memory first if pulls fail.
- [ ] **Step 3: Check each case with `curl` from a container on the network,**
      and record each status:
  - `Host: ai.example.org` `/v1/chat/completions` reaches the LiteLLM stub, and
    the stub sees `Host` ≠ `ai.example.org`.
  - `Host: AI.Example.ORG:443` routes the same way.
  - `/key/generate` gives 403.
  - `/key/generate` with a forged `X-Forwarded-For: 203.0.113.7` gives 403.
  - `//key/generate` and `/v1//key/generate` give 403 (Traefik cleans paths
    before matching, so `/v1//chat/completions` reaching the public route is
    expected and fine).
  - `Host: mlflow.example.org` `/` reaches the MLflow stub.
  - `Host: unknown.example.org` and no `Host` both give 404.
  - The ping port answers `/ping`.
  - A chunked stub response arrives in chunks (`curl -N` against whoami's
    `/?wait=` or a small SSE stub).
- [ ] **Step 4: Tear down** (`docker compose down`; only this scratch project).
      Keep the transcript of statuses for Task 7.

### Task 7: Document the edge and update project memory

**Files:**

- Modify: `.agents/rules/infrastructure.md` (new section "Traefik edge in front
  of the stack" next to "Traefik proxy for LiteLLM", which gains a line saying
  it is replaced by the edge and will be removed)
- Modify: `README.md` (the "Restricting LiteLLM admin routes" section points to
  the edge and shows its config)
- Modify via `okf` only:
  `knowledge/requirements/traefik-sidecar-allowlist-and-client-ip.md`

- [ ] **Step 1: Write the infrastructure section.** Cover: what `edge.enabled`
      changes (one public app; internal backends; hostnames on Traefik; tracking
      URI internal); the config from spec 1.5; validation errors and how to move
      a sidecar config; and the rollout from spec 1.6, including the
      per-hostname outage window, the manual `hostname add` / `bind`, the two
      client-IP checks on staging, and finding callers of the old platform
      FQDNs.
- [ ] **Step 2: Update the README section** with the same config example and a
      pointer to the rule.
- [ ] **Step 3: Update the knowledge record** through the `okf-memory` skill
      (never by hand). Record that the edge replaces the sidecar when enabled,
      that internal ingress removes the platform-FQDN bypass, the Task 6 results
      with the binary version, and that the staging checks are still pending.
      Run `pixi run -e llmaven okf validate`; expected: passes.
- [ ] **Step 4: Run** `pixi run -e llmaven verify`. Expected: passes.
- [ ] **Step 5: Commit**
      `docs(infra): document the Traefik edge and its rollout`, and the
      knowledge change as
      `docs(knowledge): record the edge replacing the sidecar` (split as the
      `okf-memory` skill directs).

## After this plan

- Stage 1 rollout (owner): create the `staging` stack config in
  `llmaven-deploy`, deploy, bind hostnames, run the two client-IP checks and the
  streaming check, then ISS and prod. Record the results in the knowledge
  record.
- Follow-up once every environment has the edge: remove `litellm.proxy` and the
  sidecar code path.
- Stage 2 plan: Keycloak, keycloak-config-cli, the oauth2-proxy logins, LiteLLM
  on the fork with SSO, `infra extract` with a Keycloak token.
