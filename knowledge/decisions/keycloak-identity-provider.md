---
type: Decision
title: Keycloak is the identity provider
description: "Keycloak, with its realm applied from the YAML by keycloak-config-cli, replaces the Entra External ID plan; keycloak_db rides the Postgres point-in-time backups."
tags: [keycloak, identity, auth, infra]
generated: { by: "claude-code:claude-sonnet-5-5", at: "2026-11-14T00:45:57Z" }
status: stable
governance: constraint
code_refs:
  - src/llmaven/infrastructure/resources/keycloak.py
  - src/llmaven/infrastructure/resources/keycloak_realm.py
  - docker/dockerfiles/keycloak.dockerfile
---

## Context

The stack needs sign-in for the MLflow and LiteLLM UIs and an identity provider for the console. The unmerged Azure console design planned Entra External ID (decision 10, "No Keycloak"); the spec `docs/superpowers/specs/2026-11-13-keycloak-azure-design.md` replaces its identity section.

## Decision

Run Keycloak 26.5.5 (optimized, `--cache=local`, one replica) as a Container App behind the Traefik edge, with `keycloak_db` on the stack's Postgres server.

- Why Keycloak over Entra External ID: the console's broker creates one Keycloak client per organization at runtime, which Entra does not offer. Keycloak will also broker CILogon later, as an `identityProviders` entry in the realm, so people sign in with their institution while their Keycloak user (and `sub`) stays stable.
- The realm lives in the stack YAML (`keycloak.realm`, `overrides`, `secret_refs`) and is rendered by `resources/keycloak_realm.py`. keycloak-config-cli applies it in a Container Apps Job that `llmaven infra deploy` starts after each successful `up`, with `IMPORT_MANAGED_*=no-delete` so runtime-created clients survive. Removing a client from the document is a manual step.
- The realm name is part of the issuer and permanent; `deploy` refuses to change it.
- `keycloak_db` is covered by the Postgres server's point-in-time backups (`database.backup_retention_days`).
- oauth2-proxy apps put the Keycloak login in front of MLflow and LiteLLM; LiteLLM's Admin UI uses SSO with `proxy_admin` mapped from the `litellm-admin` realm role.

## Rejected alternatives

- Realm import at Keycloak startup: it only imports a realm that doesn't exist yet, so later changes would be manual and untracked.
- The Pulumi Keycloak provider: it needs the admin API reachable from the deploying machine during the deploy that creates Keycloak.
- Entra External ID (the unmerged Azure console design's choice): it does not offer per-organization clients created at runtime or CILogon brokering.

## Caveats

- Removing `litellm-admin` from a user blocks the UI gate but does not demote `proxy_admin` in LiteLLM or revoke keys they minted.
- Keycloak and the login apps are internal-ingress apps reachable from inside the environment without passing Traefik, the same open trust-boundary decision as stage 1.
- Verified only locally with real containers over plain HTTP; TLS on internal FQDNs, Envoy peers and the hostname move are unverified until staging.

See `.agents/rules/infrastructure.md`, "Keycloak and the logins".

# Related Concepts
- [Path-level access control uses a Traefik edge (or sidecar) with an allowlist](../requirements/traefik-sidecar-allowlist-and-client-ip.md): The edge allowlist and client-IP trust the Keycloak admin console and login routes depend on
- [LiteLLM stays as the gateway; OSS limits shape what must be built around it](stay-on-oss-litellm-gateway.md): LiteLLM SSO for the Admin UI uses the uw-ssec fork and Keycloak
