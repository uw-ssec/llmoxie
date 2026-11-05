---
type: Fact
title: Managed Redis arrives automatically on the next deploy and is unproven live
description: "max_replicas defaults to 2, so any default stack gains Redis and its cost on the next deploy; cross-replica limit enforcement hasn't been shown on a live stack."
tags: [redis, litellm, azure, cost]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:48Z" }
status: stable
code_refs: [src/llmaven/infrastructure/resources/redis.py, src/llmaven/infrastructure/config/schema.py, tests/infrastructure/test_redis_program.py]
sources:
  - resource: "issue #211"
  - resource: "PR #212"
  - resource: tests/infrastructure/test_redis_program.py
  - resource: pixi.toml
  - resource: "https://learn.microsoft.com/en-us/azure/azure-cache-for-redis/retirement-faq"
---

**Status at e248584:** implemented in code (#212). Live enforcement has no public evidence. `.agents/rules/infrastructure.md` covers the design; this concept covers what it doesn't.

- `max_replicas` defaults to 2, so the next deploy of a stack on default settings adds Redis, a private endpoint, a subnet, private DNS and three Key Vault secrets, with their cost. That's deliberate: several replicas without Redis silently enforce limits once per replica.
- `LITELLM_DISABLE_NO_REDIS_WARNING` only hides the banner, so #211 rejects it as a fix. Routing stays `simple-shuffle` because usage-based routing adds Redis lookups to every request.
- Azure Cache for Redis was rejected because it retires (2027-03-31 and 2028-09-30, depending on tier). `pulumi-azure-native >=3.29` is required for redisenterprise API 2025-07-01, which has `publicNetworkAccess`.
- Access keys are phase 1. Entra ID auth is an unspiked follow-up.

**Mock tests weren't enough.** Two defects survived mock review. A fixed `private_endpoints_subnet` default fell outside a VNet using a non-default range, so it's now derived from the VNet and validated; only a preview against a real config caught this. LiteLLM's dependencies also omitted the private endpoint and DNS wiring, so `test_redis_program.py` now asserts the transitive closure of recorded dependencies. Infra changes that add subnets need a test with a non-default VNet.

`test_redis_program.py` stubs the Container App factory, because `user_assigned_identities=[id]` breaks the Pulumi mock serializer, so the real app resource isn't exercised. CROSSSLOT avoidance and limit enforcement across two replicas were untested at merge. Check for later evidence before calling them working.

**Sources:** issue #211; PR #212; tests/infrastructure/test_redis_program.py; pixi.toml; https://learn.microsoft.com/en-us/azure/azure-cache-for-redis/retirement-faq

# Related Concepts
- [Making a deploy a true no-op: revisions, probes and the preview gate](../decisions/no-op-deploy-controls.md): Enabling Redis is a one-time expected diff
