---
type: Decision
title: The repo is the LiteLLM and MLflow platform and its console; RAG lives in llmoxie-rag
description: "Sunset RAG removed the REST API, Streamlit UI, agentic RAG and Qdrant; the console in services/console is in scope since 2026-11-12, outside what tests/test_platform_scope.py checks."
tags: [scope, sunset-rag, architecture, console]
generated: { by: "claude-code:claude-fable-5-2", at: "2026-11-13T04:25:52Z" }
status: stable
governance: constraint
code_refs: [tests/test_platform_scope.py, src/llmaven/cli.py, docker/docker-compose.yml, pixi.toml, pyproject.toml]
sources:
  - resource: "issues #174-#180"
  - resource: "PRs #186, #188, #189, #190, #191, #194, #202"
  - resource: "PRs #128, #130, #137, #143, #144, #145, #147"
  - resource: tests/test_platform_scope.py
  - resource: "issue #193"
  - resource: "owner decision in the 2026-11-12 session"
  - resource: services/console/README.md
---

**Status at e248584:** implemented. **Amended 2026-11-12:** the console is part of the platform; see "The console" below.

`llmaven` is a CLI that stands up the LiteLLM gateway and MLflow. The REST API and Streamlit UI (#186), agentic RAG (#188), the RAG and ML dependencies, legacy notebooks, `eval/` and the `proxy` and `frontend` Pixi features (#189), Qdrant (#190), RAG-era CI and the SciPy 2024 devcontainer (#191), and `archive/` (#202) are all gone. Agentic RAG moved with its git history to `uw-ssec/llmoxie-rag`.

## The console

On 2026-11-12 the owner decided that the LLMoxie console is part of the platform. It is the front door to the LiteLLM gateway this repo deploys: organizations manage their own models, teams and API keys through it, so LiteLLM's own UI and management API can stay internal. It is therefore developed and released alongside the gateway, in `services/console/`.

This does not reopen what Sunset RAG removed. The console is a separate service with its own image (`console-web`, `console-broker`, `console-init`). It is not the old REST API or Streamlit UI, it adds no `llmaven` CLI command, and the `llmaven` package does not depend on it. RAG still belongs in llmoxie-rag.

How it arrived, on the `llmoxie-console` branch (8827d7d to 01ae504):

- Copied from `uw-ssec/llmoxie-console@feat/console` (d1056d5) as plain files, not as a git subtree or submodule. Its earlier history stays in that repository.
- Without that repository's scaffolding: its agent rules and skills, GitHub workflows, dev container, pre-commit config, community files and its empty OKF bundle were dropped, and its Pixi manifest keeps only the Docker tasks.
- The root `.pre-commit-config.yaml` excludes `services/console/`. The files were imported as-is and do not pass this repo's ruff and prettier hooks; prettier cannot parse two of the Jinja templates.
- Its tests are end to end and need a running stack (Keycloak, LiteLLM, Postgres, Mailpit), so `pytest tests/` and `verify` do not run them. No workflow in this repo builds the console image or runs its tests yet.

## The guard

`tests/test_platform_scope.py` is a deliberate guard. It pins the CLI to `infra`, `backup-infra` and `version`, compose to `db`, `mlflow`, `azurite` and `litellm`, and bans RAG and ML packages from the manifests. A failure there means a removed surface is coming back, so don't fix it by loosening the guard. References in that file are guards, not leftovers.

The guard passes with the console present because it reads only the root `pyproject.toml` and `pixi.toml`. It does not see `services/console/requirements.txt`, where the console pins `fastapi` and `uvicorn`, two of the banned packages. Keep the console's dependencies there: declaring them in the root manifests fails the guard. Adding the console to `docker/docker-compose.yml` fails it too, because compose is pinned to four services. Whether the guard should change to let the console into the local stack has not been decided; ask the owner before touching it.

What the guard doesn't cover: `LLMavenAPIConfig` and the `llmaven_api` block survive in the config schema and defaults, and #193 tracks them as leftovers.

New RAG work belongs in llmoxie-rag. RAG-era PRs here were closed with a redirect because the code they touched left this repo, not because the ideas were judged bad (#128, #130, #143, #144, #145, #147). #137 (an e2e smoke workflow) would have failed on first run because `llmaven server serve` no longer exists. Unused surfaces are removed, not archived: the history is in git (#189, #202).

The `default` Pixi environment was kept on purpose; removing it is a separate change (#202).

## Superseded

Until 2026-11-12 this decision read "the repo is the LiteLLM and MLflow platform only", and any UI counted as a removed surface. The removal of the Streamlit UI and REST API (#186) stands. What changed is that the console, a different service, is now in scope.

**Sources:** issues #174-#180; PRs #186, #188, #189, #190, #191, #194, #202; PRs #128, #130, #137, #143, #144, #145, #147; tests/test_platform_scope.py; issue #193; owner decision in the 2026-11-12 session; services/console/README.md
