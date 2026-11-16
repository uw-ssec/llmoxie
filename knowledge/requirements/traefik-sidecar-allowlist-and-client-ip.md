---
type: Requirement
title: Path-level access control uses a Traefik edge (or sidecar) with an allowlist
description: "A standalone Traefik edge (or the older sidecar) enforces path allowlists because Container Apps restricts by IP per app; the edge requires an explicit trusted peer range, observed on ISS, and other environments are unproven."
tags: [traefik, litellm, security, container-apps]
generated: { by: "claude-code:claude-sonnet-5-5", at: "2026-11-13T22:08:00Z" }
status: stable
code_refs: [src/llmaven/infrastructure/resources/traefik.py, src/llmaven/infrastructure/resources/helpers.py, src/llmaven/infrastructure/resources/container_apps.py, tests/infrastructure/test_litellm_proxy.py, tests/infrastructure/test_edge_config.py, tests/infrastructure/test_edge_routing.py, tests/infrastructure/test_edge_app.py, tests/infrastructure/test_edge_program.py]
stale_after: 2027-05-01
sources:
  - resource: "issue #214"
  - resource: "PR #217"
  - resource: src/llmaven/infrastructure/resources/traefik.py
  - resource: tests/infrastructure/test_litellm_proxy.py
  - resource: "https://learn.microsoft.com/en-us/azure/container-apps/ingress-overview#http-headers"
---

