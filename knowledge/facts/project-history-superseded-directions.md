---
type: Fact
title: "Earlier directions that were dropped, and PRs closed with no stated reason"
description: "Custom proxy, OpenTofu, the Jupyter AI survey and the demo were replaced; #126 and #168 record no rejection reason, so don't read them as design verdicts."
tags: [history, rejected]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:48Z" }
status: stable
sources:
  - resource: "PRs #30, #31, #32, #44, #45, #99, #101, #111, #112, #122, #126, #129, #167, #168, #202"
  - resource: "issues #4, #6, #51, #65, #94, #193"
---

**Status at e248584:** historical record.

- **Custom proxy.** A FastAPI OpenAI-compatible proxy with key auth on Azure Table Storage (#30, #31) moved to `archive/` (#44, #45) and was deleted (#202). LiteLLM now fills that role. No source states why it was dropped; replacement by LiteLLM is inferred from the sequence.
- **IaC tool.** #6 planned OpenTofu and to look at Bicep. It closed with "We are now using pulumi for this setup rather than opentofu". No reason is recorded.
- **Inference split.** #4's Jupyter AI and llama.cpp survey closed in favor of a logging proxy in front of vLLM. vLLM on HPC under SLURM is still unresolved research (#51, #65).
- **Demo.** #99 and #101 added a `demo/` walkthrough and closed. Issue #94 closed because the work evolved into `uw-ssec/llmoxie-rse-sandbox`.
- **Recursive text splitter.** #32 was closed because its target code was being deprecated, not because of the algorithm.
- **Image attestation.** #31 removed attestation from an early proxy image as "overkill". #193 now lists SBOM, provenance and signing as a gap, so that removal isn't standing policy (inferred).

**No recorded reason:** #126 (load testing) and #168 (log import performance) closed without comment. #129 and #167 later delivered related work, which is an inference. #122 (backup to Azure Vault), #111 and #112 are open with little or no description, so don't treat them as agreed plans.

**Sources:** PRs #30, #31, #32, #44, #45, #99, #101, #111, #112, #122, #126, #129, #167, #168, #202; issues #4, #6, #51, #65, #94, #193

# Related Concepts
- [The repo is the LiteLLM and MLflow platform only; RAG lives in llmoxie-rag](../decisions/platform-only-scope.md): Earlier stages of the project scope
