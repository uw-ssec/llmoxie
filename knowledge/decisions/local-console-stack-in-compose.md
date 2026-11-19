---
type: Decision
title: "docker/docker-compose.yml runs the console and everything it needs, as a stopgap until the Helm chart"
description: "Keycloak, Traefik, oauth2-proxy gates, Mailpit, okf-hub and the console sit in the main compose file so the console suite runs locally and in CI's console-e2e job; no ceil-dlp, so test_dlp.py is left out."
tags: [docker, compose, console, testing, ci]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-19T05:42:38Z" }
status: stable
governance: context
code_refs: [docker/docker-compose.yml, docker/keycloak/realm-litellm.json, docker/traefik/dynamic.yml, docker/create_service_dbs.sql, .github/workflows/ci.yml]
sources:
  - resource: "https://github.com/uw-ssec/llmoxie/issues/236"
---

**Status:** implemented on branch `feat/local-console-stack` (from `knowledge-hub-on-azure`), 2026-11-18.

## Decision

On 2026-11-18 the owner asked for a local compose stack that both CI (the console's end-to-end suite) and contributors can use, as a stopgap until the Helm chart (#236) replaces docker-compose as the laptop and CI stack. Given the choice of a separate overlay file or the main file, the owner chose the main file `docker/docker-compose.yml`, with the guard in `tests/test_platform_scope.py` listing the new services by name (see [platform-only scope](platform-only-scope.md)). So `pixi run -e llmaven up` starts everything.

It was ported from the owner's private stack (`~/Agent-Workspace/litellm-keycloak`), adapted to llmoxie: llmoxie's LiteLLM fork image and request logger, Keycloak 26.5.5 (the version `keycloak.dockerfile` builds on), the okf-hub container dev runs, and client names as on Azure (`mlflow-gate`, `litellm-gate`). Left out: ceil-dlp (llmoxie does not deploy it, so `test_dlp.py` is ignored by the `console-tests` service), the agent runner and the Traefik dashboard.

## Why it is built this way

- `db-init` re-runs the idempotent `create_service_dbs.sql` on every start, and `console-db` runs `services/console/db_setup.py`, the job Azure runs, rather than an initdb script: initdb scripts run only on an empty volume, and contributors already have a `llmaven_postgres_data` volume.
- Keycloak runs `start-dev --import-realm` with no volume, so the realm file in the repo always applies when the container is recreated. Accounts made at run time go with it.
- LiteLLM's UI signs in through Keycloak with the same GENERIC_* settings and role mapping as `main.py` on Azure, and `disable_password_login_when_sso_enabled` is on.
- Every secret in the file is a local dev value, but no literal password: GitGuardian flags `*_PASSWORD: <word>` lines and Keycloak user passwords (it failed PR #254 on two role passwords in the compose file and a test user's password in the realm, so the commit was rewritten). The console's and hub's database roles reuse `POSTGRES_PASSWORD` from `docker/.env`; `LITELLM_MASTER_KEY` and `OKF_HUB_MASTER_KEY_HEX` come from there too, and CI generates both per run. The test user bob was dropped (the suite never used it); `alice` / `alice123` stays because the suite signs in with it, and was not flagged. OAuth client secrets such as `console-dev-secret` were not flagged either.

## Traps

- The LiteLLM fork image is amd64 only. On an Apple Silicon Mac under Colima's QEMU, `litellm.dockerfile`'s import check timed out at 600 s, and the failed build filled the Colima disk. The local check on 2026-11-18 used a native arm64 build of a near-identical fork (1.108.5) through a scratch override; CI builds the real image on amd64.
- `docker/config.yaml` is also the base of the LiteLLM config Azure deploys (`litellm.config_file`; `tests/infrastructure` check its render). Local-only LiteLLM settings (the `fake-gpt` mock model the suite expects, and `disable_password_login_when_sso_enabled`, which Azure adds itself) are added at container start by `docker/local_litellm_config.py` into `/app/local-config.yaml`, next to the mounted logger modules LiteLLM resolves relative to its config. Putting them in `config.yaml` failed three infrastructure tests and would have deployed the mock model.
- Traefik renders `traefik/dynamic.yml` as a Go template for MLflow's port (`{{ env "MLFLOW_PORT" }}`).

## How it was checked

Locally, 2026-11-18, all 15 services healthy, suite: 300 passed, 15 skipped (`test_db_setup.py` needs Docker on the host), 1 failed. The failure is real: `test_request_logs_carry_no_provider_key_and_no_email` found the organization's provider key in the Azurite request log, because llmoxie's `adl_logger.py` has no redaction; the owner's private stack had added it (`_redact`/`_serialize`) and it never came back. Until that is fixed the console-e2e job fails.

**Sources:** owner request and choice in the 2026-11-18 session; issue #236

# Related Concepts
- [The repo is the LiteLLM and MLflow platform and its console; RAG lives in llmoxie-rag](platform-only-scope.md): The guard that names the stack's services, and the owner's choice of one compose file
