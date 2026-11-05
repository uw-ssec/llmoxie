---
type: Bug
title: "infra init and schema defaults still point at frozen llmaven-* images"
description: "CI publishes ghcr.io/uw-ssec/llmoxie-*, but defaults name ghcr.io/uw-ssec/llmaven-*:latest, so a freshly generated config gets images that no longer receive releases."
tags: [rebrand, ghcr, config]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:48Z" }
status: stable
code_refs: [src/llmaven/infrastructure/config/schema.py, src/llmaven/infrastructure/config/defaults.py, .github/workflows/build-services.yml]
sources:
  - resource: "issues #187, #193"
  - resource: "PRs #173, #186"
  - resource: src/llmaven/infrastructure/config/schema.py
  - resource: src/llmaven/infrastructure/config/defaults.py
  - resource: .github/workflows/build-services.yml
---

**Status at e248584:** open.

`build-services.yml` names images `${{ github.repository }}-<service>`, which since the repo rename gives `llmoxie-{mlflow,litellm,backup}`. The schema and `infra init` defaults still say `ghcr.io/uw-ssec/llmaven-*:latest`, and per #187 the old packages are frozen. A config relying on defaults therefore gets an image from before the rename, such as one without the LiteLLM 1.106.6 upgrade. A deployment that pins `llmoxie-*` doesn't show the bug, which is why a working stack doesn't reveal it.

The defaults also name `llmaven-api`, which isn't published and whose API #186 removed. The #187 audits say to drop `LLMavenAPIConfig` and `llmaven_api` rather than rename them.

Until this is fixed, pin `llmoxie-*` release tags explicitly in deployment configs.

**Sources:** issues #187, #193; PRs #173, #186; src/llmaven/infrastructure/config/schema.py; src/llmaven/infrastructure/config/defaults.py; .github/workflows/build-services.yml

# Related Concepts
- [The llmoxie rebrand must not rename identifiers that carry live state](../decisions/rebrand-keeps-deployed-identifiers.md): Part of the unfinished rename
