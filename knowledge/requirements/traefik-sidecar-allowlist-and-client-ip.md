---
type: Requirement
title: Path-level access control uses a Traefik sidecar with an allowlist
description: "Container Apps restricts by IP per app only and front doors can be bypassed through the platform FQDN, so #217 added an optional sidecar; the trusted-peer and forged-header gates are unproven on Azure."
tags: [traefik, litellm, security, container-apps]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:36:29Z" }
status: stable
code_refs: [src/llmaven/infrastructure/resources/traefik.py, src/llmaven/infrastructure/resources/helpers.py, src/llmaven/infrastructure/resources/container_apps.py, tests/infrastructure/test_litellm_proxy.py]
stale_after: 2027-05-01
sources:
  - resource: "issue #214"
  - resource: "PR #217"
  - resource: src/llmaven/infrastructure/resources/traefik.py
  - resource: tests/infrastructure/test_litellm_proxy.py
  - resource: "https://learn.microsoft.com/en-us/azure/container-apps/ingress-overview#http-headers"
---

**Status at dd91796:** implemented and off by default (#217, closing #214). No live Container Apps test has run. `.agents/rules/infrastructure.md` and the README cover how it works; this concept covers why, and what's unproven.

LiteLLM serves `/v1/*` and its admin surface on one port, and Container Apps ingress restricts by IP only, per app. A separate gateway, Front Door or Application Gateway was rejected because the platform FQDN would still reach the app and skip their rules.

Public paths must be an allowlist of exact paths. A blocklist of admin paths can be bypassed through route aliases, double slashes, case or encoding. Don't add prefix routes, since LiteLLM serves management routes under `/v1/` and `/health/`.

**Unproven until staging:**

- The default `trusted_proxy_ips` is the Container Apps subnet. The real Envoy peer range hasn't been confirmed on Azure.
- Trusting a whole subnet needs a test that another workload can't reach the replica's proxy port directly and forge an allowlisted `X-Forwarded-For`. The README gates production on both checks.
- Streaming through real ingress is untested.

Evidence so far is the real Traefik v3.7.17 binary against a fake backend, plus offline comparison showing the template is unchanged with the proxy off.

Traefik rate limits are per replica and in memory, so they aren't global the way Redis-backed LiteLLM limits are. Per-host rules were left out. The `LITELLM_HOST` value in the config defaults has no effect.

**Sources:** issue #214; PR #217; src/llmaven/infrastructure/resources/traefik.py; tests/infrastructure/test_litellm_proxy.py; https://learn.microsoft.com/en-us/azure/container-apps/ingress-overview#http-headers

# Related Concepts
- [Production-readiness gaps are tracked in #193, and some settings do less than they suggest](../facts/production-readiness-gaps.md): Addresses the public-surface item in #193
