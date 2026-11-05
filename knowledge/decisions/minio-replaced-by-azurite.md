---
type: Decision
title: Azurite replaced MinIO for local MLflow artifacts
description: "MinIO only backed local artifacts and upstream is archived, so local storage now matches production through wasbs://; old .env files and stored experiment locations are the upgrade trap."
tags: [docker, mlflow, azurite, minio]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:48Z" }
status: stable
code_refs: [docker/docker-compose.yml, docker/ensure_blob_container.py, docker/.env.example, docker/dockerfiles/mlflow.dockerfile]
sources:
  - resource: "issues #150, #195"
  - resource: "PRs #198, #199"
  - resource: docker/docker-compose.yml
  - resource: docker/ensure_blob_container.py
  - resource: docker/.env.example
  - resource: docker/README.md
---

**Status at e248584:** implemented (#198).

MinIO only held local MLflow artifacts and upstream `minio/minio` is archived. By #199, Docker Hub returned 404 for `minio/minio` and `quay.io/minio/mc` denied pulls, so older checkouts can't start from a clean machine. Production already uses Blob through `wasbs://`, so Azurite gives local and cloud one path and drops two services. A local artifact volume and an S3 replacement such as rustfs (#150) were not pursued; #195 went with Azurite.

Non-obvious requirements:

- The artifact root must use the account hostname form, `wasbs://mlflow@devstoreaccount1.blob.core.windows.net/`, while `AZURE_STORAGE_CONNECTION_STRING` supplies the real endpoint.
- MLflow never creates the container, hence `ensure_blob_container.py`, added through a compose entrypoint override so the published image keeps its own entrypoint.
- Azurite needed a named volume, which it lacked before.

**Upgrade trap:** experiments persist their artifact location, so old ones keep `s3://`. With an old `docker/.env`, new ones also fail with `No module named 'boto3'`. `pixi run up` doesn't pass `--build`, so MLflow must also be rebuilt.

**Sources:** issues #150, #195; PRs #198, #199; docker/docker-compose.yml; docker/ensure_blob_container.py; docker/.env.example; docker/README.md

# Related Concepts
- [The repo is the LiteLLM and MLflow platform only; RAG lives in llmoxie-rag](platform-only-scope.md): The scope guard pins the resulting compose services
