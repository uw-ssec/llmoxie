---
type: Requirement
title: Path-level access control uses a Traefik edge (or sidecar) with an allowlist
description: A standalone Traefik edge (or the older sidecar) enforces path allowlists because Container Apps restricts by IP per app; the trusted-peer and forged-header gates are unproven on Azure.
tags: [traefik, litellm, security, container-apps]
generated: { by: "claude-code:claude-sonnet-5-5", at: "2026-11-13T21:04:51Z" }
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

**Trust model (edge and sidecar).** Traefik keeps `X-Forwarded-For` only from peers in `trusted_proxy_ips` (edge default: `networking.container_apps_subnet`), and the admin allowlist and rate limiter read the rightmost entry of the header as received (depth 1). That is safe only because every legitimate peer is the Container Apps Envoy, which appends the real client IP. Any other workload that can reach Traefik's port directly from inside the trusted range can forge an allowlisted IP. Observed with the real binary: a forged `X-Forwarded-For: 203.0.113.7` from a trusted peer reached the backend (200), while the same header from an untrusted peer got 403. Don't widen `trusted_proxy_ips`.

**Unproven until staging (still pending):**

- The Envoy peer range on Azure is unconfirmed. The Envoy peer must be inside `trusted_proxy_ips`.
- No other workload in the environment may be able to reach Traefik's port directly and forge an allowlisted `X-Forwarded-For`. The README and infrastructure rule gate production on both checks.
- Streaming through real Azure ingress is untested, as is that the backends' platform FQDNs no longer answer from outside.
- Hostname moves: the deploy moves each hostname from its old app to Traefik and binds it (SNI) to the existing managed certificate named in `edge.custom_domains`. The manual `az containerapp hostname add` / `bind` is only for a hostname whose managed certificate doesn't exist yet. Whether Azure accepts the hostname on Traefik in the same deploy that removes it from the old app is unverified and is checked on staging first; if it refuses, re-running the deploy is the expected fix, which is also unverified. Each hostname has a planned outage window from removal to bind.
- DNS: each hostname's CNAME points at the old app's platform FQDN. Whether to repoint it to the Traefik app's FQDN, or Azure accepts the bind and renews the managed certificate with the old target, is unverified and checked on staging.
- MLflow's host policy: MLflow 3.5 and later returns 403 for a `Host` outside `MLFLOW_SERVER_ALLOWED_HOSTS` / `--allowed-hosts`. The deployed app sets neither (its image is `mlflow server` and `MLflowConfig.env_vars` defaults to `MLFLOW_HOST` only; compose passes `--allowed-hosts "*"`), and Traefik sends the internal FQDN as `Host`. Whether MLflow's default policy accepts it is unverified; check on staging and set `MLFLOW_SERVER_ALLOWED_HOSTS` in `mlflow.env_vars` if it returns 403.
- Rollback needs two deploys: Pulumi creates and updates before it deletes, so one deploy cannot give the backends hostnames Traefik still holds. Deploy 1 sets `edge.enabled: false` with the backends' `custom_domains` still empty; deploy 2 restores them (and the sidecar). Rehearse on staging.
- Callers of the backends' platform FQDNs break at the deploy that flips them to internal ingress, so they must be moved before it.

Evidence so far: the real Traefik v3.7.17 binary (`docker.io/library/traefik:v3.7.17@sha256:321153f6f732f912cf5c6f0597fe38743fc7895d482d7d8804a479ae0403e151`) in Docker against stub backends rendered from the edge renderer. Allowlisted and denied paths, double-slash paths, Host routing (a mixed-case Host with a port matched), unknown host 404, the rightmost-XFF cases above, and a 3-chunk SSE stream arriving 1 s apart through Traefik (not buffered) all behaved as designed. Offline comparison shows the template is unchanged with the proxy off.

**Known gap (owner decision pending):** with the edge on, LiteLLM and MLflow are reachable from any workload in the Container Apps environment (and the VNet) at their internal addresses without passing Traefik's allowlist or rate limits. LiteLLM still requires its key; MLflow has no login. The sidecar guarded in-environment callers too; the edge does not. Whether to add in-replica protection is undecided.

Behind the edge LiteLLM gets `PROXY_BASE_URL=https://<litellm.hostname>` (an operator value in `litellm.env_vars` wins), because it would otherwise build its UI login redirect from the internal `Host`. LiteLLM also waits for the `mlflow-tracking-uri` secret, so it does not start on the old public MLflow URI on the migration deploy.

Traefik rate limits are per replica and in memory, so they aren't global the way Redis-backed LiteLLM limits are. Per-host rules were left out of the sidecar. The `LITELLM_HOST` value in the config defaults has no effect.

**Sources:** issue #214; PR #217; src/llmaven/infrastructure/resources/traefik.py; tests/infrastructure/test_litellm_proxy.py; docs/superpowers/specs/2026-11-13-keycloak-azure-design.md; https://learn.microsoft.com/en-us/azure/container-apps/ingress-overview#http-headers

# Related Concepts
- [Production-readiness gaps are tracked in #193, and some settings do less than they suggest](../facts/production-readiness-gaps.md): Addresses the public-surface item in #193
