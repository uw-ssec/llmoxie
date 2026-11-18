"""The knowledge_hub config block: defaults, cross-block checks, names."""

import pytest
from pydantic import ValidationError

from llmaven.infrastructure.config.schema import (
    CONTAINER_APP_NAME_MAX,
    LLMavenConfig,
    console_job_name,
    knowledge_hub_vault_name,
)

from . import PINNED_KEYCLOAK_IMAGE  # noqa: F401
from .test_console_config import _console_data

HUB_IMAGE = "ghcr.io/uw-ssec/okf-hub:1.0@sha256:" + "d" * 64


def _hub_data(**hub) -> dict:
    data = _console_data()
    data["knowledge_hub"] = {"enabled": True, "image": HUB_IMAGE, **hub}
    return data


def test_the_hub_is_off_by_default():
    assert LLMavenConfig.model_validate(_console_data()).knowledge_hub.enabled is False


def test_on_with_pinned_image_validates():
    assert LLMavenConfig.model_validate(_hub_data()).knowledge_hub.enabled is True


def test_on_without_the_console_is_refused():
    data = _hub_data()
    data["console"]["enabled"] = False
    with pytest.raises(ValidationError, match=r"console\.enabled"):
        LLMavenConfig.model_validate(data)


def test_on_without_keycloak_is_refused():
    data = _hub_data()
    data["keycloak"]["enabled"] = False
    data["litellm"]["login"] = {"enabled": False}
    data["console"]["enabled"] = False
    data["knowledge_hub"]["enabled"] = True
    with pytest.raises(ValidationError, match=r"keycloak\.enabled"):
        LLMavenConfig.model_validate(data)


def test_on_with_a_moving_tag_is_refused():
    data = _hub_data(image="ghcr.io/uw-ssec/okf-hub:latest")
    with pytest.raises(ValidationError, match=r"knowledge_hub\.image.*sha256"):
        LLMavenConfig.model_validate(data)


def test_the_vault_name_fits():
    name = knowledge_hub_vault_name("llmaven", "staging")
    assert len(name) <= 24
    assert name.startswith("kv-llmaven-staging-")


def test_the_job_name_fits():
    name = console_job_name("llmaven", "staging", "know")
    assert len(name) <= CONTAINER_APP_NAME_MAX
