"""Guard the platform-only scope of the llmaven CLI after the RAG sunset.

The REST API server, Streamlit UI and agentic RAG system moved to
uw-ssec/llmoxie-rag. These tests fail if any of those surfaces come back.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from pathlib import Path

import pytest
import typer
import yaml
from typer.testing import CliRunner

from llmaven.cli import app
from llmaven.infrastructure.config.schema import StorageConfig

ROOT = Path(__file__).resolve().parents[1]

BANNED_PACKAGES = {
    "pydantic-ai",
    "fastembed",
    "docling",
    "fastapi",
    "uvicorn",
    "gunicorn",
    "streamlit",
    "qdrant-client",
    "sentence-transformers",
    "nltk",
    "arxiv",
    "pymupdf",
    "transformers",
    "accelerate",
    "bitsandbytes",
    "pydantic-settings",
    "pytest-asyncio",
    "testcontainers",
    "llama-cpp-python",
    "panel",
    "jupyterlab",
}


@pytest.fixture
def runner() -> CliRunner:
    """Return a Typer CLI runner."""
    return CliRunner()


@pytest.mark.parametrize("argv", [["server", "serve"], ["server", "ui"]])
def test_server_commands_removed(runner: CliRunner, argv: list[str]) -> None:
    result = runner.invoke(app, argv)
    assert result.exit_code == 2
    assert "No such command" in result.output


@pytest.mark.parametrize(
    "module",
    [
        "llmaven.main",
        "llmaven.config",
        "llmaven.v1",
        "llmaven.services",
        "llmaven.schemas",
        "llmaven.core",
        "llmaven.frontend",
    ],
)
def test_api_modules_removed(module: str) -> None:
    assert importlib.util.find_spec(module) is None


@pytest.mark.parametrize("cmd", ["ingest", "search", "chat"])
def test_agentic_commands_removed(runner: CliRunner, cmd: str) -> None:
    result = runner.invoke(app, ["agentic", cmd])
    assert result.exit_code == 2
    assert "No such command" in result.output


def test_agentic_package_removed() -> None:
    assert importlib.util.find_spec("llmaven.agentic") is None


def test_cli_exposes_only_platform_commands() -> None:
    assert set(typer.main.get_command(app).commands) == {
        "infra",
        "backup-infra",
        "version",
    }


def test_cli_import_does_not_load_rag_modules() -> None:
    banned = {
        "qdrant_client",
        "fastembed",
        "docling",
        "pydantic_ai",
        "langchain",
        "fastapi",
        "streamlit",
        "transformers",
        "torch",
    }
    code = (
        "import sys, llmaven.cli; "
        f"print(sorted({{m.split('.')[0] for m in sys.modules}} & {banned!r}))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "[]"


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_name(requirement: str) -> str:
    return _normalize(re.match(r"[A-Za-z0-9._-]+", requirement.strip()).group())


def _pyproject_packages() -> Iterator[tuple[str, str]]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    for requirement in project["dependencies"]:
        yield "dependencies", _requirement_name(requirement)
    for extra, requirements in project.get("optional-dependencies", {}).items():
        for requirement in requirements:
            yield f"optional-dependencies.{extra}", _requirement_name(requirement)


def _pixi_tables(table: dict, where: str) -> Iterator[tuple[str, str]]:
    for key in ("dependencies", "pypi-dependencies"):
        for name in table.get(key, {}):
            yield f"{where}{key}", _normalize(name)
    for target, target_table in table.get("target", {}).items():
        yield from _pixi_tables(target_table, f"{where}target.{target}.")


def _pixi_packages() -> Iterator[tuple[str, str]]:
    manifest = tomllib.loads((ROOT / "pixi.toml").read_text())
    yield from _pixi_tables(manifest, "")
    for feature, table in manifest.get("feature", {}).items():
        yield from _pixi_tables(table, f"feature.{feature}.")


def _is_banned(name: str) -> bool:
    return name in BANNED_PACKAGES or name.startswith("langchain")


@pytest.mark.parametrize(
    ("manifest", "packages"),
    [("pyproject.toml", _pyproject_packages), ("pixi.toml", _pixi_packages)],
)
def test_manifests_declare_no_rag_packages(manifest, packages) -> None:
    found = sorted(f"{where}: {name}" for where, name in packages() if _is_banned(name))
    assert found == [], f"{manifest} still declares RAG/ML packages"


def test_pixi_has_no_rag_environments_or_tasks() -> None:
    manifest = tomllib.loads((ROOT / "pixi.toml").read_text())
    assert "frontend" not in manifest.get("environments", {})
    tasks = set(manifest.get("tasks", {}))
    for table in manifest.get("feature", {}).values():
        tasks |= set(table.get("tasks", {}))
    assert tasks.isdisjoint({"serve-panel", "start-jlab", "api-server", "ui"})


def test_compose_runs_only_platform_services() -> None:
    compose = yaml.safe_load((ROOT / "docker" / "docker-compose.yml").read_text())
    assert set(compose["services"]) == {
        "db",
        "mlflow",
        "azurite",
        "litellm",
    }


def test_storage_keeps_llmaven_container() -> None:
    # Removing a container from the config deletes its blob data on the next
    # `llmaven infra deploy`, so the llmaven container must stay.
    assert StorageConfig().containers == ["mlflow", "llmaven", "litellm-logs"]
