---
type: Decision
title: "LiteLLM is pinned by version and digest, and upgrades across migrations are one-way"
description: "The image is v1.106.6 by digest because of upstream compromises; Prisma migrations are one-way, so rollback means restoring a pg_dump, not swapping the image."
tags: [litellm, supply-chain, upgrade]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:47Z" }
status: stable
governance: constraint
code_refs:
  - "docker/dockerfiles/litellm.dockerfile"
sources:
  - resource: "PR #148"
  - resource: "docker/dockerfiles/litellm.dockerfile"
  - resource: "https://github.com/BerriAI/litellm/security/advisories/GHSA-7hp6-4w63-5g45"
  - resource: "https://docs.litellm.ai/blog/security-incident-oct-21-2026"
---

**Status at e248584:** implemented (#148).

The base image is `v1.106.6` by tag and digest, replacing `v1.82.3-stable`. #148's first proposal, `v1.91.1`, was dropped; it falls in the range of GHSA-7hp6-4w63-5g45 (`>= 1.91.0, < 1.100.4`). Floating tags are out: upstream reports malicious releases, including `v1.107.0` and the floating `latest`, `main-latest` and `main-stable` Docker tags. Don't move to a newer tag without checking advisories for that exact version. There's no `-stable` suffix for this line.

**Upgrades are one-way.** Moving a 1.82.3 database to 1.106.6 applied Prisma migrations 108 to 214, and a refused startup may already have applied them. Take a fresh `pg_dump` immediately before deploying. Rollback means restoring that dump and redeploying the old image, losing spend logs written in between. Restarting the old image on a migrated database isn't a verified rollback.

Known gaps: add-ons still resolve from PyPI without hash pinning (`--require-hashes` would close it), and the runtime check at merge was ARM64 only, while CI also publishes amd64.

**Sources:** PR #148; docker/dockerfiles/litellm.dockerfile; https://github.com/BerriAI/litellm/security/advisories/GHSA-7hp6-4w63-5g45; https://docs.litellm.ai/blog/security-incident-oct-21-2026
