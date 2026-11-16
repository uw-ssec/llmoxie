---
type: Fact
title: "Keycloak's temporary admin is the realm job's login, so don't delete it"
description: "Keycloak asks to replace the bootstrap admin, but the realm job signs in as admin with keycloak-admin-password on every deploy, so deleting it breaks the next deploy."
tags: [keycloak, realm-job, admin]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-16T01:52:25Z" }
status: stable
governance: constraint
code_refs:
  - "src/llmaven/infrastructure/resources/keycloak.py"
---

**Status at 2026-11-15:** current behavior; seen on dev.

Keycloak 26 creates the bootstrap user `admin` from `KC_BOOTSTRAP_ADMIN_USERNAME`/`KC_BOOTSTRAP_ADMIN_PASSWORD` (password in Key Vault secret `keycloak-admin-password`). Its admin console then shows "You are logged in as a temporary admin user. To harden security, create a permanent admin account and delete the temporary one."

Don't follow the second half. The realm job (keycloak-config-cli) authenticates with `KEYCLOAK_USER=admin` and `KEYCLOAK_PASSWORD` from the same secret (`resources/keycloak.py`), and `llmaven infra deploy` runs that job after every `up`. With `admin` gone, every deploy would end in "Infrastructure deployed, but the Keycloak realm was not applied". Whether Keycloak would recreate the bootstrap user on a restart was not checked.

A personal admin is fine: a user in the `master` realm with the `admin` realm role. Users who sign in to the gated apps go in the app realm (`keycloak.realm.name`), not `master`.

Giving the realm job its own service-account client (client credentials) instead of the bootstrap user would let `admin` be deleted; that is not built.

**Sources:** `src/llmaven/infrastructure/resources/keycloak.py`; dev rollout 2026-11-15

# Related Concepts
- [Keycloak is the identity provider](../decisions/keycloak-identity-provider.md): Operational constraint of the realm job
