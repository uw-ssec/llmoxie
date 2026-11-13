"""The Keycloak image is pinned, optimized for Postgres, and built in CI."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "docker" / "dockerfiles" / "keycloak.dockerfile"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "build-services.yml"


def test_keycloak_base_is_pinned_by_digest():
    first_from = next(
        line
        for line in DOCKERFILE.read_text().splitlines()
        if line.startswith("FROM ")
    )
    assert re.search(
        r"quay\.io/keycloak/keycloak:26\.\d+\.\d+@sha256:[0-9a-f]{64}", first_from
    )


def test_keycloak_is_built_for_postgres_with_health():
    text = DOCKERFILE.read_text()
    for needle in (
        "kc.sh build",
        "--db=postgres",
        "--health-enabled=true",
        "--metrics-enabled=true",
    ):
        assert needle in text


def test_workflow_builds_keycloak():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    services = workflow["jobs"]["build-images"]["strategy"]["matrix"]["service"]
    assert any(
        s["name"] == "keycloak" and s["dockerfile"] == "keycloak.dockerfile"
        for s in services
    )
