"""Regression tests for default construction of LLMavenConfig.

Covers https://github.com/uw-ssec/llmaven/issues/140: LLMavenConfig used
``default_factory=BackupJobConfig`` while ``BackupJobConfig.database`` had no
default, so any LLMavenConfig() without an explicit backup_job raised — which
broke ``llmaven infra init`` (via get_config_template_yaml).
"""

from __future__ import annotations

import pytest

from llmaven.infrastructure.config.defaults import (
    generate_default_config,
    get_config_template_yaml,
)
from llmaven.infrastructure.config.schema import (
    BackupJobConfig,
    DatabaseConfig,
    LLMavenConfig,
)


def test_backup_job_config_constructs_with_no_args():
    job = BackupJobConfig()
    assert job.enabled is False
    assert job.database == "llmaven"


def test_llmaven_config_constructs_with_defaults():
    config = LLMavenConfig()
    # The default backup job is present and disabled.
    assert config.backup_job.enabled is False
    assert config.backup_job.database == "llmaven"


def test_default_backup_database_is_a_valid_default_database():
    """If backups are enabled without changing the database, validation passes."""
    assert BackupJobConfig().database in DatabaseConfig().databases


@pytest.mark.parametrize("environment", ["dev", "staging", "prod"])
def test_generate_default_config_succeeds(environment):
    config = generate_default_config(environment)
    assert config.backup_job.database == "llmaven"


@pytest.mark.parametrize("environment", ["dev", "staging", "prod"])
def test_get_config_template_yaml_succeeds(environment):
    # This is the `llmaven infra init` code path; it must not raise.
    template = get_config_template_yaml(environment)
    assert isinstance(template, str)
    assert "project:" in template


def test_enabling_backup_with_default_database_passes_validation():
    config = LLMavenConfig(backup_job=BackupJobConfig(enabled=True))
    assert config.backup_job.enabled is True


def test_validator_still_rejects_enabled_with_unknown_database():
    """The fix must not weaken the existing cross-field validation."""
    with pytest.raises(Exception) as exc:
        LLMavenConfig(
            backup_job=BackupJobConfig(enabled=True, database="not_a_real_db")
        )
    assert "not_a_real_db" in str(exc.value)
