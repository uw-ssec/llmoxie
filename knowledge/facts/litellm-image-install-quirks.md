---
type: Fact
title: "The LiteLLM image has no pip, wget or curl, and needs mlflow-skinny"
description: "Since v1.106.x the image is a uv venv, so the Dockerfile uses ensurepip; on the fork it asserts the SSO cap is gone instead of re-pinning litellm, and full mlflow caps cryptography below 47."
tags: [litellm, docker, mlflow]
generated: { by: "claude-code:claude-sonnet-5-5", at: "2026-11-13T23:41:06Z" }
status: stable
code_refs: [docker/dockerfiles/litellm.dockerfile, docker/dockerfiles/mlflow.dockerfile, docker/docker-compose.yml]
sources:
  - resource: "PRs #148, #199"
  - resource: "issue #197"
  - resource: docker/dockerfiles/litellm.dockerfile
  - resource: docker/docker-compose.yml
  - resource: pixi.toml
---

**Status at a7e7d32:** implemented. Re-checked on v1.108.6 (#235).

- Since 1.106.x the image has a uv-built venv with no `pip`, so `RUN pip install` fails. The Dockerfile bootstraps with `python -m ensurepip`, chosen over adding a second installer image. This still works on 1.108.6.
- The base is now the uw-ssec fork. The Dockerfile no longer re-pins `litellm==`: that would replace the fork's patched package with upstream's and restore the SSO cap. Instead a build-time `python -c` asserts `_raise_if_sso_exceeds_free_user_limit` is absent from `ui_sso`, which fails on the stock image (verified). The fork already ships `azure-storage-blob` 12.28.0 and `azure-identity` 1.25.2, so only `mlflow-skinny==3.6.0` is installed; the fork's own `mlflow-skinny` is 3.17.2, newer than the 3.6.0 server, so it is pinned back.
- Full `mlflow==3.6.0` caps `cryptography<47`, which downgraded the base image's 50.0.0 and reintroduced four advisories. `mlflow-skinny` is enough for LiteLLM's callback. Using `mlflow>=3.16` was rejected because it would put a newer client in front of the 3.6.0 server. On 1.108.6 the built image keeps `cryptography 50.0.0` on both amd64 and arm64.
- After layering packages on a signed base, diff versions to catch downgrades. `packaging` still moves from 26.2 to 25.0 (seen on 1.106.6).
- The image has no `wget` or `curl`. The old compose healthcheck called `wget`, so the container always looked unhealthy and `docker compose up --wait` exited 1 while `/health/liveliness` returned 200 (#197, #199). Probes run in Python `urllib`, and any new probe should assume Python only.
- On 1.108.6, `/health/readiness` returns `litellm_version: null`. Read the version from the image (`importlib.metadata.version("litellm")`), not that endpoint.
- Local builds and pulls from ghcr.io fail with `denied` or a 403 token error when the Docker credential store holds stale ghcr credentials. `docker logout ghcr.io` fixes anonymous pulls of public images.

`pixi.toml`'s `mlflow==3.10.0` is a separate dev-environment pin used by `infra extract`. It isn't the deployed version.

**Sources:** PRs #148, #199, #235; issue #197; docker/dockerfiles/litellm.dockerfile; docker/docker-compose.yml; pixi.toml

# Related Concepts
- [LiteLLM is pinned by version and digest, and upgrades across migrations are one-way](../decisions/litellm-image-digest-pin-and-one-way-upgrade.md): How the pinned image is extended
