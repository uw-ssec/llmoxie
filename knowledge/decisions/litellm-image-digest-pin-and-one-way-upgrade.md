---
type: Decision
title: "LiteLLM is pinned by version and digest, and upgrades across migrations are one-way"
description: "The image is the uw-ssec fork of v1.108.6 by digest (amd64 only; no SSO cap); check advisories per exact version, and Prisma migrations are one-way, so rollback means restoring a pg_dump."
tags: [litellm, supply-chain, upgrade]
generated: { by: "claude-code:claude-sonnet-5-5", at: "2026-11-14T00:05:16Z" }
status: stable
governance: constraint
code_refs: [docker/dockerfiles/litellm.dockerfile]
sources:
  - resource: "PR #148"
  - resource: docker/dockerfiles/litellm.dockerfile
  - resource: "https://github.com/BerriAI/litellm/security/advisories/GHSA-7hp6-4w63-5g45"
  - resource: "https://docs.litellm.ai/blog/security-incident-oct-21-2026"
---

**Status at a7e7d32:** implemented (#148, then #235). Released as llmoxie `v2026.11.5`; prod and ISS run it since 2026-11-12.

**Update 2026-11-13 (SSO stage):** the pinned image is now the uw-ssec fork, `ghcr.io/uw-ssec/llmoxie-litellm-fork:v1.108.6@sha256:98070f3f…fbd3` (branch `sso-enabled` of uw-ssec/llmoxie-litellm), amd64 only, so the published llmoxie LiteLLM image is amd64-only too (build-services.yml gives litellm `platforms: linux/amd64`; the other images stay multi-arch) and Apple Silicon/ARM hosts need emulation. The pinned version is unchanged (v1.108.6), so no new advisories apply beyond those already checked for it; the digest is the fork's own, not the upstream index below. The fork is upstream v1.108.6 plus commit `3f4f5a05`, which deletes the 5-user SSO cap and drops the proprietary `enterprise/` package; its compare against upstream `v1.108.6` touches no Prisma schema or migration file (only `.dockerignore`, `Dockerfile`, `pyproject.toml`, `uv.lock`, `README.md`, `litellm/proxy/management_endpoints/ui_sso.py`, `docker/Dockerfile.mlflow`, CI workflows and watcher script, and removed `dist/` artifacts), so the migration facts below are unchanged. Taking on the fork's maintenance was a deliberate choice: a later bump means merging upstream into the fork, publishing a new image and re-pinning its digest here, after re-checking advisories for the exact version. The Dockerfile asserts at build time that `_raise_if_sso_exceeds_free_user_limit` is absent from `ui_sso`.

The upstream digest and `cosign` notes below describe the previous base; the fork's image is not signed by upstream.

The base image is `v1.108.6` (LTS) by tag and digest (`sha256:c64fe10f…3ec3`, the multi-arch index). Floating tags are out: upstream reports malicious releases, including `v1.107.0` and the floating `latest`, `main-latest` and `main-stable` Docker tags. **Don't move to a newer tag without checking advisories for that exact version.** That check changed the target twice:

- #148's first proposal, `v1.91.1`, was in the range of GHSA-7hp6-4w63-5g45 (`>= 1.91.0, < 1.100.4`); `v1.106.6` was used instead.
- #235 was asked for `v1.108.5`, but GHSA-2rwg-2wh4-7c4f (high, published 2026-11-12) affects everything below `1.106.9` / `1.108.6`, so `v1.108.6` was pinned. List advisories with `gh api repos/BerriAI/litellm/security-advisories` and read each `vulnerable_version_range`.

**Verifying a new tag:** run `cosign verify` with the key at the commit hash given in the release notes, then verify the exact `@sha256:` digest you pin (not just the tag). Confirm that digest is the OCI index the registry serves for the tag, so amd64 and arm64 are both covered. Build both architectures and compare package versions against the base.

**Whether an advisory applies is deployment-specific.** GHSA-2rwg-2wh4-7c4f (request-body Entra credential params leak env vars, including `LITELLM_MASTER_KEY`) affects only proxies with an `azure/` or `azure_ai/` model and neither `AZURE_API_KEY` nor `AZURE_OPENAI_API_KEY` set. Prod (managed identity, no key) was exposed until 2026-11-12 19:37 UTC. ISS sets `AZURE_API_KEY` (from `LLMAVEN_SECRETS_AZURE_API_KEY`) and wasn't. Check the running container's env names (`az containerapp show … --query "properties.template.containers[].env[].name"`), not just the `.env` file: secrets carry the `LLMAVEN_SECRETS_` prefix there. Patched proxies answer a body `client_id` with 401 "client_id is not allowed in request body", which is a safe post-deploy check.

**Upgrades are one-way.** 1.82.3 → 1.106.6 applied Prisma migrations 108 to 214. 1.106.6 → 1.108.6 applied 7 more, ending at `20261015000000_managed_object_end_user_id` (a fresh database ends with 220 rows). A refused startup may already have applied them. Take or pick a recent `pg_dump` before deploying. Rollback means restoring that dump and redeploying the old image, losing spend logs written in between. Restarting the old image on a migrated database isn't a verified rollback. Replicas take a Prisma migration lock, so only one applies them; on both stacks the new revision was healthy within about 90 s.

**Rollout shape used for 1.108.6:** cut a release after the main build passes. In llmaven-deploy, move only the LiteLLM image tag. MLflow and backup sources hadn't changed, and their rebuilds come from unpinned bases. Bump `revision_suffix` and `refresh_trigger`, then deploy from a checkout of the matching release tag.

Known gaps: add-ons still resolve from PyPI without hash pinning (`--require-hashes` would close it).

**Superseded:** the upstream image `ghcr.io/berriai/litellm:v1.108.6@sha256:c64fe10f…3ec3` (pin until the SSO stage; replaced by the fork above). v1.106.6 (`sha256:37e2dafb…0b06`) was the pin from #148 until #235. The note that the runtime check was ARM64 only applied to #148; #235 was checked on both architectures.

**Sources:** PRs #148, #235; release v2026.11.5; llmaven-deploy PRs #54, #55; docker/dockerfiles/litellm.dockerfile; https://github.com/BerriAI/litellm/security/advisories/GHSA-7hp6-4w63-5g45; https://github.com/BerriAI/litellm/security/advisories/GHSA-2rwg-2wh4-7c4f; https://docs.litellm.ai/blog/security-incident-oct-21-2026
