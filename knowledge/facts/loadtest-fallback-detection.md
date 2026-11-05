---
type: Fact
title: "Load test fallback detection depends on /model/info, because /v1/messages hides fallbacks"
description: "LiteLLM 1.82.3 echoes the alias on /v1/messages and omits the fallback header, so the runner maps x-litellm-model-id; verified locally on 1.82.3 only."
tags: [loadtest, litellm]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:48Z" }
status: stable
code_refs: [src/llmaven/deployment/loadtest.py, tests/infrastructure/test_loadtest.py]
sources:
  - resource: "PR #129"
  - resource: src/llmaven/deployment/loadtest.py
  - resource: tests/infrastructure/test_loadtest.py
---

**Status at e248584:** implemented (#129). Behavior was verified on a local 1.82.3 proxy with mock responses. Main now pins 1.106.6, and #129 records no run against that version, a deployed proxy or real providers.

The response `model` can't detect a fallback. On `/v1/messages`, LiteLLM echoes the requested alias and omits `x-litellm-attempted-fallbacks`, which appears only on `/v1/chat/completions`. The runner honors the header when present, and otherwise maps `x-litellm-model-id` through `GET /model/info`, which needs a key that can read it.

If that mapping is unavailable, responses count as unclassified and `fallback_rate_pct` is `null`, never a false 0%. An HTTP 200 counts as success only with a valid message body and usage, because invalid JSON and error bodies arrive as 200. A fixed cutoff of about 2000 s was replaced by a dataset-sized deadline that reports `unsent_requests` and exits 1.

Replay strips thinking blocks, because their signatures are time-limited, along with images and tool `cache_control`, and it forces non-streaming so usage is always present. HTTPS runs are untested: Locust warns that SSL was imported before gevent monkey-patching.

**Sources:** PR #129; src/llmaven/deployment/loadtest.py; tests/infrastructure/test_loadtest.py

# Related Concepts
- [LiteLLM is pinned by version and digest, and upgrades across migrations are one-way](../decisions/litellm-image-digest-pin-and-one-way-upgrade.md): Headers need rechecking on the pinned version
