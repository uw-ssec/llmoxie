"""Startup probes check each app's own health route."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from llmaven.infrastructure.resources import container_apps, helpers


def _startup_probe(create, **kwargs):
    """Run an app helper and return its main container's Startup probe."""
    with (
        patch.object(
            container_apps.azure_native.app,
            "ContainerApp",
            return_value=SimpleNamespace(name="app", configuration=Mock()),
        ) as create_app,
        patch.object(container_apps.pulumi, "export"),
    ):
        create(
            resource_group_name="rg",
            location="westus2",
            container_env_id="env-id",
            image="example.test/app:1",
            cpu=0.5,
            memory="1Gi",
            min_replicas=1,
            max_replicas=2,
            env_vars={},
            key_vault=SimpleNamespace(properties=SimpleNamespace(vault_uri=Mock())),
            key_vault_secret_refs={},
            **kwargs,
        )
    [startup] = [
        p
        for p in create_app.call_args.kwargs["template"].containers[0].probes
        if p.type == "Startup"
    ]
    return startup


def test_mlflow_startup_probe_uses_mlflow_health_route():
    # MLflow has no /health/liveliness; probing it returns 404 and the
    # replica never becomes ready.
    startup = _startup_probe(
        helpers.create_mlflow_app, name="llmaven-dev-mlflow", port=5000
    )

    assert startup.http_get.path == "/health"
    assert startup.http_get.port == 5000


def test_litellm_startup_probe_is_unchanged_without_proxy():
    startup = _startup_probe(
        helpers.create_litellm_app,
        name="llmaven-dev-litellm",
        port=4000,
        container_env_name="env",
        config_file=None,
    )

    assert startup.http_get.path == "/health/liveliness"
    assert startup.http_get.port == 4000
    assert startup.failure_threshold == 30
