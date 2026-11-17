---
type: Decision
title: "The console runs on the Azure stack from a console block, with a vault per container and mail through ACS"
description: "The console deploys from the off-by-default console block: knowledge optional, Azure Communication Services mail, one identity and one access-policy vault per container, two LiteLLM hosts, invitee accounts from a CSV."
tags: [console, azure, infra, mail, key-vault]
generated: { by: "claude-code:claude-sonnet-5-5", at: "2026-11-16T07:25:50Z" }
status: stable
---

## Context

The console ran only in the local proof of concept. Spec: `docs/superpowers/specs/2026-11-15-console-azure-design.md`. Operator steps: `.agents/rules/infrastructure.md`, "The console". Keycloak is the identity provider (`decisions/keycloak-identity-provider`).

## Decision

- **Deployed by a `console` block in the stack program**, off by default. A hand-deployed try-out or a separate Pulumi stack was rejected: what runs on dev is what staging and prod run, and a separate stack would still need this program's edge and realm.
- **Knowledge is optional.** The hub is not deployed; with `KNOWLEDGE_HUB_URL` unset the console runs without any `KEYCLOAK_*` or `KNOWLEDGE_*` setting. The hub adds on later without rework.
- **Mail through Azure Communication Services** from a customer-managed domain, sent with the Communication Service connection string kept in the broker's vault. An SSEC/UW mail provider and Mailpit in dev were rejected. `console.mail.domain_verified` decides whether the domain is linked, because Azure links only a verified domain.
- **One identity per container, each reading only its own secrets,** because the main vault grants all or nothing. Each gets its own access-policy vault with the policies set inline when the vault is created (the identity and the deployer). An RBAC vault with per-secret role assignments was rejected: the deployer is Contributor and cannot make role assignments.
- **Two LiteLLM hosts.** `litellm.hostname` stays the gateway (only AI and health paths, API clients keep working); `litellm.admin_hostname` carries the UI and management API behind the Keycloak login. One host split by path was rejected.
- **Invitee accounts are made by an operator from a CSV** (`llmaven infra keycloak-users`). Self sign-up needs Keycloak SMTP, which on ACS needs an Entra app and a role assignment; sign in with GitHub is a later option.

## Caveats

- Unverified until dev: ARM-created database ownership and the CONNECT revoke, the Azure Files mount options, a real ACS send, the email claims in the console token, Contributor creating everything, and re-enabling after a disable (soft-deleted vault names stay reserved until recovered or purged).
- The console storage account and vaults set no network ACLs; with private endpoints on they stay public.
- Turning the console off keeps `console_db` out of Pulumi state; turning it back on needs it imported.

See `.agents/rules/infrastructure.md`, "The console".

# Related Concepts
- [The deployer is Contributor and cannot make Azure role assignments](../facts/deployer-is-contributor-no-role-assignments.md): The console's vault-per-container design follows from the deployer having no role-assignment rights
- [Keycloak is the identity provider](keycloak-identity-provider.md): The console signs in through the Keycloak realm and adds its own client there
- [Key Vault access policies get wiped by two separate mechanisms](../bugs/key-vault-access-policy-replace.md): Console vaults set access policies inline at creation, avoiding the AccessPolicy replace behavior
