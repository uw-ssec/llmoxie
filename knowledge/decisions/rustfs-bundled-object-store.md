---
type: Decision
title: "RustFS is the Helm chart's bundled object store, and S3 is the storage protocol"
description: "The owner chose RustFS over SeaweedFS, Garage and CubeFS for the chart in #236 and runs it on AKS too, so the chart speaks S3 only; unmerged prototype work."
tags: [helm, kubernetes, object-storage, s3, rustfs]
generated: { by: "claude-code:claude-fable-5-2", at: "2026-11-12T21:44:13Z" }
status: stable
code_refs: [charts/llmoxie/templates/object-storage.yaml, charts/llmoxie/files/s3_logger.py, charts/llmoxie/values.yaml]
---

**Status at a7e7d32:** decided by the project owner on 2026-11-12 for the Helm chart tracked in #236. The same day the owner decided the AKS install runs RustFS like every other site. Implemented only as an uncommitted prototype on branch `llmoxie-helm`; nothing is merged.

## Decision

The chart bundles RustFS as its object store, so llmoxie talks to object storage over the S3 API. A site with its own store gives the chart an S3 endpoint and a key Secret instead (`objectStorage.mode=external`).

## Why

The code spoke only Azure Blob: MLflow artifacts (`wasbs://`), `adl_logger.py`, and `scripts/backup_postgres.py` (`az://` or `abfs://`). AWS, GCP and HPC sites have no Blob endpoint, and Azurite is an emulator.

Four servers ran as single pods on a local k3s cluster and were probed with boto3 and s3fs on twelve behaviors (multipart upload and abort, paged and delimited lists, range reads, copy, presigned URLs, streamed writes, batch delete, lifecycle rules, keys such as `a/b` beside `a/b/c`):

- RustFS 1.0.5: 12/12, Apache-2.0, one binary on one volume. Chosen.
- SeaweedFS 4.53: 12/12, Apache-2.0, repository since 2014. The agent recommended it for its track record; the owner chose RustFS.
- Garage 2.5.0: 12/12, AGPL-3.0, needs a scripted layout and key bootstrap.
- Versity gateway 1.11.0: 9/12. It is an S3 front for a filesystem; it rejected `a/b` beside `a/b/c` and lifecycle rules, and a presigned GET returned HTTP 400 (not investigated).

CubeFS was read, not run: its Helm chart (last commit 2025-03) needs host networking, host paths, privileged pods, hand-labeled nodes and at least three masters, so it fits `external` mode, like Ceph. MinIO stays out because its repository is archived.

## Caveats

- RustFS 1.0.0 shipped on 2026-09-16. Its README says a single-drive deployment cannot be expanded in place.
- Bundled storage is one pod on one volume with no redundancy, so backups kept there share the cluster's fate.
- Verified on the prototype with RustFS 1.0.5: an MLflow artifact, a request log from the S3 logger, and a `pg_dump` backup all land in their buckets, and the objects survive a RustFS pod restart.
- Not verified: upgrades between RustFS versions, performance, behavior under failure, and CloudNativePG's own backups to RustFS.
- The chart speaks S3 only. The Azure Blob code paths (`adl_logger.py`, `wasbs://`, `az://`) serve the Pulumi Container Apps deployment until it is retired.
- Inferred, not tested: moving production means copying blobs from the storage account into RustFS, and MLflow experiments keep the `wasbs://` artifact location they were created with.
- Database backups never go to the bundled RustFS; see requirements/backups-outside-the-cluster.

**Sources:** issue #236; docs/superpowers/specs/2026-11-12-llmoxie-helm-chart-design.md; charts/llmoxie/templates/object-storage.yaml; charts/llmoxie/files/s3_logger.py; scripts/backup_postgres.py

# Related Concepts
- [Azurite replaced MinIO for local MLflow artifacts](minio-replaced-by-azurite.md): Both pick the object store behind MLflow artifacts; Azurite remains for the Azure and docker-compose path
