"""The LiteLLM image is the uw-ssec fork, without the 5-user SSO cap."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "docker" / "dockerfiles" / "litellm.dockerfile"

FORK_IMAGE = (
    "ghcr.io/uw-ssec/llmoxie-litellm-fork:v1.108.6"
    "@sha256:98070f3fcfb082155d5153bdaddbaa18a1fa05524990e7cb4b8c9fd42e68fbd3"
)


def test_litellm_base_is_the_fork():
    first_from = next(
        line for line in DOCKERFILE.read_text().splitlines() if line.startswith("FROM ")
    )
    assert first_from == f"FROM {FORK_IMAGE}"


def test_litellm_is_not_reinstalled_from_pypi():
    # A litellm== pin would replace the fork's patched package with upstream's
    # and bring the SSO cap back.
    assert "litellm==" not in DOCKERFILE.read_text()


def test_build_checks_the_sso_cap_is_gone():
    text = DOCKERFILE.read_text()
    match = re.search(r"^RUN python -c .*_raise_if_sso_exceeds_free_user_limit.*$", text, re.M)
    assert match, "build must assert the upstream cap function is absent"
    assert "ui_sso" in match.group(0)
    assert "assert not hasattr" in match.group(0)
