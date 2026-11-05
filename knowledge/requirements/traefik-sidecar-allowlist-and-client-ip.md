---
type: Requirement
title: Path-level access control needs a sidecar with an allowlist (planned)
description: "Container Apps restricts by IP per app only, and front doors can be bypassed through the platform FQDN, so #214 proposes a Traefik sidecar; client IP handling must read the rightmost XFF entry."
tags: [traefik, litellm, security, container-apps]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:48Z" }
status: draft
code_refs: [src/llmaven/infrastructure/resources/container_apps.py, src/llmaven/infrastructure/resources/helpers.py]
stale_after: 2027-05-01
sources:
  - resource: "issue #214"
  - resource: "branch feat/214-traefik-sidecar (commits 3ca16f3, 360bfe0)"
  - resource: "https://learn.microsoft.com/en-us/azure/container-apps/ingress-overview#http-headers"
---

**Status at e248584:** planned. #214 is open, and the work is on branch `feat/214-traefik-sidecar`, not on main.

LiteLLM serves `/v1/*` and its admin surface on one port, and Container Apps ingress restricts by IP only, per app. A separate gateway, Front Door or Application Gateway was rejected because the platform FQDN would still reach the app and skip their rules.

Constraints on the design:

- Public paths must be an allowlist. A blocklist of admin paths can be bypassed through route aliases, double slashes, case or encoding.
- When the proxy is on, LiteLLM binds to `127.0.0.1` so other workloads in the environment can't reach port 4000. Probes then go through the sidecar.
- LiteLLM reads `--host` or `HOST`. Per the branch, `LITELLM_HOST` isn't used, even though the defaults still set it.
- TLS ends at the platform's Envoy, so the client IP comes from `X-Forwarded-For`, and Microsoft documents only the rightmost value as platform-supplied. Use `ipStrategy.depth: 1`. A wrong setting either blocks everyone or admits forged headers.
- With the proxy off, `--expect-no-changes` must still pass.

**Open gate:** nothing has run on live Container Apps. A staging capture must confirm the real ingress peer range, and trusting a whole subnet needs a test that another workload can't reach the proxy port directly and forge the header.

**Sources:** issue #214; branch feat/214-traefik-sidecar (commits 3ca16f3, 360bfe0); https://learn.microsoft.com/en-us/azure/container-apps/ingress-overview#http-headers

# Related Concepts
- [Production-readiness gaps are tracked in #193, and some settings do less than they suggest](../facts/production-readiness-gaps.md): Addresses the public-surface item in #193
