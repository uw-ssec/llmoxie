"""ceil-dlp guardrail for LiteLLM (https://github.com/uw-ssec/ceil-dlp).

The guardrail runs inside the LiteLLM container and needs the ``litellm-dlp``
image (``docker/dockerfiles/litellm.dockerfile``, target ``litellm-dlp``). At
deploy time the guardrail module and the ceil-dlp policy file are mounted next
to the LiteLLM config, and the guardrail is registered in that config.
"""

from __future__ import annotations

import io
from pathlib import Path

from ruamel.yaml import YAML

DLP_GUARDRAIL_NAME = "ceil-dlp"
DLP_GUARDRAIL_MODULE = Path(__file__).parent / "ceil_dlp_guardrail.py"
CONFIG_MOUNT_DIR = "/app/config"


def dlp_env_vars(policy_file: Path) -> dict[str, str]:
    """Env vars for LiteLLM when the guardrail is on.

    Hugging Face is set offline: the image bakes in only the spaCy model used
    at ``ner_strength: 1``, and the container should not download models.
    """
    return {
        "CEIL_DLP_CONFIG_PATH": f"{CONFIG_MOUNT_DIR}/{policy_file.name}",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    }


def validate_dlp_policy(policy_text: str, source: str) -> None:
    """Reject a ceil-dlp policy that would fail inside the container.

    ceil-dlp defaults to ``ner_strength: 3``, which loads a BERT model and
    GLiNER from Hugging Face on the first request. With Hugging Face offline
    that request fails, so every request through the guardrail would fail.
    The policy must set ``ner_strength: 1`` (spaCy ``en_core_web_lg``, baked
    into the image).
    """
    data = YAML(typ="safe").load(policy_text)
    if not isinstance(data, dict):
        raise ValueError(f"ceil-dlp policy {source} must be a YAML mapping")
    if data.get("ner_strength") != 1:
        raise ValueError(
            f"ceil-dlp policy {source} must set ner_strength: 1. ceil-dlp "
            "defaults to 3, which downloads models at request time; the "
            "litellm-dlp image only includes the spaCy model used at level 1."
        )


def apply_dlp_guardrail(config_text: str, default_on: bool = True) -> str:
    """Register the ceil-dlp guardrail in a LiteLLM config.

    Other guardrails and the rest of the file (including comments) are kept.
    A config that already registers a guardrail named ``ceil-dlp`` is an
    error, so a hand-written entry cannot silently differ from this one.
    """
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    data = yaml.load(config_text)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError("LiteLLM config must be a YAML mapping")

    guardrails = data.get("guardrails")
    if guardrails is None:
        guardrails = []
        data["guardrails"] = guardrails
    elif not isinstance(guardrails, list):
        raise ValueError("LiteLLM config guardrails must be a list")
    if any(
        isinstance(g, dict) and g.get("guardrail_name") == DLP_GUARDRAIL_NAME
        for g in guardrails
    ):
        raise ValueError(
            f"LiteLLM config already registers a guardrail named "
            f"{DLP_GUARDRAIL_NAME!r}; remove it and let litellm.dlp add it"
        )

    guardrails.append(
        {
            "guardrail_name": DLP_GUARDRAIL_NAME,
            "litellm_params": {
                "guardrail": f"{DLP_GUARDRAIL_MODULE.stem}.CeilDLPGuardrail",
                "mode": ["pre_call", "post_call"],
                "default_on": default_on,
            },
        }
    )

    out = io.StringIO()
    yaml.dump(data, out)
    return out.getvalue()
