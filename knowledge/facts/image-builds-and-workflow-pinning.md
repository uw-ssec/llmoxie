---
type: Fact
title: "Image builds never run on PRs, and workflow actions are pinned by SHA"
description: "build-services.yml runs only after merge, on releases and on dispatch, so PR checks say nothing about images; zizmor requires full-SHA action pins."
tags: [ci, docker, github-actions, zizmor]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:48Z" }
status: stable
code_refs: [.github/workflows/build-services.yml, .github/workflows/ci.yml]
sources:
  - resource: "PRs #124, #148, #173, #181, #201"
  - resource: .github/workflows/build-services.yml
---

**Status at e248584:** implemented. Whether to add a pre-merge build is undecided.

`build-services.yml` runs on pushes to main touching its paths, on releases and on manual dispatch. The first build of a Dockerfile or builder change therefore happens after merge and publishes `:latest`. A branch dispatch is the only hosted pre-merge check, and it publishes branch-tagged images, so it needs maintainer approval. This came up on #148 (no amd64 test before merge) and #201 (builder v2 needed a per-Dockerfile `cache-key`).

- zizmor's `unpinned-uses` requires every action pinned to a full commit SHA with a version comment, so a Dependabot bump needs a follow-up pin commit. Other zizmor findings remained at #201, so a full run wasn't clean.
- On tag refs `{{branch}}` is empty and produced the invalid tag `-<sha>`, so no release images were published for v2026.10.23. The sha tag is now branch-only (#173).
- A dispatch on a tag ref uses the workflow file at that tag, so a fix on main doesn't repair an existing tag.

**Sources:** PRs #124, #148, #173, #181, #201; .github/workflows/build-services.yml

# Related Concepts
- [CI was once green while tests failed, and two traps make CI failures hard to reproduce](../bugs/ci-false-green-and-repro-traps.md): What CI does and doesn't cover
