"""CI builds and publishes the console image beside the other service images."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "build-services.yml"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _services() -> dict[str, dict]:
    matrix = _workflow()["jobs"]["build-images"]["strategy"]["matrix"]["service"]
    return {s["name"]: s for s in matrix}


def _step(prefix: str) -> dict:
    steps = _workflow()["jobs"]["build-images"]["steps"]
    return next(s for s in steps if str(s.get("name", "")).startswith(prefix))


def test_console_entry_builds_the_app_stage():
    console = _services()["console"]
    assert console["context"] == "./services/console"
    assert console["file"] == "./services/console/Dockerfile"
    assert console["target"] == "app"
    assert console["platforms"] == "linux/amd64"


def test_existing_entries_resolve_to_the_same_dockerfiles():
    services = _services()
    for name, dockerfile in {
        "mlflow": "mlflow.dockerfile",
        "litellm": "litellm.dockerfile",
        "backup": "backup.dockerfile",
        "keycloak": "keycloak.dockerfile",
    }.items():
        assert services[name]["file"] == f"./docker/dockerfiles/{dockerfile}"
        assert "target" not in services[name]


def test_build_step_reads_file_and_target_from_the_matrix():
    with_ = _step("Build and push")["with"]
    assert with_["file"] == "${{ matrix.service.file }}"
    assert with_["target"] == "${{ matrix.service.target }}"


def test_builder_cache_key_does_not_assume_docker_dockerfiles():
    with_ = _step("Setup Blacksmith Builder")["with"]
    assert with_["cache-key"] == "${{ matrix.service.file }}"


def test_console_sources_trigger_a_build():
    on = _workflow()[True]  # YAML 1.1 parses the key `on` as True
    assert "services/console/**" in on["push"]["paths"]
