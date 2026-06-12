"""Tests for the configuration loader, focused on update_config_fields().

These tests verify the ruamel.yaml round-trip behavior introduced for
https://github.com/uw-ssec/llmaven/issues/95: programmatic field updates must
preserve comments, blank lines, key ordering, and inline annotations.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from llmaven.infrastructure.config.loader import (
    ConfigLoadError,
    update_config_fields,
)


# Mirrors the structure and comment style of the real generated template
# (get_config_template_yaml): top-level sections, inline comments, `null`
# placeholders that deployment fills in, and list values.
SAMPLE_CONFIG = """\
# llmaven-config.yaml
# Top-of-file banner comment

# Project Information
project:
  name: llmaven
  environment: dev  # dev, staging, prod
  location: eastus  # Azure region
  pulumi_state_store: null  # Azure Storage account (auto-generated)

# Azure Subscription
azure:
  subscription_id: ""  # required
  resource_group: null  # Resource group name (auto-generated)

# Database Configuration
database:
  sku_name: B_Standard_B1ms  # tier
  databases:
    - llmaven
    - mlflow_db

# Deeply nested section for path tests
outer:
  inner:
    leaf: original  # keep this comment
"""


def _write(tmp_path: Path, content: str) -> Path:
    config_path = tmp_path / "llmaven-config.yaml"
    config_path.write_text(content)
    return config_path


def test_updates_nested_field_and_preserves_inline_comment(tmp_path):
    config_path = _write(tmp_path, SAMPLE_CONFIG)

    update_config_fields(
        config_path,
        {"azure.resource_group": "rg-llmaven-westus"},
    )

    result = config_path.read_text()
    # Value updated
    assert "resource_group: rg-llmaven-westus" in result
    # Inline comment preserved
    assert "# Resource group name (auto-generated)" in result
    # null replaced, not duplicated
    assert "resource_group: null" not in result


def test_updates_null_field_to_value(tmp_path):
    config_path = _write(tmp_path, SAMPLE_CONFIG)

    update_config_fields(
        config_path,
        {"project.pulumi_state_store": "pulumistate01"},
    )

    result = config_path.read_text()
    assert "pulumi_state_store: pulumistate01" in result
    assert "# Azure Storage account (auto-generated)" in result


def test_preserves_unrelated_comments_and_blank_lines(tmp_path):
    config_path = _write(tmp_path, SAMPLE_CONFIG)

    update_config_fields(
        config_path,
        {"azure.resource_group": "rg-x"},
    )

    result = config_path.read_text()
    # Banner and section comments untouched
    assert "# Top-of-file banner comment" in result
    assert "# Project Information" in result
    assert "# Azure Subscription" in result
    # Untouched fields remain
    assert "name: llmaven" in result
    assert "environment: dev  # dev, staging, prod" in result


def test_updates_deeply_nested_path(tmp_path):
    config_path = _write(tmp_path, SAMPLE_CONFIG)

    update_config_fields(config_path, {"outer.inner.leaf": "changed"})

    result = config_path.read_text()
    # Value updated and the inline comment is preserved (ruamel keeps the
    # comment at its original column, so spacing may differ — assert separately).
    assert "leaf: changed" in result
    assert "# keep this comment" in result


def test_applies_multiple_updates_at_once(tmp_path):
    config_path = _write(tmp_path, SAMPLE_CONFIG)

    update_config_fields(
        config_path,
        {
            "azure.resource_group": "rg-multi",
            "project.pulumi_state_store": "store-multi",
        },
    )

    result = config_path.read_text()
    assert "resource_group: rg-multi" in result
    assert "pulumi_state_store: store-multi" in result


def test_string_null_maps_to_yaml_null(tmp_path):
    config_path = _write(tmp_path, SAMPLE_CONFIG)

    # Start from a value, then set it back to null via the "null" string.
    update_config_fields(config_path, {"azure.resource_group": "temp"})
    update_config_fields(config_path, {"azure.resource_group": "null"})

    result = config_path.read_text()
    assert "resource_group: null" in result


def test_missing_field_raises_and_does_not_write(tmp_path):
    config_path = _write(tmp_path, SAMPLE_CONFIG)
    before = config_path.read_text()

    with pytest.raises(ConfigLoadError) as exc:
        update_config_fields(
            config_path,
            {
                "azure.resource_group": "rg-ok",
                "azure.does_not_exist": "nope",
            },
        )

    # The missing path is reported.
    assert "azure.does_not_exist" in str(exc.value)
    # The file is left untouched (atomic: no partial write on error).
    assert config_path.read_text() == before


def test_missing_intermediate_key_raises(tmp_path):
    config_path = _write(tmp_path, SAMPLE_CONFIG)

    with pytest.raises(ConfigLoadError) as exc:
        update_config_fields(config_path, {"nonexistent.child": "x"})

    assert "nonexistent.child" in str(exc.value)


def test_missing_file_raises(tmp_path):
    with pytest.raises(ConfigLoadError) as exc:
        update_config_fields(tmp_path / "nope.yaml", {"a.b": "c"})

    assert "not found" in str(exc.value)


def test_empty_file_raises(tmp_path):
    config_path = _write(tmp_path, "")

    with pytest.raises(ConfigLoadError) as exc:
        update_config_fields(config_path, {"a.b": "c"})

    assert "empty" in str(exc.value).lower()


def test_deploy_caller_scenario_preserves_comments_and_lists(tmp_path):
    """Mirror the real deploy.py caller: write both backend fields at once."""
    config_path = _write(tmp_path, SAMPLE_CONFIG)

    update_config_fields(
        config_path,
        {
            "azure.resource_group": "rg-llmaven-dev",
            "project.pulumi_state_store": "llmavenstate",
        },
    )

    result = config_path.read_text()
    assert "resource_group: rg-llmaven-dev" in result
    assert "pulumi_state_store: llmavenstate" in result
    # Representative inline comments survive.
    assert "# Azure region" in result
    assert "dev, staging, prod" in result
    # List values are preserved verbatim.
    assert "- llmaven" in result
    assert "- mlflow_db" in result


def test_untouched_null_fields_stay_null(tmp_path):
    """Updating one field must not rewrite other `null` lines to empty scalars."""
    config_path = _write(tmp_path, SAMPLE_CONFIG)

    # Only update resource_group; pulumi_state_store stays null.
    update_config_fields(config_path, {"azure.resource_group": "rg-x"})

    result = config_path.read_text()
    # The untouched null line is rendered as explicit `null`, not blank.
    assert "pulumi_state_store: null  # Azure Storage account (auto-generated)" in result
