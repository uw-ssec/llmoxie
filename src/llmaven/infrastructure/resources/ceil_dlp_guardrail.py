"""Mounted next to the LiteLLM config when ``litellm.dlp.enabled`` is set.

LiteLLM loads a custom guardrail from a file in its config directory, so this
module re-exports ceil-dlp's guardrail class from the ``litellm-dlp`` image.
"""

from ceil_dlp.guardrail import CeilDLPGuardrail  # noqa: F401
