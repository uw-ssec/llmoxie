---
type: Fact
title: "The LiteLLM image has no pip, wget or curl, and needs mlflow-skinny"
description: "Since v1.106.x the image is a uv venv, so the Dockerfile uses ensurepip and re-pins litellm; full mlflow caps cryptography below 47 and reintroduces advisories."
tags: [litellm, docker, mlflow]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:48Z" }
status: stable
code_refs: [docker/dockerfiles/litellm.dockerfile, docker/dockerfiles/mlflow.dockerfile, docker/docker-compose.yml]
sources:
  - resource: "PRs #148, #199"
  - resource: "issue #197"
  - resource: docker/dockerfiles/litellm.dockerfile
  - resource: docker/docker-compose.yml
  - resource: pixi.toml
---

**Status at e248584:** implemented.

- The 1.106.x image has a uv-built venv with no `pip`, so `RUN pip install` fails. The Dockerfile bootstraps with `python -m ensurepip`, chosen over adding a second installer image.
- It re-pins `litellm==1.106.6` so a dependency conflict fails the build instead of replacing the signature-verified package.
- Full `mlflow==3.6.0` caps `cryptography<47`, which downgraded the base image's 50.0.0 and reintroduced four advisories. `mlflow-skinny` is enough for LiteLLM's callback. Using `mlflow>=3.16` was rejected because it would put a newer client in front of the 3.6.0 server.
- After layering packages on a signed base, diff versions to catch downgrades. `packaging` still moves from 26.2 to 25.0.
- The image has no `wget` or `curl`. The old compose healthcheck called `wget`, so the container always looked unhealthy and `docker compose up --wait` exited 1 while `/health/liveliness` returned 200 (#197, #199). Probes run in Python `urllib`, and any new probe should assume Python only.

`pixi.toml`'s `mlflow==3.10.0` is a separate dev-environment pin used by `infra extract`. It isn't the deployed version.

**Sources:** PRs #148, #199; issue #197; docker/dockerfiles/litellm.dockerfile; docker/docker-compose.yml; pixi.toml

# Related Concepts
- [LiteLLM is pinned by version and digest, and upgrades across migrations are one-way](../decisions/litellm-image-digest-pin-and-one-way-upgrade.md): How the pinned image is extended
