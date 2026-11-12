---
type: Decision
title: ceil-dlp runs as an opt-in LiteLLM guardrail in a separate litellm-dlp image
description: "The ceil-dlp guardrail needs a 3.4 GB image with pinned torch, protobuf, sentencepiece and headless OpenCV, and its policy must set ner_strength: 1 because the container runs Hugging Face offline."
tags: [litellm, dlp, guardrail, ceil-dlp, docker]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-12T20:39:09Z" }
status: stable
governance: constraint
code_refs:
  - "docker/dockerfiles/litellm.dockerfile"
  - "src/llmaven/infrastructure/resources/dlp.py"
  - "src/llmaven/infrastructure/resources/ceil_dlp_guardrail.py"
---

**Status:** implemented on branch `feat/ceil-dlp-guardrail` (not yet merged or deployed).

[ceil-dlp](https://github.com/uw-ssec/ceil-dlp) runs as a LiteLLM **guardrail**, not as its legacy callback, in a **separate image**: `litellm.dockerfile` target `litellm-dlp`, published as `llmoxie-litellm-dlp`. Deployments opt in with `litellm.dlp` (off by default). With it off, the mounted files and config are byte-identical to before, so existing stacks see no diff.

**Why a separate image:** ceil-dlp's middleware imports its image and PDF detectors at load time, so even the text-only guardrail needs torch, transformers, GLiNER and docTR. The image is about 3.4 GB (arm64) to 3.6 GB (amd64), against 1.4 GB without it.

**Pins in the Dockerfile, each found by a failure in testing:**
- ceil-dlp is pinned to a uw-ssec fork commit; guardrail mode is not in PyPI 1.3.2.
- CPU torch 2.14.1 + torchvision 0.29.1 come from the PyTorch CPU index. torchvision must match torch exactly; 0.29.x with torch 2.15 fails with `operator torchvision::nms does not exist` (surfaced as transformers "Could not import module 'pipeline'").
- Base packages are held with a constraints file generated from the base image. Unconstrained, pip moved protobuf to 7 and ml-dtypes to 0.6, breaking mlflow-skinny, grpcio-status and redisvl. Only huggingface-hub (0.36) and tokenizers (0.22) may move: transformers 4.x and gliner need hub<1, and litellm accepts hub>=0.34 and tokenizers>=0.21.
- `opencv-python` is swapped for `opencv-python-headless` (the image has no libxcb). `pip check` then reports opencv-python missing for doctr and presidio-image-redactor, which is expected.
- `sentencepiece==0.2.2`: 0.2.3 ships protobuf-7 gencode, which fails at request time against the base image's protobuf 5.29.6.
- `setuptools>=78.1.1`: the PyTorch index brings 78.1.0 (CVE-2025-47273).

**The policy must set `ner_strength: 1`.** ceil-dlp defaults to 3, which downloads BERT and GLiNER on the first request (about 26 s) and pushed memory to about 4.2 GB, over the 4 GiB container. The deploy sets `HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE` and rejects a policy without `ner_strength: 1`. At level 1: about 2 GB per replica, and about 15 ms per request with mock models.

**How it is wired:** the deploy mounts `ceil_dlp_guardrail.py` (a one-line re-export; LiteLLM loads custom guardrails from files in the config directory) and the policy file into `/app/config`, sets `CEIL_DLP_CONFIG_PATH`, and appends the guardrail to the mounted LiteLLM config (`mode: [pre_call, post_call]`, `default_on` from config). A hand-written `ceil-dlp` guardrail entry is an error.

**Observed gaps (2026-11-12, ner_strength 1, mock models):** credit card blocked, email and `sk-proj-` API keys masked, whistledown round trip correct when streamed and not. At level 3 the word "Email" was tagged as a person. The guardrail does not rewrite `reasoning_content` and scans text only (no images or PDFs). An `AKIA…` AWS key is masked only if the `aws_credential` policy is enabled.

**Sources:** docker/dockerfiles/litellm.dockerfile; src/llmaven/infrastructure/resources/dlp.py; tests/infrastructure/test_dlp.py; https://github.com/uw-ssec/ceil-dlp (commit abad0ee)

# Related Concepts
- [LiteLLM is pinned by version and digest, and upgrades across migrations are one-way](litellm-image-digest-pin-and-one-way-upgrade.md): Extends the pinned LiteLLM image with a second build target