**Status at dd91796, updated for the edge:** the sidecar (#217, closing #214) is implemented and off by default. The standalone Traefik edge (`edge.enabled`, branch keycloak-service) replaces it when on; `edge.enabled` with `litellm.proxy.enabled: true` is refused. The sidecar stays for stacks that have not moved and is removed in a follow-up once every stack has. No live Container Apps test has run for either. `.agents/rules/infrastructure.md` and the README cover how it works; this concept covers why, and what is unproven.

LiteLLM serves `/v1/*` and its admin surface on one port, and Container Apps ingress restricts by IP only, per app. A separate gateway, Front Door or Application Gateway was rejected because the platform FQDN would still reach the app and skip their rules. The edge closes that bypass differently: LiteLLM and MLflow move to internal ingress, so their platform FQDNs stop answering from the internet and every request passes through Traefik, which routes by hostname. Traefik sends the backend its internal FQDN as `Host` (`passHostHeader: false`) because the environment's internal Envoy routes by `Host`. A request with no `Host` gets 400 (HTTP/1.1, rejected before routing) or 404 (HTTP/1.0); unknown hosts get 404.

Public paths must be an allowlist of exact paths. A blocklist of admin paths can be bypassed through route aliases, double slashes, case or encoding. Don't add prefix routes, since LiteLLM serves management routes under `/v1/` and `/health/`.

**Trust model (edge and sidecar).** Traefik keeps `X-Forwarded-For` only from peers in `trusted_proxy_ips` (the edge requires it to be set; the sidecar still defaults to `networking.container_apps_subnet`), and the admin allowlist and rate limiter read the rightmost entry of the header as received (depth 1). That is safe only because every legitimate peer is the Container Apps Envoy, which appends the real client IP. Any other workload that can reach Traefik's port directly from inside the trusted range can forge an allowlisted IP. Observed with the real binary: a forged `X-Forwarded-For: 203.0.113.7` from a trusted peer reached the backend (200), while the same header from an untrusted peer got 403. Don't widen `trusted_proxy_ips`.

**The edge requires `edge.trusted_proxy_ips`.** With `edge.enabled`, a missing or empty value is a config error with no default filled in (#229), so a workload-profile stack can't silently get a subnet that doesn't contain Envoy. The message gives `100.100.0.0/17` as the observed example and says not to include the replica range (`100.100.192.0/19` observed). The sidecar's `litellm.proxy.trusted_proxy_ips` still defaults to the subnet; #229 stays open for it. Separately, a pinned `edge.revision_suffix` is checked against the whole revision name `<app>--<suffix>-p<8 hex>` (54 characters), with the app name from one helper shared with the deploy (#228, edge only; the sidecar's check still measures the suffix alone).

**Unproven until staging (still pending):**

- The Envoy peer range is confirmed for one environment only. #229 observed it on the ISS stack (workload-profile environment, 2026-11-06, Traefik v3.7.17, sidecar): Envoy connected from `100.100.0.0/17` (`ClientAddr` `100.100.0.86`, `100.100.0.246`), not from `networking.container_apps_subnet`, so the subnet default dropped `X-Forwarded-For` and returned 403 on every admin path. With `trusted_proxy_ips: [100.100.0.0/17]` `/ui/` returned 200 and the forged-XFF spoofing test passed: a request from replica A (`100.100.199.52`) straight to replica B (`100.100.192.43:8080/ui/`) with a forged allowlisted XFF got 403. Replicas sit in `100.100.192.0/19` and must stay untrusted. Microsoft reserves `100.100.0.0/17`, `100.100.128.0/19`, `100.100.160.0/19` and `100.100.192.0/19` but doesn't say which block Envoy uses, so the split is observed, not guaranteed. Consumption-only environments are untested. Other environments, and the edge itself, still need the check.
- No other workload in the environment may be able to reach Traefik's port directly and forge an allowlisted `X-Forwarded-For`. The README and infrastructure rule gate production on both checks. The spoofing test passed on ISS for the sidecar only.
- Streaming through real Azure ingress is untested, as is that the backends' platform FQDNs no longer answer from outside.
- Hostname moves: the deploy moves each hostname from its old app to Traefik and binds it (SNI) to the existing managed certificate named in `edge.custom_domains`. The manual `az containerapp hostname add` / `bind` is only for a hostname whose managed certificate doesn't exist yet. Whether Azure accepts the hostname on Traefik in the same deploy that removes it from the old app is unverified and is checked on staging first; if it refuses, re-running the deploy is the expected fix, which is also unverified. Each hostname has a planned outage window from removal to bind.
- DNS: each hostname's CNAME points at the old app's platform FQDN. Whether to repoint it to the Traefik app's FQDN, or Azure accepts the bind and renews the managed certificate with the old target, is unverified and checked on staging.
- MLflow's host policy: MLflow 3.5 and later returns 403 for a `Host` outside `MLFLOW_SERVER_ALLOWED_HOSTS` / `--allowed-hosts`. The deployed app sets neither (its image is `mlflow server` and `MLflowConfig.env_vars` defaults to `MLFLOW_HOST` only; compose passes `--allowed-hosts "*"`), and Traefik sends the internal FQDN as `Host`. Whether MLflow 3.6's default policy accepts it is unverified (MLflow 3.10's default, localhost and private IPs, would not). That `Host` only exists once the edge is on, so the staging flip is the test; if MLflow answers 403, set `MLFLOW_SERVER_ALLOWED_HOSTS` in `mlflow.env_vars` there and on ISS and prod before their flip. Setting `mlflow.env_vars` replaces the default mapping, so keep `MLFLOW_HOST: "0.0.0.0"` in it, and while the edge is off the list must also cover the hosts MLflow answers to today.
- Rollback needs two deploys: Pulumi creates and updates before it deletes, so one deploy cannot give the backends hostnames Traefik still holds. Deploy 1 sets `edge.enabled: false` with the backends' `custom_domains` still empty and restores the sidecar (`litellm.proxy.enabled: true`) if it was on, so LiteLLM's admin surface isn't open on its platform FQDN between the deploys; deploy 2 restores the `custom_domains`. Rehearse on staging.
- Callers of the backends' platform FQDNs break at the deploy that flips them to internal ingress, so they must be moved before it.

Evidence so far: the real Traefik v3.7.17 binary (`docker.io/library/traefik:v3.7.17@sha256:321153f6f732f912cf5c6f0597fe38743fc7895d482d7d8804a479ae0403e151`) in Docker against stub backends rendered from the edge renderer. Allowlisted and denied paths, double-slash paths, Host routing (a mixed-case Host with a port matched), unknown host 404, the rightmost-XFF cases above, and a 3-chunk SSE stream arriving 1 s apart through Traefik (not buffered) all behaved as designed. Offline comparison shows the template is unchanged with the proxy off.

**Known gap (owner decision pending):** with the edge on, LiteLLM and MLflow are reachable from any workload in the Container Apps environment (and the VNet) at their internal addresses without passing Traefik's allowlist or rate limits. LiteLLM still requires its key; MLflow has no login. The sidecar guarded in-environment callers too; the edge does not. Whether to add in-replica protection is undecided.

Behind the edge LiteLLM gets `PROXY_BASE_URL=https://<litellm.hostname>` (an operator value in `litellm.env_vars` wins), because it would otherwise build its UI login redirect from the internal `Host`. LiteLLM also `depends_on` the `mlflow-tracking-uri` secret, so the secret is written before LiteLLM is updated on the migration deploy. Whether the running revision then reads the new value is not verified; the rollout checks it after the deploy (restart the revision if needed, confirm a trace arrives).

Traefik rate limits are per replica and in memory, so they aren't global the way Redis-backed LiteLLM limits are. Per-host rules were left out of the sidecar. The `LITELLM_HOST` value in the config defaults has no effect.

**Sources:** issue #214; PR #217; src/llmaven/infrastructure/resources/traefik.py; tests/infrastructure/test_litellm_proxy.py; docs/superpowers/specs/2026-11-13-keycloak-azure-design.md; https://learn.microsoft.com/en-us/azure/container-apps/ingress-overview#http-headers

# Related Concepts
- [Production-readiness gaps are tracked in #193, and some settings do less than they suggest](../facts/production-readiness-gaps.md): Addresses the public-surface item in #193
