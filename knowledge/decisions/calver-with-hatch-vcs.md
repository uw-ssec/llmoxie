---
type: Decision
title: "Releases use CalVer vYYYY.M.MICRO, with the version from hatch-vcs (planned)"
description: "Project owner's decision in #213: three unpadded parts because metadata-action skips invalid semver; __version__ is still hard-coded and there's no CHANGELOG yet."
tags: [release, versioning, calver]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:49Z" }
status: draft
code_refs: [.github/workflows/build-services.yml, pyproject.toml, src/llmaven/__init__.py]
sources:
  - resource: "issue #213"
  - resource: .github/workflows/build-services.yml
  - resource: src/llmaven/__init__.py
  - resource: pyproject.toml
---

**Status at e248584:** planned. `__version__` is still hard-coded `0.1.0`, `pyproject.toml` has no hatch-vcs, and there's no `CHANGELOG.md`.

The project owner's decision in #213: tags are `vYYYY.M.MICRO`, three parts, never zero-padded, and MICRO counts releases, not days. `build-services.yml` uses `docker/metadata-action` `type=semver`, which skips invalid semver, so `v2026.12` or `v2026.01.0` would publish no versioned images.

A 2-digit year was rejected because `26.11.0` sorts before the existing `2026.11.2`. Existing tags stay. Untagged builds must be `YYYY.M.MICRO.devN` with no local segment (`local_scheme = "no-local-version"`). CalVer doesn't signal breaking changes, so a CHANGELOG with upgrade notes is required.

**Sources:** issue #213; .github/workflows/build-services.yml; src/llmaven/__init__.py; pyproject.toml

# Related Concepts
- [Image builds never run on PRs, and workflow actions are pinned by SHA](../facts/image-builds-and-workflow-pinning.md): Tags drive the same image workflow
