---
type: Architecture
title: "LiteLLM's config and logger are mounted at deploy time, not built into the image"
description: "Both are inline Container App secrets mounted together because LiteLLM finds callbacks beside its config, so changing them needs a deploy and, when pinned, a trigger bump."
tags: [litellm, container-apps, config]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:48Z" }
status: stable
code_refs: [src/llmaven/infrastructure/resources/helpers.py, src/llmaven/infrastructure/resources/adl_logger.py, docker/config.yaml]
sources:
  - resource: "PRs #40, #121, #123, #170, #212"
  - resource: src/llmaven/infrastructure/resources/helpers.py
  - resource: src/llmaven/infrastructure/resources/container_apps.py
---

**Status at e248584:** implemented.

The LiteLLM config and `adl_logger.py` don't ship in the image (#40). `create_litellm_app` reads both at deploy time and stores them as inline Container App secrets, mounted together at `/app/config/`, because LiteLLM only looks for custom callback modules in the same directory as its config (#123). Compose bind-mounts the same logger from `src/`.

Consequences:

- `src/llmaven/infrastructure/resources/adl_logger.py` runs inside the LiteLLM image, where the `llmaven` package isn't installed, so it can only import what `litellm.dockerfile` provides (inferred).
- Changing it needs a deploy, not an image build.
- A change to these files alone reaches running containers only when a new revision rolls. By default `REFRESH_TRIGGER` forces one. A pinned `litellm.refresh_trigger` needs a bump, and a set `revision_suffix` must change with any template change.
- `apply_redis_router_settings` edits only the mounted copy, so `docker/config.yaml` isn't the whole deployed config.
- Importing `AdlLogger` raises if `AZURE_STORAGE_CONNECTION_STRING` is missing, so a stack mounting it without that secret fails at startup.

**Sources:** PRs #40, #121, #123, #170, #212; src/llmaven/infrastructure/resources/helpers.py; src/llmaven/infrastructure/resources/container_apps.py

# Related Concepts
- [Making a deploy a true no-op: revisions, probes and the preview gate](../decisions/no-op-deploy-controls.md): Revision controls that decide when a config change takes effect
