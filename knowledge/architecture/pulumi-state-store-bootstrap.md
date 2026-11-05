---
type: Architecture
title: The Pulumi state store and resource group live outside the Pulumi program
description: "Pre-deploy az calls create them and rewrite the config, so infra destroy can't remove them, and an unset state store creates another account."
tags: [pulumi, azure, state]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:47Z" }
status: stable
code_refs:
  - "src/llmaven/deployment/deploy.py"
sources:
  - resource: "issues #73, #96"
  - resource: "PR #82"
  - resource: "src/llmaven/deployment/deploy.py"
  - resource: ".agents/rules/pulumi-state-recovery.md"
---

**Status at e248584:** implemented; the gaps below are open.

State moved from local Pulumi state to Azure Blob so several administrators can work on one stack (#73, #82). `initialize_azure_infra()` uses `az` to create the resource group, a `pulumistate<uuid>` storage account and the `pulumi-state` container, then writes the names back to the operator's YAML. The ordering reason, that the group must exist before the store holding the state, is inferred.

`.agents/rules/infrastructure.md` already warns that `deploy --preview` can create these. Also true:

- **`infra destroy` can't remove them.** `destroy_infrastructure` only runs `stack.destroy`. `delete_resource_group()` is called only from a test (#82 said it was "currently not invoked anywhere"). Full cleanup needs a separate manual step, although the command's wording suggests otherwise.
- **An unset `project.pulumi_state_store` creates another account,** even if the group already holds one, because the name is a fresh UUID. Stacks can end up spread across stores. #96 proposes finding the existing account; that isn't implemented. Keep the field set for any existing deployment.
- **Shell variables beat the config (inferred from the code).** `get_stack` uses `os.environ.setdefault` for `PULUMI_BACKEND_URL` and `AZURE_STORAGE_ACCOUNT` and skips the key lookup if `AZURE_STORAGE_KEY` is set. The state-recovery runbook tells operators to export these, so unset them before deploying a different config.

**Sources:** issues #73, #96; PR #82; src/llmaven/deployment/deploy.py; .agents/rules/pulumi-state-recovery.md
