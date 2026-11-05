---
type: Bug
title: "The configured subscription has two paths, and az account show doesn't prove the login works"
description: "Azure CLI calls and the Pulumi provider must each receive the configured subscription, and only a token probe detects an expired login; the backup stack's provider still follows the CLI default."
tags: [azure, authentication, pulumi]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:48Z" }
status: stable
governance: constraint
code_refs: [src/llmaven/deployment/deploy.py, src/llmaven/deployment/validate.py, src/llmaven/deployment/deploy_backup.py]
sources:
  - resource: "issues #203, #205, #209"
  - resource: "PRs #206, #207"
  - resource: tests/infrastructure/test_deploy_subscription.py
  - resource: tests/infrastructure/test_expired_az_login.py
---

**Status at e248584:** implemented for the main stack (#206, #207). The backup stack gap is open.

**Two subscription paths.** `az` calls take `--subscription` per call, which leaves the user's CLI default alone and is why `az account set` was removed. The Pulumi provider takes `azure-native:subscriptionId` through `stack.set_config`, because stack config outranks `ARM_SUBSCRIPTION_ID`. Fixing only one lets a deploy target the wrong subscription.

**Expired logins.** `az account show` reads the local cache and succeeds after a session expires. Validation passed, then deploy failed with the misleading `str expected, not NoneType`: `_get_storage_key` swallowed the failure and returned `None`, and `os.environ.setdefault` then raised. `check_subscription_access` now runs `az account get-access-token --subscription <configured>`, querying only `expiresOn` so no token reaches output.

**Deliberately not done:** #203 asked for a token check in `check_azure_cli` too. It was rejected because that would test the default subscription, and an expired session there must not fail a valid deploy elsewhere.

`_get_storage_key` now returns `None` only for `ResourceNotFound` and `ResourceGroupNotFound`, because treating an auth failure as "not found" would start the create path. That check matches strings in `az` stderr.

**Open gap:** `deploy_backup.py` forwards a subscription to the key lookup but never sets the provider subscription, so the backup stack's provider follows the CLI default. Neither fix was exercised against a live expired login or live cross-subscription preview at merge.

**Sources:** issues #203, #205, #209; PRs #206, #207; tests/infrastructure/test_deploy_subscription.py; tests/infrastructure/test_expired_az_login.py

# Related Concepts
- [The Pulumi state store and resource group live outside the Pulumi program](../architecture/pulumi-state-store-bootstrap.md): Both concern what deploy does before Pulumi runs
