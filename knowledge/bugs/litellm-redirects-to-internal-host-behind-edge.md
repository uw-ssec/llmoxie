---
type: Bug
title: "LiteLLM's own redirects pointed at its internal address behind the edge"
description: "Starlette builds trailing-slash redirects from Host, which the edge sets to LiteLLM's internal FQDN, so PROXY_BASE_URL alone left /ui and the SSO start on an Azure 404 until fork #13."
tags: [litellm, edge, traefik, sso]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-16T01:52:25Z" }
status: stable
code_refs:
  - "docker/dockerfiles/litellm.dockerfile"
  - "src/llmaven/infrastructure/resources/traefik.py"
---

**Status at 2026-11-15:** fixed in the LiteLLM fork (uw-ssec/llmoxie-litellm#13), pinned in `docker/dockerfiles/litellm.dockerfile` and deployed to dev.

Behind the edge, Traefik sends LiteLLM its internal FQDN as `Host` (`passHostHeader: false`, because the environment's internal Envoy routes by `Host`). The stack sets `PROXY_BASE_URL=https://<litellm.hostname>`, which covers the SSO callback URL LiteLLM builds itself. It does not cover redirects Starlette builds from the request URL: the trailing-slash redirects (`/ui` to `/ui/`, `/sso/key/generate/` to `/sso/key/generate`, `/key/list/`). Those went to `http://<app>.internal.<domain>/...`, which the browser cannot reach, so it showed Azure's "This Container App is stopped or does not exist" 404.

It surfaced on dev once `AUTO_REDIRECT_UI_LOGIN_TO_SSO=true` was set, because the UI's auto-redirect requests `/sso/key/generate/` with a trailing slash. A user typing `/ui` without the slash hit it too.

**Fix:** `PublicRedirectMiddleware` in the fork (`litellm/proxy/middleware/public_redirect_middleware.py`) rewrites the scheme and host of any 3xx `Location` that points back at the request's own `Host` to those of `PROXY_BASE_URL`. Redirects to other hosts (Keycloak) and setups without `PROXY_BASE_URL` are untouched. Shown on dev: `/key/list/` went from `307 http://...internal.../key/list` to `307 https://dev.llm.uwssec.org/key/list`.

**Rejected:** fixing it in Traefik. Traefik cannot rewrite a `Location` header without a plugin, and stripping slashes for known paths at the edge would miss any other redirect.

MLflow sits behind the edge the same way and has not been checked for this, since MLflow is off in dev.

**Sources:** uw-ssec/llmoxie-litellm#13; LiteLLM revision logs on dev; `.agents/rules/infrastructure.md` (edge section)

# Related Concepts
- [LiteLLM is pinned by version and digest, and upgrades across migrations are one-way](../decisions/litellm-image-digest-pin-and-one-way-upgrade.md): The fix ships in the pinned fork build
- [Keycloak is the identity provider](../decisions/keycloak-identity-provider.md): Surfaced by the LiteLLM SSO login behind the edge
