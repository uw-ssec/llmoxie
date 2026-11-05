---
type: Decision
title: The repo is the LiteLLM and MLflow platform only; RAG lives in llmoxie-rag
description: "The Sunset RAG milestone removed the REST API, UI, agentic RAG and Qdrant, and tests/test_platform_scope.py fails if they return."
tags: [scope, sunset-rag, architecture]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:47Z" }
status: stable
governance: constraint
code_refs:
  - "tests/test_platform_scope.py"
  - "src/llmaven/cli.py"
  - "docker/docker-compose.yml"
  - "pixi.toml"
  - "pyproject.toml"
sources:
  - resource: "issues #174-#180"
  - resource: "PRs #186, #188, #189, #190, #191, #194, #202"
  - resource: "PRs #128, #130, #137, #143, #144, #145, #147"
  - resource: "tests/test_platform_scope.py"
  - resource: "issue #193"
---

**Status at e248584:** implemented.

`llmaven` is a CLI that stands up the LiteLLM gateway and MLflow. The REST API and Streamlit UI (#186), agentic RAG (#188), the RAG and ML dependencies, legacy notebooks, `eval/` and the `proxy` and `frontend` Pixi features (#189), Qdrant (#190), RAG-era CI and the SciPy 2024 devcontainer (#191), and `archive/` (#202) are all gone. Agentic RAG moved with its git history to `uw-ssec/llmoxie-rag`.

`tests/test_platform_scope.py` is a deliberate guard. It pins the CLI to `infra`, `backup-infra` and `version`, compose to `db`, `mlflow`, `azurite` and `litellm`, and bans RAG and ML packages from the manifests. A failure there means a removed surface is coming back, so don't fix it by loosening the guard. References in that file are guards, not leftovers.

What the guard doesn't cover: `LLMavenAPIConfig` and the `llmaven_api` block survive in the config schema and defaults, and #193 tracks them as leftovers.

New RAG work belongs in llmoxie-rag. RAG-era PRs here were closed with a redirect because the code they touched left this repo, not because the ideas were judged bad (#128, #130, #143, #144, #145, #147). #137 (an e2e smoke workflow) would have failed on first run because `llmaven server serve` no longer exists. Unused surfaces are removed, not archived: the history is in git (#189, #202).

The `default` Pixi environment was kept on purpose; removing it is a separate change (#202).

**Sources:** issues #174-#180; PRs #186, #188, #189, #190, #191, #194, #202; PRs #128, #130, #137, #143, #144, #145, #147; tests/test_platform_scope.py; issue #193
